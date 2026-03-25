import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactType


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
    def __init__(self, response=None, error=None, metadata=None):
        self.response = response
        self.error = error
        self.metadata = metadata
        self.calls = []

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self.error is not None:
            raise self.error
        return self.response

    def get_last_call_metadata(self):
        return self.metadata


class CodeDummyAgent(DummyAgent):
    output_artifact_type = ArtifactType.CODE


class PytestDummyAgent(DummyAgent):
    output_artifact_type = ArtifactType.TEST


def test_chat_returns_response_content():
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)

    result = agent.chat("system", "message")

    assert result == "ok"
    assert provider.calls == [("system", "message")]
    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["provider_call_count"] == 1
    assert metadata["provider_max_calls_per_agent"] == 0
    assert metadata["provider_remaining_calls"] is None
    assert metadata["provider_max_elapsed_seconds_per_call"] == 0.0
    assert metadata["provider_remaining_elapsed_seconds"] is None
    assert metadata["provider_cancellation_requested"] is False
    assert metadata["provider_cancellation_reason"] is None


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
    provider = DummyProvider(
        response="first line\nsecond line",
        metadata={"usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}},
    )
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
    assert result.metadata["provider_call"]["usage"]["total_tokens"] == 18
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
    assert metadata["error_message"] == "provider down"
    assert metadata["duration_ms"] >= 0
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": False,
            "error_type": "RuntimeError",
            "error_message": "provider down",
            "backoff_seconds": 0.0,
        }
    ]


def test_chat_retries_transient_provider_error_and_succeeds(monkeypatch):
    class FlakyProvider(DummyProvider):
        def __init__(self):
            super().__init__(response="ok")
            self.attempts = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            self.attempts += 1
            if self.attempts == 1:
                raise ProviderTransientError("provider temporarily unavailable")
            return "ok"

    provider = FlakyProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 2
    agent.config.provider_retry_backoff_seconds = 0.0
    monkeypatch.setattr("kycortex_agents.agents.base_agent.sleep", lambda _: None)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)

    result = agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert result == "ok"
    assert provider.calls == [("system", "message"), ("system", "message")]
    assert metadata is not None
    assert metadata["success"] is True
    assert metadata["attempts_used"] == 2
    assert metadata["max_attempts"] == 2
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "error_type": "ProviderTransientError",
            "error_message": "provider temporarily unavailable",
            "uncapped_backoff_seconds": 0.0,
            "base_backoff_seconds": 0.0,
            "jitter_seconds": 0.0,
            "backoff_seconds": 0.0,
        },
        {
            "attempt": 2,
            "success": True,
            "retryable": False,
            "backoff_seconds": 0.0,
        },
    ]


def test_chat_exhausts_transient_provider_retries(monkeypatch):
    class AlwaysTransientProvider(DummyProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

    provider = AlwaysTransientProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 2
    agent.config.provider_retry_backoff_seconds = 0.0
    monkeypatch.setattr("kycortex_agents.agents.base_agent.sleep", lambda _: None)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)

    with pytest.raises(AgentExecutionError, match="Dummy: provider temporarily unavailable"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is True
    assert metadata["attempts_used"] == 2
    assert metadata["max_attempts"] == 2
    assert metadata["error_type"] == "ProviderTransientError"
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "error_type": "ProviderTransientError",
            "error_message": "provider temporarily unavailable",
            "uncapped_backoff_seconds": 0.0,
            "base_backoff_seconds": 0.0,
            "jitter_seconds": 0.0,
            "backoff_seconds": 0.0,
        },
        {
            "attempt": 2,
            "success": False,
            "retryable": True,
            "error_type": "ProviderTransientError",
            "error_message": "provider temporarily unavailable",
            "uncapped_backoff_seconds": 0.0,
            "base_backoff_seconds": 0.0,
            "jitter_seconds": 0.0,
            "backoff_seconds": 0.0,
        },
    ]


def test_chat_applies_retry_jitter_to_sleep(monkeypatch):
    class JitterProvider(DummyProvider):
        def __init__(self):
            super().__init__(response="ok")
            self.attempts = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            self.attempts += 1
            if self.attempts == 1:
                raise ProviderTransientError("temporary provider outage")
            return "ok"

    sleep_calls: list[float] = []
    provider = JitterProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 2
    agent.config.provider_retry_backoff_seconds = 1.0
    agent.config.provider_retry_jitter_ratio = 0.5
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.25)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.sleep", lambda seconds: sleep_calls.append(seconds))

    result = agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert result == "ok"
    assert round(sum(sleep_calls), 6) == 1.25
    assert max(sleep_calls) <= agent.config.provider_cancellation_check_interval_seconds
    assert metadata is not None
    assert metadata["attempt_history"][0]["uncapped_backoff_seconds"] == 1.0
    assert metadata["attempt_history"][0]["base_backoff_seconds"] == 1.0
    assert metadata["attempt_history"][0]["jitter_seconds"] == 0.25
    assert metadata["attempt_history"][0]["backoff_seconds"] == 1.25


