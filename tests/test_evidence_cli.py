"""Tests for the auditor-facing evidence CLI, legal hold, and legal-output disclaimer."""

import json
import zipfile

import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.legal_advisor import LEGAL_OUTPUT_DISCLAIMER, SYSTEM_PROMPT, LegalAdvisorAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.evidence import export_evidence_bundle, main, verify_evidence
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.memory.state_store import list_state_snapshots
from kycortex_agents.orchestration.artifacts import ARTIFACT_MANIFEST_FILENAME, ArtifactPersistenceSupport
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactRecord, ArtifactType


def _project(tmp_path, filename="project_state.json") -> ProjectState:
    project = ProjectState(
        project_name="Evidence CLI Demo",
        goal="Validate auditor surface",
        state_file=str(tmp_path / filename),
    )
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    return project


def _saved_state(tmp_path, filename="project_state.json") -> str:
    project = _project(tmp_path, filename)
    project.mark_workflow_running()
    project.start_task("arch")
    project.complete_task("arch", "done")
    project.save()
    return str(tmp_path / filename)


def _artifacts_dir(tmp_path) -> str:
    artifacts_dir = tmp_path / "artifacts"
    support = ArtifactPersistenceSupport(str(artifacts_dir))
    support.persist_artifacts(
        [ArtifactRecord(name="legal analysis", artifact_type=ArtifactType.DOCUMENT, content="# Analysis\n")]
    )
    return str(artifacts_dir)


# --- verify ---


@pytest.mark.parametrize("filename", ["project_state.json", "project_state.sqlite"])
def test_verify_evidence_passes_for_untouched_state(tmp_path, filename):
    state_file = _saved_state(tmp_path, filename)

    summary = verify_evidence(state_file)

    assert summary["passed"] is True
    assert summary["checks"] == {
        "state_digest": "passed",
        "event_chain": "passed",
        "integrity_sidecar": "passed",
        "artifact_manifest": "skipped",
    }
    assert filename in summary["state_file"]
    assert str(tmp_path) not in summary["state_file"]


def test_verify_evidence_detects_tampered_state(tmp_path):
    state_file = _saved_state(tmp_path)
    payload = json.loads((tmp_path / "project_state.json").read_text())
    payload["goal"] = "tampered"
    (tmp_path / "project_state.json").write_text(json.dumps(payload))

    summary = verify_evidence(state_file)

    assert summary["checks"]["state_digest"] == "failed"
    assert summary["passed"] is False


def test_verify_evidence_detects_tampered_event_chain(tmp_path):
    state_file = _saved_state(tmp_path)
    payload = json.loads((tmp_path / "project_state.json").read_text())
    payload["execution_events"][0]["details"]["injected"] = "tampered"
    (tmp_path / "project_state.json").write_text(json.dumps(payload))

    summary = verify_evidence(state_file)

    assert summary["checks"]["event_chain"] == "failed"
    assert summary["passed"] is False


def test_verify_evidence_detects_sidecar_mismatch(tmp_path):
    state_file = _saved_state(tmp_path)
    (tmp_path / "project_state.json.sha256").write_text("0" * 64 + "  project_state.json\n")

    summary = verify_evidence(state_file)

    assert summary["checks"]["integrity_sidecar"] == "failed"
    assert summary["passed"] is False


def test_verify_evidence_skips_missing_sidecar(tmp_path):
    state_file = _saved_state(tmp_path)
    (tmp_path / "project_state.json.sha256").unlink()

    summary = verify_evidence(state_file)

    assert summary["checks"]["integrity_sidecar"] == "skipped"
    assert summary["passed"] is True


def test_verify_evidence_validates_artifact_manifest(tmp_path):
    state_file = _saved_state(tmp_path)
    artifacts_dir = _artifacts_dir(tmp_path)

    summary = verify_evidence(state_file, artifacts_dir)

    assert summary["checks"]["artifact_manifest"] == "passed"
    assert summary["passed"] is True


