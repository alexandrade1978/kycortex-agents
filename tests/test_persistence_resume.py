import pytest
from typing import Any, cast

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import TaskStatus


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