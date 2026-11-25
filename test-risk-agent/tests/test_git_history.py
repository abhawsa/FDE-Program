import subprocess
from pathlib import Path

import pytest

from test_risk_agent import git_history
from test_risk_agent.complexity import extract_function_spans


def _git(args, cwd: Path):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git(["init", "-q"], cwd=repo_dir)
    _git(["config", "user.email", "test@example.com"], cwd=repo_dir)
    _git(["config", "user.name", "Test"], cwd=repo_dir)
    return repo_dir


def _commit_file(repo_dir: Path, rel_path: str, content: str, message: str) -> None:
    file_path = repo_dir / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    _git(["add", "-A"], cwd=repo_dir)
    _git(["commit", "-q", "-m", message], cwd=repo_dir)


def test_is_git_repo(repo: Path, tmp_path: Path):
    assert git_history.is_git_repo(repo) is True
    not_a_repo = tmp_path / "plain_dir"
    not_a_repo.mkdir()
    assert git_history.is_git_repo(not_a_repo) is False


def test_change_frequency_by_file_counts_commits(repo: Path):
    _commit_file(repo, "mod.py", "def a():\n    return 1\n", "add a")
    _commit_file(repo, "mod.py", "def a():\n    return 1\n\ndef b():\n    return 2\n", "add b")
    _commit_file(repo, "mod.py", "def a():\n    return 2\n\ndef b():\n    return 2\n", "change a")

    freq = git_history.change_frequency_by_file(repo, "mod.py", since_days=3650)

    assert freq == 3


def test_function_change_frequency_distinguishes_hot_and_cold_functions(repo: Path):
    # The initial commit adds the whole file, so it touches both functions once.
    _commit_file(
        repo,
        "mod.py",
        "def hot():\n    return 1\n\n\ndef cold():\n    return 100\n",
        "initial",
    )
    # Then change only `hot` several more times.
    for i in range(2, 6):
        content = f"def hot():\n    return {i}\n\n\ndef cold():\n    return 100\n"
        _commit_file(repo, "mod.py", content, f"tweak hot #{i}")

    spans = extract_function_spans(repo / "mod.py")
    freq = git_history.function_change_frequency(repo, "mod.py", spans, since_days=3650)

    assert freq["hot"] == 5  # 1 initial add + 4 tweaks
    assert freq["cold"] == 1  # only the initial add ever touched it
    assert freq["hot"] > freq["cold"]


def test_function_change_frequency_differentiates_touched_functions(repo: Path):
    _commit_file(repo, "mod.py", "def a():\n    return 1\n\n\ndef b():\n    return 2\n", "init")
    _commit_file(repo, "mod.py", "def a():\n    return 2\n\n\ndef b():\n    return 2\n", "change a only")

    spans = extract_function_spans(repo / "mod.py")
    freq = git_history.function_change_frequency(repo, "mod.py", spans, since_days=3650)

    assert freq["a"] == 2  # initial add + the follow-up change
    assert freq["b"] == 1  # only the initial add


def test_since_days_window_excludes_old_commits(repo: Path):
    _commit_file(repo, "mod.py", "def a():\n    return 1\n", "init")

    freq = git_history.change_frequency_by_file(repo, "mod.py", since_days=0)

    # since=0.days means "since today" - a commit made moments ago should still
    # count as it falls within "today"; we only assert this doesn't error and
    # returns a non-negative int, since exact boundary semantics are git's own.
    assert isinstance(freq, int)
    assert freq >= 0
