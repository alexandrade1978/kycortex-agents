"""Tests for Phase 1 audit-evidence foundation: run identity, event sequencing, and execution-mode provenance."""

import pytest

from kycortex_agents.memory.project_state import PROJECT_STATE_SCHEMA_VERSION, ProjectState, Task
from kycortex_agents.memory.state_store import resolve_state_store
from kycortex_agents.types import TaskStatus


def _project(tmp_path, filename="project_state.json") -> ProjectState:
    project = ProjectState(
        project_name="Evidence Demo",
        goal="Validate evidence foundation",
        state_file=str(tmp_path / filename),
    )
    project.add_task(
        Task(id="arch", title="Architecture", description="Design", assigned_to="architect")
    )
    return project


def test_mark_workflow_running_records_run_identity(tmp_path):
    project = _project(tmp_path)

    project.mark_workflow_running()

    identity = project.run_identity
    assert isinstance(identity["run_id"], str) and len(identity["run_id"]) == 32
    assert isinstance(identity["os_user"], str) and identity["os_user"]
    assert isinstance(identity["hostname"], str) and identity["hostname"]
    assert isinstance(identity["pid"], int) and identity["pid"] > 0
    assert isinstance(identity["package_version"], str) and identity["package_version"]
    assert isinstance(identity["python_version"], str) and identity["python_version"]
    assert isinstance(identity["platform"], str) and identity["platform"]
    assert identity["started_at"] == project.workflow_started_at
    clock = identity["clock"]
    assert clock["source"] == "system_wall_clock"
    assert clock["timezone"] == "UTC"
    assert isinstance(clock["time_ns"], int)
    assert isinstance(clock["monotonic_ns"], int)
    assert clock["ntp_verified"] is False


def test_workflow_started_event_carries_run_id(tmp_path):
    project = _project(tmp_path)

    project.mark_workflow_running()

    started_events = [event for event in project.execution_events if event["event"] == "workflow_started"]
    assert started_events[-1]["details"]["run_id"] == project.run_identity["run_id"]


def test_rerun_replaces_run_identity(tmp_path):
    project = _project(tmp_path)

    project.mark_workflow_running()
    first_run_id = project.run_identity["run_id"]
    project.mark_workflow_running()

    assert project.run_identity["run_id"] != first_run_id


def test_execution_events_have_monotonic_sequence(tmp_path):
    project = _project(tmp_path)

    project.mark_workflow_running()
    project.start_task("arch")
    project.complete_task("arch", "done")
    project.mark_workflow_finished("completed")

    sequences = [event["sequence"] for event in project.execution_events]
    assert sequences == list(range(1, len(sequences) + 1))
    assert project.event_sequence == sequences[-1]


@pytest.mark.parametrize("state_filename", ["evidence.json", "evidence.sqlite"])
def test_run_identity_and_sequence_survive_persistence_roundtrip(tmp_path, state_filename):
    project = _project(tmp_path, state_filename)
    project.mark_workflow_running()
    project.start_task("arch")
    project.complete_task("arch", "done")
    project.save()

    loaded = ProjectState.load(str(tmp_path / state_filename))

    assert loaded.run_identity["run_id"] == project.run_identity["run_id"]
    assert loaded.event_sequence == project.event_sequence
    assert [event["sequence"] for event in loaded.execution_events] == [
        event["sequence"] for event in project.execution_events
    ]


@pytest.mark.parametrize("state_filename", ["legacy-v1.json", "legacy-v1.sqlite"])
def test_v1_payloads_migrate_to_v2_with_backfilled_sequences(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Migrate",
        "tasks": [],
        "decisions": [],
        "artifacts": [],
        "phase": "completed",
        "schema_version": 1,
        "execution_events": [
            {"event": "workflow_started", "timestamp": "2026-01-01T00:00:00+00:00", "task_id": None, "status": "execution", "details": {}},
            {"event": "workflow_finished", "timestamp": "2026-01-01T00:01:00+00:00", "task_id": None, "status": "completed", "details": {}},
        ],
    }
    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))

    assert loaded.schema_version == PROJECT_STATE_SCHEMA_VERSION
    assert [event["sequence"] for event in loaded.execution_events] == [1, 2]
    assert loaded.event_sequence == 2
    assert loaded.run_identity == {}


def test_v0_payloads_migrate_through_full_chain_to_v2(tmp_path):
    state_path = tmp_path / "legacy-v0.json"
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Migrate from v0",
        "tasks": [],
        "decisions": [],
        "artifacts": [],
        "phase": "init",
        "execution_events": [
            {"event": "workflow_started", "timestamp": "2025-01-01T00:00:00+00:00", "task_id": None, "status": "execution", "details": {}},
        ],
    }
    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))

    assert loaded.schema_version == PROJECT_STATE_SCHEMA_VERSION
    assert loaded.execution_events[0]["sequence"] == 1
    assert loaded.event_sequence == 1


def test_migrated_sequence_resumes_monotonically(tmp_path):
    state_path = tmp_path / "resume-seq.json"
    legacy_payload = {
        "project_name": "Legacy",
        "goal": "Resume sequencing",
        "tasks": [],
        "decisions": [],
        "artifacts": [],
        "phase": "init",
        "schema_version": 1,
        "execution_events": [
            {"event": "workflow_started", "timestamp": "2026-01-01T00:00:00+00:00", "task_id": None, "status": "execution", "details": {}},
        ],
    }
    resolve_state_store(str(state_path)).save(str(state_path), legacy_payload)

    loaded = ProjectState.load(str(state_path))
    loaded.mark_workflow_running()

    assert loaded.execution_events[-1]["sequence"] == 2


def test_complete_task_records_execution_mode_provider(tmp_path):
    project = _project(tmp_path)
    project.mark_workflow_running()
    project.start_task("arch")

    project.complete_task("arch", "done", provider_call={"provider": "openai", "model": "gpt-4o"})

    task = project.get_task("arch")
    assert task is not None
    assert task.execution_mode == "provider"
    completed = [event for event in project.execution_events if event["event"] == "task_completed"]
    assert completed[-1]["details"]["execution_mode"] == "provider"


def test_complete_task_records_execution_mode_deterministic(tmp_path):
    project = _project(tmp_path)
    project.mark_workflow_running()
    project.start_task("arch")

    project.complete_task("arch", "done")

    task = project.get_task("arch")
    assert task is not None
    assert task.execution_mode == "deterministic"
    completed = [event for event in project.execution_events if event["event"] == "task_completed"]
    assert completed[-1]["details"]["execution_mode"] == "deterministic"


def test_fail_task_records_execution_mode(tmp_path):
    project = _project(tmp_path)
    project.mark_workflow_running()
    project.start_task("arch")

    project.fail_task("arch", RuntimeError("boom"))

    task = project.get_task("arch")
    assert task is not None
    assert task.status == TaskStatus.FAILED.value
    assert task.execution_mode == "deterministic"


def test_override_task_records_manual_override_mode(tmp_path):
    project = _project(tmp_path)
    project.mark_workflow_running()

    assert project.override_task("arch", "manual output", reason="operator fix")

    task = project.get_task("arch")
    assert task is not None
    assert task.execution_mode == "manual_override"


def test_replay_clears_execution_mode(tmp_path):
    project = _project(tmp_path)
    project.mark_workflow_running()
    project.start_task("arch")
    project.complete_task("arch", "done")
    project.mark_workflow_finished("completed")

    project.replay_workflow()

    task = project.get_task("arch")
    assert task is not None
    assert task.execution_mode is None
