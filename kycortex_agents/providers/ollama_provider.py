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
        self._last_call_metadata: Optional[dict[str, Any]] = None

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
            self._last_call_metadata = None
            raise AgentExecutionError("Ollama provider failed to call the model API") from exc
        self._last_call_metadata = self._extract_metadata(payload)
        return self._extract_content(payload)

    def _extract_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt_eval_count = payload.get("prompt_eval_count")
        eval_count = payload.get("eval_count")
        total_tokens = None
        if prompt_eval_count is not None or eval_count is not None:
            total_tokens = (prompt_eval_count or 0) + (eval_count or 0)
        total_duration_ns = payload.get("total_duration")
        load_duration_ns = payload.get("load_duration")
        return {
            "usage": {
                "input_tokens": prompt_eval_count,
                "output_tokens": eval_count,
                "total_tokens": total_tokens,
            },
            "timing": {
                "total_duration_ms": round(total_duration_ns / 1_000_000, 3) if isinstance(total_duration_ns, (int, float)) else None,
                "load_duration_ms": round(load_duration_ns / 1_000_000, 3) if isinstance(load_duration_ns, (int, float)) else None,
            },
        }

    def get_last_call_metadata(self) -> Optional[dict[str, Any]]:
        if self._last_call_metadata is None:
            return None
        return dict(self._last_call_metadata)