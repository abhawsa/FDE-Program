"""Change-frequency analysis over Git history.

Uses the `git` CLI directly via subprocess (no GitPython dependency): it is
already a required tool for this track, and shelling out keeps the agent's
core path dependency-free.

Function-level change frequency: for each commit that touched a file (within
the lookback window), we parse the function spans as they existed in THAT
commit's blob and check whether the commit's diff hunks (also relative to
that same blob) overlap each span - then attribute the "touch" to today's
function of the same qualified name. Matching spans per-commit like this
(rather than against today's line numbers) avoids line-number drift from
unrelated edits elsewhere in the file. The one remaining limitation is a
function being renamed over its history, which this treats as a new
function with no prior history - see README "Where AI falls short".
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from agents.complexity import extract_function_spans
from core.models import FunctionSpan

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class GitCommandError(RuntimeError):
    pass


def _run_git(args: List[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitCommandError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def is_git_repo(path: Path) -> bool:
    try:
        output = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    except GitCommandError:
        return False
    return output.strip() == "true"


def list_commits_touching(repo_root: Path, file_rel: str, since_days: int) -> List[str]:
    out = _run_git(
        ["log", f"--since={since_days}.days", "--format=%H", "--", file_rel],
        cwd=repo_root,
    )
    return [c for c in out.splitlines() if c.strip()]


def changed_line_ranges(repo_root: Path, commit: str, file_rel: str) -> List[Tuple[int, int]]:
    """New-file line ranges touched by `commit` for `file_rel`, from a 0-context diff."""
    out = _run_git(
        ["show", "--unified=0", "--format=", commit, "--", file_rel],
        cwd=repo_root,
    )
    ranges: List[Tuple[int, int]] = []
    for line in out.splitlines():
        match = _HUNK_RE.match(line)
        if not match:
            continue
        start = int(match.group(1))
        length = int(match.group(2)) if match.group(2) is not None else 1
        if length == 0:
            # Pure deletion anchored just before `start`; treat as touching that line.
            length = 1
        ranges.append((start, start + length - 1))
    return ranges


def change_frequency_by_file(repo_root: Path, file_rel: str, since_days: int = 180) -> int:
    return len(list_commits_touching(repo_root, file_rel, since_days))


def _show_prefix(repo_root: Path) -> str:
    """Path of `repo_root` relative to the actual repo top-level, if any.

    `git show <commit>:<path>` (unlike `git log -- <path>`) always resolves
    <path> relative to the repo's top level, not the current working
    directory - so when repo_root is itself a subdirectory of a larger repo
    (as with this project's sample_target_repo), that prefix must be added.
    """
    return _run_git(["rev-parse", "--show-prefix"], cwd=repo_root).strip()


def _blob_at_commit(repo_root: Path, commit: str, file_rel: str) -> str:
    posix_rel = (_show_prefix(repo_root) + file_rel).replace("\\", "/")
    return _run_git(["show", f"{commit}:{posix_rel}"], cwd=repo_root)


def _spans_at_commit(repo_root: Path, commit: str, file_rel: str) -> List[FunctionSpan]:
    try:
        source = _blob_at_commit(repo_root, commit, file_rel)
    except GitCommandError:
        return []
    try:
        return extract_function_spans(Path(file_rel), source=source)
    except SyntaxError:
        return []


def function_change_frequency(
    repo_root: Path,
    file_rel: str,
    spans: Iterable[FunctionSpan],
    since_days: int = 180,
) -> Dict[str, int]:
    """Number of commits (in the lookback window) whose diff overlapped each function.

    For every qualifying commit, the function spans are re-derived from that
    commit's own version of the file, so a hunk at (say) lines 20-30 is
    matched against where that function actually was *at that point in
    history*, not against where it is today.
    """
    current_qualnames = {span.qualname for span in spans}
    freq = {qualname: 0 for qualname in current_qualnames}
    if not current_qualnames:
        return freq

    commits = list_commits_touching(repo_root, file_rel, since_days)
    for commit in commits:
        ranges = changed_line_ranges(repo_root, commit, file_rel)
        if not ranges:
            continue
        historical_spans = _spans_at_commit(repo_root, commit, file_rel)
        touched_qualnames = {
            span.qualname
            for span in historical_spans
            if span.qualname in current_qualnames
            and any(s <= span.end_line and e >= span.start_line for s, e in ranges)
        }
        for qualname in touched_qualnames:
            freq[qualname] += 1
    return freq
