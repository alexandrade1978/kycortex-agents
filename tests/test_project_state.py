import json
import sqlite3

import pytest

from kycortex_agents.exceptions import StatePersistenceError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.memory.state_store import resolve_state_store
from kycortex_agents.types import AgentOutput, ArtifactRecord, ArtifactType, DecisionRecord, TaskStatus, WorkflowOutcome, WorkflowStatus


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


@pytest.mark.parametrize("state_filename", ["legacy-decisions.json", "legacy-decisions.sqlite"])
def test_load_normalizes_legacy_decision_timestamps_deterministically(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Keep decision timestamps stable",
        "tasks": [],
        "decisions": [
            {
                "topic": "architecture",
                "decision": "Use layered runtime",
                "rationale": "Keeps providers isolated",
                "metadata": {"owner": "architect"},
            }
        ],
        "artifacts": [],
        "phase": "failed",
        "updated_at": "2026-03-22T10:09:00+00:00",
        "state_file": str(state_path),
    }

    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))
    first_snapshot = loaded.snapshot()
    second_snapshot = loaded.snapshot()

    assert loaded.decisions[0]["at"] == "2026-03-22T10:09:00+00:00"
    assert first_snapshot.decisions[0].created_at == "2026-03-22T10:09:00+00:00"
    assert second_snapshot.decisions[0].created_at == "2026-03-22T10:09:00+00:00"

    loaded.save()
    persisted = resolve_state_store(str(state_path)).load(str(state_path))

    assert persisted["decisions"][0]["at"] == "2026-03-22T10:09:00+00:00"


@pytest.mark.parametrize("state_filename", ["legacy-artifacts.json", "legacy-artifacts.sqlite"])
def test_load_normalizes_legacy_artifact_timestamps_deterministically(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Keep artifact timestamps stable",
        "tasks": [],
        "decisions": [],
        "artifacts": [
            {
                "name": "architecture.md",
                "artifact_type": ArtifactType.DOCUMENT.value,
                "path": "docs/architecture.md",
                "content": "# Architecture",
                "metadata": {"source": "architect"},
            }
        ],
        "phase": "failed",
        "updated_at": "2026-03-22T10:09:00+00:00",
    }

    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))
    first_snapshot = loaded.snapshot()
    second_snapshot = loaded.snapshot()

    assert loaded.artifacts[0]["created_at"] == "2026-03-22T10:09:00+00:00"
    assert first_snapshot.artifacts[0].created_at == "2026-03-22T10:09:00+00:00"
    assert second_snapshot.artifacts[0].created_at == "2026-03-22T10:09:00+00:00"

    loaded.save()
    persisted = resolve_state_store(str(state_path)).load(str(state_path))

    assert persisted["artifacts"][0]["created_at"] == "2026-03-22T10:09:00+00:00"


@pytest.mark.parametrize("state_filename", ["legacy-load.json", "legacy-load.sqlite"])
def test_load_uses_loaded_path_as_state_file_when_legacy_payload_omits_it(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Keep saving to the loaded path",
        "tasks": [],
        "decisions": [],
        "artifacts": [],
    }

    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))

    assert loaded.state_file == str(state_path)


@pytest.mark.parametrize("state_filename", ["legacy-skips.json", "legacy-skips.sqlite"])
def test_load_infers_dependency_failed_skip_reason_for_legacy_tasks(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Recover legacy skip metadata",
        "tasks": [
            {
                "id": "arch",
                "title": "Architecture",
                "description": "Design",
                "assigned_to": "architect",
                "status": TaskStatus.FAILED.value,
                "output": "boom",
            },
            {
                "id": "docs",
                "title": "Docs",
                "description": "Document",
                "assigned_to": "docs_writer",
                "dependencies": ["arch"],
                "status": TaskStatus.SKIPPED.value,
                "output": "Skipped because dependency 'arch' failed",
            },
        ],
        "decisions": [],
        "artifacts": [],
    }

    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))

    assert loaded.get_task("docs").skip_reason_type == "dependency_failed"


