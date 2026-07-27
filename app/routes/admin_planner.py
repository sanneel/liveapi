"""
REA Journey Planner — in-backoffice chat.

  GET  /admin/planner         redirects to the Optimization page's Planner tab
                              (/admin/promotions?tab=planner), where the chat
                              widget actually lives (partials/_planner_panel.html)
  POST /admin/planner/api     Gemini proxy — assembles the system prompt from the
                              journey-planner docs and forwards the conversation

The Gemini key lives in Settings (server-side) and is never sent to the browser.
The system prompt is assembled from journey-planner/system_prompt.txt plus the
two knowledge-base docs exactly the way journey-planner/planner.py does, so the
CLI and the backoffice chat always agree — edit the docs, not this file.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..auth.dependencies import require_role
from ..config import get_settings
from ..logging_config import get_logger
from ..models import User

logger = get_logger("app.routes.admin_planner")

BASE_DIR = Path(__file__).resolve().parent.parent          # app/
REPO_ROOT = BASE_DIR.parent                                # repo root
PLANNER_DIR = REPO_ROOT / "journey-planner"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_MESSAGES = 40          # cap conversation length forwarded upstream
# Composer refusals are precise and single-edit, so one or two automatic repair
# rounds convert most of them into a script. Beyond that the model tends to
# rewrite the journey rather than fix the field, so the operator should see it.
MAX_COMPOSE_REPAIRS = 2
MAX_CHARS = 20000          # per-message guard

router = APIRouter()


# Upstream statuses worth retrying: rate limit and the transient 5xx family.
# Gemini returns 503 "experiencing high demand" routinely under load, and a
# single one used to surface to the operator as a hard failure — during a
# measured 8-brief run it killed two otherwise-recoverable auto-repairs.
RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.5, 4.0)


def _with_retry(call, *args):
    """Retry a provider call on transient upstream errors.

    `call` returns (text, error) and never raises; a retryable failure is
    detected from the error string it produced, which is why the callers embed
    the status code there. Non-retryable errors (a bad key, a safety block, a
    malformed request) return immediately — retrying those just burns time.
    """
    last = (None, "no attempt made")
    for attempt in range(RETRY_ATTEMPTS):
        text, error = call(*args)
        if not error:
            return text, None
        last = (text, error)
        if not any(f" {code}:" in error for code in RETRY_STATUSES):
            return last
        if attempt == RETRY_ATTEMPTS - 1:
            break
        delay = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
        logger.info("upstream transient error (%s) — retrying in %.1fs", error[:80], delay)
        time.sleep(delay)
    return last


def _resolve_provider(settings) -> str:
    """Pick the planner LLM. Explicit planner_provider ("groq"|"gemini") always
    wins. Otherwise prefer GEMINI — it handles the full ~17K prompt with no
    per-minute token wall; Groq's free tier can't (12K TPM), so Groq is opt-in
    (set PLANNER_PROVIDER=groq, ideally on Dev tier). Fall back to whichever key
    exists."""
    p = (settings.planner_provider or "").strip().lower()
    if p in ("groq", "gemini"):
        return p
    if settings.gemini_api_key.strip():
        return "gemini"
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
        "max_tokens": settings.planner_max_tokens,
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
    gen_config = {
        "temperature": temperature,
        "maxOutputTokens": settings.planner_max_tokens,
    }
    # thinkingConfig is only valid on models that support "thinking" (2.5 flash/
    # pro). flash-lite rejects it → HTTP 400 invalid argument. Only send it when
    # a positive budget is set (i.e. you explicitly want to cap thinking); a 0/
    # unset budget just omits it (flash-lite doesn't think by default anyway).
    if settings.gemini_thinking_budget and settings.gemini_thinking_budget > 0:
        gen_config["thinkingConfig"] = {"thinkingBudget": settings.gemini_thinking_budget}
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": gen_config,
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


# Lean-prompt stand-ins for the two big reference docs. Groq's free tier caps
# tokens/minute (12K on 70b), and the full KB (~7.7K tok) + backlog (~2.2K)
# blow past it. The operational essentials the planner actually needs to emit
# specs — recipes, games, corrections — stay full; the deep reference is dropped
# with a pointer. Gemini (no such cap) still gets the full docs.
_LEAN_KB = (
    "(Knowledge base omitted to fit this model's token budget. Rely on the "
    "RECIPES CATALOG, GAMES REGISTRY and CORRECTIONS below — they are the "
    "authoritative, up-to-date truth. Do NOT invent activities or recipes not "
    "listed there; if the brief needs something absent, output the ⛔ UNCAPTURED "
    "line.)"
)
_LEAN_BACKLOG = (
    "(Capture backlog omitted. Only build recipes in the RECIPES CATALOG below; "
    "anything else is ⛔ UNCAPTURED.)"
)


def _build_system_prompt(lean: bool = False) -> str:
    """Assemble system_prompt.txt with the KB docs inlined — identical to
    journey-planner/planner.py. Read fresh each call so doc edits take effect
    without a restart. When lean=True, the two big reference docs are replaced
    with short pointers (for token-capped providers like Groq free tier); the
    recipes/games/corrections — what specs are actually built from — stay full.
    Raises FileNotFoundError if the docs are missing."""
    tpl = (PLANNER_DIR / "system_prompt.txt").read_text(encoding="utf-8")
    if lean:
        kb, backlog = _LEAN_KB, _LEAN_BACKLOG
    else:
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


def planner_view_context() -> dict:
    """State the Planner tab partial needs — shared by the (now-redirecting)
    standalone page and the Optimization page's Planner tab."""
    settings = get_settings()
    provider = _resolve_provider(settings)
    model = settings.groq_model if provider == "groq" else settings.gemini_model
    key_ok = bool((settings.groq_api_key if provider == "groq"
                   else settings.gemini_api_key).strip())
    return {
        "model": f"{provider}:{model}",
        "provider": provider,
        "key_env": "GROQ_API_KEY" if provider == "groq" else "GEMINI_API_KEY",
        "key_configured": key_ok,
        "docs_present": (PLANNER_DIR / "system_prompt.txt").exists(),
    }


