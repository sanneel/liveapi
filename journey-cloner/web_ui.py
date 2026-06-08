#!/usr/bin/env python3
"""Small local web UI for create_journeys.py.

Run on the VPS, preferably through an SSH tunnel because the form accepts a
Bearer token:

  .venv/bin/python web_ui.py --host 127.0.0.1 --port 8088
"""

from __future__ import annotations

import argparse
import html
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs


ROOT = Path(__file__).resolve().parent
TYPES = ("followup", "bfr", "two_hours", "aft")


def _page(result: str = "", command: str = "") -> bytes:
    safe_result = html.escape(result)
    safe_command = html.escape(command)
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Journey Cloner</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #080b12;
      --panel: #111827;
      --panel2: #172033;
      --line: #2b3448;
      --text: #e8edf6;
      --muted: #9aa6b8;
      --brand: #c2e325;
      --danger: #f87171;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    main {{ max-width: 1040px; margin: 0 auto; padding: 28px 18px 40px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; letter-spacing: 0; }}
    p {{ margin: 0; color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 18px; margin-top: 22px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }}
    label {{ display: block; font-size: 12px; color: var(--muted); margin-bottom: 7px; }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      background: var(--panel2);
      color: var(--text);
      border-radius: 6px;
      padding: 10px 11px;
      font-size: 14px;
      outline: none;
    }}
    input:focus, select:focus {{ border-color: var(--brand); }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .field {{ margin-bottom: 14px; }}
    .checks {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .check {{
      display: flex; align-items: center; gap: 8px;
      background: var(--panel2); border: 1px solid var(--line); border-radius: 6px;
      padding: 9px 10px; color: var(--text); font-size: 13px;
    }}
    .check input {{ width: auto; }}
    .actions {{ display: flex; gap: 10px; align-items: center; margin-top: 16px; }}
    button {{
      border: 0; background: var(--brand); color: #111827; border-radius: 6px;
      padding: 10px 14px; font-weight: 700; cursor: pointer;
    }}
    button.secondary {{ background: var(--panel2); color: var(--text); border: 1px solid var(--line); }}
    pre {{
      white-space: pre-wrap; word-break: break-word; margin: 14px 0 0;
      background: #05070c; border: 1px solid var(--line); border-radius: 8px;
      padding: 14px; color: #d8e1ef; font-size: 12px; max-height: 520px; overflow: auto;
    }}
    .warn {{ color: var(--danger); margin-top: 10px; }}
    .steps {{ display: grid; gap: 10px; margin-top: 14px; }}
    .step {{ padding: 12px; background: var(--panel2); border: 1px solid var(--line); border-radius: 7px; }}
    .step strong {{ display: block; font-size: 13px; margin-bottom: 3px; }}
    @media (max-width: 860px) {{ .layout {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Journey Cloner</h1>
    <p>Create draft journey clones from the existing templates. Times are interpreted as Chile time.</p>
    <p class="warn">Do not expose this page publicly. Use 127.0.0.1 with an SSH tunnel when possible.</p>

    <div class="layout">
      <form class="panel" method="post" action="/run">
        <div class="field">
          <label for="token">Bearer token</label>
          <input id="token" name="token" type="password" autocomplete="off" placeholder="Required only when dry run is unchecked">
        </div>

        <div class="grid">
          <div class="field">
            <label for="home">Home club</label>
            <input id="home" name="home" required placeholder="Colo Colo">
          </div>
          <div class="field">
            <label for="away">Away club</label>
            <input id="away" name="away" required placeholder="Audax">
          </div>
        </div>

        <div class="grid">
          <div class="field">
            <label for="date">Date</label>
            <input id="date" name="date" type="date" required>
          </div>
          <div class="field">
            <label for="time">Chile time</label>
            <input id="time" name="time" type="time" required>
          </div>
        </div>

        <div class="field">
          <label for="code">Promocode</label>
          <input id="code" name="code" required placeholder="VAMOSBULLA">
        </div>

        <div class="field">
          <label>Draft types</label>
          <div class="checks">
            <label class="check"><input type="checkbox" name="types" value="followup" checked> FollowUp</label>
            <label class="check"><input type="checkbox" name="types" value="bfr" checked> BFR</label>
            <label class="check"><input type="checkbox" name="types" value="two_hours" checked> 2H</label>
            <label class="check"><input type="checkbox" name="types" value="aft" checked> AFT</label>
          </div>
        </div>

        <div class="field">
          <label class="check"><input type="checkbox" name="dry_run" value="1" checked> Dry run only</label>
        </div>

        <div class="actions">
          <button type="submit">Run</button>
          <button class="secondary" type="reset">Clear</button>
        </div>
      </form>

      <aside class="panel">
        <h2 style="margin:0 0 8px;font-size:16px">Checklist</h2>
        <p>Before creating drafts, templates must exist in <code>templates/</code>.</p>
        <div class="steps">
          <div class="step"><strong>1. Test AFT first</strong><p>Select only AFT and keep dry run enabled.</p></div>
          <div class="step"><strong>2. Review output</strong><p>Generated JSON lands in <code>out/</code>.</p></div>
          <div class="step"><strong>3. Create drafts</strong><p>Uncheck dry run when the output looks right.</p></div>
        </div>
      </aside>
    </div>

    {f'<pre><strong>Command</strong>\\n{safe_command}\\n\\n<strong>Output</strong>\\n{safe_result}</pre>' if result else ''}
  </main>
</body>
</html>"""
    return body.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send(_page())

    def do_POST(self) -> None:
        if self.path != "/run":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        data = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))

        token = (data.get("token") or [""])[0].strip()
        home = (data.get("home") or [""])[0].strip()
        away = (data.get("away") or [""])[0].strip()
        date = (data.get("date") or [""])[0].strip()
        chile_time = (data.get("time") or [""])[0].strip()
        code = (data.get("code") or [""])[0].strip().upper()
        selected_types = [t for t in data.get("types", []) if t in TYPES]
        dry_run = bool(data.get("dry_run"))

        if not all([home, away, date, chile_time, code, selected_types]):
            self._send(_page("Missing required fields.", ""))
            return
        if not dry_run and not token:
            self._send(_page("Bearer token is required when dry run is unchecked.", ""))
            return

        cmd = [
            sys.executable,
            "create_journeys.py",
            "--match",
            f"{home} vs {away}",
            "--code",
            code,
            "--date",
            date,
            "--time",
            chile_time,
            "--types",
            *selected_types,
            "--yes",
        ]
        if dry_run:
            cmd.append("--dry-run")

        env = os.environ.copy()
        env["AUTH_TOKEN"] = token

        display_cmd = " ".join(
            ["AUTH_TOKEN=***", *[c if " " not in c else repr(c) for c in cmd]]
        )
        try:
            proc = subprocess.run(
                cmd,
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=240,
            )
            output = proc.stdout
            if proc.stderr:
                output += "\nSTDERR:\n" + proc.stderr
            output += f"\nExit code: {proc.returncode}"
        except Exception as exc:
            output = f"Failed to run create_journeys.py: {exc}"

        self._send(_page(output, display_cmd))

    def _send(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(fmt % args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Journey Cloner web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Journey Cloner UI listening on http://{args.host}:{args.port}")
    print("Use Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
