"""Ties git_history + complexity + coverage_ingest together into risk candidates.

This is the "Diff & History Analyzer" + "Coverage Ingestion" stages from the
recommended architecture, fused into one pass over the source tree.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple

from agents import complexity as complexity_mod
from agents import coverage_parser as coverage_ingest
from agents import history_analyzer as git_history
from core.models import FunctionSpan, RiskCandidate

DEFAULT_EXCLUDE_DIR_NAMES = frozenset(
    {"tests", "test", ".venv", "venv", "__pycache__", ".git", "build", "dist"}
)


def _normalize_rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def discover_python_files(
    source_root: Path,
    exclude_dir_names: frozenset = DEFAULT_EXCLUDE_DIR_NAMES,
) -> List[Path]:
    files = []
    for path in source_root.rglob("*.py"):
        if path.is_file() and not any(part in exclude_dir_names for part in path.parts):
            files.append(path)
    return sorted(set(files))


def analyze_repo(
    repo_root: Path,
    source_root: Path,
    coverage_json_path: Path,
    lookback_days: int = 180,
) -> Tuple[List[RiskCandidate], List[FunctionSpan]]:
    """Returns (untested risk candidates, all function spans seen) for reporting."""
    coverage_map = coverage_ingest.load_coverage_json(coverage_json_path)
    candidates: List[RiskCandidate] = []
    all_spans: List[FunctionSpan] = []

    for file_path in discover_python_files(source_root):
        rel_to_repo = _normalize_rel(file_path, repo_root)
        spans = complexity_mod.extract_function_spans(file_path)
        if not spans:
            continue
        for span in spans:
            # Re-key spans by repo-relative path so they line up with
            # RiskCandidate.file (which is always repo-relative).
            span.file = rel_to_repo
        all_spans.extend(spans)

        file_cov = coverage_ingest.find_file_coverage(coverage_map, rel_to_repo)
        freq_by_qualname = git_history.function_change_frequency(
            repo_root, rel_to_repo, spans, since_days=lookback_days
        )

        for span in spans:
            gap, missing_lines = coverage_ingest.function_coverage_gap(span, file_cov)
            if gap <= 0.0:
                continue  # fully covered -> not an "untested path", skip it
            candidates.append(
                RiskCandidate(
                    file=rel_to_repo,
                    qualname=span.qualname,
                    start_line=span.start_line,
                    end_line=span.end_line,
                    change_frequency=freq_by_qualname.get(span.qualname, 0),
                    complexity=span.complexity,
                    coverage_gap=gap,
                    missing_lines=missing_lines,
                )
            )

    return candidates, all_spans


def spans_by_key(spans: Iterable[FunctionSpan]):
    return {(_posix(s.file), s.qualname): s for s in spans}


def _posix(path: str) -> str:
    return path.replace("\\", "/")
