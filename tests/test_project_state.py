import builtins
import json
import sqlite3
from typing import Any, cast

import pytest

from kycortex_agents.exceptions import StatePersistenceError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import PROJECT_STATE_SCHEMA_VERSION, ProjectState, Task
from kycortex_agents.memory.state_store import resolve_state_store
from kycortex_agents.types import AgentOutput, ArtifactRecord, ArtifactType, DecisionRecord, FailureCategory, TaskStatus, WorkflowOutcome, WorkflowStatus


def require_task(project: ProjectState, task_id: str) -> Task:
    task = project.get_task(task_id)
    assert task is not None
    return task


def require_artifact(artifacts: list[dict[str, Any] | str], index: int = 0) -> dict[str, Any]:
    artifact = artifacts[index]
    assert isinstance(artifact, dict)
    return artifact


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
    assert loaded.schema_version == PROJECT_STATE_SCHEMA_VERSION


def test_load_rejects_invalid_json(tmp_path):
    state_path = tmp_path / "broken.json"
    state_path.write_text("{not-valid-json", encoding="utf-8")

    with pytest.raises(StatePersistenceError, match="invalid JSON"):
        ProjectState.load(str(state_path))


def test_load_rejects_missing_file(tmp_path):
    state_path = tmp_path / "missing.json"

    with pytest.raises(StatePersistenceError, match="file not found"):
        ProjectState.load(str(state_path))


@pytest.mark.parametrize("state_filename", ["invalid-schema.json", "invalid-schema.sqlite"])
def test_project_state_load_errors_limit_public_path_to_filename(tmp_path, state_filename):
    public_dir = tmp_path / "tenant-private-root"
    public_dir.mkdir()
    state_path = public_dir / state_filename
    invalid_payload = {
        "project_name": "Invalid",
        "goal": "Reject invalid schema versions",
        "tasks": [],
        "decisions": [],
        "artifacts": [],
        "schema_version": "1",
    }

    resolve_state_store(str(state_path)).save(str(state_path), invalid_payload)

    with pytest.raises(StatePersistenceError) as exc_info:
        ProjectState.load(str(state_path))

    assert state_filename in str(exc_info.value)
    assert "tenant-private-root" not in str(exc_info.value)


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
    assert loaded.schema_version == PROJECT_STATE_SCHEMA_VERSION


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_save_persists_current_schema_version(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))

    project.save()

    persisted = resolve_state_store(str(state_path)).load(str(state_path))

    assert persisted["schema_version"] == PROJECT_STATE_SCHEMA_VERSION


@pytest.mark.parametrize("state_filename", ["legacy-schema.json", "legacy-schema.sqlite"])
def test_load_migrates_legacy_payloads_to_current_schema_version(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Keep compatibility",
        "tasks": [],
        "decisions": [],
        "artifacts": [],
        "phase": "init",
    }

    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))
    loaded.save()
    persisted = resolve_state_store(str(state_path)).load(str(state_path))

    assert loaded.schema_version == PROJECT_STATE_SCHEMA_VERSION
    assert persisted["schema_version"] == PROJECT_STATE_SCHEMA_VERSION


@pytest.mark.parametrize("state_filename", ["future-schema.json", "future-schema.sqlite"])
def test_load_rejects_future_schema_versions(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    future_payload = {
        "project_name": "Future",
        "goal": "Reject unsupported versions",
        "tasks": [],
        "decisions": [],
        "artifacts": [],
        "schema_version": PROJECT_STATE_SCHEMA_VERSION + 1,
    }

    resolve_state_store(str(state_path)).save(str(state_path), future_payload)

    with pytest.raises(StatePersistenceError, match="newer than supported version"):
        ProjectState.load(str(state_path))


@pytest.mark.parametrize("state_filename", ["invalid-schema.json", "invalid-schema.sqlite"])
def test_load_rejects_non_integer_schema_versions(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    invalid_payload = {
        "project_name": "Invalid",
        "goal": "Reject invalid schema versions",
        "tasks": [],
        "decisions": [],
        "artifacts": [],
        "schema_version": "1",
    }

    resolve_state_store(str(state_path)).save(str(state_path), invalid_payload)

    with pytest.raises(StatePersistenceError, match="schema version is invalid"):
        ProjectState.load(str(state_path))


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

    artifact = require_artifact(loaded.artifacts)
    assert artifact["created_at"] == "2026-03-22T10:09:00+00:00"
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

    docs_task = require_task(loaded, "docs")
    assert docs_task.skip_reason_type == "dependency_failed"


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

    docs_task = require_task(loaded, "docs")
    assert docs_task.skip_reason_type == "manual"


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
    artifact = require_artifact(loaded.artifacts, 1)
    assert artifact["created_at"] == "2026-03-22T10:09:00+00:00"


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
        decisions=cast(
            list[dict[str, Any]],
            [
                "bad-decision-entry",
                {
                    "topic": "architecture",
                    "decision": "Use layered runtime",
                    "rationale": "Keeps providers isolated",
                },
            ],
        ),
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
                DecisionRecord("stack", "Use FastAPI", "Fits the API use case")
            ],
            metadata={"agent_name": "Architect"},
        ),
    )

    task = require_task(project, "arch")
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
    assert "attempts" not in result.details["history"][-1]
    assert "has_attempts" not in result.details["history"][-1]
    assert "error_message" not in result.details["history"][-1]
    assert "has_error_message" not in result.details["history"][-1]


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

    artifact = require_artifact(loaded.artifacts)
    assert artifact["name"] == "architecture_doc"
    assert artifact["artifact_type"] == ArtifactType.DOCUMENT.value
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

    arch_task = require_task(loaded, "arch")
    assert arch_task.output_payload is not None
    assert arch_task.output_payload["summary"] == "Architecture summary"
    assert snapshot.task_results["arch"].output is not None
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

    artifact = require_artifact(loaded.artifacts)
    assert artifact["artifact_type"] == ArtifactType.TEST.value
    assert snapshot.artifacts[0].name == "generated_tests"
    assert snapshot.artifacts[0].content == "def test_example(): pass"
    assert snapshot.artifacts[0].metadata["source"] == "qa_tester"


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_save_redacts_secrets_from_persisted_state(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    project = ProjectState(
        project_name="Demo",
        goal="Build demo api_key=sk-secret-123456",
        state_file=str(state_path),
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement with Authorization: Bearer sk-ant-secret-987654",
            assigned_to="code_engineer",
        )
    )
    project.complete_task(
        "code",
        AgentOutput(
            summary="Summary api_key=sk-secret-123456",
            raw_content="api_key=sk-secret-123456\npassword=hunter2",
            artifacts=[
                ArtifactRecord(
                    name="code_implementation",
                    artifact_type=ArtifactType.CODE,
                    path="artifacts/code.py",
                    content="Authorization: Bearer sk-ant-secret-987654",
                    metadata={"notes": "api_key=sk-secret-123456"},
                )
            ],
            decisions=[
                DecisionRecord(
                    "security",
                    "Do not persist api_key=sk-secret-123456",
                    "Authorization: Bearer sk-ant-secret-987654",
                )
            ],
            metadata={"diagnostic": "password=hunter2"},
        ),
    )
    project.add_artifact_record(
        ArtifactRecord(
            name="audit",
            artifact_type=ArtifactType.TEXT,
            content="api_key=sk-secret-123456",
            metadata={"detail": "Authorization: Bearer sk-ant-secret-987654"},
        )
    )
    project._record_execution_event(
        event="manual_audit",
        details={"message": "password=hunter2", "provider_call": {"error_message": "api_key=sk-secret-123456"}},
    )

    project.save()
    persisted = resolve_state_store(str(state_path)).load(str(state_path))

    task_payload = persisted["tasks"][0]
    assert persisted["goal"] == "Build demo api_key=[REDACTED]"
    assert "sk-ant-secret-987654" not in task_payload["description"]
    assert "[REDACTED]" in task_payload["description"]
    assert "sk-secret-123456" not in task_payload["output"]
    assert "hunter2" not in task_payload["output"]
    assert "[REDACTED]" in task_payload["output_payload"]["raw_content"]
    assert "sk-ant-secret-987654" not in task_payload["output_payload"]["artifacts"][0]["content"]
    assert "[REDACTED]" in task_payload["output_payload"]["artifacts"][0]["content"]
    assert "sk-secret-123456" not in persisted["artifacts"][0]["content"]
    assert "[REDACTED]" in persisted["artifacts"][0]["content"]
    assert "hunter2" not in persisted["execution_events"][-1]["details"]["message"]


def test_snapshot_redacts_secrets_from_public_state_views():
    project = ProjectState(project_name="Demo", goal="Build demo api_key=sk-secret-123456")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="api_key=sk-secret-123456",
            output_payload={
                "summary": "Summary api_key=sk-secret-123456",
                "raw_content": "Authorization: Bearer sk-ant-secret-987654",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code.py",
                        "content": "password=hunter2",
                        "metadata": {"notes": "api_key=sk-secret-123456"},
                    }
                ],
                "decisions": [
                    {
                        "topic": "security",
                        "decision": "Authorization: Bearer sk-ant-secret-987654",
                        "rationale": "password=hunter2",
                    }
                ],
                "metadata": {"diagnostic": "api_key=sk-secret-123456"},
            },
        )
    )
    project.add_artifact_record(
        ArtifactRecord(
            name="audit",
            artifact_type=ArtifactType.TEXT,
            content="Authorization: Bearer sk-ant-secret-987654",
            metadata={"detail": "password=hunter2"},
        )
    )
    project.add_decision("security", "api_key=sk-secret-123456", "Authorization: Bearer sk-ant-secret-987654")
    project._record_execution_event(event="manual_audit", details={"message": "password=hunter2"})

    snapshot = project.snapshot()
    result = snapshot.task_results["code"]

    assert project.goal == "Build demo api_key=sk-secret-123456"
    assert snapshot.goal == "Build demo api_key=[REDACTED]"
    assert result.output is not None
    assert "sk-ant-secret-987654" not in result.output.raw_content
    assert "[REDACTED]" in result.output.raw_content
    assert result.output.artifacts[0].content is not None
    assert "hunter2" not in result.output.artifacts[0].content
    assert "[REDACTED]" in result.output.artifacts[0].content
    assert "sk-secret-123456" not in result.output.metadata["diagnostic"]
    assert "[REDACTED]" in result.output.metadata["diagnostic"]
    assert snapshot.artifacts[0].content is not None
    assert "sk-ant-secret-987654" not in snapshot.artifacts[0].content
    assert "[REDACTED]" in snapshot.artifacts[0].content
    assert "sk-secret-123456" not in snapshot.decisions[0].decision
    assert "[REDACTED]" in snapshot.decisions[0].decision
    assert "hunter2" not in snapshot.execution_events[0]["details"]["message"]


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


def test_fail_task_records_policy_enforcement_for_dependency_validation_retry():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="deps",
            title="Dependencies",
            description="Validate dependencies",
            assigned_to="dependency_manager",
            retry_limit=1,
        )
    )

    project.start_task("deps")
    project.fail_task(
        "deps",
        RuntimeError("Dependency manifest validation failed: unsupported dependency sources or installer directives"),
        error_category=FailureCategory.DEPENDENCY_VALIDATION.value,
    )

    policy_event = next(event for event in project.execution_events if event["event"] == "policy_enforcement")

    assert policy_event["task_id"] == "deps"
    assert policy_event["details"]["policy_area"] == "dependency_manifest"
    assert policy_event["details"]["source_event"] == "task_retry_scheduled"
    assert policy_event["details"]["failure_category"] == FailureCategory.DEPENDENCY_VALIDATION.value
    assert policy_event["details"]["retryable"] is True
    assert project.execution_events[-1]["event"] == "task_retry_scheduled"


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
    assert result.details["last_error_present"] is True
    assert "last_error" not in result.details
    assert result.details["history"][-1]["event"] == "retry_scheduled"
    assert result.details["history"][-1]["has_attempts"] is True
    assert "attempts" not in result.details["history"][-1]
    assert "error_message" not in result.details["history"][-1]
    assert "has_error_message" not in result.details["history"][-1]


