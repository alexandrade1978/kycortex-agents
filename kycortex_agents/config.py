"""Public runtime configuration model and provider environment-variable mappings."""

import os
from dataclasses import dataclass, field, replace
from typing import Optional

from kycortex_agents.exceptions import ConfigValidationError
from kycortex_agents.types import ExecutionSandboxPolicy


PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama": None,
}

DEFAULT_PROVIDER_BASE_URLS = {
    "ollama": "http://localhost:11434",
}

__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_PROVIDER_BASE_URLS",
    "KYCortexConfig",
    "PROVIDER_ENV_VARS",
]

@dataclass
class KYCortexConfig:
    """Public runtime configuration for providers, workflow behavior, and outputs."""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout_seconds: float = 60.0
    provider_timeout_seconds: dict[str, float] = field(default_factory=dict)
    workflow_failure_policy: str = "fail_fast"
    workflow_resume_policy: str = "interrupted_only"
    workflow_acceptance_policy: str = "all_tasks"
    workflow_max_repair_cycles: int = 1
    provider_max_attempts: int = 1
    provider_retry_backoff_seconds: float = 0.0
    provider_retry_max_backoff_seconds: Optional[float] = None
    provider_retry_jitter_ratio: float = 0.0
    provider_max_calls_per_agent: int = 0
    provider_max_calls_per_provider: dict[str, int] = field(default_factory=dict)
    provider_max_elapsed_seconds_per_call: float = 0.0
    provider_fallback_order: tuple[str, ...] = ()
    provider_fallback_models: dict[str, str] = field(default_factory=dict)
    provider_cancellation_check_interval_seconds: float = 0.1
    provider_circuit_breaker_threshold: int = 0
    provider_circuit_breaker_cooldown_seconds: float = 0.0
    execution_sandbox_enabled: bool = True
    execution_sandbox_allow_network: bool = False
    execution_sandbox_allow_subprocesses: bool = False
    execution_sandbox_max_cpu_seconds: float = 30.0
    execution_sandbox_max_memory_mb: int = 512
    execution_sandbox_temp_root: Optional[str] = None
    project_name: str = "kycortex-project"
    output_dir: str = "./output"
    log_level: str = "INFO"

    def __post_init__(self):
        """Normalize defaults, resolve provider settings, validate config, and create output storage."""

        self.llm_provider = self.llm_provider.strip().lower()
        self.provider_fallback_order = tuple(
            provider_name.strip().lower()
            for provider_name in self.provider_fallback_order
            if provider_name.strip()
        )
        self.provider_fallback_models = {
            provider_name.strip().lower(): model_name.strip()
            for provider_name, model_name in self.provider_fallback_models.items()
            if provider_name.strip()
        }
        self.provider_timeout_seconds = {
            provider_name.strip().lower(): timeout_seconds
            for provider_name, timeout_seconds in self.provider_timeout_seconds.items()
            if provider_name.strip()
        }
        self.provider_max_calls_per_provider = {
            provider_name.strip().lower(): max_calls
            for provider_name, max_calls in self.provider_max_calls_per_provider.items()
            if provider_name.strip()
        }
        if self.api_key is None:
            self.api_key = self._resolve_api_key()
        if self.base_url is None:
            self.base_url = DEFAULT_PROVIDER_BASE_URLS.get(self.llm_provider)
        self._validate_static_config()
        os.makedirs(self.output_dir, exist_ok=True)

    def _resolve_api_key(self) -> str:
        """Resolve the configured provider API key from the matching environment variable."""

        env_var = PROVIDER_ENV_VARS.get(self.llm_provider)
        if env_var is None:
            return ""
        return os.environ.get(env_var, "")

    def _validate_static_config(self):
        """Validate static configuration values that do not require provider instantiation."""

        if not self.llm_provider:
            raise ConfigValidationError("llm_provider must not be empty")
        if not self.llm_model.strip():
            raise ConfigValidationError("llm_model must not be empty")
        if not self.project_name.strip():
            raise ConfigValidationError("project_name must not be empty")
        if not self.output_dir.strip():
            raise ConfigValidationError("output_dir must not be empty")
        if not 0 <= self.temperature <= 2:
            raise ConfigValidationError("temperature must be between 0 and 2")
        if self.max_tokens <= 0:
            raise ConfigValidationError("max_tokens must be greater than zero")
        if self.timeout_seconds <= 0:
            raise ConfigValidationError("timeout_seconds must be greater than zero")
        for provider_name, timeout_seconds in self.provider_timeout_seconds.items():
            if provider_name not in PROVIDER_ENV_VARS:
                raise ConfigValidationError(
                    f"provider_timeout_seconds contains unsupported provider: {provider_name}"
                )
            if timeout_seconds <= 0:
                raise ConfigValidationError(
                    "provider_timeout_seconds values must be greater than zero"
                )
        if self.base_url is not None and not self.base_url.strip():
            raise ConfigValidationError("base_url must not be empty when provided")
        if self.workflow_failure_policy not in {"fail_fast", "continue"}:
            raise ConfigValidationError("workflow_failure_policy must be 'fail_fast' or 'continue'")
        if self.workflow_resume_policy not in {"interrupted_only", "resume_failed"}:
            raise ConfigValidationError(
                "workflow_resume_policy must be 'interrupted_only' or 'resume_failed'"
            )
        if self.workflow_acceptance_policy not in {"all_tasks", "required_tasks"}:
            raise ConfigValidationError(
                "workflow_acceptance_policy must be 'all_tasks' or 'required_tasks'"
            )
        if self.workflow_max_repair_cycles < 0:
            raise ConfigValidationError("workflow_max_repair_cycles must be zero or greater")
        if self.provider_max_attempts <= 0:
            raise ConfigValidationError("provider_max_attempts must be greater than zero")
        if self.provider_retry_backoff_seconds < 0:
            raise ConfigValidationError("provider_retry_backoff_seconds must be zero or greater")
        if (
            self.provider_retry_max_backoff_seconds is not None
            and self.provider_retry_max_backoff_seconds < 0
        ):
            raise ConfigValidationError("provider_retry_max_backoff_seconds must be zero or greater when provided")
        if not 0 <= self.provider_retry_jitter_ratio <= 1:
            raise ConfigValidationError("provider_retry_jitter_ratio must be between 0 and 1")
        if self.provider_max_calls_per_agent < 0:
            raise ConfigValidationError("provider_max_calls_per_agent must be zero or greater")
        for provider_name, max_calls in self.provider_max_calls_per_provider.items():
            if provider_name not in PROVIDER_ENV_VARS:
                raise ConfigValidationError(
                    f"provider_max_calls_per_provider contains unsupported provider: {provider_name}"
                )
            if max_calls < 0:
                raise ConfigValidationError(
                    "provider_max_calls_per_provider values must be zero or greater"
                )
        if self.provider_max_elapsed_seconds_per_call < 0:
            raise ConfigValidationError("provider_max_elapsed_seconds_per_call must be zero or greater")
        if self.provider_cancellation_check_interval_seconds <= 0:
            raise ConfigValidationError(
                "provider_cancellation_check_interval_seconds must be greater than zero"
            )
        if len(set(self.provider_fallback_order)) != len(self.provider_fallback_order):
            raise ConfigValidationError("provider_fallback_order must not contain duplicates")
        for provider_name in self.provider_fallback_order:
            if provider_name not in PROVIDER_ENV_VARS:
                raise ConfigValidationError(
                    f"provider_fallback_order contains unsupported provider: {provider_name}"
                )
            if provider_name == self.llm_provider:
                raise ConfigValidationError(
                    "provider_fallback_order must not include the primary llm_provider"
                )
        for provider_name, model_name in self.provider_fallback_models.items():
            if provider_name not in PROVIDER_ENV_VARS:
                raise ConfigValidationError(
                    f"provider_fallback_models contains unsupported provider: {provider_name}"
                )
            if provider_name not in self.provider_fallback_order:
                raise ConfigValidationError(
                    "provider_fallback_models keys must also appear in provider_fallback_order"
                )
            if not model_name:
                raise ConfigValidationError(
                    f"provider_fallback_models must define a non-empty model for provider: {provider_name}"
                )
        missing_fallback_models = [
            provider_name
            for provider_name in self.provider_fallback_order
            if provider_name not in self.provider_fallback_models
        ]
        if missing_fallback_models:
            missing_list = ", ".join(missing_fallback_models)
            raise ConfigValidationError(
                f"provider_fallback_models must define a model for each fallback provider: {missing_list}"
            )
        if self.provider_circuit_breaker_threshold < 0:
            raise ConfigValidationError("provider_circuit_breaker_threshold must be zero or greater")
        if self.provider_circuit_breaker_cooldown_seconds < 0:
            raise ConfigValidationError("provider_circuit_breaker_cooldown_seconds must be zero or greater")
        if (
            self.provider_circuit_breaker_threshold > 0
            and self.provider_circuit_breaker_cooldown_seconds <= 0
        ):
            raise ConfigValidationError(
                "provider_circuit_breaker_cooldown_seconds must be greater than zero when provider_circuit_breaker_threshold is enabled"
            )
        if self.execution_sandbox_max_cpu_seconds <= 0:
            raise ConfigValidationError("execution_sandbox_max_cpu_seconds must be greater than zero")
        if self.execution_sandbox_max_memory_mb <= 0:
            raise ConfigValidationError("execution_sandbox_max_memory_mb must be greater than zero")
        if (
            self.execution_sandbox_temp_root is not None
            and not self.execution_sandbox_temp_root.strip()
        ):
            raise ConfigValidationError("execution_sandbox_temp_root must not be empty when provided")

    def validate_runtime(self):
        """Validate provider-specific runtime requirements such as credentials and base URLs."""

        if self.llm_provider not in PROVIDER_ENV_VARS:
            raise ConfigValidationError(f"Unsupported provider in configuration: {self.llm_provider}")
        env_var = PROVIDER_ENV_VARS[self.llm_provider]
        if env_var is None:
            if not self.base_url:
                raise ConfigValidationError(
                    f"Missing base URL for provider '{self.llm_provider}'. Pass base_url explicitly or rely on a provider default."
                )
            return
        if not self.api_key:
            raise ConfigValidationError(
                f"Missing API key for provider '{self.llm_provider}'. Set {env_var} or pass api_key explicitly."
            )

    def execution_sandbox_policy(self) -> ExecutionSandboxPolicy:
        """Return the normalized sandbox policy for generated-artifact execution."""

        return ExecutionSandboxPolicy(
            enabled=self.execution_sandbox_enabled,
            allow_network=self.execution_sandbox_allow_network,
            allow_subprocesses=self.execution_sandbox_allow_subprocesses,
            max_cpu_seconds=self.execution_sandbox_max_cpu_seconds,
            max_memory_mb=self.execution_sandbox_max_memory_mb,
            temp_root=self.execution_sandbox_temp_root,
            disable_pytest_plugin_autoload=True,
        )

    def provider_timeout_seconds_for(self, provider_name: str) -> float:
        """Return the resolved request timeout for a provider, including per-provider overrides."""

        normalized_provider_name = provider_name.strip().lower()
        return self.provider_timeout_seconds.get(normalized_provider_name, self.timeout_seconds)

    def provider_runtime_config(self, provider_name: str) -> "KYCortexConfig":
        """Return a provider-specific runtime config derived from the current policy surface."""

        normalized_provider_name = provider_name.strip().lower()
        provider_timeout_seconds = self.provider_timeout_seconds_for(normalized_provider_name)
        if normalized_provider_name == self.llm_provider and provider_timeout_seconds == self.timeout_seconds:
            return self
        return replace(
            self,
            llm_provider=normalized_provider_name,
            llm_model=(
                self.llm_model
                if normalized_provider_name == self.llm_provider
                else self.provider_fallback_models[normalized_provider_name]
            ),
            api_key=(self.api_key if normalized_provider_name == self.llm_provider else None),
            base_url=(self.base_url if normalized_provider_name == self.llm_provider else None),
            timeout_seconds=provider_timeout_seconds,
            provider_fallback_order=(),
            provider_fallback_models={},
        )

DEFAULT_CONFIG = KYCortexConfig()
