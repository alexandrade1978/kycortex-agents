import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import ConfigValidationError


def test_config_accepts_valid_provider_specific_call_budget(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        provider_max_calls_per_provider={"openai": 2},
    )

    assert config.provider_max_calls_per_provider == {"openai": 2}


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


def test_config_rejects_non_positive_ollama_num_ctx(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="ollama_num_ctx must be greater than zero when provided",
    ):
        KYCortexConfig(
            llm_provider="ollama",
            output_dir=str(tmp_path / "output"),
            ollama_num_ctx=0,
        )


def test_config_initialization_does_not_create_output_dir(tmp_path):
    output_dir = tmp_path / "output"

    config = KYCortexConfig(output_dir=str(output_dir))

    assert config.output_dir == str(output_dir)
    assert not output_dir.exists()


def test_config_rejects_invalid_timeout(tmp_path):
    with pytest.raises(ConfigValidationError, match="timeout_seconds must be greater than zero"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=0)


def test_config_rejects_non_positive_provider_timeout_override(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_timeout_seconds values must be greater than zero",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_timeout_seconds={"openai": 0.0},
        )


def test_config_rejects_unsupported_provider_timeout_override_key(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_timeout_seconds contains unsupported provider: custom",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_timeout_seconds={"custom": 15.0},
        )


def test_provider_runtime_config_uses_provider_specific_timeout_for_primary_and_fallback(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="openai",
        llm_model="gpt-4o",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        timeout_seconds=60.0,
        provider_timeout_seconds={"openai": 12.5, "anthropic": 30.0},
    )

    primary_runtime = config.provider_runtime_config("openai")
    fallback_runtime = config.provider_runtime_config("anthropic")

    assert primary_runtime.timeout_seconds == 12.5
    assert fallback_runtime.timeout_seconds == 30.0
    assert config.provider_timeout_seconds_for("openai") == 12.5
    assert config.provider_timeout_seconds_for("anthropic") == 30.0
    assert config.provider_timeout_seconds_for("ollama") == 60.0


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



def test_validate_runtime_accepts_supported_provider_with_explicit_api_key(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="openai",
        api_key="token",
    )

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


def test_config_rejects_negative_provider_health_check_cooldown(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_health_check_cooldown_seconds must be zero or greater",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_health_check_cooldown_seconds=-0.1,
        )


def test_config_rejects_invalid_provider_retry_jitter_ratio(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_retry_jitter_ratio must be between 0 and 1"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_retry_jitter_ratio=1.5)


def test_config_rejects_negative_provider_call_budget(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_max_calls_per_agent must be zero or greater"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_max_calls_per_agent=-1)


def test_config_rejects_negative_provider_specific_call_budget(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_max_calls_per_provider values must be zero or greater",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_max_calls_per_provider={"openai": -1},
        )


def test_config_rejects_unsupported_provider_specific_call_budget_key(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_max_calls_per_provider contains unsupported provider: custom",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_max_calls_per_provider={"custom": 1},
        )


def test_provider_runtime_config_returns_self_for_primary_provider_without_timeout_override(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="openai",
        api_key="token",
        timeout_seconds=22.0,
    )

    assert config.provider_runtime_config(" openai ") is config


def test_config_rejects_negative_provider_elapsed_budget(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_max_elapsed_seconds_per_call must be zero or greater"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_max_elapsed_seconds_per_call=-0.1)


def test_config_rejects_non_positive_provider_cancellation_check_interval(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_cancellation_check_interval_seconds must be greater than zero"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), provider_cancellation_check_interval_seconds=0.0)


def test_config_rejects_duplicate_provider_fallback_order_entries(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_fallback_order must not contain duplicates"):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_fallback_order=("anthropic", "anthropic"),
            provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        )


def test_config_rejects_unsupported_provider_in_fallback_order(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_fallback_order contains unsupported provider: custom",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_fallback_order=("custom",),
            provider_fallback_models={"custom": "custom-model"},
        )


def test_config_rejects_primary_provider_in_fallback_order(tmp_path):
    with pytest.raises(ConfigValidationError, match="provider_fallback_order must not include the primary llm_provider"):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            llm_provider="openai",
            provider_fallback_order=("openai",),
            provider_fallback_models={"openai": "gpt-4o"},
        )


def test_config_requires_explicit_models_for_all_fallback_providers(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_fallback_models must define a model for each fallback provider: anthropic",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_fallback_order=("anthropic",),
        )


def test_config_rejects_unsupported_provider_in_fallback_models(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_fallback_models contains unsupported provider: custom",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_fallback_models={"custom": "custom-model"},
        )


def test_config_rejects_fallback_model_key_missing_from_fallback_order(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_fallback_models keys must also appear in provider_fallback_order",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_fallback_order=("anthropic",),
            provider_fallback_models={"ollama": "llama3"},
        )


def test_config_rejects_empty_fallback_model_name(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="provider_fallback_models must define a non-empty model for provider: anthropic",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            provider_fallback_order=("anthropic",),
            provider_fallback_models={"anthropic": "   "},
        )


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


def test_config_rejects_invalid_execution_sandbox_wall_clock_limit(tmp_path):
    with pytest.raises(ConfigValidationError, match="execution_sandbox_max_wall_clock_seconds must be greater than zero"):
        KYCortexConfig(output_dir=str(tmp_path / "output"), execution_sandbox_max_wall_clock_seconds=0)


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
        execution_sandbox_max_wall_clock_seconds=18,
        execution_sandbox_max_memory_mb=256,
        execution_sandbox_temp_root=str(tmp_path),
    )

    policy = config.execution_sandbox_policy()

    assert policy.enabled is True
    assert policy.allow_network is False
    assert policy.allow_subprocesses is False
    assert policy.max_cpu_seconds == 12
    assert policy.max_wall_clock_seconds == 18
    assert policy.max_memory_mb == 256
    assert policy.temp_root == str(tmp_path)


def test_config_rejects_blank_execution_sandbox_temp_root(tmp_path):
    with pytest.raises(
        ConfigValidationError,
        match="execution_sandbox_temp_root must not be empty when provided",
    ):
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            execution_sandbox_temp_root="   ",
        )