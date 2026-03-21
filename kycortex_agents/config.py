import os
from dataclasses import dataclass
from typing import Optional

from kycortex_agents.exceptions import ConfigValidationError


PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama": None,
}

DEFAULT_PROVIDER_BASE_URLS = {
    "ollama": "http://localhost:11434",
}

@dataclass
class KYCortexConfig:
    """Global configuration for KYCortex agent system."""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout_seconds: float = 60.0
    workflow_failure_policy: str = "fail_fast"
    project_name: str = "kycortex-project"
    output_dir: str = "./output"
    log_level: str = "INFO"

    def __post_init__(self):
        self.llm_provider = self.llm_provider.strip().lower()
        if self.api_key is None:
            self.api_key = self._resolve_api_key()
        if self.base_url is None:
            self.base_url = DEFAULT_PROVIDER_BASE_URLS.get(self.llm_provider)
        self._validate_static_config()
        os.makedirs(self.output_dir, exist_ok=True)

    def _resolve_api_key(self) -> str:
        env_var = PROVIDER_ENV_VARS.get(self.llm_provider)
        if env_var is None:
            return ""
        return os.environ.get(env_var, "")

    def _validate_static_config(self):
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

    def validate_runtime(self):
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

DEFAULT_CONFIG = KYCortexConfig()
