import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import ConfigValidationError


def test_config_normalizes_provider_and_reads_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-token")

    config = KYCortexConfig(
        llm_provider=" OpenAI ",
        output_dir=str(tmp_path / "output"),
    )

    assert config.llm_provider == "openai"
    assert config.api_key == "env-token"


def test_config_reads_anthropic_env_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-token")

    config = KYCortexConfig(
        llm_provider="anthropic",
        output_dir=str(tmp_path / "output"),
    )

    assert config.llm_provider == "anthropic"
    assert config.api_key == "anthropic-token"


def test_config_rejects_invalid_temperature(tmp_path):
    with pytest.raises(ConfigValidationError, match="temperature must be between 0 and 2"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), temperature=2.5)


def test_config_rejects_invalid_max_tokens(tmp_path):
    with pytest.raises(ConfigValidationError, match="max_tokens must be greater than zero"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), max_tokens=0)


def test_validate_runtime_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="")

    with pytest.raises(ConfigValidationError, match="Missing API key"):
        config.validate_runtime()


def test_validate_runtime_rejects_unsupported_provider(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="custom", api_key="token")

    with pytest.raises(ConfigValidationError, match="Unsupported provider in configuration"):
        config.validate_runtime()