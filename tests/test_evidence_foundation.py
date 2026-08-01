"""Tests for the audit-evidence hardening program: provenance, integrity, and artifact manifests."""

import hashlib
import json

import pytest

from kycortex_agents.memory.project_state import (
    PROJECT_STATE_SCHEMA_VERSION,
    ProjectState,
    Task,
    compute_state_digest,
    verify_persisted_state_integrity,
)
from kycortex_agents.memory.state_store import resolve_state_store
from kycortex_agents.orchestration.artifacts import ARTIFACT_MANIFEST_FILENAME, ArtifactPersistenceSupport
from kycortex_agents.types import ArtifactRecord, ArtifactType, TaskStatus


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


@pytest.mark.parametrize("state_filename", ["integrity.json", "integrity.sqlite"])
def test_save_embeds_matching_integrity_digest(tmp_path, state_filename):
    project = _project(tmp_path, state_filename)
    project.mark_workflow_running()

    project.save()

    payload = resolve_state_store(str(tmp_path / state_filename)).load(str(tmp_path / state_filename))
    integrity = payload["integrity"]
    assert integrity["algorithm"] == "sha256"
    assert integrity["state_sha256"] == compute_state_digest(payload)
    assert isinstance(integrity["computed_at"], str)


@pytest.mark.parametrize("state_filename", ["sidecar.json", "sidecar.sqlite"])
def test_save_writes_integrity_sidecar(tmp_path, state_filename):
    project = _project(tmp_path, state_filename)

    project.save()

    sidecar = tmp_path / f"{state_filename}.sha256"
    payload = resolve_state_store(str(tmp_path / state_filename)).load(str(tmp_path / state_filename))
    digest, _, label = sidecar.read_text(encoding="utf-8").strip().partition("  ")
    assert digest == payload["integrity"]["state_sha256"]
    assert label == state_filename


@pytest.mark.parametrize("state_filename", ["verify.json", "verify.sqlite"])
def test_verify_persisted_state_integrity_passes_for_untouched_state(tmp_path, state_filename):
    project = _project(tmp_path, state_filename)
    project.save()

    assert verify_persisted_state_integrity(str(tmp_path / state_filename)) is True


def test_verify_persisted_state_integrity_detects_tampering(tmp_path):
    state_path = tmp_path / "tampered.json"
    project = _project(tmp_path, "tampered.json")
    project.save()

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["goal"] = "tampered goal"
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    assert verify_persisted_state_integrity(str(state_path)) is False


def test_verify_persisted_state_integrity_false_without_integrity_block(tmp_path):
    state_path = tmp_path / "no-integrity.json"
    resolve_state_store(str(state_path)).save(
        str(state_path),
        {"project_name": "Legacy", "goal": "No digest", "tasks": [], "schema_version": 2},
    )

    assert verify_persisted_state_integrity(str(state_path)) is False


def test_load_accepts_states_with_integrity_block(tmp_path):
    state_path = tmp_path / "roundtrip-integrity.json"
    project = _project(tmp_path, "roundtrip-integrity.json")
    project.mark_workflow_running()
    project.save()

    loaded = ProjectState.load(str(state_path))

    assert loaded.project_name == project.project_name
    assert loaded.run_identity["run_id"] == project.run_identity["run_id"]


def test_persist_artifacts_writes_sha256_manifest(tmp_path):
    support = ArtifactPersistenceSupport(str(tmp_path))
    artifact = ArtifactRecord(name="intake service", artifact_type=ArtifactType.CODE, content="print('ok')\n")

    support.persist_artifacts([artifact])

    manifest = json.loads((tmp_path / ARTIFACT_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["algorithm"] == "sha256"
    assert artifact.path is not None
    entry = manifest["entries"][artifact.path]
    assert entry["sha256"] == hashlib.sha256(artifact.content.encode("utf-8")).hexdigest()
    assert entry["size_bytes"] == len(artifact.content.encode("utf-8"))
    assert entry["artifact_type"] == ArtifactType.CODE.value
    assert entry["name"] == "intake service"


def test_persist_artifacts_merges_manifest_entries_across_calls(tmp_path):
    support = ArtifactPersistenceSupport(str(tmp_path))
    first = ArtifactRecord(name="first", artifact_type=ArtifactType.CODE, content="a = 1\n")
    second = ArtifactRecord(name="second", artifact_type=ArtifactType.DOCUMENT, content="# Doc\n")

    support.persist_artifacts([first])
    support.persist_artifacts([second])

    manifest = json.loads((tmp_path / ARTIFACT_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert first.path in manifest["entries"]
    assert second.path in manifest["entries"]
    assert len(manifest["entries"]) == 2


def test_persist_artifacts_skips_manifest_when_nothing_persisted(tmp_path):
    support = ArtifactPersistenceSupport(str(tmp_path))

    support.persist_artifacts([ArtifactRecord(name="empty", content="   ")])

    assert not (tmp_path / ARTIFACT_MANIFEST_FILENAME).exists()
