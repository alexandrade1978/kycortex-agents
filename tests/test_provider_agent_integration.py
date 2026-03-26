from types import SimpleNamespace

import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider
from kycortex_agents.types import AgentInput


class FakeAPIError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def build_agent_input() -> AgentInput:
    return AgentInput(
        task_id="arch",
        task_title="Architecture",
        task_description="Design the architecture",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )


def build_openai_client(response=None, error=None, captured_kwargs=None):
    def create(**kwargs):
        if captured_kwargs is not None:
            captured_kwargs.append(kwargs)
        if error is not None:
            raise error
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def build_anthropic_client(response=None, error=None, captured_kwargs=None):
    def create(**kwargs):
        if captured_kwargs is not None:
            captured_kwargs.append(kwargs)
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
    calls = 0

    def open_request(request, timeout=None):
        nonlocal calls
        current_payload = payload[min(calls, len(payload) - 1)] if isinstance(payload, list) else payload
        current_error = error[min(calls, len(error) - 1)] if isinstance(error, list) else error
        calls += 1
        if current_error is not None:
            raise current_error
        return FakeHTTPResponse(current_payload)

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
    ("provider_name", "provider", "expected_message"),
    [
        (
            "openai",
            OpenAIProvider(
                KYCortexConfig(output_dir="./output_test", llm_provider="openai", api_key="token", llm_model="gpt-4o"),
                client=build_openai_client(error=RuntimeError("openai down")),
            ),
            "failed to call the model API",
        ),
        (
            "anthropic",
            AnthropicProvider(
                KYCortexConfig(output_dir="./output_test", llm_provider="anthropic", api_key="token", llm_model="claude-3-5-sonnet"),
                client=build_anthropic_client(error=RuntimeError("anthropic down")),
            ),
            "failed to call the model API",
        ),
        (
            "ollama",
            OllamaProvider(
                KYCortexConfig(output_dir="./output_test", llm_provider="ollama", llm_model="llama3", base_url="http://localhost:11434"),
                request_opener=build_ollama_opener(error=OSError("ollama down")),
            ),
            "Ollama server is not responding",
        ),
    ],
)
def test_execute_surfaces_provider_failures_with_failed_call_metadata(provider_name, provider, expected_message):
    config = provider.config
    agent = ProviderBackedAgent(provider, config)

    with pytest.raises(AgentExecutionError, match=rf"IntegrationAgent: .*{expected_message}"):
        agent.execute(build_agent_input())

    metadata = agent.get_last_provider_call_metadata()

    assert metadata is not None
    assert metadata["provider"] == provider_name
    assert metadata["model"] == config.llm_model
    assert metadata["success"] is False
    assert metadata["error_type"] == "ProviderTransientError"
    assert metadata["retryable"] is True
    assert metadata["attempts_used"] == 1
    assert metadata["max_attempts"] == 1
    assert metadata["attempt_history"][0]["error_type"] == "ProviderTransientError"
    assert metadata["attempt_history"][0]["base_backoff_seconds"] == 0.0
    assert expected_message in metadata["error_message"]
    assert metadata["duration_ms"] >= 0


def test_execute_records_retry_attempt_metadata_for_transient_provider_recovery(monkeypatch):
    class FlakyProvider:
        def __init__(self):
            self.config = KYCortexConfig(
                output_dir="./output_test",
                llm_provider="openai",
                api_key="token",
                provider_max_attempts=2,
                provider_retry_backoff_seconds=0.0,
            )
            self.calls = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls += 1
            if self.calls == 1:
                raise ProviderTransientError("temporary provider outage")
            return "RECOVERED RESULT"

        def get_last_call_metadata(self):
            return {"usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}}

    monkeypatch.setattr("kycortex_agents.agents.base_agent.sleep", lambda _: None)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)
    provider = FlakyProvider()
    agent = ProviderBackedAgent(provider, provider.config)

    result = agent.execute(build_agent_input())

    assert result.metadata["provider_call"]["success"] is True
    assert result.metadata["provider_call"]["attempts_used"] == 2
    assert result.metadata["provider_call"]["max_attempts"] == 2
    assert len(result.metadata["provider_call"]["attempt_history"]) == 2
    assert result.metadata["provider_call"]["usage"]["total_tokens"] == 5


def test_execute_does_not_retry_deterministic_provider_request_failures():
    config = KYCortexConfig(
        output_dir="./output_test",
        llm_provider="openai",
        api_key="token",
        llm_model="gpt-4o",
        provider_max_attempts=3,
        provider_retry_backoff_seconds=1.0,
    )
    provider = OpenAIProvider(
        config,
        client=build_openai_client(error=FakeAPIError("bad request", 400)),
    )
    agent = ProviderBackedAgent(provider, config)

    with pytest.raises(AgentExecutionError, match=r"IntegrationAgent: OpenAI provider rejected the model API request"):
        agent.execute(build_agent_input())

    metadata = agent.get_last_provider_call_metadata()

    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["error_type"] == "AgentExecutionError"
    assert metadata["attempts_used"] == 1
    assert metadata["max_attempts"] == 3
    assert len(metadata["attempt_history"]) == 1
    assert metadata["attempt_history"][0]["retryable"] is False
    assert metadata["attempt_history"][0]["error_type"] == "AgentExecutionError"


