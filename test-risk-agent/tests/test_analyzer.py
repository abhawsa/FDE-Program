import json
import subprocess
from pathlib import Path

from test_risk_agent.analyzer import analyze_repo


def _git(args, cwd: Path):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_analyze_repo_ranks_untested_paths_and_skips_fully_covered(tmp_path: Path):
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    module = pkg / "mod.py"
    module.write_text(
        "def covered():\n"
        "    return 1\n"
        "\n\n"
        "def risky(x):\n"
        "    if x > 0:\n"
        "        return 1\n"
        "    return -1\n",
        encoding="utf-8",
    )

    _git(["init", "-q"], cwd=repo)
    _git(["config", "user.email", "t@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-q", "-m", "init"], cwd=repo)
    # A second change to `risky` only, so it has a higher change frequency.
    module.write_text(
        "def covered():\n"
        "    return 1\n"
        "\n\n"
        "def risky(x):\n"
        "    if x > 0:\n"
        "        return 2\n"
        "    return -1\n",
        encoding="utf-8",
    )
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-q", "-m", "tweak risky"], cwd=repo)

    # `covered` is fully executed; `risky` only has its first branch executed.
    coverage_data = {
        "files": {
            "pkg/mod.py": {
                "executed_lines": [1, 2, 5, 6],
                "missing_lines": [7],
                "summary": {"percent_covered": 80.0},
            }
        },
        "totals": {"percent_covered": 80.0},
    }
    coverage_json = repo / "coverage.json"
    coverage_json.write_text(json.dumps(coverage_data), encoding="utf-8")

    candidates, spans = analyze_repo(repo, repo, coverage_json, lookback_days=3650)

    qualnames = {c.qualname for c in candidates}
    assert "risky" in qualnames
    assert "covered" not in qualnames  # fully covered -> not an untested path

    risky = next(c for c in candidates if c.qualname == "risky")
    assert risky.missing_lines == [7]
    assert risky.change_frequency == 2  # initial add + the tweak
    assert risky.complexity == 2  # base 1 + the `if`

    assert {s.qualname for s in spans} == {"covered", "risky"}


def test_analyze_repo_excludes_tests_directory(tmp_path: Path):
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_mod.py").write_text("def test_f():\n    assert True\n", encoding="utf-8")

    _git(["init", "-q"], cwd=repo)
    _git(["config", "user.email", "t@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-q", "-m", "init"], cwd=repo)

    coverage_data = {
        "files": {"pkg/mod.py": {"executed_lines": [], "missing_lines": [1, 2], "summary": {"percent_covered": 0.0}}},
        "totals": {"percent_covered": 0.0},
    }
    coverage_json = repo / "coverage.json"
    coverage_json.write_text(json.dumps(coverage_data), encoding="utf-8")

    candidates, spans = analyze_repo(repo, repo, coverage_json, lookback_days=3650)

    assert all("tests" not in c.file.split("/") for c in candidates)
    assert all("tests" not in s.qualname for s in spans)
