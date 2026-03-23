import json
import sqlite3

import pytest

from kycortex_agents.exceptions import StatePersistenceError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.memory.state_store import resolve_state_store
from kycortex_agents.types import AgentOutput, ArtifactRecord, ArtifactType, DecisionRecord, TaskStatus, WorkflowStatus


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
    assert loaded.updated_at is not None
    assert loaded.execution_events == []


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


def test_save_and_load_project_state_with_sqlite(tmp_path):
    state_path = tmp_path / "state" / "project_state.sqlite"
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
    assert loaded.tasks[0].id == "arch"
    assert loaded.updated_at is not None


@pytest.mark.parametrize("state_filename", ["legacy.json", "legacy.sqlite"])
def test_load_accepts_legacy_payloads_missing_newer_fields(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Keep compatibility",
        "tasks": [
            {
                "id": "arch",
                "title": "Architecture",
                "description": "Design",
                "assigned_to": "architect",
                "status": TaskStatus.DONE.value,
                "output": "ARCHITECTURE DOC",
            },
            {
                "id": "review",
                "title": "Review",
                "description": "Review",
                "assigned_to": "code_reviewer",
                "dependencies": ["arch"],
            },
        ],
        "decisions": [],
        "artifacts": ["legacy-report.md"],
        "phase": "completed",
        "state_file": str(state_path),
    }

    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))
    arch_task = loaded.get_task("arch")
    review_task = loaded.get_task("review")
    snapshot = loaded.snapshot()

    assert loaded.project_name == "Legacy"
    assert loaded.goal == "Keep compatibility"
    assert loaded.execution_events == []
    assert loaded.workflow_started_at is None
    assert loaded.workflow_finished_at is None
    assert loaded.workflow_last_resumed_at is None
    assert arch_task is not None
    assert arch_task.last_provider_call is None
    assert arch_task.output_payload is None
    assert arch_task.history == []
    assert arch_task.started_at is None
    assert arch_task.last_attempt_started_at is None
    assert arch_task.last_resumed_at is None
    assert arch_task.completed_at is None
    assert review_task is not None
    assert review_task.status == TaskStatus.PENDING.value
    assert review_task.attempts == 0
    assert snapshot.task_results["arch"].output is not None
    assert snapshot.task_results["arch"].output.summary == "ARCHITECTURE DOC"
    assert snapshot.artifacts[0].name == "legacy-report.md"
    assert snapshot.artifacts[0].artifact_type == ArtifactType.OTHER


def test_load_rejects_invalid_sqlite(tmp_path):
    state_path = tmp_path / "broken.sqlite"
    connection = sqlite3.connect(state_path)
    with connection:
        connection.execute("CREATE TABLE wrong_table (id INTEGER PRIMARY KEY)")
    connection.close()

    with pytest.raises(StatePersistenceError, match="invalid SQLite"):
        ProjectState.load(str(state_path))


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


def test_complete_task_persists_structured_agent_output_payload():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    project.complete_task(
        "arch",
        AgentOutput(
            summary="Architecture summary",
            raw_content="ARCHITECTURE DOC",
            artifacts=[
                ArtifactRecord(
                    name="architecture_doc",
                    artifact_type=ArtifactType.DOCUMENT,
                    path="artifacts/architecture.md",
                    content="# Architecture",
                )
            ],
            decisions=[
                DecisionRecord(
                    topic="stack",
                    decision="Use FastAPI",
                    rationale="Fits the API use case",
                )
            ],
            metadata={"agent_name": "Architect"},
        ),
    )

    task = project.get_task("arch")
    snapshot = project.snapshot()
    result = snapshot.task_results["arch"]

    assert task.output == "ARCHITECTURE DOC"
    assert task.output_payload is not None
    assert task.history[-1]["event"] == "completed"
    assert task.output_payload["summary"] == "Architecture summary"
    assert result.output is not None
    assert result.output.artifacts[0].path == "artifacts/architecture.md"
    assert result.output.decisions[0].decision == "Use FastAPI"
    assert result.output.metadata["agent_name"] == "Architect"
    assert result.details["history"][-1]["event"] == "completed"


