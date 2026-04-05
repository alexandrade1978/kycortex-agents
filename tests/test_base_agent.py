from typing import Any, cast

import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.providers import factory as provider_factory
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactRecord, ArtifactType, DecisionRecord


class DummyAgent(BaseAgent):
    def __init__(self, provider, config=None):
        super().__init__("Dummy", "Testing", config or KYCortexConfig(output_dir="./output_test"))
        self._provider = provider
        self.events = []

    def run(self, task_description: str, context: dict) -> str | AgentOutput:
        return self.chat("system", task_description)

    def before_execute(self, agent_input: AgentInput) -> None:
        self.events.append(("before", agent_input.task_id))

    def after_execute(self, agent_input: AgentInput, output: AgentOutput) -> AgentOutput:
        output = super().after_execute(agent_input, output)
        output.metadata["hook"] = "after"
        self.events.append(("after", agent_input.task_id))
        return output

class DummyProvider(BaseLLMProvider):
    def __init__(self, response=None, error=None, metadata=None, health_response=None, health_error=None):
        self.response = response
        self.error = error
        self.metadata = metadata
        self.health_response = health_response
        self.health_error = health_error
        self.calls = []
        self.health_calls = 0

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response

    def get_last_call_metadata(self) -> dict[str, Any] | None:
        return self.metadata

    def health_check(self) -> dict[str, Any]:
        self.health_calls += 1
        if self.health_error is not None:
            raise self.health_error
        if self.health_response is not None:
            return self.health_response
        return super().health_check()


class CodeDummyAgent(DummyAgent):
    output_artifact_type = ArtifactType.CODE


class PytestDummyAgent(DummyAgent):
    output_artifact_type = ArtifactType.TEST


class DirectBaseRunAgent(DummyAgent):
    def run(self, task_description: str, context: dict) -> str | AgentOutput:
        return BaseAgent.run(self, task_description, context)


def test_chat_returns_response_content():
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)

    result = agent.chat("system", "message")

    assert result == "ok"
    assert provider.calls == [("system", "message")]
    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["provider_call_budget_limited"] is False
    assert metadata["provider_call_budget_exhausted"] is False
    assert metadata["provider_call_budget_limited_providers"] == []
    assert metadata["provider_call_budget_exhausted_providers"] == []
    assert "provider_call_count" not in metadata
    assert "provider_remaining_calls" not in metadata
    assert "provider_timeout_seconds" not in metadata
    assert metadata["provider_timeout_provider_count"] == 1
    assert "provider_timeout_seconds_by_provider" not in metadata
    assert metadata["provider_elapsed_budget_limited"] is False
    assert metadata["provider_elapsed_budget_exhausted"] is False
    assert "provider_elapsed_seconds" not in metadata
    assert "provider_max_elapsed_seconds_per_call" not in metadata
    assert "provider_remaining_elapsed_seconds" not in metadata
    assert metadata["provider_cancellation_requested"] is False
    assert metadata["provider_cancellation_reason"] is None
    assert "has_provider_cancellation_reason" not in metadata
    assert "circuit_breaker_threshold" not in metadata
    assert "circuit_breaker_cooldown_seconds" not in metadata
    assert metadata["provider_health"]["openai"]["status"] == "healthy"
    assert metadata["provider_health"]["openai"]["last_outcome"] == "success"
    assert "transient_failure_streak" not in metadata["provider_health"]["openai"]
    assert "last_success_age_seconds" not in metadata["provider_health"]["openai"]
    assert "last_failure_age_seconds" not in metadata["provider_health"]["openai"]
    assert "last_health_check_age_seconds" not in metadata["provider_health"]["openai"]
    assert metadata["provider_health"]["openai"]["last_health_check"]["status"] == "ready"
    assert metadata["provider_health"]["openai"]["last_health_check"]["active_check"] is False
    assert "cooldown_remaining_seconds" not in metadata["provider_health"]["openai"]["last_health_check"]


def test_chat_supports_provider_without_health_check_method():
    class LegacyProvider:
        def __init__(self):
            self.calls = []

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            return "ok"

        def get_last_call_metadata(self):
            return None

    provider = LegacyProvider()
    agent = DummyAgent(provider)

    result = agent.chat("system", "message")

    assert result == "ok"
    assert provider.calls == [("system", "message")]
    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["provider_health"]["openai"]["last_health_check"]["status"] == "ready"
    assert metadata["provider_health"]["openai"]["last_health_check"]["active_check"] is False


def test_chat_raises_when_provider_execution_plan_is_empty():
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)
    agent._provider_execution_plan = lambda: []

    with pytest.raises(AgentExecutionError, match="Dummy failed to call the model provider"):
        agent.chat("system", "message")

    assert provider.calls == []


def test_chat_raises_when_provider_attempts_are_zero_after_runtime_override():
    agent = DummyAgent(DummyProvider(response="ok"))
    agent.config.provider_max_attempts = 0

    with pytest.raises(AgentExecutionError, match="Dummy failed to call the model provider"):
        agent.chat("system", "message")

    assert isinstance(agent._provider, DummyProvider)
    assert agent._provider.calls == []


def test_get_provider_for_reuses_cached_primary_provider(monkeypatch):
    created_providers: list[DummyProvider] = []
    agent = DummyAgent(None)

    def create_primary_provider(runtime_config: KYCortexConfig):
        provider = DummyProvider(response=f"provider-for-{runtime_config.llm_provider}")
        created_providers.append(provider)
        return provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_primary_provider)

    first = agent._get_provider_for("openai", "gpt-4o")
    agent._provider = None
    second = agent._get_provider_for("openai", "gpt-4o")

    assert first is second
    assert len(created_providers) == 1


def test_get_provider_delegates_to_primary_provider_resolution(monkeypatch):
    agent = DummyAgent(DummyProvider(response="ok"))
    captured: list[tuple[str, str]] = []

    def fake_get_provider_for(provider_name: str, model_name: str):
        captured.append((provider_name, model_name))
        return agent._provider

    monkeypatch.setattr(agent, "_get_provider_for", fake_get_provider_for)

    assert agent._get_provider() is agent._provider
    assert captured == [(agent.config.llm_provider, agent.config.llm_model)]