@pytest.mark.parametrize("state_filename", ["legacy-manual-skips.json", "legacy-manual-skips.sqlite"])
def test_load_infers_manual_skip_reason_when_dependency_reason_does_not_match_graph(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Keep manual skips explicit",
        "tasks": [
            {
                "id": "arch",
                "title": "Architecture",
                "description": "Design",
                "assigned_to": "architect",
                "status": TaskStatus.FAILED.value,
                "output": "boom",
            },
            {
                "id": "docs",
                "title": "Docs",
                "description": "Document",
                "assigned_to": "docs_writer",
                "dependencies": [],
                "status": TaskStatus.SKIPPED.value,
                "output": "Skipped because dependency 'arch' failed",
            },
        ],
        "decisions": [],
        "artifacts": [],
    }

    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))

    assert loaded.get_task("docs").skip_reason_type == "manual"


@pytest.mark.parametrize("state_filename", ["legacy-nondict.json", "legacy-nondict.sqlite"])
def test_load_discards_non_dict_legacy_decisions_and_preserves_string_artifacts(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Normalize legacy containers",
        "tasks": [],
        "decisions": ["freeform note", {"topic": "arch", "decision": "Layered", "rationale": "Simple"}],
        "artifacts": ["README.md", {"name": "docs.md", "artifact_type": ArtifactType.DOCUMENT.value, "content": "# Docs"}],
        "updated_at": "2026-03-22T10:09:00+00:00",
    }

    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))

    assert len(loaded.decisions) == 1
    assert loaded.decisions[0]["at"] == "2026-03-22T10:09:00+00:00"
    assert loaded.artifacts[0] == "README.md"
    assert loaded.artifacts[1]["created_at"] == "2026-03-22T10:09:00+00:00"


def test_project_state_handles_missing_tasks_unresolved_dependencies_and_lightweight_decisions():
    project = ProjectState(project_name="Demo", goal="Build demo")
    blocked_task = Task(
        id="docs",
        title="Docs",
        description="Document",
        assigned_to="docs_writer",
        dependencies=["arch"],
    )
    retryable_task = Task(
        id="test",
        title="Tests",
        description="Test",
        assigned_to="qa_tester",
        attempts=1,
        retry_limit=2,
    )

    project.add_task(blocked_task)
    project.add_task(retryable_task)
    project.add_decision("architecture", "Layered", "Keeps dependencies isolated")

    assert project.get_task("missing") is None
    assert project.is_task_ready(blocked_task) is False
    assert project.should_retry_task("missing") is False
    assert project.should_retry_task("test") is True
    assert project.decisions[0]["topic"] == "architecture"
    assert project.decisions[0]["decision"] == "Layered"
    assert project.decisions[0]["rationale"] == "Keeps dependencies isolated"
    assert project.decisions[0]["at"]


def test_start_and_fail_task_ignore_unknown_task_ids():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    original_updated_at = project.updated_at
    project.start_task("missing")
    project.fail_task("missing", "boom")

    task = project.get_task("arch")

    assert task is not None
    assert task.status == TaskStatus.PENDING.value
    assert task.attempts == 0
    assert task.last_error is None
    assert project.updated_at == original_updated_at
    assert project.execution_events == []


def test_snapshot_skips_malformed_project_decisions_in_legacy_state():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        updated_at="2026-03-22T10:09:00+00:00",
        decisions=[
            "bad-decision-entry",
            {
                "topic": "architecture",
                "decision": "Use layered runtime",
                "rationale": "Keeps providers isolated",
            },
        ],
    )

    snapshot = project.snapshot()

    assert len(snapshot.decisions) == 1
    assert snapshot.decisions[0].topic == "architecture"
    assert snapshot.decisions[0].created_at == "2026-03-22T10:09:00+00:00"


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


def test_snapshot_uses_text_artifact_fallback_for_unknown_roles():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="ops",
            title="Operations handoff",
            description="Prepare release handoff",
            assigned_to="release_manager",
            status=TaskStatus.DONE.value,
            output="Ship checklist",
        )
    )

    result = project.snapshot().task_results["ops"]

    assert result.output is not None
    assert result.output.summary == "Ship checklist"
    assert result.output.artifacts[0].artifact_type == ArtifactType.TEXT
    assert result.output.artifacts[0].metadata["assigned_to"] == "release_manager"


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


def test_resume_failed_tasks_can_resume_only_failed_descendants_when_requested():
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

    resumed = project.resume_failed_tasks(include_failed_tasks=False, failed_task_ids=["arch"], additional_task_ids=["arch__repair_1"])

    assert resumed == ["review"]
    assert project.get_task("arch").status == TaskStatus.FAILED.value
    assert project.get_task("review").status == TaskStatus.PENDING.value
    assert project.execution_events[-1]["event"] == "workflow_resumed"
    assert project.execution_events[-1]["details"]["task_ids"] == ["review", "arch__repair_1"]


