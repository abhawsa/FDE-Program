"""Append-only audit trail linking every generated test back to its risk score
and every human decision to its reviewer.

Anti-pattern this directly addresses: "No audit trail linking a test to its
risk score" - every record below carries risk_score + risk_components.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from .config import AUDIT_LOG_PATH, ensure_data_dirs


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
