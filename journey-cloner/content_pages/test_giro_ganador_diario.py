#!/usr/bin/env python3
"""
Regression net for giro_ganador_diario.html.

Two suites over a real browser:
  · the offline simulation (data-mock="1") -- reels, two turns, no storage
  · the REAL code path -- fetch intercepted, so realApi, the platform's
    config shape, all four prizes by their true prizeId, the empty prize,
    a 500 plus the idempotent retry, and a reload with the turn already
    settled server-side

Needs playwright and a chromium; skips cleanly (exit 0) without them, so it
is safe to run anywhere. Unlike the other scripts/test_*.py it is NOT
dependency-free -- run it deliberately after editing the page:

    pip install playwright        # PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 if a
    python test_giro_ganador_diario.py    # chromium is already present

These checks exist because all three of the following shipped green once:
  1. `transform: ... !important` on the reel froze it -- author !important
     beats inline styles AND keyframes, so the reels never moved.
  2. A late `document.fonts.ready` reset the reels off the winning
     combination while the copy still announced the prize.
  3. `reveal()` advances `active` to the next day, so the claim went to the
     WRONG randomizer with a null turnId and the prize was never claimed.
"""

from __future__ import annotations

import contextlib
import functools
import glob
import http.server
import json
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE / "giro_ganador_diario.html"
PORT = 8791

# ids reales del template: templates/casino/casino_wof_randomizer.json
PIDS = [
    "3b286e69-b355-420a-a960-4db936a874c4",
    "65ed8cee-45b8-48bc-9ef3-69149b78a6d3",
    "f1804fa5-a469-4493-9c9a-420c1f89dd86",
    "0feeaefe-08a0-4a85-bcff-b572b47e3d1b",
]
TITLES = [
    "Giros gratis con tu depósito",
    "Bono de casino con tu depósito",
    "20 giros gratis, sin depósito",
    "Bono de casino sin depósito",
]
SLUG1, SLUG2 = "casino-wof-19-09-2026", "casino-wof-20-09-2026"

# lee el simbolo que quedo sobre la linea de pago, desde los transforms reales
PAYLINE = r"""() => Array.prototype.map.call(document.querySelectorAll('.gg-reel'), function (r) {
  var lane = r.querySelector('.gg-lane'), strip = r.querySelector('.gg-strip');
  function ty(el) {
    var t = getComputedStyle(el).transform;
    if (!t || t === 'none') { return 0; }
    var p = t.slice(t.indexOf('(') + 1, t.indexOf(')')).split(',');
    return parseFloat(p.length === 16 ? p[13] : p[5]) || 0;
  }
  var h = strip.children[0].getBoundingClientRect().height;
  var cell = strip.children[Math.round(1 - (ty(lane) + ty(strip)) / h)];
  return cell ? (cell.className.match(/gg-s(\d)/) || [])[1] : null;
})"""

STATE = r"""() => ({
  tag: document.getElementById('ggtag').hidden ? null : document.getElementById('ggtag').textContent,
  ttl: document.getElementById('ggttl').hidden ? null : document.getElementById('ggttl').textContent,
  body: document.getElementById('ggbody').hidden ? null : document.getElementById('ggbody').textContent,
  cta: document.getElementById('ggctawrap').hidden ? null : document.getElementById('ggcta').textContent,
  note: document.getElementById('ggnote').hidden ? null : document.getElementById('ggnote').textContent,
  fine: document.getElementById('ggfine').textContent,
  btn: document.getElementById('ggspin').textContent,
  btnOff: document.getElementById('ggspin').disabled,
  actHidden: document.getElementById('ggact').hidden,
  errT: document.getElementById('ggerr').hidden ? null : document.getElementById('ggerrt').textContent,
  trace: document.getElementById('ggtrace').hidden ? null : document.getElementById('ggtrace').textContent,
  wait: document.getElementById('ggwait').hidden ? null :
        document.getElementById('ggwaith').textContent + ' / ' + document.getElementById('ggwaitt').textContent,
  days: Array.prototype.map.call(document.querySelectorAll('.gg-day'), function (d) {
    return { label: d.querySelector('.gg-dnum').textContent,
             state: d.querySelector('.gg-dstate').textContent,
             won: d.className.indexOf('is-won') !== -1, hidden: d.hidden };
  }),
  won: document.getElementById('gg').className.indexOf('is-won') !== -1,
  payline: getComputedStyle(document.querySelector('.gg-payline')).opacity,
  storage: (function () {
    try { return Object.keys(localStorage).length + Object.keys(sessionStorage).length; }
    catch (e) { return -1; }
  }())
})"""

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    RESULTS.append((bool(ok), msg))


