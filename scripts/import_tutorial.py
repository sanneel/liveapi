#!/usr/bin/env python3
"""
Import a help tutorial video straight from a file on disk — no HTTP upload.

This bypasses the browser upload path (and therefore any reverse-proxy body-size
limit), so it's the reliable way to add large recordings on the server. It reuses
the exact validation, storage layout and DB write the web upload uses.

Usage:
  python scripts/import_tutorial.py --file /path/to/manual.mov --title "How to create a manual campaign"
  python scripts/import_tutorial.py --file email.mov --title "Integrate into email" --by sandros7

The file is copied to app/static/tutorials/<uuid><ext> (the original is left in
place) and a row is inserted so it appears in the Help library for every operator.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse the web route's rules so disk imports and uploads stay identical.
from app.routes.admin_tutorials import (  # noqa: E402
    ALLOWED_EXTENSIONS,
    MAX_TITLE_LENGTH,
    MAX_UPLOAD_BYTES,
    TUTORIALS_DIR,
)
from app.database import db_session  # noqa: E402
from app.logging_config import get_logger  # noqa: E402
from app.repositories.tutorial_repo import TutorialRepository  # noqa: E402

logger = get_logger("import_tutorial")

# Coarse content-type map for the common containers the player accepts.
_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".ogg": "video/ogg",
    ".ogv": "video/ogg",
    ".mov": "video/quicktime",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a tutorial video from a local file.")
    parser.add_argument("--file", required=True, help="Path to the video file.")
    parser.add_argument("--title", required=True, help="Title shown in the Help library.")
    parser.add_argument("--by", default="import-script", help="Username recorded as uploader.")
    args = parser.parse_args()

    src = Path(args.file).expanduser()
    if not src.is_file():
        print(f"Not a file: {src}", file=sys.stderr)
        return 1

    ext = src.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        print(
            f"Unsupported type '{ext}'. Use one of: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            file=sys.stderr,
        )
        return 1

    title = (args.title or "").strip()
    if not title:
        print("Title is required.", file=sys.stderr)
        return 1
    if len(title) > MAX_TITLE_LENGTH:
        print(f"Title must be {MAX_TITLE_LENGTH} characters or fewer.", file=sys.stderr)
        return 1

    size = src.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        print(f"File is too large ({size} bytes, max {MAX_UPLOAD_BYTES}).", file=sys.stderr)
        return 1

    TUTORIALS_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{ext}"
    dest = TUTORIALS_DIR / stored_name
    try:
        shutil.copy2(src, dest)
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        print(f"Copy failed: {exc}", file=sys.stderr)
        return 1

    try:
        with db_session() as session:
            tutorial = TutorialRepository(session).create(
                title=title,
                filename=stored_name,
                original_name=src.name,
                content_type=_CONTENT_TYPES.get(ext),
                size_bytes=size,
                uploaded_by=args.by,
            )
            new_id = tutorial.id
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)  # don't orphan the file if the row failed
        print(f"DB insert failed (file removed): {exc}", file=sys.stderr)
        return 1

    logger.info(f"import_tutorial id={new_id} title={title!r} file={stored_name} size={size}")
    print(f"[success] Imported tutorial #{new_id}: {title!r}  ->  static/tutorials/{stored_name} ({size/1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