def test_create_repair_task_records_lineage_and_requeue_audit():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.FAILED.value,
            output="broken code",
        )
    )

    repair_task = project._create_repair_task(
        "code",
        "code_engineer",
        {"cycle": 1, "instruction": "Repair the code."},
    )

    assert repair_task is not None
    assert repair_task.id == "code__repair_1"
    assert repair_task.repair_origin_task_id == "code"
    assert repair_task.repair_attempt == 1
    assert repair_task.assigned_to == "code_engineer"
    assert project.get_task("code").history[-1]["event"] == "requeued"
    assert any(event["event"] == "task_repair_created" for event in project.execution_events)


def test_complete_task_syncs_repair_result_back_to_origin():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.FAILED.value,
            output="broken code",
            attempts=1,
        )
    )
    repair_task = project._create_repair_task(
        "code",
        "code_engineer",
        {"cycle": 1, "instruction": "Repair the code."},
    )

    project.start_task(repair_task.id)
    project.complete_task(repair_task.id, "def repaired() -> int:\n    return 1")

    origin = project.get_task("code")
    assert origin.status == TaskStatus.DONE.value
    assert origin.output == "def repaired() -> int:\n    return 1"
    assert origin.attempts == 2
    assert origin.history[-1]["event"] == "repaired"
    assert any(event["event"] == "task_repaired" for event in project.execution_events)


def test_fail_task_syncs_repair_failure_back_to_origin():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            status=TaskStatus.FAILED.value,
            output="broken tests",
            attempts=1,
        )
    )
    repair_task = project._create_repair_task(
        "tests",
        "qa_tester",
        {"cycle": 1, "instruction": "Repair the tests."},
    )

    project.start_task(repair_task.id)
    project.fail_task(repair_task.id, RuntimeError("pytest failed"), error_category="test_validation")

    origin = project.get_task("tests")
    assert origin.status == TaskStatus.FAILED.value
    assert origin.last_error == "pytest failed"
    assert origin.last_error_category == "test_validation"
    assert origin.attempts == 2
    assert origin.history[-1]["event"] == "repair_failed"


def test_fail_task_syncs_structured_repair_failure_payload_back_to_origin():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Write docs",
            assigned_to="docs_writer",
            status=TaskStatus.FAILED.value,
            output="broken docs",
            attempts=1,
        )
    )
    repair_task = project._create_repair_task(
        "docs",
        "docs_writer",
        {"cycle": 1, "instruction": "Repair the docs."},
    )

    project.start_task(repair_task.id)
    project.fail_task(
        repair_task.id,
        RuntimeError("markdown broken"),
        output=AgentOutput(summary="docs", raw_content="# repaired docs"),
        error_category="task_execution",
    )

    origin = project.get_task("docs")
    assert origin.output == "markdown broken"
    assert origin.output_payload is not None
    assert origin.output_payload["raw_content"] == "# repaired docs"


def test_resume_failed_tasks_records_workflow_resumed_for_additional_ids_without_failed_tasks():
    project = ProjectState(project_name="Demo", goal="Build demo")

    resumed = project.resume_failed_tasks(include_failed_tasks=False, failed_task_ids=[], additional_task_ids=["code__repair_1"])

    assert resumed == []
    assert project.workflow_last_resumed_at is not None
    assert project.execution_events[-1]["event"] == "workflow_resumed"
    assert project.execution_events[-1]["details"]["task_ids"] == ["code__repair_1"]


def test_resume_failed_tasks_without_failed_or_additional_ids_is_a_no_op():
    project = ProjectState(project_name="Demo", goal="Build demo")

    resumed = project.resume_failed_tasks(include_failed_tasks=False, failed_task_ids=[], additional_task_ids=[])

    assert resumed == []
    assert project.workflow_last_resumed_at is None
    assert project.execution_events == []


