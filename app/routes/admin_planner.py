"""
REA Journey Planner — in-backoffice chat.

  GET  /admin/planner        chat page (editor+)
  POST /admin/planner/api     Gemini proxy — assembles the system prompt from the
                              journey-planner docs and forwards the conversation

The Gemini key lives in Settings (server-side) and is never sent to the browser.
The system prompt is assembled from journey-planner/system_prompt.txt plus the
two knowledge-base docs exactly the way journey-planner/planner.py does, so the
CLI and the backoffice chat always agree — edit the docs, not this file.
"""

from __future__ import annotations

from pathlib import Path

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth.dependencies import require_role
from ..config import get_settings
from ..logging_config import get_logger
from ..models import User

logger = get_logger("app.routes.admin_planner")

BASE_DIR = Path(__file__).resolve().parent.parent          # app/
REPO_ROOT = BASE_DIR.parent                                # repo root
PLANNER_DIR = REPO_ROOT / "journey-planner"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_MESSAGES = 40          # cap conversation length forwarded upstream
MAX_CHARS = 20000          # per-message guard

router = APIRouter()


def _resolve_provider(settings) -> str:
    """Pick the planner LLM. Explicit planner_provider wins; otherwise prefer
    Groq (free tier, cheapest) when its key is set, else Gemini."""
    p = (settings.planner_provider or "").strip().lower()
    if p in ("groq", "gemini"):
        return p
    if settings.groq_api_key.strip():
        return "groq"
    return "gemini"


def _call_groq(settings, system_prompt: str, messages: list, temperature: float):
    """Groq (OpenAI-compatible). Returns (text, error). Cheapest planner path."""
    chat = [{"role": "system", "content": system_prompt}]
    for m in messages:
        role = "assistant" if m.get("role") == "model" else "user"
        text = str(m.get("text", ""))[:MAX_CHARS]
        if text:
            chat.append({"role": role, "content": text})
    body = {
        "model": settings.groq_model,
        "messages": chat,
        "temperature": temperature,
        "max_tokens": 8192,
    }
    try:
        r = requests.post(
            GROQ_URL, json=body, timeout=120,
            headers={"Authorization": f"Bearer {settings.groq_api_key.strip()}"},
        )
    except requests.RequestException as exc:
        logger.warning("groq request failed: %s", exc)
        return None, f"Upstream request failed: {exc}"
    if r.status_code != 200:
        detail = ""
        try:
            detail = r.json().get("error", {}).get("message", "")
        except Exception:
            detail = r.text[:300]
        logger.warning("groq %s: %s", r.status_code, detail)
        return None, f"Groq error {r.status_code}: {detail}"
    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    finish = choice.get("finish_reason")
    if not text:
        return None, f"Empty response (finish_reason: {finish})."
    if finish and finish not in ("stop", "end_turn"):
        text += f"\n\n[finish_reason: {finish}]"
    return text, None


def _call_gemini(settings, system_prompt: str, messages: list, temperature: float):
    """Gemini (fallback). Returns (text, error)."""
    contents = []
    for m in messages:
        role = "model" if m.get("role") == "model" else "user"
        text = str(m.get("text", ""))[:MAX_CHARS]
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingBudget": settings.gemini_thinking_budget},
        },
    }
    url = GEMINI_URL.format(model=settings.gemini_model)
    try:
        r = requests.post(url, params={"key": settings.gemini_api_key.strip()},
                          json=body, timeout=120)
    except requests.RequestException as exc:
        logger.warning("gemini request failed: %s", exc)
        return None, f"Upstream request failed: {exc}"
    if r.status_code != 200:
        detail = ""
        try:
            detail = r.json().get("error", {}).get("message", "")
        except Exception:
            detail = r.text[:300]
        logger.warning("gemini %s: %s", r.status_code, detail)
        return None, f"Gemini error {r.status_code}: {detail}"
    data = r.json()
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    block = (data.get("promptFeedback") or {}).get("blockReason")
    if block:
        return None, f"Response blocked: {block}"
    finish = cand.get("finishReason")
    if not text:
        return None, f"Empty response (finishReason: {finish})."
    if finish and finish != "STOP":
        text += f"\n\n[finishReason: {finish}]"
    return text, None


