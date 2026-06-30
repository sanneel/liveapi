"""Run figma_export.py from the admin UI to test the GOW Figma -> image pull.

Note: this calls api.figma.com, which the sandbox network policy blocks (you'll
get a connection/403 error here). It works where Figma is reachable (your
machine or an admin host with the policy opened). FIGMA_TOKEN must be set in the
server environment (a read-only File-content PAT).
"""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from typing import List, Tuple

from ..config import BASE_DIR

CLONER_DIR = BASE_DIR / "journey-cloner"
SCRIPT = CLONER_DIR / "figma_export.py"
OUT_DIR = CLONER_DIR / "figma_out"


def python_executable() -> str:
    import sys
    return sys.executable or "python3"


def _run(args: List[str], timeout: int = 120) -> Tuple[int, str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [python_executable(), str(SCRIPT), *args]
    display = " ".join(c if " " not in c else repr(c) for c in cmd)
    proc = subprocess.run(cmd, cwd=CLONER_DIR, env=env, text=True, encoding="utf-8",
                          capture_output=True, timeout=timeout)
    out = proc.stdout + ("\nSTDERR:\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, out, display


def token_present() -> bool:
    return bool(os.environ.get("FIGMA_TOKEN", "").strip())


def inspect(file_key: str, page: str = "") -> Tuple[int, str, str]:
    args = ["--key", file_key.strip(), "--inspect"]
    if page.strip():
        args += ["--page", page.strip()]
    return _run(args)


def export(file_key: str, game: str, page: str = "", scale: str = "1") -> Tuple[int, str, str, List[dict]]:
    args = ["--key", file_key.strip(), "--game", game.strip(), "--scale", (scale or "1").strip(), "--out", str(OUT_DIR)]
    if page.strip():
        args += ["--page", page.strip()]
    rc, out, display = _run(args)
    images: List[dict] = []
    if rc == 0:
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", game.lower()).strip("_")
        folder = OUT_DIR / slug
        if folder.exists():
            for png in sorted(folder.glob("*.png")):
                data = base64.b64encode(png.read_bytes()).decode("ascii")
                images.append({"slot": png.stem, "data_uri": f"data:image/png;base64,{data}",
                               "bytes": png.stat().st_size})
    return rc, out, display, images
