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
MAX_MESSAGES = 40          # cap conversation length forwarded upstream
MAX_CHARS = 20000          # per-message guard

router = APIRouter()


def _build_system_prompt() -> str:
    """Assemble system_prompt.txt with the two KB docs inlined — identical to
    journey-planner/planner.py. Read fresh each call so doc edits take effect
    without a restart. Raises FileNotFoundError if the docs are missing."""
    tpl = (PLANNER_DIR / "system_prompt.txt").read_text(encoding="utf-8")
    kb = (PLANNER_DIR / "REA_KNOWLEDGE_BASE.md").read_text(encoding="utf-8")
    backlog = (PLANNER_DIR / "REA_CAPTURE_BACKLOG_CHECKLIST.md").read_text(encoding="utf-8")
    corr_file = PLANNER_DIR / "corrections.md"
    corrections = corr_file.read_text(encoding="utf-8") if corr_file.exists() else ""
    return (
        tpl
        .replace("<KNOWLEDGE_BASE>\n</KNOWLEDGE_BASE>", kb)
        .replace("<CAPTURE_BACKLOG>\n</CAPTURE_BACKLOG>", backlog)
        .replace("<CORRECTIONS>\n</CORRECTIONS>", corrections)
    )


@router.get("/admin/planner", response_class=HTMLResponse)
def planner_page(
    request: Request,
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "planner/index.html",
        {
            "active_page": "planner",
            "current_user": user,
            "model": settings.gemini_model,
            "key_configured": bool(settings.gemini_api_key.strip()),
            "docs_present": (PLANNER_DIR / "system_prompt.txt").exists(),
        },
    )


@router.post("/admin/planner/api")
async def planner_api(
    request: Request,
    user: User = Depends(require_role("editor")),
) -> JSONResponse:
    settings = get_settings()
    key = settings.gemini_api_key.strip()
    if not key:
        return JSONResponse(
            {"error": "Gemini key not configured. Set GEMINI_API_KEY in the .env "
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

    contents = []
    for m in messages[-MAX_MESSAGES:]:
        role = "model" if m.get("role") == "model" else "user"
        text = str(m.get("text", ""))[:MAX_CHARS]
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})
    if not contents:
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

    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 8192,
            # Disable (or cap) 2.5-flash "thinking" — biggest cost lever.
            "thinkingConfig": {"thinkingBudget": settings.gemini_thinking_budget},
        },
    }
    url = GEMINI_URL.format(model=settings.gemini_model)

    try:
        r = requests.post(url, params={"key": key}, json=body, timeout=120)
    except requests.RequestException as exc:
        logger.warning("gemini request failed: %s", exc)
        return JSONResponse({"error": f"Upstream request failed: {exc}"}, status_code=200)

    if r.status_code != 200:
        detail = ""
        try:
            detail = r.json().get("error", {}).get("message", "")
        except Exception:
            detail = r.text[:300]
        logger.warning("gemini %s: %s", r.status_code, detail)
        return JSONResponse(
            {"error": f"Gemini error {r.status_code}: {detail}"}, status_code=200
        )

    data = r.json()
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()

    finish = cand.get("finishReason")
    block = (data.get("promptFeedback") or {}).get("blockReason")
    if block:
        return JSONResponse({"error": f"Response blocked: {block}"}, status_code=200)
    if not text:
        return JSONResponse(
            {"error": f"Empty response (finishReason: {finish})."}, status_code=200
        )
    if finish and finish != "STOP":
        text += f"\n\n[finishReason: {finish}]"

    return JSONResponse({"text": text})