def test_fail_task_redacts_live_failure_state_events_and_terminal_context():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
        )
    )

    project.mark_workflow_running(acceptance_policy="required_tasks", repair_max_cycles=1)
    project.start_task("tests")
    project.fail_task(
        "tests",
        RuntimeError("Authorization: Bearer sk-ant-secret-987654"),
        provider_call={
            "provider": "anthropic",
            "model": "claude-3-5-sonnet",
            "success": False,
            "base_url": "https://alice:secret-pass@example.com/messages",
            "error_message": "api_key=sk-secret-123456",
        },
        output=AgentOutput(summary="failure", raw_content="password=hunter2"),
        error_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
    )
    project.mark_workflow_finished(
        "failed",
        acceptance_policy="required_tasks",
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
        acceptance_criteria_met=False,
        acceptance_evaluation={"policy": "required_tasks", "accepted": False, "failed_task_ids": ["tests"]},
    )

    task = require_task(project, "tests")
    task_failed_event = next(event for event in project.execution_events if event["event"] == "task_failed")
    task_policy_event = next(
        event
        for event in project.execution_events
        if event["event"] == "policy_enforcement" and event["details"]["source_event"] == "task_failed"
    )
    workflow_policy_event = next(
        event
        for event in project.execution_events
        if event["event"] == "policy_enforcement" and event["details"]["source_event"] == "workflow_finished"
    )
    workflow_event = next(event for event in project.execution_events if event["event"] == "workflow_finished")

    assert "sk-ant-secret-987654" not in task.last_error
    assert "hunter2" not in task.output_payload["raw_content"]
    assert "secret-pass" not in str(task.last_provider_call)
    assert "sk-secret-123456" not in str(task.last_provider_call)
    assert "sk-ant-secret-987654" not in task.history[-1]["error_message"]
    assert "sk-ant-secret-987654" not in task_failed_event["details"]["error_message"]
    assert "secret-pass" not in str(task_failed_event["details"]["provider_call"])
    assert "sk-ant-secret-987654" not in task_policy_event["details"]["message"]
    assert "secret-pass" not in str(task_policy_event["details"]["provider_call"])
    assert "sk-ant-secret-987654" not in workflow_policy_event["details"]["message"]
    assert "secret-pass" not in str(workflow_policy_event["details"]["provider_call"])
    assert "sk-ant-secret-987654" not in workflow_event["details"]["failure_message"]
    assert "secret-pass" not in str(workflow_event["details"]["provider_call"])
    assert "[REDACTED]" in task.last_error
    assert task.output == task.last_error
    assert "[REDACTED]" in task.output_payload["raw_content"]
    assert "[REDACTED]" in task.last_provider_call["base_url"]
    assert task.last_provider_call["has_error_message"] is True
    assert "error_message" not in task.last_provider_call
    assert "[REDACTED]" in task.history[-1]["error_message"]
    assert task_failed_event["details"]["error_message"] == task.last_error
    assert task_policy_event["details"]["message"] == task.last_error
    assert workflow_policy_event["details"]["message"] == task.last_error
    assert workflow_event["details"]["failure_message"] == task.last_error
    assert "[REDACTED]" in workflow_event["details"]["provider_call"]["base_url"]
    assert workflow_event["details"]["provider_call"]["has_error_message"] is True
    assert "error_message" not in workflow_event["details"]["provider_call"]


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
    arch_task = require_task(project, "arch")
    review_task = require_task(project, "review")
    assert arch_task.status == TaskStatus.PENDING.value
    assert arch_task.output is None
    assert arch_task.history[-1]["event"] == "requeued"
    assert review_task.status == TaskStatus.PENDING.value
    assert review_task.output is None
    assert review_task.history[-1]["event"] == "requeued"


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
    snapshot = project.snapshot()

    assert resumed == ["review"]
    arch_task = require_task(project, "arch")
    review_task = require_task(project, "review")
    assert arch_task.status == TaskStatus.FAILED.value
    assert review_task.status == TaskStatus.PENDING.value
    assert project.execution_events[-1]["event"] == "workflow_resumed"
    assert project.execution_events[-1]["details"]["task_ids"] == ["review", "arch__repair_1"]
    assert snapshot.execution_events[-1]["details"]["reason"] == "failed_workflow"
    assert snapshot.execution_events[-1]["details"]["task_count"] == 2
    assert snapshot.execution_events[-1]["details"]["unique_task_count"] == 2
    assert "provider_budget" not in snapshot.execution_events[-1]["details"]
    assert "task_ids" not in snapshot.execution_events[-1]["details"]
    assert snapshot.workflow_telemetry["resume_summary"] == {
        "has_multiple_resume_events": False,
        "has_multiple_reasons": False,
        "has_multiple_resumed_tasks": True,
        "has_multiple_unique_tasks": True,
        "last_resumed_at": project.workflow_last_resumed_at,
    }


def test_record_workflow_progress_includes_task_status_and_preserves_explicit_provider_budget():
    project = ProjectState(project_name="Demo", goal="Build demo")

    project._record_execution_event(
        event="custom",
        details={"provider_budget": {"remaining_calls": 1}},
    )
    telemetry = project.record_workflow_progress(task_id="code", task_status=TaskStatus.RUNNING.value)

    assert project.execution_events[0]["details"]["provider_budget"] == {"remaining_calls": 1}
    assert project.execution_events[-1]["event"] == "workflow_progress"
    assert project.execution_events[-1]["task_id"] == "code"
    assert project.execution_events[-1]["details"]["task_status"] == TaskStatus.RUNNING.value
    assert project.execution_events[-1]["details"]["workflow_telemetry"] == telemetry
    assert "provider_budget" in project.execution_events[-1]["details"]

    project.record_workflow_progress(task_id="review")

    assert "task_status" not in project.execution_events[-1]["details"]


def test_snapshot_workflow_progress_minimizes_embedded_workflow_telemetry():
    project = ProjectState(project_name="Demo", goal="Build demo")

    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.RUNNING.value,
        )
    )

    project.record_workflow_progress(task_id="code", task_status=TaskStatus.RUNNING.value)

    snapshot = project.snapshot()
    progress_event = snapshot.execution_events[-1]

    assert progress_event["event"] == "workflow_progress"
    assert progress_event["details"]["task_status"] == TaskStatus.RUNNING.value
    assert progress_event["details"]["has_workflow_telemetry"] is True
    assert "workflow_telemetry" not in progress_event["details"]
    assert "provider_budget" not in progress_event["details"]


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
    code_task = require_task(project, "code")
    assert code_task.history[-1]["event"] == "requeued"
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
    assert repair_task is not None

    project.start_task(repair_task.id)
    project.complete_task(
        repair_task.id,
        "def repaired() -> int:\n    return 1",
        provider_call={
            "provider": "openai",
            "model": "gpt-4o",
            "success": True,
            "base_url": "https://alice:secret-pass@example.com/v1",
            "provider_health": {
                "openai": {
                    "status": "healthy",
                    "last_outcome": "success",
                    "last_health_check": {
                        "status": "ready",
                        "provider": "openai",
                        "model": "gpt-4o",
                        "backend_reachable": True,
                        "base_url": "https://alice:secret-pass@example.com/v1",
                        "checked_at": 123.0,
                        "timeout_seconds": 4.5,
                        "active_check": True,
                        "cooldown_cached": False,
                    },
                }
            },
        },
    )

    origin = require_task(project, "code")
    repaired_task = require_task(project, repair_task.id)
    repaired_provider_call = cast(dict[str, Any], repaired_task.last_provider_call)
    origin_provider_call = cast(dict[str, Any], origin.last_provider_call)
    assert origin.status == TaskStatus.DONE.value
    assert origin.output == "def repaired() -> int:\n    return 1"
    assert origin.attempts == 2
    assert origin.history[-1]["event"] == "repaired"
    assert "secret-pass" not in str(repaired_provider_call)
    assert "secret-pass" not in str(origin_provider_call)
    assert "[REDACTED]" in repaired_provider_call["base_url"]
    assert "[REDACTED]" in origin_provider_call["base_url"]
    assert "provider" not in repaired_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "provider" not in origin_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "model" not in repaired_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "model" not in origin_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "backend_reachable" not in repaired_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "backend_reachable" not in origin_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "base_url" not in repaired_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "base_url" not in origin_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "checked_at" not in repaired_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "checked_at" not in origin_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "timeout_seconds" not in repaired_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "timeout_seconds" not in origin_provider_call["provider_health"]["openai"]["last_health_check"]
    internal_repaired_event = next(event for event in project.execution_events if event["event"] == "task_repaired")
    assert internal_repaired_event["details"]["assigned_to"] == "code_engineer"

    snapshot = project.snapshot()
    repaired_event = next(event for event in snapshot.execution_events if event["event"] == "task_repaired")

    assert repaired_event["details"]["repair_attempt"] == 1
    assert repaired_event["details"]["has_assigned_to"] is True
    assert repaired_event["details"]["has_repair_task"] is True
    assert "assigned_to" not in repaired_event["details"]
    assert "repair_task_id" not in repaired_event["details"]


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
    assert repair_task is not None

    project.start_task(repair_task.id)
    project.fail_task(repair_task.id, RuntimeError("pytest failed"), error_category="test_validation")

    origin = require_task(project, "tests")
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
    assert repair_task is not None

    project.start_task(repair_task.id)
    project.fail_task(
        repair_task.id,
        RuntimeError("markdown broken"),
        output=AgentOutput(summary="docs", raw_content="# repaired docs"),
        error_category="task_execution",
    )

    origin = require_task(project, "docs")
    assert origin.output == "markdown broken"
    assert origin.output_payload is not None
    assert origin.output_payload["raw_content"] == "# repaired docs"


def test_fail_task_syncs_redacted_repair_failure_back_to_origin():
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
    assert repair_task is not None

    project.start_task(repair_task.id)
    project.fail_task(
        repair_task.id,
        RuntimeError("password=hunter2"),
        provider_call={
            "provider": "openai",
            "model": "gpt-4o",
            "success": False,
            "base_url": "https://alice:secret-pass@example.com/v1",
            "error_message": "api_key=sk-secret-123456",
        },
        output=AgentOutput(summary="docs", raw_content="Authorization: Bearer sk-ant-secret-987654"),
        error_category=FailureCategory.TASK_EXECUTION.value,
    )

    origin = require_task(project, "docs")

    assert "hunter2" not in origin.last_error
    assert origin.output == origin.last_error
    assert origin.output_payload is not None
    assert "sk-ant-secret-987654" not in origin.output_payload["raw_content"]
    assert "secret-pass" not in str(origin.last_provider_call)
    assert "sk-secret-123456" not in str(origin.last_provider_call)
    assert "hunter2" not in origin.history[-1]["error_message"]
    assert "[REDACTED]" in origin.last_error
    assert "[REDACTED]" in origin.output_payload["raw_content"]
    assert "[REDACTED]" in origin.last_provider_call["base_url"]
    assert origin.last_provider_call["has_error_message"] is True
    assert "error_message" not in origin.last_provider_call
    assert "[REDACTED]" in origin.history[-1]["error_message"]
    assert origin.history[-1]["event"] == "repair_failed"


def test_resume_failed_tasks_records_workflow_resumed_for_additional_ids_without_failed_tasks():
    project = ProjectState(project_name="Demo", goal="Build demo")

    resumed = project.resume_failed_tasks(include_failed_tasks=False, failed_task_ids=[], additional_task_ids=["code__repair_1"])
    snapshot = project.snapshot()

    assert resumed == []
    assert project.workflow_last_resumed_at is not None
    assert project.execution_events[-1]["event"] == "workflow_resumed"
    assert project.execution_events[-1]["details"]["task_ids"] == ["code__repair_1"]
    assert snapshot.execution_events[-1]["details"]["reason"] == "failed_workflow"
    assert snapshot.execution_events[-1]["details"]["task_count"] == 1
    assert snapshot.execution_events[-1]["details"]["unique_task_count"] == 1
    assert "provider_budget" not in snapshot.execution_events[-1]["details"]
    assert "task_ids" not in snapshot.execution_events[-1]["details"]