def _build_system_prompt() -> str:
    """Assemble system_prompt.txt with the two KB docs inlined — identical to
    journey-planner/planner.py. Read fresh each call so doc edits take effect
    without a restart. Raises FileNotFoundError if the docs are missing."""
    tpl = (PLANNER_DIR / "system_prompt.txt").read_text(encoding="utf-8")
    kb = (PLANNER_DIR / "REA_KNOWLEDGE_BASE.md").read_text(encoding="utf-8")
    backlog = (PLANNER_DIR / "REA_CAPTURE_BACKLOG_CHECKLIST.md").read_text(encoding="utf-8")
    corr_file = PLANNER_DIR / "corrections.md"
    corrections = corr_file.read_text(encoding="utf-8") if corr_file.exists() else ""
    cat_file = REPO_ROOT / "journey-cloner" / "recipes_catalog.json"
    catalog = cat_file.read_text(encoding="utf-8") if cat_file.exists() else "{}"
    # Inject the COMPACT games index (name→ids) to keep the prompt small; the
    # full games.json stays authoritative but is ~5x larger.
    games_index = REPO_ROOT / "journey-cloner" / "library" / "games_index.md"
    games_file = REPO_ROOT / "journey-cloner" / "library" / "games.json"
    if games_index.exists():
        games = games_index.read_text(encoding="utf-8")
    elif games_file.exists():
        games = games_file.read_text(encoding="utf-8")
    else:
        games = "{}"
    return (
        tpl
        .replace("<KNOWLEDGE_BASE>\n</KNOWLEDGE_BASE>", kb)
        .replace("<CAPTURE_BACKLOG>\n</CAPTURE_BACKLOG>", backlog)
        .replace("<RECIPES_CATALOG>\n</RECIPES_CATALOG>", catalog)
        .replace("<GAMES_REGISTRY>\n</GAMES_REGISTRY>", games)
        .replace("<CORRECTIONS>\n</CORRECTIONS>", corrections)
    )


@router.get("/admin/planner", response_class=HTMLResponse)
def planner_page(
    request: Request,
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    settings = get_settings()
    provider = _resolve_provider(settings)
    model = settings.groq_model if provider == "groq" else settings.gemini_model
    key_ok = bool((settings.groq_api_key if provider == "groq"
                   else settings.gemini_api_key).strip())
    return templates.TemplateResponse(
        request,
        "planner/index.html",
        {
            "active_page": "planner",
            "current_user": user,
            "model": f"{provider}:{model}",
            "provider": provider,
            "key_env": "GROQ_API_KEY" if provider == "groq" else "GEMINI_API_KEY",
            "key_configured": key_ok,
            "docs_present": (PLANNER_DIR / "system_prompt.txt").exists(),
        },
    )


@router.post("/admin/planner/api")
async def planner_api(
    request: Request,
    user: User = Depends(require_role("editor")),
) -> JSONResponse:
    settings = get_settings()
    provider = _resolve_provider(settings)
    key = (settings.groq_api_key if provider == "groq" else settings.gemini_api_key).strip()
    if not key:
        env = "GROQ_API_KEY" if provider == "groq" else "GEMINI_API_KEY"
        return JSONResponse(
            {"error": f"{provider.title()} key not configured. Set {env} in the .env "
                      "(or the jugabet service environment) and restart."},
            status_code=200,
        )

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request body."}, status_code=200)

    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return JSONResponse({"error": "No messages."}, status_code=200)
    messages = messages[-MAX_MESSAGES:]
    if not any(str(m.get("text", "")).strip() for m in messages):
        return JSONResponse({"error": "Empty conversation."}, status_code=200)

    try:
        temperature = float(payload.get("temperature", 0.2))
    except (TypeError, ValueError):
        temperature = 0.2
    temperature = min(max(temperature, 0.0), 1.0)

    try:
        system_prompt = _build_system_prompt()
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"Planner docs not found under {PLANNER_DIR}. "
                      "Make sure the journey-planner/ folder is deployed."},
            status_code=200,
        )

    if provider == "groq":
        text, error = _call_groq(settings, system_prompt, messages, temperature)
    else:
        text, error = _call_gemini(settings, system_prompt, messages, temperature)

    if error:
        return JSONResponse({"error": error}, status_code=200)
    return JSONResponse({"text": text})
