"""Combines change frequency, complexity, and coverage gap into one risk score.

Deliberately NOT "rank by coverage gap alone" - see problem statement
anti-patterns. change_frequency and complexity are log-scaled then min-max
normalized across the candidate set (their raw scales are unbounded and not
comparable to each other or to the already-0..1 coverage_gap).
"""
from __future__ import annotations

import math
from typing import List

from .config import RiskWeights
from .models import RiskCandidate


def _minmax_normalize(values: List[float]) -> List[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def rank_candidates(candidates: List[RiskCandidate], weights: RiskWeights) -> List[RiskCandidate]:
    """Scores and sorts candidates in place (highest risk first). Returns the same list."""
    if not candidates:
        return candidates

    freq_log = [math.log1p(max(c.change_frequency, 0)) for c in candidates]
    complexity_log = [math.log1p(max(c.complexity, 0)) for c in candidates]
    freq_norm = _minmax_normalize(freq_log)
    complexity_norm = _minmax_normalize(complexity_log)

    for candidate, f_norm, x_norm in zip(candidates, freq_norm, complexity_norm):
        score = (
            weights.change_frequency * f_norm
            + weights.complexity * x_norm
            + weights.coverage_gap * candidate.coverage_gap
        )
        candidate.risk_components = {
            "change_frequency_raw": candidate.change_frequency,
            "change_frequency_norm": round(f_norm, 4),
            "complexity_raw": candidate.complexity,
            "complexity_norm": round(x_norm, 4),
            "coverage_gap": round(candidate.coverage_gap, 4),
            "weights": {
                "change_frequency": round(weights.change_frequency, 4),
                "complexity": round(weights.complexity, 4),
                "coverage_gap": round(weights.coverage_gap, 4),
            },
        }
        candidate.risk_score = round(score, 4)
        candidate.rationale = (
            f"Changed in {candidate.change_frequency} commit(s) in the lookback window "
            f"(normalized {f_norm:.2f}); cyclomatic complexity {candidate.complexity} "
            f"(normalized {x_norm:.2f}); {candidate.coverage_gap * 100:.0f}% of this "
            f"function's lines are uncovered. Weighted risk score = {candidate.risk_score:.3f}."
        )

    candidates.sort(key=lambda c: c.risk_score, reverse=True)
    return candidates