def test_get_provider_for_reuses_cached_fallback_provider(monkeypatch):
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
    )
    agent = DummyAgent(DummyProvider(response="primary"), config)
    cached_fallback = DummyProvider(response="fallback")
    agent._provider_cache[("anthropic", "claude-3-5-sonnet")] = cached_fallback

    def unexpected_create_provider(runtime_config: KYCortexConfig):
        raise AssertionError("create_provider should not be called when fallback provider is cached")

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", unexpected_create_provider)

    resolved = agent._get_provider_for("anthropic", "claude-3-5-sonnet")

    assert resolved is cached_fallback


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
    assert metadata["has_error_type"] is True
    assert "error_type" not in metadata
    assert metadata["has_error_message"] is True
    assert "error_message" not in metadata
    assert metadata["duration_ms"] >= 0
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": False,
            "has_error_type": True,
            "has_error_message": True,
            "backoff_seconds": 0.0,
        }
    ]


def test_chat_redacts_sensitive_values_from_failed_provider_call_metadata():
    provider = DummyProvider(error=RuntimeError("request failed api_key=sk-secret-123456 Authorization: Bearer sk-ant-secret-987654"))
    agent = DummyAgent(provider)

    with pytest.raises(AgentExecutionError):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()

    assert metadata is not None
    assert metadata["has_error_message"] is True
    assert "error_message" not in metadata
    assert "sk-secret-123456" not in str(metadata)
    assert "sk-ant-secret-987654" not in str(metadata)
    assert metadata["attempt_history"][0]["has_error_type"] is True
    assert "error_type" not in metadata["attempt_history"][0]
    assert metadata["attempt_history"][0]["has_error_message"] is True
    assert "error_message" not in metadata["attempt_history"][0]


def test_chat_sanitizes_prompt_input_before_provider_generate():
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)

    result = agent.chat(
        "system api_key=sk-secret-123456\x00",
        "message Authorization: Bearer sk-ant-secret-987654",
    )

    assert result == "ok"
    assert provider.calls == [
        ("system api_key=[REDACTED]", "message Authorization: Bearer [REDACTED]"),
    ]
    assert "\x00" not in provider.calls[0][0]


def test_execute_redacts_sensitive_provider_metadata_before_exposing_provider_call():
    provider = DummyProvider(
        response="ok",
        metadata={
            "api_key": "sk-secret-123456",
            "nested": {"authorization": "Bearer sk-ant-secret-987654"},
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        },
    )
    agent = DummyAgent(provider)

    result = agent.execute(
        AgentInput(
            task_id="task-1",
            task_title="Task",
            task_description="message",
            project_name="Demo",
            project_goal="Build demo",
            context={},
        )
    )

    provider_call = result.metadata["provider_call"]

    assert provider_call["api_key"] == "[REDACTED]"
    assert provider_call["nested"]["authorization"] == "[REDACTED]"
    assert provider_call["usage"]["total_tokens"] == 5


def test_execute_redacts_sensitive_values_from_live_agent_output():
    class StructuredSecretAgent(DummyAgent):
        def run(self, task_description: str, context: dict) -> AgentOutput:
            return AgentOutput(
                summary="api_key=sk-secret-123456 summary",
                raw_content="Authorization: Bearer sk-ant-secret-987654",
                artifacts=[
                    ArtifactRecord(
                        name="secret_artifact",
                        artifact_type=ArtifactType.TEXT,
                        path="artifacts/sk-secret-123456.txt",
                        content="password=hunter2",
                        metadata={"session_token": "session-secret-token"},
                    )
                ],
                decisions=[
                    DecisionRecord(
                        topic="Authorization: Bearer sk-ant-secret-987654",
                        decision="Keep api_key=sk-secret-123456 hidden",
                        rationale="password=hunter2",
                        metadata={"refresh_token": "refresh-secret-token"},
                    )
                ],
                metadata={"api_key": "sk-secret-123456", "nested": {"authorization": "Bearer sk-ant-secret-987654"}},
            )

    agent = StructuredSecretAgent(DummyProvider(response="ok"))

    result = agent.execute(
        AgentInput(
            task_id="task-1",
            task_title="Task",
            task_description="message",
            project_name="Demo",
            project_goal="Build demo",
            context={},
        )
    )

    assert "sk-secret-123456" not in result.summary
    assert "sk-ant-secret-987654" not in result.raw_content
    assert result.metadata["api_key"] == "[REDACTED]"
    assert result.metadata["nested"]["authorization"] == "[REDACTED]"
    assert result.artifacts[0].path == "artifacts/[REDACTED].txt"
    assert result.artifacts[0].content == "password=[REDACTED]"
    assert result.artifacts[0].metadata["session_token"] == "[REDACTED]"
    assert result.decisions[0].topic == "Authorization: Bearer [REDACTED]"
    assert result.decisions[0].decision == "Keep api_key=[REDACTED] hidden"
    assert result.decisions[0].rationale == "password=[REDACTED]"
    assert result.decisions[0].metadata["refresh_token"] == "[REDACTED]"


def test_after_execute_redacts_default_artifact_content_when_live_output_contains_secrets():
    agent = DummyAgent(DummyProvider(response="ok"))
    agent._last_provider_call_metadata = None
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )
    output = AgentOutput(
        summary="summary api_key=sk-secret-123456",
        raw_content="Authorization: Bearer sk-ant-secret-987654",
        artifacts=[],
        decisions=[],
        metadata={},
    )

    finalized = BaseAgent.after_execute(agent, agent_input, output)

    assert finalized.raw_content == "Authorization: Bearer [REDACTED]"
    assert finalized.summary == "summary api_key=[REDACTED]"
    assert finalized.artifacts[0].content == "Authorization: Bearer [REDACTED]"


def test_execute_reapplies_public_redaction_when_after_execute_bypasses_super():
    class UnsafeAfterExecuteAgent(DummyAgent):
        def run(self, task_description: str, context: dict) -> AgentOutput:
            return AgentOutput(
                summary="api_key=sk-secret-123456 summary",
                raw_content="Authorization: Bearer sk-ant-secret-987654",
                artifacts=[
                    ArtifactRecord(
                        name="secret_artifact",
                        artifact_type=ArtifactType.TEXT,
                        path="artifacts/secret.txt",
                        content="password=hunter2",
                    )
                ],
                metadata={"api_key": "sk-secret-123456"},
            )

        def after_execute(self, agent_input: AgentInput, output: AgentOutput) -> AgentOutput:
            output.metadata["unsafe_hook"] = "Authorization: Bearer sk-ant-secret-987654"
            return output

    agent = UnsafeAfterExecuteAgent(DummyProvider(response="ok"))

    result = agent.execute(
        AgentInput(
            task_id="task-1",
            task_title="Task",
            task_description="message",
            project_name="Demo",
            project_goal="Build demo",
            context={},
        )
    )

    assert result.summary == "api_key=[REDACTED] summary"
    assert result.raw_content == "Authorization: Bearer [REDACTED]"
    assert result.metadata["api_key"] == "[REDACTED]"
    assert result.metadata["unsafe_hook"] == "Authorization: Bearer [REDACTED]"
    assert result.artifacts[0].content == "password=[REDACTED]"


