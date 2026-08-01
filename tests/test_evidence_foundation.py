"""Tests for the audit-evidence hardening program: provenance, integrity, and artifact manifests."""

import hashlib
import json

import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ConfigValidationError, StatePersistenceError
from kycortex_agents.memory.project_state import (
    EVENT_CHAIN_GENESIS_HASH,
    PROJECT_STATE_SCHEMA_VERSION,
    ProjectState,
    Task,
    compute_execution_event_hash,
    compute_state_digest,
    verify_execution_event_chain,
    verify_persisted_event_chain,
    verify_persisted_state_integrity,
)
from kycortex_agents.memory.state_store import (
    list_state_snapshots,
    load_state_snapshot,
    resolve_state_store,
    state_file_lock,
)
from kycortex_agents.orchestration.artifacts import ARTIFACT_MANIFEST_FILENAME, ArtifactPersistenceSupport
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.providers.base import BaseLLMProvider, sanitize_provider_call_metadata
from kycortex_agents.types import AgentOutput, ArtifactRecord, ArtifactType, TaskStatus


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


# --- Phase 3: complete provider-call history, sanitization modes, prompt capture ---


class _EvidenceProvider(BaseLLMProvider):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls += 1
        step = self.responses.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _EvidenceAgent(BaseAgent):
    def __init__(self, provider, config):
        super().__init__("Evidence", "Testing", config)
        self._provider = provider

    def run(self, task_description: str, context: dict) -> str | AgentOutput:
        return self.chat("system prompt", task_description)


def _agent(tmp_path, provider, **config_overrides) -> _EvidenceAgent:
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), **config_overrides)
    return _EvidenceAgent(provider, config)


def test_sanitize_provider_call_metadata_default_matches_strict_mode():
    provider_call = {
        "provider": "openai",
        "model": "gpt-4o",
        "success": False,
        "error_type": "RuntimeError",
        "error_message": "backend exploded",
    }

    assert sanitize_provider_call_metadata(provider_call) == sanitize_provider_call_metadata(
        provider_call, mode="strict"
    )
    strict = sanitize_provider_call_metadata(provider_call, mode="strict")
    assert strict["has_error_message"] is True
    assert "error_message" not in strict
    assert "error_type" not in strict


def test_sanitize_provider_call_metadata_audit_mode_preserves_redacted_error_details():
    provider_call = {
        "provider": "openai",
        "model": "gpt-4o",
        "success": False,
        "error_type": "RuntimeError",
        "error_message": "call failed with api_key=super-secret-token",
        "attempt_history": [
            {
                "attempt": 1,
                "success": False,
                "error_type": "ProviderTransientError",
                "error_message": "throttled",
                "jitter_seconds": 0.1,
            }
        ],
        "fallback_history": [
            {"provider": "anthropic", "model": "claude-3", "status": "failed_transient", "error_message": "down"}
        ],
    }

    audit = sanitize_provider_call_metadata(provider_call, mode="audit")

    assert audit["error_type"] == "RuntimeError"
    assert "super-secret-token" not in audit["error_message"]
    assert "[REDACTED]" in audit["error_message"]
    assert audit["attempt_history"][0]["error_message"] == "throttled"
    assert "jitter_seconds" not in audit["attempt_history"][0]
    assert audit["fallback_history"][0]["model"] == "claude-3"
    assert audit["fallback_history"][0]["error_message"] == "down"


def test_sanitize_provider_call_metadata_audit_mode_still_redacts_sensitive_keys():
    audit = sanitize_provider_call_metadata(
        {"provider": "openai", "api_key": "sk-abcdefghijklmnop", "error_message": "boom"},
        mode="audit",
    )

    assert audit["api_key"] == "[REDACTED]"


def test_sanitize_provider_call_metadata_rejects_unknown_mode():
    with pytest.raises(ValueError):
        sanitize_provider_call_metadata({"provider": "openai"}, mode="verbose")


def test_evidence_config_defaults(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))

    assert config.evidence_sanitization_mode == "strict"
    assert config.evidence_capture_prompts is False
    assert config.evidence_prompt_capture_max_chars == 20000


def test_evidence_config_normalizes_and_validates_sanitization_mode(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), evidence_sanitization_mode=" AUDIT ")
    assert config.evidence_sanitization_mode == "audit"

    with pytest.raises(ConfigValidationError):
        KYCortexConfig(output_dir=str(tmp_path / "output"), evidence_sanitization_mode="verbose")


