"""Show the raw bytes around the odds so we can see their exact format.

probe_state_blob found 0 clean JSON <script> blobs, yet the raw HTML holds 137
odds + 'cuota'. So they live in some non-JSON inline form. This dumps:
  1. Every <script> opening tag (id/type/src) + first 80 chars of its body.
  2. Context windows around the first odds numbers.
  3. Context around 'cuota'.
  4. Presence of known SSR/state markers.
Saves the raw HTML to /tmp/jb_raw.html.

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_raw_context.py
"""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

OVERLAY = (
    "https://jugabet.cl/football/all/1"
    "?tournaments=c19cb5ffb4404c31b869b53dd90161de"
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ODDS_RE = re.compile(r"\b\d+\.\d{2}\b")
SCRIPT_OPEN_RE = re.compile(r"<script([^>]*)>", re.IGNORECASE)
SCRIPT_FULL_RE = re.compile(r"<script([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)
OUT = Path("/tmp/jb_raw.html")


def collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    req = urllib.request.Request(OVERLAY, headers={"User-Agent": UA, "Accept-Language": "es-CL"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "ignore")
    OUT.write_text(html, encoding="utf-8")
    print(f"raw bytes={len(html)}  saved -> {OUT}")

    # 1) script tags
    tags = SCRIPT_FULL_RE.findall(html)
    print(f"\n=== {len(tags)} <script>...</script> blocks ===")
    for i, (attrs, body) in enumerate(tags[:40]):
        head = collapse(body)[:80]
        print(f"[{i}] <script{attrs[:90]}> len={len(body)} head={head!r}")

    # 2) odds context
    print("\n=== context around first odds numbers ===")
    seen_spans = []
    for m in ODDS_RE.finditer(html):
        s = m.start()
        if any(abs(s - p) < 120 for p in seen_spans):
            continue
        seen_spans.append(s)
        ctx = collapse(html[max(0, s - 180): s + 180])
        print(f"\n  @{s} ...{ctx}...")
        if len(seen_spans) >= 6:
            break

    # 3) cuota context
    print("\n=== context around 'cuota' ===")
    low = html.lower()
    start = 0
    for _ in range(3):
        idx = low.find("cuota", start)
        if idx == -1:
            break
        print(f"\n  @{idx} ...{collapse(html[max(0, idx - 160): idx + 160])}...")
        start = idx + 5

    # 4) state markers
    print("\n=== SSR / state markers present? ===")
    for marker in (
        "__NEXT_DATA__", "ng-state", "__INITIAL_STATE__", "window.__", "self.__",
        "transferState", "TransferState", "application/json", "STATE__",
        "outcomeId", "marketId", "eventId", "competitors", "selectionId", "price",
        "coefficient",
    ):
        print(f"   {marker:18} : {marker in html}")


if __name__ == "__main__":
    main()
