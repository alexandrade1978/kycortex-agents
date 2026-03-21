from __future__ import annotations

import json
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.providers.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    def __init__(
        self,
        config: KYCortexConfig,
        request_opener: Optional[Callable[..., Any]] = None,
    ):
        self.config = config
        self._request_opener = request_opener or urlopen

    def _endpoint(self) -> str:
        base_url = (self.config.base_url or "").rstrip("/")
        return f"{base_url}/api/generate"

    def _build_payload(self, system_prompt: str, user_message: str) -> dict[str, Any]:
        return {
            "model": self.config.llm_model,
            "system": system_prompt,
            "prompt": user_message,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
            },
        }

    def _extract_content(self, payload: dict[str, Any]) -> str:
        content = payload.get("response")
        if not content:
            raise AgentExecutionError("Ollama provider returned an empty response")
        return content

    def generate(self, system_prompt: str, user_message: str) -> str:
        body = json.dumps(self._build_payload(system_prompt, user_message)).encode("utf-8")
        request = Request(
            self._endpoint(),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._request_opener(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise AgentExecutionError("Ollama provider failed to call the model API") from exc
        return self._extract_content(payload)