def test_pause_workflow_marks_snapshot_paused_and_suppresses_runnable_tasks():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
        )
    )
    project.mark_workflow_running()

    changed = project.pause_workflow(reason="manual_operator_pause")
    snapshot = project.snapshot()

    assert changed is True
    assert project.phase == WorkflowStatus.PAUSED.value
    assert project.workflow_paused_at is not None
    assert project.workflow_pause_reason == "manual_operator_pause"
    assert snapshot.workflow_status == WorkflowStatus.PAUSED
    assert project.runnable_tasks() == []
    assert project.execution_events[-1]["event"] == "workflow_paused"
    assert project.execution_events[-1]["details"]["reason"] == "manual_operator_pause"


def test_pause_workflow_redacts_sensitive_operator_reason():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
        )
    )
    project.mark_workflow_running()

    changed = project.pause_workflow(reason="api_key=sk-secret-123456")

    assert changed is True
    assert "sk-secret-123456" not in project.workflow_pause_reason
    assert "[REDACTED]" in project.workflow_pause_reason
    assert "sk-secret-123456" not in project.execution_events[-1]["details"]["reason"]
    assert "[REDACTED]" in project.execution_events[-1]["details"]["reason"]


def test_cancel_workflow_marks_terminal_state_and_skips_pending_tasks():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Write docs",
            assigned_to="docs_writer",
        )
    )

    cancelled_task_ids = project.cancel_workflow(reason="manual_operator_cancel")
    snapshot = project.snapshot()

    assert cancelled_task_ids == ["docs"]
    assert require_task(project, "arch").status == TaskStatus.DONE.value
    assert require_task(project, "docs").status == TaskStatus.SKIPPED.value
    assert require_task(project, "docs").skip_reason_type == "workflow_cancelled"
    assert require_task(project, "docs").output == "manual_operator_cancel"
    assert project.phase == WorkflowStatus.CANCELLED.value
    assert project.terminal_outcome == WorkflowOutcome.CANCELLED.value
    assert project.failure_category == FailureCategory.WORKFLOW_CANCELLED.value
    assert project.acceptance_criteria_met is False
    assert snapshot.workflow_status == WorkflowStatus.CANCELLED
    assert project.execution_events[-1]["event"] == "workflow_cancelled"
    assert project.execution_events[-1]["details"]["reason"] == "manual_operator_cancel"
    assert project.execution_events[-1]["details"]["cancelled_task_ids"] == ["docs"]
    assert snapshot.execution_events[-1]["details"]["reason"] == "manual_operator_cancel"
    assert snapshot.execution_events[-1]["details"]["terminal_outcome"] == WorkflowOutcome.CANCELLED.value
    assert snapshot.execution_events[-1]["details"]["cancelled_task_count"] == 1
    assert "provider_budget" not in snapshot.execution_events[-1]["details"]
    assert "cancelled_task_ids" not in snapshot.execution_events[-1]["details"]


def test_cancel_workflow_redacts_sensitive_operator_reason():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Write docs",
            assigned_to="docs_writer",
        )
    )

    cancelled_task_ids = project.cancel_workflow(reason="password=hunter2")
    task = require_task(project, "docs")
    task_cancelled_event = next(event for event in project.execution_events if event["event"] == "task_cancelled")
    workflow_cancelled_event = next(event for event in project.execution_events if event["event"] == "workflow_cancelled")
    snapshot = project.snapshot()

    assert cancelled_task_ids == ["docs"]
    assert "hunter2" not in task.last_error
    assert "hunter2" not in task.output
    assert "hunter2" not in task_cancelled_event["details"]["reason"]
    assert "hunter2" not in workflow_cancelled_event["details"]["reason"]
    assert "[REDACTED]" in task.last_error
    assert task.output == task.last_error
    assert "[REDACTED]" in task_cancelled_event["details"]["reason"]
    assert "[REDACTED]" in workflow_cancelled_event["details"]["reason"]
    assert snapshot.execution_events[-1]["details"]["reason"] == workflow_cancelled_event["details"]["reason"]
    assert snapshot.execution_events[-1]["details"]["terminal_outcome"] == WorkflowOutcome.CANCELLED.value
    assert snapshot.execution_events[-1]["details"]["cancelled_task_count"] == 1
    assert "provider_budget" not in snapshot.execution_events[-1]["details"]
    assert "cancelled_task_ids" not in snapshot.execution_events[-1]["details"]


def test_pause_workflow_rejects_cancelled_workflow():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
        )
    )
    project.cancel_workflow(reason="manual_operator_cancel")

    with pytest.raises(ValueError, match="finished workflow"):
        project.pause_workflow(reason="manual_operator_pause")


def test_override_task_marks_task_done_and_records_manual_override_event():
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

    changed = project.override_task("arch", "MANUAL ARCHITECTURE", reason="manual_operator_override")
    task = require_task(project, "arch")

    assert changed is True
    assert task.status == TaskStatus.DONE.value
    assert task.output == "MANUAL ARCHITECTURE"
    assert task.last_error is None
    assert task.history[-1]["event"] == "overridden"
    assert task.history[-1]["error_message"] == "manual_operator_override"
    assert project.execution_events[-1]["event"] == "task_overridden"
    assert project.execution_events[-1]["details"]["reason"] == "manual_operator_override"


def test_replay_workflow_resets_base_tasks_and_clears_run_metadata():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        decisions=[{"topic": "stack", "decision": "typed", "rationale": "safe", "at": "2026-03-22T10:00:00+00:00"}],
        artifacts=[{"name": "architecture.md", "artifact_type": ArtifactType.DOCUMENT.value, "created_at": "2026-03-22T10:00:00+00:00"}],
        phase="completed",
        terminal_outcome=WorkflowOutcome.COMPLETED.value,
        acceptance_criteria_met=True,
        acceptance_evaluation={"accepted": True},
        workflow_started_at="2026-03-22T10:00:00+00:00",
        workflow_finished_at="2026-03-22T10:05:00+00:00",
        workflow_paused_at="2026-03-22T10:03:00+00:00",
        workflow_pause_reason="manual_pause",
        workflow_last_resumed_at="2026-03-22T10:04:00+00:00",
        repair_cycle_count=1,
        repair_max_cycles=2,
        repair_history=[{"cycle": 1, "reason": "resume_failed_tasks"}],
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            attempts=2,
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
            completed_at="2026-03-22T10:05:00+00:00",
        )
    )

    replayed_task_ids = project.replay_workflow(reason="manual_replay")
    task = require_task(project, "arch")
    snapshot = project.snapshot()

    assert replayed_task_ids == ["arch"]
    assert task.status == TaskStatus.PENDING.value
    assert task.attempts == 0
    assert task.output is None
    assert task.completed_at is None
    assert task.history[-1]["event"] == "replayed"
    assert project.decisions == []
    assert project.artifacts == []
    assert project.phase == "init"
    assert project.terminal_outcome is None
    assert project.workflow_started_at is None
    assert project.workflow_finished_at is None
    assert project.workflow_paused_at is None
    assert project.workflow_pause_reason is None
    assert project.workflow_last_resumed_at is None
    assert project.repair_cycle_count == 0
    assert project.repair_history == []
    assert project.execution_events[-1]["event"] == "workflow_replayed"
    assert project.execution_events[-1]["details"]["reason"] == "manual_replay"
    assert snapshot.execution_events[-1]["details"]["reason"] == "manual_replay"
    assert snapshot.execution_events[-1]["details"]["replayed_task_count"] == 1
    assert snapshot.execution_events[-1]["details"]["removed_task_count"] == 0
    assert snapshot.execution_events[-1]["details"]["cleared_decision_count"] == 1
    assert snapshot.execution_events[-1]["details"]["cleared_artifact_count"] == 1
    assert "provider_budget" not in snapshot.execution_events[-1]["details"]
    assert "replayed_task_ids" not in snapshot.execution_events[-1]["details"]
    assert "removed_task_ids" not in snapshot.execution_events[-1]["details"]
    assert snapshot.workflow_status == WorkflowStatus.INIT


def test_replay_workflow_removes_repair_lineage_tasks():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement",
            assigned_to="code_engineer",
            status=TaskStatus.FAILED.value,
            output="boom",
        )
    )
    project.add_task(
        Task(
            id="code__repair_1",
            title="Repair Implementation",
            description="Repair",
            assigned_to="code_engineer",
            repair_origin_task_id="code",
            repair_attempt=1,
            status=TaskStatus.FAILED.value,
            output="still boom",
        )
    )
    project.add_task(
        Task(
            id="code__repair_1__budget_plan",
            title="Budget plan",
            description="Plan",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="PLAN",
        )
    )

    replayed_task_ids = project.replay_workflow(reason="manual_replay")
    snapshot = project.snapshot()

    assert replayed_task_ids == ["code"]
    assert [task.id for task in project.tasks] == ["code"]
    assert project.execution_events[-1]["details"]["removed_task_ids"] == ["code__repair_1", "code__repair_1__budget_plan"]
    assert snapshot.execution_events[-1]["details"]["reason"] == "manual_replay"
    assert snapshot.execution_events[-1]["details"]["replayed_task_count"] == 1
    assert snapshot.execution_events[-1]["details"]["removed_task_count"] == 2
    assert snapshot.execution_events[-1]["details"]["cleared_decision_count"] == 0
    assert snapshot.execution_events[-1]["details"]["cleared_artifact_count"] == 0
    assert "provider_budget" not in snapshot.execution_events[-1]["details"]
    assert "replayed_task_ids" not in snapshot.execution_events[-1]["details"]
    assert "removed_task_ids" not in snapshot.execution_events[-1]["details"]


def test_resume_workflow_clears_pause_state_and_records_resume_summary():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
        )
    )
    project.mark_workflow_running()
    project.pause_workflow(reason="manual_operator_pause")

    changed = project.resume_workflow(reason="paused_workflow")
    snapshot = project.snapshot()

    assert changed is True
    assert project.phase == "execution"
    assert project.workflow_paused_at is None
    assert project.workflow_pause_reason is None
    assert project.workflow_last_resumed_at is not None
    assert snapshot.workflow_status == WorkflowStatus.INIT
    assert project.execution_events[-1]["event"] == "workflow_resumed"
    assert project.execution_events[-1]["details"]["reason"] == "paused_workflow"
    assert project.execution_events[-1]["details"]["task_ids"] == []
    assert project.execution_events[-1]["details"]["provider_budget"] is None
    assert snapshot.execution_events[-1]["details"]["reason"] == "paused_workflow"
    assert snapshot.execution_events[-1]["details"]["task_count"] == 0
    assert snapshot.execution_events[-1]["details"]["unique_task_count"] == 0
    assert "provider_budget" not in snapshot.execution_events[-1]["details"]
    assert "task_ids" not in snapshot.execution_events[-1]["details"]
    assert snapshot.workflow_telemetry["resume_summary"] == {
        "has_multiple_resume_events": False,
        "has_multiple_reasons": False,
        "has_multiple_resumed_tasks": False,
        "has_multiple_unique_tasks": False,
        "last_resumed_at": project.workflow_last_resumed_at,
    }


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
    assert repair_task is not None
    repair_task.retry_limit = 1

    project.start_task(repair_task.id)
    project.fail_task(
        repair_task.id,
        RuntimeError("markdown broken"),
        output=AgentOutput(summary="docs", raw_content="# repaired docs"),
        error_category="task_execution",
    )

    origin = require_task(project, "docs")
    repair = require_task(project, repair_task.id)
    internal_retry_event = next(event for event in project.execution_events if event["event"] == "task_repair_retry_scheduled")
    snapshot = project.snapshot()
    retry_event = next(event for event in snapshot.execution_events if event["event"] == "task_repair_retry_scheduled")

    assert repair.status == TaskStatus.PENDING.value
    assert origin.status == TaskStatus.FAILED.value
    assert origin.output == "broken docs"
    assert origin.output_payload is None
    assert origin.completed_at is None
    assert origin.history[-1]["event"] == "repair_retry_scheduled"
    assert internal_retry_event["details"]["error_type"] == "RuntimeError"
    assert retry_event["details"]["has_repair_task"] is True
    assert retry_event["details"]["has_error_type"] is True
    assert "repair_task_id" not in retry_event["details"]
    assert "error_type" not in retry_event["details"]


