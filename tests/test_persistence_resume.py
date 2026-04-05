import pytest
from typing import Any, cast

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import FailureCategory, TaskStatus, WorkflowOutcome


KYCortexConfig = cast(Any, KYCortexConfig)


class RecordingAgent:
    def __init__(self, response: str):
        self.response = response

    def run(self, task_description: str, context: dict) -> str:
        return self.response


class FlakyAgent:
    def __init__(self, failures_before_success: int, success_response: str):
        self.failures_before_success = failures_before_success
        self.success_response = success_response
        self.calls = 0

    def run(self, task_description: str, context: dict) -> str:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError(f"boom-{self.calls}")
        return self.success_response


def require_task(project: ProjectState, task_id: str) -> Task:
    task = project.get_task(task_id)
    assert task is not None
    return task


def require_provider_call(task: Task) -> dict[str, Any]:
    provider_call = task.last_provider_call
    assert isinstance(provider_call, dict)
    return provider_call


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_persisted_interrupted_workflow_resumes_after_reload(tmp_path, state_filename):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    state_path = tmp_path / state_filename
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.RUNNING.value,
            attempts=1,
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )

    project.save()
    reloaded = ProjectState.load(str(state_path))

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": RecordingAgent("ARCHITECTURE DOC"),
                "code_reviewer": RecordingAgent("REVIEWED"),
            }
        ),
    )

    orchestrator.execute_workflow(reloaded)

    resumed_arch = require_task(reloaded, "arch")
    resumed_review = require_task(reloaded, "review")

    assert resumed_arch.status == TaskStatus.DONE.value
    assert resumed_arch.attempts == 2
    assert resumed_arch.output == "ARCHITECTURE DOC"
    assert resumed_arch.last_resumed_at is not None
    assert "resumed" in [entry["event"] for entry in resumed_arch.history]
    assert resumed_review.status == TaskStatus.DONE.value
    assert resumed_review.output == "REVIEWED"
    assert reloaded.workflow_last_resumed_at is not None
    assert any(event["event"] == "workflow_resumed" for event in reloaded.execution_events)


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_persisted_failed_workflow_resumes_after_reload(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
    )
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )

    architect = FlakyAgent(failures_before_success=1, success_response="ARCHITECTURE DOC")
    failing_orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": architect,
                "code_reviewer": RecordingAgent("REVIEWED"),
            }
        ),
    )

    with pytest.raises(RuntimeError, match="boom-1"):
        failing_orchestrator.execute_workflow(project)

    failed = ProjectState.load(str(state_path))

    failed_arch = require_task(failed, "arch")
    assert failed_arch.status == TaskStatus.FAILED.value
    assert failed.phase == "failed"

    resume_orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": architect,
                "code_reviewer": RecordingAgent("REVIEWED"),
            }
        ),
    )

    resume_orchestrator.execute_workflow(failed)

    resumed_arch = require_task(failed, "arch")
    resumed_review = require_task(failed, "review")
    repair_task = require_task(failed, "arch__repair_1")

    assert resumed_arch.status == TaskStatus.DONE.value
    assert resumed_arch.output == "ARCHITECTURE DOC"
    assert "requeued" in [entry["event"] for entry in resumed_arch.history]
    assert repair_task.status == TaskStatus.DONE.value
    assert repair_task.repair_origin_task_id == "arch"
    assert resumed_review.status == TaskStatus.DONE.value
    assert resumed_review.output == "REVIEWED"
    assert failed.workflow_last_resumed_at is not None
    assert any(event["event"] == "task_requeued" for event in failed.execution_events)
    assert failed.execution_events[-1]["event"] == "workflow_finished"


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_persisted_provider_transient_failure_does_not_auto_resume_after_reload(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )

    class TimeoutProvider:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []
            self.health_calls = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

        def get_last_call_metadata(self) -> None:
            return None

        def health_check(self) -> dict[str, object]:
            self.health_calls += 1
            return {
                "provider": "openai",
                "model": "gpt-4o",
                "status": "healthy",
                "active_check": False,
                "retryable": False,
            }

    class ProviderBackedArchitect(BaseAgent):
        def __init__(self, provider: Any, runtime_config: Any):
            super().__init__("Architect", "Architecture & Design", runtime_config)
            self._provider = cast(Any, provider)

        def run(self, task_description: str, context: dict[str, Any]) -> str:
            return self.chat("system", task_description)

    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    provider = TimeoutProvider()
    failing_orchestrator = Orchestrator(
        config,
        registry=AgentRegistry({"architect": ProviderBackedArchitect(provider, config)}),
    )

    with pytest.raises(ProviderTransientError, match="Architect: provider temporarily unavailable"):
        failing_orchestrator.execute_workflow(project)

    failed = ProjectState.load(str(state_path))
    failed_arch = require_task(failed, "arch")
    failed_provider_call = require_provider_call(failed_arch)

    assert failed.phase == "failed"
    assert failed.failure_category == FailureCategory.PROVIDER_TRANSIENT.value
    assert failed.terminal_outcome == WorkflowOutcome.FAILED.value
    assert failed_arch.status == TaskStatus.FAILED.value
    assert failed_arch.last_error_category == FailureCategory.PROVIDER_TRANSIENT.value
    assert failed_provider_call["provider"] == "openai"
    assert failed_provider_call["retryable"] is True
    assert failed_provider_call["attempts_used"] == 1

    resume_orchestrator = Orchestrator(
        config,
        registry=AgentRegistry({"architect": ProviderBackedArchitect(TimeoutProvider(), config)}),
    )

    with pytest.raises(AgentExecutionError, match="cannot resume automatically"):
        resume_orchestrator.execute_workflow(failed)

    reloaded_arch = require_task(failed, "arch")
    reloaded_provider_call = require_provider_call(reloaded_arch)

    assert failed.phase == "failed"
    assert failed.failure_category == FailureCategory.PROVIDER_TRANSIENT.value
    assert failed.terminal_outcome == WorkflowOutcome.FAILED.value
    assert failed.repair_cycle_count == 0
    assert failed.get_task("arch__repair_1") is None
    assert reloaded_arch.status == TaskStatus.FAILED.value
    assert reloaded_arch.last_error_category == FailureCategory.PROVIDER_TRANSIENT.value
    assert reloaded_provider_call["provider"] == "openai"
    assert reloaded_provider_call["retryable"] is True
    assert reloaded_provider_call["attempts_used"] == 1


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_completed_workflow_persists_fallback_provider_metadata_after_reload(tmp_path, state_filename, monkeypatch):
    state_path = tmp_path / state_filename
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        provider_max_attempts=1,
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
    )

    class TransientPrimaryProvider:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []
            self.health_calls = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("primary temporarily unavailable")

        def get_last_call_metadata(self) -> None:
            return None

        def health_check(self) -> dict[str, object]:
            self.health_calls += 1
            return {
                "provider": "openai",
                "model": "gpt-4o",
                "status": "healthy",
                "active_check": False,
                "retryable": False,
            }

    class FallbackProvider:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []
            self.health_calls = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            return "FALLBACK ARCHITECTURE"

        def get_last_call_metadata(self) -> None:
            return None

        def health_check(self) -> dict[str, object]:
            self.health_calls += 1
            return {
                "provider": "anthropic",
                "model": "claude-3-5-sonnet",
                "status": "healthy",
                "active_check": False,
                "retryable": False,
            }

    class ProviderBackedArchitect(BaseAgent):
        def __init__(self, provider: Any, runtime_config: Any):
            super().__init__("Architect", "Architecture & Design", runtime_config)
            self._provider = cast(Any, provider)

        def run(self, task_description: str, context: dict[str, Any]) -> str:
            return self.chat("system", task_description)

    primary_provider = TransientPrimaryProvider()
    fallback_provider = FallbackProvider()

    def create_fallback_provider(runtime_config: Any):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_fallback_provider)

    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry({"architect": ProviderBackedArchitect(primary_provider, config)}),
    )

    orchestrator.execute_workflow(project)

    reloaded = ProjectState.load(str(state_path))
    reloaded_arch = require_task(reloaded, "arch")
    provider_call = require_provider_call(reloaded_arch)

    assert reloaded.phase == "completed"
    assert reloaded.terminal_outcome == WorkflowOutcome.COMPLETED.value
    assert reloaded_arch.status == TaskStatus.DONE.value
    assert reloaded_arch.output == "FALLBACK ARCHITECTURE"
    assert provider_call["provider"] == "anthropic"
    assert provider_call["success"] is True
    assert "fallback_used" not in provider_call
    assert provider_call["fallback_history"] == [
        {
            "provider": "openai",
            "status": "failed_transient",
            "has_error_type": True,
            "has_error_message": True,
            "attempts_used": 1,
        }
    ]
    assert primary_provider.calls == [("system", "Design the architecture")]
    assert fallback_provider.calls == [("system", "Design the architecture")]


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_resume_failed_requeues_skipped_descendants_transitively(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.FAILED.value,
            output="boom",
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
            status=TaskStatus.SKIPPED.value,
            output="Skipped because dependency 'arch' failed",
            skip_reason_type="dependency_failed",
            completed_at="2026-03-22T10:06:30+00:00",
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Docs",
            description="Document the review",
            assigned_to="docs_writer",
            dependencies=["review"],
            status=TaskStatus.SKIPPED.value,
            output="Skipped because dependency 'arch' failed",
            skip_reason_type="dependency_failed",
            completed_at="2026-03-22T10:07:00+00:00",
        )
    )

    project.save()
    reloaded = ProjectState.load(str(state_path))

    resumed = reloaded.resume_failed_tasks()
    arch_task = require_task(reloaded, "arch")
    review_task = require_task(reloaded, "review")
    docs_task = require_task(reloaded, "docs")

    assert resumed == ["arch", "review", "docs"]
    assert arch_task.status == TaskStatus.PENDING.value
    assert review_task.status == TaskStatus.PENDING.value
    assert docs_task.status == TaskStatus.PENDING.value
    assert docs_task.output is None
    assert docs_task.last_error == "Task resumed after failed workflow execution"
    assert docs_task.history[-1]["event"] == "requeued"


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_resume_failed_does_not_revive_manually_skipped_tasks(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.FAILED.value,
            output="boom",
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
            status=TaskStatus.SKIPPED.value,
            output="Skipped because dependency 'arch' failed",
            skip_reason_type="dependency_failed",
            completed_at="2026-03-22T10:06:30+00:00",
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Docs",
            description="Document the review",
            assigned_to="docs_writer",
            dependencies=["review"],
            status=TaskStatus.SKIPPED.value,
            output="Skipped because dependency 'arch' failed",
            skip_reason_type="dependency_failed",
            completed_at="2026-03-22T10:07:00+00:00",
        )
    )
    project.add_task(
        Task(
            id="legal",
            title="Legal",
            description="Hold for manual sign-off",
            assigned_to="legal_advisor",
            dependencies=["arch"],
            status=TaskStatus.SKIPPED.value,
            output="Skipped pending legal approval",
            skip_reason_type="manual",
            completed_at="2026-03-22T10:07:30+00:00",
        )
    )

    project.save()
    reloaded = ProjectState.load(str(state_path))

    resumed = reloaded.resume_failed_tasks()
    arch_task = require_task(reloaded, "arch")
    review_task = require_task(reloaded, "review")
    docs_task = require_task(reloaded, "docs")
    legal_task = require_task(reloaded, "legal")

    assert resumed == ["arch", "review", "docs"]
    assert arch_task.status == TaskStatus.PENDING.value
    assert review_task.status == TaskStatus.PENDING.value
    assert docs_task.status == TaskStatus.PENDING.value
    assert legal_task.status == TaskStatus.SKIPPED.value
    assert legal_task.output == "Skipped pending legal approval"
    assert legal_task.skip_reason_type == "manual"


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_resume_failed_does_not_revive_legacy_manual_skip_with_dependency_shaped_reason(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.FAILED.value,
            output="boom",
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
            status=TaskStatus.SKIPPED.value,
            output="Skipped because dependency 'arch' failed",
            completed_at="2026-03-22T10:06:30+00:00",
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Docs",
            description="Document the review",
            assigned_to="docs_writer",
            dependencies=["review"],
            status=TaskStatus.SKIPPED.value,
            output="Skipped because dependency 'arch' failed",
            completed_at="2026-03-22T10:07:00+00:00",
        )
    )
    project.add_task(
        Task(
            id="signoff",
            title="Signoff",
            description="Await approval",
            assigned_to="legal_advisor",
            status=TaskStatus.DONE.value,
            output="APPROVED",
            completed_at="2026-03-22T10:07:15+00:00",
        )
    )
    project.add_task(
        Task(
            id="legal",
            title="Legal",
            description="Hold for manual sign-off",
            assigned_to="legal_advisor",
            dependencies=["signoff"],
            status=TaskStatus.SKIPPED.value,
            output="Skipped because dependency 'arch' failed",
            completed_at="2026-03-22T10:07:30+00:00",
        )
    )

    project.save()
    reloaded = ProjectState.load(str(state_path))

    review_task = require_task(reloaded, "review")
    docs_task = require_task(reloaded, "docs")
    legal_task = require_task(reloaded, "legal")

    assert review_task.skip_reason_type == "dependency_failed"
    assert docs_task.skip_reason_type == "dependency_failed"
    assert legal_task.skip_reason_type == "manual"

    resumed = reloaded.resume_failed_tasks()

    assert resumed == ["arch", "review", "docs"]
    assert legal_task.status == TaskStatus.SKIPPED.value
    assert legal_task.output == "Skipped because dependency 'arch' failed"
    assert legal_task.skip_reason_type == "manual"