import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import TaskStatus


class RecordingAgent:
    def __init__(self, response: str):
        self.response = response
        self.last_description = None
        self.last_context = None

    def run(self, task_description: str, context: dict) -> str:
        self.last_description = task_description
        self.last_context = context
        return self.response


class FailingAgent:
    def run(self, task_description: str, context: dict) -> str:
        raise RuntimeError("boom")


def test_run_task_exposes_semantic_context(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
        )
    )

    agent = RecordingAgent("IMPLEMENTED CODE")
    orchestrator = Orchestrator(config)
    orchestrator.agents = {"code_engineer": agent}

    result = orchestrator.run_task(project.tasks[1], project)

    assert result == "IMPLEMENTED CODE"
    assert project.tasks[1].status == TaskStatus.DONE.value
    assert agent.last_description == "Implement the application"
    assert agent.last_context["architecture"] == "ARCHITECTURE DOC"
    assert agent.last_context["completed_tasks"]["arch"] == "ARCHITECTURE DOC"
    assert agent.last_context["task"]["id"] == "code"
    assert agent.last_context["snapshot"]["project_name"] == "Demo"


def test_run_task_marks_failure_and_reraises(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    orchestrator = Orchestrator(config)
    orchestrator.agents = {"architect": FailingAgent()}

    with pytest.raises(RuntimeError, match="boom"):
        orchestrator.run_task(project.tasks[0], project)

    assert project.tasks[0].status == TaskStatus.FAILED.value
    assert project.tasks[0].output == "boom"