def test_execute_preserves_internal_unredacted_output_when_after_execute_bypasses_super():
    class UnsafeAfterExecuteAgent(DummyAgent):
        def run(self, task_description: str, context: dict) -> AgentOutput:
            return AgentOutput(
                summary="api_key=sk-secret-123456 summary",
                raw_content="Authorization: Bearer sk-ant-secret-987654",
                metadata={"api_key": "sk-secret-123456"},
            )

        def after_execute(self, agent_input: AgentInput, output: AgentOutput) -> AgentOutput:
            return output

    agent = UnsafeAfterExecuteAgent(DummyProvider(response="ok"))

    result = agent.execute(
        AgentInput(
            task_id="task-1",
            task_title="Task",
            task_description="message",
            project_name="Demo",
            project_goal="Build demo",
            context={},
        )
    )
    internal_output = agent._consume_last_unredacted_output()

    assert result.raw_content == "Authorization: Bearer [REDACTED]"
    assert internal_output is not None
    assert internal_output.raw_content == "Authorization: Bearer sk-ant-secret-987654"
    assert internal_output.metadata["api_key"] == "sk-secret-123456"
    assert agent._consume_last_unredacted_output() is None


def test_execute_sanitizes_task_description_before_provider_generate():
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)

    result = agent.execute(
        AgentInput(
            task_id="task-1",
            task_title="Task",
            task_description="message api_key=sk-secret-123456",
            project_name="Demo",
            project_goal="Build demo",
            context={},
        )
    )

    assert result.raw_content == "ok"
    assert provider.calls == [("system", "message api_key=[REDACTED]")]


def test_chat_redacts_sensitive_values_from_provider_health_metadata():
    provider = DummyProvider(
        response="ok",
        health_error=ProviderTransientError("Authorization: Bearer sk-ant-secret-987654"),
    )
    agent = DummyAgent(provider)

    with pytest.raises(ProviderTransientError, match=r"\[REDACTED\]"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()

    assert metadata is not None
    provider_health = metadata["provider_health"]["openai"]
    assert provider_health["has_last_error_type"] is True
    assert "last_error_type" not in provider_health
    assert provider_health["has_last_error_message"] is True
    assert "last_error_message" not in provider_health
    assert "transient_failure_streak" not in provider_health
    assert "last_success_age_seconds" not in provider_health
    assert "last_failure_age_seconds" not in provider_health
    assert "last_health_check_age_seconds" not in provider_health
    assert provider_health["last_health_check"]["has_error_type"] is True
    assert "error_type" not in provider_health["last_health_check"]
    assert provider_health["last_health_check"]["has_error_message"] is True
    assert "error_message" not in provider_health["last_health_check"]
    assert "cooldown_remaining_seconds" not in provider_health["last_health_check"]


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
            "has_error_type": True,
            "has_error_message": True,
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

    with pytest.raises(ProviderTransientError, match="Dummy: provider temporarily unavailable") as exc_info:
        agent.chat("system", "message")

    assert exc_info.type is ProviderTransientError
    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is True
    assert metadata["attempts_used"] == 2
    assert metadata["max_attempts"] == 2
    assert metadata["has_error_type"] is True
    assert "error_type" not in metadata
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "has_error_type": True,
            "has_error_message": True,
            "uncapped_backoff_seconds": 0.0,
            "base_backoff_seconds": 0.0,
            "jitter_seconds": 0.0,
            "backoff_seconds": 0.0,
        },
        {
            "attempt": 2,
            "success": False,
            "retryable": True,
            "has_error_type": True,
            "has_error_message": True,
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

    with pytest.raises(AgentExecutionError, match="Dummy: provider call budget exhausted"):
        agent.chat("system", "second-message")

    metadata = agent.get_last_provider_call_metadata()
    assert first_result == "ok"
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["attempts_used"] == 0
    assert metadata["provider_call_budget_limited"] is True
    assert metadata["provider_call_budget_exhausted"] is True
    assert metadata["provider_call_budget_limited_providers"] == []
    assert metadata["provider_call_budget_exhausted_providers"] == []
    assert "provider_call_count" not in metadata
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

    with pytest.raises(AgentExecutionError, match="Dummy: provider call budget exhausted"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["attempts_used"] == 1
    assert metadata["provider_call_budget_limited"] is True
    assert metadata["provider_call_budget_exhausted"] is True
    assert metadata["provider_call_budget_limited_providers"] == []
    assert metadata["provider_call_budget_exhausted_providers"] == []
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "has_error_type": True,
            "has_error_message": True,
            "uncapped_backoff_seconds": 0.0,
            "base_backoff_seconds": 0.0,
            "jitter_seconds": 0.0,
            "backoff_seconds": 0.0,
        }
    ]


def test_chat_fails_fast_when_provider_specific_call_budget_is_exhausted():
    provider = DummyProvider(response="ok")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_max_calls_per_provider={"openai": 1},
    )
    agent = DummyAgent(provider, config)

    first_result = agent.chat("system", "message")

    with pytest.raises(AgentExecutionError, match="Dummy: provider call budget exhausted for openai"):
        agent.chat("system", "second-message")

    metadata = agent.get_last_provider_call_metadata()
    assert first_result == "ok"
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["attempts_used"] == 0
    assert metadata["provider_call_budget_limited"] is True
    assert metadata["provider_call_budget_exhausted"] is False
    assert metadata["provider_call_budget_limited_providers"] == ["openai"]
    assert metadata["provider_call_budget_exhausted_providers"] == ["openai"]
    assert "provider_call_counts_by_provider" not in metadata
    assert metadata["attempt_history"] == []
    assert provider.calls == [("system", "message")]