def test_chat_fails_fast_when_provider_call_budget_is_exhausted():
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)
    agent.config.provider_max_calls_per_agent = 1

    first_result = agent.chat("system", "message")

    with pytest.raises(AgentExecutionError, match="Dummy: provider call budget exhausted after 1 calls"):
        agent.chat("system", "second-message")

    metadata = agent.get_last_provider_call_metadata()
    assert first_result == "ok"
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["attempts_used"] == 0
    assert metadata["provider_call_count"] == 1
    assert metadata["provider_max_calls_per_agent"] == 1
    assert metadata["provider_remaining_calls"] == 0
    assert metadata["attempt_history"] == []
    assert provider.calls == [("system", "message")]


def test_chat_budget_blocks_additional_retry_attempts_after_first_failure(monkeypatch):
    class AlwaysTransientProvider(DummyProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

    provider = AlwaysTransientProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 2
    agent.config.provider_retry_backoff_seconds = 0.0
    agent.config.provider_max_calls_per_agent = 1
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)

    with pytest.raises(AgentExecutionError, match="Dummy: provider call budget exhausted after 1 calls"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["attempts_used"] == 1
    assert metadata["provider_call_count"] == 1
    assert metadata["provider_remaining_calls"] == 0
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "error_type": "ProviderTransientError",
            "error_message": "provider temporarily unavailable",
            "uncapped_backoff_seconds": 0.0,
            "base_backoff_seconds": 0.0,
            "jitter_seconds": 0.0,
            "backoff_seconds": 0.0,
        }
    ]


def test_chat_stops_retrying_when_elapsed_budget_is_exhausted_before_next_attempt(monkeypatch):
    class AlwaysTransientProvider(DummyProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

    provider = AlwaysTransientProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 3
    agent.config.provider_retry_backoff_seconds = 0.0
    agent.config.provider_max_elapsed_seconds_per_call = 0.5
    timestamps = iter([100.0, 100.0, 100.2, 100.2, 100.6, 100.6])
    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: next(timestamps))
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)

    with pytest.raises(AgentExecutionError, match="Dummy: provider elapsed budget exhausted after 0.6 seconds"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["attempts_used"] == 1
    assert metadata["provider_elapsed_seconds"] == 0.6
    assert metadata["provider_max_elapsed_seconds_per_call"] == 0.5
    assert metadata["provider_remaining_elapsed_seconds"] == 0.0
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "error_type": "ProviderTransientError",
            "error_message": "provider temporarily unavailable",
            "uncapped_backoff_seconds": 0.0,
            "base_backoff_seconds": 0.0,
            "jitter_seconds": 0.0,
            "backoff_seconds": 0.0,
        }
    ]


def test_chat_does_not_sleep_past_elapsed_budget(monkeypatch):
    class AlwaysTransientProvider(DummyProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

    provider = AlwaysTransientProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 3
    agent.config.provider_retry_backoff_seconds = 1.0
    agent.config.provider_max_elapsed_seconds_per_call = 0.5
    sleep_calls: list[float] = []
    timestamps = iter([100.0, 100.0, 100.2, 100.2, 100.2, 100.2, 100.2])
    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: next(timestamps))
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.sleep", lambda seconds: sleep_calls.append(seconds))

    with pytest.raises(AgentExecutionError, match="Dummy: provider elapsed budget exhausted after 0.2 seconds"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["attempts_used"] == 1
    assert metadata["provider_elapsed_seconds"] == 0.2
    assert metadata["provider_remaining_elapsed_seconds"] == 0.3
    assert sleep_calls == []


def test_chat_fails_fast_when_provider_cancellation_is_requested_before_first_attempt():
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)
    agent.request_provider_cancellation("operator requested stop")

    with pytest.raises(AgentExecutionError, match=r"Dummy: provider call cancelled \(operator requested stop\)"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["attempts_used"] == 0
    assert metadata["provider_cancellation_requested"] is True
    assert metadata["provider_cancellation_reason"] == "operator requested stop"
    assert provider.calls == []


def test_chat_cancels_during_retry_backoff(monkeypatch):
    class AlwaysTransientProvider(DummyProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

    provider = AlwaysTransientProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 2
    agent.config.provider_retry_backoff_seconds = 0.2
    agent.config.provider_cancellation_check_interval_seconds = 0.1
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        agent.request_provider_cancellation("operator requested stop")

    monkeypatch.setattr("kycortex_agents.agents.base_agent.sleep", fake_sleep)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)

    with pytest.raises(AgentExecutionError, match=r"Dummy: provider call cancelled \(operator requested stop\)"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["attempts_used"] == 1
    assert metadata["provider_cancellation_requested"] is True
    assert metadata["provider_cancellation_reason"] == "operator requested stop"
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "error_type": "ProviderTransientError",
            "error_message": "provider temporarily unavailable",
            "uncapped_backoff_seconds": 0.2,
            "base_backoff_seconds": 0.2,
            "jitter_seconds": 0.0,
            "backoff_seconds": 0.2,
        }
    ]
    assert sleep_calls == [0.1]
    assert provider.calls == [("system", "message")]


