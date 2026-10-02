"""Stage the extended offline model collection, continuing past independent failures."""
import argparse
import json
import sys
from pathlib import Path

from model_catalog import catalog, install, is_installed


def main():
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-whisper", action="store_true", help="Also bundle small/medium/large transcription models")
    parser.add_argument("--report", type=Path, default=Path("studio-verification/model-setup.json"))
    args = parser.parse_args()
    reports = []
    for entry in catalog():
        if entry.kind == "whisper" and entry.key not in {"whisper-base.en", "whisper-base"} and not args.all_whisper:
            continue
        try:
            if not is_installed(entry):
                print(f"Installing {entry.key}...", flush=True)
                install(entry, progress=lambda message: print(message, flush=True))
            reports.append({"key": entry.key, "installed": True})
        except Exception as exc:
            reports.append({"key": entry.key, "installed": False, "error": str(exc)})
            print(f"FAILED {entry.key}: {exc}", flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    return 0 if all(r["installed"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
