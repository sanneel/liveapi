#!/usr/bin/env python3
"""Pack extension/ for distribution: a signed CRX for IT, a ZIP for hand install.

Run this whenever extension/ changes and you want operators to get the new
version:

    python3 scripts/pack_script_runner.py

Writes into app/static/script-runner/ (gitignored, rebuilt not committed):

    runner.crx          signed extension, what Chrome force-installs
    script-runner.zip   same files unsigned, for Load unpacked
    update.xml          the update manifest ExtensionInstallForcelist points at
    runner.json         id/version/sizes/hashes, read by the admin install page

THE SIGNING KEY IS THE EXTENSION'S IDENTITY. deploy/script-runner.pem is
generated on the first run and must then never change or be lost: the extension
id is derived from it, IT's policy pins that id, and a new key means a new id —
a different extension as far as Chrome is concerned, needing a new IT ticket.
It is gitignored because it is a private key; back it up wherever the other
deploy secrets live.

Chrome does the signing (--pack-extension) rather than a Python CRX3 writer:
it is the reference implementation of the format, and anyone shipping a Chrome
extension has Chrome. openssl derives the id from the key, which is the same
thing Chrome does internally — first 16 bytes of the SHA-256 of the DER public
key, hex digits mapped 0-f to a-p.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXT = REPO / "extension"
KEY = REPO / "deploy" / "script-runner.pem"
OUT = REPO / "app" / "static" / "script-runner"

# Not shipped to operators: tests are for us, and the README is on the page.
EXCLUDE = {"tests", "README.md", ".DS_Store"}

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/opt/google/chrome/chrome",
]


def die(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def find_chrome() -> str:
    for path in CHROME_CANDIDATES:
        if Path(path).is_file():
            return path
    die(
        "Chrome not found. Packing needs it for the CRX signature; install "
        "Chrome, or set one of: " + ", ".join(CHROME_CANDIDATES)
    )


def stage(dest: Path) -> None:
    """Copy the shippable extension files into dest/extension."""
    root = dest / "extension"
    root.mkdir(parents=True)
    for item in sorted(EXT.iterdir()):
        if item.name in EXCLUDE:
            continue
        if item.is_dir():
            shutil.copytree(item, root / item.name)
        else:
            shutil.copy2(item, root / item.name)


def extension_id(key: Path) -> str:
    """The id Chrome will give this key: sha256(DER public key)[:16], 0-f -> a-p."""
    der = subprocess.run(
        ["openssl", "rsa", "-in", str(key), "-pubout", "-outform", "DER"],
        capture_output=True, check=True,
    ).stdout
    digest = hashlib.sha256(der).hexdigest()[:32]
    return digest.translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))


def make_zip(src: Path, dest: Path) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src))


def main() -> int:
    if not (EXT / "manifest.json").is_file():
        die(f"no manifest at {EXT / 'manifest.json'}")

    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not version:
        die("manifest.json has no version")

    chrome = find_chrome()
    KEY.parent.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        stage(tmpdir)
        staged = tmpdir / "extension"

        cmd = [chrome, "--no-message-box", f"--pack-extension={staged}"]
        if KEY.is_file():
            cmd.append(f"--pack-extension-key={KEY}")
            print(f"Signing with existing key {KEY.relative_to(REPO)}")
        else:
            print(f"No key yet — Chrome will generate one, saved to "
                  f"{KEY.relative_to(REPO)}. BACK THIS UP: it is the extension's identity.")

        result = subprocess.run(cmd, capture_output=True, text=True)
        crx = tmpdir / "extension.crx"
        if not crx.is_file():
            die("Chrome did not produce a CRX.\n"
                f"  exit={result.returncode}\n  stdout={result.stdout.strip()}\n"
                f"  stderr={result.stderr.strip()}")

        generated_key = tmpdir / "extension.pem"
        if generated_key.is_file() and not KEY.is_file():
            shutil.move(str(generated_key), KEY)
            KEY.chmod(0o600)

        ext_id = extension_id(KEY)
        crx_bytes = crx.read_bytes()
        (OUT / "runner.crx").write_bytes(crx_bytes)
        make_zip(staged, OUT / "script-runner.zip")

    zip_bytes = (OUT / "script-runner.zip").read_bytes()

    # Chrome fetches this to decide whether to install or update. codebase must
    # be absolute, and the host has to be reachable without a login — Chrome
    # cannot authenticate.
    (OUT / "update.xml").write_text(
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>\n"
        f"  <app appid='{ext_id}'>\n"
        f"    <updatecheck codebase='@BASE@/script-runner/runner.crx' version='{version}' />\n"
        "  </app>\n"
        "</gupdate>\n",
        encoding="utf-8",
    )

    meta = {
        "id": ext_id,
        "version": version,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "crx_bytes": len(crx_bytes),
        "crx_sha256": hashlib.sha256(crx_bytes).hexdigest(),
        "zip_bytes": len(zip_bytes),
        "zip_sha256": hashlib.sha256(zip_bytes).hexdigest(),
    }
    (OUT / "runner.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    print(f"\n  extension id : {ext_id}")
    print(f"  version      : {version}")
    print(f"  runner.crx   : {len(crx_bytes):,} bytes")
    print(f"  zip          : {len(zip_bytes):,} bytes")
    print(f"\nWritten to {OUT.relative_to(REPO)}/. The install page at "
          f"/admin/tools/script-runner serves these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