def test_snapshot_task_repair_retry_scheduled_events_use_presence_flags_for_legacy_error_type_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_repair_retry_scheduled",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "docs",
                "status": "failed",
                "details": {
                    "repair_task_id": "docs__repair_1",
                    "repair_attempt": 1,
                    "error_type": "RuntimeError",
                    "error_category": "task_execution",
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    retry_event = snapshot.execution_events[0]

    assert retry_event["event"] == "task_repair_retry_scheduled"
    assert retry_event["details"]["has_repair_task"] is True
    assert retry_event["details"]["has_error_type"] is True
    assert "repair_task_id" not in retry_event["details"]
    assert "error_type" not in retry_event["details"]


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
        output_payload=None,
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

    code_task = require_task(loaded, "code")
    assert code_task.repair_context["cycle"] == 1
    assert code_task.repair_context["repair_owner"] == "code_engineer"


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
                "repair_owner": "qa_tester",
                "original_assigned_to": "qa_tester",
                "helper_surface_usages": ["RiskScoringService (line 33)"],
                "helper_surface_symbols": ["RiskScoringService"],
                "decomposition_mode": "budget_compaction_planner",
                "decomposition_target_agent": "architect",
                "decomposition_failure_category": "test_validation",
                "failure_message": "Generated pytest suite failed validation.",
                "failure_error_type": "PytestCollectionError",
                "failed_artifact_content": "def test_generated_suite():\n    assert False",
                "failed_output": "def test_generated_suite():\n    assert False",
                "validation_summary": "Generated test validation:\n- Pytest collection failed",
                "existing_tests": "def test_existing_suite():\n    assert True",
            },
        )
    )

    result = project.snapshot().task_results["tests"]

    assert result.details["repair_context"]["cycle"] == 2
    assert result.details["repair_context"]["failure_category"] == "test_validation"
    assert result.details["repair_context"]["has_failed_artifact_content"] is True
    assert result.details["repair_context"]["has_instruction"] is True
    assert result.details["repair_context"]["has_repair_owner"] is True
    assert result.details["repair_context"]["has_original_assigned_to"] is True
    assert result.details["repair_context"]["has_helper_surface_usages"] is True
    assert result.details["repair_context"]["has_helper_surface_symbols"] is True
    assert result.details["repair_context"]["has_decomposition_mode"] is True
    assert result.details["repair_context"]["has_decomposition_target_agent"] is True
    assert result.details["repair_context"]["has_decomposition_failure_category"] is True
    assert result.details["repair_context"]["has_failure_message"] is True
    assert result.details["repair_context"]["has_failure_error_type"] is True
    assert result.details["repair_context"]["has_failed_output"] is True
    assert result.details["repair_context"]["has_validation_summary"] is True
    assert result.details["repair_context"]["has_existing_tests"] is True
    assert "failed_artifact_content" not in result.details["repair_context"]
    assert "instruction" not in result.details["repair_context"]
    assert "repair_owner" not in result.details["repair_context"]
    assert "original_assigned_to" not in result.details["repair_context"]
    assert "helper_surface_usages" not in result.details["repair_context"]
    assert "helper_surface_symbols" not in result.details["repair_context"]
    assert "decomposition_mode" not in result.details["repair_context"]
    assert "decomposition_target_agent" not in result.details["repair_context"]
    assert "decomposition_failure_category" not in result.details["repair_context"]
    assert "failure_message" not in result.details["repair_context"]
    assert "failure_error_type" not in result.details["repair_context"]
    assert "failed_output" not in result.details["repair_context"]
    assert "validation_summary" not in result.details["repair_context"]
    assert "existing_tests" not in result.details["repair_context"]


def test_snapshot_minimizes_public_task_repair_lineage_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests__repair_2",
            title="Repair tests",
            description="Repair tests",
            assigned_to="qa_tester",
            status=TaskStatus.FAILED.value,
            output="repair failed",
            last_error="repair failed",
            last_error_type="RuntimeError",
            last_error_category=FailureCategory.TEST_VALIDATION.value,
            repair_origin_task_id="tests",
            repair_attempt=2,
            repair_context={
                "cycle": 2,
                "failure_category": "test_validation",
                "instruction": "Repair the generated pytest suite.",
                "repair_owner": "qa_tester",
                "original_assigned_to": "qa_tester",
                "helper_surface_usages": ["RiskScoringService (line 33)"],
                "helper_surface_symbols": ["RiskScoringService"],
                "decomposition_mode": "budget_compaction_planner",
                "decomposition_target_agent": "architect",
                "decomposition_failure_category": "test_validation",
                "failure_message": "Generated pytest suite failed validation.",
                "failure_error_type": "PytestCollectionError",
                "failed_artifact_content": "def test_generated_suite():\n    assert False",
                "failed_output": "def test_generated_suite():\n    assert False",
                "validation_summary": "Generated test validation:\n- Pytest collection failed",
                "existing_tests": "def test_existing_suite():\n    assert True",
                "source_failure_task_id": "tests",
                "budget_decomposition_plan_task_id": "tests__repair_2__budget_plan",
                "provider_call": {"provider": "openai", "success": False},
            },
        )
    )

    result = project.snapshot().task_results["tests__repair_2"]

    assert result.details["repair_context"]["cycle"] == 2
    assert result.details["repair_context"]["failure_category"] == "test_validation"
    assert result.details["repair_context"]["has_failed_artifact_content"] is True
    assert result.details["repair_context"]["has_instruction"] is True
    assert result.details["repair_context"]["has_repair_owner"] is True
    assert result.details["repair_context"]["has_original_assigned_to"] is True
    assert result.details["repair_context"]["has_helper_surface_usages"] is True
    assert result.details["repair_context"]["has_helper_surface_symbols"] is True
    assert result.details["repair_context"]["has_decomposition_mode"] is True
    assert result.details["repair_context"]["has_decomposition_target_agent"] is True
    assert result.details["repair_context"]["has_decomposition_failure_category"] is True
    assert result.details["repair_context"]["has_failure_message"] is True
    assert result.details["repair_context"]["has_failure_error_type"] is True
    assert result.details["repair_context"]["has_source_failure_task"] is True
    assert result.details["repair_context"]["has_budget_decomposition_plan"] is True
    assert result.details["repair_context"]["has_provider_call"] is True
    assert result.details["repair_context"]["has_validation_summary"] is True
    assert result.details["repair_context"]["has_existing_tests"] is True
    assert result.details["repair_context"]["has_failed_output"] is True
    assert "failed_artifact_content" not in result.details["repair_context"]
    assert "instruction" not in result.details["repair_context"]
    assert "repair_owner" not in result.details["repair_context"]
    assert "original_assigned_to" not in result.details["repair_context"]
    assert "helper_surface_usages" not in result.details["repair_context"]
    assert "helper_surface_symbols" not in result.details["repair_context"]
    assert "decomposition_mode" not in result.details["repair_context"]
    assert "decomposition_target_agent" not in result.details["repair_context"]
    assert "decomposition_failure_category" not in result.details["repair_context"]
    assert "failure_message" not in result.details["repair_context"]
    assert "failure_error_type" not in result.details["repair_context"]
    assert "failed_output" not in result.details["repair_context"]
    assert "source_failure_task_id" not in result.details["repair_context"]
    assert "budget_decomposition_plan_task_id" not in result.details["repair_context"]
    assert "provider_call" not in result.details["repair_context"]
    assert "validation_summary" not in result.details["repair_context"]
    assert "existing_tests" not in result.details["repair_context"]
    assert result.details["has_repair_origin"] is True
    assert "repair_origin_task_id" not in result.details
    assert result.failure is not None
    assert result.failure.details["repair_context"]["has_failed_artifact_content"] is True
    assert result.failure.details["repair_context"]["has_instruction"] is True
    assert result.failure.details["repair_context"]["has_repair_owner"] is True
    assert result.failure.details["repair_context"]["has_original_assigned_to"] is True
    assert result.failure.details["repair_context"]["has_helper_surface_usages"] is True
    assert result.failure.details["repair_context"]["has_helper_surface_symbols"] is True
    assert result.failure.details["repair_context"]["has_decomposition_mode"] is True
    assert result.failure.details["repair_context"]["has_decomposition_target_agent"] is True
    assert result.failure.details["repair_context"]["has_decomposition_failure_category"] is True
    assert result.failure.details["repair_context"]["has_failure_message"] is True
    assert result.failure.details["repair_context"]["has_failure_error_type"] is True
    assert result.failure.details["repair_context"]["has_source_failure_task"] is True
    assert result.failure.details["repair_context"]["has_budget_decomposition_plan"] is True
    assert result.failure.details["repair_context"]["has_provider_call"] is True
    assert result.failure.details["repair_context"]["has_validation_summary"] is True
    assert result.failure.details["repair_context"]["has_existing_tests"] is True
    assert result.failure.details["repair_context"]["has_failed_output"] is True
    assert "failed_artifact_content" not in result.failure.details["repair_context"]
    assert "instruction" not in result.failure.details["repair_context"]
    assert "repair_owner" not in result.failure.details["repair_context"]
    assert "original_assigned_to" not in result.failure.details["repair_context"]
    assert "helper_surface_usages" not in result.failure.details["repair_context"]
    assert "helper_surface_symbols" not in result.failure.details["repair_context"]
    assert "decomposition_mode" not in result.failure.details["repair_context"]
    assert "decomposition_target_agent" not in result.failure.details["repair_context"]
    assert "decomposition_failure_category" not in result.failure.details["repair_context"]
    assert "failure_message" not in result.failure.details["repair_context"]
    assert "failure_error_type" not in result.failure.details["repair_context"]
    assert "failed_output" not in result.failure.details["repair_context"]
    assert "source_failure_task_id" not in result.failure.details["repair_context"]
    assert "budget_decomposition_plan_task_id" not in result.failure.details["repair_context"]
    assert "provider_call" not in result.failure.details["repair_context"]
    assert "validation_summary" not in result.failure.details["repair_context"]
    assert "existing_tests" not in result.failure.details["repair_context"]
    assert result.failure.details["has_repair_origin"] is True
    assert "repair_origin_task_id" not in result.failure.details


