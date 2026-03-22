import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import AgentInput, ArtifactType, TaskStatus, WorkflowStatus


class StaticAgent(BaseAgent):
    def __init__(self, name: str, role: str, config: KYCortexConfig, response: str, artifact_type: ArtifactType, artifact_name: str):
        super().__init__(name, role, config)
        self.response = response
        self.output_artifact_type = artifact_type
        self.output_artifact_name = artifact_name

    def run(self, task_description: str, context: dict) -> str:
        return self.response


class RecordingMergeAgent(BaseAgent):
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "merged_documentation"

    def __init__(self, config: KYCortexConfig):
        super().__init__("MergeDocs", "Documentation Merge", config)
        self.seen_context = None
        self.seen_artifact_names = None
        self.seen_decision_topics = None

    def run_with_input(self, agent_input: AgentInput) -> str:
        self.seen_context = dict(agent_input.context)
        self.seen_artifact_names = [artifact.name for artifact in agent_input.context["artifacts"]]
        self.seen_decision_topics = [decision.topic for decision in agent_input.context["decisions"]]
        return "MERGED DOCUMENTATION"

    def run(self, task_description: str, context: dict) -> str:
        raise AssertionError("run should not be used")


def build_config(tmp_path):
    return KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="token")


def build_registry(config: KYCortexConfig):
    merge_agent = RecordingMergeAgent(config)
    registry = AgentRegistry(
        {
            "architect": StaticAgent("Architect", "Architecture", config, "ARCHITECTURE DOC", ArtifactType.DOCUMENT, "architecture"),
            "code_engineer": StaticAgent("Engineer", "Implementation", config, "print('hello world')", ArtifactType.CODE, "implementation"),
            "code_reviewer": StaticAgent("Reviewer", "Review", config, "PASS: reviewed", ArtifactType.DOCUMENT, "review"),
            "qa_tester": StaticAgent("Tester", "Testing", config, "def test_example():\n    assert True", ArtifactType.TEST, "tests"),
            "docs_writer": merge_agent,
        }
    )
    return registry, merge_agent


def build_project(state_file: str | None = None):
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=state_file or "project_state.json")
    project.add_task(Task(id="arch", title="Architecture", description="Design the system", assigned_to="architect"))
    project.add_task(Task(id="code", title="Implementation", description="Implement the service", assigned_to="code_engineer", dependencies=["arch"]))
    project.add_task(Task(id="review", title="Review", description="Review the implementation", assigned_to="code_reviewer", dependencies=["code"]))
    project.add_task(Task(id="tests", title="Tests", description="Write tests", assigned_to="qa_tester", dependencies=["code"]))
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Merge architecture, review, and test outputs into docs",
            assigned_to="docs_writer",
            dependencies=["review", "tests"],
        )
    )
    return project


def test_multi_parent_convergence_receives_merged_context_and_artifacts(tmp_path):
    config = build_config(tmp_path)
    registry, merge_agent = build_registry(config)
    project = build_project()

    Orchestrator(config, registry=registry).execute_workflow(project)

    assert merge_agent.seen_context["architecture"] == "ARCHITECTURE DOC"
    assert merge_agent.seen_context["code"] == "print('hello world')"
    assert merge_agent.seen_context["review"] == "PASS: reviewed"
    assert merge_agent.seen_context["tests"] == "def test_example():\n    assert True"
    assert merge_agent.seen_context["completed_tasks"] == {
        "arch": "ARCHITECTURE DOC",
        "code": "print('hello world')",
        "review": "PASS: reviewed",
        "tests": "def test_example():\n    assert True",
    }
    assert merge_agent.seen_artifact_names == [
        "arch_architecture",
        "code_implementation",
        "review_review",
        "tests_tests",
    ]
    assert merge_agent.seen_decision_topics == []
    assert [task.status for task in project.tasks] == [
        TaskStatus.DONE.value,
        TaskStatus.DONE.value,
        TaskStatus.DONE.value,
        TaskStatus.DONE.value,
        TaskStatus.DONE.value,
    ]
    assert project.snapshot().workflow_status == WorkflowStatus.COMPLETED


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_multi_parent_convergence_preserves_upstream_artifacts_after_reload(tmp_path, state_filename):
    config = build_config(tmp_path)
    state_path = tmp_path / state_filename
    registry, merge_agent = build_registry(config)
    project = build_project(str(state_path))
    orchestrator = Orchestrator(config, registry=registry)

    orchestrator.run_task(project.get_task("arch"), project)
    project.save()
    orchestrator.run_task(project.get_task("code"), project)
    project.save()
    orchestrator.run_task(project.get_task("review"), project)
    project.save()
    orchestrator.run_task(project.get_task("tests"), project)
    project.save()

    reloaded = ProjectState.load(str(state_path))
    reloaded_registry, reloaded_merge_agent = build_registry(config)

    Orchestrator(config, registry=reloaded_registry).execute_workflow(reloaded)

    assert reloaded_merge_agent.seen_context["architecture"] == "ARCHITECTURE DOC"
    assert reloaded_merge_agent.seen_context["code"] == "print('hello world')"
    assert reloaded_merge_agent.seen_context["review"] == "PASS: reviewed"
    assert reloaded_merge_agent.seen_context["tests"] == "def test_example():\n    assert True"
    assert reloaded_merge_agent.seen_artifact_names == [
        "arch_architecture",
        "code_implementation",
        "review_review",
        "tests_tests",
    ]

    snapshot_artifacts = {artifact.name: artifact for artifact in reloaded.snapshot().artifacts}

    assert snapshot_artifacts["arch_architecture"].artifact_type == ArtifactType.DOCUMENT
    assert snapshot_artifacts["code_implementation"].artifact_type == ArtifactType.CODE
    assert snapshot_artifacts["review_review"].artifact_type == ArtifactType.DOCUMENT
    assert snapshot_artifacts["tests_tests"].artifact_type == ArtifactType.TEST
    assert reloaded.get_task("docs").status == TaskStatus.DONE.value
