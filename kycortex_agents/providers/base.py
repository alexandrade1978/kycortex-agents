from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_message: str) -> str:
        raise NotImplementedError

    def get_last_call_metadata(self) -> Optional[dict[str, Any]]:
        return None