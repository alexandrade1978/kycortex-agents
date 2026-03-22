from __future__ import annotations

from typing import Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import ConfigValidationError, ProviderConfigurationError
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider

__all__ = ["create_provider"]


def create_provider(config: KYCortexConfig) -> BaseLLMProvider:
    provider_name = config.llm_provider.lower().strip()
    provider_map = {
        "anthropic": AnthropicProvider,
        "ollama": OllamaProvider,
        "openai": OpenAIProvider,
    }
    provider_class: Optional[type[BaseLLMProvider]] = provider_map.get(provider_name)
    if provider_class is None:
        raise ProviderConfigurationError(f"Unsupported LLM provider: {config.llm_provider}")
    try:
        config.validate_runtime()
    except ConfigValidationError as exc:
        raise ProviderConfigurationError(str(exc)) from exc
    return provider_class(config)