def test_verify_evidence_detects_tampered_artifact(tmp_path):
    state_file = _saved_state(tmp_path)
    artifacts_dir = _artifacts_dir(tmp_path)
    manifest = json.loads((tmp_path / "artifacts" / ARTIFACT_MANIFEST_FILENAME).read_text())
    artifact_relative_path = next(iter(manifest["entries"]))
    (tmp_path / "artifacts" / artifact_relative_path).write_text("tampered")

    summary = verify_evidence(state_file, artifacts_dir)

    assert summary["checks"]["artifact_manifest"] == "failed"
    assert summary["passed"] is False


def test_verify_evidence_fails_manifest_check_when_manifest_missing(tmp_path):
    state_file = _saved_state(tmp_path)

    summary = verify_evidence(state_file, str(tmp_path / "missing-artifacts"))

    assert summary["checks"]["artifact_manifest"] == "failed"
    assert summary["passed"] is False


# --- CLI entry point ---


def test_main_verify_returns_zero_and_prints_summary(tmp_path, capsys):
    state_file = _saved_state(tmp_path)

    exit_code = main(["verify", state_file])

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["passed"] is True


def test_main_verify_returns_one_on_failed_verification(tmp_path, capsys):
    state_file = _saved_state(tmp_path)
    payload = json.loads((tmp_path / "project_state.json").read_text())
    payload["goal"] = "tampered"
    (tmp_path / "project_state.json").write_text(json.dumps(payload))

    exit_code = main(["verify", state_file])

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["passed"] is False


def test_main_returns_two_on_missing_state_file(tmp_path, capsys):
    exit_code = main(["verify", str(tmp_path / "missing.json")])

    assert exit_code == 2
    printed = json.loads(capsys.readouterr().out)
    assert "error" in printed
    assert str(tmp_path) not in printed["error"]


# --- export ---


def test_export_evidence_bundle_writes_self_contained_zip(tmp_path):
    state_file = _saved_state(tmp_path)
    artifacts_dir = _artifacts_dir(tmp_path)
    bundle_path = tmp_path / "bundle" / "evidence.zip"

    summary = export_evidence_bundle(state_file, str(bundle_path), artifacts_dir)

    assert summary["passed"] is True
    with zipfile.ZipFile(bundle_path) as bundle:
        names = set(bundle.namelist())
        assert {"README.md", "state.json", "state.sha256", "evidence_report.json", "verification_summary.json"} <= names
        assert ARTIFACT_MANIFEST_FILENAME in names
        assert any(name.startswith("artifacts/") for name in names)
        state_payload = json.loads(bundle.read("state.json"))
        assert state_payload["project_name"] == "Evidence CLI Demo"
        report = json.loads(bundle.read("evidence_report.json"))
        assert report["project_name"] == "Evidence CLI Demo"
        assert report["event_chain_head"] == state_payload["integrity"]["event_chain_head"]
        assert report["legal_hold"] is False
        assert "not legal advice" in report["disclaimer"]
        bundled_summary = json.loads(bundle.read("verification_summary.json"))
        assert bundled_summary["passed"] is True
        readme = bundle.read("README.md").decode("utf-8")
        assert "python -m kycortex_agents.evidence verify" in readme


def test_main_export_returns_one_but_still_writes_bundle_on_failed_verification(tmp_path, capsys):
    state_file = _saved_state(tmp_path)
    payload = json.loads((tmp_path / "project_state.json").read_text())
    payload["goal"] = "tampered"
    (tmp_path / "project_state.json").write_text(json.dumps(payload))
    bundle_path = tmp_path / "evidence.zip"

    exit_code = main(["export", state_file, str(bundle_path)])

    assert exit_code == 1
    assert bundle_path.exists()
    with zipfile.ZipFile(bundle_path) as bundle:
        assert json.loads(bundle.read("verification_summary.json"))["passed"] is False


# --- legal hold (G9) ---


