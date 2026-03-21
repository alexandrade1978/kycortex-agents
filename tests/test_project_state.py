import json

import pytest

from kycortex_agents.exceptions import StatePersistenceError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import ArtifactType, TaskStatus


def test_save_and_load_project_state(tmp_path):
    state_path = tmp_path / "state" / "project_state.json"
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        state_file=str(state_path),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    project.save()

    loaded = ProjectState.load(str(state_path))

    assert loaded.project_name == "Demo"
    assert loaded.goal == "Build demo"
    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].id == "arch"


def test_load_rejects_invalid_json(tmp_path):
    state_path = tmp_path / "broken.json"
    state_path.write_text("{not-valid-json", encoding="utf-8")

    with pytest.raises(StatePersistenceError, match="invalid JSON"):
        ProjectState.load(str(state_path))


def test_load_rejects_missing_file(tmp_path):
    state_path = tmp_path / "missing.json"

    with pytest.raises(StatePersistenceError, match="file not found"):
        ProjectState.load(str(state_path))


def test_save_writes_valid_json(tmp_path):
    state_path = tmp_path / "project_state.json"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))

    project.save()

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["project_name"] == "Demo"


def test_snapshot_includes_structured_task_output():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="print('hello')\nprint('world')",
        )
    )

    snapshot = project.snapshot()
    result = snapshot.task_results["code"]

    assert result.output is not None
    assert result.output.summary == "print('hello')"
    assert result.output.raw_content == "print('hello')\nprint('world')"
    assert result.output.artifacts[0].artifact_type == ArtifactType.CODE
    assert result.output.metadata["task_id"] == "code"


def test_runnable_tasks_respect_dependencies():
    project = ProjectState(project_name="Demo", goal="Build demo")
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
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )

    runnable_ids = [task.id for task in project.runnable_tasks()]
    blocked_ids = [task.id for task in project.blocked_tasks()]

    assert runnable_ids == ["arch"]
    assert blocked_ids == ["code"]

    project.complete_task("arch", "ARCHITECTURE DOC")

    assert [task.id for task in project.runnable_tasks()] == ["code"]


def test_fail_task_requeues_when_retry_budget_exists():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            retry_limit=1,
        )
    )

    project.start_task("code")
    project.fail_task("code", "temporary failure")

    task = project.get_task("code")

    assert task is not None
    assert task.status == TaskStatus.PENDING.value
    assert task.attempts == 1
    assert task.last_error == "temporary failure"
    assert project.should_retry_task("code") is True


def test_resume_interrupted_tasks_resets_running_tasks():
    project = ProjectState(project_name="Demo", goal="Build demo")
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
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="IMPLEMENTED CODE",
        )
    )

    resumed = project.resume_interrupted_tasks()

    assert resumed == ["arch"]
    assert project.tasks[0].status == TaskStatus.PENDING.value
    assert project.tasks[0].last_error == "Task resumed after interrupted execution"
    assert project.tasks[1].status == TaskStatus.DONE.value