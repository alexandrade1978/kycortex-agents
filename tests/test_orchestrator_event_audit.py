import pytest

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import TaskStatus


class RecordingAgent:
    def __init__(self, response: str):
        self.response = response

    def run(self, task_description: str, context: dict) -> str:
        return self.response


class FailingAgent:
    def run(self, task_description: str, context: dict) -> str:
        raise RuntimeError("boom")


def test_execute_workflow_logs_workflow_blocked_for_persisted_unsatisfied_dependencies(tmp_path, caplog):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.FAILED.value,
            output="boom",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": RecordingAgent("ARCHITECTURE DOC"),
                "code_reviewer": RecordingAgent("REVIEWED"),
            }
        ),
    )

    with caplog.at_level("INFO", logger="Orchestrator"):
        with pytest.raises(
            AgentExecutionError,
            match="Workflow is blocked because pending tasks have unsatisfied dependencies: review",
        ):
            orchestrator.execute_workflow(project)

    blocked_record = next(record for record in caplog.records if getattr(record, "event", None) == "workflow_blocked")

    assert blocked_record.project_name == "Demo"
    assert blocked_record.phase == "failed"
    assert blocked_record.blocked_task_ids == "review"
    assert project.phase == "failed"
    assert project.execution_events[0]["event"] == "workflow_started"
    assert project.execution_events[-1]["event"] == "workflow_finished"
    assert project.execution_events[-1]["status"] == "failed"


def test_execute_workflow_logs_cascading_dependent_tasks_skipped(tmp_path, caplog):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), workflow_failure_policy="continue")
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Validate",
            assigned_to="qa_tester",
            dependencies=["code", "review"],
        )
    )

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": FailingAgent(),
                "code_engineer": RecordingAgent("IMPLEMENTED CODE"),
                "code_reviewer": RecordingAgent("REVIEWED"),
                "qa_tester": RecordingAgent("TESTS"),
            }
        ),
    )

    with caplog.at_level("INFO", logger="Orchestrator"):
        orchestrator.execute_workflow(project)

    skipped_record = next(record for record in caplog.records if getattr(record, "event", None) == "dependent_tasks_skipped")

    assert skipped_record.project_name == "Demo"
    assert skipped_record.task_id == "arch"
    assert skipped_record.skipped_task_ids == ["code", "review", "tests"]
    assert project.get_task("arch").status == TaskStatus.FAILED.value
    assert project.get_task("code").status == TaskStatus.SKIPPED.value
    assert project.get_task("review").status == TaskStatus.SKIPPED.value
    assert project.get_task("tests").status == TaskStatus.SKIPPED.value
    assert project.phase == "completed"


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_cascading_task_skip_audit_trail_persists_across_reload(tmp_path, state_filename):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), workflow_failure_policy="continue")
    state_path = tmp_path / state_filename
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Validate",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": FailingAgent(),
                "code_engineer": RecordingAgent("IMPLEMENTED CODE"),
                "qa_tester": RecordingAgent("TESTS"),
            }
        ),
    )

    orchestrator.execute_workflow(project)
    project.save()

    reloaded = ProjectState.load(str(state_path))
    skipped_events = [event for event in reloaded.execution_events if event["event"] == "task_skipped"]

    assert [event["task_id"] for event in skipped_events] == ["code", "tests"]
    assert skipped_events[0]["details"]["reason"] == "Skipped because dependency 'arch' failed"
    assert skipped_events[1]["details"]["reason"] == "Skipped because dependency 'arch' failed"
    assert reloaded.get_task("code").history[-1]["event"] == "skipped"
    assert reloaded.get_task("tests").history[-1]["event"] == "skipped"
