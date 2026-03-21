from abc import ABC, abstractmethod
from typing import Any, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.providers.factory import create_provider
from kycortex_agents.types import AgentInput, AgentOutput


class BaseAgent(ABC):
    required_context_keys: tuple[str, ...] = ()

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

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        self.validate_input(agent_input)
        self.before_execute(agent_input)
        try:
            result = self.run_with_input(agent_input)
            output = self._normalize_output(result, agent_input)
            return self.after_execute(agent_input, output)
        except Exception as exc:
            self.on_execution_error(agent_input, exc)
            raise AssertionError("on_execution_error must raise an exception") from exc

    def validate_input(self, agent_input: AgentInput) -> None:
        if not agent_input.task_id.strip():
            raise AgentExecutionError(f"{self.name}: task_id must not be empty")
        if not agent_input.task_title.strip():
            raise AgentExecutionError(f"{self.name}: task_title must not be empty")
        if not agent_input.task_description.strip():
            raise AgentExecutionError(f"{self.name}: task_description must not be empty")
        if not agent_input.project_name.strip():
            raise AgentExecutionError(f"{self.name}: project_name must not be empty")
        if not isinstance(agent_input.context, dict):
            raise AgentExecutionError(f"{self.name}: context must be a dictionary")
        for key in self.required_context_keys:
            value = agent_input.context.get(key)
            if value is None:
                raise AgentExecutionError(f"{self.name}: required context key '{key}' is missing")
            if isinstance(value, str) and not value.strip():
                raise AgentExecutionError(f"{self.name}: required context key '{key}' must not be empty")

    def before_execute(self, agent_input: AgentInput) -> None:
        return None

    def after_execute(self, agent_input: AgentInput, output: AgentOutput) -> AgentOutput:
        output.metadata.setdefault("agent_name", self.name)
        output.metadata.setdefault("agent_role", self.role)
        output.metadata.setdefault("task_id", agent_input.task_id)
        return output

    def on_execution_error(self, agent_input: AgentInput, exc: Exception) -> None:
        if isinstance(exc, AgentExecutionError):
            raise exc
        raise AgentExecutionError(f"{self.name} failed during agent execution") from exc

    def _normalize_output(self, result: Any, agent_input: AgentInput) -> AgentOutput:
        if isinstance(result, AgentOutput):
            if not result.raw_content.strip():
                raise AgentExecutionError(f"{self.name}: agent output raw_content must not be empty")
            if not result.summary.strip():
                result.summary = self._summarize_output(result.raw_content)
            return result
        if not isinstance(result, str):
            raise AgentExecutionError(f"{self.name}: agent output must be a string or AgentOutput")
        if not result.strip():
            raise AgentExecutionError(f"{self.name}: agent output must not be empty")
        return AgentOutput(
            summary=self._summarize_output(result),
            raw_content=result,
            metadata={
                "agent_name": self.name,
                "agent_role": self.role,
                "task_id": agent_input.task_id,
            },
        )

    def _summarize_output(self, raw_content: str) -> str:
        first_line = raw_content.strip().splitlines()[0].strip()
        return first_line[:120]

    def require_context_value(self, agent_input: AgentInput, key: str) -> Any:
        value = agent_input.context.get(key)
        if value is None:
            raise AgentExecutionError(f"{self.name}: required context key '{key}' is missing")
        if isinstance(value, str) and not value.strip():
            raise AgentExecutionError(f"{self.name}: required context key '{key}' must not be empty")
        return value

    @abstractmethod
    def run(self, task_description: str, context: dict) -> str:
        pass

    def __repr__(self):
        return f"<Agent name={self.name} role={self.role}>"