def test_chat_provider_specific_budget_blocks_additional_retry_attempts_after_first_failure(monkeypatch):
    class AlwaysTransientProvider(DummyProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

    provider = AlwaysTransientProvider()
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_max_attempts=2,
        provider_retry_backoff_seconds=0.0,
        provider_max_calls_per_provider={"openai": 1},
    )
    agent = DummyAgent(provider, config)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)

    with pytest.raises(AgentExecutionError, match="Dummy: provider call budget exhausted for openai"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["attempts_used"] == 1
    assert metadata["provider_call_budget_limited"] is True
    assert metadata["provider_call_budget_exhausted"] is False
    assert metadata["provider_call_budget_limited_providers"] == ["openai"]
    assert metadata["provider_call_budget_exhausted_providers"] == ["openai"]
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "has_error_type": True,
            "has_error_message": True,
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
    timestamps = iter([100.0, 100.0, 100.0, 100.0, 100.2, 100.6])
    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: next(timestamps))
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)

    with pytest.raises(AgentExecutionError, match="Dummy: provider elapsed budget exhausted after 0.6 seconds"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["attempts_used"] == 1
    assert metadata["provider_elapsed_budget_limited"] is True
    assert metadata["provider_elapsed_budget_exhausted"] is True
    assert "provider_elapsed_seconds" not in metadata
    assert "provider_max_elapsed_seconds_per_call" not in metadata
    assert "provider_remaining_elapsed_seconds" not in metadata
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "has_error_type": True,
            "has_error_message": True,
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
    assert metadata["provider_elapsed_budget_limited"] is True
    assert metadata["provider_elapsed_budget_exhausted"] is False
    assert "provider_elapsed_seconds" not in metadata
    assert "provider_max_elapsed_seconds_per_call" not in metadata
    assert "provider_remaining_elapsed_seconds" not in metadata
    assert sleep_calls == []


def test_chat_fails_before_first_attempt_when_elapsed_budget_is_already_exhausted(monkeypatch):
    provider = DummyProvider(response="ok")
    agent = DummyAgent(provider)
    agent.config.provider_max_elapsed_seconds_per_call = 0.1
    timestamps = iter([100.0, 100.0, 100.2])

    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: next(timestamps))
    monkeypatch.setattr(agent, "_probe_provider_health", lambda *args, **kwargs: None)

    with pytest.raises(AgentExecutionError, match="Dummy: provider elapsed budget exhausted after 0.2 seconds"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["attempts_used"] == 0
    assert metadata["attempt_history"] == []
    assert metadata["provider_call_budget_limited"] is False
    assert metadata["provider_call_budget_exhausted"] is False
    assert metadata["provider_elapsed_budget_limited"] is True
    assert metadata["provider_elapsed_budget_exhausted"] is True
    assert "provider_elapsed_seconds" not in metadata
    assert "provider_max_elapsed_seconds_per_call" not in metadata
    assert "provider_remaining_elapsed_seconds" not in metadata
    assert provider.calls == []


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
    assert metadata["has_provider_cancellation_reason"] is True
    assert "provider_cancellation_reason" not in metadata
    assert provider.calls == []


def test_probe_provider_health_raises_for_cached_non_retryable_snapshot(monkeypatch):
    agent = DummyAgent(DummyProvider(response="ok"))
    cached_snapshot = {
        "provider": "openai",
        "model": "gpt-4o",
        "status": "failing",
        "active_check": True,
        "retryable": False,
        "error_type": "AgentExecutionError",
        "error_message": "configured model unavailable",
    }

    monkeypatch.setattr(
        "kycortex_agents.agents.base_agent._maybe_get_cached_health_snapshot",
        lambda runtime_config, current_time: dict(cached_snapshot),
    )

    assert agent._provider is not None
    with pytest.raises(AgentExecutionError, match="configured model unavailable"):
        agent._probe_provider_health("openai", "gpt-4o", agent._provider)

    assert agent._provider_last_health_checks["openai"]["status"] == "failing"


def test_probe_provider_health_fills_missing_snapshot_defaults():
    provider = DummyProvider(
        response="ok",
        health_response={
            "provider": None,
            "model": None,
            "status": None,
            "active_check": None,
            "retryable": None,
        },
    )
    agent = DummyAgent(provider)

    snapshot = agent._probe_provider_health("openai", "gpt-4o", provider)

    assert snapshot["provider"] == "openai"
    assert snapshot["model"] == "gpt-4o"
    assert snapshot["status"] == "ready"
    assert snapshot["active_check"] is False
    assert snapshot["retryable"] is False


def test_probe_provider_health_raises_transient_for_retryable_degraded_snapshot():
    provider = DummyProvider(
        response="ok",
        health_response={
            "provider": "openai",
            "model": "gpt-4o",
            "status": "degraded",
            "active_check": True,
            "retryable": True,
            "error_message": "temporary outage",
        },
    )
    agent = DummyAgent(provider)

    with pytest.raises(ProviderTransientError, match="temporary outage"):
        agent._probe_provider_health("openai", "gpt-4o", provider)

    assert agent._provider_last_health_checks["openai"]["status"] == "degraded"


def test_clear_provider_cancellation_resets_requested_state():
    agent = DummyAgent(DummyProvider(response="ok"))
    agent.request_provider_cancellation("operator requested stop")

    agent.clear_provider_cancellation()

    assert agent._provider_cancellation_requested is False
    assert agent._provider_cancellation_reason is None


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
    assert metadata["has_provider_cancellation_reason"] is True
    assert "provider_cancellation_reason" not in metadata
    assert metadata["attempt_history"] == [
        {
            "attempt": 1,
            "success": False,
            "retryable": True,
            "has_error_type": True,
            "has_error_message": True,
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

    with pytest.raises(ProviderTransientError, match="Dummy: provider temporarily unavailable") as first_exc_info:
        agent.chat("system", "message")

    assert first_exc_info.type is ProviderTransientError
    first_metadata = agent.get_last_provider_call_metadata()
    assert first_metadata is not None
    assert first_metadata["circuit_breaker_open"] is False
    assert "circuit_breaker_failure_streak" not in first_metadata
    assert "circuit_breaker_remaining_seconds" not in first_metadata

    with pytest.raises(ProviderTransientError, match="Dummy: provider temporarily unavailable") as second_exc_info:
        agent.chat("system", "message")

    assert second_exc_info.type is ProviderTransientError
    second_metadata = agent.get_last_provider_call_metadata()
    assert second_metadata is not None
    assert second_metadata["circuit_breaker_open"] is True
    assert "circuit_breaker_failure_streak" not in second_metadata
    assert "circuit_breaker_remaining_seconds" not in second_metadata
    assert second_metadata["provider_health"]["openai"]["status"] == "open_circuit"
    assert second_metadata["provider_health"]["openai"]["last_outcome"] == "failure"
    assert second_metadata["provider_health"]["openai"]["last_failure_retryable"] is True

    with pytest.raises(AgentExecutionError, match="Dummy: provider circuit breaker is open for 10 more seconds"):
        agent.chat("system", "message")

    open_metadata = agent.get_last_provider_call_metadata()
    assert open_metadata is not None
    assert open_metadata["retryable"] is False
    assert open_metadata["attempts_used"] == 0
    assert open_metadata["attempt_history"] == []
    assert open_metadata["circuit_breaker_open"] is True
    assert "circuit_breaker_failure_streak" not in open_metadata
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

    with pytest.raises(ProviderTransientError, match="Dummy: provider temporarily unavailable") as exc_info:
        agent.chat("system", "message")

    assert exc_info.type is ProviderTransientError
    result = agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert result == "ok"
    assert metadata is not None
    assert metadata["success"] is True
    assert metadata["circuit_breaker_open"] is False
    assert "circuit_breaker_failure_streak" not in metadata
    assert "circuit_breaker_remaining_seconds" not in metadata
    assert metadata["provider_health"]["openai"]["status"] == "healthy"
    assert metadata["provider_health"]["openai"]["last_outcome"] == "success"


def test_chat_falls_back_when_primary_provider_circuit_is_open(monkeypatch):
    primary_provider = DummyProvider(response="PRIMARY RESULT")
    fallback_provider = DummyProvider(response="FALLBACK RESULT")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        provider_circuit_breaker_threshold=1,
        provider_circuit_breaker_cooldown_seconds=10.0,
    )
    agent = DummyAgent(primary_provider, config)
    agent._provider_circuit_open_untils["openai"] = 110.0

    def create_fallback_provider(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_fallback_provider)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: 100.0)

    result = agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert result == "FALLBACK RESULT"
    assert metadata is not None
    assert metadata["provider"] == "anthropic"
    assert metadata["fallback_used"] is True
    assert "fallback_count" not in metadata
    assert metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "skipped_open_circuit",
        }
    ]
    assert primary_provider.calls == []
    assert fallback_provider.calls == [("system", "message")]


