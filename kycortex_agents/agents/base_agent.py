from abc import ABC, abstractmethod
from typing import Optional
from kycortex_agents.config import KYCortexConfig

class BaseAgent(ABC):
    def __init__(self, name: str, role: str, config: KYCortexConfig):
        self.name = name
        self.role = role
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.config.api_key)
        return self._client

    def chat(self, system_prompt: str, user_message: str) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.config.llm_model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        return response.choices[0].message.content

    @abstractmethod
    def run(self, task_description: str, context: dict) -> str:
        pass

    def __repr__(self):
        return f"<Agent name={self.name} role={self.role}>"
