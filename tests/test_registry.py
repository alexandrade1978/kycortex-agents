import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.registry import AgentRegistry, build_default_registry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError


class DummyAgent(BaseAgent):
    def __init__(self):
        super().__init__("Dummy", "Testing", KYCortexConfig(output_dir="./output_test", api_key="token"))

    def run(self, task_description: str, context: dict) -> str:
        return "ok"


def test_registry_normalizes_agent_keys():
    registry = AgentRegistry()
    agent = DummyAgent()

    registry.register(" Code Engineer ", agent)

    assert registry.get("code_engineer") is agent
    assert registry.get("Code Engineer") is agent


def test_registry_rejects_unknown_agent():
    registry = AgentRegistry()

    with pytest.raises(AgentExecutionError, match="Unknown agent"):
        registry.get("missing")


def test_build_default_registry_contains_core_agents(tmp_path):
    registry = build_default_registry(KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="token"))

    assert registry.has("architect")
    assert registry.has("code_engineer")
    assert registry.has("code_reviewer")