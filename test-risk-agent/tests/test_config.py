from pathlib import Path

from test_risk_agent.config import RiskWeights, Settings, load_risk_weights


def test_risk_weights_normalized_sums_to_one():
    weights = RiskWeights(change_frequency=2, complexity=1, coverage_gap=1).normalized()
    total = weights.change_frequency + weights.complexity + weights.coverage_gap
    assert abs(total - 1.0) < 1e-9
    assert weights.change_frequency == 0.5


def test_risk_weights_normalized_handles_all_zero():
    weights = RiskWeights(change_frequency=0, complexity=0, coverage_gap=0).normalized()
    assert weights.change_frequency == weights.complexity == weights.coverage_gap


def test_load_risk_weights_from_yaml_file(tmp_path: Path):
    path = tmp_path / "weights.yaml"
    path.write_text("weights:\n  change_frequency: 5\n  complexity: 3\n  coverage_gap: 2\n", encoding="utf-8")

    weights = load_risk_weights(path)

    assert abs(weights.change_frequency - 0.5) < 1e-9
    assert abs(weights.complexity - 0.3) < 1e-9
    assert abs(weights.coverage_gap - 0.2) < 1e-9


def test_load_risk_weights_missing_file_returns_default(tmp_path: Path):
    weights = load_risk_weights(tmp_path / "does_not_exist.yaml")
    total = weights.change_frequency + weights.complexity + weights.coverage_gap
    assert abs(total - 1.0) < 1e-9


def test_settings_from_env_defaults(monkeypatch):
    for key in (
        "ANTHROPIC_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "RISK_LOOKBACK_DAYS",
        "RISK_TOP_N",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env()

    assert settings.anthropic_api_key is None
    assert settings.langfuse_public_key is None
    assert settings.lookback_days == 180
    assert settings.top_n == 10
