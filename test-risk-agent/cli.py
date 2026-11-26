"""Command-line entrypoint. Run from the project root (test-risk-agent/):

    python cli.py baseline   # produce the input coverage.json
    python cli.py analyze    # analyze -> rank -> generate, pause for review
    python cli.py review     # interactive approve / edit / reject queue
    python cli.py apply      # resume: write approved tests, coverage delta, report
    python cli.py status     # review queue counts
    python cli.py report     # print the latest run report

See README.md for the full walkthrough.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from workflow import coverage_delta as coverage_delta_mod
from workflow import pipeline
from review import review_queue
from core.config import (
    AUDIT_LOG_PATH,
    PROJECT_ROOT,
    REPORTS_DIR,
    ensure_data_dirs,
    load_risk_weights,
)
from core.models import TestDraft
from core.tracing import tracer
from workflow.reporting import render_draft_outcomes, render_risk_table

DEFAULT_TARGET_REPO = PROJECT_ROOT / "sample_target_repo"


def _select_engine(requested: str) -> str:
    if requested in ("simple", "langgraph"):
        return requested
    try:
        import langgraph  # noqa: F401

        return "langgraph"
    except ImportError:
        return "simple"


def _default_reviewer() -> str:
    try:
        result = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=False
        )
        name = result.stdout.strip()
        if name:
            return name
    except Exception:
        pass
    return os.environ.get("USERNAME") or os.environ.get("USER") or "reviewer"


def _add_common_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", default=str(DEFAULT_TARGET_REPO))
    parser.add_argument("--source-root", default=None, help="defaults to --repo-root")
    parser.add_argument("--tests-dir", default=None, help="defaults to <repo-root>/tests")
    parser.add_argument("--coverage-json", default=None, help="defaults to <repo-root>/coverage.json")
    parser.add_argument("--source-pkg", default="billing,inventory")


def cmd_baseline(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root)
    out_json = Path(args.coverage_json) if args.coverage_json else repo_root / "coverage.json"
    print(f"Running pytest + coverage over {repo_root} (source={args.source_pkg}) ...")
    result = coverage_delta_mod.run_coverage(repo_root, args.source_pkg, out_json)
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    print(f"\nBaseline coverage report written to: {out_json}")


def cmd_analyze(args: argparse.Namespace) -> None:
    ensure_data_dirs()
    repo_root = Path(args.repo_root).resolve()
    source_root = Path(args.source_root).resolve() if args.source_root else repo_root
    tests_dir = Path(args.tests_dir).resolve() if args.tests_dir else repo_root / "tests"
    coverage_json = Path(args.coverage_json).resolve() if args.coverage_json else repo_root / "coverage.json"

    if not coverage_json.exists():
        print(
            f"Coverage report not found at {coverage_json}.\n"
            "Run `baseline` first to generate it.",
            file=sys.stderr,
        )
        sys.exit(1)

    initial_state: Dict[str, Any] = {
        "repo_root": str(repo_root),
        "source_root": str(source_root),
        "tests_dir": str(tests_dir),
        "coverage_json_path": str(coverage_json),
        "source_pkg": args.source_pkg,
        "reports_dir": str(REPORTS_DIR),
        "audit_log_path": str(AUDIT_LOG_PATH),
        "lookback_days": args.lookback_days,
        "top_n": args.top_n,
        "weights": dataclasses.asdict(load_risk_weights()),
    }

    engine = _select_engine(args.engine)
    print(f"Running analyze -> rank -> generate (engine={engine}) ...")

    if engine == "langgraph":
        from workflow import langgraph_orchestrator as graph_mod

        with graph_mod.sqlite_checkpointer_cm() as checkpointer:
            app = graph_mod.compiled_app(checkpointer)
            config = graph_mod.thread_config(args.thread_id)
            state = app.invoke(initial_state, config=config)
    else:
        state = pipeline.run_simple_analyze(initial_state)

    candidates = state.get("candidates", [])
    drafts = state.get("drafts", [])

    print("\n" + render_risk_table(candidates))
    print("\n" + render_draft_outcomes(drafts))
    print(
        f"\n{len(drafts)} candidate test(s) drafted and queued for human review "
        f"(out of {len(candidates)} untested risky path(s) found)."
    )
    print("Next: `review` to approve/edit/reject, then `apply` to finalize.")

    tracer.flush()
    if tracer.enabled:
        print(f"\nLangFuse: flushed {len(drafts)} test_generation trace(s) for this run.")
        for draft in drafts:
            url = tracer.trace_url(draft.get("trace_id"))
            if url:
                print(f"  {draft['candidate']['qualname']}: {url}")


def _render_draft(draft: TestDraft) -> None:
    c = draft.candidate
    print("=" * 78)
    print(f"Draft {draft.id}  (generated_by={draft.generated_by})")
    print(f"  File:        {c['file']}")
    print(f"  Function:    {c['qualname']} (lines {c['start_line']}-{c['end_line']})")
    print(f"  Risk score:  {c['risk_score']:.3f}")
    print(f"  Rationale:   {c['rationale']}")
    if draft.low_value:
        print("  LOW-VALUE WARNING:")
        for reason in draft.low_value_reasons:
            print(f"    - {reason}")
    print("-" * 78)
    print(draft.code)
    print("=" * 78)


def _edit_via_tempfile(code: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write(code)
        temp_path = fh.name
    print(f"\nEdit the draft at: {temp_path}")
    input("Save your changes, then press Enter here to continue...")
    content = Path(temp_path).read_text(encoding="utf-8")
    try:
        os.remove(temp_path)
    except OSError:
        pass
    return content


def cmd_review(args: argparse.Namespace) -> None:
    pending = review_queue.list_drafts(status="pending")
    if not pending:
        print("No pending drafts to review.")
        return

    reviewer = args.reviewer or _default_reviewer()
    print(f"Reviewing {len(pending)} draft(s) as '{reviewer}'.\n")

    for draft in pending:
        _render_draft(draft)
        action = input("Decision - [a]pprove / [e]dit / [r]eject / [s]kip: ").strip().lower()
        if action in ("", "s", "skip"):
            print("Skipped (left pending).\n")
            continue
        comment = input("Optional comment (Enter to skip): ").strip() or None

        if action in ("a", "approve"):
            review_queue.apply_decision(draft.id, "approve", reviewer, comment)
            print("-> Approved.\n")
        elif action in ("r", "reject"):
            review_queue.apply_decision(draft.id, "reject", reviewer, comment)
            print("-> Rejected.\n")
        elif action in ("e", "edit"):
            edited_code = _edit_via_tempfile(draft.code)
            review_queue.apply_decision(draft.id, "edit", reviewer, comment, edited_code=edited_code)
            print("-> Saved your edited version (status=edited).\n")
        else:
            print(f"Unrecognized action {action!r}, left pending.\n")

    print("Review session complete. Run `status` for totals, `apply` once you're ready to finalize.")


def cmd_apply(args: argparse.Namespace) -> None:
    engine = _select_engine(args.engine)
    print(f"Resuming pipeline (engine={engine}) ...")

    if engine == "langgraph":
        from langgraph.types import Command

        from workflow import langgraph_orchestrator as graph_mod

        with graph_mod.sqlite_checkpointer_cm() as checkpointer:
            app = graph_mod.compiled_app(checkpointer)
            config = graph_mod.thread_config(args.thread_id)
            current = app.get_state(config)
            if not current.next:
                print(
                    "No paused run found for this thread. Run `analyze` first "
                    f"(thread-id={args.thread_id!r}).",
                    file=sys.stderr,
                )
                sys.exit(1)
            state = app.invoke(Command(resume="reviewed"), config=config)
    else:
        state = pipeline.run_simple_apply()

    apply_result = state.get("apply_result", {})
    print(f"\nApplied: {len(apply_result.get('applied', []))}")
    print(f"Conflicts: {len(apply_result.get('conflicts', []))}")
    print(f"Skipped (not approved/edited): {len(apply_result.get('skipped', []))}")
    for conflict in apply_result.get("conflicts", []):
        print(f"  CONFLICT: {conflict['draft_id']} -> {conflict['path']} (needs manual resolution)")

    delta = state.get("coverage_delta")
    if delta:
        print(
            f"\nCoverage: {delta['overall_before']:.1f}% -> {delta['overall_after']:.1f}% "
            f"({delta['overall_delta']:+.1f} pts)"
        )
    print(f"\nFull report: {state.get('report_path')}")


def cmd_status(_args: argparse.Namespace) -> None:
    summary = review_queue.queue_summary()
    print("Review queue summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


def cmd_report(_args: argparse.Namespace) -> None:
    report_path = REPORTS_DIR / "latest_report.md"
    if not report_path.exists():
        print("No report yet - run `analyze` then `apply` first.")
        return
    print(report_path.read_text(encoding="utf-8"))


def cmd_ui(args: argparse.Namespace) -> None:
    from webui.app import main as run_webui

    sys.argv = ["webui", "--host", args.host, "--port", str(args.port)]
    run_webui()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_baseline = sub.add_parser("baseline", help="run pytest+coverage to produce the input coverage.json")
    _add_common_target_args(p_baseline)
    p_baseline.set_defaults(func=cmd_baseline)

    p_analyze = sub.add_parser("analyze", help="analyze -> rank -> generate, then pause for review")
    _add_common_target_args(p_analyze)
    p_analyze.add_argument("--lookback-days", type=int, default=180)
    p_analyze.add_argument("--top-n", type=int, default=10)
    p_analyze.add_argument("--engine", choices=["auto", "simple", "langgraph"], default="auto")
    p_analyze.add_argument("--thread-id", default="default")
    p_analyze.set_defaults(func=cmd_analyze)

    p_review = sub.add_parser("review", help="interactively approve/edit/reject pending drafts")
    p_review.add_argument("--reviewer", default=None)
    p_review.set_defaults(func=cmd_review)

    p_apply = sub.add_parser("apply", help="resume the paused run: apply approved tests + coverage delta + report")
    p_apply.add_argument("--engine", choices=["auto", "simple", "langgraph"], default="auto")
    p_apply.add_argument("--thread-id", default="default")
    p_apply.set_defaults(func=cmd_apply)

    p_status = sub.add_parser("status", help="show review queue counts")
    p_status.set_defaults(func=cmd_status)

    p_report = sub.add_parser("report", help="print the latest run report")
    p_report.set_defaults(func=cmd_report)

    p_ui = sub.add_parser("ui", help="launch the local web control panel")
    p_ui.add_argument("--host", default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=5151)
    p_ui.set_defaults(func=cmd_ui)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