def test_save_and_load_preserves_rich_artifact_records_json(tmp_path):
    state_path = tmp_path / "project_state.json"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_artifact_record(
        ArtifactRecord(
            name="architecture_doc",
            artifact_type=ArtifactType.DOCUMENT,
            path="artifacts/architecture.md",
            content="# Architecture",
            metadata={"source": "architect"},
        )
    )

    project.save()
    loaded = ProjectState.load(str(state_path))
    snapshot = loaded.snapshot()

    assert loaded.artifacts[0]["name"] == "architecture_doc"
    assert loaded.artifacts[0]["artifact_type"] == ArtifactType.DOCUMENT.value
    assert snapshot.artifacts[0].path == "artifacts/architecture.md"
    assert snapshot.artifacts[0].content == "# Architecture"
    assert snapshot.artifacts[0].metadata["source"] == "architect"


def test_save_and_load_preserves_structured_task_output_payload_json(tmp_path):
    state_path = tmp_path / "project_state.json"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
        )
    )
    project.complete_task(
        "arch",
        AgentOutput(
            summary="Architecture summary",
            raw_content="ARCHITECTURE DOC",
            artifacts=[ArtifactRecord(name="architecture_doc", artifact_type=ArtifactType.DOCUMENT)],
            metadata={"agent_name": "Architect"},
        ),
    )

    project.save()
    loaded = ProjectState.load(str(state_path))
    snapshot = loaded.snapshot()

    assert loaded.get_task("arch").output_payload is not None
    assert loaded.get_task("arch").output_payload["summary"] == "Architecture summary"
    assert snapshot.task_results["arch"].output.summary == "Architecture summary"
    assert snapshot.task_results["arch"].output.metadata["agent_name"] == "Architect"


def test_save_and_load_preserves_rich_artifact_records_sqlite(tmp_path):
    state_path = tmp_path / "project_state.sqlite"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_artifact_record(
        ArtifactRecord(
            name="generated_tests",
            artifact_type=ArtifactType.TEST,
            content="def test_example(): pass",
            metadata={"source": "qa_tester"},
        )
    )

    project.save()
    loaded = ProjectState.load(str(state_path))
    snapshot = loaded.snapshot()

    assert loaded.artifacts[0]["artifact_type"] == ArtifactType.TEST.value
    assert snapshot.artifacts[0].name == "generated_tests"
    assert snapshot.artifacts[0].content == "def test_example(): pass"
    assert snapshot.artifacts[0].metadata["source"] == "qa_tester"


def test_snapshot_remains_backward_compatible_with_legacy_string_artifacts():
    project = ProjectState(project_name="Demo", goal="Build demo", artifacts=["legacy-report.md"])

    snapshot = project.snapshot()

    assert snapshot.artifacts[0].name == "legacy-report.md"
    assert snapshot.artifacts[0].artifact_type == ArtifactType.OTHER


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
    assert task.started_at is not None
    assert task.last_attempt_started_at is not None
    assert task.history[-1]["event"] == "retry_scheduled"
    assert project.should_retry_task("code") is True


def test_snapshot_hides_failed_output_after_task_is_requeued_for_retry():
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
    project.fail_task("code", RuntimeError("temporary failure"))

    task = project.get_task("code")
    result = project.snapshot().task_results["code"]

    assert task is not None
    assert task.status == TaskStatus.PENDING.value
    assert task.last_error == "temporary failure"
    assert task.output is None
    assert result.status == TaskStatus.PENDING
    assert result.output is None
    assert result.failure is None
    assert result.completed_at is None
    assert result.details["history"][-1]["event"] == "retry_scheduled"


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
    assert project.tasks[0].last_resumed_at is not None
    assert project.tasks[0].history[-1]["event"] == "resumed"
    assert project.tasks[1].status == TaskStatus.DONE.value


