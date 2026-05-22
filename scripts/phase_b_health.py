"""
Phase B health check — Hot engine + Club system parallel-run validator.

Usage:
    python scripts/phase_b_health.py

Optional environment variables:
    PHASE_B_BASE_URL    default http://127.0.0.1:8000
    PHASE_B_SPORT       default football
    PHASE_B_DB_PATH     default data/jugabet.db
    PHASE_B_USERNAME    admin login (required for override-flow test)
    PHASE_B_PASSWORD    admin password (required for override-flow test)
    PHASE_B_TIMEOUT     per-request timeout in seconds, default 10

    TELEGRAM_BOT_TOKEN  bot token from @BotFather (enables alerting)
    TELEGRAM_CHAT_ID    chat/channel id to send alerts to

Exit code 0 only when every non-skipped check passes. WARN does not fail.

Telegram alerting (optional):
    If TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set, a FAIL summary fires
    a Telegram message via api.telegram.org sendMessage. A WARN-only summary
    fires a lighter warning notification. All-PASS runs are silent.
    Alerts are fire-and-forget (background thread, bounded join) and never
    crash the script if Telegram itself is unreachable.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests


# Defaults — actual env reads happen inside each function so wrappers
# that mutate os.environ AFTER import still take effect.
_DEFAULTS = {
    "PHASE_B_BASE_URL": "http://127.0.0.1:8000",
    "PHASE_B_SPORT": "football",
    "PHASE_B_DB_PATH": "data/jugabet.db",
    "PHASE_B_TIMEOUT": "10",
}


def _env(name: str) -> str:
    return os.environ.get(name, _DEFAULTS.get(name, "")).strip()


def _base_url() -> str:
    return _env("PHASE_B_BASE_URL").rstrip("/")


def _sport() -> str:
    return _env("PHASE_B_SPORT") or "football"


def _db_path() -> str:
    return _env("PHASE_B_DB_PATH") or "data/jugabet.db"


def _timeout() -> float:
    try:
        return float(_env("PHASE_B_TIMEOUT") or "10")
    except ValueError:
        return 10.0


def _username() -> Optional[str]:
    v = os.environ.get("PHASE_B_USERNAME", "").strip()
    return v or None


def _password() -> Optional[str]:
    v = os.environ.get("PHASE_B_PASSWORD", "")
    return v or None


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL | WARN | SKIP
    detail: str = ""


# ─── Telegram alerting ──────────────────────────────────────────────────
def send_telegram_alert(text: str) -> None:
    """Fire a Telegram notification, fire-and-forget.

    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID at call time. If either
    is missing, this is a silent no-op (alerting disabled). The actual
    POST runs in a background thread with a short timeout so the caller
    never blocks on a slow Telegram API or a flaky network. Any exception
    raised by requests is swallowed — health-check exit code stays
    governed solely by the actual check results.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    def _post() -> None:
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception:
            # Never let alert failures bubble up — alerting is best-effort.
            pass

    t = threading.Thread(target=_post, daemon=False)
    t.start()
    # Bounded join: don't block the script for more than ~5s waiting on
    # Telegram. If the thread is still running after that, we leave it
    # to finish or die with the process.
    t.join(timeout=5)


# ─── DB helpers ─────────────────────────────────────────────────────────
def _open_db() -> sqlite3.Connection:
    path = _db_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"DB not found at {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _q_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    cur = conn.execute(sql, params)
    return cur.fetchone()