def test_chat_reopens_circuit_breaker_after_recovery_and_new_transient_streak(monkeypatch):
    class FlappingProvider(DummyProvider):
        def __init__(self):
            super().__init__()
            self.outcomes = iter(["fail", "fail", "ok", "fail", "fail"])

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            if next(self.outcomes) == "fail":
                raise ProviderTransientError("provider temporarily unavailable")
            return "ok"

    provider = FlappingProvider()
    agent = DummyAgent(provider)
    agent.config.provider_max_attempts = 1
    agent.config.provider_circuit_breaker_threshold = 2
    agent.config.provider_circuit_breaker_cooldown_seconds = 10.0
    current_time = {"value": 100.0}
    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: current_time["value"])

    with pytest.raises(ProviderTransientError, match="Dummy: provider temporarily unavailable"):
        agent.chat("system", "message-1")

    first_failure_metadata = agent.get_last_provider_call_metadata()
    assert first_failure_metadata is not None
    assert first_failure_metadata["circuit_breaker_open"] is False
    assert "circuit_breaker_failure_streak" not in first_failure_metadata

    with pytest.raises(ProviderTransientError, match="Dummy: provider temporarily unavailable"):
        agent.chat("system", "message-2")

    second_failure_metadata = agent.get_last_provider_call_metadata()
    assert second_failure_metadata is not None
    assert second_failure_metadata["circuit_breaker_open"] is True
    assert "circuit_breaker_failure_streak" not in second_failure_metadata
    assert "circuit_breaker_remaining_seconds" not in second_failure_metadata

    with pytest.raises(AgentExecutionError, match="Dummy: provider circuit breaker is open for 10 more seconds"):
        agent.chat("system", "message-3")

    first_open_metadata = agent.get_last_provider_call_metadata()
    assert first_open_metadata is not None
    assert first_open_metadata["attempts_used"] == 0
    assert first_open_metadata["attempt_history"] == []

    current_time["value"] = 111.0
    result = agent.chat("system", "message-4")

    recovery_metadata = agent.get_last_provider_call_metadata()
    assert result == "ok"
    assert recovery_metadata is not None
    assert recovery_metadata["success"] is True
    assert recovery_metadata["circuit_breaker_open"] is False
    assert "circuit_breaker_failure_streak" not in recovery_metadata

    current_time["value"] = 112.0
    with pytest.raises(ProviderTransientError, match="Dummy: provider temporarily unavailable"):
        agent.chat("system", "message-5")

    third_failure_metadata = agent.get_last_provider_call_metadata()
    assert third_failure_metadata is not None
    assert third_failure_metadata["circuit_breaker_open"] is False
    assert "circuit_breaker_failure_streak" not in third_failure_metadata

    with pytest.raises(ProviderTransientError, match="Dummy: provider temporarily unavailable"):
        agent.chat("system", "message-6")

    fourth_failure_metadata = agent.get_last_provider_call_metadata()
    assert fourth_failure_metadata is not None
    assert fourth_failure_metadata["circuit_breaker_open"] is True
    assert "circuit_breaker_failure_streak" not in fourth_failure_metadata
    assert "circuit_breaker_remaining_seconds" not in fourth_failure_metadata

    with pytest.raises(AgentExecutionError, match="Dummy: provider circuit breaker is open for 10 more seconds"):
        agent.chat("system", "message-7")

    second_open_metadata = agent.get_last_provider_call_metadata()
    assert second_open_metadata is not None
    assert second_open_metadata["attempts_used"] == 0
    assert second_open_metadata["attempt_history"] == []
    assert second_open_metadata["circuit_breaker_open"] is True
    assert "circuit_breaker_failure_streak" not in second_open_metadata
    assert second_open_metadata["provider_health"]["openai"]["status"] == "open_circuit"
    assert provider.calls == [
        ("system", "message-1"),
        ("system", "message-2"),
        ("system", "message-4"),
        ("system", "message-5"),
        ("system", "message-6"),
    ]


