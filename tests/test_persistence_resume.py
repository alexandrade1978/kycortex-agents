import pytest

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import TaskStatus


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

    resumed_arch = reloaded.get_task("arch")
    resumed_review = reloaded.get_task("review")

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

    assert failed.get_task("arch").status == TaskStatus.FAILED.value
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

    resumed_arch = failed.get_task("arch")
    resumed_review = failed.get_task("review")

    assert resumed_arch.status == TaskStatus.DONE.value
    assert resumed_arch.output == "ARCHITECTURE DOC"
    assert "requeued" in [entry["event"] for entry in resumed_arch.history]
    assert resumed_review.status == TaskStatus.DONE.value
    assert resumed_review.output == "REVIEWED"
    assert failed.workflow_last_resumed_at is not None
    assert any(event["event"] == "task_requeued" for event in failed.execution_events)
    assert failed.execution_events[-1]["event"] == "workflow_finished"