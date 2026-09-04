#!/usr/bin/env python3
"""Archive the previous index.html edition and update archive/catalog.json.

This script is designed for GitHub Actions. It reads the previous index.html from
Git history, extracts its edition date, and preserves it under archive/YYYY-MM-DD.html
when the current index.html represents a different edition.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / "archive" / "catalog.json"


def git_show(ref: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Unable to read {path} at {ref}")
    return result.stdout


def extract_date(html: str) -> str | None:
    patterns = [
        r'<meta\s+name=["\']edition-date["\']\s+content=["\'](\d{4}-\d{2}-\d{2})["\']',
        r'data-edition-date=["\'](\d{4}-\d{2}-\d{2})["\']',
        r'([A-Z][a-z]+,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s*[·&]',
    ]
    for i, pattern in enumerate(patterns):
        match = re.search(pattern, html, re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        if i < 2:
            return value
        try:
            parsed = dt.datetime.strptime(value, "%A, %B %d, %Y")
            return parsed.date().isoformat()
        except ValueError:
            pass
    return None


def title_for(date_string: str) -> str:
    parsed = dt.date.fromisoformat(date_string)
    return parsed.strftime("%A, %B %-d, %Y") if sys.platform != "win32" else parsed.strftime("%A, %B %#d, %Y")


def load_catalog() -> dict:
    if not CATALOG.exists():
        return {"schema_version": 1, "updated": None, "editions": []}
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def save_catalog(catalog: dict) -> None:
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-ref", required=True)
    args = parser.parse_args()

    previous_ref = args.previous_ref.strip()
    if not previous_ref or set(previous_ref) == {"0"}:
        print("No usable previous ref. Nothing to archive.")
        return 0

    try:
        previous_html = git_show(previous_ref, "index.html")
    except RuntimeError as exc:
        print(f"Previous index unavailable: {exc}")
        return 0

    current_path = ROOT / "index.html"
    if not current_path.exists():
        print("Current index.html is missing.", file=sys.stderr)
        return 1
    current_html = current_path.read_text(encoding="utf-8")

    previous_date = extract_date(previous_html)
    current_date = extract_date(current_html)
    if not previous_date:
        print("Could not determine the previous edition date. Archive step skipped.", file=sys.stderr)
        return 1
    if current_date and current_date == previous_date:
        print(f"index.html still represents {previous_date}; no edition rollover detected.")
        return 0

    archive_dir = ROOT / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{previous_date}.html"

    if archive_path.exists():
        existing = archive_path.read_text(encoding="utf-8")
        if existing != previous_html:
            print(
                f"Immutable archive conflict: {archive_path.relative_to(ROOT)} already exists with different content.",
                file=sys.stderr,
            )
            return 1
        print(f"Archive snapshot already exists for {previous_date}.")
    else:
        archive_path.write_text(previous_html, encoding="utf-8")
        print(f"Archived previous edition to {archive_path.relative_to(ROOT)}")

    catalog = load_catalog()
    editions = catalog.setdefault("editions", [])
    expected_path = f"archive/{previous_date}.html"
    existing_entry = next((e for e in editions if e.get("date") == previous_date), None)

    if existing_entry:
        if existing_entry.get("path") != expected_path:
            print(f"Catalog conflict for {previous_date}.", file=sys.stderr)
            return 1
        existing_entry.update({"title": title_for(previous_date), "format": "html", "status": "available"})
    else:
        editions.append(
            {
                "date": previous_date,
                "title": title_for(previous_date),
                "path": expected_path,
                "format": "html",
                "status": "available",
            }
        )

    editions.sort(key=lambda e: e.get("date", ""), reverse=True)
    catalog["schema_version"] = 1
    catalog["updated"] = dt.datetime.now(dt.timezone.utc).date().isoformat()
    save_catalog(catalog)
    print(f"Catalog now contains {len(editions)} edition(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
