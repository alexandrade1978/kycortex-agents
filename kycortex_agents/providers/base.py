from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


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