def test_execute_falls_back_to_secondary_provider_after_transient_primary_failure(monkeypatch):
    primary_config = KYCortexConfig(
        output_dir="./output_test",
        llm_provider="openai",
        api_key="token",
        llm_model="gpt-4o",
        provider_max_attempts=1,
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
    )
    primary_provider = OpenAIProvider(
        primary_config,
        client=build_openai_client(error=RuntimeError("openai down")),
    )
    fallback_provider = AnthropicProvider(
        KYCortexConfig(
            output_dir="./output_test",
            llm_provider="anthropic",
            api_key="token",
            llm_model="claude-3-5-sonnet",
        ),
        client=build_anthropic_client(
            response=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="FALLBACK RESULT")],
                usage=SimpleNamespace(input_tokens=12, output_tokens=8),
            )
        ),
    )

    def create_fallback_provider(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        assert runtime_config.llm_model == "claude-3-5-sonnet"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_fallback_provider)
    agent = ProviderBackedAgent(primary_provider, primary_config)

    result = agent.execute(build_agent_input())

    metadata = result.metadata["provider_call"]
    assert result.raw_content == "FALLBACK RESULT"
    assert metadata["provider"] == "anthropic"
    assert metadata["model"] == "claude-3-5-sonnet"
    assert metadata["success"] is True
    assert metadata["fallback_used"] is True
    assert metadata["fallback_count"] == 1
    assert metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "failed_transient",
            "error_type": "ProviderTransientError",
            "error_message": "OpenAI provider failed to call the model API",
            "attempts_used": 1,
        }
    ]
    assert metadata["attempts_used"] == 2
    assert metadata["usage"]["total_tokens"] == 20
    assert metadata["provider_health"]["openai"]["status"] == "degraded"
    assert metadata["provider_health"]["openai"]["last_failure_retryable"] is True
    assert metadata["provider_health"]["anthropic"]["status"] == "healthy"


def test_execute_falls_back_to_secondary_provider_after_primary_provider_budget_exhaustion(monkeypatch):
    primary_config = KYCortexConfig(
        output_dir="./output_test",
        llm_provider="openai",
        api_key="token",
        llm_model="gpt-4o",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        provider_max_calls_per_provider={"openai": 1},
    )
    primary_provider = OpenAIProvider(
        primary_config,
        client=build_openai_client(
            response=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="PRIMARY RESULT"))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        ),
    )
    fallback_provider = AnthropicProvider(
        KYCortexConfig(
            output_dir="./output_test",
            llm_provider="anthropic",
            api_key="token",
            llm_model="claude-3-5-sonnet",
        ),
        client=build_anthropic_client(
            response=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="FALLBACK RESULT")],
                usage=SimpleNamespace(input_tokens=12, output_tokens=8),
            )
        ),
    )

    def create_fallback_provider(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        assert runtime_config.llm_model == "claude-3-5-sonnet"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_fallback_provider)
    agent = ProviderBackedAgent(primary_provider, primary_config)

    first_result = agent.execute(build_agent_input())
    second_result = agent.execute(build_agent_input())

    metadata = second_result.metadata["provider_call"]
    assert first_result.raw_content == "PRIMARY RESULT"
    assert second_result.raw_content == "FALLBACK RESULT"
    assert metadata["provider"] == "anthropic"
    assert metadata["fallback_used"] is True
    assert metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "skipped_call_budget_exhausted",
            "provider_call_count": 1,
            "provider_max_calls": 1,
        }
    ]
    assert metadata["provider_call_counts_by_provider"] == {"openai": 1, "anthropic": 1}
    assert metadata["provider_max_calls_per_provider"] == {"openai": 1}
    assert metadata["provider_remaining_calls_by_provider"] == {"openai": 0}


def test_execute_surfaces_provider_specific_timeout_metadata_and_runtime_override(monkeypatch):
    primary_calls: list[dict[str, object]] = []
    fallback_calls: list[dict[str, object]] = []
    primary_config = KYCortexConfig(
        output_dir="./output_test",
        llm_provider="openai",
        api_key="token",
        llm_model="gpt-4o",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        provider_max_calls_per_provider={"openai": 1},
        timeout_seconds=60.0,
        provider_timeout_seconds={"openai": 11.0, "anthropic": 22.0},
    )
    primary_provider = OpenAIProvider(
        primary_config.provider_runtime_config("openai"),
        client=build_openai_client(
            response=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="PRIMARY RESULT"))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            ),
            captured_kwargs=primary_calls,
        ),
    )
    fallback_provider = AnthropicProvider(
        KYCortexConfig(
            output_dir="./output_test",
            llm_provider="anthropic",
            api_key="token",
            llm_model="claude-3-5-sonnet",
            timeout_seconds=22.0,
        ),
        client=build_anthropic_client(
            response=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="FALLBACK RESULT")],
                usage=SimpleNamespace(input_tokens=12, output_tokens=8),
            ),
            captured_kwargs=fallback_calls,
        ),
    )

    def create_fallback_provider(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        assert runtime_config.timeout_seconds == 22.0
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_fallback_provider)
    agent = ProviderBackedAgent(primary_provider, primary_config)

    first_result = agent.execute(build_agent_input())
    second_result = agent.execute(build_agent_input())

    metadata = second_result.metadata["provider_call"]
    assert first_result.raw_content == "PRIMARY RESULT"
    assert second_result.raw_content == "FALLBACK RESULT"
    assert primary_calls[0]["timeout"] == 11.0
    assert fallback_calls[0]["timeout"] == 22.0
    assert metadata["provider_timeout_seconds"] == 22.0
    assert metadata["provider_timeout_seconds_by_provider"] == {"openai": 11.0, "anthropic": 22.0}