def test_resume_failed_tasks_resets_failed_and_dependency_skipped_tasks():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
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
            description="Review",
            assigned_to="code_reviewer",
            dependencies=["arch"],
            status=TaskStatus.SKIPPED.value,
            output="Skipped because dependency 'arch' failed",
            completed_at="2026-03-22T10:06:30+00:00",
        )
    )

    resumed = project.resume_failed_tasks()

    assert resumed == ["arch", "review"]
    assert project.get_task("arch").status == TaskStatus.PENDING.value
    assert project.get_task("arch").output is None
    assert project.get_task("arch").history[-1]["event"] == "requeued"
    assert project.get_task("review").status == TaskStatus.PENDING.value
    assert project.get_task("review").output is None
    assert project.get_task("review").history[-1]["event"] == "requeued"


def test_snapshot_uses_persisted_execution_metadata_for_started_at_and_failure_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            retry_limit=1,
            attempts=2,
            status=TaskStatus.FAILED.value,
            output="boom-2",
            last_error_type="RuntimeError",
            started_at="2026-03-22T10:00:00+00:00",
            last_attempt_started_at="2026-03-22T10:05:00+00:00",
            last_resumed_at="2026-03-22T10:04:00+00:00",
            history=[{"event": "failed", "timestamp": "2026-03-22T10:06:00+00:00", "status": "failed", "attempts": 2, "error_message": "boom-2"}],
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )

    result = project.snapshot().task_results["code"]

    assert result.started_at == "2026-03-22T10:00:00+00:00"
    assert result.failure is not None
    assert result.failure.error_type == "RuntimeError"
    assert result.failure.details["attempts"] == 2
    assert result.failure.details["retry_limit"] == 1
    assert result.failure.details["error_type"] == "RuntimeError"
    assert result.failure.details["last_attempt_started_at"] == "2026-03-22T10:05:00+00:00"
    assert result.failure.details["last_resumed_at"] == "2026-03-22T10:04:00+00:00"
    assert result.failure.details["task_duration_ms"] == 360000.0
    assert result.failure.details["last_attempt_duration_ms"] == 60000.0
    assert result.details["task_duration_ms"] == 360000.0
    assert result.details["last_attempt_duration_ms"] == 60000.0
    assert result.details["history"][0]["event"] == "failed"


def test_save_and_load_preserves_task_history_json(tmp_path):
    state_path = tmp_path / "project_state.json"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            history=[{"event": "started", "timestamp": "2026-03-22T10:00:00+00:00", "status": "running", "attempts": 1, "error_message": None}],
        )
    )

    project.save()
    loaded = ProjectState.load(str(state_path))

    assert loaded.get_task("arch").history[0]["event"] == "started"


def test_save_and_load_preserves_task_history_sqlite(tmp_path):
    state_path = tmp_path / "project_state.sqlite"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            history=[{"event": "started", "timestamp": "2026-03-22T10:00:00+00:00", "status": "running", "attempts": 1, "error_message": None}],
        )
    )

    project.save()
    loaded = ProjectState.load(str(state_path))

    assert loaded.get_task("arch").history[0]["event"] == "started"


def test_snapshot_includes_workflow_execution_metadata():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {"event": "workflow_started", "timestamp": "2026-03-22T10:00:00+00:00", "task_id": None, "status": "execution", "details": {}},
            {"event": "workflow_finished", "timestamp": "2026-03-22T10:06:00+00:00", "task_id": None, "status": "completed", "details": {"workflow_duration_ms": 360000.0}},
        ],
        workflow_started_at="2026-03-22T10:00:00+00:00",
        workflow_finished_at="2026-03-22T10:06:00+00:00",
        workflow_last_resumed_at="2026-03-22T10:04:00+00:00",
        updated_at="2026-03-22T10:06:00+00:00",
        phase="completed",
    )

    snapshot = project.snapshot()

    assert snapshot.started_at == "2026-03-22T10:00:00+00:00"
    assert snapshot.finished_at == "2026-03-22T10:06:00+00:00"
    assert snapshot.last_resumed_at == "2026-03-22T10:04:00+00:00"
    assert snapshot.execution_events[0]["event"] == "workflow_started"
    assert snapshot.execution_events[1]["details"]["workflow_duration_ms"] == 360000.0
    assert snapshot.updated_at == "2026-03-22T10:06:00+00:00"


