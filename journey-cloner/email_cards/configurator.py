#!/usr/bin/env python3
"""Slot-card configurator — drop a PNG, get the card PNG + flip GIF.

A tiny local web tool. You drop a slot-game image into the browser, pick the
suit (deposit tier) and free-spins count, and it renders the same premium Ace
card used in the email, with your image dropped into the artwork well, plus the
front <-> JUGABET-back flip GIF for email.

Run it on the machine that has Chromium (the same one render_cards.py uses):

    python configurator.py --host 127.0.0.1 --port 8099

then open http://127.0.0.1:8099 in a browser. Nothing is uploaded anywhere —
the image is processed locally and the results are handed straight back.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import render_cards as R
import make_gif as G

# Accepted dropped-image mime -> file extension for the temp handoff.
_DATA_URI_RE = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,(.+)$", re.DOTALL)

SUIT_LABELS = {
    "hearts": "♥ Hearts",
    "diamonds": "♦ Diamonds",
    "clubs": "♣ Clubs",
    "spades": "♠ Spades",
}


def _suit_index(name: str) -> int:
    for i, s in enumerate(R.SUITS):
        if s[0] == name:
            return i
    raise ValueError(f"unknown suit: {name}")


def _b64_data_uri(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _render(suit: str, free_spins: str, game_uri: str, gif_width: int) -> dict:
    """Render the front PNG and the flip GIF for one suit, both as data URIs."""
    idx = _suit_index(suit)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        png_path = tmp / "front.png"
        R.render_png(R.single_html(idx, free_spins, game_uri), png_path, scale=2)
        gif_path = G.make_one(idx, free_spins, gif_width, tmp, game_uri)
        return {
            "front_png": _b64_data_uri(png_path.read_bytes(), "image/png"),
            "flip_gif": _b64_data_uri(gif_path.read_bytes(), "image/gif"),
            "gif_name": gif_path.name,
        }


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Slot Card Configurator · JugaBet</title>
<style>
  :root{ color-scheme:dark; --bg:#0b0d11; --panel:#15181f; --line:#232833;
    --text:#e7e9ee; --muted:#8a93a3; --lime:#c2e325; --gold:#d4af37; }
  *{ box-sizing:border-box; }
  body{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--text); }
  main{ max-width:1000px; margin:0 auto; padding:28px 18px 60px; }
  h1{ margin:0 0 4px; font-size:23px; }
  p.sub{ margin:0 0 22px; color:var(--muted); font-size:13.5px; }
  .layout{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }
  @media(max-width:760px){ .layout{ grid-template-columns:1fr; } }
  .panel{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px; }
  label{ display:block; font-size:12px; color:var(--muted); margin:14px 0 6px; text-transform:uppercase; letter-spacing:.4px; }
  select,input[type=number]{ width:100%; background:#0f1218; color:var(--text); border:1px solid var(--line);
    border-radius:8px; padding:10px 11px; font-size:14px; }
  .drop{ margin-top:6px; border:2px dashed #33404f; border-radius:12px; min-height:190px; display:flex;
    align-items:center; justify-content:center; text-align:center; padding:16px; cursor:pointer;
    color:var(--muted); font-size:13px; transition:border-color .15s,background .15s; position:relative; overflow:hidden; }
  .drop.hover{ border-color:var(--lime); background:rgba(194,227,37,.06); color:var(--text); }
  .drop img{ position:absolute; inset:0; width:100%; height:100%; object-fit:contain; background:#0b0d11; }
  .hint{ font-size:11.5px; color:#6c7686; margin-top:8px; line-height:1.5; }
  button.go{ margin-top:18px; width:100%; border:0; border-radius:999px; padding:13px; font-weight:800;
    font-size:15px; letter-spacing:.03em; cursor:pointer; background:var(--lime); color:#12140f; }
  button.go:disabled{ opacity:.5; cursor:default; }
  .result{ display:flex; flex-direction:column; align-items:center; gap:14px; }
  .stage{ width:100%; max-width:300px; aspect-ratio:360/650; background:#0b0d11; border:1px solid var(--line);
    border-radius:12px; overflow:hidden; display:flex; align-items:center; justify-content:center; }
  .stage img{ width:100%; height:100%; object-fit:contain; }
  .dl{ display:flex; gap:10px; flex-wrap:wrap; justify-content:center; }
  .dl a{ text-decoration:none; font-size:13px; font-weight:700; padding:9px 14px; border-radius:8px;
    background:#1c2330; color:var(--text); border:1px solid var(--line); }
  .dl a.primary{ background:var(--gold); color:#151203; border-color:var(--gold); }
  .empty{ color:var(--muted); font-size:13px; text-align:center; padding:40px 10px; }
  .spin{ display:inline-block; width:15px; height:15px; border:2px solid rgba(0,0,0,.35);
    border-top-color:#12140f; border-radius:50%; animation:sp .7s linear infinite; vertical-align:-2px; margin-right:8px; }
  @keyframes sp{ to{ transform:rotate(360deg); } }
  .err{ color:#f87171; font-size:13px; margin-top:10px; }
</style>
</head>
<body>
<main>
  <h1>Slot Card Configurator</h1>
  <p class="sub">Drop a slot-game image → get the Ace card PNG and the email flip GIF, with your art in the well.</p>
  <div class="layout">
    <section class="panel">
      <label for="drop">Slot game image</label>
      <div class="drop" id="drop">
        <span id="drop-text">Drop a PNG/JPG here, or click to choose.<br>Best fit: ~360×300 (well is 360×300).</span>
        <input type="file" id="file" accept="image/*" hidden>
      </div>
      <p class="hint">The image is cropped to fill the black artwork well (object-fit: cover). Nothing is uploaded — it is rendered locally.</p>

      <label for="suit">Suit / deposit tier</label>
      <select id="suit"></select>

      <label for="fs">Free spins</label>
      <input type="number" id="fs" value="50" min="1" max="999">

      <label for="w">GIF width (px)</label>
      <input type="number" id="w" value="300" min="120" max="500">

      <button class="go" id="go" disabled>Generate card + GIF</button>
      <div class="err" id="err"></div>
    </section>

    <section class="panel">
      <div id="result" class="result">
        <div class="empty">Your generated flip GIF will appear here.</div>
      </div>
    </section>
  </div>
</main>
<script>
(function(){
  var SUITS = __SUITS__;               // [{value,label,deposit,bet}]
  var sel = document.getElementById('suit');
  SUITS.forEach(function(s){
    var o = document.createElement('option');
    o.value = s.value; o.textContent = s.label + '  ·  Deposit ' + s.deposit + ' / Spin ' + s.bet;
    sel.appendChild(o);
  });

  var drop = document.getElementById('drop'), file = document.getElementById('file'),
      dropText = document.getElementById('drop-text'), go = document.getElementById('go'),
      err = document.getElementById('err'), result = document.getElementById('result');
  var gameDataUri = '';

  function setImage(dataUri){
    gameDataUri = dataUri;
    var img = drop.querySelector('img'); if(img) img.remove();
    if(dataUri){
      var i = document.createElement('img'); i.src = dataUri; drop.appendChild(i);
      dropText.style.display = 'none'; go.disabled = false;
    } else { dropText.style.display = ''; go.disabled = true; }
  }
  function readFile(f){
    if(!f || !/^image\\//.test(f.type)){ err.textContent = 'Please choose an image file.'; return; }
    err.textContent = '';
    var r = new FileReader(); r.onload = function(){ setImage(r.result); }; r.readAsDataURL(f);
  }

  drop.addEventListener('click', function(){ file.click(); });
  file.addEventListener('change', function(){ readFile(file.files[0]); });
  ['dragenter','dragover'].forEach(function(e){ drop.addEventListener(e, function(ev){ ev.preventDefault(); drop.classList.add('hover'); }); });
  ['dragleave','drop'].forEach(function(e){ drop.addEventListener(e, function(ev){ ev.preventDefault(); drop.classList.remove('hover'); }); });
  drop.addEventListener('drop', function(ev){ readFile(ev.dataTransfer.files[0]); });

  go.addEventListener('click', function(){
    if(!gameDataUri) return;
    err.textContent = '';
    go.disabled = true;
    var label = go.textContent; go.innerHTML = '<span class="spin"></span>Rendering…';
    result.innerHTML = '<div class="empty">Rendering the card and flip GIF (a few seconds)…</div>';
    fetch('/generate', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ suit: sel.value, free_spins: String(document.getElementById('fs').value||'50'),
        gif_width: parseInt(document.getElementById('w').value||'300',10), game: gameDataUri })
    }).then(function(r){ return r.json(); }).then(function(d){
      go.disabled = false; go.textContent = label;
      if(d.error){ err.textContent = d.error; result.innerHTML = '<div class="empty">—</div>'; return; }
      result.innerHTML =
        '<div class="stage"><img src="'+d.flip_gif+'" alt="flip gif"></div>' +
        '<div class="dl">' +
          '<a class="primary" download="'+d.gif_name+'" href="'+d.flip_gif+'">⬇ Download GIF</a>' +
          '<a download="card_front.png" href="'+d.front_png+'">⬇ Download PNG</a>' +
        '</div>';
    }).catch(function(e){
      go.disabled = false; go.textContent = label;
      err.textContent = 'Render failed: ' + e;
      result.innerHTML = '<div class="empty">—</div>';
    });
  });
})();
</script>
</body>
</html>"""


