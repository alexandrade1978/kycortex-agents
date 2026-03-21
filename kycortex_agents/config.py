import os
from dataclasses import dataclass
from typing import Optional

from kycortex_agents.exceptions import ConfigValidationError


PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

@dataclass
class KYCortexConfig:
    """Global configuration for KYCortex agent system."""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    api_key: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 4096
    project_name: str = "kycortex-project"
    output_dir: str = "./output"
    log_level: str = "INFO"

    def __post_init__(self):
        self.llm_provider = self.llm_provider.strip().lower()
        if self.api_key is None:
            self.api_key = self._resolve_api_key()
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

    def validate_runtime(self):
        env_var = PROVIDER_ENV_VARS.get(self.llm_provider)
        if env_var is None:
            raise ConfigValidationError(f"Unsupported provider in configuration: {self.llm_provider}")
        if not self.api_key:
            raise ConfigValidationError(
                f"Missing API key for provider '{self.llm_provider}'. Set {env_var} or pass api_key explicitly."
            )

DEFAULT_CONFIG = KYCortexConfig()
