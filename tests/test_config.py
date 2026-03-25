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


def test_config_sets_default_ollama_base_url(tmp_path):
    config = KYCortexConfig(
        llm_provider="ollama",
        output_dir=str(tmp_path / "output"),
    )

    assert config.base_url == "http://localhost:11434"


def test_config_rejects_invalid_timeout(tmp_path):
    with pytest.raises(ConfigValidationError, match="timeout_seconds must be greater than zero"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=0)


def test_config_rejects_invalid_temperature(tmp_path):
    with pytest.raises(ConfigValidationError, match="temperature must be between 0 and 2"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), temperature=2.5)


def test_config_rejects_invalid_max_tokens(tmp_path):
    with pytest.raises(ConfigValidationError, match="max_tokens must be greater than zero"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), max_tokens=0)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"llm_provider": "   "}, "llm_provider must not be empty"),
        ({"llm_model": "   "}, "llm_model must not be empty"),
        ({"project_name": "   "}, "project_name must not be empty"),
        ({"output_dir": "   "}, "output_dir must not be empty"),
        (
            {"base_url": "   ", "api_key": "token"},
            "base_url must not be empty when provided",
        ),
    ],
)
def test_config_rejects_blank_required_fields(tmp_path, overrides, message):
    with pytest.raises(ConfigValidationError, match=message):
        init_kwargs = {"output_dir": str(tmp_path / "output"), **overrides}
        KYCortexConfig(**init_kwargs)


def test_validate_runtime_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="")

    with pytest.raises(ConfigValidationError, match="Missing API key"):
        config.validate_runtime()


def test_validate_runtime_rejects_unsupported_provider(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="custom", api_key="token")

    with pytest.raises(ConfigValidationError, match="Unsupported provider in configuration"):
        config.validate_runtime()


def test_validate_runtime_accepts_ollama_without_api_key(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama")

    config.validate_runtime()


def test_config_rejects_invalid_workflow_resume_policy(tmp_path):
    with pytest.raises(ConfigValidationError, match="workflow_resume_policy must be 'interrupted_only' or 'resume_failed'"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), workflow_resume_policy="always")


def test_config_rejects_invalid_workflow_failure_policy(tmp_path):
    with pytest.raises(ConfigValidationError, match="workflow_failure_policy must be 'fail_fast' or 'continue'"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), workflow_failure_policy="retry_forever")


def test_config_rejects_invalid_workflow_acceptance_policy(tmp_path):
    with pytest.raises(ConfigValidationError, match="workflow_acceptance_policy must be 'all_tasks' or 'required_tasks'"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), workflow_acceptance_policy="optional_only")


def test_config_rejects_negative_workflow_max_repair_cycles(tmp_path):
    with pytest.raises(ConfigValidationError, match="workflow_max_repair_cycles must be zero or greater"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), workflow_max_repair_cycles=-1)


def test_config_rejects_invalid_provider_max_attempts(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_max_attempts must be greater than zero"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_max_attempts=0)


def test_config_rejects_negative_provider_retry_backoff(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_retry_backoff_seconds must be zero or greater"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_retry_backoff_seconds=-0.1)


def test_config_rejects_invalid_provider_retry_jitter_ratio(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_retry_jitter_ratio must be between 0 and 1"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_retry_jitter_ratio=1.5)


def test_config_rejects_negative_provider_call_budget(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_max_calls_per_agent must be zero or greater"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_max_calls_per_agent=-1)


def test_config_rejects_negative_provider_retry_max_backoff(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_retry_max_backoff_seconds must be zero or greater when provided"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_retry_max_backoff_seconds=-0.1)


def test_config_rejects_negative_provider_circuit_breaker_threshold(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_circuit_breaker_threshold must be zero or greater"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_circuit_breaker_threshold=-1)


def test_config_rejects_negative_provider_circuit_breaker_cooldown(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_circuit_breaker_cooldown_seconds must be zero or greater"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_circuit_breaker_cooldown_seconds=-0.1)


def test_config_rejects_non_positive_circuit_breaker_cooldown_when_threshold_enabled(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_circuit_breaker_cooldown_seconds must be greater than zero when provider_circuit_breaker_threshold is enabled",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_circuit_breaker_threshold=2,
            provider_circuit_breaker_cooldown_seconds=0.0,
        )


def test_validate_runtime_rejects_ollama_without_base_url(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama")
    config.base_url = ""

    with pytest.raises(ConfigValidationError, match="Missing base URL for provider 'ollama'"):
        config.validate_runtime()


def test_config_rejects_invalid_execution_sandbox_cpu_limit(tmp_path):
    with pytest.raises(ConfigValidationError, match="execution_sandbox_max_cpu_seconds must be greater than zero"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), execution_sandbox_max_cpu_seconds=0)


def test_config_rejects_invalid_execution_sandbox_memory_limit(tmp_path):
    with pytest.raises(ConfigValidationError, match="execution_sandbox_max_memory_mb must be greater than zero"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), execution_sandbox_max_memory_mb=0)


def test_config_builds_execution_sandbox_policy(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=True,
        execution_sandbox_allow_network=False,
        execution_sandbox_allow_subprocesses=False,
        execution_sandbox_max_cpu_seconds=12,
        execution_sandbox_max_memory_mb=256,
        execution_sandbox_temp_root=str(tmp_path),
    )

    policy = config.execution_sandbox_policy()

    assert policy.enabled is True
    assert policy.allow_network is False
    assert policy.allow_subprocesses is False
    assert policy.max_cpu_seconds == 12
    assert policy.max_memory_mb == 256
    assert policy.temp_root == str(tmp_path)