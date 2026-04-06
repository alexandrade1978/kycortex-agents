from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from copy import deepcopy
import random
import re
from time import perf_counter, sleep
from typing import Any, Optional, cast

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers.base import (
    BaseLLMProvider,
    redact_sensitive_data,
    redact_sensitive_text,
    sanitize_prompt_input,
    sanitize_provider_call_metadata,
)
from kycortex_agents.providers.factory import (
    _maybe_get_cached_health_snapshot,
    _store_health_snapshot,
    create_provider,
)
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactRecord, ArtifactType, DecisionRecord


class BaseAgent(ABC):
    """Base class for public agent extensions.

    Subclasses typically implement `run()` or `run_with_input()` and may override
    lifecycle hooks to add validation, output shaping, or error handling.
    """

    """Context keys that must be present before execution starts."""
    required_context_keys: tuple[str, ...] = ()
    output_artifact_type: ArtifactType = ArtifactType.TEXT
    output_artifact_name: str = "output"

    def __init__(self, name: str, role: str, config: KYCortexConfig):
        self.name = name
        self.role = role
        self.config = config
        self._provider: Optional[BaseLLMProvider] = None
        self._provider_cache: dict[tuple[str, str], BaseLLMProvider] = {}
        self._last_provider_call_metadata: Optional[dict[str, Any]] = None
        self._provider_call_count = 0
        self._provider_call_counts: dict[str, int] = {}
        self._provider_transient_failure_streaks: dict[str, int] = {}
        self._provider_circuit_open_untils: dict[str, float] = {}
        self._provider_last_outcomes: dict[str, str] = {}
        self._provider_last_failure_at: dict[str, float] = {}
        self._provider_last_success_at: dict[str, float] = {}
        self._provider_last_error_types: dict[str, str] = {}
        self._provider_last_error_messages: dict[str, str] = {}
        self._provider_last_retryable_failures: dict[str, bool] = {}
        self._provider_last_health_checks: dict[str, dict[str, Any]] = {}
        self._provider_cancellation_requested = False
        self._provider_cancellation_reason: Optional[str] = None
        self._last_unredacted_output: Optional[AgentOutput] = None

    def _get_provider(self) -> BaseLLMProvider:
        return self._get_provider_for(self.config.llm_provider, self.config.llm_model)

    def _get_provider_for(self, provider_name: str, model_name: str) -> BaseLLMProvider:
        provider_key = (provider_name, model_name)
        runtime_config = self.config.provider_runtime_config(provider_name)
        if provider_name == self.config.llm_provider and model_name == self.config.llm_model:
            if self._provider is not None:
                self._provider_cache[provider_key] = self._provider
                return self._provider
            if provider_key in self._provider_cache:
                self._provider = self._provider_cache[provider_key]
                return self._provider
            self._provider = create_provider(runtime_config)
            self._provider_cache[provider_key] = self._provider
            return self._provider
        cached_provider = self._provider_cache.get(provider_key)
        if cached_provider is not None:
            return cached_provider
        provider = create_provider(runtime_config)
        self._provider_cache[provider_key] = provider
        return provider

    def chat(self, system_prompt: str, user_message: str) -> str:
        started_at = perf_counter()
        sanitized_system_prompt = sanitize_prompt_input(system_prompt)
        sanitized_user_message = sanitize_prompt_input(user_message)
        provider_plan = self._provider_execution_plan()
        max_attempts = self.config.provider_max_attempts
        attempt_history: list[dict[str, Any]] = []
        fallback_history: list[dict[str, Any]] = []
        for provider_index, (provider_name, model_name) in enumerate(provider_plan):
            provider = self._get_provider_for(provider_name, model_name)
            current_time = perf_counter()
            self._raise_if_provider_cancellation_requested(
                provider_name,
                model_name,
                started_at,
                current_time,
                attempt_history,
                max_attempts,
                fallback_history,
            )
            if self._is_provider_circuit_open(provider_name, current_time):
                remaining_seconds = round(
                    max(self._provider_circuit_open_untils.get(provider_name, 0.0) - current_time, 0.0),
                    6,
                )
                if provider_index < len(provider_plan) - 1:
                    fallback_history.append(
                        {
                            "provider": provider_name,
                            "status": "skipped_open_circuit",
                            "remaining_cooldown_seconds": remaining_seconds,
                        }
                    )
                    continue
                message = f"{self.name}: provider circuit breaker is open for {remaining_seconds:g} more seconds"
                self._last_provider_call_metadata = {
                    "provider": provider_name,
                    "model": model_name,
                    "success": False,
                    "duration_ms": round((current_time - started_at) * 1000, 3),
                    "error_type": "AgentExecutionError",
                    "error_message": message.removeprefix(f"{self.name}: "),
                    "retryable": False,
                    "attempts_used": len(attempt_history),
                    "max_attempts": max_attempts,
                    "attempt_history": list(attempt_history),
                    **self._provider_call_budget_metadata(),
                    **self._provider_timeout_metadata(provider_name, provider_plan),
                    **self._provider_elapsed_budget_metadata(started_at, current_time),
                    **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                    **self._provider_cancellation_metadata(),
                    **self._provider_circuit_metadata(provider_name, current_time),
                    **self._provider_health_metadata(current_time, provider_plan),
                }
                raise AgentExecutionError(message)
            if self._is_provider_specific_call_budget_exhausted(provider_name):
                if provider_index < len(provider_plan) - 1:
                    fallback_history.append(
                        {
                            "provider": provider_name,
                            "status": "skipped_call_budget_exhausted",
                        }
                    )
                    continue
                message = f"{self.name}: provider call budget exhausted for {provider_name}"
                self._last_provider_call_metadata = {
                    "provider": provider_name,
                    "model": model_name,
                    "success": False,
                    "duration_ms": round((current_time - started_at) * 1000, 3),
                    "error_type": "AgentExecutionError",
                    "error_message": message.removeprefix(f"{self.name}: "),
                    "retryable": False,
                    "attempts_used": len(attempt_history),
                    "max_attempts": max_attempts,
                    "attempt_history": list(attempt_history),
                    **self._provider_call_budget_metadata(),
                    **self._provider_timeout_metadata(provider_name, provider_plan),
                    **self._provider_elapsed_budget_metadata(started_at, current_time),
                    **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                    **self._provider_cancellation_metadata(),
                    **self._provider_circuit_metadata(provider_name, current_time),
                    **self._provider_health_metadata(current_time, provider_plan),
                }
                raise AgentExecutionError(message)
            try:
                self._probe_provider_health(provider_name, model_name, provider)
            except (ProviderTransientError, AgentExecutionError) as exc:
                current_time = perf_counter()
                if provider_index < len(provider_plan) - 1:
                    fallback_history.append(
                        {
                            "provider": provider_name,
                            "status": "failed_health_check",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "retryable": isinstance(exc, ProviderTransientError),
                        }
                    )
                    continue
                self._last_provider_call_metadata = {
                    "provider": provider_name,
                    "model": model_name,
                    "success": False,
                    "duration_ms": round((current_time - started_at) * 1000, 3),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "retryable": isinstance(exc, ProviderTransientError),
                    "attempts_used": len(attempt_history),
                    "max_attempts": max_attempts,
                    "attempt_history": list(attempt_history),
                    **self._provider_call_budget_metadata(),
                    **self._provider_timeout_metadata(provider_name, provider_plan),
                    **self._provider_elapsed_budget_metadata(started_at, current_time),
                    **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                    **self._provider_cancellation_metadata(),
                    **self._provider_circuit_metadata(provider_name, current_time),
                    **self._provider_health_metadata(current_time, provider_plan),
                }
                raise self._prefix_agent_execution_error(exc) from exc
            for attempt in range(1, max_attempts + 1):
                current_time = perf_counter()
                self._raise_if_provider_cancellation_requested(
                    provider_name,
                    model_name,
                    started_at,
                    current_time,
                    attempt_history,
                    max_attempts,
                    fallback_history,
                )
                if self._is_provider_elapsed_budget_exhausted(started_at, current_time):
                    message = (
                        f"{self.name}: provider elapsed budget exhausted after "
                        f"{current_time - started_at:g} seconds"
                    )
                    self._last_provider_call_metadata = {
                        "provider": provider_name,
                        "model": model_name,
                        "success": False,
                        "duration_ms": round((current_time - started_at) * 1000, 3),
                        "error_type": "AgentExecutionError",
                        "error_message": message.removeprefix(f"{self.name}: "),
                        "retryable": False,
                        "attempts_used": len(attempt_history),
                        "max_attempts": max_attempts,
                        "attempt_history": list(attempt_history),
                        **self._provider_call_budget_metadata(),
                        **self._provider_timeout_metadata(provider_name, provider_plan),
                        **self._provider_elapsed_budget_metadata(started_at, current_time),
                        **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                        **self._provider_cancellation_metadata(),
                        **self._provider_circuit_metadata(provider_name, current_time),
                        **self._provider_health_metadata(current_time, provider_plan),
                    }
                    raise AgentExecutionError(message)
                if self._is_provider_call_budget_exhausted():
                    message = f"{self.name}: provider call budget exhausted"
                    self._last_provider_call_metadata = {
                        "provider": provider_name,
                        "model": model_name,
                        "success": False,
                        "duration_ms": round((current_time - started_at) * 1000, 3),
                        "error_type": "AgentExecutionError",
                        "error_message": message.removeprefix(f"{self.name}: "),
                        "retryable": False,
                        "attempts_used": len(attempt_history),
                        "max_attempts": max_attempts,
                        "attempt_history": list(attempt_history),
                        **self._provider_call_budget_metadata(),
                        **self._provider_timeout_metadata(provider_name, provider_plan),
                        **self._provider_elapsed_budget_metadata(started_at, current_time),
                        **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                        **self._provider_cancellation_metadata(),
                        **self._provider_circuit_metadata(provider_name, current_time),
                        **self._provider_health_metadata(current_time, provider_plan),
                    }
                    raise AgentExecutionError(message)
                if self._is_provider_specific_call_budget_exhausted(provider_name):
                    if provider_index < len(provider_plan) - 1:
                        fallback_history.append(
                            {
                                "provider": provider_name,
                                "status": "failed_call_budget_exhausted",
                            }
                        )
                        break
                    message = f"{self.name}: provider call budget exhausted for {provider_name}"
                    self._last_provider_call_metadata = {
                        "provider": provider_name,
                        "model": model_name,
                        "success": False,
                        "duration_ms": round((current_time - started_at) * 1000, 3),
                        "error_type": "AgentExecutionError",
                        "error_message": message.removeprefix(f"{self.name}: "),
                        "retryable": False,
                        "attempts_used": len(attempt_history),
                        "max_attempts": max_attempts,
                        "attempt_history": list(attempt_history),
                        **self._provider_call_budget_metadata(),
                        **self._provider_timeout_metadata(provider_name, provider_plan),
                        **self._provider_elapsed_budget_metadata(started_at, current_time),
                        **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                        **self._provider_cancellation_metadata(),
                        **self._provider_circuit_metadata(provider_name, current_time),
                        **self._provider_health_metadata(current_time, provider_plan),
                    }
                    raise AgentExecutionError(message)
                try:
                    self._provider_call_count += 1
                    self._provider_call_counts[provider_name] = self._provider_call_counts.get(provider_name, 0) + 1
                    response = provider.generate(sanitized_system_prompt, sanitized_user_message)
                    self._reset_provider_circuit_breaker(provider_name)
                    self._record_provider_success(provider_name, current_time)
                    attempt_history.append(
                        {
                            "attempt": len(attempt_history) + 1,
                            "success": True,
                            "retryable": False,
                            "backoff_seconds": 0.0,
                        }
                    )
                    completed_at = perf_counter()
                    self._last_provider_call_metadata = {
                        "provider": provider_name,
                        "model": model_name,
                        "success": True,
                        "duration_ms": round((completed_at - started_at) * 1000, 3),
                        "error_type": None,
                        "attempts_used": len(attempt_history),
                        "max_attempts": max_attempts,
                        "attempt_history": list(attempt_history),
                        **self._provider_call_budget_metadata(),
                        **self._provider_timeout_metadata(provider_name, provider_plan),
                        **self._provider_elapsed_budget_metadata(started_at, completed_at),
                        **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                        **self._provider_cancellation_metadata(),
                        **self._provider_circuit_metadata(provider_name, completed_at),
                        **self._provider_health_metadata(completed_at, provider_plan),
                    }
                    provider_metadata = provider.get_last_call_metadata()
                    if provider_metadata is not None:
                        self._last_provider_call_metadata.update(redact_sensitive_data(provider_metadata))
                    return response
                except ProviderTransientError as exc:
                    uncapped_backoff_seconds = self.config.provider_retry_backoff_seconds * (2 ** (attempt - 1))
                    max_backoff_seconds = self.config.provider_retry_max_backoff_seconds
                    base_backoff_seconds = uncapped_backoff_seconds
                    if max_backoff_seconds is not None:
                        base_backoff_seconds = min(base_backoff_seconds, max_backoff_seconds)
                    jitter_seconds = 0.0
                    if base_backoff_seconds > 0 and self.config.provider_retry_jitter_ratio > 0:
                        jitter_seconds = random.uniform(
                            0.0,
                            base_backoff_seconds * self.config.provider_retry_jitter_ratio,
                        )
                    total_backoff_seconds = base_backoff_seconds + jitter_seconds
                    attempt_history.append(
                        {
                            "attempt": len(attempt_history) + 1,
                            "success": False,
                            "retryable": True,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "uncapped_backoff_seconds": round(uncapped_backoff_seconds, 6),
                            "base_backoff_seconds": round(base_backoff_seconds, 6),
                            "jitter_seconds": round(jitter_seconds, 6),
                            "backoff_seconds": round(total_backoff_seconds, 6),
                        }
                    )
                    current_time = perf_counter()
                    self._last_provider_call_metadata = {
                        "provider": provider_name,
                        "model": model_name,
                        "success": False,
                        "duration_ms": round((current_time - started_at) * 1000, 3),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "retryable": True,
                        "attempts_used": len(attempt_history),
                        "max_attempts": max_attempts,
                        "attempt_history": list(attempt_history),
                        **self._provider_call_budget_metadata(),
                        **self._provider_timeout_metadata(provider_name, provider_plan),
                        **self._provider_elapsed_budget_metadata(started_at, current_time),
                        **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                        **self._provider_cancellation_metadata(),
                        **self._provider_health_metadata(current_time, provider_plan),
                    }
                    if attempt >= max_attempts:
                        self._record_provider_failure(
                            provider_name,
                            current_time,
                            type(exc).__name__,
                            str(exc),
                            retryable=True,
                        )
                        self._record_provider_transient_failure(provider_name, current_time)
                        self._last_provider_call_metadata.update(self._provider_circuit_metadata(provider_name, current_time))
                        self._last_provider_call_metadata.update(self._provider_health_metadata(current_time, provider_plan))
                        if provider_index < len(provider_plan) - 1:
                            fallback_history.append(
                                {
                                    "provider": provider_name,
                                    "status": "failed_transient",
                                    "error_type": type(exc).__name__,
                                    "error_message": str(exc),
                                }
                            )
                            break
                        raise self._prefix_agent_execution_error(exc) from exc
                    remaining_elapsed_budget = self._provider_elapsed_budget_remaining_seconds(
                        started_at,
                        current_time,
                    )
                    if remaining_elapsed_budget is not None and total_backoff_seconds >= remaining_elapsed_budget:
                        message = (
                            f"{self.name}: provider elapsed budget exhausted after "
                            f"{current_time - started_at:g} seconds"
                        )
                        self._last_provider_call_metadata = {
                            "provider": provider_name,
                            "model": model_name,
                            "success": False,
                            "duration_ms": round((current_time - started_at) * 1000, 3),
                            "error_type": "AgentExecutionError",
                            "error_message": message.removeprefix(f"{self.name}: "),
                            "retryable": False,
                            "attempts_used": len(attempt_history),
                            "max_attempts": max_attempts,
                            "attempt_history": list(attempt_history),
                            **self._provider_call_budget_metadata(),
                            **self._provider_timeout_metadata(provider_name, provider_plan),
                            **self._provider_elapsed_budget_metadata(started_at, current_time),
                            **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                            **self._provider_cancellation_metadata(),
                            **self._provider_circuit_metadata(provider_name, current_time),
                            **self._provider_health_metadata(current_time, provider_plan),
                        }
                        raise AgentExecutionError(message) from exc
                    if total_backoff_seconds > 0:
                        self._sleep_with_cancellation(
                            total_backoff_seconds,
                            provider_name,
                            model_name,
                            started_at,
                            attempt_history,
                            max_attempts,
                            fallback_history,
                        )
                except Exception as exc:
                    current_time = perf_counter()
                    self._reset_provider_circuit_breaker(provider_name)
                    self._record_provider_failure(
                        provider_name,
                        current_time,
                        type(exc).__name__,
                        str(exc),
                        retryable=False,
                    )
                    attempt_history.append(
                        {
                            "attempt": len(attempt_history) + 1,
                            "success": False,
                            "retryable": False,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "backoff_seconds": 0.0,
                        }
                    )
                    self._last_provider_call_metadata = {
                        "provider": provider_name,
                        "model": model_name,
                        "success": False,
                        "duration_ms": round((current_time - started_at) * 1000, 3),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "retryable": False,
                        "attempts_used": len(attempt_history),
                        "max_attempts": max_attempts,
                        "attempt_history": list(attempt_history),
                        **self._provider_call_budget_metadata(),
                        **self._provider_timeout_metadata(provider_name, provider_plan),
                        **self._provider_elapsed_budget_metadata(started_at, current_time),
                        **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
                        **self._provider_cancellation_metadata(),
                        **self._provider_circuit_metadata(provider_name, current_time),
                        **self._provider_health_metadata(current_time, provider_plan),
                    }
                    if isinstance(exc, AgentExecutionError):
                        raise self._prefix_agent_execution_error(exc) from exc
                    raise AgentExecutionError(f"{self.name} failed to call the model provider") from exc
        raise AgentExecutionError(f"{self.name} failed to call the model provider")

    def _provider_execution_plan(self) -> list[tuple[str, str]]:
        return [
            (self.config.llm_provider, self.config.llm_model),
            *[
                (provider_name, self.config.provider_fallback_models[provider_name])
                for provider_name in self.config.provider_fallback_order
            ],
        ]

    def _is_provider_circuit_open(self, provider_name: str, current_time: float) -> bool:
        if self.config.provider_circuit_breaker_threshold <= 0:
            return False
        return current_time < self._provider_circuit_open_untils.get(provider_name, 0.0)

    def _is_provider_call_budget_exhausted(self) -> bool:
        if self.config.provider_max_calls_per_agent <= 0:
            return False
        return self._provider_call_count >= self.config.provider_max_calls_per_agent

    def _is_provider_specific_call_budget_exhausted(self, provider_name: str) -> bool:
        provider_max_calls = self.config.provider_max_calls_per_provider.get(provider_name, 0)
        if provider_max_calls <= 0:
            return False
        return self._provider_call_counts.get(provider_name, 0) >= provider_max_calls

    def _is_provider_elapsed_budget_exhausted(self, started_at: float, current_time: float) -> bool:
        if self.config.provider_max_elapsed_seconds_per_call <= 0:
            return False
        return (current_time - started_at) >= self.config.provider_max_elapsed_seconds_per_call

    def _provider_elapsed_budget_remaining_seconds(
        self,
        started_at: float,
        current_time: float,
    ) -> Optional[float]:
        if self.config.provider_max_elapsed_seconds_per_call <= 0:
            return None
        return max(
            self.config.provider_max_elapsed_seconds_per_call - (current_time - started_at),
            0.0,
        )

    def _record_provider_transient_failure(self, provider_name: str, current_time: float) -> None:
        if self.config.provider_circuit_breaker_threshold <= 0:
            self._provider_transient_failure_streaks[provider_name] = 0
            self._provider_circuit_open_untils[provider_name] = 0.0
            return
        current_streak = self._provider_transient_failure_streaks.get(provider_name, 0) + 1
        self._provider_transient_failure_streaks[provider_name] = current_streak
        if current_streak >= self.config.provider_circuit_breaker_threshold:
            self._provider_circuit_open_untils[provider_name] = (
                current_time + self.config.provider_circuit_breaker_cooldown_seconds
            )

    def _reset_provider_circuit_breaker(self, provider_name: str) -> None:
        self._provider_transient_failure_streaks[provider_name] = 0
        self._provider_circuit_open_untils[provider_name] = 0.0

    def _provider_circuit_metadata(self, provider_name: str, current_time: float) -> dict[str, Any]:
        remaining_seconds = 0.0
        if self._is_provider_circuit_open(provider_name, current_time):
            remaining_seconds = max(
                self._provider_circuit_open_untils.get(provider_name, 0.0) - current_time,
                0.0,
            )
        return {
            "circuit_breaker_open": self._is_provider_circuit_open(provider_name, current_time),
            "circuit_breaker_failure_streak": self._provider_transient_failure_streaks.get(provider_name, 0),
            "circuit_breaker_threshold": self.config.provider_circuit_breaker_threshold,
            "circuit_breaker_cooldown_seconds": round(
                self.config.provider_circuit_breaker_cooldown_seconds,
                6,
            ),
            "circuit_breaker_remaining_seconds": round(remaining_seconds, 6),
        }

    def _provider_fallback_metadata(
        self,
        provider_name: str,
        model_name: str,
        fallback_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "fallback_history": list(fallback_history),
        }

    def _provider_health_metadata(
        self,
        current_time: float,
        provider_plan: list[tuple[str, str]],
    ) -> dict[str, Any]:
        provider_health: dict[str, dict[str, Any]] = {}
        for provider_name, model_name in provider_plan:
            circuit_open = self._is_provider_circuit_open(provider_name, current_time)
            last_outcome = self._provider_last_outcomes.get(provider_name)
            last_health_check = self._provider_last_health_checks.get(provider_name)
            status = "idle"
            if circuit_open:
                status = "open_circuit"
            elif last_outcome == "success":
                status = "healthy"
            elif last_outcome == "failure":
                status = (
                    "degraded"
                    if self._provider_last_retryable_failures.get(provider_name, False)
                    else "failing"
                )
            elif last_health_check is not None:
                status = str(last_health_check.get("status", status))
            last_success_at = self._provider_last_success_at.get(provider_name)
            last_failure_at = self._provider_last_failure_at.get(provider_name)
            public_last_health_check = (
                None
                if last_health_check is None
                else redact_sensitive_data({
                    key: value
                    for key, value in last_health_check.items()
                    if key != "checked_at"
                })
            )
            if isinstance(public_last_health_check, dict):
                health_check_error_message = public_last_health_check.get("error_message")
                if isinstance(health_check_error_message, str):
                    public_last_health_check["has_error_message"] = bool(health_check_error_message)
                    public_last_health_check.pop("error_message", None)
            last_error_message = self._provider_last_error_messages.get(provider_name)
            provider_health[provider_name] = {
                "model": model_name,
                "status": status,
                "circuit_breaker_open": circuit_open,
                "transient_failure_streak": self._provider_transient_failure_streaks.get(provider_name, 0),
                "last_outcome": last_outcome,
                "last_success_age_seconds": None
                if last_success_at is None
                else round(max(current_time - last_success_at, 0.0), 6),
                "last_failure_age_seconds": None
                if last_failure_at is None
                else round(max(current_time - last_failure_at, 0.0), 6),
                "last_error_type": self._provider_last_error_types.get(provider_name),
                "last_failure_retryable": self._provider_last_retryable_failures.get(provider_name),
                "last_health_check": public_last_health_check,
                "last_health_check_age_seconds": (
                    None
                    if last_health_check is None or "checked_at" not in last_health_check
                    else round(max(current_time - float(last_health_check["checked_at"]), 0.0), 6)
                ),
            }
            if isinstance(last_error_message, str):
                provider_health[provider_name]["has_last_error_message"] = bool(last_error_message)
        return {"provider_health": provider_health}

    def _probe_provider_health(
        self,
        provider_name: str,
        model_name: str,
        provider: BaseLLMProvider,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        runtime_config = self.config.provider_runtime_config(provider_name)
        snapshot: dict[str, Any]
        cached_snapshot = _maybe_get_cached_health_snapshot(runtime_config, started_at)
        if cached_snapshot is not None:
            snapshot = redact_sensitive_data(dict(cached_snapshot))
            self._provider_last_health_checks[provider_name] = snapshot
            error_message = str(
                snapshot.get("error_message")
                or f"{provider_name} health check returned status {snapshot.get('status', 'degraded')}"
            )
            retryable = bool(snapshot.get("retryable", snapshot.get("status") == "degraded"))
            self._record_provider_failure(
                provider_name,
                started_at,
                str(snapshot.get("error_type") or type(self).__name__),
                error_message,
                retryable=retryable,
            )
            if retryable:
                self._record_provider_transient_failure(provider_name, started_at)
                raise ProviderTransientError(error_message)
            raise AgentExecutionError(error_message)
        health_check = getattr(provider, "health_check", None)
        try:
            if callable(health_check):
                typed_health_check = cast(Callable[[], Mapping[str, Any]], health_check)
                snapshot = dict(typed_health_check())
            else:
                snapshot = {
                    "provider": provider_name,
                    "model": model_name,
                    "status": "ready",
                    "active_check": False,
                }
        except ProviderTransientError as exc:
            completed_at = perf_counter()
            snapshot = {
                "provider": provider_name,
                "model": model_name,
                "status": "degraded",
                "active_check": True,
                "retryable": True,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "latency_ms": round((completed_at - started_at) * 1000, 3),
                "checked_at": completed_at,
                "cooldown_cached": False,
                "cooldown_remaining_seconds": 0.0,
            }
            snapshot = redact_sensitive_data(snapshot)
            self._provider_last_health_checks[provider_name] = snapshot
            _store_health_snapshot(runtime_config, snapshot, completed_at)
            self._record_provider_failure(
                provider_name,
                completed_at,
                type(exc).__name__,
                str(exc),
                retryable=True,
            )
            self._record_provider_transient_failure(provider_name, completed_at)
            raise
        except AgentExecutionError as exc:
            completed_at = perf_counter()
            snapshot = {
                "provider": provider_name,
                "model": model_name,
                "status": "failing",
                "active_check": True,
                "retryable": False,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "latency_ms": round((completed_at - started_at) * 1000, 3),
                "checked_at": completed_at,
                "cooldown_cached": False,
                "cooldown_remaining_seconds": 0.0,
            }
            snapshot = redact_sensitive_data(snapshot)
            self._provider_last_health_checks[provider_name] = snapshot
            _store_health_snapshot(runtime_config, snapshot, completed_at)
            self._record_provider_failure(
                provider_name,
                completed_at,
                type(exc).__name__,
                str(exc),
                retryable=False,
            )
            raise

        completed_at = perf_counter()
        if snapshot.get("provider") is None:
            snapshot["provider"] = provider_name
        if snapshot.get("model") is None:
            snapshot["model"] = model_name
        if snapshot.get("status") is None:
            snapshot["status"] = "ready"
        if snapshot.get("active_check") is None:
            snapshot["active_check"] = False
        if snapshot.get("retryable") is None:
            snapshot["retryable"] = False
        snapshot.setdefault("latency_ms", round((completed_at - started_at) * 1000, 3))
        snapshot["checked_at"] = completed_at
        snapshot.setdefault("cooldown_cached", False)
        snapshot.setdefault("cooldown_remaining_seconds", 0.0)
        snapshot = redact_sensitive_data(snapshot)
        self._provider_last_health_checks[provider_name] = snapshot
        _store_health_snapshot(runtime_config, snapshot, completed_at)
        if snapshot.get("active_check") and snapshot.get("status") in {"degraded", "failing"}:
            error_message = str(
                snapshot.get("error_message")
                or f"{provider_name} health check returned status {snapshot['status']}"
            )
            retryable = bool(snapshot.get("retryable", snapshot["status"] == "degraded"))
            self._record_provider_failure(
                provider_name,
                completed_at,
                str(snapshot.get("error_type") or "AgentExecutionError"),
                error_message,
                retryable=retryable,
            )
            if retryable:
                self._record_provider_transient_failure(provider_name, completed_at)
                raise ProviderTransientError(error_message)
            raise AgentExecutionError(error_message)
        return snapshot

    def _provider_cancellation_metadata(self) -> dict[str, Any]:
        return {
            "provider_cancellation_requested": self._provider_cancellation_requested,
            "provider_cancellation_reason": self._provider_cancellation_reason,
        }

    def _provider_call_budget_metadata(self) -> dict[str, Any]:
        remaining_calls: Optional[int] = None
        if self.config.provider_max_calls_per_agent > 0:
            remaining_calls = max(
                self.config.provider_max_calls_per_agent - self._provider_call_count,
                0,
            )
        remaining_calls_by_provider = {
            provider_name: max(max_calls - self._provider_call_counts.get(provider_name, 0), 0)
            for provider_name, max_calls in self.config.provider_max_calls_per_provider.items()
        }
        return {
            "provider_call_count": self._provider_call_count,
            "provider_call_counts_by_provider": dict(self._provider_call_counts),
            "provider_max_calls_per_agent": self.config.provider_max_calls_per_agent,
            "provider_max_calls_per_provider": dict(self.config.provider_max_calls_per_provider),
            "provider_remaining_calls": remaining_calls,
            "provider_remaining_calls_by_provider": remaining_calls_by_provider,
        }

    def _provider_timeout_metadata(
        self,
        provider_name: str,
        provider_plan: list[tuple[str, str]],
    ) -> dict[str, Any]:
        return {
            "provider_timeout_seconds": round(self.config.provider_timeout_seconds_for(provider_name), 6),
            "provider_timeout_seconds_by_provider": {
                planned_provider_name: round(
                    self.config.provider_timeout_seconds_for(planned_provider_name),
                    6,
                )
                for planned_provider_name, _ in provider_plan
            },
        }

    def _provider_elapsed_budget_metadata(
        self,
        started_at: float,
        current_time: float,
    ) -> dict[str, Any]:
        elapsed_seconds = max(current_time - started_at, 0.0)
        return {
            "provider_elapsed_seconds": round(elapsed_seconds, 6),
            "provider_max_elapsed_seconds_per_call": round(
                self.config.provider_max_elapsed_seconds_per_call,
                6,
            ),
            "provider_remaining_elapsed_seconds": (
                None
                if self.config.provider_max_elapsed_seconds_per_call <= 0
                else round(
                    self._provider_elapsed_budget_remaining_seconds(started_at, current_time) or 0.0,
                    6,
                )
            ),
        }

    def _record_provider_success(self, provider_name: str, current_time: float) -> None:
        self._provider_last_outcomes[provider_name] = "success"
        self._provider_last_success_at[provider_name] = current_time
        self._provider_last_retryable_failures[provider_name] = False

    def _record_provider_failure(
        self,
        provider_name: str,
        current_time: float,
        error_type: str,
        error_message: str,
        *,
        retryable: bool,
    ) -> None:
        sanitized_error_message = str(redact_sensitive_data(error_message))
        self._provider_last_outcomes[provider_name] = "failure"
        self._provider_last_failure_at[provider_name] = current_time
        self._provider_last_error_types[provider_name] = error_type
        self._provider_last_error_messages[provider_name] = sanitized_error_message
        self._provider_last_retryable_failures[provider_name] = retryable

    def request_provider_cancellation(self, reason: Optional[str] = None) -> None:
        self._provider_cancellation_requested = True
        self._provider_cancellation_reason = reason.strip() if isinstance(reason, str) and reason.strip() else "cancellation requested"

    def clear_provider_cancellation(self) -> None:
        self._provider_cancellation_requested = False
        self._provider_cancellation_reason = None

    def _raise_if_provider_cancellation_requested(
        self,
        provider_name: str,
        model_name: str,
        started_at: float,
        current_time: float,
        attempt_history: list[dict[str, Any]],
        max_attempts: int,
        fallback_history: list[dict[str, Any]],
    ) -> None:
        if not self._provider_cancellation_requested:
            return
        reason = self._provider_cancellation_reason or "cancellation requested"
        message = f"{self.name}: provider call cancelled ({reason})"
        self._last_provider_call_metadata = {
            "provider": provider_name,
            "model": model_name,
            "success": False,
            "duration_ms": round((current_time - started_at) * 1000, 3),
            "error_type": "AgentExecutionError",
            "error_message": message.removeprefix(f"{self.name}: "),
            "retryable": False,
            "attempts_used": len(attempt_history),
            "max_attempts": max_attempts,
            "attempt_history": list(attempt_history),
            **self._provider_call_budget_metadata(),
            **self._provider_timeout_metadata(provider_name, self._provider_execution_plan()),
            **self._provider_elapsed_budget_metadata(started_at, current_time),
            **self._provider_fallback_metadata(provider_name, model_name, fallback_history),
            **self._provider_cancellation_metadata(),
            **self._provider_circuit_metadata(provider_name, current_time),
        }
        raise AgentExecutionError(message)

    def _sleep_with_cancellation(
        self,
        total_backoff_seconds: float,
        provider_name: str,
        model_name: str,
        started_at: float,
        attempt_history: list[dict[str, Any]],
        max_attempts: int,
        fallback_history: list[dict[str, Any]],
    ) -> None:
        remaining_seconds = total_backoff_seconds
        while remaining_seconds > 0:
            chunk_seconds = min(
                remaining_seconds,
                self.config.provider_cancellation_check_interval_seconds,
            )
            sleep(chunk_seconds)
            remaining_seconds = max(remaining_seconds - chunk_seconds, 0.0)
            current_time = perf_counter()
            self._raise_if_provider_cancellation_requested(
                provider_name,
                model_name,
                started_at,
                current_time,
                attempt_history,
                max_attempts,
                fallback_history,
            )

    def run_with_input(self, agent_input: AgentInput) -> str | AgentOutput:
        return self.run(agent_input.task_description, agent_input.context)

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        self.validate_input(agent_input)
        self.before_execute(agent_input)
        try:
            result = self.run_with_input(agent_input)
            output = self._normalize_output(result, agent_input)
            unredacted_output = self._finalize_output(
                agent_input,
                deepcopy(output),
                redact_output=False,
                use_custom_validation=False,
            )
            finalized_output = self.after_execute(agent_input, output)
            finalized_output = self._finalize_output(
                agent_input,
                finalized_output,
                redact_output=True,
                use_custom_validation=False,
            )
            self._last_unredacted_output = unredacted_output
            return finalized_output
        except Exception as exc:
            self.on_execution_error(agent_input, exc)
            raise AssertionError("on_execution_error must raise an exception") from exc

    def validate_input(self, agent_input: AgentInput) -> None:
        """Validate the public AgentInput contract before agent execution."""
        if not agent_input.task_id.strip():
            raise AgentExecutionError(f"{self.name}: task_id must not be empty")
        if not agent_input.task_title.strip():
            raise AgentExecutionError(f"{self.name}: task_title must not be empty")
        if not agent_input.task_description.strip():
            raise AgentExecutionError(f"{self.name}: task_description must not be empty")
        if not agent_input.project_name.strip():
            raise AgentExecutionError(f"{self.name}: project_name must not be empty")
        if not isinstance(agent_input.context, dict):
            raise AgentExecutionError(f"{self.name}: context must be a dictionary")
        for key in self.required_context_keys:
            value = agent_input.context.get(key)
            if value is None:
                raise AgentExecutionError(f"{self.name}: required context key '{key}' is missing")
            if isinstance(value, str) and not value.strip():
                raise AgentExecutionError(f"{self.name}: required context key '{key}' must not be empty")

    def before_execute(self, agent_input: AgentInput) -> None:
        """Hook invoked after input validation and before the agent runs."""
        return None

    def after_execute(self, agent_input: AgentInput, output: AgentOutput) -> AgentOutput:
        """Hook invoked after normalization to finalize the public AgentOutput."""
        return self._finalize_output(agent_input, output, redact_output=True)

    def _finalize_output(
        self,
        agent_input: AgentInput,
        output: AgentOutput,
        *,
        redact_output: bool,
        use_custom_validation: bool = True,
    ) -> AgentOutput:
        output = self._normalize_output_for_artifact_type(output)
        if redact_output:
            output = self._redact_output(output)
        if use_custom_validation:
            self.validate_output(output)
        else:
            BaseAgent.validate_output(self, output)
        output.metadata.setdefault("agent_name", self.name)
        output.metadata.setdefault("agent_role", self.role)
        output.metadata.setdefault("task_id", agent_input.task_id)
        output.metadata.setdefault("project_name", agent_input.project_name)
        provider_call = output.metadata.get("provider_call") if isinstance(output.metadata, dict) else None
        if isinstance(provider_call, Mapping):
            output.metadata["provider_call"] = sanitize_provider_call_metadata(provider_call)
        elif self._last_provider_call_metadata is not None:
            output.metadata.setdefault(
                "provider_call",
                sanitize_provider_call_metadata(self._last_provider_call_metadata),
            )
        if not output.artifacts:
            output.artifacts.append(self._build_default_artifact(agent_input, output))
        return output

    def _redact_output(self, output: AgentOutput) -> AgentOutput:
        output.summary = redact_sensitive_text(output.summary)
        output.raw_content = redact_sensitive_text(output.raw_content)
        output.artifacts = [self._redact_artifact_record(artifact) for artifact in output.artifacts]
        output.decisions = [self._redact_decision_record(decision) for decision in output.decisions]
        output.metadata = cast(dict[str, Any], redact_sensitive_data(output.metadata))
        return output

    def _redact_artifact_record(self, artifact: ArtifactRecord) -> ArtifactRecord:
        return ArtifactRecord(
            name=redact_sensitive_text(artifact.name),
            artifact_type=artifact.artifact_type,
            path=redact_sensitive_text(artifact.path) if artifact.path is not None else None,
            content=redact_sensitive_text(artifact.content) if artifact.content is not None else None,
            created_at=artifact.created_at,
            metadata=cast(dict[str, Any], redact_sensitive_data(artifact.metadata)),
        )

    def _redact_decision_record(self, decision: DecisionRecord) -> DecisionRecord:
        return DecisionRecord(
            topic=redact_sensitive_text(decision.topic),
            decision=redact_sensitive_text(decision.decision),
            rationale=redact_sensitive_text(decision.rationale),
            created_at=decision.created_at,
            metadata=cast(dict[str, Any], redact_sensitive_data(decision.metadata)),
        )

    def _consume_last_unredacted_output(self) -> Optional[AgentOutput]:
        output = self._last_unredacted_output
        self._last_unredacted_output = None
        return output

    def _normalize_output_for_artifact_type(self, output: AgentOutput) -> AgentOutput:
        if self.output_artifact_type not in {ArtifactType.CODE, ArtifactType.TEST}:
            return output
        normalized_raw_content = self._extract_code_content(output.raw_content)
        if normalized_raw_content == output.raw_content:
            return output
        output.raw_content = normalized_raw_content
        output.summary = self._summarize_output(normalized_raw_content)
        return output

    def _extract_code_content(self, raw_content: str) -> str:
        code_blocks = re.findall(r"```(?:[A-Za-z0-9_+-]+)?\n(.*?)```", raw_content, flags=re.DOTALL)
        if not code_blocks:
            return self._extract_code_like_lines(raw_content)
        normalized_blocks = [block.strip() for block in code_blocks if block.strip()]
        if not normalized_blocks:
            return self._extract_code_like_lines(raw_content)
        return "\n\n".join(normalized_blocks)

    def _extract_code_like_lines(self, raw_content: str) -> str:
        lines = raw_content.strip().splitlines()
        start_index: Optional[int] = None
        code_start_pattern = re.compile(
            r"^(from\s+\S+\s+import\s+.+|import\s+\S+|class\s+\w+|def\s+\w+|async\s+def\s+\w+|@\w+|if\s+__name__\s*==\s*['\"]__main__['\"]\s*:|[A-Za-z_][A-Za-z0-9_]*\s*=)"
        )
        for index, line in enumerate(lines):
            stripped = line.strip()
            if code_start_pattern.match(stripped):
                start_index = index
                break
        if start_index is None:
            return raw_content
        candidate = "\n".join(lines[start_index:]).strip()
        return candidate or raw_content

    def validate_output(self, output: AgentOutput) -> None:
        """Validate the public AgentOutput contract before state is persisted."""
        if not output.raw_content.strip():
            raise AgentExecutionError(f"{self.name}: agent output raw_content must not be empty")
        if not output.summary.strip():
            raise AgentExecutionError(f"{self.name}: agent output summary must not be empty")
        if not isinstance(output.artifacts, list):
            raise AgentExecutionError(f"{self.name}: agent output artifacts must be a list")
        if not isinstance(output.decisions, list):
            raise AgentExecutionError(f"{self.name}: agent output decisions must be a list")
        if not isinstance(output.metadata, dict):
            raise AgentExecutionError(f"{self.name}: agent output metadata must be a dictionary")

    def on_execution_error(self, agent_input: AgentInput, exc: Exception) -> None:
        """Hook invoked for execution failures before the final public error is raised."""
        if isinstance(exc, AgentExecutionError):
            raise exc
        raise AgentExecutionError(f"{self.name} failed during agent execution") from exc

    def _prefix_agent_execution_error(self, exc: AgentExecutionError) -> AgentExecutionError:
        message = f"{self.name}: {redact_sensitive_data(str(exc))}"
        if isinstance(exc, ProviderTransientError):
            return ProviderTransientError(message)
        return AgentExecutionError(message)

    def _normalize_output(self, result: Any, agent_input: AgentInput) -> AgentOutput:
        if isinstance(result, AgentOutput):
            if not result.summary.strip():
                result.summary = self._summarize_output(result.raw_content)
            return result
        if not isinstance(result, str):
            raise AgentExecutionError(f"{self.name}: agent output must be a string or AgentOutput")
        if not result.strip():
            raise AgentExecutionError(f"{self.name}: agent output must not be empty")
        return AgentOutput(
            summary=self._summarize_output(result),
            raw_content=result,
            metadata={
                "agent_name": self.name,
                "agent_role": self.role,
                "task_id": agent_input.task_id,
            },
        )

    def _summarize_output(self, raw_content: str) -> str:
        first_line = raw_content.strip().splitlines()[0].strip()
        return first_line[:120]

    def _build_default_artifact(self, agent_input: AgentInput, output: AgentOutput) -> ArtifactRecord:
        return ArtifactRecord(
            name=f"{agent_input.task_id}_{self.output_artifact_name}",
            artifact_type=self.output_artifact_type,
            content=output.raw_content,
            metadata={
                "agent_name": self.name,
                "task_id": agent_input.task_id,
                "project_name": agent_input.project_name,
            },
        )

    def require_context_value(self, agent_input: AgentInput, key: str) -> Any:
        value = agent_input.context.get(key)
        if value is None:
            raise AgentExecutionError(f"{self.name}: required context key '{key}' is missing")
        if isinstance(value, str) and not value.strip():
            raise AgentExecutionError(f"{self.name}: required context key '{key}' must not be empty")
        return value

    def get_last_provider_call_metadata(self) -> Optional[dict[str, Any]]:
        if self._last_provider_call_metadata is None:
            return None
        return sanitize_provider_call_metadata(self._last_provider_call_metadata)

    @abstractmethod
    def run(self, task_description: str, context: dict) -> str | AgentOutput:
        pass

    def __repr__(self):
        return f"<Agent name={self.name} role={self.role}>"