def test_chat_returns_to_primary_after_cooldown_and_can_fallback_again(monkeypatch):
    class FlappingPrimaryProvider(DummyProvider):
        def __init__(self):
            super().__init__()
            self.outcomes = iter(["fail", "ok", "fail"])

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            if next(self.outcomes) == "fail":
                raise ProviderTransientError("primary temporarily unavailable")
            return "PRIMARY RESULT"

    primary_provider = FlappingPrimaryProvider()
    fallback_provider = DummyProvider(response="FALLBACK RESULT")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_max_attempts=1,
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        provider_circuit_breaker_threshold=1,
        provider_circuit_breaker_cooldown_seconds=10.0,
    )
    agent = DummyAgent(primary_provider, config)
    current_time = {"value": 100.0}

    def create_provider_for_fallback(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_provider_for_fallback)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: current_time["value"])

    first_result = agent.chat("system", "message one")

    first_metadata = agent.get_last_provider_call_metadata()
    assert first_result == "FALLBACK RESULT"
    assert first_metadata is not None
    assert first_metadata["provider"] == "anthropic"
    assert first_metadata["fallback_used"] is True
    assert first_metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "failed_transient",
            "has_error_type": True,
            "has_error_message": True,
            "attempts_used": 1,
        }
    ]

    second_result = agent.chat("system", "message two")

    second_metadata = agent.get_last_provider_call_metadata()
    assert second_result == "FALLBACK RESULT"
    assert second_metadata is not None
    assert second_metadata["provider"] == "anthropic"
    assert second_metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "skipped_open_circuit",
        }
    ]

    current_time["value"] = 111.0
    third_result = agent.chat("system", "message three")

    third_metadata = agent.get_last_provider_call_metadata()
    assert third_result == "PRIMARY RESULT"
    assert third_metadata is not None
    assert third_metadata["provider"] == "openai"
    assert third_metadata["fallback_used"] is False
    assert third_metadata["circuit_breaker_open"] is False
    assert "circuit_breaker_failure_streak" not in third_metadata

    current_time["value"] = 112.0
    fourth_result = agent.chat("system", "message four")

    fourth_metadata = agent.get_last_provider_call_metadata()
    assert fourth_result == "FALLBACK RESULT"
    assert fourth_metadata is not None
    assert fourth_metadata["provider"] == "anthropic"
    assert fourth_metadata["fallback_used"] is True
    assert fourth_metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "failed_transient",
            "has_error_type": True,
            "has_error_message": True,
            "attempts_used": 1,
        }
    ]
    assert primary_provider.calls == [
        ("system", "message one"),
        ("system", "message three"),
        ("system", "message four"),
    ]
    assert fallback_provider.calls == [
        ("system", "message one"),
        ("system", "message two"),
        ("system", "message four"),
    ]


def test_chat_falls_back_when_primary_provider_specific_budget_is_exhausted(monkeypatch):
    primary_provider = DummyProvider(response="PRIMARY RESULT")
    fallback_provider = DummyProvider(response="FALLBACK RESULT")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        provider_max_calls_per_provider={"openai": 1},
    )
    agent = DummyAgent(primary_provider, config)

    def create_fallback_provider(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_fallback_provider)

    first_result = agent.chat("system", "message")
    second_result = agent.chat("system", "second-message")

    metadata = agent.get_last_provider_call_metadata()
    assert first_result == "PRIMARY RESULT"
    assert second_result == "FALLBACK RESULT"
    assert metadata is not None
    assert metadata["provider"] == "anthropic"
    assert metadata["fallback_used"] is True
    assert metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "skipped_call_budget_exhausted",
            "call_budget_exhausted": True,
        }
    ]
    assert metadata["provider_call_budget_limited"] is True
    assert metadata["provider_call_budget_exhausted"] is False
    assert metadata["provider_call_budget_limited_providers"] == ["openai"]
    assert metadata["provider_call_budget_exhausted_providers"] == ["openai"]
    assert primary_provider.calls == [("system", "message")]
    assert fallback_provider.calls == [("system", "second-message")]


def test_chat_falls_back_after_primary_provider_budget_is_exhausted_mid_retry(monkeypatch):
    class AlwaysTransientProvider(DummyProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

    primary_provider = AlwaysTransientProvider()
    fallback_provider = DummyProvider(response="FALLBACK RESULT")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_max_attempts=2,
        provider_retry_backoff_seconds=0.0,
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        provider_max_calls_per_provider={"openai": 1},
    )
    agent = DummyAgent(primary_provider, config)

    def create_provider_for_fallback(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_provider_for_fallback)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.random.uniform", lambda start, end: 0.0)

    result = agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert result == "FALLBACK RESULT"
    assert metadata is not None
    assert metadata["provider"] == "anthropic"
    assert metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "failed_call_budget_exhausted",
            "call_budget_exhausted": True,
            "attempts_used": 1,
        }
    ]
    assert metadata["provider_call_budget_limited"] is True
    assert metadata["provider_call_budget_exhausted"] is False
    assert metadata["provider_call_budget_limited_providers"] == ["openai"]
    assert metadata["provider_call_budget_exhausted_providers"] == ["openai"]
    assert metadata["attempt_history"][0]["retryable"] is True
    assert primary_provider.calls == [("system", "message")]
    assert fallback_provider.calls == [("system", "message")]


def test_chat_falls_back_after_primary_provider_transient_failure(monkeypatch):
    class AlwaysTransientProvider(DummyProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

    primary_provider = AlwaysTransientProvider()
    fallback_provider = DummyProvider(response="FALLBACK RESULT")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_max_attempts=1,
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
    )
    agent = DummyAgent(primary_provider, config)

    def create_provider_for_fallback(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_provider_for_fallback)

    result = agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert result == "FALLBACK RESULT"
    assert metadata is not None
    assert metadata["provider"] == "anthropic"
    assert metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "failed_transient",
            "has_error_type": True,
            "has_error_message": True,
            "attempts_used": 1,
        }
    ]


def test_chat_falls_back_after_transient_provider_health_check_failure(monkeypatch):
    primary_provider = DummyProvider(health_error=ProviderTransientError("provider health check timed out"))
    fallback_provider = DummyProvider(response="FALLBACK RESULT")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
    )
    agent = DummyAgent(primary_provider, config)

    def create_provider_for_fallback(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_provider_for_fallback)

    result = agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert result == "FALLBACK RESULT"
    assert metadata is not None
    assert metadata["provider"] == "anthropic"
    assert metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "failed_health_check",
            "has_error_type": True,
            "has_error_message": True,
            "retryable": True,
        }
    ]
    assert primary_provider.calls == []
    assert primary_provider.health_calls == 1
    assert fallback_provider.calls == [("system", "message")]
    assert metadata["provider_health"]["openai"]["status"] == "degraded"
    assert metadata["provider_health"]["openai"]["last_health_check"]["status"] == "degraded"
    assert metadata["provider_health"]["openai"]["last_health_check"]["retryable"] is True


