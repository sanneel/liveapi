"""
REA Journey Planner — in-backoffice chat.

  GET  /admin/ai              the planner's own page (partials/_planner_panel.html)
  GET  /admin/planner         redirects to /admin/ai (old bookmarks)
  POST /admin/planner/api     Gemini proxy — assembles the system prompt from the
                              journey-planner docs and forwards the conversation

The Gemini key lives in Settings (server-side) and is never sent to the browser.
The system prompt is assembled from journey-planner/system_prompt.txt plus the
two knowledge-base docs exactly the way journey-planner/planner.py does, so the
CLI and the backoffice chat always agree — edit the docs, not this file.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

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
MAX_CHARS = 20000          # per-message guard for what is sent UPSTREAM
# Guard for a reply we only process locally (render boards, compose scripts). A
# continued reply for a 30-journey campaign runs past 90K chars legitimately, so
# the upstream per-message cap is the wrong limit to apply to it.
MAX_ARTIFACT_CHARS = 250_000

router = APIRouter()


# Upstream statuses worth retrying: rate limit and the transient 5xx family.
# Gemini returns 503 "experiencing high demand" routinely under load, and a
# single one used to surface to the operator as a hard failure — during a
# measured 8-brief run it killed two otherwise-recoverable auto-repairs.
RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.5, 4.0)


# Per-request token accounting. Every planner answer can fan out into repair and
# continuation calls, so "what did this campaign cost" is otherwise unknowable.
# A contextvar keeps concurrent requests from mixing their totals.
_USAGE: contextvars.ContextVar[dict] = contextvars.ContextVar("planner_usage")


def _usage_start() -> dict:
    totals = {"calls": 0, "input": 0, "cached": 0, "thought": 0, "answer": 0}
    _USAGE.set(totals)
    return totals


def _usage_add(meta: dict) -> None:
    try:
        totals = _USAGE.get()
    except LookupError:
        return
    totals["calls"] += 1
    totals["input"] += int(meta.get("promptTokenCount") or 0)
    totals["cached"] += int(meta.get("cachedContentTokenCount") or 0)
    totals["thought"] += int(meta.get("thoughtsTokenCount") or 0)
    totals["answer"] += int(meta.get("candidatesTokenCount") or 0)


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


# A reply that hit the output cap carries this marker (added by the callers
# below). A 30-journey plan or its design block genuinely does not fit one
# round, so the planner asks the model to carry on and stitches the pieces.
_TRUNCATED = ("[finishReason: MAX_TOKENS]", "[finish_reason: length]")
MAX_CONTINUATIONS = 4

# Budget for the mechanical calls (fix this knob, emit that block). Measured on
# the Ruletazo workflow, the full 8K-thought budget on these was ~60% of the
# thinking spend and changed nothing about the answers: they are "apply the
# refusal you were just handed", not "plan a campaign". The lean prompt drops the
# knowledge base and capture backlog with them — 23.5K input tokens -> 15.7K.
REPAIR_THINKING = 1024


def _is_truncated(text: str) -> bool:
    return any(marker in (text or "") for marker in _TRUNCATED)


def _strip_markers(text: str) -> str:
    for marker in _TRUNCATED:
        text = text.replace(marker, "")
    return text.rstrip()


def _complete(settings, messages: list, temperature: float, *,
              lean: bool | None = None,
              thinking: int | None = None) -> tuple[str | None, str | None]:
    """One planner answer, continued until it is actually finished.

    The provider stops at `planner_max_tokens`, which a big campaign exceeds: the
    Ruletazo brief (37 journeys) died halfway through its design block, leaving
    unparseable JSON and no boards. Here a truncated reply is continued from
    exactly where it stopped and the parts are concatenated, so callers always
    see one whole answer.
    """
    provider = _resolve_provider(settings)
    if lean is None:
        lean = provider == "groq"
    system_prompt = _build_system_prompt(lean=lean)
    model = None if lean else (settings.gemini_planning_model or None)
    if provider == "groq":
        caller, args = _call_groq, (settings, system_prompt, messages, temperature)
    else:
        caller, args = _call_gemini, (settings, system_prompt, messages, temperature,
                                      thinking, model)

    text, error = _with_retry(caller, *args)
    if error or not text:
        return text, error

    rounds = 0
    while _is_truncated(text) and rounds < MAX_CONTINUATIONS:
        rounds += 1
        so_far = _strip_markers(text)
        # The model sees its own partial answer and is told to resume mid-token —
        # no preamble, no restating, or the stitched result would repeat itself.
        follow = messages + [
            {"role": "model", "text": so_far[-8000:]},
            {"role": "user", "text":
                "Your reply was cut off by the output limit. Continue it from the "
                "EXACT character where it stopped — do not repeat anything already "
                "written, do not restate the outline, do not add a preamble or "
                "explanation, and if you were mid-way through a ```json block, "
                "carry on inside that block and close it properly."},
        ]
        cont_args = ((settings, system_prompt, follow, temperature) if provider == "groq"
                     else (settings, system_prompt, follow, temperature, thinking, model))
        more, more_error = _with_retry(caller, *cont_args)
        if more_error or not more:
            logger.warning("continuation %d unavailable: %s", rounds, more_error)
            return so_far, None
        logger.info("planner reply truncated — continued (round %d, +%d chars)",
                    rounds, len(more))
        if _is_truncated(more):
            text = so_far + more            # marker kept: the loop goes again
        else:
            text = so_far + _strip_markers(more)
    return text, None


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


GEMINI_CACHE_URL = "https://generativelanguage.googleapis.com/v1beta/cachedContents"
# How long a cached system prompt lives server-side. Long enough that a whole
# campaign session (plan -> specs -> repairs -> compose) reuses one entry, short
# enough that an edited corrections.md is picked up soon after. The digest check
# below makes a stale entry impossible anyway — this only bounds the idle cost.
GEMINI_CACHE_TTL_SECONDS = 3600
# Below this the API rejects the cache create, and the saving would not be worth
# a round trip. 2.5 Flash's documented floor is 1024 tokens; ~4 chars/token.
GEMINI_CACHE_MIN_CHARS = 6000
_gemini_cache: dict = {"name": "", "digest": "", "expires": 0.0, "disabled": False}


def _ensure_gemini_cache(settings, system_prompt: str, model: str) -> str:
    """Cache the system prompt server-side and return its handle, or "".

    The system prompt is byte-identical on every call and is ~19K tokens, so
    without this every request re-bills the whole thing at full input price — a
    campaign is a dozen calls. Cached input bills far below fresh input.

    Keyed on a digest of the prompt AND the model, so editing corrections.md or
    switching model silently starts a new entry instead of serving a stale one.

    FAILS OPEN. Any error disables caching for the process and the caller sends
    the prompt inline as before: a planner that still works uncached beats one
    that 500s because a cache create was rejected.
    """
    if _gemini_cache["disabled"] or len(system_prompt) < GEMINI_CACHE_MIN_CHARS:
        return ""
    digest = hashlib.sha256(f"{model}\x00{system_prompt}".encode("utf-8")).hexdigest()
    now = time.time()
    if _gemini_cache["digest"] == digest and _gemini_cache["expires"] > now + 60:
        return _gemini_cache["name"]
    body = {
        "model": f"models/{model}",
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "ttl": f"{GEMINI_CACHE_TTL_SECONDS}s",
    }
    try:
        r = requests.post(GEMINI_CACHE_URL,
                          params={"key": settings.gemini_api_key.strip()},
                          json=body, timeout=30)
    except requests.RequestException as exc:
        logger.warning("gemini cache create failed (continuing uncached): %s", exc)
        return ""
    if r.status_code != 200:
        detail = r.text[:200]
        # A model that does not support explicit caching will keep rejecting it;
        # stop asking rather than paying a failed round trip on every call.
        logger.warning("gemini cache create %s — continuing uncached: %s",
                       r.status_code, detail)
        _gemini_cache["disabled"] = True
        return ""
    name = (r.json() or {}).get("name") or ""
    if not name:
        _gemini_cache["disabled"] = True
        return ""
    _gemini_cache.update({"name": name, "digest": digest,
                          "expires": now + GEMINI_CACHE_TTL_SECONDS})
    logger.info("gemini system prompt cached as %s (%d chars, ttl %ds)",
                name, len(system_prompt), GEMINI_CACHE_TTL_SECONDS)
    return name


def _call_gemini(settings, system_prompt: str, messages: list, temperature: float,
                 thinking: int | None = None, model: str | None = None):
    """Gemini (fallback). Returns (text, error).

    `thinking` overrides the configured budget for THIS call. Planning a campaign
    needs deliberation; "fix the field this refusal names" does not, and paying
    8K thought tokens for a mechanical edit is most of what made a full workflow
    expensive."""
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
    budget = settings.gemini_thinking_budget if thinking is None else thinking
    if budget and budget > 0:
        gen_config["thinkingConfig"] = {"thinkingBudget": budget}
    use_model = model or settings.gemini_model
    body = {"contents": contents, "generationConfig": gen_config}
    # Either reference the cached system prompt OR send it inline — the API
    # rejects both together.
    cache_name = _ensure_gemini_cache(settings, system_prompt, use_model)
    if cache_name:
        body["cachedContent"] = cache_name
    else:
        body["system_instruction"] = {"parts": [{"text": system_prompt}]}
    url = GEMINI_URL.format(model=use_model)
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
    _usage_add(data.get("usageMetadata") or {})
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


# Lean-prompt stand-in for the deep reference doc. Groq's free tier caps
# tokens/minute (12K on 70b) and the full KB blows past it. The essentials the
# planner actually needs to emit specs — recipes, games, corrections — stay full;
# only the deep reference is dropped, with a pointer. Gemini has no such cap and
# gets the full doc.
_LEAN_KB = (
    "(Knowledge base omitted to fit this model's token budget. Rely on the "
    "RECIPES CATALOG, GAMES REGISTRY and CORRECTIONS below — they are the "
    "authoritative, up-to-date truth. Do NOT invent activities or recipes not "
    "listed there; if the brief needs something absent, output the ⛔ UNCAPTURED "
    "line.)"
)


def _assert_no_unfilled_blocks(prompt: str) -> None:
    """Refuse a prompt still carrying an empty <TAG>\n</TAG> placeholder.

    An unsubstituted placeholder is worse than a missing section: the model reads
    an empty tagged block as "this IS the list", so one typo'd tag name quietly
    tells it there are no recipes, no games, or no generators. This page builds its
    own prompt, so a block wired only into journey-planner/planner.py reaches the
    CLI and not the UI — which is how a literal <GENERATORS_CATALOG> shipped here.
    """
    stray = re.findall(r"<([A-Z_]+)>\n</\1>", prompt)
    if stray:
        raise RuntimeError(f"system_prompt.txt has unfilled blocks: {stray} — "
                           f"_build_system_prompt must substitute every one")


def _build_system_prompt(lean: bool = False) -> str:
    """Assemble system_prompt.txt with the KB docs inlined — identical to
    journey-planner/planner.py. Read fresh each call so doc edits take effect
    without a restart. When lean=True, the two big reference docs are replaced
    with short pointers (for token-capped providers like Groq free tier); the
    recipes/games/corrections — what specs are actually built from — stay full.
    Raises FileNotFoundError if the docs are missing."""
    tpl = (PLANNER_DIR / "system_prompt.txt").read_text(encoding="utf-8")
    # The capture backlog is NO LONGER injected. It answered "what is composable"
    # in hand-written prose while the generated RECIPES CATALOG answers the same
    # question from the code that does the building — and the prose had drifted,
    # so the prompt shipped a section contradicting its own catalog (it still
    # called email_engagement_split unconfirmed long after gow_comms.json captured
    # it). ~2.2k tokens saved and one whole class of contradiction with it. The
    # file stays on disk as a human capture-planning note.
    if lean:
        kb = _LEAN_KB
    else:
        kb = (PLANNER_DIR / "REA_KNOWLEDGE_BASE.md").read_text(encoding="utf-8")
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
    gen_file = REPO_ROOT / "journey-cloner" / "generators_catalog.json"
    generators = gen_file.read_text(encoding="utf-8") if gen_file.exists() else "{}"
    out = (
        tpl
        .replace("<KNOWLEDGE_BASE>\n</KNOWLEDGE_BASE>", kb)
        .replace("<RECIPES_CATALOG>\n</RECIPES_CATALOG>", catalog)
        .replace("<GENERATORS_CATALOG>\n</GENERATORS_CATALOG>", generators)
        .replace("<GAMES_REGISTRY>\n</GAMES_REGISTRY>", games)
        .replace("<CORRECTIONS>\n</CORRECTIONS>", corrections)
    )
    _assert_no_unfilled_blocks(out)
    return out


def planner_view_context() -> dict:
    """State the Planner tab partial needs — shared by the (now-redirecting)
    standalone page and the Optimization page's Planner tab."""
    settings = get_settings()
    provider = _resolve_provider(settings)
    model = (settings.groq_model if provider == "groq"
             else (settings.gemini_planning_model or settings.gemini_model))
    key_ok = bool((settings.groq_api_key if provider == "groq"
                   else settings.gemini_api_key).strip())
    return {
        "model": f"{provider}:{model}",
        "provider": provider,
        "key_env": "GROQ_API_KEY" if provider == "groq" else "GEMINI_API_KEY",
        "key_configured": key_ok,
        "docs_present": (PLANNER_DIR / "system_prompt.txt").exists(),
    }


