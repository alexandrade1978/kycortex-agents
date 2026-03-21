from types import SimpleNamespace

import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError


class DummyAgent(BaseAgent):
    def __init__(self, client):
        super().__init__("Dummy", "Testing", KYCortexConfig(output_dir="./output_test"))
        self._client = client

    def run(self, task_description: str, context: dict) -> str:
        return self.chat("system", task_description)


def build_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def build_client(response=None, error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_chat_returns_response_content():
    agent = DummyAgent(build_client(response=build_response("ok")))

    result = agent.chat("system", "message")

    assert result == "ok"


def test_chat_raises_on_provider_error():
    agent = DummyAgent(build_client(error=RuntimeError("provider down")))

    with pytest.raises(AgentExecutionError, match="failed to call the model provider"):
        agent.chat("system", "message")


def test_chat_raises_on_empty_response():
    agent = DummyAgent(build_client(response=build_response(None)))

    with pytest.raises(AgentExecutionError, match="returned an empty response"):
        agent.chat("system", "message")