def _page() -> bytes:
    suits = [
        {"value": s[0], "label": SUIT_LABELS.get(s[0], s[0]), "deposit": s[2], "bet": s[3]}
        for s in R.SUITS
    ]
    return PAGE.replace("__SUITS__", json.dumps(suits)).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        self._send(200, "text/html; charset=utf-8", _page())

    def do_POST(self) -> None:
        if self.path != "/generate":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            # generous cap (~24MB) for a dropped image encoded as base64
            if length > 24 * 1024 * 1024:
                return self._json(413, {"error": "Image too large (max ~18MB)."})
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "Bad request."})

        suit = str(data.get("suit", "")).strip()
        free_spins = str(data.get("free_spins", "50")).strip() or "50"
        gif_width = int(data.get("gif_width", 300) or 300)
        gif_width = max(120, min(500, gif_width))
        game = str(data.get("game", ""))

        if suit not in SUIT_LABELS:
            return self._json(400, {"error": "Pick a suit."})
        m = _DATA_URI_RE.match(game)
        if not m:
            return self._json(400, {"error": "Drop a PNG or JPG image first."})
        try:
            base64.b64decode(m.group(2), validate=True)
        except (binascii.Error, ValueError):
            return self._json(400, {"error": "Image data was not valid base64."})

        try:
            out = _render(suit, free_spins, game, gif_width)
        except Exception as exc:  # keep the tool alive, report to the browser
            return self._json(500, {"error": f"Render failed: {exc}"})
        return self._json(200, out)

    # ── helpers ──
    def _json(self, code: int, obj: dict) -> None:
        self._send(code, "application/json", json.dumps(obj).encode("utf-8"))

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(fmt % args)


def main() -> int:
    ap = argparse.ArgumentParser(description="Slot card configurator web tool")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Slot Card Configurator on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
