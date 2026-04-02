"""Public provider-factory helpers for resolving built-in LLM backends."""

from __future__ import annotations

import hashlib
from time import perf_counter
from typing import Any, Callable, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import (
    AgentExecutionError,
    ConfigValidationError,
    ProviderConfigurationError,
    ProviderTransientError,
)
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.base import BaseLLMProvider, redact_sensitive_data
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider

__all__ = ["create_provider", "probe_provider_health"]


_HEALTH_PROBE_CACHE: dict[tuple[str, str, str, float, str], dict[str, Any]] = {}


def _health_probe_cache_identity(config: KYCortexConfig) -> str:
    credential = config.api_key or ""
    if not credential:
        return ""
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


def _health_probe_cache_key(config: KYCortexConfig) -> tuple[str, str, str, float, str]:
    return (
        config.llm_provider,
        config.llm_model,
        config.base_url or "",
        round(config.timeout_seconds, 6),
        _health_probe_cache_identity(config),
    )


def _health_probe_cooldown_seconds(config: KYCortexConfig) -> float:
    if config.provider_health_check_cooldown_seconds > 0:
        return config.provider_health_check_cooldown_seconds
    if config.provider_circuit_breaker_cooldown_seconds > 0:
        return config.provider_circuit_breaker_cooldown_seconds
    return 0.0


def _build_cached_health_snapshot(entry: dict[str, Any], remaining_seconds: float) -> dict[str, object]:
    snapshot = redact_sensitive_data(dict(entry["snapshot"]))
    snapshot["checked_at"] = float(entry["checked_at"])
    snapshot["cooldown_cached"] = True
    snapshot["cooldown_remaining_seconds"] = round(remaining_seconds, 6)
    return snapshot


def _maybe_get_cached_health_snapshot(
    config: KYCortexConfig,
    current_time: float,
) -> Optional[dict[str, object]]:
    cooldown_seconds = _health_probe_cooldown_seconds(config)
    if cooldown_seconds <= 0:
        return None
    cache_key = _health_probe_cache_key(config)
    entry = _HEALTH_PROBE_CACHE.get(cache_key)
    if entry is None:
        return None
    remaining_seconds = max(float(entry["checked_at"]) + cooldown_seconds - current_time, 0.0)
    if remaining_seconds <= 0:
        _HEALTH_PROBE_CACHE.pop(cache_key, None)
        return None
    return _build_cached_health_snapshot(entry, remaining_seconds)


def _store_health_snapshot(config: KYCortexConfig, snapshot: dict[str, object], checked_at: float) -> None:
    cache_key = _health_probe_cache_key(config)
    if snapshot.get("status") not in {"degraded", "failing"}:
        _HEALTH_PROBE_CACHE.pop(cache_key, None)
        return
    sanitized_snapshot = redact_sensitive_data(snapshot)
    _HEALTH_PROBE_CACHE[cache_key] = {
        "checked_at": checked_at,
        "snapshot": {
            key: value
            for key, value in sanitized_snapshot.items()
            if key not in {"cooldown_cached", "cooldown_remaining_seconds"}
        },
    }


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

    started_at = perf_counter()
    cached_snapshot = _maybe_get_cached_health_snapshot(config, started_at)
    if cached_snapshot is not None:
        return cached_snapshot

    provider = create_provider(config)
    try:
        snapshot = dict(provider.health_check())
    except ProviderTransientError as exc:
        completed_at = perf_counter()
        snapshot = {
            "provider": config.llm_provider,
            "model": config.llm_model,
            "status": "degraded",
            "active_check": True,
            "retryable": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "latency_ms": round((completed_at - started_at) * 1000, 3),
            "cooldown_cached": False,
            "cooldown_remaining_seconds": 0.0,
        }
        snapshot = redact_sensitive_data(snapshot)
        _store_health_snapshot(config, snapshot, completed_at)
        return snapshot
    except AgentExecutionError as exc:
        completed_at = perf_counter()
        snapshot = {
            "provider": config.llm_provider,
            "model": config.llm_model,
            "status": "failing",
            "active_check": True,
            "retryable": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "latency_ms": round((completed_at - started_at) * 1000, 3),
            "cooldown_cached": False,
            "cooldown_remaining_seconds": 0.0,
        }
        snapshot = redact_sensitive_data(snapshot)
        _store_health_snapshot(config, snapshot, completed_at)
        return snapshot
    completed_at = perf_counter()
    if snapshot.get("provider") is None:
        snapshot["provider"] = config.llm_provider
    if snapshot.get("model") is None:
        snapshot["model"] = config.llm_model
    if snapshot.get("status") is None:
        snapshot["status"] = "ready"
    if snapshot.get("active_check") is None:
        snapshot["active_check"] = False
    snapshot["retryable"] = False
    snapshot["latency_ms"] = round((completed_at - started_at) * 1000, 3)
    snapshot["cooldown_cached"] = False
    snapshot["cooldown_remaining_seconds"] = 0.0
    snapshot = redact_sensitive_data(snapshot)
    _store_health_snapshot(config, snapshot, completed_at)
    return snapshot