def test_chat_reuses_cached_unhealthy_health_check_during_cooldown(monkeypatch):
    provider_factory._HEALTH_PROBE_CACHE.clear()
    primary_provider = DummyProvider(health_error=ProviderTransientError("provider health check timed out"))
    fallback_provider = DummyProvider(response="FALLBACK RESULT")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        provider_health_check_cooldown_seconds=30.0,
    )
    agent = DummyAgent(primary_provider, config)

    def create_provider_for_fallback(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_provider_for_fallback)

    first_result = agent.chat("system", "message one")
    second_result = agent.chat("system", "message two")

    metadata = agent.get_last_provider_call_metadata()
    assert first_result == "FALLBACK RESULT"
    assert second_result == "FALLBACK RESULT"
    assert primary_provider.calls == []
    assert primary_provider.health_calls == 1
    assert fallback_provider.calls == [("system", "message one"), ("system", "message two")]
    assert metadata is not None
    assert metadata["provider_health"]["openai"]["last_health_check"]["cooldown_cached"] is True
    assert "cooldown_remaining_seconds" not in metadata["provider_health"]["openai"]["last_health_check"]


def test_cached_unhealthy_health_check_can_open_circuit_breaker(monkeypatch):
    provider_factory._HEALTH_PROBE_CACHE.clear()
    primary_provider = DummyProvider(health_error=ProviderTransientError("provider health check timed out"))
    fallback_provider = DummyProvider(response="FALLBACK RESULT")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        provider_health_check_cooldown_seconds=30.0,
        provider_circuit_breaker_threshold=2,
        provider_circuit_breaker_cooldown_seconds=10.0,
    )
    agent = DummyAgent(primary_provider, config)

    def create_provider_for_fallback(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_provider_for_fallback)
    timestamps = iter([100.0] * 20 + [101.0] * 20 + [102.0] * 20)
    monkeypatch.setattr("kycortex_agents.agents.base_agent.perf_counter", lambda: next(timestamps, 102.0))

    first_result = agent.chat("system", "message one")
    first_metadata = agent.get_last_provider_call_metadata()
    second_result = agent.chat("system", "message two")
    second_metadata = agent.get_last_provider_call_metadata()
    third_result = agent.chat("system", "message three")
    third_metadata = agent.get_last_provider_call_metadata()

    assert first_result == "FALLBACK RESULT"
    assert second_result == "FALLBACK RESULT"
    assert third_result == "FALLBACK RESULT"
    assert first_metadata is not None
    assert first_metadata["provider_health"]["openai"]["status"] == "degraded"
    assert second_metadata is not None
    assert agent._provider_transient_failure_streaks["openai"] == 2
    assert agent._provider_circuit_open_untils["openai"] > 102.0
    assert second_metadata["provider_health"]["openai"]["status"] == "open_circuit"
    assert second_metadata["provider_health"]["openai"]["last_health_check"]["cooldown_cached"] is True
    assert third_metadata is not None
    assert third_metadata["provider_health"]["openai"]["status"] == "open_circuit"
    assert third_metadata["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "skipped_open_circuit",
        }
    ]
    assert primary_provider.calls == []
    assert primary_provider.health_calls == 1
    assert fallback_provider.calls == [
        ("system", "message one"),
        ("system", "message two"),
        ("system", "message three"),
    ]


def test_chat_fails_fast_when_last_provider_health_check_is_deterministically_unhealthy():
    provider = DummyProvider(health_error=AgentExecutionError("provider health check rejected backend"))
    agent = DummyAgent(provider)

    with pytest.raises(AgentExecutionError, match="Dummy: provider health check rejected backend"):
        agent.chat("system", "message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is False
    assert metadata["attempts_used"] == 0
    assert metadata["attempt_history"] == []
    assert metadata["has_error_type"] is True
    assert "error_type" not in metadata
    assert metadata["has_error_message"] is True
    assert "error_message" not in metadata
    assert metadata["provider_health"]["openai"]["status"] == "failing"
    assert metadata["provider_health"]["openai"]["last_health_check"]["status"] == "failing"
    assert provider.calls == []
    assert provider.health_calls == 1


def test_chat_fails_fast_when_last_provider_health_check_is_transient():
    provider = DummyProvider(health_error=ProviderTransientError("provider health check timed out"))
    agent = DummyAgent(provider)

    with pytest.raises(ProviderTransientError, match="Dummy: provider health check timed out") as exc_info:
        agent.chat("system", "message")

    assert exc_info.type is ProviderTransientError
    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["success"] is False
    assert metadata["retryable"] is True
    assert metadata["attempts_used"] == 0
    assert metadata["attempt_history"] == []
    assert metadata["has_error_type"] is True
    assert "error_type" not in metadata
    assert metadata["has_error_message"] is True
    assert "error_message" not in metadata
    assert metadata["provider_health"]["openai"]["status"] == "degraded"
    assert metadata["provider_health"]["openai"]["last_health_check"]["status"] == "degraded"
    assert provider.calls == []
    assert provider.health_calls == 1


def test_chat_surfaces_provider_specific_timeout_metadata_for_fallback(monkeypatch):
    primary_provider = DummyProvider(response="PRIMARY RESULT")
    fallback_provider = DummyProvider(response="FALLBACK RESULT")
    config = KYCortexConfig(
        output_dir="./output_test",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
        provider_max_calls_per_provider={"openai": 1},
        timeout_seconds=60.0,
        provider_timeout_seconds={"openai": 10.0, "anthropic": 25.0},
    )
    agent = DummyAgent(primary_provider, config)

    def create_fallback_provider(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        assert runtime_config.timeout_seconds == 25.0
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_fallback_provider)

    agent.chat("system", "message")
    agent.chat("system", "second-message")

    metadata = agent.get_last_provider_call_metadata()
    assert metadata is not None
    assert metadata["provider"] == "anthropic"
    assert "provider_timeout_seconds" not in metadata
    assert metadata["provider_timeout_provider_count"] == 2
    assert "provider_timeout_seconds_by_provider" not in metadata


def test_execute_raises_assertion_when_error_hook_does_not_raise():
    class NonRaisingErrorHookAgent(DummyAgent):
        def run(self, task_description: str, context: dict) -> str:
            raise RuntimeError("boom")

        def on_execution_error(self, agent_input: AgentInput, exc: Exception) -> None:
            self.events.append(("error", str(exc)))

    agent = NonRaisingErrorHookAgent(DummyProvider(response="ok"))
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    with pytest.raises(AssertionError, match="on_execution_error must raise an exception"):
        agent.execute(agent_input)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("task_id", "   ", "task_id must not be empty"),
        ("task_title", "   ", "task_title must not be empty"),
        ("task_description", "   ", "task_description must not be empty"),
        ("project_name", "   ", "project_name must not be empty"),
    ],
)
def test_validate_input_rejects_blank_required_fields(field, value, message):
    agent = DummyAgent(DummyProvider(response="ok"))
    payload = {
        "task_id": "task-1",
        "task_title": "Task",
        "task_description": "message",
        "project_name": "Demo",
        "project_goal": "Build demo",
        "context": {},
    }
    payload[field] = value

    with pytest.raises(AgentExecutionError, match=message):
        agent.validate_input(AgentInput(**payload))


