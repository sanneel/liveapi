"""Extract the embedded odds JSON from the raw World Cup HTML.

Probe A proved a plain HTTP GET already contains 137 odds in an embedded JSON
blob (Angular transfer-state). This finds that blob and maps its shape so we can
parse event -> market -> outcome -> price directly, with no browser.

It:
  1. GETs the overlay HTML.
  2. Parses every <script> whose body is JSON.
  3. Prints each JSON blob's top-level keys (transfer-state keys are often the
     real API URLs the SSR used -> a directly-callable odds endpoint).
  4. Walks for "outcome-like" dicts (any field that looks like odds, 1.01-1000,
     2 decimals) and prints samples with their path + parent object.
  5. Saves the biggest JSON blob to /tmp/jb_state.json for deeper inspection.

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_state_blob.py
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.request
from pathlib import Path

OVERLAY = (
    "https://jugabet.cl/football/all/1"
    "?tournaments=c19cb5ffb4404c31b869b53dd90161de"  # FIFA World Cup 2026
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
OUT = Path("/tmp/jb_state.json")


def _looks_like_odds(value) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return 1.01 <= f <= 1000.0


def _try_json(body: str):
    body = body.strip()
    if not body or body[0] not in "{[":
        return None
    for candidate in (body, _html.unescape(body)):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def walk_outcomes(obj, path="", out=None, depth=0):
    """Yield (path, dict) for dicts that carry an odds-looking value."""
    if out is None:
        out = []
    if len(out) >= 8 or depth > 25:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _looks_like_odds(v) and len(str(k)) <= 16:
                out.append((path or "/", k, obj))
                break
        for k, v in obj.items():
            walk_outcomes(v, f"{path}/{k}", out, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:60]):
            walk_outcomes(v, f"{path}[{i}]", out, depth + 1)
    return out


def main() -> None:
    req = urllib.request.Request(OVERLAY, headers={"User-Agent": UA, "Accept-Language": "es-CL"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html_text = r.read().decode("utf-8", "ignore")
    print(f"raw bytes={len(html_text)}")

    blobs = []
    for body in SCRIPT_RE.findall(html_text):
        data = _try_json(body)
        if data is not None:
            blobs.append((len(body), data))
    blobs.sort(key=lambda x: x[0], reverse=True)
    print(f"JSON <script> blobs found: {len(blobs)}")

    best = None
    for size, data in blobs:
        keys = list(data.keys()) if isinstance(data, dict) else f"[list len={len(data)}]"
        flat = json.dumps(data)[:200]
        has_odds = bool(re.search(r"\d+\.\d{2}", json.dumps(data)[:200000]))
        print(f"\n--- blob size={size} type={type(data).__name__} has_odds={has_odds} ---")
        if isinstance(data, dict):
            shown = keys[:25]
            for kk in shown:
                print(f"   key: {str(kk)[:120]}")
            if len(keys) > 25:
                print(f"   ... (+{len(keys) - 25} more keys)")
        print(f"   head: {flat}")
        if has_odds and best is None:
            best = data

    if best is None and blobs:
        best = blobs[0][1]

    if best is not None:
        OUT.write_text(json.dumps(best, ensure_ascii=False), encoding="utf-8")
        print(f"\nsaved biggest/odds blob -> {OUT}")
        print("\n=== outcome-like dicts (path | odds-key | object) ===")
        for path, key, obj in walk_outcomes(best):
            compact = json.dumps(obj, ensure_ascii=False)[:280]
            print(f"\n  PATH: {path}")
            print(f"  ODDS KEY: {key}")
            print(f"  OBJ: {compact}")
    else:
        print("no JSON blob parsed; odds may be in a non-JSON inline format")


if __name__ == "__main__":
    main()
