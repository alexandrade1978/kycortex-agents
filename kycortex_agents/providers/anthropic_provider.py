from __future__ import annotations

from typing import Any, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.providers.base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, config: KYCortexConfig, client: Optional[Any] = None):
        self.config = config
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic

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
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:
            raise AgentExecutionError("Anthropic provider failed to call the model API") from exc
        return self._extract_content(response)