"""AST-based function discovery and cyclomatic complexity.

No third-party dependency (e.g. radon) on purpose: this is a small,
auditable, self-contained implementation so reviewers can trust exactly
what "complexity" means here.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional

from .models import FunctionSpan

_LINEAR_DECISION_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.Assert,
)


def cyclomatic_complexity(node: ast.AST) -> int:
    """McCabe-style cyclomatic complexity: 1 + number of independent decision points."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, _LINEAR_DECISION_NODES):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            # `a and b and c` contributes 2 extra branches, not 1.
            complexity += max(len(child.values) - 1, 0)
        elif isinstance(child, ast.IfExp):
            complexity += 1
        elif isinstance(child, ast.comprehension):
            complexity += 1 + len(child.ifs)
        elif type(child).__name__ == "match_case":
            # ast.Match/match_case only exist on Python 3.10+; matched by
            # class name so this stays harmless on anything that lacks it.
            complexity += 1
    return complexity


def extract_function_spans(file_path: Path, source: Optional[str] = None) -> List[FunctionSpan]:
    """Return every (possibly nested) function/method defined in a source file."""
    source = source if source is not None else file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    lines = source.splitlines()
    spans: List[FunctionSpan] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                end_line = getattr(child, "end_lineno", child.lineno)
                snippet = "\n".join(lines[child.lineno - 1 : end_line])
                spans.append(
                    FunctionSpan(
                        file=str(file_path),
                        qualname=qualname,
                        start_line=child.lineno,
                        end_line=end_line,
                        complexity=cyclomatic_complexity(child),
                        source=snippet,
                    )
                )
                visit(child, prefix=f"{qualname}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix=f"{prefix}{child.name}.")
            else:
                visit(child, prefix=prefix)

    visit(tree, prefix="")
    return spans
