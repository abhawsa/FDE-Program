"""Local web control panel for the AI Test Coverage & Regression Risk Agent.

Wraps the same pipeline modules the CLI uses (agents/, workflow/, review/,
audit/, core/) behind a small Flask app, so the analyze -> review -> apply
loop can be driven by clicking buttons instead of running `python cli.py
...` each time. This is a convenience layer only - it calls the exact same
functions as cli.py, nothing is duplicated or reimplemented.

Always uses the dependency-free "simple" engine (workflow.pipeline), not
the LangGraph StateGraph: a stateless HTTP request per click is a better
fit for that than a cross-process interrupt()/resume thread. The LangGraph
engine (with its real interrupt()-based pause) remains available via
`python cli.py analyze --engine langgraph` for that orchestration path.

Run with:  python webui/app.py   (or: python cli.py ui)
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

from audit import audit_log  # noqa: E402
from core.config import REPORTS_DIR, ensure_data_dirs, load_risk_weights  # noqa: E402
from review import review_queue  # noqa: E402
from workflow import pipeline  # noqa: E402

DEFAULT_TARGET_REPO = PROJECT_ROOT / "sample_target_repo"

app = Flask(__name__, static_folder=str(Path(__file__).parent / "static"), static_url_path="")


def _error_response(exc: Exception, status: int = 400):
    return jsonify({"error": str(exc), "trace": traceback.format_exc()}), status


def _target_defaults(body: Dict[str, Any]) -> Dict[str, Any]:
    repo_root = Path(body.get("repo_root") or DEFAULT_TARGET_REPO).resolve()
    source_root = Path(body["source_root"]).resolve() if body.get("source_root") else repo_root
    tests_dir = Path(body["tests_dir"]).resolve() if body.get("tests_dir") else repo_root / "tests"
    coverage_json = (
        Path(body["coverage_json"]).resolve() if body.get("coverage_json") else repo_root / "coverage.json"
    )
    return {
        "repo_root": repo_root,
        "source_root": source_root,
        "tests_dir": tests_dir,
        "coverage_json": coverage_json,
        "source_pkg": body.get("source_pkg") or "billing,inventory",
    }


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status")
def api_status():
    ensure_data_dirs()
    summary = review_queue.queue_summary()
    report_path = REPORTS_DIR / "latest_report.md"
    report_json_path = REPORTS_DIR / "latest_report.json"
    return jsonify(
        {
            "queue": summary,
            "has_paused_simple_run": pipeline.SIMPLE_STATE_PATH.exists(),
            "has_report": report_path.exists(),
            "report_summary": _read_report_summary(report_json_path),
        }
    )


def _read_report_summary(report_json_path: Path):
    if not report_json_path.exists():
        return None
    import json

    try:
        data = json.loads(report_json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return {
        "coverage_delta": data.get("coverage_delta"),
        "apply_result": data.get("apply_result"),
        "candidate_count": len(data.get("candidates", [])),
        "draft_count": len(data.get("drafts", [])),
    }


@app.route("/api/baseline", methods=["POST"])
def api_baseline():
    from workflow import coverage_delta as coverage_delta_mod

    body = request.get_json(silent=True) or {}
    targets = _target_defaults(body)
    targets["tests_dir"].parent.mkdir(parents=True, exist_ok=True)
    try:
        result = coverage_delta_mod.run_coverage(
            targets["repo_root"], targets["source_pkg"], targets["coverage_json"]
        )
    except Exception as exc:  # pragma: no cover - defensive
        return _error_response(exc, 500)
    return jsonify(
        {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "coverage_json_path": str(targets["coverage_json"]),
        }
    )


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    body = request.get_json(silent=True) or {}
    targets = _target_defaults(body)

    if not targets["coverage_json"].exists():
        return _error_response(
            FileNotFoundError(
                f"Coverage report not found at {targets['coverage_json']}. Run Baseline first."
            )
        )

    initial_state: Dict[str, Any] = {
        "repo_root": str(targets["repo_root"]),
        "source_root": str(targets["source_root"]),
        "tests_dir": str(targets["tests_dir"]),
        "coverage_json_path": str(targets["coverage_json"]),
        "source_pkg": targets["source_pkg"],
        "reports_dir": str(REPORTS_DIR),
        "audit_log_path": str(audit_log.AUDIT_LOG_PATH),
        "lookback_days": int(body.get("lookback_days") or 180),
        "top_n": int(body.get("top_n") or 10),
        "weights": _weights_dict(),
    }
    try:
        state = pipeline.run_simple_analyze(initial_state)
    except Exception as exc:
        return _error_response(exc, 500)

    return jsonify({"candidates": state.get("candidates", []), "drafts": state.get("drafts", [])})


def _weights_dict() -> Dict[str, float]:
    import dataclasses

    return dataclasses.asdict(load_risk_weights())


@app.route("/api/drafts")
def api_drafts():
    status = request.args.get("status")
    drafts = review_queue.list_drafts(status=status)
    return jsonify([d.to_dict() for d in drafts])


@app.route("/api/drafts/<draft_id>/decision", methods=["POST"])
def api_draft_decision(draft_id: str):
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    reviewer = body.get("reviewer") or "web-ui"
    comment = body.get("comment") or None
    edited_code = body.get("edited_code") or None
    try:
        updated = review_queue.apply_decision(
            draft_id, decision, reviewer, comment=comment, edited_code=edited_code
        )
    except (ValueError, FileNotFoundError) as exc:
        return _error_response(exc, 400)
    except Exception as exc:
        return _error_response(exc, 500)
    return jsonify(updated.to_dict())


@app.route("/api/apply", methods=["POST"])
def api_apply():
    try:
        state = pipeline.run_simple_apply()
    except RuntimeError as exc:
        return _error_response(exc, 400)
    except Exception as exc:
        return _error_response(exc, 500)
    return jsonify(
        {
            "apply_result": state.get("apply_result", {}),
            "coverage_delta": state.get("coverage_delta", {}),
            "report_path": state.get("report_path"),
        }
    )


@app.route("/api/report")
def api_report():
    report_path = REPORTS_DIR / "latest_report.md"
    if not report_path.exists():
        return jsonify({"markdown": None})
    return jsonify({"markdown": report_path.read_text(encoding="utf-8")})


@app.route("/api/audit")
def api_audit():
    entries = audit_log.read_all()
    entries = list(reversed(entries))
    limit = int(request.args.get("limit", 50))
    return jsonify(entries[:limit])


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the risk agent's local web control panel.")
    parser.add_argument("--port", type=int, default=5151)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    ensure_data_dirs()
    print(f"Risk Agent Control Panel: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
