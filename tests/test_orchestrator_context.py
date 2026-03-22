import pytest

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import ArtifactRecord, ArtifactType, DecisionRecord, TaskStatus


class RecordingAgent:
    def __init__(self, response: str = "ok"):
        self.response = response
        self.last_input = None

    def run_with_input(self, agent_input):
        self.last_input = agent_input
        return self.response


def build_config(tmp_path):
    return KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="token")


def build_inspector_project(role: str, output: str, task_title: str = "Inspector"):
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="upstream",
            title=f"{role} upstream",
            description="Produce upstream output",
            assigned_to=role,
            status=TaskStatus.DONE.value,
            output=output,
        )
    )
    project.add_task(
        Task(
            id="inspect",
            title=task_title,
            description="Inspect context",
            assigned_to="inspector",
            dependencies=["upstream"],
        )
    )
    return project


@pytest.mark.parametrize(
    ("role", "title", "output", "expected_key"),
    [
        ("architect", "Architecture", "ARCHITECTURE DOC", "architecture"),
        ("code_engineer", "Implementation", "print('hello')", "code"),
        ("code_reviewer", "Review", "PASS: reviewed", "review"),
        ("qa_tester", "Tests", "def test_example():\n    assert True", "tests"),
        ("docs_writer", "Documentation", "README content", "documentation"),
        ("legal_advisor", "Legal", "Legal analysis", "legal"),
    ],
)
def test_orchestrator_context_maps_all_public_agent_roles_to_semantic_keys(tmp_path, role, title, output, expected_key):
    config = build_config(tmp_path)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="upstream",
            title=title,
            description="Produce upstream output",
            assigned_to=role,
            status=TaskStatus.DONE.value,
            output=output,
        )
    )
    project.add_task(
        Task(
            id="inspect",
            title="Inspector",
            description="Inspect context",
            assigned_to="inspector",
            dependencies=["upstream"],
        )
    )

    inspector = RecordingAgent()
    Orchestrator(config, registry=AgentRegistry({"inspector": inspector})).run_task(project.get_task("inspect"), project)

    context = inspector.last_input.context

    assert context["upstream"] == output
    assert context["completed_tasks"]["upstream"] == output
    assert context[expected_key] == output


def test_orchestrator_context_for_first_task_exposes_snapshot_without_completed_outputs(tmp_path):
    config = build_config(tmp_path)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="inspect",
            title="Inspector",
            description="Inspect empty context",
            assigned_to="inspector",
        )
    )

    inspector = RecordingAgent()
    Orchestrator(config, registry=AgentRegistry({"inspector": inspector})).run_task(project.get_task("inspect"), project)

    context = inspector.last_input.context

    assert context["project_name"] == "Demo"
    assert context["goal"] == "Build demo"
    assert context["completed_tasks"] == {}
    assert context["decisions"] == []
    assert context["artifacts"] == []
    assert context["snapshot"]["project_name"] == "Demo"
    assert context["snapshot"]["task_results"]["inspect"]["status"] == TaskStatus.PENDING.value
    assert context["task"]["id"] == "inspect"


def test_orchestrator_context_includes_snapshot_decisions_and_artifacts_for_downstream_tasks(tmp_path):
    config = build_config(tmp_path)
    project = build_inspector_project("architect", "ARCHITECTURE DOC")
    project.add_decision_record(
        DecisionRecord(
            topic="stack",
            decision="Use typed runtime",
            rationale="Supports contract validation",
            metadata={"owner": "architect"},
        )
    )
    project.add_artifact_record(
        ArtifactRecord(
            name="architecture.md",
            artifact_type=ArtifactType.DOCUMENT,
            content="# Architecture",
            metadata={"task_id": "upstream"},
        )
    )

    inspector = RecordingAgent()
    Orchestrator(config, registry=AgentRegistry({"inspector": inspector})).run_task(project.get_task("inspect"), project)

    context = inspector.last_input.context

    assert context["architecture"] == "ARCHITECTURE DOC"
    assert context["decisions"][0].topic == "stack"
    assert context["decisions"][0].metadata["owner"] == "architect"
    assert context["artifacts"][0].name == "architecture.md"
    assert context["artifacts"][0].metadata["task_id"] == "upstream"
    assert context["snapshot"]["decisions"][0]["topic"] == "stack"
    assert context["snapshot"]["artifacts"][0]["name"] == "architecture.md"


@pytest.mark.parametrize(
    ("task_title", "expected_key", "output"),
    [
        ("Architecture Decision", "architecture", "ARCHITECTURE DOC"),
        ("Review Findings", "review", "PASS: reviewed"),
        ("Integration Tests", "tests", "def test_example():\n    assert True"),
        ("Docs Refresh", "documentation", "README content"),
        ("License Audit", "legal", "Legal analysis"),
    ],
)
def test_orchestrator_context_uses_task_title_fallback_for_semantic_keys(tmp_path, task_title, expected_key, output):
    config = build_config(tmp_path)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="upstream",
            title=task_title,
            description="Produce upstream output",
            assigned_to="custom_specialist",
            status=TaskStatus.DONE.value,
            output=output,
        )
    )
    project.add_task(
        Task(
            id="inspect",
            title="Inspector",
            description="Inspect context",
            assigned_to="inspector",
            dependencies=["upstream"],
        )
    )

    inspector = RecordingAgent()
    Orchestrator(config, registry=AgentRegistry({"inspector": inspector})).run_task(project.get_task("inspect"), project)

    context = inspector.last_input.context

    assert context["upstream"] == output
    assert context["completed_tasks"]["upstream"] == output
    assert context[expected_key] == output


def test_orchestrator_context_omits_semantic_alias_when_role_and_title_are_unknown(tmp_path):
    config = build_config(tmp_path)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="upstream",
            title="Unmapped Deliverable",
            description="Produce upstream output",
            assigned_to="custom_specialist",
            status=TaskStatus.DONE.value,
            output="RAW OUTPUT",
        )
    )
    project.add_task(
        Task(
            id="inspect",
            title="Inspector",
            description="Inspect context",
            assigned_to="inspector",
            dependencies=["upstream"],
        )
    )

    inspector = RecordingAgent()
    Orchestrator(config, registry=AgentRegistry({"inspector": inspector})).run_task(project.get_task("inspect"), project)

    context = inspector.last_input.context

    assert context["upstream"] == "RAW OUTPUT"
    assert context["completed_tasks"]["upstream"] == "RAW OUTPUT"
    assert "architecture" not in context
    assert "review" not in context
    assert "tests" not in context
    assert "documentation" not in context
    assert "legal" not in context
