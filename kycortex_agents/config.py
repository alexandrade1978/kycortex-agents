"""Public runtime configuration model and provider environment-variable mappings."""

import os
from dataclasses import dataclass
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
    workflow_failure_policy: str = "fail_fast"
    workflow_resume_policy: str = "interrupted_only"
    workflow_acceptance_policy: str = "all_tasks"
    workflow_max_repair_cycles: int = 1
    provider_max_attempts: int = 1
    provider_retry_backoff_seconds: float = 0.0
    provider_retry_jitter_ratio: float = 0.0
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
        if not 0 <= self.provider_retry_jitter_ratio <= 1:
            raise ConfigValidationError("provider_retry_jitter_ratio must be between 0 and 1")
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

DEFAULT_CONFIG = KYCortexConfig()
