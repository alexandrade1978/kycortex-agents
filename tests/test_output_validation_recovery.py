import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.types import AgentOutput, TaskStatus


class StaticProvider(BaseLLMProvider):
    def __init__(self, response: str = "MODEL OUTPUT", metadata=None):
        self.response = response
        self.metadata = metadata or {}
        self.calls = 0

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls += 1
        return self.response

    def get_last_call_metadata(self):
        return dict(self.metadata)


class EmptyOutputAfterProviderAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("EmptyOutput", "Testing", config)
        self._provider = StaticProvider(metadata={"usage": {"total_tokens": 12}})

    def run(self, task_description: str, context: dict) -> str:
        self.chat("system", task_description)
        return "   "


class RetryAfterValidationFailureAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("RetryAgent", "Testing", config)
        self._provider = StaticProvider(metadata={"usage": {"total_tokens": 9}})
        self.calls = 0

    def run(self, task_description: str, context: dict) -> str:
        self.calls += 1
        self.chat("system", task_description)
        if self.calls == 1:
            return ""
        return "Recovered output\nwith detail"


class InvalidTypeAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("InvalidType", "Testing", config)

    def run(self, task_description: str, context: dict):
        return 42


class MissingSummaryAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("MissingSummary", "Testing", config)

    def run(self, task_description: str, context: dict) -> AgentOutput:
        return AgentOutput(
            summary="",
            raw_content="Normalized summary\nMore detail",
            metadata={
                "provider_call": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "success": True,
                    "usage": {"total_tokens": 21},
                }
            },
        )


def build_config(tmp_path, **overrides):
    payload = {"output_dir": str(tmp_path / "output"), "api_key": "token"}
    payload.update(overrides)
    return KYCortexConfig(**payload)


def test_run_task_fails_on_empty_output_and_preserves_provider_metadata(tmp_path):
    config = build_config(tmp_path)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    agent = EmptyOutputAfterProviderAgent(config)
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": agent}))

    with pytest.raises(AgentExecutionError, match="agent output must not be empty"):
        orchestrator.run_task(project.tasks[0], project)

    task = project.get_task("arch")

    assert task is not None
    assert task.status == TaskStatus.FAILED.value
    assert task.output == "EmptyOutput: agent output must not be empty"
    assert task.output_payload is None
    assert task.last_error_type == "AgentExecutionError"
    assert task.last_provider_call["provider"] == "openai"
    assert task.last_provider_call["success"] is True
    assert task.last_provider_call["usage"]["total_tokens"] == 12
    assert project.artifacts == []
    assert project.decisions == []


def test_execute_workflow_retries_after_output_validation_failure_and_completes(tmp_path):
    config = build_config(tmp_path)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            retry_limit=1,
        )
    )
    agent = RetryAfterValidationFailureAgent(config)
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": agent}))

    orchestrator.execute_workflow(project)

    task = project.get_task("arch")

    assert task is not None
    assert agent.calls == 2
    assert task.status == TaskStatus.DONE.value
    assert task.attempts == 2
    assert task.output == "Recovered output\nwith detail"
    assert task.output_payload is not None
    assert task.output_payload["summary"] == "Recovered output"
    assert task.last_provider_call["success"] is True
    assert task.last_provider_call["usage"]["total_tokens"] == 9
    assert [event["event"] for event in task.history] == ["started", "retry_scheduled", "started", "completed"]
    assert any(event["event"] == "task_retry_scheduled" for event in project.execution_events)
    assert project.phase == "completed"


def test_run_task_rejects_invalid_output_type_without_partial_persistence(tmp_path):
    config = build_config(tmp_path)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(Task(id="review", title="Review", description="Review", assigned_to="code_reviewer"))
    orchestrator = Orchestrator(config, registry=AgentRegistry({"code_reviewer": InvalidTypeAgent(config)}))

    with pytest.raises(AgentExecutionError, match="agent output must be a string or AgentOutput"):
        orchestrator.run_task(project.tasks[0], project)

    task = project.get_task("review")

    assert task is not None
    assert task.status == TaskStatus.FAILED.value
    assert task.output == "InvalidType: agent output must be a string or AgentOutput"
    assert task.output_payload is None
    assert task.last_provider_call is None
    assert project.artifacts == []
    assert project.decisions == []


def test_run_task_normalizes_missing_summary_and_persists_output_provider_metadata(tmp_path):
    config = build_config(tmp_path)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(Task(id="docs", title="Docs", description="Document", assigned_to="docs_writer"))
    orchestrator = Orchestrator(config, registry=AgentRegistry({"docs_writer": MissingSummaryAgent(config)}))

    result = orchestrator.run_task(project.tasks[0], project)
    task = project.get_task("docs")

    assert result == "Normalized summary\nMore detail"
    assert task is not None
    assert task.status == TaskStatus.DONE.value
    assert task.output_payload is not None
    assert task.output_payload["summary"] == "Normalized summary"
    assert task.output_payload["metadata"]["provider_call"]["usage"]["total_tokens"] == 21
    assert task.last_provider_call["provider"] == "openai"
    assert task.last_provider_call["usage"]["total_tokens"] == 21
    assert project.artifacts[0]["name"] == "docs_output"
    assert project.artifacts[0]["content"] == "Normalized summary\nMore detail"
