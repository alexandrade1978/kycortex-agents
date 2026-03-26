"""Public provider-factory helpers for resolving built-in LLM backends."""

from __future__ import annotations

from time import perf_counter
from typing import Callable, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import (
    AgentExecutionError,
    ConfigValidationError,
    ProviderConfigurationError,
    ProviderTransientError,
)
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider

__all__ = ["create_provider", "probe_provider_health"]


def create_provider(config: KYCortexConfig) -> BaseLLMProvider:
    """Instantiate the built-in provider configured by the supplied runtime settings."""

    provider_name = config.llm_provider.lower().strip()
    provider_map = {
        "anthropic": AnthropicProvider,
        "ollama": OllamaProvider,
        "openai": OpenAIProvider,
    }
    provider_class: Optional[Callable[[KYCortexConfig], BaseLLMProvider]] = provider_map.get(provider_name)
    if provider_class is None:
        raise ProviderConfigurationError(f"Unsupported LLM provider: {config.llm_provider}")
    try:
        config.validate_runtime()
    except ConfigValidationError as exc:
        raise ProviderConfigurationError(str(exc)) from exc
    return provider_class(config)


def probe_provider_health(config: KYCortexConfig) -> dict[str, object]:
    """Instantiate the built-in provider and return a structured health snapshot."""

    provider = create_provider(config)
    started_at = perf_counter()
    try:
        snapshot = dict(provider.health_check())
    except ProviderTransientError as exc:
        completed_at = perf_counter()
        return {
            "provider": config.llm_provider,
            "model": config.llm_model,
            "status": "degraded",
            "active_check": True,
            "retryable": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "latency_ms": round((completed_at - started_at) * 1000, 3),
        }
    except AgentExecutionError as exc:
        completed_at = perf_counter()
        return {
            "provider": config.llm_provider,
            "model": config.llm_model,
            "status": "failing",
            "active_check": True,
            "retryable": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "latency_ms": round((completed_at - started_at) * 1000, 3),
        }
    completed_at = perf_counter()
    snapshot.setdefault("provider", config.llm_provider)
    snapshot.setdefault("model", config.llm_model)
    snapshot.setdefault("status", "ready")
    snapshot.setdefault("active_check", False)
    snapshot["retryable"] = False
    snapshot["latency_ms"] = round((completed_at - started_at) * 1000, 3)
    return snapshot