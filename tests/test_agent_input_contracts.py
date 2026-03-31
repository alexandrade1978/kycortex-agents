import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import AgentInput, AgentOutput, TaskStatus


class InspectableAgent(BaseAgent):
    required_context_keys = ("architecture",)

    def __init__(self, config: KYCortexConfig):
        super().__init__("Inspectable", "Testing", config)
        self.last_input: AgentInput | None = None

    def run(self, task_description: str, context: dict) -> str:
        return "ok"

    def run_with_input(self, agent_input: AgentInput) -> str | AgentOutput:
        self.last_input = agent_input
        return super().run_with_input(agent_input)


def require_task(project: ProjectState, task_id: str) -> Task:
    task = project.get_task(task_id)
    assert task is not None
    return task


def build_config(tmp_path):
    config = KYCortexConfig()
    config.output_dir = str(tmp_path / "output")
    config.api_key = "token"
    return config


def build_input(**overrides):
    payload = {
        "task_id": "task-1",
        "task_title": "Task",
        "task_description": "Implement feature",
        "project_name": "Demo",
        "project_goal": "Build demo",
        "context": {"architecture": "Layered design"},
    }
    payload.update(overrides)
    return AgentInput(**payload)


@pytest.mark.parametrize(
    ("field_name", "value", "error_fragment"),
    [
        ("task_id", "", "task_id must not be empty"),
        ("task_title", "   ", "task_title must not be empty"),
        ("task_description", "", "task_description must not be empty"),
        ("project_name", "", "project_name must not be empty"),
    ],
)
def test_execute_rejects_empty_public_agent_input_fields(tmp_path, field_name, value, error_fragment):
    agent = InspectableAgent(build_config(tmp_path))
    payload = {field_name: value}

    with pytest.raises(AgentExecutionError, match=error_fragment):
        agent.execute(build_input(**payload))


def test_execute_rejects_non_mapping_context(tmp_path):
    agent = InspectableAgent(build_config(tmp_path))

    with pytest.raises(AgentExecutionError, match="context must be a dictionary"):
        agent.execute(build_input(context=["architecture"]))


@pytest.mark.parametrize(
    ("context", "error_fragment"),
    [
        ({"architecture": None}, "required context key 'architecture' is missing"),
        ({"architecture": "   "}, "required context key 'architecture' must not be empty"),
    ],
)
def test_required_context_keys_reject_none_and_blank_values(tmp_path, context, error_fragment):
    agent = InspectableAgent(build_config(tmp_path))

    with pytest.raises(AgentExecutionError, match=error_fragment):
        agent.execute(build_input(context=context))


def test_orchestrator_context_exposes_only_completed_outputs_and_transitive_semantic_keys(tmp_path):
    config = build_config(tmp_path)
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
            id="code",
            title="Implementation",
            description="Implement",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="print('hello')",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="blocked",
            title="Blocked review",
            description="Blocked",
            assigned_to="code_reviewer",
            status=TaskStatus.FAILED.value,
            output="boom",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review implementation",
            assigned_to="review_agent",
            dependencies=["code"],
        )
    )

    agent = InspectableAgent(config)
    orchestrator = Orchestrator(config, registry=AgentRegistry({"review_agent": agent}))

    result = orchestrator.run_task(require_task(project, "review"), project)
    assert agent.last_input is not None
    context = agent.last_input.context

    assert result == "ok"
    assert context["arch"] == "ARCHITECTURE DOC"
    assert context["code"] == "print('hello')"
    assert context["architecture"] == "ARCHITECTURE DOC"
    assert context["completed_tasks"] == {
        "arch": "ARCHITECTURE DOC",
        "code": "print('hello')",
    }
    assert "blocked" not in context
    assert "review" not in context
    assert "review" not in context["completed_tasks"]
    review_task = require_task(project, "review")
    assert review_task.status == TaskStatus.DONE.value