@router.get("/admin/planner")
def planner_page(
    request: Request,
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    """Planner moved into the Optimization hub as a tab — keep the old URL
    working for bookmarks/links instead of 404ing."""
    return RedirectResponse(url="/admin/promotions?tab=planner", status_code=307)


def _detect_mode(text: str, fallback: str) -> str:
    """Pick the engine from the spec's own keys.

    The browser guesses with a regex, which misroutes often enough to matter (a
    chain spec sent to --spec dies as "unknown recipe None"). Parsing the object
    here is deterministic: `reference` means a MODE 4 graph, `chain` a MODE 5
    chain, `recipe` a MODE 3 spec. Falls back to the caller's mode when nothing
    parses — the composer then produces its own clean refusal.
    """
    blob = text.strip()
    fences = re.findall(r"```(?:json|JSON)?\s*(.*?)```", blob, re.S)
    candidates = [*reversed([f.strip() for f in fences]), blob]
    # ...and the first balanced {...}, which is what a "Here is the spec:"
    # lead-in leaves behind. Same three-way fallback as compose._extract_json.
    depth, start = 0, None
    for i, ch in enumerate(blob):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(blob[start:i + 1])
                break
    for candidate in candidates:
        try:
            spec = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(spec, dict):
            continue
        if "kind" in spec and ("date" in spec or "dates" in spec):
            return "randomizer"
        if "reference" in spec:
            return "graph"
        if isinstance(spec.get("chain"), list):
            return "chain"
        if "recipe" in spec:
            return "spec"
    return fallback


def _extract_all_specs(text: str) -> list[dict]:
    """Every JSON object in a reply that looks like a buildable spec.

    A campaign is many objects but a spec builds ONE, so an operator either asks
    per object or gets several specs in one reply. Both are supported: fenced
    blocks first (what the model emits when listing several), else the whole
    reply, else the first balanced {...}."""
    blob = (text or "").strip()
    found: list[dict] = []
    seen: set[str] = set()

    def consider(candidate: str) -> None:
        try:
            spec = json.loads(candidate)
        except ValueError:
            return
        if not isinstance(spec, dict):
            return
        # A spec is identifiable by the key that selects its engine.
        if not ({"recipe", "chain", "reference", "kind"} & set(spec)):
            return
        fingerprint = json.dumps(spec, sort_keys=True)
        if fingerprint not in seen:
            seen.add(fingerprint)
            found.append(spec)

    for fence in re.findall(r"```(?:json|JSON)?\s*(.*?)```", blob, re.S):
        consider(fence.strip())
    if not found:
        consider(blob)
    if not found:
        depth, start = 0, None
        for i, ch in enumerate(blob):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}" and depth:
                depth -= 1
                if depth == 0 and start is not None:
                    consider(blob[start:i + 1])
                    start = None
    return found


