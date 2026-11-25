"""Shared data structures passed between pipeline stages.

Everything here is a plain dataclass with to_dict/from_dict so it can be
serialized to JSON for the on-disk human review queue and audit log -
no ORM, no database, just files a reviewer can open and read.
"""
from __future__ import annotations

import dataclasses
import time
import uuid
from typing import Any, Dict, List, Optional


def new_draft_id() -> str:
    return f"draft_{uuid.uuid4().hex[:12]}"


@dataclasses.dataclass
class FunctionSpan:
    """A single function/method found via AST parsing of a source file."""

    file: str
    qualname: str
    start_line: int
    end_line: int
    complexity: int
    source: str


@dataclasses.dataclass
class RiskCandidate:
    """An untested (or partially tested) code path with its risk inputs."""

    file: str
    qualname: str
    start_line: int
    end_line: int
    change_frequency: int
    complexity: int
    coverage_gap: float  # fraction in [0, 1] of the function's lines that are uncovered
    missing_lines: List[int] = dataclasses.field(default_factory=list)
    risk_score: float = 0.0
    risk_components: Dict[str, Any] = dataclasses.field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RiskCandidate":
        return RiskCandidate(**d)


@dataclasses.dataclass
class TestDraft:
    """A candidate test generated for one RiskCandidate, pending human review.

    status lifecycle: pending -> approved | edited | rejected -> applied
    (applied only happens after an explicit `apply` step writes it to disk;
    rejected drafts are never written anywhere outside the review queue).
    """

    __test__ = False  # not a pytest test class, despite the name

    id: str
    candidate: Dict[str, Any]
    code: str
    framework: str = "pytest"
    status: str = "pending"
    low_value: bool = False
    low_value_reasons: List[str] = dataclasses.field(default_factory=list)
    reviewer: Optional[str] = None
    reviewer_comment: Optional[str] = None
    generated_by: str = "template"  # "llm" | "template"
    trace_id: Optional[str] = None
    target_test_path: Optional[str] = None
    created_at: float = dataclasses.field(default_factory=time.time)
    updated_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TestDraft":
        return TestDraft(**d)
