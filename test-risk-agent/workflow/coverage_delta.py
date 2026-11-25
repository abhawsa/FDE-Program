"""Re-runs coverage after approved tests are applied and reports the delta.

Because apply_tests.py only ever writes APPROVED/EDITED drafts to disk,
re-running coverage.py over the test suite afterwards naturally measures
"coverage improvement from approved tests only" - there is nothing else in
tests_dir that could account for the difference.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict


def run_coverage(repo_root: Path, source_pkg: str, out_json: Path) -> subprocess.CompletedProcess:
    """Runs `coverage run -m pytest` + `coverage json` inside repo_root. Never raises on test failure."""
    run_result = subprocess.run(
        [sys.executable, "-m", "coverage", "run", f"--source={source_pkg}", "-m", "pytest", "-q"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        [sys.executable, "-m", "coverage", "json", "-o", str(out_json)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return run_result


def compute_delta(before_json: Path, after_json: Path) -> Dict:
    before = json.loads(before_json.read_text(encoding="utf-8"))
    after = json.loads(after_json.read_text(encoding="utf-8"))

    overall_before = before.get("totals", {}).get("percent_covered", 0.0)
    overall_after = after.get("totals", {}).get("percent_covered", 0.0)

    per_file = {}
    all_files = set(before.get("files", {}).keys()) | set(after.get("files", {}).keys())
    for file_name in sorted(all_files):
        b = before.get("files", {}).get(file_name, {}).get("summary", {}).get("percent_covered", 0.0)
        a = after.get("files", {}).get(file_name, {}).get("summary", {}).get("percent_covered", 0.0)
        if abs(a - b) > 1e-6:
            per_file[file_name] = {"before": b, "after": a, "delta": round(a - b, 2)}

    return {
        "overall_before": overall_before,
        "overall_after": overall_after,
        "overall_delta": round(overall_after - overall_before, 2),
        "per_file": per_file,
    }
