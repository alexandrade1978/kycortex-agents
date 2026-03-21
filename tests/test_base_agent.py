import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.types import AgentInput


class DummyAgent(BaseAgent):
    def __init__(self, provider):
        super().__init__("Dummy", "Testing", KYCortexConfig(output_dir="./output_test"))
        self._provider = provider

    def run(self, task_description: str, context: dict) -> str:
        return self.chat("system", task_description)

class DummyProvider(BaseLLMProvider):
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self.error is not None:
            raise self.error
        return self.response


def test_chat_returns_response_content():
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)

    result = agent.chat("system", "message")

    assert result == "ok"
    assert provider.calls == [("system", "message")]


def test_chat_raises_on_provider_error():
    agent = DummyAgent(DummyProvider(error=RuntimeError("provider down")))

    with pytest.raises(AgentExecutionError, match="Dummy failed to call the model provider"):
        agent.chat("system", "message")


def test_chat_raises_on_empty_response():
    agent = DummyAgent(DummyProvider(error=AgentExecutionError("provider returned an empty response")))

    with pytest.raises(AgentExecutionError, match="Dummy: provider returned an empty response"):
        agent.chat("system", "message")


def test_run_with_input_delegates_to_legacy_run_signature():
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={"architecture": "doc"},
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert provider.calls == [("system", "message")]