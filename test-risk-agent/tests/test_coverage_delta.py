from pathlib import Path

from workflow import coverage_delta


def _make_tiny_project(root: Path) -> None:
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_mod.py").write_text(
        "from pkg.mod import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )


def test_run_coverage_and_compute_delta_reflects_newly_added_test(tmp_path: Path):
    _make_tiny_project(tmp_path)

    before_json = tmp_path / "before.json"
    coverage_delta.run_coverage(tmp_path, "pkg", before_json)
    before = coverage_delta.compute_delta(before_json, before_json)
    assert before["overall_delta"] == 0.0  # comparing a report to itself

    # Now add a test for `sub`, which was previously uncovered.
    (tmp_path / "tests" / "test_sub.py").write_text(
        "from pkg.mod import sub\n\n\ndef test_sub():\n    assert sub(5, 2) == 3\n",
        encoding="utf-8",
    )
    after_json = tmp_path / "after.json"
    coverage_delta.run_coverage(tmp_path, "pkg", after_json)

    delta = coverage_delta.compute_delta(before_json, after_json)

    assert delta["overall_after"] > delta["overall_before"]
    assert delta["overall_delta"] > 0
    assert any("mod.py" in f for f in delta["per_file"])