def test_fail_task_syncs_repair_retry_without_finalizing_origin_output():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Write docs",
            assigned_to="docs_writer",
            status=TaskStatus.FAILED.value,
            output="broken docs",
            attempts=1,
        )
    )
    repair_task = project._create_repair_task(
        "docs",
        "docs_writer",
        {"cycle": 1, "instruction": "Repair the docs."},
    )
    repair_task.retry_limit = 1

    project.start_task(repair_task.id)
    project.fail_task(
        repair_task.id,
        RuntimeError("markdown broken"),
        output=AgentOutput(summary="docs", raw_content="# repaired docs"),
        error_category="task_execution",
    )

    origin = project.get_task("docs")
    repair = project.get_task(repair_task.id)

    assert repair is not None
    assert repair.status == TaskStatus.PENDING.value
    assert origin is not None
    assert origin.status == TaskStatus.FAILED.value
    assert origin.output == "broken docs"
    assert origin.output_payload is None
    assert origin.completed_at is None
    assert origin.history[-1]["event"] == "repair_retry_scheduled"


def test_plan_task_repair_and_repair_helpers_ignore_missing_origin():
    project = ProjectState(project_name="Demo", goal="Build demo")

    project._plan_task_repair("missing", {"cycle": 1})
    missing = project._create_repair_task("missing", "code_engineer", {"cycle": 1})
    project._sync_repair_origin_start(Task(id="repair", title="Repair", description="Repair", assigned_to="code_engineer", repair_origin_task_id="missing"), "2026-03-22T10:00:00+00:00")
    project._sync_repair_origin_failure(
        Task(id="repair", title="Repair", description="Repair", assigned_to="code_engineer", repair_origin_task_id="missing"),
        error_message="boom",
        error_type="RuntimeError",
        provider_call=None,
        output=None,
        completed_at="2026-03-22T10:01:00+00:00",
        final_failure=True,
    )
    project._sync_repair_origin_completion(
        Task(id="repair", title="Repair", description="Repair", assigned_to="code_engineer", repair_origin_task_id="missing"),
        None,
    )

    assert missing is None
    assert project.execution_events == []


def test_create_repair_task_returns_existing_child_when_present():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.FAILED.value,
        )
    )
    first = project._create_repair_task("code", "code_engineer", {"cycle": 1})
    second = project._create_repair_task("code", "code_engineer", {"cycle": 1})

    assert first is second
    assert len([task for task in project.tasks if task.repair_origin_task_id == "code"]) == 1


def test_save_and_load_preserve_task_repair_context(tmp_path):
    state_path = tmp_path / "repair_context.json"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            repair_context={
                "cycle": 1,
                "failure_category": "code_validation",
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module.",
            },
        )
    )

    project.save()
    loaded = ProjectState.load(str(state_path))

    assert loaded.get_task("code").repair_context["cycle"] == 1
    assert loaded.get_task("code").repair_context["repair_owner"] == "code_engineer"


def test_snapshot_exposes_task_repair_context_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            status=TaskStatus.PENDING.value,
            repair_context={
                "cycle": 2,
                "failure_category": "test_validation",
                "instruction": "Repair the generated pytest suite.",
            },
        )
    )

    result = project.snapshot().task_results["tests"]

    assert result.details["repair_context"]["cycle"] == 2
    assert result.details["repair_context"]["failure_category"] == "test_validation"


def test_start_repair_cycle_updates_snapshot_and_execution_history():
    project = ProjectState(project_name="Demo", goal="Build demo", repair_max_cycles=2)

    entry = project.start_repair_cycle(
        reason="resume_failed_tasks",
        failure_category="test_validation",
        failed_task_ids=["tests"],
    )
    snapshot = project.snapshot()

    assert entry["cycle"] == 1
    assert entry["failure_category"] == "test_validation"
    assert entry["failed_task_ids"] == ["tests"]
    assert entry["budget_remaining"] == 1
    assert snapshot.repair_cycle_count == 1
    assert snapshot.repair_max_cycles == 2
    assert snapshot.repair_budget_remaining == 1
    assert snapshot.repair_history == [entry]
    assert project.execution_events[-1]["event"] == "workflow_repair_cycle_started"


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


def test_snapshot_preserves_failure_record_for_failed_task_without_output():
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
            last_error="provider timeout",
            last_error_type="TimeoutError",
            last_provider_call={"provider": "openai", "success": False},
            started_at="2026-03-22T10:00:00+00:00",
            last_attempt_started_at="2026-03-22T10:05:00+00:00",
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )

    result = project.snapshot().task_results["code"]

    assert result.status == TaskStatus.FAILED
    assert result.failure is not None
    assert result.failure.message == "provider timeout"
    assert result.failure.error_type == "TimeoutError"
    assert result.failure.category == "unknown"
    assert result.failure.details["provider_call"]["provider"] == "openai"


