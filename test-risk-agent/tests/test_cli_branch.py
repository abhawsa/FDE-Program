"""Tests for `--branch` (cli._checkout_branch): checks out a branch in
--repo-root before baseline/analyze, without ever discarding uncommitted work.
"""
import subprocess
from pathlib import Path

import pytest

import cli


def _git(args, cwd: Path):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _current_branch(repo_dir: Path) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir).strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git(["init", "-q", "-b", "main"], cwd=repo_dir)
    _git(["config", "user.email", "test@example.com"], cwd=repo_dir)
    _git(["config", "user.name", "Test"], cwd=repo_dir)
    (repo_dir / "mod.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _git(["add", "-A"], cwd=repo_dir)
    _git(["commit", "-q", "-m", "init"], cwd=repo_dir)
    _git(["checkout", "-q", "-b", "feature"], cwd=repo_dir)
    (repo_dir / "mod.py").write_text("def a():\n    return 2\n", encoding="utf-8")
    _git(["add", "-A"], cwd=repo_dir)
    _git(["commit", "-q", "-m", "feature change"], cwd=repo_dir)
    _git(["checkout", "-q", "main"], cwd=repo_dir)
    return repo_dir


def test_no_branch_is_a_noop(repo: Path):
    cli._checkout_branch(repo, None)
    assert _current_branch(repo) == "main"


def test_already_on_requested_branch_is_a_noop(repo: Path):
    cli._checkout_branch(repo, "main")
    assert _current_branch(repo) == "main"


def test_switches_to_requested_branch(repo: Path):
    cli._checkout_branch(repo, "feature")
    assert _current_branch(repo) == "feature"
    assert (repo / "mod.py").read_text(encoding="utf-8") == "def a():\n    return 2\n"


def test_refuses_to_switch_with_uncommitted_changes(repo: Path):
    (repo / "mod.py").write_text("def a():\n    return 999  # local WIP\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        cli._checkout_branch(repo, "feature")

    assert _current_branch(repo) == "main"
    assert "WIP" in (repo / "mod.py").read_text(encoding="utf-8")


def test_unknown_branch_errors_cleanly(repo: Path):
    with pytest.raises(SystemExit):
        cli._checkout_branch(repo, "does-not-exist")
    assert _current_branch(repo) == "main"