def test_legal_hold_defaults_to_false_and_roundtrips(tmp_path):
    project = _project(tmp_path)
    assert project.legal_hold is False

    project.legal_hold = True
    project.save()
    reloaded = ProjectState.load(str(tmp_path / "project_state.json"))

    assert reloaded.legal_hold is True


@pytest.mark.parametrize("filename", ["project_state.json", "project_state.sqlite"])
def test_legal_hold_suspends_snapshot_pruning(tmp_path, filename):
    project = _project(tmp_path, filename)
    project.snapshot_history_limit = 2
    project.legal_hold = True

    for _ in range(4):
        project.save()

    versions = [snapshot["version"] for snapshot in list_state_snapshots(str(tmp_path / filename))]
    assert versions == [1, 2, 3, 4]


def test_releasing_legal_hold_resumes_pruning(tmp_path):
    project = _project(tmp_path)
    project.snapshot_history_limit = 2
    project.legal_hold = True
    for _ in range(3):
        project.save()

    project.legal_hold = False
    project.save()

    versions = [snapshot["version"] for snapshot in list_state_snapshots(str(tmp_path / "project_state.json"))]
    assert versions == [3, 4]


# --- legal-output disclaimer (G10) ---


class _StubProvider(BaseLLMProvider):
    def generate(self, system_prompt: str, user_message: str) -> str:
        return "License analysis: all dependencies are MIT-compatible."


def _legal_agent(tmp_path) -> LegalAdvisorAgent:
    agent = LegalAdvisorAgent(KYCortexConfig(output_dir=str(tmp_path / "output")))
    agent._provider = _StubProvider()
    return agent


def _legal_input() -> AgentInput:
    return AgentInput(
        task_id="legal",
        task_title="Legal review",
        task_description="Review dependency licenses",
        project_name="Demo",
        project_goal="Ship compliantly",
        context={"dependencies": ["requests"]},
    )


def test_legal_system_prompt_states_not_legal_advice():
    assert "not legal advice" in SYSTEM_PROMPT
    assert "AI language model" in SYSTEM_PROMPT


def test_legal_artifact_carries_disclaimer_header(tmp_path):
    agent = _legal_agent(tmp_path)

    output = agent.execute(_legal_input())

    assert output.artifacts, "legal agent must produce a document artifact"
    for artifact in output.artifacts:
        assert artifact.content.startswith(LEGAL_OUTPUT_DISCLAIMER)
    assert "does not constitute legal advice" in LEGAL_OUTPUT_DISCLAIMER
    assert "AI language model" in LEGAL_OUTPUT_DISCLAIMER


def test_disclaimer_is_not_duplicated_when_content_already_carries_it(tmp_path):
    class _PreDisclaimedAgent(LegalAdvisorAgent):
        def run_with_input(self, agent_input: AgentInput) -> AgentOutput:
            content = f"{LEGAL_OUTPUT_DISCLAIMER}\n\nAlready disclaimed analysis."
            return AgentOutput(
                summary="pre-disclaimed",
                raw_content=content,
                artifacts=[
                    ArtifactRecord(
                        name="legal_analysis",
                        artifact_type=ArtifactType.DOCUMENT,
                        content=content,
                    )
                ],
            )

    agent = _PreDisclaimedAgent(KYCortexConfig(output_dir=str(tmp_path / "output")))
    agent._provider = _StubProvider()

    output = agent.execute(_legal_input())

    artifact_content = output.artifacts[0].content
    assert artifact_content.count(LEGAL_OUTPUT_DISCLAIMER) == 1


def test_non_legal_agents_do_not_prepend_disclaimers(tmp_path):
    class _PlainAgent(BaseAgent):
        def __init__(self, config):
            super().__init__("Plain", "Testing", config)

        def run(self, task_description: str, context: dict) -> str:
            return "plain output"

    agent = _PlainAgent(KYCortexConfig(output_dir=str(tmp_path / "output")))

    output = agent.execute(_legal_input())

    assert output.artifacts[0].content == "plain output"