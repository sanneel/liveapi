#!/usr/bin/env python3
"""
Extracts the JSON request body from a Chrome DevTools "Copy as fetch" file.

Usage:
  python extract_templates.py raw_fetches/two_hours.txt templates/two_hours.json
"""

import json
import re
import sys
from pathlib import Path


def extract_body(fetch_text: str) -> dict:
    # Matches: "body": "{\"journeyName\":...}"
    match = re.search(r'"body"\s*:\s*"((?:\\.|[^"\\])*)"', fetch_text, flags=re.DOTALL)
    if not match:
        raise ValueError('Could not find a string field named "body". Make sure this is Copy as fetch for POST /journey-drafts.')

    escaped_json_body = '"' + match.group(1) + '"'
    body_text = json.loads(escaped_json_body)
    return json.loads(body_text)


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python extract_templates.py <copy-as-fetch.txt> <output-template.json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    fetch_text = input_path.read_text(encoding="utf-8")
    body = extract_body(fetch_text)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Extracted template: {output_path}")
    print(f"journeyName: {body.get('journeyName')}")
    print(f"duplicatedFromId: {body.get('duplicatedFromId')}")
    print(f"reservedJourneyId currently in template: {body.get('reservedJourneyId')}")
    print("The main script will replace reservedJourneyId with a fresh one each run.")


if __name__ == "__main__":
    main()