def test_evidence_config_rejects_non_positive_prompt_capture_limit(tmp_path):
    with pytest.raises(ConfigValidationError):
        KYCortexConfig(output_dir=str(tmp_path / "output"), evidence_prompt_capture_max_chars=0)


def test_chat_appends_every_call_to_provider_call_log(tmp_path):
    agent = _agent(tmp_path, _EvidenceProvider(["first", "second"]))

    agent.chat("system", "one")
    agent.chat("system", "two")

    history = agent.get_provider_call_history()
    assert [entry["call_index"] for entry in history] == [1, 2]
    assert all(entry["success"] is True for entry in history)
    assert all(entry["recorded_at"] for entry in history)


def test_chat_appends_failed_call_to_provider_call_log(tmp_path):
    agent = _agent(tmp_path, _EvidenceProvider([RuntimeError("backend down")]))

    with pytest.raises(AgentExecutionError):
        agent.chat("system", "one")

    history = agent.get_provider_call_history()
    assert len(history) == 1
    assert history[0]["success"] is False
    assert history[0]["has_error_message"] is True
    assert "error_message" not in history[0]


def test_provider_call_history_audit_mode_preserves_error_text(tmp_path):
    agent = _agent(
        tmp_path,
        _EvidenceProvider([RuntimeError("backend down: api_key=topsecret")]),
        evidence_sanitization_mode="audit",
    )

    with pytest.raises(AgentExecutionError):
        agent.chat("system", "one")

    entry = agent.get_provider_call_history()[0]
    assert entry["error_type"] == "RuntimeError"
    assert "topsecret" not in entry["error_message"]
    assert "[REDACTED]" in entry["error_message"]


def test_prompt_capture_disabled_by_default(tmp_path):
    agent = _agent(tmp_path, _EvidenceProvider(["done"]))

    agent.chat("system", "one")

    entry = agent.get_provider_call_history()[0]
    assert "captured_prompt" not in entry
    assert "captured_response" not in entry


def test_prompt_capture_records_redacted_truncated_prompt_and_response(tmp_path):
    agent = _agent(
        tmp_path,
        _EvidenceProvider(["a very long provider response body"]),
        evidence_capture_prompts=True,
        evidence_prompt_capture_max_chars=16,
    )

    agent.chat("system with api_key=hidden-secret", "user message body over the limit")

    entry = agent.get_provider_call_history()[0]
    captured_system = entry["captured_prompt"]["system_prompt"]
    assert "hidden-secret" not in captured_system["text"]
    captured_user = entry["captured_prompt"]["user_message"]
    assert captured_user["truncated"] is True
    assert len(captured_user["text"]) == 16
    assert captured_user["original_chars"] == len("user message body over the limit")
    assert entry["captured_response"]["truncated"] is True
    assert entry["captured_response"]["text"] == "a very long provider response body"[:16]


def test_record_task_provider_calls_appends_and_persists(tmp_path):
    project = _project(tmp_path)

    appended = project.record_task_provider_calls(
        "arch",
        [
            {"provider": "openai", "model": "gpt-4o", "success": False, "call_index": 1},
            {"provider": "openai", "model": "gpt-4o", "success": True, "call_index": 2},
        ],
    )
    project.save()

    assert appended == 2
    reloaded = ProjectState.load(str(tmp_path / "project_state.json"))
    task = reloaded.get_task("arch")
    assert [call["call_index"] for call in task.provider_calls] == [1, 2]
    assert task.provider_calls[0]["success"] is False


def test_record_task_provider_calls_redacts_secrets_and_skips_invalid_entries(tmp_path):
    project = _project(tmp_path)

    appended = project.record_task_provider_calls(
        "arch",
        [{"provider": "openai", "api_key": "sk-abcdefghijklmnop"}, "not-a-dict"],
    )

    assert appended == 1
    task = project.get_task("arch")
    assert task.provider_calls[0]["api_key"] == "[REDACTED]"


def test_record_task_provider_calls_ignores_unknown_task(tmp_path):
    project = _project(tmp_path)

    assert project.record_task_provider_calls("missing", [{"provider": "openai"}]) == 0