def _spec_mode(spec: dict) -> str:
    """Which engine builds this spec, from its own keys."""
    if "kind" in spec and ("date" in spec or "dates" in spec):
        return "randomizer"
    if "reference" in spec:
        return "graph"
    if isinstance(spec.get("chain"), list):
        return "chain"
    return "spec"


def _repair_spec(settings, spec_text: str, refusal: str, mode: str) -> str | None:
    """Ask the planner to fix a spec the composer refused. Returns the corrected
    reply, or None if the model could not be reached.

    Kept deliberately narrow: the model is given the spec, the exact refusal and
    one instruction — change only what the refusal names. A free-form "try
    again" tends to produce a different journey rather than the same journey
    with the error fixed."""
    instruction = (
        f"The composer REFUSED this {mode} spec. Fix ONLY what the refusal names "
        f"and re-emit the corrected JSON object — no prose, no explanation, no "
        f"other changes to the journey.\n\n"
        f"--- SPEC ---\n{spec_text}\n\n--- REFUSAL ---\n{refusal.strip()[:4000]}\n"
    )
    try:
        provider = _resolve_provider(settings)
        system_prompt = _build_system_prompt(lean=(provider == "groq"))
        caller = _call_groq if provider == "groq" else _call_gemini
        text, error = _with_retry(caller, settings, system_prompt,
                                  [{"role": "user", "text": instruction}], 0.0)
    except Exception as exc:
        logger.warning("spec repair call failed: %s", exc)
        return None
    if error or not text:
        logger.warning("spec repair unavailable: %s", error)
        return None
    return text


