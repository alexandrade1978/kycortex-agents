from __future__ import annotations

from typing import Any, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers._error_classifier import is_transient_provider_exception
from kycortex_agents.providers.base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    """Anthropic-backed provider implementation for Claude message models."""

    def __init__(self, config: KYCortexConfig, client: Optional[Any] = None):
        self.config = config
        self._client = client
        self._last_call_metadata: Optional[dict[str, Any]] = None

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic  # type: ignore[import-not-found]

            self._client = Anthropic(api_key=self.config.api_key)
        return self._client

    def _extract_content(self, response: Any) -> str:
        try:
            content_blocks = response.content
        except AttributeError as exc:
            raise AgentExecutionError("Anthropic provider returned an invalid response payload") from exc

        for block in content_blocks:
            text = getattr(block, "text", None)
            if getattr(block, "type", None) == "text" and text:
                return text

        raise AgentExecutionError("Anthropic provider returned an empty response")

    def generate(self, system_prompt: str, user_message: str) -> str:
        client = self._get_client()
        try:
            response = client.messages.create(
                model=self.config.llm_model,
                system=system_prompt,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                timeout=self.config.timeout_seconds,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:
            self._last_call_metadata = None
            if is_transient_provider_exception(exc):
                raise ProviderTransientError("Anthropic provider failed to call the model API") from exc
            raise AgentExecutionError("Anthropic provider rejected the model API request") from exc
        self._last_call_metadata = self._extract_metadata(response)
        return self._extract_content(response)

    def _extract_metadata(self, response: Any) -> Optional[dict[str, Any]]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        cache_creation_input_tokens = getattr(usage, "cache_creation_input_tokens", None)
        cache_read_input_tokens = getattr(usage, "cache_read_input_tokens", None)
        total_tokens = None
        if input_tokens is not None or output_tokens is not None:
            total_tokens = (input_tokens or 0) + (output_tokens or 0)
        return {
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
            }
        }

    def get_last_call_metadata(self) -> Optional[dict[str, Any]]:
        if self._last_call_metadata is None:
            return None
        return dict(self._last_call_metadata)