from typing import Any

import pytest

from kycortex_agents.agents.architect import ArchitectAgent
from kycortex_agents.agents.code_engineer import CodeEngineerAgent
from kycortex_agents.agents.code_reviewer import CodeReviewerAgent
from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.types import ArtifactType, TaskStatus, WorkflowStatus


class DummyProvider(BaseLLMProvider):
    def __init__(self, response: str):
        self.response = response

    def generate(self, system_prompt: str, user_message: str) -> str:
        return self.response

    def get_last_call_metadata(self):
        return None


def require_task(project: ProjectState, task_id: str) -> Task:
    task = project.get_task(task_id)
    assert task is not None
    return task


def artifact_map(project: ProjectState) -> dict[str, dict[str, Any]]:
    artifacts_by_name: dict[str, dict[str, Any]] = {}
    for artifact in project.artifacts:
        assert isinstance(artifact, dict)
        name = artifact.get("name")
        assert isinstance(name, str)
        artifacts_by_name[name] = artifact
    return artifacts_by_name


class RecordingCodeEngineerAgent(CodeEngineerAgent):
    def __init__(self, config: KYCortexConfig, provider):
        super().__init__(config)
        self._provider = provider
        self.seen_architecture = None

    def run_with_input(self, agent_input):
        self.seen_architecture = self.require_context_value(agent_input, "architecture")
        return super().run_with_input(agent_input)


class RecordingCodeReviewerAgent(CodeReviewerAgent):
    def __init__(self, config: KYCortexConfig, provider):
        super().__init__(config)
        self._provider = provider
        self.seen_code = None

    def run_with_input(self, agent_input):
        self.seen_code = self.require_context_value(agent_input, "code")
        return super().run_with_input(agent_input)


class RecordingQATesterAgent(QATesterAgent):
    def __init__(self, config: KYCortexConfig, provider):
        super().__init__(config)
        self._provider = provider
        self.seen_code = None

    def run_with_input(self, agent_input):
        self.seen_code = self.require_context_value(agent_input, "code")
        return super().run_with_input(agent_input)


def build_registry(config: KYCortexConfig):
    architect = ArchitectAgent(config)
    architect._provider = DummyProvider("ARCHITECTURE DOC")
    engineer = RecordingCodeEngineerAgent(config, DummyProvider("print('hello world')"))
    reviewer = RecordingCodeReviewerAgent(config, DummyProvider("PASS: code reviewed"))
    tester = RecordingQATesterAgent(config, DummyProvider("def test_example():\n    assert True"))
    registry = AgentRegistry(
        {
            "architect": architect,
            "code_engineer": engineer,
            "code_reviewer": reviewer,
            "qa_tester": tester,
        }
    )
    return registry, engineer, reviewer, tester


def test_dependency_chain_propagates_semantic_context_and_artifacts(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    registry, engineer, reviewer, tester = build_registry(config)
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
            description="Implement the service",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the implementation",
            assigned_to="code_reviewer",
            dependencies=["code"],
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests for the implementation",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    orchestrator = Orchestrator(config, registry=registry)

    orchestrator.execute_workflow(project)

    assert engineer.seen_architecture == "ARCHITECTURE DOC"
    assert reviewer.seen_code == "print('hello world')"
    assert tester.seen_code == "print('hello world')"
    assert [task.status for task in project.tasks] == [
        TaskStatus.DONE.value,
        TaskStatus.DONE.value,
        TaskStatus.DONE.value,
        TaskStatus.DONE.value,
    ]
    assert project.snapshot().workflow_status == WorkflowStatus.COMPLETED

    artifacts_by_name = artifact_map(project)

    assert artifacts_by_name["arch_architecture"]["artifact_type"] == ArtifactType.DOCUMENT.value
    assert artifacts_by_name["code_implementation"]["artifact_type"] == ArtifactType.CODE.value
    assert artifacts_by_name["review_review"]["artifact_type"] == ArtifactType.DOCUMENT.value
    assert artifacts_by_name["tests_tests"]["artifact_type"] == ArtifactType.TEST.value


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_reloaded_outputs_preserve_downstream_code_context_and_artifacts(tmp_path, state_filename):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    state_path = tmp_path / state_filename
    registry, engineer, reviewer, _ = build_registry(config)
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
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
            description="Implement the service",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the implementation",
            assigned_to="code_reviewer",
            dependencies=["code"],
        )
    )

    orchestrator = Orchestrator(config, registry=registry)

    orchestrator.run_task(require_task(project, "arch"), project)
    project.save()
    orchestrator.run_task(require_task(project, "code"), project)
    project.save()

    reloaded = ProjectState.load(str(state_path))
    reloaded_reviewer = RecordingCodeReviewerAgent(config, DummyProvider("PASS: code reviewed"))
    reloaded_registry = AgentRegistry(
        {
            "architect": registry.get("architect"),
            "code_engineer": engineer,
            "code_reviewer": reloaded_reviewer,
        }
    )

    Orchestrator(config, registry=reloaded_registry).execute_workflow(reloaded)

    reloaded_arch = require_task(reloaded, "arch")
    reloaded_code = require_task(reloaded, "code")
    reloaded_review = require_task(reloaded, "review")
    assert reloaded_arch.status == TaskStatus.DONE.value
    assert reloaded_code.status == TaskStatus.DONE.value
    assert reloaded_review.status == TaskStatus.DONE.value
    assert reloaded_reviewer.seen_code == "print('hello world')"

    snapshot_artifacts = {artifact.name: artifact for artifact in reloaded.snapshot().artifacts}

    assert snapshot_artifacts["arch_architecture"].artifact_type == ArtifactType.DOCUMENT
    assert snapshot_artifacts["code_implementation"].artifact_type == ArtifactType.CODE
    assert snapshot_artifacts["review_review"].artifact_type == ArtifactType.DOCUMENT