@router.post("/admin/planner/compose")
def planner_compose(
    payload: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> JSONResponse:
    """Run the composer over a planner reply and hand back the console script.

    Deliberately a sync `def`: FastAPI runs it in the threadpool, so the
    subprocess (up to 300s) cannot stall the event loop the way an `async def`
    calling blocking code would — the service runs a single uvicorn worker.

    The reply is passed through verbatim; compose.py tolerates ```json fences
    and prose lead-ins. A refusal is not an error here — returncode 3 with the
    explanation in `log` is the composer working as designed, and the operator
    can paste that text back into the chat for the planner to correct itself.
    """
    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "Nothing to compose — send the planner reply."})
    if len(text) > MAX_CHARS:
        return JSONResponse({"error": f"Reply too large ({len(text)} chars, max {MAX_CHARS})."})
    mode = str(payload.get("mode") or "spec").strip().lower()
    if mode not in ("spec", "graph", "chain", "randomizer"):
        return JSONResponse(
            {"error": f"Unknown mode {mode!r} — use 'spec', 'graph', 'chain' "
                      f"or 'randomizer'."})

    try:
        from ..services.journey_cloner_runner import generate_composed_console_script
    except ImportError as exc:
        return JSONResponse({"error": f"Composer not available: {exc}"})

    settings = get_settings()

    # A campaign is many objects; a spec builds one. Build every spec present so
    # a reply listing several journeys produces several scripts in one click.
    specs = _extract_all_specs(text)
    if not specs:
        return JSONResponse({
            "error": "That reply is a plan, not a spec — there is no buildable "
                     "JSON object in it. Ask for one object at a time: say "
                     "\"journey 2 in full\", then \"generate json\". For the "
                     "whole campaign, ask for \"the spec JSON for every "
                     "journey, one JSON block each\"."})
    if len(specs) > 1:
        results = []
        for i, spec in enumerate(specs, 1):
            spec_mode = _spec_mode(spec)
            try:
                code, log, cmd, js, filename = generate_composed_console_script(
                    json.dumps(spec), mode=spec_mode)
            except Exception as exc:
                logger.warning("planner compose failed on spec %d: %s", i, exc)
                code, log, js, filename = 1, f"Composer failed to run: {exc}", None, ""
            results.append({
                "index": i,
                "name": spec.get("journey_name") or spec.get("name") or f"object {i}",
                "mode": spec_mode, "ok": code == 0 and bool(js),
                "returncode": code, "log": log, "js": js, "filename": filename,
            })
        built = sum(1 for r in results if r["ok"])
        return JSONResponse({"ok": built > 0, "multi": True, "built": built,
                             "total": len(results), "results": results})

    # Single spec: the mode comes from the spec itself, not the browser's guess.
    mode = _spec_mode(specs[0])
    attempts: list[dict] = []
    current = text
    # Every refusal the composer emits names the offending field and says how to
    # fix it, so a refusal is a repair instruction the model can act on. The
    # common failures — minor-vs-major units, a game tuple from two different
    # games, a knob the chosen recipe lacks — are all one-edit fixes that the
    # model gets right when told. Retrying here is the difference between "the
    # tool refused" and "the tool produced a script".
    for attempt in range(1 + MAX_COMPOSE_REPAIRS):
        try:
            code, log, cmd, js, filename = generate_composed_console_script(current, mode=mode)
        except Exception as exc:                  # subprocess timeout, OSError, ...
            logger.warning("planner compose failed: %s", exc)
            return JSONResponse({"error": f"Composer failed to run: {exc}"})
        attempts.append({"attempt": attempt + 1, "returncode": code, "log": log})
        if code == 0 and js:
            return JSONResponse({"ok": True, "returncode": 0, "log": log, "cmd": cmd,
                                 "js": js, "filename": filename,
                                 "attempts": attempts, "repaired": attempt > 0})
        if attempt >= MAX_COMPOSE_REPAIRS:
            break
        repaired = _repair_spec(settings, current, log, mode)
        if not repaired:
            break
        logger.info("planner compose refused (exit %s) — retrying with a repair", code)
        current = repaired

    logger.info("planner compose refused after %d attempt(s)", len(attempts))
    return JSONResponse({"ok": False, "returncode": attempts[-1]["returncode"],
                         "log": attempts[-1]["log"], "cmd": cmd,
                         "attempts": attempts})


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

    # Groq's free tier is token-capped → send it the lean prompt (drops the big
    # reference docs, keeps recipes/games/corrections). Gemini gets the full one.
    try:
        system_prompt = _build_system_prompt(lean=(provider == "groq"))
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"Planner docs not found under {PLANNER_DIR}. "
                      "Make sure the journey-planner/ folder is deployed."},
            status_code=200,
        )

    caller = _call_groq if provider == "groq" else _call_gemini
    text, error = _with_retry(caller, settings, system_prompt, messages, temperature)

    if error:
        return JSONResponse({"error": error}, status_code=200)
    return JSONResponse({"text": text})
