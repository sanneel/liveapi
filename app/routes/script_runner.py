"""Script Runner extension — distribution + the install page.

  GET /script-runner/update.xml         update manifest        PUBLIC
  GET /script-runner/runner.crx         signed extension       PUBLIC
  GET /script-runner/script-runner.zip  unsigned, for unpacked PUBLIC
  GET /admin/tools/script-runner        install instructions   editor

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

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..auth.dependencies import require_role
from ..config import get_settings
from ..logging_config import get_logger
from ..models import User

logger = get_logger("app.routes.script_runner")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
DIST = BASE_DIR / "static" / "script-runner"

router = APIRouter()

# Chrome's own content types. It is forgiving about the CRX one, but an
# update manifest served as text/html is not parsed at all.
CRX_TYPE = "application/x-chrome-extension"
XML_TYPE = "application/xml"


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

    # The exact policy value IT pastes. Built here rather than written by hand
    # in the template so the id and the URL can never disagree with the CRX
    # actually being served.
    policy = None
    if meta:
        policy = json.dumps(
            {meta["id"]: {
                "installation_mode": "force_installed",
                "update_url": f"{base}/script-runner/update.xml",
            }},
            indent=2,
        )

    return templates.TemplateResponse(
        "script_runner.html",
        {
            "request": request,
            "current_user": user,
            "active": "script_runner",
            "meta": meta,
            "policy": policy,
            "base": base,
            "crm_origin_pattern": base + "/*",
        },
    )