def test_snapshot_preserves_failure_category_and_terminal_outcome_fields():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        phase="failed",
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category="test_validation",
        acceptance_criteria_met=False,
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            status=TaskStatus.FAILED.value,
            last_error="pytest failed",
            last_error_type="AgentExecutionError",
            last_error_category="test_validation",
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )

    snapshot = project.snapshot()

    assert snapshot.terminal_outcome == WorkflowOutcome.FAILED.value
    assert snapshot.failure_category == "test_validation"
    assert snapshot.acceptance_criteria_met is False
    assert snapshot.task_results["tests"].failure is not None
    assert snapshot.task_results["tests"].failure.category == "test_validation"


def test_snapshot_ignores_malformed_output_payload_entries():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
            output_payload={
                "summary": "Architecture summary",
                "raw_content": "ARCHITECTURE DOC",
                "artifacts": [
                    "legacy-report.md",
                    123,
                    {"name": "architecture.md", "artifact_type": ArtifactType.DOCUMENT.value},
                ],
                "decisions": [
                    "bad-decision-entry",
                    {"topic": "runtime", "decision": "Persist snapshots", "rationale": "Supports resume"},
                ],
            },
        )
    )
    project.updated_at = "2026-03-22T10:09:00+00:00"

    result = project.snapshot().task_results["arch"]

    assert result.output is not None
    assert [artifact.name for artifact in result.output.artifacts] == ["legacy-report.md", "architecture.md"]
    assert result.output.artifacts[1].created_at == "2026-03-22T10:09:00+00:00"
    assert len(result.output.decisions) == 1
    assert result.output.decisions[0].decision == "Persist snapshots"


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
            {"event": "workflow_started", "timestamp": "2026-03-22T10:00:00+00:00", "task_id": None, "status": "execution", "details": {"acceptance_policy": "required_tasks"}},
            {"event": "workflow_finished", "timestamp": "2026-03-22T10:06:00+00:00", "task_id": None, "status": "completed", "details": {"workflow_duration_ms": 360000.0, "acceptance_policy": "required_tasks", "terminal_outcome": "completed", "failure_category": None, "acceptance_criteria_met": True, "acceptance_evaluation": {"policy": "required_tasks", "accepted": True, "required_task_ids": ["arch"], "completed_task_ids": ["arch"]}}},
        ],
        workflow_started_at="2026-03-22T10:00:00+00:00",
        workflow_finished_at="2026-03-22T10:06:00+00:00",
        workflow_last_resumed_at="2026-03-22T10:04:00+00:00",
        updated_at="2026-03-22T10:06:00+00:00",
        phase="completed",
        acceptance_policy="required_tasks",
        terminal_outcome="completed",
        acceptance_criteria_met=True,
        acceptance_evaluation={"policy": "required_tasks", "accepted": True, "required_task_ids": ["arch"], "completed_task_ids": ["arch"]},
    )

    snapshot = project.snapshot()

    assert snapshot.started_at == "2026-03-22T10:00:00+00:00"
    assert snapshot.finished_at == "2026-03-22T10:06:00+00:00"
    assert snapshot.last_resumed_at == "2026-03-22T10:04:00+00:00"
    assert snapshot.acceptance_policy == "required_tasks"
    assert snapshot.terminal_outcome == "completed"
    assert snapshot.acceptance_criteria_met is True
    assert snapshot.acceptance_evaluation["required_task_ids"] == ["arch"]
    assert snapshot.execution_events[0]["event"] == "workflow_started"
    assert snapshot.execution_events[1]["details"]["workflow_duration_ms"] == 360000.0
    assert snapshot.updated_at == "2026-03-22T10:06:00+00:00"


