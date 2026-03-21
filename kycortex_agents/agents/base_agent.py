from abc import ABC, abstractmethod
from typing import Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.providers.factory import create_provider
from kycortex_agents.types import AgentInput


class BaseAgent(ABC):
    def __init__(self, name: str, role: str, config: KYCortexConfig):
        self.name = name
        self.role = role
        self.config = config
        self._provider: Optional[BaseLLMProvider] = None

    def _get_provider(self) -> BaseLLMProvider:
        if self._provider is None:
            self._provider = create_provider(self.config)
        return self._provider

    def chat(self, system_prompt: str, user_message: str) -> str:
        try:
            return self._get_provider().generate(system_prompt, user_message)
        except Exception as exc:
            if isinstance(exc, AgentExecutionError):
                raise AgentExecutionError(f"{self.name}: {exc}") from exc
            raise AgentExecutionError(f"{self.name} failed to call the model provider") from exc

    def run_with_input(self, agent_input: AgentInput) -> str:
        return self.run(agent_input.task_description, agent_input.context)

    @abstractmethod
    def run(self, task_description: str, context: dict) -> str:
        pass

    def __repr__(self):
        return f"<Agent name={self.name} role={self.role}>"
