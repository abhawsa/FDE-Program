"""Writes approved/edited drafts into the real test suite.

This is the ONLY place in the codebase allowed to write a generated test
into tests_dir, and it only ever does so for drafts whose status is
"approved" or "edited" - a rejected or still-pending draft is never
touched. Conflicts with an existing file are flagged, never overwritten.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from . import audit_log
from . import review_queue
from .models import TestDraft

APPLIED_STATUSES = {"approved", "edited"}


def _target_filename(draft: TestDraft) -> str:
    qualname = draft.candidate["qualname"]
    safe = "".join(ch if ch.isalnum() else "_" for ch in qualname).strip("_").lower()
    return f"test_generated_{safe}.py"


def apply_approved_drafts(drafts: List[TestDraft], tests_dir: Path) -> Dict[str, list]:
    tests_dir.mkdir(parents=True, exist_ok=True)
    applied: List[str] = []
    conflicts: List[dict] = []
    skipped: List[str] = []

    for draft in drafts:
        if draft.status not in APPLIED_STATUSES:
            skipped.append(draft.id)
            continue

        target_path = tests_dir / _target_filename(draft)

        if target_path.exists():
            existing = target_path.read_text(encoding="utf-8")
            if existing.strip() == draft.code.strip():
                # Idempotent re-apply of a draft that's already on disk.
                draft.target_test_path = str(target_path)
                applied.append(draft.id)
                continue
            conflicts.append({"draft_id": draft.id, "path": str(target_path)})
            audit_log.record(
                "apply_conflict",
                {
                    "draft_id": draft.id,
                    "path": str(target_path),
                    "reason": "an existing generated test file differs from this draft; "
                    "refusing to silently overwrite it - resolve manually",
                },
            )
            continue

        target_path.write_text(draft.code, encoding="utf-8")
        draft.target_test_path = str(target_path)
        draft.status = "applied"
        review_queue.save_draft(draft)

        applied.append(draft.id)
        audit_log.record(
            "test_applied",
            {
                "draft_id": draft.id,
                "file": draft.candidate.get("file"),
                "qualname": draft.candidate.get("qualname"),
                "risk_score": draft.candidate.get("risk_score"),
                "risk_components": draft.candidate.get("risk_components"),
                "target_path": str(target_path),
                "reviewer": draft.reviewer,
                "trace_id": draft.trace_id,
            },
        )

    return {"applied": applied, "conflicts": conflicts, "skipped": skipped}
