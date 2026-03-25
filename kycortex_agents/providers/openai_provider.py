from __future__ import annotations

from typing import Any, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers._error_classifier import is_transient_provider_exception
from kycortex_agents.providers.base import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    """OpenAI-backed provider implementation for chat completion models."""

    def __init__(self, config: KYCortexConfig, client: Optional[Any] = None):
        self.config = config
        self._client = client
        self._last_call_metadata: Optional[dict[str, Any]] = None

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.config.api_key)
        return self._client

    def _build_messages(self, system_prompt: str, user_message: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    def _extract_content(self, response: Any) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise AgentExecutionError("OpenAI provider returned an invalid response payload") from exc
        if not content:
            raise AgentExecutionError("OpenAI provider returned an empty response")
        return content

    def generate(self, system_prompt: str, user_message: str) -> str:
        client = self._get_client()
        try:
            response = client.chat.completions.create(
                model=self.config.llm_model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                messages=self._build_messages(system_prompt, user_message),
            )
        except Exception as exc:
            self._last_call_metadata = None
            if is_transient_provider_exception(exc):
                raise ProviderTransientError("OpenAI provider failed to call the model API") from exc
            raise AgentExecutionError("OpenAI provider rejected the model API request") from exc
        self._last_call_metadata = self._extract_metadata(response)
        return self._extract_content(response)

    def _extract_metadata(self, response: Any) -> Optional[dict[str, Any]]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        return {
            "usage": {
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
        }

    def get_last_call_metadata(self) -> Optional[dict[str, Any]]:
        if self._last_call_metadata is None:
            return None
        return dict(self._last_call_metadata)