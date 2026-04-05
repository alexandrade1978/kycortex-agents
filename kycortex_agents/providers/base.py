from __future__ import annotations

from collections.abc import Mapping
import re
from abc import ABC, abstractmethod
from typing import Any, Optional


_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "refresh_token",
    "secret",
    "session_token",
}
_SECRET_ASSIGNMENT_PATTERNS = (
    re.compile(
        r"(?i)\b((?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|session[_ -]?token|secret|password)\s*[:=]\s*['\"]?)([^'\"\s,;]+)(['\"]?)"
    ),
    re.compile(
        r"(?i)\b((?:openai_api_key|anthropic_api_key|aws_secret_access_key|aws_session_token|hf_token)\s*[:=]\s*['\"]?)([^'\"\s,;]+)(['\"]?)"
    ),
    re.compile(r"(?i)\b(authorization\s*:\s*bearer\s+)([^\s,;]+)"),
    re.compile(r"(?i)\b(bearer\s+)([^\s,;]+)"),
)
_STANDALONE_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}\b"),
)
_URL_USERINFO_PATTERN = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@")
_PROMPT_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_LEGACY_PROVIDER_CALL_BUDGET_KEYS = (
    "provider_call_count",
    "provider_call_counts_by_provider",
    "provider_max_calls_per_agent",
    "provider_max_calls_per_provider",
    "provider_remaining_calls",
    "provider_remaining_calls_by_provider",
)

def _redact_assignment_match(match: re.Match[str]) -> str:
    suffix = match.group(3) if match.re.groups >= 3 else ""
    return f"{match.group(1)}{_REDACTED}{suffix}"

def redact_sensitive_text(value: str) -> str:
    """Return a string with obvious credentials and bearer secrets redacted."""

    redacted = _URL_USERINFO_PATTERN.sub(r"\1[REDACTED]:[REDACTED]@", value)
    for pattern in _SECRET_ASSIGNMENT_PATTERNS:
        redacted = pattern.sub(_redact_assignment_match, redacted)
    for pattern in _STANDALONE_SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def sanitize_prompt_input(value: str) -> str:
    """Return provider-bound prompt text with control chars stripped and secrets redacted."""

    sanitized = redact_sensitive_text(value)
    return _PROMPT_CONTROL_CHAR_PATTERN.sub(" ", sanitized)


