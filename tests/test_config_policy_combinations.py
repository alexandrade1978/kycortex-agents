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
        self.calls = 0

    def run(self, task_description: str, context: dict) -> str:
        self.calls += 1
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


@pytest.mark.parametrize(
    (
        "failure_policy",
        "resume_policy",
        "expect_first_run_exception",
        "expect_second_run_exception",
        "expected_statuses_after_first_run",
        "expected_statuses_after_second_run",
    ),
    [
        (
            "fail_fast",
            "interrupted_only",
            RuntimeError,
            AgentExecutionError,
            {"arch": TaskStatus.FAILED.value, "code": TaskStatus.PENDING.value, "review": TaskStatus.PENDING.value},
            {"arch": TaskStatus.FAILED.value, "code": TaskStatus.DONE.value, "review": TaskStatus.PENDING.value},
        ),
        (
            "fail_fast",
            "resume_failed",
            RuntimeError,
            None,
            {"arch": TaskStatus.FAILED.value, "code": TaskStatus.PENDING.value, "review": TaskStatus.PENDING.value},
            {"arch": TaskStatus.DONE.value, "code": TaskStatus.DONE.value, "review": TaskStatus.DONE.value},
        ),
        (
            "continue",
            "interrupted_only",
            None,
            None,
            {"arch": TaskStatus.FAILED.value, "code": TaskStatus.DONE.value, "review": TaskStatus.SKIPPED.value},
            {"arch": TaskStatus.FAILED.value, "code": TaskStatus.DONE.value, "review": TaskStatus.SKIPPED.value},
        ),
        (
            "continue",
            "resume_failed",
            None,
            None,
            {"arch": TaskStatus.FAILED.value, "code": TaskStatus.DONE.value, "review": TaskStatus.SKIPPED.value},
            {"arch": TaskStatus.DONE.value, "code": TaskStatus.DONE.value, "review": TaskStatus.DONE.value},
        ),
    ],
)
def test_workflow_policy_combinations_control_persisted_second_run_behavior(
    tmp_path,
    failure_policy,
    resume_policy,
    expect_first_run_exception,
    expect_second_run_exception,
    expected_statuses_after_first_run,
    expected_statuses_after_second_run,
):
    state_path = tmp_path / f"{failure_policy}_{resume_policy}.json"
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy=failure_policy,
        workflow_resume_policy=resume_policy,
    )
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    project.add_task(Task(id="code", title="Implementation", description="Implement", assigned_to="code_engineer"))
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )

    architect = FlakyAgent(failures_before_success=1, success_response="ARCHITECTURE DOC")
    engineer = RecordingAgent("IMPLEMENTED CODE")
    reviewer = RecordingAgent("REVIEWED")
    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": architect,
                "code_engineer": engineer,
                "code_reviewer": reviewer,
            }
        ),
    )

    if expect_first_run_exception is None:
        orchestrator.execute_workflow(project)
    else:
        with pytest.raises(expect_first_run_exception):
            orchestrator.execute_workflow(project)

    project.save()
    reloaded = ProjectState.load(str(state_path))

    assert {task.id: task.status for task in reloaded.tasks} == expected_statuses_after_first_run

    if expect_second_run_exception is None:
        orchestrator.execute_workflow(reloaded)
    else:
        with pytest.raises(expect_second_run_exception):
            orchestrator.execute_workflow(reloaded)

    actual_statuses_after_second_run = {task.id: task.status for task in reloaded.tasks}
    for task_id, status in expected_statuses_after_second_run.items():
        assert actual_statuses_after_second_run[task_id] == status

    if resume_policy == "resume_failed":
        repair_task_ids = [task.id for task in reloaded.tasks if task.repair_origin_task_id]
        assert repair_task_ids
        assert all(actual_statuses_after_second_run[task_id] == TaskStatus.DONE.value for task_id in repair_task_ids)
    else:
        assert all(not task.repair_origin_task_id for task in reloaded.tasks)

    if resume_policy == "resume_failed":
        assert reloaded.workflow_last_resumed_at is not None
    else:
        assert reloaded.workflow_last_resumed_at is None


def test_retry_budget_is_consumed_before_resume_failed_policy_requeues_task(tmp_path):
    state_path = tmp_path / "retry_resume_failed.json"
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
            description="Design",
            assigned_to="architect",
            retry_limit=1,
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

    architect = FlakyAgent(failures_before_success=2, success_response="ARCHITECTURE DOC")
    reviewer = RecordingAgent("REVIEWED")
    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry({"architect": architect, "code_reviewer": reviewer}),
    )

    with pytest.raises(RuntimeError, match="boom-2"):
        orchestrator.execute_workflow(project)

    project.save()
    reloaded = ProjectState.load(str(state_path))

    arch_task = require_task(reloaded, "arch")
    assert arch_task.attempts == 2
    assert arch_task.status == TaskStatus.FAILED.value

    orchestrator.execute_workflow(reloaded)

    arch_task = require_task(reloaded, "arch")
    review_task = require_task(reloaded, "review")
    assert arch_task.status == TaskStatus.DONE.value
    assert arch_task.attempts == 3
    assert review_task.status == TaskStatus.DONE.value
    assert [entry["event"] for entry in arch_task.history].count("retry_scheduled") == 1
    assert any(event["event"] == "task_requeued" for event in reloaded.execution_events)