from kycortex_agents import AgentRegistry, ArtifactType, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.types import AgentInput, AgentOutput


class SummaryAgent(BaseAgent):
    required_context_keys = ("architecture",)
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "summary"

    def __init__(self, config: KYCortexConfig):
        super().__init__(name="Summary Agent", role="summarizer", config=config)

    def run_with_input(self, agent_input: AgentInput) -> AgentOutput:
        architecture = self.require_context_value(agent_input, "architecture")
        summary = architecture.splitlines()[0].strip()
        return AgentOutput(
            summary=f"Summary ready for {agent_input.project_name}",
            raw_content=f"Architecture summary: {summary}",
            metadata={"custom_agent": True},
        )

    def run(self, task_description: str, context: dict) -> str:
        raise NotImplementedError


class RecordingArchitectAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig, response: str):
        super().__init__(name="Recording Architect", role="architect", config=config)
        self.response = response

    def run(self, task_description: str, context: dict) -> str:
        return self.response


if __name__ == "__main__":
    config = KYCortexConfig(
        project_name="custom-agent-demo",
        output_dir="./output_custom_agent_demo",
    )

    registry = AgentRegistry(
        {
            "architect": RecordingArchitectAgent(config, "Service boundary: API, worker, storage"),
            "summary_agent": SummaryAgent(config),
        }
    )

    project = ProjectState(
        project_name="CustomAgentDemo",
        goal="Demonstrate a custom agent using BaseAgent and AgentRegistry",
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the system architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="summary",
            title="Summarize architecture",
            description="Summarize the completed architecture for stakeholders",
            assigned_to="summary_agent",
            dependencies=["arch"],
        )
    )

    orchestrator = Orchestrator(config, registry=registry)
    orchestrator.execute_workflow(project)
    summary_task = project.get_task("summary")
    if summary_task is None:
        raise RuntimeError("summary task missing from project state")

    print("Custom agent workflow summary:")
    print(project.summary())
    print("\nSummary output:")
    print(summary_task.output)