def test_snapshot_minimizes_public_repair_lineage_event_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement",
            assigned_to="code_engineer",
            status=TaskStatus.FAILED.value,
            output="broken code",
        )
    )
    repair_context = {
        "cycle": 1,
        "failure_category": FailureCategory.CODE_VALIDATION.value,
        "instruction": "Repair the generated Python module.",
        "repair_owner": "code_engineer",
        "original_assigned_to": "code_engineer",
        "helper_surface_usages": ["RiskScoringService (line 33)"],
        "helper_surface_symbols": ["RiskScoringService"],
        "decomposition_mode": "budget_compaction_planner",
        "decomposition_target_agent": "architect",
        "decomposition_failure_category": "code_validation",
        "failure_message": "Generated module failed import validation.",
        "failure_error_type": "ImportError",
        "failed_artifact_content": "def broken():\n    return missing_symbol",
        "failed_output": "def broken():\n    return missing_symbol",
        "validation_summary": "Generated code validation:\n- Syntax OK: no",
        "existing_tests": "def test_broken():\n    assert broken() == 1",
        "source_failure_task_id": "tests",
        "provider_call": {"provider": "openai", "success": False, "provider_call_count": 2},
    }

    decomposition_task = project._create_budget_decomposition_task("code", repair_context)
    assert decomposition_task is not None
    repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
    project._plan_task_repair("code", repair_context)
    repair_task = project._create_repair_task("code", "code_engineer", repair_context)
    assert repair_task is not None
    project.start_task(repair_task.id)
    project.fail_task(repair_task.id, RuntimeError("repair failed"), error_category=FailureCategory.CODE_VALIDATION.value)

    internal_decomposition_event = next(
        event for event in project.execution_events if event["event"] == "task_budget_decomposition_created"
    )
    internal_created_event = next(event for event in project.execution_events if event["event"] == "task_repair_created")
    internal_started_event = next(event for event in project.execution_events if event["event"] == "task_repair_started")
    assert internal_decomposition_event["details"]["assigned_to"] == "architect"
    assert internal_created_event["details"]["assigned_to"] == "code_engineer"
    assert internal_started_event["details"]["assigned_to"] == "code_engineer"

    snapshot = project.snapshot()
    planned_event = next(event for event in snapshot.execution_events if event["event"] == "task_repair_planned")
    decomposition_event = next(event for event in snapshot.execution_events if event["event"] == "task_budget_decomposition_created")
    created_event = next(event for event in snapshot.execution_events if event["event"] == "task_repair_created")
    requeued_event = next(
        event
        for event in snapshot.execution_events
        if event["event"] == "task_requeued" and event["details"].get("has_repair_task") is True
    )
    started_event = next(event for event in snapshot.execution_events if event["event"] == "task_repair_started")
    failed_event = next(event for event in snapshot.execution_events if event["event"] == "task_repair_failed")

    assert planned_event["details"]["has_source_failure_task"] is True
    assert planned_event["details"]["has_budget_decomposition_plan"] is True
    assert planned_event["details"]["has_provider_call"] is True
    assert planned_event["details"]["instruction"] == "Repair the generated Python module."
    assert planned_event["details"]["repair_owner"] == "code_engineer"
    assert planned_event["details"]["original_assigned_to"] == "code_engineer"
    assert planned_event["details"]["helper_surface_usages"] == ["RiskScoringService (line 33)"]
    assert planned_event["details"]["helper_surface_symbols"] == ["RiskScoringService"]
    assert planned_event["details"]["decomposition_mode"] == "budget_compaction_planner"
    assert planned_event["details"]["decomposition_target_agent"] == "architect"
    assert planned_event["details"]["decomposition_failure_category"] == "code_validation"
    assert planned_event["details"]["failed_artifact_content"] == "def broken():\n    return missing_symbol"
    assert planned_event["details"]["failure_message"] == "Generated module failed import validation."
    assert planned_event["details"]["failure_error_type"] == "ImportError"
    assert planned_event["details"]["failed_output"] == "def broken():\n    return missing_symbol"
    assert planned_event["details"]["validation_summary"] == "Generated code validation:\n- Syntax OK: no"
    assert planned_event["details"]["existing_tests"] == "def test_broken():\n    assert broken() == 1"
    assert "source_failure_task_id" not in planned_event["details"]
    assert "budget_decomposition_plan_task_id" not in planned_event["details"]
    assert "provider_call" not in planned_event["details"]
    assert "provider_budget" not in planned_event["details"]

    assert decomposition_event["details"]["has_assigned_to"] is True
    assert decomposition_event["details"]["has_decomposition_target_task"] is True
    assert "assigned_to" not in decomposition_event["details"]
    assert "decomposition_target_task_id" not in decomposition_event["details"]

    assert created_event["details"]["has_assigned_to"] is True
    assert created_event["details"]["has_repair_origin"] is True
    assert "assigned_to" not in created_event["details"]
    assert "repair_origin_task_id" not in created_event["details"]

    assert requeued_event["details"]["has_repair_task"] is True
    assert "repair_task_id" not in requeued_event["details"]

    assert started_event["details"]["has_assigned_to"] is True
    assert started_event["details"]["has_repair_task"] is True
    assert "assigned_to" not in started_event["details"]
    assert "repair_task_id" not in started_event["details"]

    assert failed_event["details"]["has_repair_task"] is True
    assert failed_event["details"]["has_error_type"] is True
    assert "error_type" not in failed_event["details"]
    assert "repair_task_id" not in failed_event["details"]


