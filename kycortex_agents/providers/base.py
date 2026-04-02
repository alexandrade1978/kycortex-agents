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