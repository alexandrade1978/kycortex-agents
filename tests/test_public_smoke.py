from kycortex_agents import AgentRegistry, ArtifactType, BaseAgent, KYCortexConfig, workflows
from kycortex_agents.types import AgentInput, AgentOutput, TaskStatus, WorkflowStatus


class PublicArchitectAgent(BaseAgent):
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "architecture"

    def __init__(self, config: KYCortexConfig):
        super().__init__("PublicArchitect", "Architecture", config)

    def run_with_input(self, agent_input: AgentInput) -> AgentOutput:
        return AgentOutput(
            summary="Architecture ready",
            raw_content=f"ARCHITECTURE for {agent_input.project_name}",
        )

    def run(self, task_description: str, context: dict) -> str:
        raise NotImplementedError


class PublicReviewerAgent(BaseAgent):
    required_context_keys = ("architecture",)
    output_artifact_name = "review"

    def __init__(self, config: KYCortexConfig):
        super().__init__("PublicReviewer", "Review", config)
        self.seen_architecture = None

    def run_with_input(self, agent_input: AgentInput) -> str:
        architecture = self.require_context_value(agent_input, "architecture")
        self.seen_architecture = architecture
        return f"REVIEWED: {architecture}"

    def run(self, task_description: str, context: dict) -> str:
        raise NotImplementedError


def test_root_public_api_executes_dependency_workflow(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    reviewer = PublicReviewerAgent(config)
    registry = AgentRegistry(
        {
            "architect": PublicArchitectAgent(config),
            "code_reviewer": reviewer,
        }
    )
    project = workflows.ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        workflows.Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        workflows.Task(
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )

    orchestrator = workflows.Orchestrator(config, registry=registry)

    orchestrator.execute_workflow(project)
    arch_task = project.get_task("arch")
    review_task = project.get_task("review")

    assert arch_task is not None
    assert review_task is not None

    assert arch_task.status == TaskStatus.DONE.value
    assert review_task.status == TaskStatus.DONE.value
    assert reviewer.seen_architecture == "ARCHITECTURE for Demo"
    assert project.snapshot().workflow_status == WorkflowStatus.COMPLETED
    assert project.execution_events[-1]["event"] == "workflow_finished"


def test_workflows_module_smoke_supports_public_resume_flow(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_resume_policy="resume_failed",
    )
    reviewer = PublicReviewerAgent(config)
    registry = AgentRegistry(
        {
            "architect": PublicArchitectAgent(config),
            "code_reviewer": reviewer,
        }
    )
    state_path = tmp_path / "project_state.json"
    project = workflows.ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        workflows.Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.RUNNING.value,
            attempts=1,
        )
    )
    project.add_task(
        workflows.Task(
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )
    project.save()

    reloaded = workflows.ProjectState.load(str(state_path))
    orchestrator = workflows.Orchestrator(config, registry=registry)

    orchestrator.execute_workflow(reloaded)
    arch_task = reloaded.get_task("arch")
    review_task = reloaded.get_task("review")

    assert arch_task is not None
    assert review_task is not None

    assert arch_task.attempts == 2
    assert arch_task.status == TaskStatus.DONE.value
    assert review_task.status == TaskStatus.DONE.value
    assert reloaded.workflow_last_resumed_at is not None
    assert any(event["event"] == "workflow_resumed" for event in reloaded.execution_events)