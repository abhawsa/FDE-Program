"""Append-only audit trail linking every generated test back to its risk score
and every human decision to its reviewer.

Anti-pattern this directly addresses: "No audit trail linking a test to its
risk score" - every record below carries risk_score + risk_components.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import AUDIT_LOG_PATH, PROJECT_ROOT, ensure_data_dirs

# Pretty-printed JSON-array snapshot of the log, suitable for inclusion in a
# submission ZIP or for a reviewer to skim without a JSONL-aware tool. The
# append-only AUDIT_LOG_PATH (JSONL) remains the source of truth at runtime;
# this is a point-in-time export of it.
GENERATION_AUDIT_LOG_JSON_PATH = PROJECT_ROOT / "audit" / "generation_audit_log.json"


def record(event_type: str, payload: Dict[str, Any]) -> None:
    ensure_data_dirs()
    entry = {"timestamp": time.time(), "event": event_type, **payload}
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")


def read_all() -> List[dict]:
    if not AUDIT_LOG_PATH.exists():
        return []
    entries = []
    for line in AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def export_json_array(out_path: Optional[Path] = None) -> Path:
    """Writes the full audit trail as a pretty-printed JSON array.

    Called after `apply` so `audit/generation_audit_log.json` always
    reflects the latest run - every draft linked to its risk score, and
    every review decision linked to its reviewer.
    """
    out_path = out_path or GENERATION_AUDIT_LOG_JSON_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(read_all(), indent=2, default=str), encoding="utf-8")
    return out_path
