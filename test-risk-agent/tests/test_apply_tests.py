from pathlib import Path

import pytest

from review import apply_tests, review_queue
from audit import audit_log
from core.models import TestDraft, new_draft_id


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch):
    queue_dir = tmp_path / "review_queue"
    queue_dir.mkdir()
    monkeypatch.setattr(review_queue, "REVIEW_QUEUE_DIR", queue_dir)
    monkeypatch.setattr(review_queue, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(audit_log, "ensure_data_dirs", lambda: None)
    yield


def _draft(status: str, code: str = "def test_f():\n    assert 1 == 1\n", **overrides) -> TestDraft:
    base = dict(
        id=new_draft_id(),
        candidate={"file": "pkg/mod.py", "qualname": "f", "risk_score": 0.5, "risk_components": {}},
        code=code,
        status=status,
    )
    base.update(overrides)
    draft = TestDraft(**base)
    review_queue.save_draft(draft)
    return draft


def test_applies_only_approved_and_edited_drafts(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    approved = _draft("approved", code="def test_a():\n    assert True == True\n", candidate={"qualname": "a"})
    edited = _draft("edited", code="def test_b():\n    assert 2 == 2\n", candidate={"qualname": "b"})
    pending = _draft("pending", candidate={"qualname": "c"})
    rejected = _draft("rejected", candidate={"qualname": "d"})

    result = apply_tests.apply_approved_drafts([approved, edited, pending, rejected], tests_dir)

    assert set(result["applied"]) == {approved.id, edited.id}
    assert set(result["skipped"]) == {pending.id, rejected.id}
    assert result["conflicts"] == []
    assert (tests_dir / "test_generated_a.py").exists()
    assert (tests_dir / "test_generated_b.py").exists()
    assert not (tests_dir / "test_generated_c.py").exists()


def test_never_overwrites_a_conflicting_existing_file(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    target = tests_dir / "test_generated_a.py"
    target.write_text("def test_a():\n    assert 'human-written' == 'human-written'\n", encoding="utf-8")

    draft = _draft("approved", code="def test_a():\n    assert 'llm-written' == 'llm-written'\n", candidate={"qualname": "a"})

    result = apply_tests.apply_approved_drafts([draft], tests_dir)

    assert result["conflicts"] == [{"draft_id": draft.id, "path": str(target)}]
    assert result["applied"] == []
    # The human-written file on disk must be untouched.
    assert "human-written" in target.read_text(encoding="utf-8")

    entries = audit_log.read_all()
    assert any(e["event"] == "apply_conflict" for e in entries)


def test_reapplying_identical_content_is_idempotent(tmp_path: Path):
    """A second analyze/review cycle that drafts byte-identical content for the
    same function should apply cleanly, not be treated as a conflict."""
    tests_dir = tmp_path / "tests"
    draft1 = _draft("approved", code="def test_a():\n    assert 1 == 1\n", candidate={"qualname": "a"})
    first = apply_tests.apply_approved_drafts([draft1], tests_dir)
    assert first["applied"] == [draft1.id]
    assert draft1.status == "applied"

    draft2 = _draft("approved", code="def test_a():\n    assert 1 == 1\n", candidate={"qualname": "a"})
    second = apply_tests.apply_approved_drafts([draft2], tests_dir)

    assert second["applied"] == [draft2.id]
    assert second["conflicts"] == []
