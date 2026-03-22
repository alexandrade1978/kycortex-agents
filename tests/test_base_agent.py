import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.types import AgentInput, AgentOutput


class DummyAgent(BaseAgent):
    def __init__(self, provider):
        super().__init__("Dummy", "Testing", KYCortexConfig(output_dir="./output_test"))
        self._provider = provider
        self.events = []

    def run(self, task_description: str, context: dict) -> str:
        return self.chat("system", task_description)

    def before_execute(self, agent_input: AgentInput) -> None:
        self.events.append(("before", agent_input.task_id))

    def after_execute(self, agent_input: AgentInput, output: AgentOutput) -> AgentOutput:
        output = super().after_execute(agent_input, output)
        output.metadata["hook"] = "after"
        self.events.append(("after", agent_input.task_id))
        return output

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


def test_execute_returns_standardized_agent_output():
    provider = DummyProvider(response="first line\nsecond line")
    agent = DummyAgent(provider)
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    result = agent.execute(agent_input)

    assert result.summary == "first line"
    assert result.raw_content == "first line\nsecond line"
    assert result.metadata["agent_name"] == "Dummy"
    assert result.metadata["provider_call"]["provider"] == "openai"
    assert result.metadata["provider_call"]["model"] == "gpt-4o"
    assert result.metadata["provider_call"]["success"] is True
    assert result.metadata["provider_call"]["duration_ms"] >= 0
    assert result.metadata["hook"] == "after"
    assert agent.events == [("before", "task-1"), ("after", "task-1")]


def test_execute_rejects_missing_task_description():
    agent = DummyAgent(DummyProvider(response="ok"))
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    with pytest.raises(AgentExecutionError, match="task_description must not be empty"):
        agent.execute(agent_input)


def test_execute_wraps_unexpected_runtime_errors():
    class ExplodingAgent(DummyAgent):
        def run(self, task_description: str, context: dict) -> str:
            raise RuntimeError("boom")

    agent = ExplodingAgent(DummyProvider(response="ok"))
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    with pytest.raises(AgentExecutionError, match="Dummy failed during agent execution"):
        agent.execute(agent_input)


def test_chat_captures_failed_provider_call_metadata():
    provider = DummyProvider(error=RuntimeError("provider down"))
    agent = DummyAgent(provider)

    with pytest.raises(AgentExecutionError, match="Dummy failed to call the model provider"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()

    assert metadata is not None
    assert metadata["provider"] == "openai"
    assert metadata["model"] == "gpt-4o"
    assert metadata["success"] is False
    assert metadata["error_type"] == "RuntimeError"
    assert metadata["duration_ms"] >= 0