from __future__ import annotations

from typing import Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import ProviderConfigurationError
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider


def create_provider(config: KYCortexConfig) -> BaseLLMProvider:
    provider_name = config.llm_provider.lower().strip()
    provider_map = {
        "openai": OpenAIProvider,
    }
    provider_class: Optional[type[BaseLLMProvider]] = provider_map.get(provider_name)
    if provider_class is None:
        raise ProviderConfigurationError(f"Unsupported LLM provider: {config.llm_provider}")
    return provider_class(config)