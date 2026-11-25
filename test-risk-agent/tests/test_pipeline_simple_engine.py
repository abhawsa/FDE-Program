"""End-to-end test of the dependency-free "simple" engine (no langgraph needed).

Builds a tiny synthetic git repo + coverage report, runs the full
analyze -> rank -> generate -> (review) -> apply -> coverage-delta -> report
sequence through pipeline.py directly, and checks every stage produced
something sane - this is the engine used automatically when langgraph isn't
installed, so it must work on its own.
"""
import json
import subprocess
from pathlib import Path

import pytest

from test_risk_agent import audit_log, pipeline, review_queue


def _git(args, cwd: Path):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch):
    queue_dir = tmp_path / "review_queue"
    queue_dir.mkdir()
    monkeypatch.setattr(review_queue, "REVIEW_QUEUE_DIR", queue_dir)
    monkeypatch.setattr(review_queue, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(audit_log, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(pipeline, "SIMPLE_STATE_PATH", tmp_path / "simple_pipeline_state.json")
    monkeypatch.setattr(pipeline, "ensure_data_dirs", lambda: None)
    yield


def _build_target_repo(root: Path) -> None:
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(
        "def risky(x):\n    if x > 0:\n        return 1\n    return -1\n",
        encoding="utf-8",
    )
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_placeholder.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")

    _git(["init", "-q"], cwd=root)
    _git(["config", "user.email", "t@example.com"], cwd=root)
    _git(["config", "user.name", "Test"], cwd=root)
    _git(["add", "-A"], cwd=root)
    _git(["commit", "-q", "-m", "init"], cwd=root)

    coverage_data = {
        "files": {"pkg/mod.py": {"executed_lines": [1], "missing_lines": [2, 3, 4], "summary": {"percent_covered": 25.0}}},
        "totals": {"percent_covered": 25.0},
    }
    (root / "coverage.json").write_text(json.dumps(coverage_data), encoding="utf-8")


def test_simple_engine_runs_full_pipeline_without_langgraph(tmp_path: Path):
    repo = tmp_path / "target_repo"
    _build_target_repo(repo)

    initial_state = {
        "repo_root": str(repo),
        "source_root": str(repo),
        "tests_dir": str(repo / "tests"),
        "coverage_json_path": str(repo / "coverage.json"),
        "source_pkg": "pkg",
        "reports_dir": str(tmp_path / "reports"),
        "audit_log_path": str(tmp_path / "audit_log.jsonl"),
        "lookback_days": 3650,
        "top_n": 10,
        "weights": {"change_frequency": 0.4, "complexity": 0.3, "coverage_gap": 0.3},
    }

    analyzed = pipeline.run_simple_analyze(initial_state)
    assert analyzed["candidates"]
    assert analyzed["drafts"]
    assert analyzed["drafts"][0]["generated_by"] == "template"  # no ANTHROPIC_API_KEY in test env

    # Human review happens entirely against the on-disk queue, independent of
    # pipeline state - approve the one and only draft.
    draft_id = analyzed["drafts"][0]["id"]
    review_queue.apply_decision(draft_id, "approve", reviewer="test-reviewer")

    finalized = pipeline.run_simple_apply()

    assert finalized["apply_result"]["applied"] == [draft_id]
    # The fallback template stub never calls the function under test (it's an
    # honest TODO, not a fabricated pass), so coverage legitimately does NOT
    # improve here - that's correct, not a bug. See test_coverage_delta.py for
    # the case where a real test body does raise coverage.
    delta = finalized["coverage_delta"]
    assert delta["overall_after"] >= delta["overall_before"]
    assert Path(finalized["report_path"]).exists()

    applied_test_files = list((repo / "tests").glob("test_generated_*.py"))
    assert len(applied_test_files) == 1
