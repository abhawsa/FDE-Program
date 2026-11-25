from test_risk_agent.config import RiskWeights
from test_risk_agent.models import RiskCandidate
from test_risk_agent.risk_ranker import rank_candidates


def _candidate(**overrides) -> RiskCandidate:
    base = dict(
        file="pkg/mod.py",
        qualname="f",
        start_line=1,
        end_line=5,
        change_frequency=0,
        complexity=1,
        coverage_gap=1.0,
    )
    base.update(overrides)
    return RiskCandidate(**base)


def test_high_change_frequency_outranks_coverage_gap_alone():
    """Anti-pattern check: ranking must NOT be coverage-gap-only."""
    hot_path = _candidate(qualname="hot", change_frequency=12, complexity=6, coverage_gap=0.5)
    cold_but_fully_uncovered = _candidate(qualname="cold", change_frequency=0, complexity=1, coverage_gap=1.0)

    ranked = rank_candidates([cold_but_fully_uncovered, hot_path], RiskWeights(0.4, 0.3, 0.3).normalized())

    assert ranked[0].qualname == "hot"


def test_rank_candidates_sorts_descending_by_score():
    low = _candidate(qualname="low", change_frequency=1, complexity=1, coverage_gap=0.1)
    high = _candidate(qualname="high", change_frequency=10, complexity=10, coverage_gap=1.0)
    mid = _candidate(qualname="mid", change_frequency=5, complexity=5, coverage_gap=0.5)

    ranked = rank_candidates([low, high, mid], RiskWeights().normalized())

    assert [c.qualname for c in ranked] == ["high", "mid", "low"]
    assert ranked[0].risk_score >= ranked[1].risk_score >= ranked[2].risk_score


def test_rank_candidates_populates_rationale_and_components():
    candidate = _candidate(change_frequency=3, complexity=4, coverage_gap=0.75)
    ranked = rank_candidates([candidate], RiskWeights().normalized())

    assert ranked[0].rationale  # non-empty, human-readable
    components = ranked[0].risk_components
    assert "change_frequency_norm" in components
    assert "complexity_norm" in components
    assert components["coverage_gap"] == 0.75


def test_rank_candidates_handles_empty_list():
    assert rank_candidates([], RiskWeights().normalized()) == []


def test_weights_are_renormalized():
    weights = RiskWeights(change_frequency=4, complexity=3, coverage_gap=3).normalized()
    total = weights.change_frequency + weights.complexity + weights.coverage_gap
    assert abs(total - 1.0) < 1e-9