def test_snapshot_task_repair_created_events_use_presence_flags_for_legacy_assigned_to_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_repair_created",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "code__repair_1",
                "status": "pending",
                "details": {
                    "repair_origin_task_id": "code",
                    "repair_attempt": 1,
                    "assigned_to": "code_engineer",
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    created_event = snapshot.execution_events[0]

    assert created_event["event"] == "task_repair_created"
    assert created_event["details"]["repair_attempt"] == 1
    assert created_event["details"]["has_assigned_to"] is True
    assert created_event["details"]["has_repair_origin"] is True
    assert "assigned_to" not in created_event["details"]
    assert "repair_origin_task_id" not in created_event["details"]


def test_snapshot_task_repair_started_events_use_presence_flags_for_legacy_assigned_to_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_repair_started",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "code",
                "status": "running",
                "details": {
                    "repair_task_id": "code__repair_1",
                    "repair_attempt": 1,
                    "assigned_to": "code_engineer",
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    started_event = snapshot.execution_events[0]

    assert started_event["event"] == "task_repair_started"
    assert started_event["details"]["repair_attempt"] == 1
    assert started_event["details"]["has_assigned_to"] is True
    assert started_event["details"]["has_repair_task"] is True
    assert "assigned_to" not in started_event["details"]
    assert "repair_task_id" not in started_event["details"]


def test_snapshot_task_budget_decomposition_events_use_presence_flags_for_legacy_assigned_to_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_budget_decomposition_created",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "code__repair_1__budget_plan",
                "status": "pending",
                "details": {
                    "decomposition_target_task_id": "code",
                    "repair_attempt": 1,
                    "assigned_to": "architect",
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    decomposition_event = snapshot.execution_events[0]

    assert decomposition_event["event"] == "task_budget_decomposition_created"
    assert decomposition_event["details"]["repair_attempt"] == 1
    assert decomposition_event["details"]["has_assigned_to"] is True
    assert decomposition_event["details"]["has_decomposition_target_task"] is True
    assert "assigned_to" not in decomposition_event["details"]
    assert "decomposition_target_task_id" not in decomposition_event["details"]


def test_snapshot_task_repaired_events_use_presence_flags_for_legacy_assigned_to_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_repaired",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "code",
                "status": "done",
                "details": {
                    "repair_task_id": "code__repair_1",
                    "repair_attempt": 1,
                    "assigned_to": "code_engineer",
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    repaired_event = snapshot.execution_events[0]

    assert repaired_event["event"] == "task_repaired"
    assert repaired_event["details"]["repair_attempt"] == 1
    assert repaired_event["details"]["has_assigned_to"] is True
    assert repaired_event["details"]["has_repair_task"] is True
    assert "assigned_to" not in repaired_event["details"]
    assert "repair_task_id" not in repaired_event["details"]


def test_snapshot_task_repair_failed_events_use_presence_flags_for_legacy_error_type_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_repair_failed",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "code",
                "status": "failed",
                "details": {
                    "repair_task_id": "repair-code",
                    "repair_attempt": 1,
                    "error_type": "RuntimeError",
                    "error_category": FailureCategory.CODE_VALIDATION.value,
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    failed_event = snapshot.execution_events[0]

    assert failed_event["event"] == "task_repair_failed"
    assert failed_event["details"]["has_repair_task"] is True
    assert failed_event["details"]["has_error_type"] is True
    assert "repair_task_id" not in failed_event["details"]
    assert "error_type" not in failed_event["details"]


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
    assert snapshot.repair_history == [
        {
            "cycle": 1,
            "started_at": entry["started_at"],
            "reason": "resume_failed_tasks",
            "failure_category": "test_validation",
            "has_failed_tasks": True,
            "budget_remaining": 1,
        }
    ]
    assert project.execution_events[-1]["event"] == "workflow_repair_cycle_started"
    assert snapshot.execution_events[-1]["details"]["cycle"] == 1
    assert snapshot.execution_events[-1]["details"]["started_at"] == entry["started_at"]
    assert snapshot.execution_events[-1]["details"]["reason"] == "resume_failed_tasks"
    assert snapshot.execution_events[-1]["details"]["failure_category"] == "test_validation"
    assert snapshot.execution_events[-1]["details"]["has_failed_tasks"] is True
    assert snapshot.execution_events[-1]["details"]["budget_remaining"] == 1
    assert "provider_budget" not in snapshot.execution_events[-1]["details"]
    assert "failed_task_ids" not in snapshot.execution_events[-1]["details"]
    assert snapshot.workflow_telemetry["repair_summary"] == {
        "has_repair_cycles": True,
        "max_cycles": 2,
        "budget_remaining": 1,
        "has_multiple_history_entries": False,
        "has_multiple_reasons": False,
        "last_reason_present": True,
        "has_multiple_failure_categories": False,
        "has_failed_tasks": True,
    }


def test_repair_summary_aggregates_repair_reasons_across_cycles():
    project = ProjectState(project_name="Demo", goal="Build demo", repair_max_cycles=3)

    project.start_repair_cycle(
        reason="resume_failed_tasks",
        failure_category="test_validation",
        failed_task_ids=["tests"],
    )
    project.start_repair_cycle(
        reason="manual_retry",
        failure_category="dependency_validation",
        failed_task_ids=["deps", "tests"],
    )

    assert project.snapshot().workflow_telemetry["repair_summary"] == {
        "has_repair_cycles": True,
        "max_cycles": 3,
        "budget_remaining": 1,
        "has_multiple_history_entries": True,
        "has_multiple_reasons": True,
        "last_reason_present": True,
        "has_multiple_failure_categories": True,
        "has_failed_tasks": True,
    }


def test_repair_summary_ignores_malformed_entries_and_non_list_failed_task_ids():
    project = ProjectState(project_name="Demo", goal="Build demo", repair_max_cycles=5)
    project.repair_cycle_count = 2
    project.repair_history = cast(
        list[dict[str, Any]],
        [
            None,
            {"reason": 7, "failure_category": ["bad"], "failed_task_ids": "tests"},
            {
                "reason": "manual_retry",
                "failure_category": "test_validation",
                "failed_task_ids": ["tests", "", None, "code"],
            },
        ],
    )

    assert project._repair_summary() == {
        "has_repair_cycles": True,
        "max_cycles": 5,
        "budget_remaining": 3,
        "has_multiple_history_entries": True,
        "has_multiple_reasons": False,
        "last_reason_present": True,
        "has_multiple_failure_categories": False,
        "has_failed_tasks": True,
    }


def test_snapshot_repair_history_uses_failed_task_presence_for_legacy_entries():
    project = ProjectState(project_name="Demo", goal="Build demo", repair_max_cycles=2)
    project.repair_cycle_count = 1
    project.repair_history = cast(
        list[dict[str, Any]],
        [
            {
                "cycle": 1,
                "started_at": "2026-03-22T10:01:00+00:00",
                "reason": "resume_failed_tasks",
                "failure_category": "test_validation",
                "failed_task_ids": ["tests"],
                "budget_remaining": 1,
            }
        ],
    )
    project.execution_events = [
        {
            "event": "workflow_repair_cycle_started",
            "timestamp": "2026-03-22T10:01:00+00:00",
            "task_id": None,
            "status": "execution",
            "details": {
                "cycle": 1,
                "started_at": "2026-03-22T10:01:00+00:00",
                "reason": "resume_failed_tasks",
                "failure_category": "test_validation",
                "failed_task_ids": ["tests"],
                "budget_remaining": 1,
            },
        }
    ]

    snapshot = project.snapshot()

    assert snapshot.repair_history == [
        {
            "cycle": 1,
            "started_at": "2026-03-22T10:01:00+00:00",
            "reason": "resume_failed_tasks",
            "failure_category": "test_validation",
            "has_failed_tasks": True,
            "budget_remaining": 1,
        }
    ]
    assert snapshot.execution_events[0]["details"]["cycle"] == 1
    assert snapshot.execution_events[0]["details"]["started_at"] == "2026-03-22T10:01:00+00:00"
    assert snapshot.execution_events[0]["details"]["reason"] == "resume_failed_tasks"
    assert snapshot.execution_events[0]["details"]["failure_category"] == "test_validation"
    assert snapshot.execution_events[0]["details"]["has_failed_tasks"] is True
    assert snapshot.execution_events[0]["details"]["budget_remaining"] == 1
    assert "provider_budget" not in snapshot.execution_events[0]["details"]
    assert "failed_task_ids" not in snapshot.execution_events[0]["details"]


def test_snapshot_workflow_resumed_events_use_task_counts_for_legacy_entries():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.execution_events = [
        {
            "event": "workflow_resumed",
            "timestamp": "2026-03-22T10:01:00+00:00",
            "task_id": None,
            "status": "execution",
            "details": {
                "reason": "failed_workflow",
                "task_ids": ["tests__repair_1", "tests__repair_1", "review"],
            },
        }
    ]

    snapshot = project.snapshot()

    assert snapshot.execution_events[0]["details"]["reason"] == "failed_workflow"
    assert snapshot.execution_events[0]["details"]["task_count"] == 3
    assert snapshot.execution_events[0]["details"]["unique_task_count"] == 2
    assert "provider_budget" not in snapshot.execution_events[0]["details"]
    assert "task_ids" not in snapshot.execution_events[0]["details"]
    assert snapshot.workflow_telemetry["resume_summary"] == {
        "has_multiple_resume_events": False,
        "has_multiple_reasons": False,
        "has_multiple_resumed_tasks": True,
        "has_multiple_unique_tasks": True,
        "last_resumed_at": None,
    }


def test_snapshot_workflow_cancelled_events_use_task_counts_for_legacy_entries():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.execution_events = [
        {
            "event": "workflow_cancelled",
            "timestamp": "2026-03-22T10:01:00+00:00",
            "task_id": None,
            "status": WorkflowStatus.CANCELLED.value,
            "details": {
                "reason": "manual_operator_cancel",
                "cancelled_task_ids": ["docs", "review"],
                "terminal_outcome": WorkflowOutcome.CANCELLED.value,
            },
        }
    ]

    snapshot = project.snapshot()

    assert snapshot.execution_events[0]["details"]["reason"] == "manual_operator_cancel"
    assert snapshot.execution_events[0]["details"]["terminal_outcome"] == WorkflowOutcome.CANCELLED.value
    assert snapshot.execution_events[0]["details"]["cancelled_task_count"] == 2
    assert "provider_budget" not in snapshot.execution_events[0]["details"]
    assert "cancelled_task_ids" not in snapshot.execution_events[0]["details"]


def test_snapshot_workflow_replayed_events_use_task_counts_for_legacy_entries():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.execution_events = [
        {
            "event": "workflow_replayed",
            "timestamp": "2026-03-22T10:01:00+00:00",
            "task_id": None,
            "status": "init",
            "details": {
                "reason": "manual_replay",
                "replayed_task_ids": ["arch", "code"],
                "removed_task_ids": ["code__repair_1"],
                "cleared_decision_count": 2,
                "cleared_artifact_count": 3,
            },
        }
    ]

    snapshot = project.snapshot()

    assert snapshot.execution_events[0]["details"]["reason"] == "manual_replay"
    assert snapshot.execution_events[0]["details"]["replayed_task_count"] == 2
    assert snapshot.execution_events[0]["details"]["removed_task_count"] == 1
    assert snapshot.execution_events[0]["details"]["cleared_decision_count"] == 2
    assert snapshot.execution_events[0]["details"]["cleared_artifact_count"] == 3
    assert "provider_budget" not in snapshot.execution_events[0]["details"]
    assert "replayed_task_ids" not in snapshot.execution_events[0]["details"]
    assert "removed_task_ids" not in snapshot.execution_events[0]["details"]


def test_provider_attempt_and_retry_helpers_handle_scalar_fallbacks():
    project = ProjectState(project_name="Demo", goal="Build demo")

    assert project._provider_attempt_count({"attempt_history": "bad", "attempts_used": 2.9}) == 2
    assert project._provider_attempt_count({"attempt_history": "bad", "attempts_used": True}) == 0
    assert project._provider_retry_attempt_count({"attempt_history": "bad"}, 1) == 0
    assert project._provider_retry_attempt_count({"attempt_history": "bad"}, 4) == 3


def test_mark_workflow_finished_records_acceptance_summary_in_workflow_telemetry():
    project = ProjectState(project_name="Demo", goal="Build demo")

    project.mark_workflow_running(acceptance_policy="required_tasks", repair_max_cycles=1)
    project.mark_workflow_finished(
        "completed",
        acceptance_policy="required_tasks",
        terminal_outcome=WorkflowOutcome.COMPLETED.value,
        acceptance_criteria_met=True,
        acceptance_evaluation={
            "policy": "required_tasks",
            "accepted": True,
            "reason": "all_required_tasks_done",
            "evaluated_task_ids": ["arch", "code"],
            "required_task_ids": ["arch"],
            "completed_task_ids": ["arch", "code"],
            "failed_task_ids": [],
            "skipped_task_ids": [],
            "pending_task_ids": [],
        },
    )

    event = project.execution_events[-1]
    snapshot = project.snapshot()

    assert event["event"] == "workflow_finished"
    assert event["details"]["acceptance_evaluation"] == {
        "policy": "required_tasks",
        "accepted": True,
        "reason": "all_required_tasks_done",
        "terminal_outcome": WorkflowOutcome.COMPLETED.value,
        "failure_category": None,
        "has_evaluated_tasks": True,
        "has_required_tasks": True,
        "has_completed_tasks": True,
        "has_failed_tasks": False,
        "has_skipped_tasks": False,
        "has_pending_tasks": False,
    }
    assert event["details"]["workflow_telemetry"]["acceptance_summary"] == {
        "policy": "required_tasks",
        "accepted": True,
        "reason": "all_required_tasks_done",
        "terminal_outcome": WorkflowOutcome.COMPLETED.value,
        "failure_category": None,
        "has_evaluated_tasks": True,
        "has_required_tasks": True,
        "has_completed_tasks": True,
        "has_failed_tasks": False,
        "has_skipped_tasks": False,
        "has_pending_tasks": False,
    }
    assert snapshot.workflow_telemetry["acceptance_summary"] == event["details"]["workflow_telemetry"]["acceptance_summary"]


def test_mark_workflow_finished_records_policy_enforcement_for_security_failures():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            status=TaskStatus.FAILED.value,
            output="sandbox policy blocked filesystem write outside sandbox root",
            last_error="sandbox policy blocked filesystem write outside sandbox root",
            last_error_type="RuntimeError",
            last_error_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )

    project.mark_workflow_running(acceptance_policy="required_tasks", repair_max_cycles=1)
    project.mark_workflow_finished(
        "failed",
        acceptance_policy="required_tasks",
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
        acceptance_criteria_met=False,
        acceptance_evaluation={"policy": "required_tasks", "accepted": False, "failed_task_ids": ["tests"]},
    )

    policy_event = next(event for event in project.execution_events if event["event"] == "policy_enforcement")
    workflow_event = next(event for event in project.execution_events if event["event"] == "workflow_finished")

    assert policy_event["task_id"] == "tests"
    assert policy_event["details"]["policy_area"] == "sandbox"
    assert policy_event["details"]["source_event"] == "workflow_finished"
    assert policy_event["details"]["failure_category"] == FailureCategory.SANDBOX_SECURITY_VIOLATION.value
    assert policy_event["details"]["message"] == "sandbox policy blocked filesystem write outside sandbox root"
    assert policy_event["details"]["error_type"] == "RuntimeError"
    assert policy_event["details"]["terminal_outcome"] == WorkflowOutcome.FAILED.value
    assert workflow_event["details"]["acceptance_evaluation"] == {
        "policy": "required_tasks",
        "accepted": False,
        "reason": None,
        "terminal_outcome": WorkflowOutcome.FAILED.value,
        "failure_category": FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
        "has_evaluated_tasks": False,
        "has_required_tasks": False,
        "has_completed_tasks": False,
        "has_failed_tasks": True,
        "has_skipped_tasks": False,
        "has_pending_tasks": False,
    }
    assert workflow_event["details"]["failure_task_id"] == "tests"
    assert workflow_event["details"]["failure_message"] == "sandbox policy blocked filesystem write outside sandbox root"
    assert workflow_event["details"]["failure_error_type"] == "RuntimeError"
    assert project.execution_events[-1]["event"] == "workflow_finished"


def test_snapshot_minimizes_public_policy_enforcement_provider_call_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            retry_limit=0,
        )
    )

    project.mark_workflow_running(acceptance_policy="required_tasks", repair_max_cycles=1)
    project.start_task("tests")
    project.fail_task(
        "tests",
        RuntimeError("provider call failed"),
        provider_call={
            "provider": "openai",
            "model": "gpt-4o",
            "success": False,
            "base_url": "https://example.com/v1",
        },
        error_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
    )

    internal_policy_event = next(event for event in project.execution_events if event["event"] == "policy_enforcement")
    assert internal_policy_event["details"]["provider_call"]["provider"] == "openai"

    snapshot = project.snapshot()
    policy_event = next(event for event in snapshot.execution_events if event["event"] == "policy_enforcement")

    assert policy_event["details"]["policy_area"] == "sandbox"
    assert policy_event["details"]["source_event"] == "task_failed"
    assert policy_event["details"]["failure_category"] == FailureCategory.SANDBOX_SECURITY_VIOLATION.value
    assert policy_event["details"]["has_message"] is True
    assert policy_event["details"]["has_error_type"] is True
    assert policy_event["details"]["has_provider_call"] is True
    assert "message" not in policy_event["details"]
    assert "error_type" not in policy_event["details"]
    assert "provider_call" not in policy_event["details"]


def test_snapshot_policy_enforcement_events_use_presence_flags_for_legacy_provider_call_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "policy_enforcement",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "tests",
                "status": "failed",
                "details": {
                    "policy_area": "sandbox",
                    "source_event": "task_failed",
                    "failure_category": FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
                    "message": "provider call failed",
                    "error_type": "RuntimeError",
                    "provider_call": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "success": False,
                    },
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    policy_event = snapshot.execution_events[0]

    assert policy_event["event"] == "policy_enforcement"
    assert policy_event["details"]["policy_area"] == "sandbox"
    assert policy_event["details"]["source_event"] == "task_failed"
    assert policy_event["details"]["failure_category"] == FailureCategory.SANDBOX_SECURITY_VIOLATION.value
    assert policy_event["details"]["has_message"] is True
    assert policy_event["details"]["has_error_type"] is True
    assert policy_event["details"]["has_provider_call"] is True
    assert "message" not in policy_event["details"]
    assert "error_type" not in policy_event["details"]
    assert "provider_call" not in policy_event["details"]


def test_snapshot_minimizes_public_task_completed_provider_call_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    project.start_task("arch")
    project.complete_task(
        "arch",
        "ARCHITECTURE DOC",
        provider_call={
            "provider": "openai",
            "model": "gpt-4o",
            "success": True,
            "base_url": "https://alice:secret-pass@example.com/v1",
            "provider_health": {
                "openai": {
                    "status": "healthy",
                    "last_outcome": "success",
                    "last_health_check": {
                        "status": "ready",
                        "provider": "openai",
                        "model": "gpt-4o",
                        "backend_reachable": True,
                        "base_url": "https://alice:secret-pass@example.com/v1",
                        "checked_at": 123.0,
                        "timeout_seconds": 4.5,
                        "active_check": True,
                        "cooldown_cached": False,
                    },
                }
            },
        },
    )

    task = require_task(project, "arch")
    task_provider_call = cast(dict[str, Any], task.last_provider_call)
    internal_completed_event = next(event for event in project.execution_events if event["event"] == "task_completed")
    assert internal_completed_event["details"]["assigned_to"] == "architect"
    assert internal_completed_event["details"]["provider_call"]["provider"] == "openai"
    assert "secret-pass" not in str(task_provider_call)
    assert "secret-pass" not in str(internal_completed_event["details"]["provider_call"])
    assert "[REDACTED]" in task_provider_call["base_url"]
    assert "[REDACTED]" in internal_completed_event["details"]["provider_call"]["base_url"]
    assert "provider" not in task_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "provider" not in internal_completed_event["details"]["provider_call"]["provider_health"]["openai"]["last_health_check"]
    assert "model" not in task_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "model" not in internal_completed_event["details"]["provider_call"]["provider_health"]["openai"]["last_health_check"]
    assert "backend_reachable" not in task_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "backend_reachable" not in internal_completed_event["details"]["provider_call"]["provider_health"]["openai"]["last_health_check"]
    assert "base_url" not in task_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "base_url" not in internal_completed_event["details"]["provider_call"]["provider_health"]["openai"]["last_health_check"]
    assert "checked_at" not in task_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "checked_at" not in internal_completed_event["details"]["provider_call"]["provider_health"]["openai"]["last_health_check"]
    assert "timeout_seconds" not in task_provider_call["provider_health"]["openai"]["last_health_check"]
    assert "timeout_seconds" not in internal_completed_event["details"]["provider_call"]["provider_health"]["openai"]["last_health_check"]

    snapshot = project.snapshot()
    completed_event = next(event for event in snapshot.execution_events if event["event"] == "task_completed")

    assert completed_event["details"]["has_assigned_to"] is True
    assert completed_event["details"]["has_provider_call"] is True
    assert "assigned_to" not in completed_event["details"]
    assert "provider_call" not in completed_event["details"]


def test_snapshot_task_completed_events_use_presence_flags_for_legacy_provider_call_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_completed",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "arch",
                "status": "done",
                "details": {
                    "attempts": 1,
                    "assigned_to": "architect",
                    "provider_call": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "success": True,
                    },
                    "last_attempt_duration_ms": 1234.0,
                    "task_duration_ms": 2345.0,
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    completed_event = snapshot.execution_events[0]

    assert completed_event["event"] == "task_completed"
    assert completed_event["details"]["has_assigned_to"] is True
    assert completed_event["details"]["has_provider_call"] is True
    assert completed_event["details"]["last_attempt_duration_ms"] == 1234.0
    assert completed_event["details"]["task_duration_ms"] == 2345.0
    assert "assigned_to" not in completed_event["details"]
    assert "provider_call" not in completed_event["details"]


def test_snapshot_minimizes_public_task_started_assigned_to_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    project.start_task("arch")

    internal_started_event = next(event for event in project.execution_events if event["event"] == "task_started")
    assert internal_started_event["details"]["assigned_to"] == "architect"
    assert internal_started_event["details"]["provider_budget"] is None

    snapshot = project.snapshot()
    started_event = next(event for event in snapshot.execution_events if event["event"] == "task_started")

    assert started_event["details"]["has_assigned_to"] is True
    assert started_event["details"]["attempts"] == 1
    assert "assigned_to" not in started_event["details"]
    assert "provider_budget" not in started_event["details"]


def test_snapshot_task_started_events_use_presence_flags_for_legacy_assigned_to_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_started",
                "timestamp": "2026-03-22T10:05:00+00:00",
                "task_id": "arch",
                "status": "running",
                "details": {
                    "attempts": 1,
                    "assigned_to": "architect",
                    "provider_budget": None,
                },
            }
        ],
        updated_at="2026-03-22T10:05:00+00:00",
    )

    snapshot = project.snapshot()
    started_event = snapshot.execution_events[0]

    assert started_event["event"] == "task_started"
    assert started_event["details"]["has_assigned_to"] is True
    assert started_event["details"]["attempts"] == 1
    assert "assigned_to" not in started_event["details"]
    assert "provider_budget" not in started_event["details"]


