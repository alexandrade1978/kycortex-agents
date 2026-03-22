from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import AgentOutput, TaskStatus


class ExecuteFirstAgent:
    def __init__(self):
        self.called = []

    def execute(self, agent_input):
        self.called.append("execute")
        return AgentOutput(summary="Structured", raw_content="EXECUTE RESULT")

    def run_with_input(self, agent_input):
        self.called.append("run_with_input")
        raise AssertionError("run_with_input should not be used when execute exists")

    def run(self, task_description: str, context: dict) -> str:
        self.called.append("run")
        raise AssertionError("run should not be used when execute exists")


class RunWithInputAgent:
    def __init__(self):
        self.called = []
        self.last_input = None

    def run_with_input(self, agent_input):
        self.called.append("run_with_input")
        self.last_input = agent_input
        return "RUN WITH INPUT RESULT"

    def run(self, task_description: str, context: dict) -> str:
        self.called.append("run")
        raise AssertionError("run should not be used when run_with_input exists")


class LegacyRunAgent:
    def __init__(self):
        self.called = []
        self.last_description = None
        self.last_context = None

    def run(self, task_description: str, context: dict) -> str:
        self.called.append("run")
        self.last_description = task_description
        self.last_context = context
        return "LEGACY RESULT"


def build_project():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    return project


def test_orchestrator_prefers_execute_over_other_agent_entrypoints(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    agent = ExecuteFirstAgent()
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": agent}))
    project = build_project()

    result = orchestrator.run_task(project.get_task("arch"), project)

    assert result == "EXECUTE RESULT"
    assert agent.called == ["execute"]
    assert project.get_task("arch").status == TaskStatus.DONE.value
    assert project.get_task("arch").output_payload["summary"] == "Structured"


def test_orchestrator_uses_run_with_input_before_legacy_run(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    agent = RunWithInputAgent()
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": agent}))
    project = build_project()

    result = orchestrator.run_task(project.get_task("arch"), project)

    assert result == "RUN WITH INPUT RESULT"
    assert agent.called == ["run_with_input"]
    assert agent.last_input.task_id == "arch"
    assert agent.last_input.project_name == "Demo"
    assert project.get_task("arch").status == TaskStatus.DONE.value


def test_orchestrator_falls_back_to_legacy_run_signature(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    agent = LegacyRunAgent()
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": agent}))
    project = build_project()

    result = orchestrator.run_task(project.get_task("arch"), project)

    assert result == "LEGACY RESULT"
    assert agent.called == ["run"]
    assert agent.last_description == "Design the architecture"
    assert agent.last_context["project_name"] == "Demo"
    assert agent.last_context["task"]["id"] == "arch"
    assert project.get_task("arch").status == TaskStatus.DONE.value