def test_snapshot_reports_completed_when_acceptance_policy_completes_with_optional_failures():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        phase="completed",
        acceptance_policy="required_tasks",
        terminal_outcome=WorkflowOutcome.COMPLETED.value,
        acceptance_criteria_met=True,
        workflow_started_at="2026-03-22T10:00:00+00:00",
        workflow_finished_at="2026-03-22T10:06:00+00:00",
        tasks=[
            Task(
                id="code",
                title="Implementation",
                description="Implement",
                assigned_to="code_engineer",
                required_for_acceptance=True,
                status=TaskStatus.DONE.value,
            ),
            Task(
                id="docs",
                title="Documentation",
                description="Document",
                assigned_to="docs_writer",
                status=TaskStatus.FAILED.value,
                output="boom",
            ),
        ],
    )

    assert project.snapshot().workflow_status == WorkflowStatus.COMPLETED


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


def test_load_rejects_invalid_top_level_project_state_payload(tmp_path):
    state_path = tmp_path / "invalid-project-state.json"
    resolve_state_store(str(state_path)).save(
        str(state_path),
        {
            "project_name": "Demo",
            "goal": "Build demo",
            "tasks": [],
            "unexpected_field": True,
        },
    )

    with pytest.raises(StatePersistenceError, match="Project state data is invalid"):
        ProjectState.load(str(state_path))


def test_legacy_skip_reason_helpers_treat_non_matching_dependency_messages_as_manual():
    project = ProjectState(project_name="Demo", goal="Build demo")
    task = Task(
        id="docs",
        title="Docs",
        description="Document",
        assigned_to="docs_writer",
        status=TaskStatus.SKIPPED.value,
        output="Skipped manually by operator",
    )

    assert project._extract_dependency_failed_task_id(task) is None
    assert project._matching_dependency_failed_reason_task_id(task) is None
    assert project._infer_legacy_skip_reason_type(task) == "manual"


def test_legacy_skip_reason_helpers_treat_non_failed_dependency_as_manual():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
        )
    )
    task = Task(
        id="docs",
        title="Docs",
        description="Document",
        assigned_to="docs_writer",
        dependencies=["arch"],
        status=TaskStatus.SKIPPED.value,
        output="Skipped because dependency 'arch' failed",
    )

    assert project._matching_dependency_failed_reason_task_id(task) == "arch"
    assert project._infer_legacy_skip_reason_type(task) == "manual"


def test_depends_on_task_handles_cycles_and_missing_dependencies_without_looping():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            dependencies=["code", "missing"],
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

    assert project._depends_on_task(project.get_task("arch"), "code") is True
    assert project._depends_on_task(project.get_task("arch"), "tests") is False


def test_skip_task_ignores_missing_task_ids_without_side_effects():
    project = ProjectState(project_name="Demo", goal="Build demo")

    project.skip_task("missing", "nothing to do")

    assert project.execution_events == []


def test_skip_dependent_tasks_ignores_non_pending_dependents():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.FAILED.value,
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Docs",
            description="Document",
            assigned_to="docs_writer",
            dependencies=["arch"],
            status=TaskStatus.DONE.value,
        )
    )

    skipped = project.skip_dependent_tasks("arch", "Skipped because dependency 'arch' failed")

    assert skipped == []
    assert project.get_task("docs").status == TaskStatus.DONE.value


def test_duration_ms_returns_none_for_invalid_timestamps():
    project = ProjectState(project_name="Demo", goal="Build demo")

    assert project._duration_ms("not-an-iso-date", "2026-03-22T10:06:00+00:00") is None


def test_snapshot_reports_failed_workflow_status_for_terminal_failed_outcome():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        workflow_finished_at="2026-03-22T10:06:00+00:00",
        terminal_outcome=WorkflowOutcome.FAILED.value,
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.FAILED.value,
        )
    )

    assert project.snapshot().workflow_status == WorkflowStatus.FAILED


def test_build_agent_output_handles_blank_output_and_summary_helper_returns_empty_string():
    project = ProjectState(project_name="Demo", goal="Build demo")
    task = Task(
        id="docs",
        title="Documentation",
        description="Document",
        assigned_to="docs_writer",
        status=TaskStatus.DONE.value,
        output=None,
    )

    output = project._build_agent_output(task)

    assert project._summarize_output("   \n\t") == ""
    assert output.summary == ""
    assert output.raw_content == ""
    assert output.metadata["status"] == TaskStatus.DONE.value


def test_project_summary_reports_done_task_counts():
    project = ProjectState(project_name="Demo", goal="Build demo", phase="running")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement",
            assigned_to="code_engineer",
            status=TaskStatus.PENDING.value,
        )
    )

    assert project.summary() == "Project: Demo | Phase: running | Tasks: 1/2 done"


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