def test_legacy_task_payload_without_provider_calls_loads_with_empty_history(tmp_path):
    project = _project(tmp_path)
    project.save()
    state_file = tmp_path / "project_state.json"
    payload = json.loads(state_file.read_text())
    payload.pop("integrity", None)
    for task_payload in payload["tasks"]:
        task_payload.pop("provider_calls", None)
    state_file.write_text(json.dumps(payload))

    reloaded = ProjectState.load(str(state_file))

    assert reloaded.get_task("arch").provider_calls == []


def test_replay_workflow_clears_provider_calls(tmp_path):
    project = _project(tmp_path)
    project.record_task_provider_calls("arch", [{"provider": "openai", "success": True}])
    project.complete_task("arch", "done")

    project.replay_workflow()

    assert project.get_task("arch").provider_calls == []


def test_override_task_preserves_provider_call_history(tmp_path):
    project = _project(tmp_path)
    project.start_task("arch")
    project.record_task_provider_calls("arch", [{"provider": "openai", "success": False}])
    project.fail_task("arch", RuntimeError("boom"))

    assert project.override_task("arch", "manual output", reason="operator fix") is True
    task = project.get_task("arch")
    assert task.execution_mode == "manual_override"
    assert len(task.provider_calls) == 1


def test_run_task_records_provider_calls_across_retries(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    provider = _EvidenceProvider([RuntimeError("transient backend failure"), "ARCHITECTURE DOC"])
    agent = _EvidenceAgent(provider, config)
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": agent}))
    project = ProjectState(
        project_name="Evidence Demo",
        goal="Validate provider history",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            retry_limit=1,
        )
    )
    task = project.tasks[0]

    with pytest.raises(AgentExecutionError):
        orchestrator.run_task(task, project)
    result = orchestrator.run_task(task, project)

    assert result == "ARCHITECTURE DOC"
    assert task.status == TaskStatus.DONE.value
    assert len(task.provider_calls) == 2
    assert task.provider_calls[0]["success"] is False
    assert task.provider_calls[1]["success"] is True
    assert [call["call_index"] for call in task.provider_calls] == [1, 2]
    assert task.last_provider_call is not None
    assert task.last_provider_call["success"] is True

    project.save()
    reloaded = ProjectState.load(str(tmp_path / "project_state.json"))
    assert len(reloaded.get_task("arch").provider_calls) == 2


# --- Phase 4: event hash chaining, versioned snapshots, advisory locking ---


def test_execution_events_carry_hash_chain(tmp_path):
    project = _project(tmp_path)

    project.mark_workflow_running()
    project.start_task("arch")
    project.complete_task("arch", "done")

    events = project.execution_events
    assert len(events) >= 3
    assert events[0]["prev_hash"] == EVENT_CHAIN_GENESIS_HASH
    for previous, current in zip(events, events[1:]):
        assert current["prev_hash"] == previous["event_hash"]
    for event in events:
        assert event["event_hash"] == compute_execution_event_hash(event)
    assert verify_execution_event_chain(events) is True


def test_verify_execution_event_chain_detects_tampering(tmp_path):
    project = _project(tmp_path)
    project.mark_workflow_running()
    project.start_task("arch")

    project.execution_events[0]["details"]["injected"] = "tampered"

    assert verify_execution_event_chain(project.execution_events) is False


def test_verify_execution_event_chain_accepts_pre_chain_prefix():
    legacy_event = {"sequence": 1, "event": "workflow_started", "details": {}}
    chained_event = {
        "sequence": 2,
        "event": "task_started",
        "details": {},
        "prev_hash": EVENT_CHAIN_GENESIS_HASH,
    }
    chained_event["event_hash"] = compute_execution_event_hash(chained_event)

    assert verify_execution_event_chain([legacy_event, chained_event]) is True
    assert verify_execution_event_chain([chained_event, legacy_event]) is False


def test_event_chain_continues_across_reload(tmp_path):
    project = _project(tmp_path)
    project.mark_workflow_running()
    project.save()

    reloaded = ProjectState.load(str(tmp_path / "project_state.json"))
    reloaded.start_task("arch")
    reloaded.complete_task("arch", "done")

    assert verify_execution_event_chain(reloaded.execution_events) is True
    assert reloaded.execution_events[-1]["prev_hash"] == reloaded.execution_events[-2]["event_hash"]


@pytest.mark.parametrize("filename", ["project_state.json", "project_state.sqlite"])
def test_verify_persisted_event_chain(tmp_path, filename):
    project = _project(tmp_path, filename)
    project.mark_workflow_running()
    project.start_task("arch")
    project.complete_task("arch", "done")
    project.save()

    assert verify_persisted_event_chain(str(tmp_path / filename)) is True