def test_chat_caps_retry_backoff_before_jitter(monkeypatch):
    class CappedBackoffProvider(DummyProvider):
        def __init__(self):
            super().__init__(response="ok")
            self.attempts = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            self.attempts += 1
            if self.attempts == 1:
                raise ProviderTransientError("temporary provider outage")
            return "ok"

    sleep_calls: list[float] = []
    provider = CappedBackoffProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 2
    agent.config.provider_retry_backoff_seconds = 5.0
    agent.config.provider_retry_max_backoff_seconds = 1.5
    agent.config.provider_retry_jitter_ratio = 0.5
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.25)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.sleep", lambda seconds: sleep_calls.append(seconds))

    result = agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert result == "ok"
    assert round(sum(sleep_calls), 6) == 1.75
    assert max(sleep_calls) <= agent.config.provider_cancellation_check_interval_seconds
    assert metadata is not None
    assert metadata["attempt_history"][0]["uncapped_backoff_seconds"] == 5.0
    assert metadata["attempt_history"][0]["base_backoff_seconds"] == 1.5
    assert metadata["attempt_history"][0]["jitter_seconds"] == 0.25
    assert metadata["attempt_history"][0]["backoff_seconds"] == 1.75


def test_chat_opens_circuit_breaker_after_repeated_transient_failures(monkeypatch):
    class AlwaysTransientProvider(DummyProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

    provider = AlwaysTransientProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 1
    agent.config.provider_circuit_breaker_threshold = 2
    agent.config.provider_circuit_breaker_cooldown_seconds = 10.0
    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: 100.0)

    with pytest.raises(AgentExecutionError, match="Dummy: provider temporarily unavailable"):
        agent.chat("system", "message")

    first_metadata = agent.get_last_provider_call_metadata()
    assert first_metadata is not None
    assert first_metadata["circuit_breaker_open"] is False
    assert first_metadata["circuit_breaker_failure_streak"] == 1
    assert first_metadata["circuit_breaker_remaining_seconds"] == 0.0

    with pytest.raises(AgentExecutionError, match="Dummy: provider temporarily unavailable"):
        agent.chat("system", "message")

    second_metadata = agent.get_last_provider_call_metadata()
    assert second_metadata is not None
    assert second_metadata["circuit_breaker_open"] is True
    assert second_metadata["circuit_breaker_failure_streak"] == 2
    assert second_metadata["circuit_breaker_remaining_seconds"] == 10.0

    with pytest.raises(AgentExecutionError, match="Dummy: provider circuit breaker is open for 10 more seconds"):
        agent.chat("system", "message")

    open_metadata = agent.get_last_provider_call_metadata()
    assert open_metadata is not None
    assert open_metadata["retryable"] is False
    assert open_metadata["attempts_used"] == 0
    assert open_metadata["attempt_history"] == []
    assert open_metadata["circuit_breaker_open"] is True
    assert open_metadata["circuit_breaker_failure_streak"] == 2
    assert provider.calls == [("system", "message"), ("system", "message")]


def test_chat_resets_circuit_breaker_after_successful_call(monkeypatch):
    class RecoveringProvider(DummyProvider):
        def __init__(self):
            super().__init__(response="ok")
            self.attempts = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            self.attempts += 1
            if self.attempts == 1:
                raise ProviderTransientError("provider temporarily unavailable")
            return "ok"

    provider = RecoveringProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 1
    agent.config.provider_circuit_breaker_threshold = 2
    agent.config.provider_circuit_breaker_cooldown_seconds = 10.0

    timestamps = iter([100.0, 100.0, 100.0, 100.0, 100.0, 111.0, 111.0, 111.0, 111.0, 111.0])
    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: next(timestamps, 111.0))

    with pytest.raises(AgentExecutionError, match="Dummy: provider temporarily unavailable"):
        agent.chat("system", "message")

    result = agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert result == "ok"
    assert metadata is not None
    assert metadata["success"] is True
    assert metadata["circuit_breaker_open"] is False
    assert metadata["circuit_breaker_failure_streak"] == 0
    assert metadata["circuit_breaker_remaining_seconds"] == 0.0


@pytest.mark.parametrize("agent_class", [CodeDummyAgent, PytestDummyAgent])
def test_execute_extracts_code_from_markdown_fences_for_code_artifacts(agent_class):
    provider = DummyProvider(response="Implementation draft\n```python\nprint('hello')\n```\nExtra explanation")
    agent = agent_class(provider)
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "print('hello')"
    assert result.summary == "print('hello')"
    assert result.artifacts[0].content == "print('hello')"


@pytest.mark.parametrize("agent_class", [CodeDummyAgent, PytestDummyAgent])
def test_execute_strips_leading_prose_from_code_artifacts_without_fences(agent_class):
    provider = DummyProvider(response="Here is the implementation you requested:\n\nimport logging\n\ndef hello() -> str:\n    return 'hi'")
    agent = agent_class(provider)
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "import logging\n\ndef hello() -> str:\n    return 'hi'"
    assert result.summary == "import logging"
    assert result.artifacts[0].content == "import logging\n\ndef hello() -> str:\n    return 'hi'"