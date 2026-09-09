"""Script Runner extension — distribution + the install page.

  GET  /script-runner/update.xml         update manifest        PUBLIC
  GET  /script-runner/runner.crx         signed extension       PUBLIC
  GET  /script-runner/script-runner.zip  unsigned, for unpacked PUBLIC
  GET  /admin/tools/script-runner        install instructions   editor
  POST /admin/tools/script-runner/job    mint a run code        editor
  GET  /run/{code}                       hand over the script   PUBLIC

The three file routes are deliberately unauthenticated: Chrome fetches an
update manifest and a CRX with no session and no way to log in, so a
force-installed extension behind the admin cookie would simply never install.
They leak nothing — the extension is the same code that ships in the repo, and
it holds no secrets. The instructions page, which names the CRM's own origins,
stays behind a login.

Nothing here is served unless scripts/pack_script_runner.py has been run: the
artifacts are build output, gitignored, and the routes 404 without them rather
than handing Chrome a truncated CRX.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth.dependencies import require_role
from ..config import get_settings
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import User
from ..services import run_jobs

logger = get_logger("app.routes.script_runner")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
DIST = BASE_DIR / "static" / "script-runner"

router = APIRouter()

# Chrome's own content types. It is forgiving about the CRX one, but an
# update manifest served as text/html is not parsed at all.
# The loader the operator saves once, as a DevTools Snippet or a bookmarklet.
# It is fixed: the only thing that changes per run is the code typed into the
# prompt, which is what makes saving it worthwhile.
LOADER_TEMPLATE = """\
(async () => {
  const CRM = '@CRM@';
  const code = prompt('Run code from the CRM:');
  if (!code) return;
  const r = await fetch(CRM + '/run/' + encodeURIComponent(code.trim().toUpperCase()));
  const src = await r.text();
  if (!r.ok) { console.error(src.trim()); return; }
  console.log('%cLoaded ' + src.length.toLocaleString() + ' bytes. Running...', 'color:#22c55e;font-weight:bold');
  try {
    (0, eval)(src);
  } catch (e) {
    console.error('Could not run it: ' + e.message);
    console.error('If that mentions Content Security Policy, this page forbids eval. '
      + 'Fall back to Copy script in the CRM and paste it here.');
  }
})();
"""

CRX_TYPE = "application/x-chrome-extension"
XML_TYPE = "application/xml"

# The loader runs on a page served by the backoffice, so the response has to be
# readable cross-origin. Echo the Origin only when it is the backoffice — never
# "*", which would let any site read a script off a leaked code.
ALLOWED_ORIGIN_SUFFIX = ".rea-backoffice.gr8.tech"


def _cors(origin: str | None) -> dict:
    if not origin:
        return {}
    try:
        host = urlsplit(origin).hostname or ""
    except ValueError:
        return {}
    if not host.endswith(ALLOWED_ORIGIN_SUFFIX):
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}


def _meta() -> dict | None:
    """Build metadata from the last pack run, or None if never packed."""
    path = DIST / "runner.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("script-runner/runner.json is unreadable — repack")
        return None


def _public_base(request: Request) -> str:
    """Absolute origin for update.xml's codebase, which cannot be relative.

    Prefers the configured public origin; falls back to the requested one so
    this works on a laptop before PUBLIC_BASE_URL is set.
    """
    configured = (get_settings().public_base_url or "").rstrip("/")
    if configured.startswith("http"):
        return configured
    return str(request.base_url).rstrip("/")


@router.get("/script-runner/update.xml")
def update_manifest(request: Request) -> Response:
    path = DIST / "update.xml"
    if not path.is_file():
        return Response("not packed", status_code=404, media_type="text/plain")
    xml = path.read_text(encoding="utf-8").replace("@BASE@", _public_base(request))
    # No caching: Chrome re-checks this to find new versions, and a cached copy
    # is how a shipped update silently fails to roll out.
    return Response(xml, media_type=XML_TYPE, headers={"Cache-Control": "no-store"})


@router.get("/script-runner/runner.crx")
def runner_crx() -> Response:
    path = DIST / "runner.crx"
    if not path.is_file():
        return Response("not packed", status_code=404, media_type="text/plain")
    return Response(path.read_bytes(), media_type=CRX_TYPE, headers={
        "Cache-Control": "no-store",
        "Content-Disposition": 'attachment; filename="runner.crx"',
    })


@router.get("/script-runner/script-runner.zip")
def runner_zip() -> Response:
    path = DIST / "script-runner.zip"
    if not path.is_file():
        return Response("not packed", status_code=404, media_type="text/plain")
    return Response(path.read_bytes(), media_type="application/zip", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": 'attachment; filename="script-runner.zip"',
    })


@router.get("/admin/tools/script-runner", response_class=HTMLResponse)
def install_page(request: Request, user: User = Depends(require_role("editor"))):
    meta = _meta()
    base = _public_base(request)

    # The exact policy values IT pastes. Built here rather than written by hand
    # in the template so the id and the URL can never disagree with the CRX
    # actually being served.
    #
    # Two forms, because which policy IT edits matters here. On these laptops
    # ExtensionInstallBlocklist is ["*"] from cloud (user) policy, and
    # ExtensionSettings is set at PLATFORM MACHINE level by the Mac MDM — which
    # per Chrome's precedence order (platform machine > cloud machine > platform
    # user > cloud user) overrides the cloud ExtensionSettings wholesale.
    # So:
    #   * ExtensionInstallForcelist in the Admin console works (a different
    #     policy, not overridden, and a forcelist entry beats the blocklist);
    #   * adding to the MDM's ExtensionSettings works (highest precedence);
    #   * adding to CLOUD ExtensionSettings would be silently ignored.
    policy = None
    forcelist = None
    if meta:
        update_url = f"{base}/script-runner/update.xml"
        forcelist = f'{meta["id"]};{update_url}'
        policy = json.dumps(
            {meta["id"]: {
                "installation_mode": "force_installed",
                "update_url": update_url,
            }},
            indent=2,
        )

    loader = LOADER_TEMPLATE.replace("@CRM@", base)
    # A bookmarklet has to be one line, and every character that could end the
    # href needs escaping — build it here rather than in the template.
    bookmarklet = "javascript:" + quote(
        " ".join(line.strip() for line in loader.splitlines() if line.strip()),
        safe="",
    )

    return templates.TemplateResponse(
        "script_runner.html",
        {
            "request": request,
            "current_user": user,
            "active": "script_runner",
            "meta": meta,
            "policy": policy,
            "forcelist": forcelist,
            "loader": loader,
            "bookmarklet": bookmarklet,
            # From the service, so the page cannot drift from what it enforces.
            "ttl_minutes": run_jobs.TTL_SECONDS // 60,
            "max_reads": run_jobs.MAX_READS,
            "base": base,
            "crm_origin_pattern": base + "/*",
        },
    )


@router.post("/admin/tools/script-runner/job")
@limiter.limit("60/minute")
def mint_run_code(
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> JSONResponse:
    """Store the script the page is already showing, and return a run code.

    Called by /static/js/run_code.js from the admin page, which has the script
    text in the DOM already. Doing it this way means none of the ~10 view
    functions that render a console-script card have to change.
    """
    try:
        job = run_jobs.create(
            name=str(body.get("name") or "console script"),
            text=body.get("text") or "",
            created_by=user.username,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    logger.info("run code minted for %s by %s", job.name, user.username)
    return JSONResponse({
        "code": job.code,
        "expires_in": job.expires_in,
        "reads_left": run_jobs.MAX_READS,
        "bytes": len(job.text),
    })


@router.get("/run/{code}")
@limiter.limit("20/minute")
def hand_over_script(code: str, request: Request) -> Response:
    """Hand the script to the loader running in the backoffice console.

    PUBLIC, and it has to be: the fetch comes from a page on the backoffice
    origin, which carries no CRM session because the cookie is SameSite=lax.
    The code is the credential — 31^10, minutes to live, a few reads — and the
    rate limit above is what makes guessing pointless rather than merely slow.
    """
    headers = _cors(request.headers.get("origin"))
    job = run_jobs.claim(code)
    if job is None:
        # Deliberately identical for expired, spent and never-existed: a
        # guesser learns nothing about which codes are real.
        return Response(
            "// No such run code, or it has expired. Generate a new one in the CRM.\n",
            status_code=404,
            media_type="application/javascript",
            headers=headers,
        )

    logger.info("run code redeemed: %s (%s)", job.name, job.created_by)
    headers["Cache-Control"] = "no-store"
    return Response(job.text, media_type="application/javascript", headers=headers)
