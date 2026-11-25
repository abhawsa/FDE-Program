"""Parses `coverage json` reports and maps missing lines back to functions.

Generate the input with:
    coverage run -m pytest
    coverage json -o coverage.json
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .models import FunctionSpan


@dataclass
class FileCoverage:
    file: str
    executed_lines: Set[int]
    missing_lines: Set[int]
    percent_covered: float


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def load_coverage_json(path: Path) -> Dict[str, FileCoverage]:
    if not path.exists():
        raise FileNotFoundError(
            f"Coverage report not found at {path}. Generate it with "
            "`coverage run -m pytest && coverage json -o {path.name}`."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    result: Dict[str, FileCoverage] = {}
    for file_path, info in data.get("files", {}).items():
        normalized = _normalize(file_path)
        result[normalized] = FileCoverage(
            file=normalized,
            executed_lines=set(info.get("executed_lines", [])),
            missing_lines=set(info.get("missing_lines", [])),
            percent_covered=float(info.get("summary", {}).get("percent_covered", 0.0)),
        )
    return result


def find_file_coverage(coverage_map: Dict[str, FileCoverage], file_rel: str) -> Optional[FileCoverage]:
    target = _normalize(file_rel)
    if target in coverage_map:
        return coverage_map[target]
    # Fall back to suffix matching in case the report was generated from a
    # different working directory (absolute vs. relative paths).
    for key, value in coverage_map.items():
        if key.endswith(target) or target.endswith(key):
            return value
    return None


def function_coverage_gap(
    span: FunctionSpan, file_cov: Optional[FileCoverage]
) -> Tuple[float, List[int]]:
    """Fraction (0..1) of the function's executable lines that are uncovered."""
    if file_cov is None:
        return 0.0, []  # file never ran through coverage - nothing to claim here

    func_lines = set(range(span.start_line, span.end_line + 1))
    relevant_missing = func_lines & file_cov.missing_lines
    relevant_known = func_lines & (file_cov.missing_lines | file_cov.executed_lines)
    if not relevant_known:
        return 0.0, []

    gap = len(relevant_missing) / len(relevant_known)
    return gap, sorted(relevant_missing)
