from types import SimpleNamespace

import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider
from kycortex_agents.types import AgentInput


def build_agent_input() -> AgentInput:
    return AgentInput(
        task_id="arch",
        task_title="Architecture",
        task_description="Design the architecture",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )


def build_openai_client(response=None, error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def build_anthropic_client(response=None, error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    return SimpleNamespace(messages=SimpleNamespace(create=create))


class FakeHTTPResponse:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def build_ollama_opener(payload=None, error=None):
    def open_request(request, timeout=None):
        if error is not None:
            raise error
        return FakeHTTPResponse(payload)

    return open_request


class ProviderBackedAgent(BaseAgent):
    def __init__(self, provider, config: KYCortexConfig):
        super().__init__("IntegrationAgent", "Testing", config)
        self._provider = provider

    def run(self, task_description: str, context: dict) -> str:
        return self.chat("system", task_description)


@pytest.mark.parametrize(
    ("provider_name", "provider", "expected_model", "expected_usage", "expected_timing"),
    [
        (
            "openai",
            OpenAIProvider(
                KYCortexConfig(output_dir="./output_test", llm_provider="openai", api_key="token", llm_model="gpt-4o"),
                client=build_openai_client(
                    response=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="OPENAI RESULT"))],
                        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                    )
                ),
            ),
            "gpt-4o",
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            None,
        ),
        (
            "anthropic",
            AnthropicProvider(
                KYCortexConfig(output_dir="./output_test", llm_provider="anthropic", api_key="token", llm_model="claude-3-5-sonnet"),
                client=build_anthropic_client(
                    response=SimpleNamespace(
                        content=[SimpleNamespace(type="text", text="ANTHROPIC RESULT")],
                        usage=SimpleNamespace(
                            input_tokens=12,
                            output_tokens=8,
                            cache_creation_input_tokens=3,
                            cache_read_input_tokens=2,
                        ),
                    )
                ),
            ),
            "claude-3-5-sonnet",
            {
                "input_tokens": 12,
                "output_tokens": 8,
                "total_tokens": 20,
                "cache_creation_input_tokens": 3,
                "cache_read_input_tokens": 2,
            },
            None,
        ),
        (
            "ollama",
            OllamaProvider(
                KYCortexConfig(output_dir="./output_test", llm_provider="ollama", llm_model="llama3", base_url="http://localhost:11434"),
                request_opener=build_ollama_opener(
                    payload='{"response": "OLLAMA RESULT", "prompt_eval_count": 14, "eval_count": 9, "total_duration": 125000000, "load_duration": 25000000}'
                ),
            ),
            "llama3",
            {"input_tokens": 14, "output_tokens": 9, "total_tokens": 23},
            {"total_duration_ms": 125.0, "load_duration_ms": 25.0},
        ),
    ],
)
def test_execute_integrates_provider_metadata(provider_name, provider, expected_model, expected_usage, expected_timing):
    config = provider.config
    agent = ProviderBackedAgent(provider, config)

    result = agent.execute(build_agent_input())

    assert result.summary.endswith("RESULT")
    assert result.raw_content.endswith("RESULT")
    assert result.metadata["agent_name"] == "IntegrationAgent"
    assert result.metadata["provider_call"]["provider"] == provider_name
    assert result.metadata["provider_call"]["model"] == expected_model
    assert result.metadata["provider_call"]["success"] is True
    assert result.metadata["provider_call"]["duration_ms"] >= 0
    assert result.metadata["provider_call"]["usage"] == expected_usage
    if expected_timing is None:
        assert "timing" not in result.metadata["provider_call"]
    else:
        assert result.metadata["provider_call"]["timing"] == expected_timing
    assert result.artifacts[0].metadata["agent_name"] == "IntegrationAgent"
    assert result.artifacts[0].metadata["task_id"] == "arch"


@pytest.mark.parametrize(
    ("provider_name", "provider"),
    [
        (
            "openai",
            OpenAIProvider(
                KYCortexConfig(output_dir="./output_test", llm_provider="openai", api_key="token", llm_model="gpt-4o"),
                client=build_openai_client(error=RuntimeError("openai down")),
            ),
        ),
        (
            "anthropic",
            AnthropicProvider(
                KYCortexConfig(output_dir="./output_test", llm_provider="anthropic", api_key="token", llm_model="claude-3-5-sonnet"),
                client=build_anthropic_client(error=RuntimeError("anthropic down")),
            ),
        ),
        (
            "ollama",
            OllamaProvider(
                KYCortexConfig(output_dir="./output_test", llm_provider="ollama", llm_model="llama3", base_url="http://localhost:11434"),
                request_opener=build_ollama_opener(error=OSError("ollama down")),
            ),
        ),
    ],
)
def test_execute_surfaces_provider_failures_with_failed_call_metadata(provider_name, provider):
    config = provider.config
    agent = ProviderBackedAgent(provider, config)

    with pytest.raises(AgentExecutionError, match="IntegrationAgent: .*failed to call the model API"):
        agent.execute(build_agent_input())

    metadata = agent.get_last_provider_call_metadata()

    assert metadata is not None
    assert metadata["provider"] == provider_name
    assert metadata["model"] == config.llm_model
    assert metadata["success"] is False
    assert metadata["error_type"] == "AgentExecutionError"
    assert metadata["duration_ms"] >= 0