def _q_all(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    cur = conn.execute(sql, params)
    return cur.fetchall()


# ─── HTTP helpers ───────────────────────────────────────────────────────
def _login_session() -> Tuple[Optional[requests.Session], str]:
    """Returns (session, reason). reason is '' on success.

    Differentiates "no creds provided" from "creds present but login failed"
    so the override-flow check can report a useful diagnostic.

    Sets a session-wide `Origin` header that matches `_base_url()` so the
    SameOriginUnsafeMethodMiddleware (app/middleware/security.py) accepts
    our unsafe-method requests. Without this, /admin/login returns 403.
    """
    username = _username()
    password = _password()
    if not username or not password:
        return None, "PHASE_B_USERNAME/PASSWORD not set"
    base = _base_url()
    s = requests.Session()
    s.headers.update({"Origin": base, "Referer": base + "/admin/login"})
    try:
        r = s.post(
            f"{base}/admin/login",
            data={"username": username, "password": password},
            allow_redirects=False,
            timeout=_timeout(),
        )
    except requests.RequestException as e:
        return None, f"login request failed: {e}"
    if r.status_code not in (200, 302, 303):
        return None, f"login HTTP {r.status_code}"
    if "jugabet_session" not in s.cookies:
        return None, "login succeeded but no session cookie set (check COOKIE_SECURE vs http)"
    return s, ""


# ─── Checks ─────────────────────────────────────────────────────────────
def check_db_health() -> List[CheckResult]:
    results: List[CheckResult] = []
    try:
        conn = _open_db()
    except Exception as e:
        return [CheckResult("db.open", "FAIL", str(e))]

    try:
        # clubs exist
        row = _q_one(conn, "SELECT COUNT(*) AS n FROM clubs")
        n_clubs = int(row["n"]) if row else 0
        if n_clubs == 0:
            results.append(CheckResult(
                "db.clubs.count",
                "WARN",
                "0 clubs — parser may not have run a full cycle yet"
            ))
        else:
            results.append(CheckResult("db.clubs.count", "PASS", f"{n_clubs} clubs"))

        # overrides table exists and is queryable
        row = _q_one(conn, "SELECT COUNT(*) AS n FROM hot_override")
        n_over = int(row["n"]) if row else 0
        results.append(CheckResult(
            "db.hot_override.count",
            "PASS",
            f"{n_over} overrides (0 is normal for a fresh deploy)"
        ))

        # clubs: no null critical fields
        row = _q_one(
            conn,
            "SELECT COUNT(*) AS n FROM clubs WHERE name IS NULL OR name = '' OR slug IS NULL OR slug = ''"
        )
        n_bad = int(row["n"]) if row else 0
        if n_bad > 0:
            results.append(CheckResult(
                "db.clubs.no_null_fields", "FAIL",
                f"{n_bad} clubs have empty name or slug"
            ))
        else:
            results.append(CheckResult("db.clubs.no_null_fields", "PASS"))

        # matches: critical fields
        row = _q_one(
            conn,
            """SELECT COUNT(*) AS n FROM matches
               WHERE is_active = 1
                 AND (event_id IS NULL OR event_id = ''
                      OR home_name IS NULL OR home_name = ''
                      OR away_name IS NULL OR away_name = ''
                      OR sport IS NULL OR sport = ''
                      OR status IS NULL OR status = '')"""
        )
        n_bad = int(row["n"]) if row else 0
        if n_bad > 0:
            results.append(CheckResult(
                "db.matches.no_null_critical", "FAIL",
                f"{n_bad} active matches with null/empty critical field"
            ))
        else:
            row = _q_one(conn, "SELECT COUNT(*) AS n FROM matches WHERE is_active=1")
            n = int(row["n"]) if row else 0
            results.append(CheckResult(
                "db.matches.no_null_critical", "PASS",
                f"{n} active matches, all critical fields populated"
            ))

        # alembic at head 0009
        row = _q_one(conn, "SELECT version_num FROM alembic_version LIMIT 1")
        ver = row["version_num"] if row else None
        if ver == "0009":
            results.append(CheckResult("db.alembic.head", "PASS", "0009"))
        else:
            results.append(CheckResult(
                "db.alembic.head", "FAIL",
                f"expected 0009, got {ver!r}"
            ))
    finally:
        conn.close()

    return results


def check_hot_endpoint() -> List[CheckResult]:
    base = _base_url()
    sport = _sport()
    url = f"{base}/hot/{sport}?limit=5"
    try:
        r = requests.get(url, timeout=_timeout())
    except requests.RequestException as e:
        return [CheckResult("hot.json.fetch", "FAIL", str(e))]

    results: List[CheckResult] = []
    if r.status_code != 200:
        results.append(CheckResult(
            "hot.json.status", "FAIL", f"HTTP {r.status_code}"
        ))
        return results
    results.append(CheckResult("hot.json.status", "PASS", "200 OK"))

    try:
        payload = r.json()
    except ValueError as e:
        results.append(CheckResult("hot.json.parse", "FAIL", str(e)))
        return results
    results.append(CheckResult("hot.json.parse", "PASS"))

    if payload.get("sport") != sport:
        results.append(CheckResult(
            "hot.json.sport_field", "FAIL",
            f"expected sport={sport}, got {payload.get('sport')!r}"
        ))
    else:
        results.append(CheckResult("hot.json.sport_field", "PASS"))

    matches = payload.get("matches") or []
    if not isinstance(matches, list):
        results.append(CheckResult(
            "hot.json.matches_list", "FAIL", "matches is not a list"
        ))
        return results

    if not matches:
        results.append(CheckResult(
            "hot.json.matches_nonempty", "WARN",
            "matches list is empty — no active events for sport"
        ))
        return results

    results.append(CheckResult(
        "hot.json.matches_nonempty", "PASS", f"{len(matches)} returned"
    ))

    # Structural validation on the top event
    top = matches[0]
    required = ("event_id", "sport", "status", "home", "away", "tournament", "time")
    missing = [k for k in required if k not in top]
    if missing:
        results.append(CheckResult(
            "hot.json.top.structure", "FAIL",
            f"missing keys on top event: {missing}"
        ))
    else:
        results.append(CheckResult("hot.json.top.structure", "PASS"))

    # Nested team structure
    home = top.get("home") or {}
    away = top.get("away") or {}
    if home.get("name") and away.get("name"):
        results.append(CheckResult(
            "hot.json.top.teams", "PASS",
            f"{home.get('name')} vs {away.get('name')}"
        ))
    else:
        results.append(CheckResult(
            "hot.json.top.teams", "FAIL", "home/away name missing"
        ))

    # PNG sibling endpoint
    png_url = f"{base}/hot/{sport}.png"
    try:
        rp = requests.get(png_url, timeout=_timeout())
        ct = rp.headers.get("Content-Type", "")
        if rp.status_code == 200 and ct.startswith("image/png"):
            results.append(CheckResult(
                "hot.png.status",
                "PASS",
                f"200 OK image/png ({len(rp.content)} bytes, X-Cache={rp.headers.get('X-Cache', '?')})"
            ))
        else:
            results.append(CheckResult(
                "hot.png.status", "FAIL",
                f"HTTP {rp.status_code} content-type={ct!r}"
            ))
    except requests.RequestException as e:
        results.append(CheckResult("hot.png.fetch", "FAIL", str(e)))

    return results


def check_club_endpoint() -> List[CheckResult]:
    results: List[CheckResult] = []
    try:
        conn = _open_db()
        row = _q_one(conn, "SELECT slug, name FROM clubs ORDER BY created_at DESC LIMIT 1")
        conn.close()
    except Exception as e:
        return [CheckResult("club.db_pick", "FAIL", str(e))]

    if row is None:
        return [CheckResult("club.db_pick", "SKIP", "no clubs in DB to test")]

    slug = row["slug"]
    name = row["name"]
    results.append(CheckResult("club.db_pick", "PASS", f"slug={slug} name={name!r}"))

    # HTML page
    base = _base_url()
    try:
        r = requests.get(f"{base}/club/{slug}", timeout=_timeout())
    except requests.RequestException as e:
        return results + [CheckResult("club.html.fetch", "FAIL", str(e))]

    if r.status_code != 200:
        results.append(CheckResult(
            "club.html.status", "FAIL", f"HTTP {r.status_code}"
        ))
        return results
    results.append(CheckResult("club.html.status", "PASS", "200 OK"))

    body = r.text
    if name in body:
        results.append(CheckResult(
            "club.html.has_name", "PASS", "club name rendered"
        ))
    else:
        results.append(CheckResult(
            "club.html.has_name", "FAIL", "club name not found in HTML"
        ))

    # Fallback or match presence
    if "Apostar ahora" in body or "cta_url" in body or "href=" in body:
        results.append(CheckResult("club.html.cta", "PASS", "CTA element present"))
    else:
        results.append(CheckResult("club.html.cta", "WARN", "no CTA detected — template may be customised"))

    # PNG sibling endpoint
    try:
        rp = requests.get(f"{base}/club/{slug}.png", timeout=_timeout())
        ct = rp.headers.get("Content-Type", "")
        if rp.status_code == 200 and ct.startswith("image/png"):
            results.append(CheckResult(
                "club.png.status",
                "PASS",
                f"200 OK image/png ({len(rp.content)} bytes, X-Cache={rp.headers.get('X-Cache', '?')})"
            ))
        else:
            results.append(CheckResult(
                "club.png.status", "FAIL",
                f"HTTP {rp.status_code} content-type={ct!r}"
            ))
    except requests.RequestException as e:
        results.append(CheckResult("club.png.fetch", "FAIL", str(e)))

    return results


def check_legacy_render() -> List[CheckResult]:
    results: List[CheckResult] = []
    try:
        conn = _open_db()
        row = _q_one(
            conn,
            "SELECT slug FROM campaigns WHERE enabled = 1 ORDER BY created_at DESC LIMIT 1"
        )
        conn.close()
    except Exception as e:
        return [CheckResult("legacy.db_pick", "FAIL", str(e))]

    if row is None:
        return [CheckResult(
            "legacy.db_pick", "SKIP",
            "no enabled campaigns — nothing to parity-check"
        )]

    slug = row["slug"]
    base = _base_url()
    url = f"{base}/r/{slug}.png"
    try:
        # HEAD first to keep it cheap
        r = requests.head(url, timeout=_timeout(), allow_redirects=True)
    except requests.RequestException as e:
        return results + [CheckResult("legacy.head", "FAIL", str(e))]

    # Some servers may not honour HEAD for the route; fall back to GET if 405.
    if r.status_code == 405:
        try:
            r = requests.get(url, timeout=_timeout())
        except requests.RequestException as e:
            return results + [CheckResult("legacy.get_fallback", "FAIL", str(e))]

    if r.status_code != 200:
        results.append(CheckResult(
            "legacy.status", "FAIL", f"HTTP {r.status_code} for /r/{slug}.png"
        ))
        return results
    results.append(CheckResult(
        "legacy.status", "PASS", f"200 OK on /r/{slug}.png"
    ))

    ct = r.headers.get("Content-Type", "")
    if ct.startswith("image/png"):
        results.append(CheckResult("legacy.content_type", "PASS", ct))
    else:
        results.append(CheckResult(
            "legacy.content_type", "FAIL", f"unexpected content-type {ct!r}"
        ))

    dep = r.headers.get("X-Deprecated", "")
    mig = r.headers.get("X-Migrate-To", "")
    if dep.lower() == "true" and mig:
        results.append(CheckResult(
            "legacy.deprecation_headers", "PASS",
            f"X-Deprecated=true X-Migrate-To={mig}"
        ))
    else:
        results.append(CheckResult(
            "legacy.deprecation_headers", "FAIL",
            f"expected X-Deprecated=true + X-Migrate-To header"
        ))

    return results


def check_override_flow() -> List[CheckResult]:
    results: List[CheckResult] = []
    sess, reason = _login_session()
    if sess is None:
        # If creds were genuinely not provided, this is a SKIP. If creds
        # were provided but login itself failed, that's a FAIL.
        status = "SKIP" if "not set" in reason else "FAIL"
        return [CheckResult("override.login", status, reason)]
    results.append(CheckResult("override.login", "PASS"))

    base = _base_url()
    sport = _sport()
    # Pull current /hot to pick an event_id that's NOT already pinned at top.
    try:
        r = requests.get(f"{base}/hot/{sport}?limit=10", timeout=_timeout())
        r.raise_for_status()
        matches = (r.json() or {}).get("matches") or []
    except Exception as e:
        return results + [CheckResult("override.seed.fetch", "FAIL", str(e))]

    if len(matches) < 2:
        return results + [CheckResult(
            "override.seed", "SKIP",
            "need at least 2 matches in /hot to validate ordering change"
        )]

    target = matches[-1]
    target_eid = target["event_id"]
    current_top = matches[0]["event_id"]
    if target_eid == current_top:
        target = matches[1]
        target_eid = target["event_id"]
    results.append(CheckResult(
        "override.seed", "PASS",
        f"will pin event_id={target_eid} (currently below top={current_top})"
    ))

    # POST override
    try:
        r = sess.post(
            f"{base}/api/hot/override/{target_eid}",
            json={"pin": True, "boost": 100.0},
            timeout=_timeout(),
        )
    except requests.RequestException as e:
        return results + [CheckResult("override.upsert", "FAIL", str(e))]

    if r.status_code != 200:
        return results + [CheckResult(
            "override.upsert", "FAIL", f"HTTP {r.status_code} body={r.text[:200]}"
        )]
    results.append(CheckResult("override.upsert", "PASS", "POST 200 OK"))

    # Tiny pause — cache invalidation is synchronous, but give the response
    # a moment in case there's any threading hop.
    time.sleep(0.5)

    try:
        r2 = requests.get(f"{base}/hot/{sport}?limit=10", timeout=_timeout())
        r2.raise_for_status()
        new_matches = (r2.json() or {}).get("matches") or []
    except Exception as e:
        return results + [CheckResult("override.reread", "FAIL", str(e))]

    if not new_matches:
        results.append(CheckResult(
            "override.reorder", "FAIL", "/hot returned empty after override"
        ))
    elif new_matches[0]["event_id"] == target_eid:
        results.append(CheckResult(
            "override.reorder", "PASS",
            f"pinned event surfaced top within 1 request cycle"
        ))
    else:
        results.append(CheckResult(
            "override.reorder", "FAIL",
            f"expected top={target_eid}, got top={new_matches[0]['event_id']}"
        ))

    # Cleanup — DELETE the override
    try:
        rd = sess.delete(
            f"{base}/api/hot/override/{target_eid}", timeout=_timeout()
        )
        if rd.status_code == 200:
            results.append(CheckResult(
                "override.cleanup", "PASS", "DELETE 200 OK"
            ))
        else:
            results.append(CheckResult(
                "override.cleanup", "WARN",
                f"DELETE returned {rd.status_code} — manual cleanup may be needed for event_id={target_eid}"
            ))
    except requests.RequestException as e:
        results.append(CheckResult(
            "override.cleanup", "WARN", f"{e} — manual cleanup may be needed"
        ))

    return results


# ─── Reporting ──────────────────────────────────────────────────────────
def _color(status: str) -> str:
    return {
        "PASS": "\033[32m",
        "FAIL": "\033[31m",
        "WARN": "\033[33m",
        "SKIP": "\033[90m",
    }.get(status, "")


RESET = "\033[0m"
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _fmt(status: str) -> str:
    if USE_COLOR:
        return f"{_color(status)}{status:<5}{RESET}"
    return f"{status:<5}"


def _print_section(title: str, rows: List[CheckResult]) -> None:
    print(f"\n=== {title} ===")
    for r in rows:
        line = f"  [{_fmt(r.status)}] {r.name}"
        if r.detail:
            line += f"   {r.detail}"
        print(line)


def main() -> int:
    print(f"Phase B health check  •  base={_base_url()}  •  sport={_sport()}  •  db={_db_path()}")

    sections: List[Tuple[str, Callable[[], List[CheckResult]]]] = [
        ("DB Health", check_db_health),
        ("Hot Endpoint", check_hot_endpoint),
        ("Club Endpoint", check_club_endpoint),
        ("Legacy Render Parity", check_legacy_render),
        ("Override Flow", check_override_flow),
    ]

    all_results: List[CheckResult] = []
    for title, fn in sections:
        try:
            rows = fn()
        except Exception as e:
            rows = [CheckResult(f"{title.lower().replace(' ', '_')}.exception", "FAIL", repr(e))]
        _print_section(title, rows)
        all_results.extend(rows)

    n_pass = sum(1 for r in all_results if r.status == "PASS")
    n_fail = sum(1 for r in all_results if r.status == "FAIL")
    n_warn = sum(1 for r in all_results if r.status == "WARN")
    n_skip = sum(1 for r in all_results if r.status == "SKIP")
    print(f"\nSummary: {n_pass} PASS  {n_fail} FAIL  {n_warn} WARN  {n_skip} SKIP")

    # ── Alerting layer (additive, never affects exit code) ──
    # FAIL → critical alert; WARN-only → lighter notification; all-PASS → silent.
    try:
        base = _base_url()
        if n_fail > 0:
            failed_names = [r.name for r in all_results if r.status == "FAIL"][:10]
            send_telegram_alert(
                f"❌ Phase B FAILED on {base}. Check logs immediately.\n"
                f"{n_fail} FAIL / {n_warn} WARN / {n_pass} PASS\n"
                f"Failing checks: {', '.join(failed_names) if failed_names else '(none)'}"
            )
        elif n_warn > 0:
            warn_names = [r.name for r in all_results if r.status == "WARN"][:10]
            send_telegram_alert(
                f"⚠️ Phase B has {n_warn} warning(s) on {base}.\n"
                f"Warnings: {', '.join(warn_names) if warn_names else '(none)'}"
            )
    except Exception:
        # Alerting must never affect the health check exit contract.
        pass

    return 1 if n_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