def redact_sensitive_data(value: Any) -> Any:
    """Recursively redact obvious credentials from provider-facing metadata."""

    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_sensitive_key(key):
                redacted[key] = None if item is None else _REDACTED
            else:
                redacted[key] = redact_sensitive_data(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    return value


def sanitize_provider_call_metadata(provider_call: Mapping[str, Any]) -> dict[str, Any]:
    """Return provider-call metadata with secrets redacted and surfaced error/retry/budget details minimized."""

    sanitized = redact_sensitive_data(dict(provider_call))
    if not isinstance(sanitized, dict):
        return {}
    _sanitize_provider_call_attempt_history(sanitized)
    _sanitize_provider_call_budget_metadata(sanitized)
    _sanitize_provider_call_cancellation_metadata(sanitized)
    _sanitize_provider_call_circuit_breaker_metadata(sanitized)
    _sanitize_provider_call_elapsed_budget_metadata(sanitized)
    _sanitize_provider_call_timeout_metadata(sanitized)
    _sanitize_provider_call_fallback_history(sanitized)
    _sanitize_provider_call_health_metadata(sanitized)
    _sanitize_provider_call_active_target_metadata(sanitized)
    _sanitize_provider_call_primary_target_metadata(sanitized)
    _sanitize_provider_call_top_level_error_message(sanitized)
    _sanitize_provider_call_top_level_error_type(sanitized)
    return sanitized


def _sanitize_provider_call_attempt_history(provider_call: dict[str, Any]) -> None:
    attempt_history = provider_call.get("attempt_history")
    if not isinstance(attempt_history, list):
        return

    sanitized_history: list[Any] = []
    for entry in attempt_history:
        if not isinstance(entry, dict):
            sanitized_history.append(entry)
            continue

        sanitized_entry = dict(entry)
        sanitized_entry.pop("uncapped_backoff_seconds", None)
        sanitized_entry.pop("base_backoff_seconds", None)
        sanitized_entry.pop("jitter_seconds", None)
        _minimize_nested_provider_error_type(sanitized_entry)
        _minimize_nested_provider_error_message(sanitized_entry)
        sanitized_history.append(sanitized_entry)

    provider_call["attempt_history"] = sanitized_history


def _minimize_nested_provider_error_message(provider_call_entry: dict[str, Any]) -> None:
    error_message = provider_call_entry.get("error_message")
    if isinstance(error_message, str):
        provider_call_entry["has_error_message"] = bool(error_message)
        provider_call_entry.pop("error_message", None)


def _minimize_nested_provider_error_type(provider_call_entry: dict[str, Any]) -> None:
    error_type = provider_call_entry.get("error_type")
    if isinstance(error_type, str):
        provider_call_entry["has_error_type"] = bool(error_type)
        provider_call_entry.pop("error_type", None)


def _sanitize_provider_call_top_level_error_message(provider_call: dict[str, Any]) -> None:
    error_message = provider_call.get("error_message")
    if isinstance(error_message, str):
        provider_call["has_error_message"] = bool(error_message)
        provider_call.pop("error_message", None)


def _sanitize_provider_call_top_level_error_type(provider_call: dict[str, Any]) -> None:
    error_type = provider_call.get("error_type")
    if isinstance(error_type, str):
        provider_call["has_error_type"] = bool(error_type)
        provider_call.pop("error_type", None)


def _sanitize_provider_call_cancellation_metadata(provider_call: dict[str, Any]) -> None:
    cancellation_reason = provider_call.get("provider_cancellation_reason")
    if isinstance(cancellation_reason, str):
        provider_call["has_provider_cancellation_reason"] = bool(cancellation_reason)
        provider_call.pop("provider_cancellation_reason", None)


def _sanitize_provider_call_circuit_breaker_metadata(provider_call: dict[str, Any]) -> None:
    provider_call.pop("circuit_breaker_failure_streak", None)
    provider_call.pop("circuit_breaker_threshold", None)
    provider_call.pop("circuit_breaker_cooldown_seconds", None)
    provider_call.pop("circuit_breaker_remaining_seconds", None)


def _sanitize_provider_call_timeout_metadata(provider_call: dict[str, Any]) -> None:
    provider_call.pop("provider_timeout_seconds", None)
    provider_call.pop("provider_timeout_seconds_by_provider", None)
    provider_call.pop("provider_timeout_provider_count", None)


def _sanitize_provider_call_elapsed_budget_metadata(provider_call: dict[str, Any]) -> None:
    max_elapsed_seconds = provider_call.get("provider_max_elapsed_seconds_per_call")
    remaining_elapsed_seconds = provider_call.get("provider_remaining_elapsed_seconds")

    provider_call["provider_elapsed_budget_limited"] = bool(
        provider_call.get("provider_elapsed_budget_limited")
    ) or _is_positive_number(max_elapsed_seconds)
    provider_call["provider_elapsed_budget_exhausted"] = bool(
        provider_call.get("provider_elapsed_budget_exhausted")
    ) or _is_exhausted_budget(remaining_elapsed_seconds)

    provider_call.pop("provider_elapsed_seconds", None)
    provider_call.pop("provider_max_elapsed_seconds_per_call", None)
    provider_call.pop("provider_remaining_elapsed_seconds", None)


def _sanitize_provider_call_budget_metadata(provider_call: dict[str, Any]) -> None:
    limited_providers: list[str]
    exhausted_providers: list[str]

    if any(key in provider_call for key in _LEGACY_PROVIDER_CALL_BUDGET_KEYS):
        limited_providers = _limited_budget_providers(
            provider_call.get("provider_max_calls_per_provider")
        )
        exhausted_providers = _exhausted_budget_providers(
            limited_providers,
            provider_call.get("provider_remaining_calls_by_provider"),
        )
        limited = _is_positive_number(provider_call.get("provider_max_calls_per_agent")) or bool(
            limited_providers
        )
        exhausted = _is_positive_number(
            provider_call.get("provider_max_calls_per_agent")
        ) and _is_exhausted_budget(provider_call.get("provider_remaining_calls"))
    else:
        limited_providers = _normalized_string_list(
            provider_call.get("provider_call_budget_limited_providers")
        )
        exhausted_candidates = _normalized_string_list(
            provider_call.get("provider_call_budget_exhausted_providers")
        )
        exhausted_providers = [
            provider_name
            for provider_name in exhausted_candidates
            if provider_name in limited_providers or not limited_providers
        ]
        limited = bool(provider_call.get("provider_call_budget_limited")) or bool(limited_providers)
        exhausted = bool(provider_call.get("provider_call_budget_exhausted"))

    provider_call["provider_call_budget_limited"] = limited
    provider_call["provider_call_budget_exhausted"] = exhausted
    provider_call["provider_call_budget_limited_providers"] = limited_providers
    provider_call["provider_call_budget_exhausted_providers"] = exhausted_providers

    for key in _LEGACY_PROVIDER_CALL_BUDGET_KEYS:
        provider_call.pop(key, None)


def _sanitize_provider_call_fallback_history(provider_call: dict[str, Any]) -> None:
    provider_call.pop("fallback_used", None)
    provider_call.pop("fallback_count", None)
    fallback_history = provider_call.get("fallback_history")
    if not isinstance(fallback_history, list):
        return

    sanitized_history: list[Any] = []
    for entry in fallback_history:
        if not isinstance(entry, dict):
            sanitized_history.append(entry)
            continue

        sanitized_entry = dict(entry)
        sanitized_entry.pop("model", None)
        sanitized_entry.pop("attempts_used", None)
        sanitized_entry.pop("provider_call_count", None)
        sanitized_entry.pop("provider_max_calls", None)
        sanitized_entry.pop("call_budget_exhausted", None)
        sanitized_entry.pop("remaining_cooldown_seconds", None)

        _minimize_nested_provider_error_type(sanitized_entry)
        _minimize_nested_provider_error_message(sanitized_entry)
        sanitized_history.append(sanitized_entry)

    provider_call["fallback_history"] = sanitized_history


def _sanitize_provider_call_active_target_metadata(provider_call: dict[str, Any]) -> None:
    provider_call.pop("active_provider", None)
    provider_call.pop("active_model", None)


def _sanitize_provider_call_primary_target_metadata(provider_call: dict[str, Any]) -> None:
    provider_call.pop("primary_provider", None)
    provider_call.pop("primary_model", None)


def _sanitize_provider_call_health_metadata(provider_call: dict[str, Any]) -> None:
    raw_provider_health = provider_call.get("provider_health")
    if not isinstance(raw_provider_health, Mapping):
        return

    sanitized_provider_health: dict[Any, Any] = {}
    for provider_name, raw_health_entry in raw_provider_health.items():
        if not isinstance(raw_health_entry, Mapping):
            sanitized_provider_health[provider_name] = raw_health_entry
            continue

        sanitized_health_entry = dict(raw_health_entry)
        _minimize_provider_health_error_message(sanitized_health_entry)
        _minimize_provider_health_error_type(sanitized_health_entry)
        _minimize_provider_health_age_fields(sanitized_health_entry)

        last_health_check = sanitized_health_entry.get("last_health_check")
        if isinstance(last_health_check, Mapping):
            sanitized_last_health_check = dict(last_health_check)
            _minimize_nested_health_check_error_type(sanitized_last_health_check)
            _minimize_nested_health_check_error_message(sanitized_last_health_check)
            _minimize_nested_health_check_timing_fields(sanitized_last_health_check)
            sanitized_last_health_check.pop("model_ready", None)
            sanitized_last_health_check.pop("retryable", None)
            sanitized_last_health_check.pop("latency_ms", None)
            sanitized_last_health_check.pop("provider", None)
            sanitized_health_entry["last_health_check"] = sanitized_last_health_check

        sanitized_provider_health[provider_name] = sanitized_health_entry

    provider_call["provider_health"] = sanitized_provider_health


def _minimize_provider_health_error_message(provider_health_entry: dict[str, Any]) -> None:
    provider_health_entry.pop("last_error_message", None)
    provider_health_entry.pop("has_last_error_message", None)


def _minimize_provider_health_error_type(provider_health_entry: dict[str, Any]) -> None:
    provider_health_entry.pop("last_error_type", None)
    provider_health_entry.pop("has_last_error_type", None)


def _minimize_provider_health_age_fields(provider_health_entry: dict[str, Any]) -> None:
    provider_health_entry.pop("circuit_breaker_open", None)
    provider_health_entry.pop("transient_failure_streak", None)
    provider_health_entry.pop("last_success_age_seconds", None)
    provider_health_entry.pop("last_failure_age_seconds", None)
    provider_health_entry.pop("last_health_check_age_seconds", None)
    provider_health_entry.pop("last_failure_retryable", None)


def _minimize_nested_health_check_error_type(health_check_entry: dict[str, Any]) -> None:
    health_check_entry.pop("error_type", None)
    health_check_entry.pop("has_error_type", None)


def _minimize_nested_health_check_error_message(health_check_entry: dict[str, Any]) -> None:
    health_check_entry.pop("error_message", None)
    health_check_entry.pop("has_error_message", None)


def _minimize_nested_health_check_timing_fields(health_check_entry: dict[str, Any]) -> None:
    health_check_entry.pop("cooldown_remaining_seconds", None)


def _limited_budget_providers(raw_limits: Any) -> list[str]:
    if not isinstance(raw_limits, Mapping):
        return []
    return sorted(
        provider_name
        for provider_name, max_calls in raw_limits.items()
        if isinstance(provider_name, str) and provider_name and _is_positive_number(max_calls)
    )


def _exhausted_budget_providers(limited_providers: list[str], raw_remaining: Any) -> list[str]:
    if not isinstance(raw_remaining, Mapping):
        return []
    return [
        provider_name
        for provider_name in limited_providers
        if _is_exhausted_budget(raw_remaining.get(provider_name))
    ]


def _normalized_string_list(raw_values: Any) -> list[str]:
    if not isinstance(raw_values, list):
        return []
    return sorted(
        value.strip()
        for value in raw_values
        if isinstance(value, str) and value.strip()
    )


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _is_exhausted_budget(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value <= 0


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    if normalized in _SENSITIVE_KEY_NAMES:
        return True
    return normalized.endswith(
        (
            "_api_key",
            "_access_token",
            "_refresh_token",
            "_session_token",
            "_secret",
            "_password",
            "_credential",
            "_credentials",
        )
    )


class BaseLLMProvider(ABC):
    """Abstract provider contract for model-backed agent text generation."""

    @abstractmethod
    def generate(self, system_prompt: str, user_message: str) -> str:
        """Return a model response for the given system and user prompts."""

        raise NotImplementedError

    def get_last_call_metadata(self) -> Optional[dict[str, Any]]:
        """Return provider-specific metadata captured from the most recent model call."""

        return None

    def health_check(self) -> dict[str, Any]:
        """Return a lightweight provider health snapshot without generating model output."""

        config = getattr(self, "config", None)
        return {
            "provider": getattr(config, "llm_provider", None),
            "model": getattr(config, "llm_model", None),
            "status": "ready",
            "active_check": False,
        }