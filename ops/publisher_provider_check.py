"""Check provider capabilities before reserving an editorial generation attempt.

Reuse the separately tested non-publishing check. Do not modify content, retry
ledgers, credentials, or approval records. Completed releases need no new API call.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from check_openai_access import Client, CheckFailure, MODELS, run_check

ROOT = Path(__file__).resolve().parents[1]
REPORT = "credential-check-report.json"
STAGES = {"configuration", "research_and_web_search", "speech", "transcription"}


def already_complete(root: Path, edition: str) -> bool:
    try:
        manifest = json.loads((root / "release.json").read_text(encoding="utf-8"))
        paths = manifest.get("files", {})
        required = {
            "index.html", "podcast.xml", "archive/catalog.json",
            f"archive/{edition}.html", f"audio/{edition}.mp3",
            f"podcast-script/{edition}.txt", f"transcript/{edition}.html",
            f"data/audio-quality-{edition}.json",
        }
        return (manifest.get("schema_version") == 1
                and manifest.get("edition_date") == edition
                and manifest.get("audio_status") == "complete"
                and isinstance(paths, dict) and required.issubset(paths)
                and all((root / p).is_file() for p in required))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def preflight(root: Path, edition: str, check=run_check, client_factory=Client) -> dict:
    date.fromisoformat(edition)
    report_path = root / REPORT
    # Never let a committed or previous run's report stand in for this check.
    report_path.unlink(missing_ok=True)
    common = {
        "schema_version": 1, "edition_date": edition,
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "operation": "publisher_provider_preflight",
        "publication_attempted": False, "research_budget_modified": False,
    }
    if already_complete(root, edition):
        report = {**common, "passed": None, "skipped": True, "checks": [],
                  "reason": "complete_committed_release_requires_no_generation"}
    else:
        try:
            report = check(client_factory(os.getenv("OPENAI_API_KEY", "")),
                           os.getenv("RURAL_UPDATE_MODEL", MODELS["research"]))
        except CheckFailure as error:
            report = {
                "passed": False,
                "checks": [{"stage": "configuration", "passed": False,
                            "reason": error.reason}],
            }
        except Exception:
            report = {
                "passed": False,
                "checks": [{"stage": "configuration", "passed": False,
                            "reason": "preflight_local_error"}],
            }
        report = {**report, **common, "skipped": False}
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def failure_message(root: Path, edition: str) -> str:
    base = ("Provider capability preflight failed. No editorial generation "
            "attempt was reserved by this check.")
    try:
        report = json.loads((root / REPORT).read_text(encoding="utf-8"))
        if (report.get("run_id") != os.getenv("GITHUB_RUN_ID", "local")
                or report.get("edition_date") != edition
                or report.get("passed") is not False):
            return base
        failed = next(c for c in report.get("checks", []) if c.get("passed") is False)
        stage = failed.get("stage")
        stage = stage if stage in STAGES else "configuration"
        status = failed.get("http_status")
        detail = f" at {stage}"
        if type(status) is int and 400 <= status <= 599:
            detail += f" (HTTP {status})"
        return ("Provider capability preflight failed" + detail
                + ". No editorial generation attempt was reserved by this check. "
                "See credential-check-report.json; correct the reported capability "
                "or provider condition before requesting recovery.")
    except (OSError, ValueError, TypeError, AttributeError, StopIteration):
        return base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--failure-message", action="store_true")
    args = parser.parse_args()
    date.fromisoformat(args.date)
    if args.failure_message:
        print(failure_message(ROOT, args.date))
        return 0
    report = preflight(ROOT, args.date)
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("passed") is True or report.get("skipped") is True else 1


if __name__ == "__main__":
    sys.exit(main())
