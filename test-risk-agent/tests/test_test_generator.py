from agents import test_generator
from core.config import Settings
from core.models import FunctionSpan, RiskCandidate


def _candidate_and_span():
    candidate = RiskCandidate(
        file="billing/discounts.py",
        qualname="apply_discount",
        start_line=10,
        end_line=20,
        change_frequency=8,
        complexity=5,
        coverage_gap=1.0,
        missing_lines=[11, 12, 13],
        risk_score=0.9,
        risk_components={},
        rationale="high change frequency and fully uncovered",
    )
    span = FunctionSpan(
        file="billing/discounts.py",
        qualname="apply_discount",
        start_line=10,
        end_line=20,
        complexity=5,
        source="def apply_discount(subtotal, quantity):\n    return subtotal\n",
    )
    return candidate, span


def test_generate_draft_falls_back_to_template_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    candidate, span = _candidate_and_span()
    settings = Settings.from_env()

    draft = test_generator.generate_draft(candidate, span, settings)

    assert draft.generated_by == "template"
    assert "from billing.discounts import apply_discount" in draft.code
    assert draft.status == "pending"


def test_template_draft_is_flagged_low_value(monkeypatch):
    """The honest TODO stub must never be mistaken for a real, confidence-inspiring test."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    candidate, span = _candidate_and_span()
    settings = Settings.from_env()

    draft = test_generator.generate_draft(candidate, span, settings)

    assert draft.low_value is True
    assert draft.low_value_reasons


def test_import_statement_uses_top_level_name_for_nested_qualname():
    stmt = test_generator._import_statement("billing/discounts.py", "Helper.apply_discount")
    assert stmt == "from billing.discounts import Helper"


def test_strip_markdown_fences_removes_wrapping_fences():
    wrapped = "```python\ndef test_x():\n    assert 1 == 1\n```"
    assert test_generator._strip_markdown_fences(wrapped) == "def test_x():\n    assert 1 == 1\n"