def test_validate_input_rejects_non_dict_context_and_missing_required_keys():
    class RequiresArchitectureAgent(DummyAgent):
        required_context_keys = ("architecture",)

    agent = RequiresArchitectureAgent(DummyProvider(response="ok"))

    with pytest.raises(AgentExecutionError, match="context must be a dictionary"):
        agent.validate_input(
            AgentInput(
                task_id="task-1",
                task_title="Task",
                task_description="message",
                project_name="Demo",
                project_goal="Build demo",
                context=cast(dict[str, Any], "not-a-dict"),
            )
        )

    with pytest.raises(AgentExecutionError, match="required context key 'architecture' is missing"):
        agent.validate_input(
            AgentInput(
                task_id="task-1",
                task_title="Task",
                task_description="message",
                project_name="Demo",
                project_goal="Build demo",
                context={},
            )
        )

    with pytest.raises(AgentExecutionError, match="required context key 'architecture' must not be empty"):
        agent.validate_input(
            AgentInput(
                task_id="task-1",
                task_title="Task",
                task_description="message",
                project_name="Demo",
                project_goal="Build demo",
                context={"architecture": "   "},
            )
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda output: setattr(output, "raw_content", "   "), "agent output raw_content must not be empty"),
        (lambda output: setattr(output, "summary", "   "), "agent output summary must not be empty"),
        (lambda output: setattr(output, "artifacts", None), "agent output artifacts must be a list"),
        (lambda output: setattr(output, "decisions", None), "agent output decisions must be a list"),
        (lambda output: setattr(output, "metadata", None), "agent output metadata must be a dictionary"),
    ],
)
def test_validate_output_rejects_invalid_public_contract_fields(mutator, message):
    agent = DummyAgent(DummyProvider(response="ok"))
    output = AgentOutput(summary="summary", raw_content="content", artifacts=[], decisions=[], metadata={})
    mutator(output)

    with pytest.raises(AgentExecutionError, match=message):
        agent.validate_output(output)


def test_before_execute_returns_none_and_after_execute_adds_default_artifact_without_provider_metadata():
    agent = DummyAgent(DummyProvider(response="ok"))
    agent._last_provider_call_metadata = None
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )
    output = AgentOutput(summary="summary", raw_content="content", artifacts=[], decisions=[], metadata={})

    assert agent.before_execute(agent_input) is None

    finalized = BaseAgent.after_execute(agent, agent_input, output)

    assert finalized.artifacts[0].name == "task-1_output"
    assert "provider_call" not in finalized.metadata


def test_on_execution_error_reraises_agent_execution_errors():
    agent = DummyAgent(DummyProvider(response="ok"))
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    with pytest.raises(AgentExecutionError, match="already normalized"):
        agent.on_execution_error(agent_input, AgentExecutionError("already normalized"))


def test_code_artifact_normalization_falls_back_when_markdown_code_block_is_empty():
    agent = CodeDummyAgent(DummyProvider(response="ok"))
    output = AgentOutput(summary="summary", raw_content="```python\n```", artifacts=[], decisions=[], metadata={})

    normalized = agent._normalize_output_for_artifact_type(output)

    assert normalized.raw_content == "```python\n```"


def test_normalize_output_handles_agent_output_and_rejects_invalid_types_or_blank_strings():
    agent = DummyAgent(DummyProvider(response="ok"))
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )
    structured = AgentOutput(summary="   ", raw_content="first line\nsecond line", artifacts=[], decisions=[], metadata={})

    normalized = agent._normalize_output(structured, agent_input)

    assert normalized.summary == "first line"

    with pytest.raises(AgentExecutionError, match="agent output must be a string or AgentOutput"):
        agent._normalize_output(123, agent_input)

    with pytest.raises(AgentExecutionError, match="agent output must not be empty"):
        agent._normalize_output("   ", agent_input)


@pytest.mark.parametrize(
    ("context", "message"),
    [
        ({}, "required context key 'architecture' is missing"),
        ({"architecture": "   "}, "required context key 'architecture' must not be empty"),
    ],
)
def test_require_context_value_rejects_missing_or_blank_values(context, message):
    agent = DummyAgent(DummyProvider(response="ok"))
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context=context,
    )

    with pytest.raises(AgentExecutionError, match=message):
        agent.require_context_value(agent_input, "architecture")


def test_require_context_value_returns_non_empty_value_and_provider_metadata_accessor_copies_state():
    agent = DummyAgent(DummyProvider(response="ok"))
    agent_input = AgentInput(
        task_id="task-1",
        task_title="Task",
        task_description="message",
        project_name="Demo",
        project_goal="Build demo",
        context={"architecture": "Layered runtime"},
    )
    agent._last_provider_call_metadata = {"provider": "openai"}

    metadata_copy = agent.get_last_provider_call_metadata()
    assert metadata_copy is not None
    metadata_copy["provider"] = "mutated"

    assert agent.require_context_value(agent_input, "architecture") == "Layered runtime"
    assert agent.get_last_provider_call_metadata() == {
        "provider": "openai",
        "provider_call_budget_limited": False,
        "provider_call_budget_exhausted": False,
        "provider_call_budget_limited_providers": [],
        "provider_call_budget_exhausted_providers": [],
        "provider_elapsed_budget_limited": False,
        "provider_elapsed_budget_exhausted": False,
    }


def test_get_last_provider_call_metadata_returns_none_when_no_call_has_run():
    agent = DummyAgent(DummyProvider(response="ok"))
    agent._last_provider_call_metadata = None

    assert agent.get_last_provider_call_metadata() is None


def test_base_agent_repr_and_abstract_run_fallback_are_exposed():
    agent = DirectBaseRunAgent(DummyProvider(response="ok"))

    assert repr(agent) == "<Agent name=Dummy role=Testing>"
    assert agent.run("message", {}) is None


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