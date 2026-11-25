"""Pure pipeline step functions shared by both orchestration engines.

- The LangGraph engine (graph.py) wraps each step_* function as a graph node.
- The dependency-free "simple" engine (run_simple_* below) calls them in a
  plain sequence, persisting state to a JSON file between CLI invocations.

Keeping the actual analyze/rank/generate/apply/report logic here (instead of
inside graph.py) means the pipeline runs identically - and is testable
identically - whether or not langgraph is installed.

Security note: LLM/LangFuse credentials are intentionally re-read from the
environment inside step_generate() rather than threaded through state, so
they are never written to a checkpoint file or the on-disk pipeline state.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, List

from agents import repo_scanner as analyzer
from agents import risk_ranker
from agents import test_generator
from audit import audit_log
from review import apply_tests
from review import review_queue
from workflow import coverage_delta as coverage_delta_mod
from workflow import reporting
from core.config import DATA_DIR, RiskWeights, Settings, ensure_data_dirs
from core.models import FunctionSpan, RiskCandidate, TestDraft

SIMPLE_STATE_PATH = DATA_DIR / "simple_pipeline_state.json"


def _span_to_dict(span: FunctionSpan) -> Dict[str, Any]:
    return dataclasses.asdict(span)


def _span_from_dict(d: Dict[str, Any]) -> FunctionSpan:
    return FunctionSpan(**d)


def step_analyze(state: Dict[str, Any]) -> Dict[str, Any]:
    repo_root = Path(state["repo_root"])
    source_root = Path(state["source_root"])
    coverage_json_path = Path(state["coverage_json_path"])
    candidates, spans = analyzer.analyze_repo(
        repo_root, source_root, coverage_json_path, lookback_days=state["lookback_days"]
    )
    span_index = {f"{s.file}::{s.qualname}": _span_to_dict(s) for s in spans}
    return {"candidates": [c.to_dict() for c in candidates], "span_index": span_index}


def step_rank(state: Dict[str, Any]) -> Dict[str, Any]:
    weights = RiskWeights(**state["weights"])
    candidates = [RiskCandidate.from_dict(c) for c in state["candidates"]]
    ranked = risk_ranker.rank_candidates(candidates, weights)
    top = ranked[: state["top_n"]]
    return {
        "candidates": [c.to_dict() for c in ranked],
        "top_candidates": [c.to_dict() for c in top],
    }


def step_generate(state: Dict[str, Any]) -> Dict[str, Any]:
    ensure_data_dirs()
    settings = Settings.from_env()
    span_index = state["span_index"]
    drafts: List[Dict[str, Any]] = []
    for candidate_dict in state["top_candidates"]:
        candidate = RiskCandidate.from_dict(candidate_dict)
        span_key = f"{candidate.file}::{candidate.qualname}"
        span = _span_from_dict(span_index[span_key])
        draft = test_generator.generate_draft(candidate, span, settings)
        review_queue.save_draft(draft)
        drafts.append(draft.to_dict())
    return {"drafts": drafts}


def step_refresh_drafts_from_queue(state: Dict[str, Any]) -> Dict[str, Any]:
    drafts = [review_queue.load_draft(d["id"]).to_dict() for d in state.get("drafts", [])]
    return {"drafts": drafts}


def step_apply(state: Dict[str, Any]) -> Dict[str, Any]:
    drafts = [TestDraft.from_dict(d) for d in state["drafts"]]
    tests_dir = Path(state["tests_dir"])
    result = apply_tests.apply_approved_drafts(drafts, tests_dir)
    return {"apply_result": result, "drafts": [d.to_dict() for d in drafts]}


def step_coverage_delta(state: Dict[str, Any]) -> Dict[str, Any]:
    repo_root = Path(state["repo_root"])
    before_json = Path(state["coverage_json_path"])
    after_json = Path(state["reports_dir"]) / "coverage_after.json"
    coverage_delta_mod.run_coverage(repo_root, state["source_pkg"], after_json)
    delta = coverage_delta_mod.compute_delta(before_json, after_json)
    return {"coverage_delta": delta}


def step_report(state: Dict[str, Any]) -> Dict[str, Any]:
    report_text = reporting.build_markdown_report(state)
    reports_dir = Path(state["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "latest_report.md"
    report_path.write_text(report_text, encoding="utf-8")
    raw_path = reports_dir / "latest_report.json"
    raw_path.write_text(
        json.dumps(
            {
                "candidates": state.get("candidates", []),
                "drafts": state.get("drafts", []),
                "apply_result": state.get("apply_result", {}),
                "coverage_delta": state.get("coverage_delta", {}),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    audit_log.export_json_array()
    return {"report_path": str(report_path)}


# --------------------------------------------------------------------------
# Dependency-free "simple" engine: same steps, run in sequence, state parked
# in a JSON file between separate CLI invocations instead of a LangGraph
# checkpointer. Used automatically when langgraph is not installed, or
# explicitly via --engine simple.
# --------------------------------------------------------------------------


def run_simple_analyze(initial_state: Dict[str, Any]) -> Dict[str, Any]:
    state = dict(initial_state)
    state.update(step_analyze(state))
    state.update(step_rank(state))
    state.update(step_generate(state))
    ensure_data_dirs()
    SIMPLE_STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    return state


def load_simple_state() -> Dict[str, Any]:
    if not SIMPLE_STATE_PATH.exists():
        raise RuntimeError(
            "No paused run found for the simple engine. Run `analyze --engine simple` first."
        )
    return json.loads(SIMPLE_STATE_PATH.read_text(encoding="utf-8"))


def run_simple_apply() -> Dict[str, Any]:
    state = load_simple_state()
    state.update(step_refresh_drafts_from_queue(state))
    state.update(step_apply(state))
    state.update(step_coverage_delta(state))
    state.update(step_report(state))
    SIMPLE_STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    return state
