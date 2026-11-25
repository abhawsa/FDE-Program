import json
from pathlib import Path

import pytest

from test_risk_agent.coverage_ingest import (
    find_file_coverage,
    function_coverage_gap,
    load_coverage_json,
)
from test_risk_agent.models import FunctionSpan


def _write_coverage_json(path: Path) -> None:
    data = {
        "files": {
            "pkg/mod.py": {
                "executed_lines": [1, 2, 3, 7, 8],
                "missing_lines": [4, 5, 6],
                "summary": {"percent_covered": 62.5},
            }
        },
        "totals": {"percent_covered": 62.5},
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_coverage_json_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_coverage_json(tmp_path / "does_not_exist.json")


def test_load_coverage_json_parses_files(tmp_path: Path):
    cov_path = tmp_path / "coverage.json"
    _write_coverage_json(cov_path)

    coverage_map = load_coverage_json(cov_path)

    assert "pkg/mod.py" in coverage_map
    file_cov = coverage_map["pkg/mod.py"]
    assert file_cov.missing_lines == {4, 5, 6}
    assert file_cov.executed_lines == {1, 2, 3, 7, 8}


def test_find_file_coverage_normalizes_separators(tmp_path: Path):
    cov_path = tmp_path / "coverage.json"
    _write_coverage_json(cov_path)
    coverage_map = load_coverage_json(cov_path)

    found = find_file_coverage(coverage_map, "pkg\\mod.py")

    assert found is not None
    assert found.file == "pkg/mod.py"


def test_function_coverage_gap_partial_overlap(tmp_path: Path):
    cov_path = tmp_path / "coverage.json"
    _write_coverage_json(cov_path)
    coverage_map = load_coverage_json(cov_path)
    file_cov = coverage_map["pkg/mod.py"]

    span = FunctionSpan(file="pkg/mod.py", qualname="f", start_line=4, end_line=8, complexity=2, source="")
    gap, missing = function_coverage_gap(span, file_cov)

    # lines 4..8 intersect {4,5,6,7,8}; missing within that range: 4,5,6 -> 3/5
    assert gap == pytest.approx(3 / 5)
    assert missing == [4, 5, 6]


def test_function_coverage_gap_fully_covered_is_zero(tmp_path: Path):
    cov_path = tmp_path / "coverage.json"
    _write_coverage_json(cov_path)
    coverage_map = load_coverage_json(cov_path)
    file_cov = coverage_map["pkg/mod.py"]

    span = FunctionSpan(file="pkg/mod.py", qualname="g", start_line=1, end_line=3, complexity=1, source="")
    gap, missing = function_coverage_gap(span, file_cov)

    assert gap == 0.0
    assert missing == []


def test_function_coverage_gap_no_file_coverage_is_zero():
    span = FunctionSpan(file="pkg/mod.py", qualname="g", start_line=1, end_line=3, complexity=1, source="")
    gap, missing = function_coverage_gap(span, None)
    assert gap == 0.0
    assert missing == []