def test_verify_persisted_event_chain_detects_tampered_event(tmp_path):
    project = _project(tmp_path)
    project.mark_workflow_running()
    project.save()
    state_file = tmp_path / "project_state.json"
    payload = json.loads(state_file.read_text())
    payload["execution_events"][0]["details"]["injected"] = "tampered"
    state_file.write_text(json.dumps(payload))

    assert verify_persisted_event_chain(str(state_file)) is False


def test_integrity_block_records_event_chain_head(tmp_path):
    project = _project(tmp_path)
    project.mark_workflow_running()
    project.save()

    payload = json.loads((tmp_path / "project_state.json").read_text())
    assert payload["integrity"]["event_chain_head"] == project.execution_events[-1]["event_hash"]


def test_snapshot_history_disabled_by_default(tmp_path):
    project = _project(tmp_path)
    project.save()
    project.save()

    assert not (tmp_path / "project_state.json.history").exists()
    assert list_state_snapshots(str(tmp_path / "project_state.json")) == []


def test_json_snapshot_history_appends_per_save(tmp_path):
    project = _project(tmp_path)
    project.snapshot_history_limit = 5

    project.save()
    project.mark_workflow_running()
    project.save()

    state_file = str(tmp_path / "project_state.json")
    snapshots = list_state_snapshots(state_file)
    assert [snapshot["version"] for snapshot in snapshots] == [1, 2]
    first_payload = load_state_snapshot(state_file, 1)
    second_payload = load_state_snapshot(state_file, 2)
    assert first_payload["project_name"] == "Evidence Demo"
    assert len(second_payload["execution_events"]) > len(first_payload["execution_events"])


def test_json_snapshot_history_prunes_beyond_limit(tmp_path):
    project = _project(tmp_path)
    project.snapshot_history_limit = 2

    for _ in range(4):
        project.save()

    state_file = str(tmp_path / "project_state.json")
    assert [snapshot["version"] for snapshot in list_state_snapshots(state_file)] == [3, 4]


def test_sqlite_snapshot_history_appends_and_prunes(tmp_path):
    project = _project(tmp_path, "project_state.sqlite")
    project.snapshot_history_limit = 2

    for _ in range(3):
        project.save()

    state_file = str(tmp_path / "project_state.sqlite")
    snapshots = list_state_snapshots(state_file)
    assert [snapshot["version"] for snapshot in snapshots] == [2, 3]
    payload = load_state_snapshot(state_file, 3)
    assert payload["project_name"] == "Evidence Demo"
    reloaded = ProjectState.load(state_file)
    assert reloaded.project_name == "Evidence Demo"


def test_load_state_snapshot_unknown_version_raises(tmp_path):
    project = _project(tmp_path)
    project.snapshot_history_limit = 3
    project.save()

    with pytest.raises(StatePersistenceError):
        load_state_snapshot(str(tmp_path / "project_state.json"), 99)


def test_snapshots_preserve_integrity_and_chain(tmp_path):
    project = _project(tmp_path)
    project.snapshot_history_limit = 3
    project.mark_workflow_running()
    project.save()

    payload = load_state_snapshot(str(tmp_path / "project_state.json"), 1)
    assert compute_state_digest(payload) == payload["integrity"]["state_sha256"]
    assert verify_execution_event_chain(payload["execution_events"]) is True


def test_state_file_lock_creates_lock_file_and_is_reentrant_across_scopes(tmp_path):
    state_file = str(tmp_path / "project_state.json")

    with state_file_lock(state_file):
        pass
    with state_file_lock(state_file, exclusive=False):
        with state_file_lock(state_file, exclusive=False):
            pass

    assert (tmp_path / "project_state.json.lock").exists()


def test_save_holds_lock_and_keeps_sidecar_consistent(tmp_path):
    project = _project(tmp_path)
    project.save()

    state_file = tmp_path / "project_state.json"
    assert (tmp_path / "project_state.json.lock").exists()
    sidecar = (tmp_path / "project_state.json.sha256").read_text()
    payload = json.loads(state_file.read_text())
    assert sidecar.split()[0] == payload["integrity"]["state_sha256"]
    assert verify_persisted_state_integrity(str(state_file)) is True
