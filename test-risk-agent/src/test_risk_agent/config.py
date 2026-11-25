"""Paths, .env loading, and tunable settings for the agent.

Deliberately stdlib + PyYAML only - nothing here requires langgraph,
anthropic, or langfuse to be installed, so `config` can always be imported.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# test-risk-agent/src/test_risk_agent/config.py -> parents[2] == test-risk-agent/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
REVIEW_QUEUE_DIR = DATA_DIR / "review_queue"
REPORTS_DIR = DATA_DIR / "reports"
AUDIT_LOG_PATH = DATA_DIR / "audit_log.jsonl"
CHECKPOINT_DB_PATH = DATA_DIR / "graph_checkpoints.sqlite"
DEFAULT_RISK_WEIGHTS_PATH = PROJECT_ROOT / "config" / "risk_weights.yaml"


def ensure_data_dirs() -> None:
    for d in (DATA_DIR, REVIEW_QUEUE_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _load_dotenv(path: Path) -> None:
    """Minimal KEY=VALUE .env loader - avoids a python-dotenv dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class RiskWeights:
    change_frequency: float = 0.4
    complexity: float = 0.3
    coverage_gap: float = 0.3

    def normalized(self) -> "RiskWeights":
        total = self.change_frequency + self.complexity + self.coverage_gap
        if total <= 0:
            return RiskWeights(1 / 3, 1 / 3, 1 / 3)
        return RiskWeights(
            self.change_frequency / total,
            self.complexity / total,
            self.coverage_gap / total,
        )


def load_risk_weights(path: Optional[Path] = None) -> RiskWeights:
    path = path or DEFAULT_RISK_WEIGHTS_PATH
    if not path.exists():
        return RiskWeights().normalized()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    weights = data.get("weights", {}) or {}
    return RiskWeights(
        change_frequency=float(weights.get("change_frequency", 0.4)),
        complexity=float(weights.get("complexity", 0.3)),
        coverage_gap=float(weights.get("coverage_gap", 0.3)),
    ).normalized()


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-5"
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: str = "https://cloud.langfuse.com"
    lookback_days: int = 180
    top_n: int = 10

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
            langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY") or None,
            langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY") or None,
            langfuse_host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            lookback_days=int(os.environ.get("RISK_LOOKBACK_DAYS", "180")),
            top_n=int(os.environ.get("RISK_TOP_N", "10")),
        )
