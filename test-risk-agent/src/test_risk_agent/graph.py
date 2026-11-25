"""LangGraph orchestration: analyze -> rank -> generate -> human_review -> apply -> report.

The human_review node calls `interrupt()`, which genuinely pauses execution
(persisted via a SQLite checkpointer so it survives across separate CLI
process invocations) until a human has reviewed the drafts and a later CLI
command resumes the graph. This module is only imported when `langgraph`
is installed; cli.py falls back to pipeline.py's dependency-free sequential
engine otherwise.
"""
from __future__ import annotations

from typing import Any, Dict, List, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import pipeline
from .config import CHECKPOINT_DB_PATH, ensure_data_dirs


class PipelineState(TypedDict, total=False):
    repo_root: str
    source_root: str
    tests_dir: str
    coverage_json_path: str
    source_pkg: str
    reports_dir: str
    audit_log_path: str
    lookback_days: int
    top_n: int
    weights: dict
    candidates: List[dict]
    top_candidates: List[dict]
    span_index: dict
    drafts: List[dict]
    apply_result: dict
    coverage_delta: dict
    report_path: str


def _node_analyze(state: PipelineState) -> Dict[str, Any]:
    return pipeline.step_analyze(state)


def _node_rank(state: PipelineState) -> Dict[str, Any]:
    return pipeline.step_rank(state)


def _node_generate(state: PipelineState) -> Dict[str, Any]:
    return pipeline.step_generate(state)


def _node_human_review(state: PipelineState) -> Dict[str, Any]:
    pending_ids = [d["id"] for d in state.get("drafts", []) if d["status"] == "pending"]
    interrupt(
        {
            "message": (
                "Paused for human review. Run `review` to approve/edit/reject each "
                "drafted test, then `apply` to resume this run."
            ),
            "pending_draft_ids": pending_ids,
        }
    )
    # Resumed: re-read authoritative decisions from the on-disk review queue
    # rather than trusting whatever was threaded through the resume value.
    return pipeline.step_refresh_drafts_from_queue(state)


def _node_apply(state: PipelineState) -> Dict[str, Any]:
    return pipeline.step_apply(state)


def _node_compute_coverage_delta(state: PipelineState) -> Dict[str, Any]:
    return pipeline.step_coverage_delta(state)


def _node_report(state: PipelineState) -> Dict[str, Any]:
    return pipeline.step_report(state)


def build_graph() -> StateGraph:
    graph = StateGraph(PipelineState)
    graph.add_node("analyze", _node_analyze)
    graph.add_node("rank", _node_rank)
    graph.add_node("generate", _node_generate)
    graph.add_node("human_review", _node_human_review)
    graph.add_node("apply", _node_apply)
    graph.add_node("compute_coverage_delta", _node_compute_coverage_delta)
    graph.add_node("report", _node_report)

    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "rank")
    graph.add_edge("rank", "generate")
    graph.add_edge("generate", "human_review")
    graph.add_edge("human_review", "apply")
    graph.add_edge("apply", "compute_coverage_delta")
    graph.add_edge("compute_coverage_delta", "report")
    graph.add_edge("report", END)
    return graph


def sqlite_checkpointer_cm():
    """Context manager yielding a SqliteSaver backed by data/graph_checkpoints.sqlite."""
    ensure_data_dirs()
    return SqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH))


def compiled_app(checkpointer):
    return build_graph().compile(checkpointer=checkpointer)


def thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}