def test_snapshot_minimizes_public_task_completed_assigned_to_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    project.start_task("arch")
    project.complete_task("arch", "ARCHITECTURE DOC")

    internal_completed_event = next(event for event in project.execution_events if event["event"] == "task_completed")
    assert internal_completed_event["details"]["assigned_to"] == "architect"

    snapshot = project.snapshot()
    completed_event = next(event for event in snapshot.execution_events if event["event"] == "task_completed")

    assert completed_event["details"]["has_assigned_to"] is True
    assert "assigned_to" not in completed_event["details"]


def test_snapshot_task_completed_events_use_presence_flags_for_legacy_assigned_to_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_completed",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "arch",
                "status": "done",
                "details": {
                    "attempts": 1,
                    "assigned_to": "architect",
                    "last_attempt_duration_ms": 1234.0,
                    "task_duration_ms": 2345.0,
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    completed_event = snapshot.execution_events[0]

    assert completed_event["event"] == "task_completed"
    assert completed_event["details"]["has_assigned_to"] is True
    assert completed_event["details"]["last_attempt_duration_ms"] == 1234.0
    assert completed_event["details"]["task_duration_ms"] == 2345.0
    assert "assigned_to" not in completed_event["details"]


def test_snapshot_minimizes_public_task_failed_provider_call_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            retry_limit=0,
        )
    )

    project.mark_workflow_running(acceptance_policy="required_tasks", repair_max_cycles=1)
    project.start_task("tests")
    project.fail_task(
        "tests",
        RuntimeError("provider call failed"),
        provider_call={
            "provider": "openai",
            "model": "gpt-4o",
            "success": False,
            "base_url": "https://example.com/v1",
        },
        error_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
    )

    internal_task_failed_event = next(event for event in project.execution_events if event["event"] == "task_failed")
    assert internal_task_failed_event["details"]["provider_call"]["provider"] == "openai"

    snapshot = project.snapshot()
    task_failed_event = next(event for event in snapshot.execution_events if event["event"] == "task_failed")

    assert task_failed_event["details"]["has_error_message"] is True
    assert task_failed_event["details"]["has_error_type"] is True
    assert task_failed_event["details"]["has_provider_call"] is True
    assert "error_message" not in task_failed_event["details"]
    assert "error_type" not in task_failed_event["details"]
    assert "provider_call" not in task_failed_event["details"]


def test_snapshot_task_failed_events_use_presence_flags_for_legacy_provider_call_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_failed",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "tests",
                "status": "failed",
                "details": {
                    "attempts": 1,
                    "error_message": "provider call failed",
                    "error_type": "RuntimeError",
                    "error_category": FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
                    "provider_call": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "success": False,
                    },
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    task_failed_event = snapshot.execution_events[0]

    assert task_failed_event["event"] == "task_failed"
    assert task_failed_event["details"]["has_error_message"] is True
    assert task_failed_event["details"]["has_error_type"] is True
    assert task_failed_event["details"]["has_provider_call"] is True
    assert "error_message" not in task_failed_event["details"]
    assert "error_type" not in task_failed_event["details"]
    assert "provider_call" not in task_failed_event["details"]


def test_snapshot_minimizes_public_task_retry_scheduled_provider_call_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            retry_limit=1,
        )
    )

    project.start_task("tests")
    project.fail_task(
        "tests",
        RuntimeError("provider call failed"),
        provider_call={
            "provider": "openai",
            "model": "gpt-4o",
            "success": False,
            "base_url": "https://example.com/v1",
        },
        error_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
    )

    internal_retry_event = next(event for event in project.execution_events if event["event"] == "task_retry_scheduled")
    assert internal_retry_event["details"]["provider_call"]["provider"] == "openai"

    snapshot = project.snapshot()
    retry_event = next(event for event in snapshot.execution_events if event["event"] == "task_retry_scheduled")

    assert retry_event["details"]["has_error_type"] is True
    assert retry_event["details"]["has_provider_call"] is True
    assert "error_type" not in retry_event["details"]
    assert "provider_call" not in retry_event["details"]


def test_snapshot_task_retry_scheduled_events_use_presence_flags_for_legacy_provider_call_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "task_retry_scheduled",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": "tests",
                "status": "pending",
                "details": {
                    "attempts": 1,
                    "retry_limit": 1,
                    "error_type": "RuntimeError",
                    "error_category": FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
                    "provider_call": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "success": False,
                    },
                },
            }
        ],
        updated_at="2026-03-22T10:06:00+00:00",
    )

    snapshot = project.snapshot()
    retry_event = snapshot.execution_events[0]

    assert retry_event["event"] == "task_retry_scheduled"
    assert retry_event["details"]["has_error_type"] is True
    assert retry_event["details"]["has_provider_call"] is True
    assert "error_type" not in retry_event["details"]
    assert "provider_call" not in retry_event["details"]


def test_snapshot_minimizes_public_workflow_finished_failure_task_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            status=TaskStatus.FAILED.value,
            output="sandbox policy blocked filesystem write outside sandbox root",
            last_error="sandbox policy blocked filesystem write outside sandbox root",
            last_error_type="RuntimeError",
            last_error_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )

    project.mark_workflow_running(acceptance_policy="required_tasks", repair_max_cycles=1)
    project.mark_workflow_finished(
        "failed",
        acceptance_policy="required_tasks",
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
        acceptance_criteria_met=False,
        acceptance_evaluation={"policy": "required_tasks", "accepted": False, "failed_task_ids": ["tests"]},
    )

    snapshot = project.snapshot()
    workflow_event = next(event for event in snapshot.execution_events if event["event"] == "workflow_finished")

    assert workflow_event["details"]["acceptance_evaluation"] == snapshot.acceptance_evaluation
    assert workflow_event["details"]["has_failure_task"] is True
    assert workflow_event["details"]["has_failure_message"] is True
    assert workflow_event["details"]["has_failure_error_type"] is True
    assert "failure_task_id" not in workflow_event["details"]
    assert "failure_message" not in workflow_event["details"]
    assert "failure_error_type" not in workflow_event["details"]


def test_snapshot_workflow_finished_events_use_presence_flags_for_legacy_failure_task_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "workflow_finished",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": None,
                "status": "failed",
                "details": {
                    "workflow_duration_ms": 360000.0,
                    "acceptance_policy": "required_tasks",
                    "terminal_outcome": WorkflowOutcome.FAILED.value,
                    "failure_category": FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
                    "acceptance_criteria_met": False,
                    "acceptance_evaluation": {
                        "policy": "required_tasks",
                        "accepted": False,
                        "failed_task_ids": ["tests"],
                    },
                    "failure_task_id": "tests",
                    "failure_message": "sandbox policy blocked filesystem write outside sandbox root",
                    "failure_error_type": "RuntimeError",
                },
            }
        ],
        workflow_started_at="2026-03-22T10:00:00+00:00",
        workflow_finished_at="2026-03-22T10:06:00+00:00",
        updated_at="2026-03-22T10:06:00+00:00",
        phase="failed",
        acceptance_policy="required_tasks",
        terminal_outcome=WorkflowOutcome.FAILED.value,
        acceptance_criteria_met=False,
        failure_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
        acceptance_evaluation={"policy": "required_tasks", "accepted": False, "failed_task_ids": ["tests"]},
    )

    snapshot = project.snapshot()
    workflow_event = snapshot.execution_events[0]

    assert workflow_event["event"] == "workflow_finished"
    assert workflow_event["details"]["has_failure_task"] is True
    assert workflow_event["details"]["has_failure_message"] is True
    assert workflow_event["details"]["has_failure_error_type"] is True
    assert "failure_task_id" not in workflow_event["details"]
    assert "failure_message" not in workflow_event["details"]
    assert "failure_error_type" not in workflow_event["details"]
    assert workflow_event["details"]["acceptance_evaluation"] == snapshot.acceptance_evaluation


def test_snapshot_minimizes_public_workflow_finished_provider_call_details():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
        )
    )

    project.mark_workflow_running(acceptance_policy="required_tasks", repair_max_cycles=1)
    project.start_task("tests")
    project.fail_task(
        "tests",
        RuntimeError("provider call failed"),
        provider_call={
            "provider": "openai",
            "model": "gpt-4o",
            "success": False,
            "base_url": "https://example.com/v1",
        },
        error_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
    )
    project.mark_workflow_finished(
        "failed",
        acceptance_policy="required_tasks",
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
        acceptance_criteria_met=False,
        acceptance_evaluation={"policy": "required_tasks", "accepted": False, "failed_task_ids": ["tests"]},
    )

    snapshot = project.snapshot()
    workflow_event = next(event for event in snapshot.execution_events if event["event"] == "workflow_finished")

    assert workflow_event["details"]["has_provider_call"] is True
    assert workflow_event["details"]["has_failure_message"] is True
    assert workflow_event["details"]["has_failure_error_type"] is True
    assert "provider_call" not in workflow_event["details"]
    assert "failure_message" not in workflow_event["details"]
    assert "failure_error_type" not in workflow_event["details"]