def test_snapshot_reports_init_workflow_status_for_empty_and_pending_projects():
    empty_project = ProjectState(project_name="Demo", goal="Build demo")
    pending_project = ProjectState(project_name="Demo", goal="Build demo")
    pending_project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
        )
    )

    assert empty_project.snapshot().workflow_status == WorkflowStatus.INIT
    assert pending_project.snapshot().workflow_status == WorkflowStatus.INIT


def test_snapshot_reports_running_workflow_status_when_any_task_is_running():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.RUNNING.value,
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Docs",
            description="Document",
            assigned_to="docs_writer",
            status=TaskStatus.SKIPPED.value,
            output="Skipped because dependency 'arch' failed",
        )
    )

    assert project.snapshot().workflow_status == WorkflowStatus.RUNNING


def test_save_and_load_preserves_execution_events_json(tmp_path):
    state_path = tmp_path / "project_state.json"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.execution_events.append(
        {
            "event": "task_completed",
            "timestamp": "2026-03-22T10:06:00+00:00",
            "task_id": "arch",
            "status": "done",
            "details": {"attempts": 1},
        }
    )

    project.save()
    loaded = ProjectState.load(str(state_path))

    assert loaded.execution_events[0]["event"] == "task_completed"
    assert loaded.execution_events[0]["details"]["attempts"] == 1


def test_save_and_load_preserves_execution_events_sqlite(tmp_path):
    state_path = tmp_path / "project_state.sqlite"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.execution_events.append(
        {
            "event": "task_completed",
            "timestamp": "2026-03-22T10:06:00+00:00",
            "task_id": "arch",
            "status": "done",
            "details": {"attempts": 1},
        }
    )

    project.save()
    loaded = ProjectState.load(str(state_path))

    assert loaded.execution_events[0]["event"] == "task_completed"
    assert loaded.execution_events[0]["details"]["attempts"] == 1


def test_save_and_load_preserves_execution_metadata_json(tmp_path):
    state_path = tmp_path / "project_state.json"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            started_at="2026-03-22T10:00:00+00:00",
            last_attempt_started_at="2026-03-22T10:01:00+00:00",
            last_resumed_at="2026-03-22T10:02:00+00:00",
        )
    )

    project.save()
    loaded = ProjectState.load(str(state_path))

    assert loaded.get_task("arch").started_at == "2026-03-22T10:00:00+00:00"
    assert loaded.get_task("arch").last_attempt_started_at == "2026-03-22T10:01:00+00:00"
    assert loaded.get_task("arch").last_resumed_at == "2026-03-22T10:02:00+00:00"


def test_save_and_load_preserves_workflow_metadata_json(tmp_path):
    state_path = tmp_path / "project_state.json"
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        state_file=str(state_path),
        workflow_started_at="2026-03-22T10:00:00+00:00",
        workflow_finished_at="2026-03-22T10:06:00+00:00",
        workflow_last_resumed_at="2026-03-22T10:04:00+00:00",
        updated_at="2026-03-22T10:06:00+00:00",
    )

    project.save()
    loaded = ProjectState.load(str(state_path))

    assert loaded.workflow_started_at == "2026-03-22T10:00:00+00:00"
    assert loaded.workflow_finished_at == "2026-03-22T10:06:00+00:00"
    assert loaded.workflow_last_resumed_at == "2026-03-22T10:04:00+00:00"