@router.get("/admin/ai", response_class=HTMLResponse)
def ai_page(
    request: Request,
    user: User = Depends(require_role("editor")),
):
    """The AI planner on its own page.

    It lived as a tab on the Optimization hub, sharing that page with nine
    generator forms — which meant a cropped panel for the one thing here that is
    a workspace rather than a form. Optimization is now only generators.
    """
    from ..routes.admin_views import templates
    # Same call shape as every other page here: (request, name, context).
    return templates.TemplateResponse(request, "ai.html", {
        "active_page": "ai",
        "current_user": user,
        "pl": planner_view_context(),
    })


@router.get("/admin/planner")
def planner_page(
    request: Request,
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    """Old bookmarks and the old Optimization tab link both land here."""
    return RedirectResponse(url="/admin/ai", status_code=307)


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
    # A SHAPE refusal ("this recipe is deposit-gated", "this recipe has no
    # knobs") cannot be fixed by editing a value — the answer is a different
    # engine. The old instruction forbade exactly that, so the model edited
    # knobs forever and got refused every round.
    wants_chain = "MODE 5" in refusal or "chain" in refusal.lower()
    if wants_chain:
        instruction = (
            f"The composer REFUSED this {mode} spec, and the refusal says the "
            f"RECIPE cannot express this journey. Do not try to fix the knobs — "
            f"re-emit it as a MODE 5 CHAIN spec instead, containing only the "
            f"activities this journey actually needs, with the same values. "
            f"Output ONLY the JSON object.\n\n"
            f"--- SPEC ---\n{spec_text}\n\n--- REFUSAL ---\n{refusal.strip()[:4000]}\n"
        )
    else:
        instruction = (
            f"The composer REFUSED this {mode} spec. Fix ONLY what the refusal "
            f"names and re-emit the corrected JSON object — no prose, no "
            f"explanation, no other changes to the journey.\n\n"
            f"--- SPEC ---\n{spec_text}\n\n--- REFUSAL ---\n{refusal.strip()[:4000]}\n"
        )
    try:
        text, error = _complete(settings, [{"role": "user", "text": instruction}], 0.0,
                                lean=True, thinking=REPAIR_THINKING)
    except Exception as exc:
        logger.warning("spec repair call failed: %s", exc)
        return None
    if error or not text:
        logger.warning("spec repair unavailable: %s", error)
        return None
    return text


def _games_in(spec: dict) -> set[str]:
    """Every game a spec names, in either shape (recipe knobs or chain nodes)."""
    found: set[str] = set()

    def add(value) -> None:
        text = str(value or "").strip()
        if text and "⛔" not in text:
            found.add(re.sub(r"[^a-z0-9]+", "", text.lower()))

    for knob, value in (spec.get("knobs") or {}).items():
        if "game" in knob.lower():
            add(value)

    def walk(nodes) -> None:
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            if node.get("game"):
                add(node["game"])
            for branch in (node.get("branches") or {}).values():
                walk(branch)

    walk(spec.get("chain"))
    return found


def _reject_game_swaps(before: list[dict], after: list[dict]) -> tuple[list[dict], list[str]]:
    """Drop repaired specs that changed a game to one the brief never named.

    A repair round is told to fix the engine, not the campaign. But when the
    composer refuses an unregistered game it also suggests near matches, and the
    model will happily take one — turning "Bone Fortune" into "Ocean Fortune" and
    "3x5 Double Blazing" into "Double Rainbow". That builds cleanly and grants
    spins on the wrong game, which is worse than not building at all. Only the
    operator gets to choose a replacement game, so a swap is dropped here and
    reported.
    """
    allowed: set[str] = set()
    for spec in before:
        allowed |= _games_in(spec)
    kept, swapped = [], []
    for spec in after:
        extra = _games_in(spec) - allowed
        if extra and allowed:
            swapped.append(spec.get("journey_name") or spec.get("name") or "journey")
            continue
        kept.append(spec)
    return kept, swapped


def _chain_palette(specs: list[dict]) -> str:
    """The allowed inline settings for exactly the activities these specs use.

    The full palette is already in the system prompt (inside the recipes
    catalog), but on a 30-journey repair the model keeps inventing one new
    setting name per round — `promotion_settings`, `targetSystem`,
    `max_bonus_amount` — and each round costs a model call. Handing it the
    relevant few lines as data converges in one round instead of five.
    """
    catalog_file = REPO_ROOT / "journey-cloner" / "recipes_catalog.json"
    try:
        activities = json.loads(catalog_file.read_text(encoding="utf-8")) \
            .get("chain_composer", {}).get("activities", {})
    except Exception as exc:                       # missing/!json catalog
        logger.warning("chain palette unavailable: %s", exc)
        return ""
    if not activities:
        return ""

    # Which activity names appear in these specs (through their aliases)?
    used: set[str] = set()

    def walk(nodes) -> None:
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            raw = str(node.get("type") or node.get("activity") or "").strip().lower()
            for key, spec in activities.items():
                if raw == key or raw in (spec.get("aliases") or []):
                    used.add(key)
                    break
            for branch in (node.get("branches") or {}).values():
                walk(branch)

    for spec in specs:
        walk(spec.get("chain"))
    if not used:
        used = set(activities)                     # first repair: nothing is a chain yet

    lines = []
    for key in sorted(used):
        keys = [k for k in (activities[key].get("inline_keys") or []) if k != "(none)"]
        allowed = ", ".join(keys) if keys else (
            'NO settings at all — the node is {"type": "' + key + '"} and nothing else')
        lines.append(f"  {key}: {allowed}")
    return ("\n\nThe ONLY settings each of these activities accepts (anything else "
            "is refused, not ignored):\n" + "\n".join(lines))


def _repair_batch(settings, specs: list[dict], reasons: list[str]) -> str | None:
    """One correction round for a whole campaign's specs.

    A 30-journey campaign refused 30 times is one mistake made 30 times — most
    often a recipe that cannot express the journey (no game knob), whose only fix
    is a different engine. The model is shown the distinct refusals and re-emits
    every spec, so "full script" turns into scripts instead of a wall of ⛔.
    """
    joined = "\n".join(f"  - {r}" for r in reasons)
    # A "recipe does not define that knob" / "recipe is deposit-gated" refusal is
    # a SHAPE refusal: no edit to the knobs can fix it, the answer is the chain
    # engine. Asked politely ("switch if the refusal says…") the model keeps the
    # recipe and gets refused again, so when the reasons say shape, the
    # instruction is not a choice.
    wants_chain = any(re.search(r"does not define|has no |deposit-gated|MODE 5|zero knobs",
                                r, re.I) for r in reasons)
    if wants_chain:
        instruction = (
            f"The composer REFUSED all of the specs below. The distinct reasons "
            f"were:\n{joined}\n\n"
            f"These recipes cannot express these journeys — that is a shape "
            f"problem, and editing knobs cannot fix it. Re-emit ALL {len(specs)} "
            f"objects as MODE 5 CHAIN specs: the {{\"name\", \"source\", \"chain\", "
            f"\"date\", \"days\"}} shape, settings INLINE on each node, and NO "
            f"`recipe` key anywhere. Keep every journey's name, its activities and "
            f"its values. The rules that get violated most, so check each one:\n"
            f"  * NO `follow` key on any node — a chain wires itself, and a `follow` "
            f"that names the node's own forward event is refused outright.\n"
            f"  * NO wrapper keys: settings go INLINE on the node. Never "
            f"`settings`, never `promotion_settings`. `promotion` takes no settings "
            f"at all — it is exactly {{\"type\": \"promotion\"}}.\n"
            f"  * ONLY the setting names that activity lists in the CHAIN COMPOSER "
            f"palette; the refusals above print the allowed list where they know it.\n"
            f"  * Amounts are MINOR units — multiply every CLP figure by 100 "
            f"(2.500 CLP -> 250000, bet 50 -> 5000).\n"
            f"  * The brief's game NAME goes in `game`; send no provider. NEVER "
            f"swap it for a near match the composer suggested — a journey that "
            f"grants spins on a different game is wrong, not fixed. If a game is "
            f"not registered, leave that journey out and name it at the end.\n"
            f"  * The ENTRY is the spec's `source` field — {{\"type\": \"api\"}} for a "
            f"wheel/promo-page entry, {{\"type\": \"segment\"}} for a segment. It is "
            f"NOT a chain node: no `external_system_source` node, no `targetSystem`.\n"
            f"  * Do not add a terminal node — the composer appends it.\n"
            f"  * DROP any object that is not a journey — a promo page, a wheel, a "
            f"randomizer. Emit no block for it and name it in one line at the end.\n"
            f"One ```json block per journey, no prose between them."
            f"{_chain_palette(specs)}\n\n"
            f"--- SPECS ---\n{json.dumps(specs, ensure_ascii=False)[:MAX_CHARS]}\n"
        )
    else:
        instruction = (
            f"The composer REFUSED the specs below. The distinct reasons were:\n"
            f"{joined}\n\n"
            f"Re-emit ALL {len(specs)} objects, corrected, one ```json block each "
            f"and no prose between them. Keep every journey's NAME and VALUES "
            f"exactly as they are — only fix what the refusals name. Drop an object "
            f"only if it is not a journey at all (a promo page), and say so in one "
            f"line after the blocks.\n\n"
            f"--- SPECS ---\n{json.dumps(specs, ensure_ascii=False)[:MAX_CHARS]}\n"
        )
    try:
        text, error = _complete(settings, [{"role": "user", "text": instruction}], 0.0,
                                lean=True, thinking=REPAIR_THINKING)
    except Exception as exc:
        logger.warning("batch repair call failed: %s", exc)
        return None
    if error or not text:
        logger.warning("batch repair unavailable: %s", error)
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
    if len(text) > MAX_ARTIFACT_CHARS:
        return JSONResponse({"error": f"Reply too large ({len(text)} chars, "
                                     f"max {MAX_ARTIFACT_CHARS})."})
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

        def build_all(batch: list[dict]) -> list[dict]:
            """Compose a whole campaign's specs.

            Recipe specs collapse into ONE script — one token capture, one paste,
            every draft — and a wheel alongside them joins that SAME script: its
            prize routing needs the journey ids, which only exist once the
            journeys in it have been created. Chains use a different engine, so
            those stay individual.
            """
            results: list[dict] = []
            recipe_specs = [s for s in batch if _spec_mode(s) == "spec"]
            wheel_specs = [s for s in batch if _spec_mode(s) == "randomizer"]
            other_specs = [s for s in batch
                           if _spec_mode(s) not in ("spec", "randomizer")]
            if len(recipe_specs) > 1:
                names = [s.get("journey_name") or "journey" for s in recipe_specs]
                payload: dict = {"journeys": recipe_specs}
                # One wheel rides along with the journeys it routes into. More
                # than one is ambiguous (which journeys belong to which wheel?),
                # so the extras stay separate scripts.
                with_wheel = wheel_specs[0] if len(wheel_specs) == 1 else None
                if with_wheel:
                    payload["randomizer"] = with_wheel
                    wheel_specs = wheel_specs[1:]
                    names = names + [f"randomizer: {with_wheel.get('kind', 'wheel')}"]
                try:
                    code, log, cmd, js, filename = generate_composed_console_script(
                        json.dumps(payload), mode="batch")
                except Exception as exc:
                    logger.warning("planner batch compose failed: %s", exc)
                    code, log, js, filename = 1, f"Composer failed to run: {exc}", None, ""
                # What the script ACTUALLY carries, read back from the build log.
                # "20 journeys + the wheel" while the script created 5 and dropped
                # the wheel is worse than no label at all.
                in_script = re.findall(r"^  ✓ (.+)$", log or "", re.M)
                not_built = re.findall(r"^  ⛔ (.+)$", log or "", re.M)
                journeys_in = [n for n in in_script if not n.startswith("randomizer ")]
                wheel_in = [n for n in in_script if n.startswith("randomizer ")]
                if in_script:
                    label = f"{len(journeys_in)} journey(s)"
                    label += " + the wheel" if wheel_in else ""
                    label += " — one paste"
                    if len(journeys_in) < len(recipe_specs) or (with_wheel and not wheel_in):
                        label += f" ({len(not_built)} object(s) NOT built)"
                    names = in_script + [f"⛔ {n}" for n in not_built]
                else:
                    label = (f"{len(recipe_specs)} journeys + the wheel — one paste"
                             if with_wheel else f"{len(recipe_specs)} journeys in one script")
                results.append({
                    "index": 1, "batch": True, "count": len(journeys_in) or len(recipe_specs),
                    "name": label,
                    "detail": names, "mode": "batch",
                    # exit 4 = partial: fewer drafts than asked for, still usable.
                    "ok": code in (0, 4) and bool(js), "partial": code == 4,
                    "returncode": code, "log": log, "js": js, "filename": filename,
                })
            else:
                other_specs = recipe_specs + other_specs
            other_specs = other_specs + wheel_specs

            for spec in other_specs:
                spec_mode = _spec_mode(spec)
                i = len(results) + 1
                try:
                    code, log, cmd, js, filename = generate_composed_console_script(
                        json.dumps(spec), mode=spec_mode)
                except Exception as exc:
                    logger.warning("planner compose failed on spec %d: %s", i, exc)
                    code, log, js, filename = 1, f"Composer failed to run: {exc}", None, ""
                results.append({
                    "index": i,
                    "name": spec.get("journey_name") or spec.get("name")
                            or spec.get("kind") or f"object {i}",
                    "mode": spec_mode, "ok": code == 0 and bool(js),
                    "returncode": code, "log": log, "js": js, "filename": filename,
                })
            return results

        def scored(results: list[dict]) -> int:
            """Objects actually built (a batch result stands for its whole count)."""
            return sum(r.get("count", 1) if r.get("ok") else 0 for r in results)

        def digest(results: list[dict]) -> list[str]:
            """The DISTINCT refusals in a run.

            A 30-journey campaign refused 30 times is one mistake made 30 times,
            so the per-object prefix is stripped and duplicates collapse — that is
            what makes a single repair round able to fix the whole batch. Every
            line is scanned, not just the first: a batch log carries one refusal
            per journey and the dominant reason is usually further down.
            """
            reasons: list[str] = []
            for r in results:
                if r["ok"]:
                    continue
                for line in (r.get("log") or "").splitlines():
                    line = line.strip()
                    if line.upper().startswith("STDERR"):
                        continue
                    if not line or not re.search(
                            r"⛔|refus|unknown|not a known|does not define|unsupported",
                            line, re.I):
                        continue
                    key = re.sub(r"^⛔\s*\d+\.\s*[^:]*:\s*", "", line)[:700]
                    if key not in reasons:
                        reasons.append(key)
                    if len(reasons) >= 6:
                        break
            return reasons

        # Repair rounds, same budget as the single-spec path. One round is not
        # enough in practice: the first fixes the ENGINE (a recipe that cannot
        # carry a game becomes a chain) and the second fixes the setting names
        # that engine uses. Each round is one model call for the whole campaign.
        current, results, repaired = specs, [], False
        swaps: list[str] = []          # journeys a repair tried to re-game
        best: tuple[int, list[dict]] = (-1, [])
        for attempt in range(1 + MAX_COMPOSE_REPAIRS):
            results = build_all(current)
            score = scored(results)
            if score > best[0]:
                best = (score, results)
                repaired = attempt > 0
            if all(r["ok"] for r in results) or attempt == MAX_COMPOSE_REPAIRS:
                break
            reasons = digest(results)
            if not reasons:
                break
            logger.info("batch compose refused (round %d) — repairing over %d distinct reason(s)",
                        attempt + 1, len(reasons))
            fixed = _repair_batch(settings, current, reasons)
            next_specs = _extract_all_specs(fixed or "")
            next_specs, swapped = _reject_game_swaps(current, next_specs)
            if swapped:
                logger.info("batch repair swapped games on %d object(s) — dropped",
                            len(swapped))
                swaps.extend(swapped)
            if not next_specs:
                logger.info("batch repair produced no specs — stopping")
                break
            current = next_specs

        built_objects, results = best
        for name in dict.fromkeys(swaps):
            results.append({
                "index": len(results) + 1, "name": name, "mode": "spec", "ok": False,
                "returncode": 3,
                "log": "⛔ not built — the repair tried to swap this journey's game "
                       "for a similar registered one. The brief's game is not in the "
                       "games registry, and granting spins on a different game is "
                       "not a fix: register the game (journey-cloner/"
                       "build_games_registry.py) or tell the planner which "
                       "registered game to use instead.",
            })
        built = sum(1 for r in results if r["ok"])
        return JSONResponse({"ok": built > 0, "multi": True, "built": built,
                             "repaired": repaired, "objects": built_objects,
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
        # A shape refusal is repaired by switching ENGINES, so the mode has to
        # be re-read from what came back — otherwise a chain spec would be run
        # through --spec and die as "unknown recipe None".
        mode = _detect_mode(current, mode)

    logger.info("planner compose refused after %d attempt(s)", len(attempts))
    return JSONResponse({"ok": False, "returncode": attempts[-1]["returncode"],
                         "log": attempts[-1]["log"], "cmd": cmd,
                         "attempts": attempts})


DESIGN_SCRIPT = PLANNER_DIR / "render_journey_design.py"
DESIGN_OUT_DIR = REPO_ROOT / "data" / "journey_designs"
MAX_DESIGN_JOURNEYS = 40       # a brief past this is a paste accident, not a campaign
KEEP_DESIGN_RUNS = 40          # boards go to the browser as data URLs; disk is a cache


def _prune_design_runs() -> None:
    """Keep the last few render directories. The operator gets the PNGs inline
    and downloads what they want, so older runs are only useful for a quick
    re-check — an unbounded pile of them is not."""
    try:
        runs = sorted((p for p in DESIGN_OUT_DIR.iterdir() if p.is_dir()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except FileNotFoundError:
        return
    for stale in runs[KEEP_DESIGN_RUNS:]:
        shutil.rmtree(stale, ignore_errors=True)


def _looks_like_plan(text: str) -> bool:
    """Is this reply a campaign plan (so a design can be drawn from it)?"""
    probe = text.upper()
    return ("OBJECTS TO BUILD" in probe or "CREATION ORDER" in probe
            or "SAY WHICH OBJECT" in probe or "CAMPAIGN:" in probe)


def _design_block_for(settings, plan_text: str) -> str | None:
    """Ask the planner for the design block of an outline that shipped without one.

    MODE 1 is supposed to include it, but compliance slips on long briefs — the
    model spends its reply on the outline and flags and just stops. Rather than
    make the operator notice and re-ask, the block is requested here from the
    plan the model already wrote. Same one-shot repair the composer does for a
    refused spec; the plan itself is never re-generated, so nothing changes but
    the picture data.
    """
    instruction = (
        "Below is a campaign outline you already produced. Emit ONLY the MODE 1 "
        "DESIGN BLOCK for it — a single ```json fence containing the `diagram` "
        "object, one entry in `journeys` for every object in the outline, in the "
        "same order and with the same names. No prose, no outline, no spec.\n\n"
        f"--- OUTLINE ---\n{plan_text[:MAX_CHARS]}\n"
    )
    try:
        text, error = _complete(settings, [{"role": "user", "text": instruction}], 0.0,
                                lean=True, thinking=REPAIR_THINKING)
    except Exception as exc:
        logger.warning("design block request failed: %s", exc)
        return None
    if error or not text:
        logger.warning("design block unavailable: %s", error)
        return None
    return text


@router.post("/admin/planner/design")
def planner_design(
    payload: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> JSONResponse:
    """Render a MODE 1 reply's `diagram` block into picture boards.

    The planner emits the outline plus a JSON diagram; this turns that diagram
    into PNGs (one card per activity, with its icon) and hands them back inline
    as data URLs. Sync `def` for the same reason compose is: the subprocess runs
    in FastAPI's threadpool instead of blocking the event loop.

    The model never sees the images — it only produced the data. An outline that
    arrived without a design block is repaired once (see `_design_block_for`)
    rather than bounced back to the operator.
    """
    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "Nothing to render — send the planner reply."})
    if len(text) > MAX_ARTIFACT_CHARS:
        return JSONResponse({"error": f"Reply too large ({len(text)} chars, "
                                     f"max {MAX_ARTIFACT_CHARS})."})
    try:
        per_image = int(payload.get("per_image", 2))
    except (TypeError, ValueError):
        per_image = 2
    per_image = min(max(per_image, 0), 12)     # 0 = every journey on one board
    if not DESIGN_SCRIPT.exists():
        return JSONResponse({"error": f"Renderer not found at {DESIGN_SCRIPT} — "
                                      "make sure journey-planner/ is deployed."})

    run_dir = DESIGN_OUT_DIR / f"{time.strftime('%Y-%m-%d')}_{uuid.uuid4().hex[:8]}"
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    cmd = [str(venv_python) if venv_python.exists() else sys.executable,
           str(DESIGN_SCRIPT), "-", "--out", str(run_dir), "--name", "journey",
           "--per-image", str(per_image)]

    def draw(source: str) -> tuple[int, dict, str]:
        """Run the renderer over `source`. Returns (exit code, manifest, detail)."""
        try:
            proc = subprocess.run(cmd, input=source, text=True, encoding="utf-8",
                                  capture_output=True, timeout=120, cwd=str(REPO_ROOT))
        except Exception as exc:                   # timeout, OSError, ...
            logger.warning("design render failed: %s", exc)
            return 1, {}, f"Renderer failed to run: {exc}"
        out = (proc.stdout or "").strip()
        found: dict = {}
        for line in reversed(out.splitlines()):    # manifest is the last JSON line
            try:
                found = json.loads(line)
                break
            except ValueError:
                continue
        detail = found.get("error") or (proc.stderr or out or "").strip()[-1200:]
        return proc.returncode, found, detail

    code, manifest, detail = draw(text)
    repaired = False
    if (code != 0 or not manifest.get("ok")) and _looks_like_plan(text):
        # The outline is there but the design block is not — ask for just the
        # block and draw that instead of sending the operator back to the chat.
        logger.info("design block missing from a plan — requesting it")
        block = _design_block_for(get_settings(), text)
        if block:
            code, manifest, detail = draw(block)
            repaired = manifest.get("ok", False)

    if code != 0 or not manifest.get("ok"):
        logger.info("design render refused (exit %s): %s", code, detail[:200])
        shutil.rmtree(run_dir, ignore_errors=True)
        # The common case is a reply that is a spec or a follow-up answer, not an
        # outline — say what to do about it instead of echoing the parser.
        if "no diagram" in detail.lower():
            detail = ("that reply carries no `diagram` block, and the planner could "
                      "not produce one from it. Ask for \"the outline again, with "
                      "the design block\".")
        return JSONResponse({"ok": False, "error": f"No design to draw — {detail}"})

    images = []
    for item in (manifest.get("images") or [])[:MAX_DESIGN_JOURNEYS]:
        path = Path(item.get("path") or "")
        if not path.is_file():
            continue
        images.append({
            "name": path.name,
            "journeys": item.get("journeys") or [],
            "w": item.get("w"), "h": item.get("h"),
            "data": "data:image/png;base64,"
                    + base64.b64encode(path.read_bytes()).decode("ascii"),
        })
    if not images:
        shutil.rmtree(run_dir, ignore_errors=True)
        return JSONResponse({"ok": False, "error": "Renderer produced no boards."})
    _prune_design_runs()
    return JSONResponse({"ok": True, "repaired": repaired,
                         # Half a plan drawn beats none, but the operator has to
                         # know the design data itself was cut off.
                         "truncated": bool(manifest.get("truncated")),
                         # near-identical journeys share a board, so the count of
                         # boards is not the count of journeys
                         "collapsed": int(manifest.get("collapsed") or 0),
                         "count": len(images), "images": images,
                         "campaign": manifest.get("campaign") or "",
                         "journeys": manifest.get("journeys") or len(images),
                         "dir": str(run_dir)})


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

    totals = _usage_start()
    text, error = _complete(settings, messages, temperature)
    # Cached input bills far below fresh input, and the system prompt is identical
    # on every call, so the cache-hit share is the single most useful number here.
    logger.info("planner usage: %d call(s), input %d (cached %d), thought %d, answer %d",
                totals["calls"], totals["input"], totals["cached"],
                totals["thought"], totals["answer"])

    if error:
        return JSONResponse({"error": error}, status_code=200)
    return JSONResponse({"text": text, "usage": totals})
