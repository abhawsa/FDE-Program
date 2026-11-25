"""The human review queue: one JSON file per draft under data/review_queue/.

This is the Human Review Gate. Nothing in this module ever writes a
generated test into the real test suite - that only happens in
apply_tests.py, and only for drafts whose status is "approved" or "edited".
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

from . import audit_log
from . import low_value_detector
from .config import REVIEW_QUEUE_DIR, ensure_data_dirs
from .models import TestDraft

VALID_DECISIONS = {"approve", "edit", "reject"}


def _path_for(draft_id: str) -> Path:
    return REVIEW_QUEUE_DIR / f"{draft_id}.json"


def save_draft(draft: TestDraft) -> Path:
    ensure_data_dirs()
    path = _path_for(draft.id)
    path.write_text(json.dumps(draft.to_dict(), indent=2, default=str), encoding="utf-8")
    return path


def load_draft(draft_id: str) -> TestDraft:
    path = _path_for(draft_id)
    if not path.exists():
        raise FileNotFoundError(f"No draft found with id {draft_id!r}")
    return TestDraft.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_drafts(status: Optional[str] = None) -> List[TestDraft]:
    ensure_data_dirs()
    drafts = []
    for path in sorted(REVIEW_QUEUE_DIR.glob("draft_*.json")):
        draft = TestDraft.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if status is None or draft.status == status:
            drafts.append(draft)
    # Highest risk first, so a reviewer always sees the most regression-prone
    # path at the top of the queue regardless of on-disk file ordering.
    drafts.sort(key=lambda d: d.candidate.get("risk_score", 0.0), reverse=True)
    return drafts


def apply_decision(
    draft_id: str,
    decision: str,
    reviewer: str,
    comment: Optional[str] = None,
    edited_code: Optional[str] = None,
) -> TestDraft:
    if decision not in VALID_DECISIONS:
        raise ValueError(f"invalid decision {decision!r}, expected one of {sorted(VALID_DECISIONS)}")

    draft = load_draft(draft_id)

    if decision == "edit":
        if not edited_code or not edited_code.strip():
            raise ValueError("edited_code is required for an 'edit' decision")
        draft.code = edited_code
        draft.status = "edited"
        draft.low_value_reasons = low_value_detector.evaluate_test_code(edited_code)
        draft.low_value = bool(draft.low_value_reasons)
    elif decision == "approve":
        draft.status = "approved"
    else:
        draft.status = "rejected"

    draft.reviewer = reviewer
    draft.reviewer_comment = comment
    draft.updated_at = time.time()
    save_draft(draft)

    audit_log.record(
        "review_decision",
        {
            "draft_id": draft.id,
            "decision": decision,
            "reviewer": reviewer,
            "comment": comment,
            "file": draft.candidate.get("file"),
            "qualname": draft.candidate.get("qualname"),
            "risk_score": draft.candidate.get("risk_score"),
            "risk_components": draft.candidate.get("risk_components"),
            "low_value": draft.low_value,
            "low_value_reasons": draft.low_value_reasons,
            "trace_id": draft.trace_id,
        },
    )
    return draft


def queue_summary() -> dict:
    drafts = list_drafts()
    summary = {"total": len(drafts)}
    for status in ("pending", "approved", "edited", "rejected", "applied"):
        summary[status] = sum(1 for d in drafts if d.status == status)
    return summary