def test_save_and_load_preserves_execution_metadata_sqlite(tmp_path):
    state_path = tmp_path / "project_state.sqlite"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            started_at="2026-03-22T10:00:00+00:00",
            last_attempt_started_at="2026-03-22T10:01:00+00:00",
            last_resumed_at="2026-03-22T10:02:00+00:00",
        )
    )

    project.save()
    loaded = ProjectState.load(str(state_path))

    assert loaded.get_task("arch").started_at == "2026-03-22T10:00:00+00:00"
    assert loaded.get_task("arch").last_attempt_started_at == "2026-03-22T10:01:00+00:00"
    assert loaded.get_task("arch").last_resumed_at == "2026-03-22T10:02:00+00:00"


def test_save_and_load_preserves_workflow_metadata_sqlite(tmp_path):
    state_path = tmp_path / "project_state.sqlite"
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        state_file=str(state_path),
        workflow_started_at="2026-03-22T10:00:00+00:00",
        workflow_finished_at="2026-03-22T10:06:00+00:00",
        workflow_last_resumed_at="2026-03-22T10:04:00+00:00",
        updated_at="2026-03-22T10:06:00+00:00",
    )

    project.save()
    loaded = ProjectState.load(str(state_path))

    assert loaded.workflow_started_at == "2026-03-22T10:00:00+00:00"
    assert loaded.workflow_finished_at == "2026-03-22T10:06:00+00:00"
    assert loaded.workflow_last_resumed_at == "2026-03-22T10:04:00+00:00"


def test_execution_plan_rejects_cycles():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            dependencies=["code"],
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

    with pytest.raises(WorkflowDefinitionError, match="cyclic"):
        project.execution_plan()


def test_skip_dependent_tasks_marks_pending_descendants_as_skipped():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
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
            id="test",
            title="Tests",
            description="Test",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    skipped = project.skip_dependent_tasks("arch", "Skipped because arch failed")

    assert skipped == ["code", "test"]
    assert project.get_task("code").status == TaskStatus.SKIPPED.value
    assert project.get_task("test").status == TaskStatus.SKIPPED.value


def test_skip_task_clears_stale_structured_output_from_snapshot():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="docs",
            title="Docs",
            description="Document",
            assigned_to="docs_writer",
            output="STALE CONTENT",
            output_payload={
                "summary": "Stale summary",
                "raw_content": "STALE CONTENT",
                "artifacts": [],
                "decisions": [],
                "metadata": {"provider_call": {"provider": "openai"}},
            },
            last_provider_call={"provider": "openai", "model": "gpt-4o"},
            last_error_type="RuntimeError",
            started_at="2026-03-22T10:00:00+00:00",
            last_attempt_started_at="2026-03-22T10:05:00+00:00",
            last_resumed_at="2026-03-22T10:04:00+00:00",
        )
    )

    project.skip_task("docs", "Skipped because dependency 'arch' failed")

    task = project.get_task("docs")
    result = project.snapshot().task_results["docs"]

    assert task is not None
    assert task.status == TaskStatus.SKIPPED.value
    assert task.output == "Skipped because dependency 'arch' failed"
    assert task.output_payload is None
    assert task.last_provider_call is None
    assert task.last_error_type is None
    assert task.started_at is None
    assert task.last_attempt_started_at is None
    assert task.last_resumed_at is None
    assert result.status == TaskStatus.SKIPPED
    assert result.started_at is None
    assert result.output is not None
    assert result.output.summary == "Skipped because dependency 'arch' failed"
    assert result.details["last_provider_call"] is None
    assert result.details["last_error_type"] is None
    assert result.details["last_attempt_started_at"] is None
    assert result.details["last_resumed_at"] is None
    assert result.details["task_duration_ms"] is None
    assert result.details["last_attempt_duration_ms"] is None


def test_snapshot_does_not_expose_created_at_as_started_at_for_never_started_tasks():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="docs",
            title="Docs",
            description="Document",
            assigned_to="docs_writer",
            created_at="2026-03-22T10:00:00+00:00",
        )
    )

    result = project.snapshot().task_results["docs"]

    assert result.status == TaskStatus.PENDING
    assert result.started_at is None
    assert result.completed_at is None