def test_snapshot_workflow_finished_events_use_presence_flags_for_legacy_provider_call_details():
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        execution_events=[
            {
                "event": "workflow_finished",
                "timestamp": "2026-03-22T10:06:00+00:00",
                "task_id": None,
                "status": "failed",
                "details": {
                    "workflow_duration_ms": 360000.0,
                    "acceptance_policy": "required_tasks",
                    "terminal_outcome": WorkflowOutcome.FAILED.value,
                    "failure_category": FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
                    "acceptance_criteria_met": False,
                    "acceptance_evaluation": {
                        "policy": "required_tasks",
                        "accepted": False,
                        "failed_task_ids": ["tests"],
                    },
                    "provider_call": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "success": False,
                    },
                    "failure_message": "provider call failed",
                    "failure_error_type": "RuntimeError",
                },
            }
        ],
        workflow_started_at="2026-03-22T10:00:00+00:00",
        workflow_finished_at="2026-03-22T10:06:00+00:00",
        updated_at="2026-03-22T10:06:00+00:00",
        phase="failed",
        acceptance_policy="required_tasks",
        terminal_outcome=WorkflowOutcome.FAILED.value,
        acceptance_criteria_met=False,
        failure_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
        acceptance_evaluation={"policy": "required_tasks", "accepted": False, "failed_task_ids": ["tests"]},
    )

    snapshot = project.snapshot()
    workflow_event = snapshot.execution_events[0]

    assert workflow_event["event"] == "workflow_finished"
    assert workflow_event["details"]["has_provider_call"] is True
    assert workflow_event["details"]["has_failure_message"] is True
    assert workflow_event["details"]["has_failure_error_type"] is True
    assert "provider_call" not in workflow_event["details"]
    assert "failure_message" not in workflow_event["details"]
    assert "failure_error_type" not in workflow_event["details"]


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
    assert result.failure.details["has_provider_call"] is False
    assert "error_type" not in result.failure.details
    assert result.failure.details["last_attempt_started_at"] == "2026-03-22T10:05:00+00:00"
    assert result.failure.details["last_resumed_at"] == "2026-03-22T10:04:00+00:00"
    assert result.failure.details["task_duration_ms"] == 360000.0
    assert result.failure.details["last_attempt_duration_ms"] == 60000.0
    assert result.resource_telemetry == {
        "has_provider_call": False,
        "task_duration_ms": 360000,
        "last_attempt_duration_ms": 60000,
        "provider_duration_ms": None,
        "usage": {},
    }
    assert result.details["has_provider_call"] is False
    assert result.details["last_error_present"] is True
    assert "last_error" not in result.details
    assert result.details["task_duration_ms"] == 360000.0
    assert result.details["last_attempt_duration_ms"] == 60000.0
    assert result.details["history"][0]["event"] == "failed"
    assert result.details["history"][0]["has_attempts"] is True
    assert "attempts" not in result.details["history"][0]
    assert result.details["history"][0]["has_error_message"] is True
    assert "error_message" not in result.details["history"][0]
    assert result.failure.details["history"][0]["event"] == "failed"
    assert result.failure.details["history"][0]["has_attempts"] is True
    assert "attempts" not in result.failure.details["history"][0]
    assert result.failure.details["history"][0]["has_error_message"] is True
    assert "error_message" not in result.failure.details["history"][0]


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
    assert "provider_call" not in result.failure.details
    assert result.resource_telemetry["has_provider_call"] is True
    assert "provider" not in result.resource_telemetry
    assert "model" not in result.resource_telemetry


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


def test_workflow_telemetry_summary_tracks_sparse_provider_health_and_fallback_metadata():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            last_provider_call={
                "provider": "openai",
                "success": None,
                "attempts_used": 1,
                "duration_ms": 12.5,
                "usage": {"prompt_tokens": 5},
                "provider_health": {
                    "openai": {
                        "model": None,
                        "status": "open_circuit",
                        "last_outcome": None,
                        "last_failure_retryable": True,
                        "last_error_type": "TimeoutError",
                        "last_health_check": {"active_check": True, "cooldown_cached": False},
                    },
                    "": {},
                    "anthropic": "invalid",
                },
                "fallback_history": [
                    None,
                    {"provider": "", "status": "", "error_type": ""},
                    {
                        "provider": "anthropic",
                        "status": "failed_health_check",
                        "error_type": "ProviderTransientError",
                    },
                ],
            },
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the changes",
            assigned_to="code_reviewer",
            status=TaskStatus.FAILED.value,
            last_provider_call={
                "provider": None,
                "success": False,
                "error_type": "AgentExecutionError",
                "latency_ms": 20,
                "usage": {"completion_tokens": 2},
            },
        )
    )
    project.execution_events.append(
        {
            "event": "workflow_resumed",
            "details": {"reason": "", "task_ids": "not-a-list"},
        }
    )

    telemetry = project.snapshot().workflow_telemetry

    assert telemetry["resume_summary"]["has_multiple_resume_events"] is False
    assert telemetry["resume_summary"]["has_multiple_reasons"] is False
    assert telemetry["resume_summary"]["has_multiple_unique_tasks"] is False
    assert telemetry["provider_summary"]["openai"]["has_multiple_tasks"] is False
    assert telemetry["provider_summary"]["openai"]["has_successes"] is False
    assert telemetry["provider_summary"]["openai"]["has_failures"] is False
    assert telemetry["provider_summary"]["openai"]["has_attempts"] is True
    assert telemetry["provider_summary"]["openai"]["has_retry_attempts"] is False
    assert telemetry["provider_summary"]["openai"]["duration_ms"]["count"] == 1
    assert telemetry["provider_summary"]["openai"]["usage"] == {"prompt_tokens": 5}
    assert telemetry["provider_health_summary"]["openai"] == {
        "models": [],
        "status_counts": {"open_circuit": 1},
        "last_outcome_counts": {},
        "circuit_open_count": 1,
        "retryable_failure_count": 1,
        "active_health_check_count": 1,
    }
    assert telemetry["has_multiple_final_providers"] is False
    assert telemetry["has_multiple_observed_providers"] is True
    assert telemetry["has_attempts"] is True
    assert telemetry["has_retry_attempts"] is False
    assert telemetry["duration_ms"]["count"] == 2
    assert telemetry["usage"] == {"completion_tokens": 2, "prompt_tokens": 5}
    assert telemetry["fallback_summary"] == {
        "has_multiple_tasks": False,
        "has_entries": True,
        "has_multiple_providers": False,
        "has_multiple_statuses": False,
    }
    assert telemetry["error_summary"] == {
        "has_final_errors": True,
        "has_fallback_errors": True,
    }


def test_workflow_telemetry_summary_filters_invalid_provider_usage_metrics(monkeypatch):
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            last_provider_call={
                "provider": "openai",
                "success": True,
                "usage": {"prompt_tokens": 1},
            },
        )
    )
    accumulate_calls = {"count": 0}

    def fake_accumulate(target, metrics):
        accumulate_calls["count"] += 1
        if accumulate_calls["count"] == 1:
            target["total_tokens"] = 9.0
            return
        target[7] = 2.0
        target["bool_metric"] = True
        target["prompt_tokens"] = 3.0

    monkeypatch.setattr(project, "_accumulate_numeric_metrics", fake_accumulate)

    telemetry = project._workflow_telemetry_summary()

    assert telemetry["usage"] == {"total_tokens": 9}
    assert telemetry["provider_summary"]["openai"]["usage"] == {"prompt_tokens": 3}


def test_workflow_telemetry_summary_handles_non_dict_provider_usage_bucket(monkeypatch):
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            last_provider_call={
                "provider": "openai",
                "success": True,
                "usage": {"prompt_tokens": 1},
            },
        )
    )
    accumulate_calls = {"count": 0}

    def fake_accumulate(target, metrics):
        accumulate_calls["count"] += 1
        if accumulate_calls["count"] == 1:
            target["total_tokens"] = 1.0
            return
        target["__sentinel__"] = 1.0

    original_isinstance = builtins.isinstance

    def fake_isinstance(obj, typ):
        if typ is dict and original_isinstance(obj, dict) and obj.get("__sentinel__") == 1.0:
            return False
        return original_isinstance(obj, typ)

    monkeypatch.setattr(project, "_accumulate_numeric_metrics", fake_accumulate)
    monkeypatch.setattr(builtins, "isinstance", fake_isinstance)

    telemetry = project._workflow_telemetry_summary()

    assert telemetry["usage"] == {"total_tokens": 1}
    assert telemetry["provider_summary"]["openai"]["usage"] == {}


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

    arch_task = require_task(loaded, "arch")
    assert arch_task.history[0]["event"] == "started"


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

    arch_task = require_task(loaded, "arch")
    assert arch_task.history[0]["event"] == "started"


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
    assert snapshot.acceptance_evaluation == {
        "policy": "required_tasks",
        "accepted": True,
        "reason": None,
        "terminal_outcome": "completed",
        "failure_category": None,
        "has_evaluated_tasks": False,
        "has_required_tasks": True,
        "has_completed_tasks": True,
        "has_failed_tasks": False,
        "has_skipped_tasks": False,
        "has_pending_tasks": False,
    }
    assert snapshot.execution_events[0]["event"] == "workflow_started"
    assert snapshot.execution_events[1]["details"]["workflow_duration_ms"] == 360000.0
    assert snapshot.execution_events[1]["details"]["acceptance_evaluation"] == snapshot.acceptance_evaluation
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

    arch_task = require_task(project, "arch")
    assert project._depends_on_task(arch_task, "code") is True
    assert project._depends_on_task(arch_task, "tests") is False


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
    docs_task = require_task(project, "docs")
    assert docs_task.status == TaskStatus.DONE.value


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


def test_project_summary_redacts_sensitive_project_name():
    project = ProjectState(
        project_name="Customer api_key=sk-secret-123456",
        goal="Build demo",
        phase="running",
    )

    assert "sk-secret-123456" not in project.summary()
    assert project.summary() == "Project: Customer api_key=[REDACTED] | Phase: running | Tasks: 0/0 done"


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

    arch_task = require_task(loaded, "arch")
    assert arch_task.started_at == "2026-03-22T10:00:00+00:00"
    assert arch_task.last_attempt_started_at == "2026-03-22T10:01:00+00:00"
    assert arch_task.last_resumed_at == "2026-03-22T10:02:00+00:00"


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

    arch_task = require_task(loaded, "arch")
    assert arch_task.started_at == "2026-03-22T10:00:00+00:00"
    assert arch_task.last_attempt_started_at == "2026-03-22T10:01:00+00:00"
    assert arch_task.last_resumed_at == "2026-03-22T10:02:00+00:00"


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
    code_task = require_task(project, "code")
    test_task = require_task(project, "test")
    assert code_task.status == TaskStatus.SKIPPED.value
    assert test_task.status == TaskStatus.SKIPPED.value


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
    assert result.details["has_provider_call"] is False
    assert result.details["last_error_present"] is True
    assert "last_error" not in result.details
    assert "last_provider_call" not in result.details
    assert "last_error_type" not in result.details
    assert result.details["history"][0]["event"] == "skipped"
    assert result.details["history"][0]["has_error_message"] is True
    assert "error_message" not in result.details["history"][0]
    assert result.details["last_attempt_started_at"] is None
    assert result.details["last_resumed_at"] is None
    assert result.details["task_duration_ms"] is None
    assert result.details["last_attempt_duration_ms"] is None


def test_skip_task_redacts_sensitive_operator_reason():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="docs",
            title="Docs",
            description="Document",
            assigned_to="docs_writer",
        )
    )

    project.skip_task("docs", "Authorization: Bearer sk-ant-secret-987654")

    task = require_task(project, "docs")

    assert "sk-ant-secret-987654" not in task.last_error
    assert "sk-ant-secret-987654" not in task.output
    assert "sk-ant-secret-987654" not in task.history[-1]["error_message"]
    assert "sk-ant-secret-987654" not in project.execution_events[-1]["details"]["reason"]
    assert "[REDACTED]" in task.last_error
    assert task.output == task.last_error
    assert "[REDACTED]" in task.history[-1]["error_message"]
    assert "[REDACTED]" in project.execution_events[-1]["details"]["reason"]


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