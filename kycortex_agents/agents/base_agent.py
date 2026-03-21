from abc import ABC, abstractmethod
from typing import Any, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError


class BaseAgent(ABC):
    def __init__(self, name: str, role: str, config: KYCortexConfig):
        self.name = name
        self.role = role
        self.config = config
        self._client: Optional[Any] = None

    def _get_client(self):
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
            raise AgentExecutionError(f"{self.name} returned an invalid response payload") from exc
        if not content:
            raise AgentExecutionError(f"{self.name} returned an empty response")
        return content

    def chat(self, system_prompt: str, user_message: str) -> str:
        client = self._get_client()
        try:
            response = client.chat.completions.create(
                model=self.config.llm_model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                messages=self._build_messages(system_prompt, user_message),
            )
        except Exception as exc:
            raise AgentExecutionError(f"{self.name} failed to call the model provider") from exc
        return self._extract_content(response)

    @abstractmethod
    def run(self, task_description: str, context: dict) -> str:
        pass

    def __repr__(self):
        return f"<Agent name={self.name} role={self.role}>"
