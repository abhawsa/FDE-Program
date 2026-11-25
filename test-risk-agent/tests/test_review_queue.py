from pathlib import Path

import pytest

from test_risk_agent import audit_log, review_queue
from test_risk_agent.models import TestDraft, new_draft_id


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch):
    """Redirect the review queue and audit log to a throwaway tmp_path for every test."""
    queue_dir = tmp_path / "review_queue"
    queue_dir.mkdir()
    monkeypatch.setattr(review_queue, "REVIEW_QUEUE_DIR", queue_dir)
    monkeypatch.setattr(review_queue, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(audit_log, "ensure_data_dirs", lambda: None)
    yield


def _draft(**overrides) -> TestDraft:
    base = dict(
        id=new_draft_id(),
        candidate={"file": "pkg/mod.py", "qualname": "f", "risk_score": 0.5, "risk_components": {}},
        code="def test_f():\n    assert f() == 1\n",
    )
    base.update(overrides)
    return TestDraft(**base)


def test_save_and_load_roundtrip():
    draft = _draft()
    review_queue.save_draft(draft)

    loaded = review_queue.load_draft(draft.id)

    assert loaded.id == draft.id
    assert loaded.code == draft.code
    assert loaded.status == "pending"


def test_load_draft_missing_raises():
    with pytest.raises(FileNotFoundError):
        review_queue.load_draft("draft_doesnotexist")


def test_list_drafts_filters_by_status():
    pending = _draft()
    review_queue.save_draft(pending)
    approved = _draft()
    review_queue.save_draft(approved)
    review_queue.apply_decision(approved.id, "approve", reviewer="alice")

    only_pending = review_queue.list_drafts(status="pending")
    only_approved = review_queue.list_drafts(status="approved")

    assert [d.id for d in only_pending] == [pending.id]
    assert [d.id for d in only_approved] == [approved.id]


def test_apply_decision_approve():
    draft = _draft()
    review_queue.save_draft(draft)

    updated = review_queue.apply_decision(draft.id, "approve", reviewer="alice", comment="looks right")

    assert updated.status == "approved"
    assert updated.reviewer == "alice"
    assert updated.reviewer_comment == "looks right"


def test_apply_decision_reject():
    draft = _draft()
    review_queue.save_draft(draft)

    updated = review_queue.apply_decision(draft.id, "reject", reviewer="bob")

    assert updated.status == "rejected"


def test_apply_decision_edit_requires_code_and_reruns_low_value_check():
    draft = _draft(code="def test_f():\n    pass\n")
    review_queue.save_draft(draft)

    with pytest.raises(ValueError):
        review_queue.apply_decision(draft.id, "edit", reviewer="alice", edited_code="")

    updated = review_queue.apply_decision(
        draft.id, "edit", reviewer="alice", edited_code="def test_f():\n    assert f() == 1\n"
    )

    assert updated.status == "edited"
    assert updated.low_value is False


def test_apply_decision_invalid_decision_raises():
    draft = _draft()
    review_queue.save_draft(draft)
    with pytest.raises(ValueError):
        review_queue.apply_decision(draft.id, "maybe", reviewer="alice")


def test_apply_decision_writes_audit_entry():
    draft = _draft()
    review_queue.save_draft(draft)

    review_queue.apply_decision(draft.id, "approve", reviewer="alice")

    entries = audit_log.read_all()
    assert len(entries) == 1
    assert entries[0]["event"] == "review_decision"
    assert entries[0]["draft_id"] == draft.id
    assert entries[0]["reviewer"] == "alice"


def test_queue_summary_counts_each_status():
    a, b, c = _draft(), _draft(), _draft()
    for d in (a, b, c):
        review_queue.save_draft(d)
    review_queue.apply_decision(a.id, "approve", reviewer="alice")
    review_queue.apply_decision(b.id, "reject", reviewer="alice")

    summary = review_queue.queue_summary()

    assert summary["total"] == 3
    assert summary["pending"] == 1
    assert summary["approved"] == 1
    assert summary["rejected"] == 1
