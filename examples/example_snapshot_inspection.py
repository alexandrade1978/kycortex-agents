from kycortex_agents import AgentRegistry, ArtifactType, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.providers import BaseLLMProvider
from kycortex_agents.types import AgentInput, AgentOutput, DecisionRecord


class FakeMetadataProvider(BaseLLMProvider):
    def __init__(self, response: str, metadata: dict):
        self.response = response
        self.metadata = metadata

    def generate(self, system_prompt: str, user_message: str) -> str:
        return self.response

    def get_last_call_metadata(self) -> dict:
        return dict(self.metadata)


class SnapshotAgent(BaseAgent):
    def __init__(
        self,
        config: KYCortexConfig,
        name: str,
        role: str,
        artifact_type: ArtifactType,
        artifact_name: str,
        response: str,
        provider_name: str,
        model_name: str,
        decision_topic: str,
    ):
        super().__init__(name=name, role=role, config=config)
        self.output_artifact_type = artifact_type
        self.output_artifact_name = artifact_name
        self._provider = FakeMetadataProvider(
            response=response,
            metadata={
                "usage": {"total_tokens": len(response.split()) + 5},
                "provider": provider_name,
                "model": model_name,
            },
        )
        self.decision_topic = decision_topic

    def run_with_input(self, agent_input: AgentInput) -> AgentOutput:
        raw_content = self.chat("system", agent_input.task_description)
        return AgentOutput(
            summary=raw_content.splitlines()[0].strip(),
            raw_content=raw_content,
            decisions=[
                DecisionRecord(
                    topic=self.decision_topic,
                    decision=f"{self.name} completed deterministically.",
                    rationale=f"Recorded while inspecting snapshot data for {agent_input.task_id}.",
                )
            ],
        )

    def run(self, task_description: str, context: dict) -> str:
        raise NotImplementedError


def build_snapshot_registry(config: KYCortexConfig) -> AgentRegistry:
    return AgentRegistry(
        {
            "architect": SnapshotAgent(
                config,
                name="Snapshot Architect",
                role="architect",
                artifact_type=ArtifactType.DOCUMENT,
                artifact_name="architecture",
                response="Architecture snapshot ready",
                provider_name="openai",
                model_name="snapshot-openai-demo",
                decision_topic="architecture_snapshot",
            ),
            "code_reviewer": SnapshotAgent(
                config,
                name="Snapshot Reviewer",
                role="code_reviewer",
                artifact_type=ArtifactType.DOCUMENT,
                artifact_name="review",
                response="Review snapshot ready",
                provider_name="anthropic",
                model_name="snapshot-anthropic-demo",
                decision_topic="review_snapshot",
            ),
        }
    )


def build_snapshot_project(state_path: str) -> ProjectState:
    project = ProjectState(
        project_name="SnapshotInspectionDemo",
        goal="Demonstrate how to inspect structured snapshot state after a workflow run.",
        state_file=state_path,
    )
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
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )
    return project


if __name__ == "__main__":
    state_path = "./output_snapshot_inspection_demo/project_state.json"
    config = KYCortexConfig(
        project_name="snapshot-inspection-demo",
        output_dir="./output_snapshot_inspection_demo",
    )
    project = build_snapshot_project(state_path)
    registry = build_snapshot_registry(config)

    Orchestrator(config, registry=registry).execute_workflow(project)

    snapshot = project.snapshot()

    print("Snapshot workflow status:")
    print(snapshot.workflow_status)
    print("\nTask results:")
    for task_id, task_result in snapshot.task_results.items():
        provider_call = task_result.details.get("last_provider_call")
        print(
            f"- {task_id}: status={task_result.status.value}, "
            f"summary={task_result.output.summary if task_result.output else None}, "
            f"provider={provider_call['provider'] if provider_call else None}, "
            f"model={provider_call['model'] if provider_call else None}"
        )

    print("\nWorkflow telemetry:")
    print(snapshot.workflow_telemetry)

    print("\nArtifacts:")
    print([artifact.name for artifact in snapshot.artifacts])
    print("\nDecisions:")
    print([decision.topic for decision in snapshot.decisions])
    print("\nExecution events:")
    print([event["event"] for event in snapshot.execution_events])
