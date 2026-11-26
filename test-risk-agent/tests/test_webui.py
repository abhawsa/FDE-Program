"""Tests for the local web control panel (webui/app.py).

Uses Flask's test client - no real HTTP server, no subprocess - so these
run as fast and deterministically as the rest of the suite. Builds a tiny
synthetic git repo + coverage report (same pattern as
test_pipeline_simple_engine.py) and drives the full analyze -> decide ->
apply cycle through the HTTP API, with every storage path isolated to
tmp_path so a test run can never touch the real project's data/ or
audit/generation_audit_log.json.
"""
import json
import subprocess
from pathlib import Path

import pytest

from audit import audit_log
from review import review_queue
from workflow import pipeline
from webui import app as webui_app


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
    monkeypatch.setattr(audit_log, "GENERATION_AUDIT_LOG_JSON_PATH", tmp_path / "generation_audit_log.json")
    monkeypatch.setattr(audit_log, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(pipeline, "SIMPLE_STATE_PATH", tmp_path / "simple_pipeline_state.json")
    monkeypatch.setattr(pipeline, "ensure_data_dirs", lambda: None)
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(webui_app, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(webui_app, "ensure_data_dirs", lambda: None)
    yield


@pytest.fixture
def client():
    webui_app.app.testing = True
    return webui_app.app.test_client()


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


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Risk Agent Control Panel" in resp.data


def test_status_on_empty_queue(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["queue"]["total"] == 0
    assert data["has_report"] is False


def test_analyze_requires_baseline_first(client, tmp_path):
    repo = tmp_path / "repo_no_coverage"
    repo.mkdir()
    resp = client.post("/api/analyze", json={"repo_root": str(repo), "source_pkg": "pkg"})
    assert resp.status_code == 400
    assert "Coverage report not found" in resp.get_json()["error"]


def test_full_cycle_analyze_decide_apply(client, tmp_path):
    repo = tmp_path / "target_repo"
    _build_target_repo(repo)

    # analyze
    resp = client.post("/api/analyze", json={"repo_root": str(repo), "source_pkg": "pkg"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["candidates"]) == 1
    assert len(data["drafts"]) == 1
    draft_id = data["drafts"][0]["id"]
    assert data["drafts"][0]["status"] == "pending"

    # queue reflects the pending draft
    resp = client.get("/api/drafts?status=pending")
    assert len(resp.get_json()) == 1

    # decide: approve
    resp = client.post(
        f"/api/drafts/{draft_id}/decision",
        json={"decision": "approve", "reviewer": "test-reviewer", "comment": "looks fine"},
    )
    assert resp.status_code == 200
    decided = resp.get_json()
    assert decided["status"] == "approved"
    assert decided["reviewer"] == "test-reviewer"

    # apply
    resp = client.post("/api/apply", json={})
    assert resp.status_code == 200
    result = resp.get_json()
    assert result["apply_result"]["applied"] == [draft_id]
    assert result["coverage_delta"]["overall_after"] >= result["coverage_delta"]["overall_before"]
    assert Path(result["report_path"]).exists()

    # status now reflects the applied draft
    resp = client.get("/api/status")
    status = resp.get_json()
    assert status["queue"]["applied"] == 1
    assert status["has_report"] is True

    # report endpoint returns the generated markdown
    resp = client.get("/api/report")
    assert resp.get_json()["markdown"]

    # audit endpoint reflects both the review decision and the apply
    resp = client.get("/api/audit")
    events = [e["event"] for e in resp.get_json()]
    assert "review_decision" in events
    assert "test_applied" in events


def test_decision_rejects_invalid_value(client, tmp_path):
    repo = tmp_path / "target_repo2"
    _build_target_repo(repo)
    client.post("/api/analyze", json={"repo_root": str(repo), "source_pkg": "pkg"})
    draft_id = client.get("/api/drafts?status=pending").get_json()[0]["id"]

    resp = client.post(f"/api/drafts/{draft_id}/decision", json={"decision": "maybe"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_decision_edit_requires_edited_code(client, tmp_path):
    repo = tmp_path / "target_repo3"
    _build_target_repo(repo)
    client.post("/api/analyze", json={"repo_root": str(repo), "source_pkg": "pkg"})
    draft_id = client.get("/api/drafts?status=pending").get_json()[0]["id"]

    resp = client.post(f"/api/drafts/{draft_id}/decision", json={"decision": "edit"})
    assert resp.status_code == 400


def test_apply_without_prior_analyze_errors_cleanly(client):
    resp = client.post("/api/apply", json={})
    assert resp.status_code == 400
    assert "No paused run found" in resp.get_json()["error"]