def wrap(mock: bool, out: Path) -> None:
    subprocess.run(
        [sys.executable, str(HERE / "preview.py"), str(PAGE), "-o", str(out)]
        + (["--mock"] if mock else []),
        check=True, capture_output=True,
    )


def chromium() -> str | None:
    for pat in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                "/opt/pw-browsers/chromium/chrome-linux/chrome"):
        hit = sorted(glob.glob(pat))
        if hit:
            return hit[-1]
    return None


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: ANN002
        pass


class _QuietServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        pass


@contextlib.contextmanager
def serving(directory: Path):
    """El blob pide rutas absolutas (/service-discovery/...), asi que hay que
    servirlo por http: sobre file:// esas peticiones no se pueden interceptar."""
    srv = _QuietServer(("127.0.0.1", PORT),
                       functools.partial(_QuietHandler, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{PORT}"
    finally:
        srv.shutdown()
        srv.server_close()


def block_fonts(pg) -> None:
    """Las fuentes de Google pueden estar bloqueadas y la peticion queda
    colgada; ademas resolver fonts.ready TARDE es justo la condicion que
    reseteaba la cinta despues de ganar. Cortarlas reproduce el fallo."""
    pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    pg.route("**/fonts.gstatic.com/**", lambda r: r.abort())


def cfg(rid: str, turns=None) -> dict:
    return {
        "id": rid, "status": "Active",
        "timeline": {"finishDate": "2026-09-21T03:58:00Z"},
        "prizes": [{"prizeId": p, "weight": w} for p, w in zip(PIDS, [60, 35, 5, 0])],
        "playerProgress": {"playerTurns": turns or []},
    }


# ─────────────────────────── suite 1: simulacion ───────────────────────────
def suite_mock(browser, base: str) -> None:
    pg = browser.new_page(viewport={"width": 1180, "height": 900})
    block_fonts(pg)
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(base + "/mock.html")
    pg.wait_for_function("() => !document.getElementById('ggspin').disabled", timeout=15000)

    check(pg.evaluate("() => document.querySelectorAll('.gg-strip')[0].children.length") == 66,
          "strip built with 66 cells")
    rest = pg.evaluate(PAYLINE)
    check(len(set(rest)) == 3, f"reels rest on three different symbols (got {rest})")
    s = pg.evaluate(STATE)
    check(s["payline"] == "0", "payline dark before any spin")
    check(s["ttl"] is None, "no prize copy before spinning")
    check(s["days"][0]["state"] == "Tu giro de hoy", "day 1 armed")

    pg.click("#ggspin")
    pg.wait_for_timeout(400)
    check(pg.evaluate("() => document.querySelectorAll('.gg-reel.is-rolling').length") == 3,
          "stage 1: all three reels roll while the request is in flight")
    check(pg.evaluate("() => document.getElementById('ggfine').textContent") == "Girando…",
          "stage 1 hint")

    pg.wait_for_function("() => document.getElementById('gg').className.indexOf('is-won') !== -1",
                         timeout=20000)
    pg.wait_for_timeout(600)
    check(pg.evaluate(PAYLINE) == ["0", "0", "0"], "stage 2: three of a kind on prize 0")
    s = pg.evaluate(STATE)
    check(float(s["payline"]) > 0.9, "payline lit on the win")
    check(s["ttl"] == TITLES[0], f"prize 0 title (got {s['ttl']!r})")
    check("20, 40, 60 u 80" in (s["body"] or ""),
          "prize 0 body names the whole tier ladder, never a single number")
    check(s["note"] == "Ya está acreditado.", f"claim stamp reached the note (got {s['note']!r})")
    check(s["days"][0]["won"], "day 1 card marked won")
    check(s["btn"] == "Girar de nuevo", "a second spin is offered while day 2 is open")

    # las tres regresiones que un dia pasaron en verde
    pg.wait_for_timeout(900)
    check(pg.evaluate(PAYLINE) == ["0", "0", "0"], "a late fonts.ready does NOT reset the win")
    pg.set_viewport_size({"width": 900, "height": 940})
    pg.wait_for_timeout(400)
    check(pg.evaluate(PAYLINE) == ["0", "0", "0"], "a resize after the win keeps three of a kind")
    pg.set_viewport_size({"width": 1180, "height": 900})
    pg.wait_for_timeout(250)

    pg.click("#ggspin")
    pg.wait_for_timeout(300)
    check(pg.evaluate("() => document.getElementById('gg').className.indexOf('is-won') !== -1") is False,
          "the old result is cleared while spin 2 is in flight")
    pg.wait_for_function("() => document.getElementById('gg').className.indexOf('is-won') !== -1",
                         timeout=20000)
    pg.wait_for_timeout(600)
    check(pg.evaluate(PAYLINE) == ["1", "1", "1"], "spin 2 lands prize 1")
    s = pg.evaluate(STATE)
    check(s["ttl"] == TITLES[1], f"prize 1 title (got {s['ttl']!r})")
    check(s["wait"] == "Usaste tus dos giros / Gracias por jugar. Revisa tus premios en tu cuenta.",
          f"both turns spent -> end-of-promo panel (got {s['wait']!r})")
    check(s["actHidden"], "spin button gone once both turns are spent")

    before = pg.evaluate(PAYLINE)
    pg.evaluate("() => document.getElementById('ggspin').click()")
    pg.wait_for_timeout(700)
    check(pg.evaluate(PAYLINE) == before, "clicking the hidden button cannot spin a third time")
    check(pg.evaluate(STATE)["storage"] == 0,
          "the page wrote nothing to localStorage/sessionStorage")
    check(not errors, f"no uncaught page errors (got {errors})")
    pg.close()


# ─────────────────────── suite 2: camino real (fetch) ───────────────────────
def real_page(browser, base: str, *, prize=None, empty=False, fail_first=False,
              turns=None, unknown=False):
    seen = {"turns": [], "calls": 0, "claims": []}
    pg = browser.new_page(viewport={"width": 1180, "height": 900})
    block_fonts(pg)
    logs: list[str] = []
    pg.on("console", lambda m: logs.append(m.text))
    pg.on("pageerror", lambda e: logs.append("PAGEERROR: " + str(e)))

    def handler(route):
        u = route.request.url
        j = lambda st, b: route.fulfill(status=st, content_type="application/json", body=json.dumps(b))
        if "/url-short-name/" in u:
            if SLUG1 in u:
                return j(200, cfg("rand-day-1", turns))
            # dia 2: en produccion el randomizer de manana todavia no existe
            return j(404, {"message": "NotFound", "traceId": "trace-404"})
        if "/turn/" in u:
            seen["calls"] += 1
            seen["turns"].append(u.rsplit("/", 1)[-1])
            if fail_first and seen["calls"] == 1:
                return j(500, {"message": "Upstream exploded", "traceId": "trace-abc123"})
            pid = "no-such-prize-id" if unknown else PIDS[prize]
            return j(200, {"playerPrize": {"prizeId": pid, "isEmptyPrize": empty}})
        if "/claim-prize/" in u:
            seen["claims"].append(u.rsplit("/", 1)[-1])
            return j(200, {"prizeClaimedAt": "2026-09-19T12:00:00Z"})
        return j(404, {})

    pg.route("**/service-discovery/**", handler)
    pg.goto(base + "/real.html")
    pg.wait_for_function(
        "() => document.getElementById('ggfine').textContent !== 'Cargando…'"
        " || !document.getElementById('ggwait').hidden"
        " || !document.getElementById('ggerr').hidden", timeout=15000)
    pg.wait_for_timeout(200)
    return pg, seen, logs


def suite_real(browser, base: str) -> None:
    # boot: dia 1 abierto, dia 2 aun invisible
    pg, seen, logs = real_page(browser, base)
    s = pg.evaluate(STATE)
    check(s["btnOff"] is False, "day-1 config loaded over real fetch -> spin enabled")
    check(s["days"][0]["state"] == "Tu giro de hoy", "day 1 armed")
    check(s["days"][1]["state"] == "Pendiente",
          f"a 404 on tomorrow's randomizer reads 'Pendiente' (got {s['days'][1]['state']!r})")
    check(s["errT"] is None, "a 404 on tomorrow's randomizer does NOT error the page")
    pg.close()

    # las cuatro combinaciones, por prizeId real
    for ix, want in enumerate(TITLES):
        pg, seen, logs = real_page(browser, base, prize=ix)
        pg.click("#ggspin")
        pg.wait_for_function("() => document.getElementById('gg').className.indexOf('is-won') !== -1",
                             timeout=20000)
        pg.wait_for_timeout(700)
        s = pg.evaluate(STATE)
        check(s["ttl"] == want, f"prize {ix} ({PIDS[ix][:8]}) -> {want!r} (got {s['ttl']!r})")
        check(pg.evaluate(PAYLINE) == [str(ix)] * 3, f"prize {ix} lands symbol {ix} three times")
        check(seen["claims"] == seen["turns"],
              f"prize {ix} auto-claimed against the turn just played (claims {seen['claims']})")
        check(s["wait"] == "Ya jugaste hoy / Vuelve mañana por tu segundo giro.",
              f"prize {ix} -> come-back-tomorrow (got {s['wait']!r})")
        check(s["days"][1]["state"] == "Pendiente", f"prize {ix}: no phantom second spin today")
        pg.close()

    # premio vacio
    pg, seen, logs = real_page(browser, base, prize=0, empty=True)
    pg.click("#ggspin")
    pg.wait_for_function("() => document.getElementById('gg').className.indexOf('is-won') !== -1",
                         timeout=20000)
    pg.wait_for_timeout(500)
    s = pg.evaluate(STATE)
    check(s["ttl"] == "No salió premio", f"isEmptyPrize -> empty copy (got {s['ttl']!r})")
    check(s["cta"] is None, "empty prize offers no deposit CTA")
    pg.close()

    # premio sin copy: no inventa cifra, avisa
    pg, seen, logs = real_page(browser, base, prize=0, unknown=True)
    pg.click("#ggspin")
    pg.wait_for_function("() => document.getElementById('gg').className.indexOf('is-won') !== -1",
                         timeout=20000)
    pg.wait_for_timeout(500)
    s = pg.evaluate(STATE)
    check(s["ttl"] == "Tu premio quedó asignado",
          f"a prize with no configured copy gets a safe generic (got {s['ttl']!r})")
    check(s["cta"] is None, "unknown prize offers no CTA")
    check(any("sin copy configurada" in l for l in logs),
          "unknown prize warns the operator in the console")
    pg.close()

    # fallo + reintento idempotente
    pg, seen, logs = real_page(browser, base, prize=2, fail_first=True)
    pg.click("#ggspin")
    pg.wait_for_function("() => !document.getElementById('ggerr').hidden", timeout=20000)
    s = pg.evaluate(STATE)
    check("HTTP 500" in (s["trace"] or ""), f"status shown on the technical line (got {s['trace']!r})")
    check("trace-abc123" in (s["trace"] or ""), "traceId surfaced for support")
    check("Upstream exploded" in (s["trace"] or ""), "server message goes to the technical line...")
    check("Upstream exploded" not in (s["errT"] or ""), "...and never into the player copy")
    check(s["errT"] == "Tu giro no se perdió. Prueba de nuevo.", "player sees reassuring copy")
    pg.click("#ggretry")
    pg.wait_for_function("() => document.getElementById('gg').className.indexOf('is-won') !== -1",
                         timeout=20000)
    pg.wait_for_timeout(500)
    check(len(set(seen["turns"])) == 1,
          f"retry re-PUTs the SAME playerTurnId (ids {set(seen['turns'])})")
    check(seen["calls"] == 2, f"exactly one retry (got {seen['calls']} turn calls)")
    check(pg.evaluate(STATE)["ttl"] == TITLES[2], "retry reveals the prize")
    pg.close()

    # vuelta con la tirada ya resuelta en el servidor
    settled = [{"playerTurnId": "srv-turn-1",
                "playerPrize": {"prizeId": PIDS[1], "isEmptyPrize": False},
                "prizeReceivedAt": "2026-09-19T10:00:00Z", "prizeClaimedAt": None}]
    pg, seen, logs = real_page(browser, base, turns=settled)
    pg.wait_for_timeout(400)
    s = pg.evaluate(STATE)
    check(s["btnOff"] is True, "server says the turn is spent -> no spin offered on reload")
    check(s["days"][0]["state"] == TITLES[1],
          f"reload paints the settled prize from the server (got {s['days'][0]['state']!r})")
    check(seen["claims"] == ["srv-turn-1"],
          f"an unclaimed settled turn is auto-claimed on load (got {seen['claims']})")
    pg.close()


# ───────────────────────────── invariantes del blob ─────────────────────────
def suite_source() -> None:
    src = PAGE.read_text(encoding="utf-8")
    js = re.search(r'<script type="text/javascript">(.*)</script>', src, re.S).group(1)
    css = re.search(r'<style type="text/css">(.*?)</style>', src, re.S).group(1)
    check(js.count("<") == 0, "script contains no '<' (CKEditor would escape it)")
    check(js.count("&") == 0, "script contains no '&'")
    check(css.count("&") == 0 and css.count("<") == 0, "style block contains no '&' or '<'")
    check(css.count(">") == 0, "style block uses no '>' combinators")
    stray = [l for l in src.split("\n") if "&" in l and "&nbsp;" not in l]
    check(not stray, f"the only ampersands are &nbsp; (stray: {stray[:2]})")
    # sin comentarios: el propio archivo MENCIONA que no usa storage
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    check("sessionStorage" not in code and "localStorage" not in code,
          "the page has no browser-storage code path at all")
    for prop in ("transform:translateY(0) !important",):
        check(prop not in css,
              f"no '{prop}' -- author !important would freeze the reels")
    for k in ("unknownTtl", "unknownBody", "emptyTtl", "lockedH", "doneH", "endedH"):
        check(f'"{k}"' in src, f"data-copy defines {k}")
    for a in re.findall(r"data-(?:prize-\w+|copy|days)='([^']*)'", src):
        json.loads(a)
    check(True, "every data-* JSON attribute parses")
    labels = json.loads(re.search(r"data-prize-labels='([^']*)'", src).group(1))
    check([labels.get(str(i)) for i in range(4)] == TITLES,
          "all four prize positions have configured copy")


def main() -> int:
    suite_source()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed -- ran source checks only "
              "(pip install playwright to run the browser suites)\n")
        return report()
    exe = chromium()
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        wrap(True, d / "mock.html")
        wrap(False, d / "real.html")
        with serving(d) as base:
            with sync_playwright() as pw:
                try:
                    browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
                except Exception as exc:  # noqa: BLE001
                    print(f"could not launch chromium ({exc}) -- source checks only\n")
                    return report()
                try:
                    suite_mock(browser, base)
                    suite_real(browser, base)
                finally:
                    browser.close()
    return report()


def report() -> int:
    bad = [m for ok, m in RESULTS if not ok]
    for ok, m in RESULTS:
        print(("  [OK]   " if ok else "  [FAIL] ") + m)
    print()
    if bad:
        print(f"FAILED ({len(bad)}):")
        for m in bad:
            print("  - " + m)
        return 1
    print(f"All {len(RESULTS)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
