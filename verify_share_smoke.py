"""Verify default engines, explicitly allowing absent optional translation assets."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args()
    if args.executable:
        result = subprocess.run([str(args.executable), "--studio-smoke-report", str(args.report.resolve())], timeout=480)
        code = result.returncode
    else:
        from studio_smoke import run
        code = run(args.report)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    failures = [check for check in report["checks"] if not check["passed"]]
    expected = len(failures) == 1 and failures[0]["name"] == "Installed offline translation pairs" and failures[0].get("error") == "No offline translation pairs installed"
    if code not in (0, 1) or "status" in report or len(report["checks"]) != 11 or (failures and not expected):
        raise RuntimeError(f"Sharing runtime verification failed: {report}")
    if expected:
        failures[0]["skipped"] = True
        failures[0]["reason"] = "Translation models download on demand."
    report["passed"] = True
    report["profile"] = "sharing"
    args.report.with_suffix(".sharing.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
