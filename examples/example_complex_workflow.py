from kycortex_agents import AgentRegistry, ArtifactType, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.types import AgentInput, AgentOutput, DecisionRecord


class StructuredRecordingAgent(BaseAgent):
    def __init__(
        self,
        config: KYCortexConfig,
        name: str,
        role: str,
        artifact_type: ArtifactType,
        artifact_name: str,
        response: str,
        decision_topic: str | None = None,
        decision_text: str | None = None,
    ):
        super().__init__(name=name, role=role, config=config)
        self.output_artifact_type = artifact_type
        self.output_artifact_name = artifact_name
        self.response = response
        self.decision_topic = decision_topic
        self.decision_text = decision_text

    def run_with_input(self, agent_input: AgentInput) -> AgentOutput:
        decisions = []
        if self.decision_topic is not None and self.decision_text is not None:
            decisions.append(
                DecisionRecord(
                    topic=self.decision_topic,
                    decision=self.decision_text,
                    rationale=f"Recorded by {self.name} during the deterministic complex-workflow demo.",
                )
            )
        return AgentOutput(
            summary=self.response.splitlines()[0].strip(),
            raw_content=self.response,
            decisions=decisions,
        )

    def run(self, task_description: str, context: dict) -> str:
        raise NotImplementedError


class MergeDocumentationAgent(BaseAgent):
    required_context_keys = ("architecture", "code", "review", "tests")
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "merged_documentation"

    def __init__(self, config: KYCortexConfig):
        super().__init__(name="Merge Documentation", role="docs_writer", config=config)

    def run_with_input(self, agent_input: AgentInput) -> AgentOutput:
        architecture = self.require_context_value(agent_input, "architecture")
        implementation = self.require_context_value(agent_input, "code")
        review = self.require_context_value(agent_input, "review")
        tests = self.require_context_value(agent_input, "tests")
        artifacts = agent_input.context["artifacts"]
        decisions = agent_input.context["decisions"]
        artifact_names = [artifact.name for artifact in artifacts]
        decision_topics = [decision.topic for decision in decisions]
        completed_task_ids = sorted(agent_input.context["completed_tasks"].keys())

        return AgentOutput(
            summary="Merged documentation package ready",
            raw_content=(
                "Complex workflow output bundle\n"
                f"Architecture: {architecture}\n"
                f"Implementation: {implementation}\n"
                f"Review: {review}\n"
                f"Tests: {tests}\n"
                f"Artifacts: {', '.join(artifact_names)}\n"
                f"Decision topics: {', '.join(decision_topics)}\n"
                f"Completed tasks: {', '.join(completed_task_ids)}"
            ),
            decisions=[
                DecisionRecord(
                    topic="documentation_merge",
                    decision="Merged upstream workflow outputs into one delivery packet.",
                    rationale="A converging DAG example should show how downstream tasks see artifacts and decisions from multiple parents.",
                )
            ],
            metadata={
                "artifact_names": artifact_names,
                "decision_topics": decision_topics,
                "completed_task_ids": completed_task_ids,
            },
        )

    def run(self, task_description: str, context: dict) -> str:
        raise NotImplementedError


def build_complex_registry(config: KYCortexConfig) -> AgentRegistry:
    return AgentRegistry(
        {
            "architect": StructuredRecordingAgent(
                config,
                name="Recording Architect",
                role="architect",
                artifact_type=ArtifactType.DOCUMENT,
                artifact_name="architecture",
                response="Service boundaries: API, worker, persistence",
                decision_topic="architecture_style",
                decision_text="Use a three-layer service split for orchestration, execution, and persistence.",
            ),
            "code_engineer": StructuredRecordingAgent(
                config,
                name="Recording Engineer",
                role="code_engineer",
                artifact_type=ArtifactType.CODE,
                artifact_name="implementation",
                response="def run_service() -> str:\n    return 'service-ready'",
            ),
            "code_reviewer": StructuredRecordingAgent(
                config,
                name="Recording Reviewer",
                role="code_reviewer",
                artifact_type=ArtifactType.DOCUMENT,
                artifact_name="review",
                response="Review result: service code matches the planned module boundaries.",
                decision_topic="review_status",
                decision_text="Approved the implementation for integration testing.",
            ),
            "qa_tester": StructuredRecordingAgent(
                config,
                name="Recording Tester",
                role="qa_tester",
                artifact_type=ArtifactType.TEST,
                artifact_name="tests",
                response="def test_run_service() -> None:\n    assert run_service() == 'service-ready'",
            ),
            "docs_writer": MergeDocumentationAgent(config),
        }
    )


def build_complex_project(state_path: str) -> ProjectState:
    project = ProjectState(
        project_name="ComplexWorkflowDemo",
        goal="Demonstrate a converging workflow graph with artifact and decision flow across multiple parents.",
        state_file=state_path,
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the service architecture",
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
            description="Write integration tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Merge architecture, review, and test outputs into a final delivery packet",
            assigned_to="docs_writer",
            dependencies=["review", "tests"],
        )
    )
    return project


def _format_csv(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def main() -> None:
    state_path = "./output_complex_workflow_demo/project_state.json"
    config = KYCortexConfig(
        project_name="complex-workflow-demo",
        output_dir="./output_complex_workflow_demo",
    )
    registry = build_complex_registry(config)
    project = build_complex_project(state_path)

    Orchestrator(config, registry=registry).execute_workflow(project)

    snapshot = project.snapshot()
    docs_task = project.get_task("docs")
    if docs_task is None:
        raise RuntimeError("docs task missing from project state")

    print("Complex workflow summary:")
    print(project.summary())
    print("\nMerged documentation output:")
    print(docs_task.output)
    print("\nArtifact names:")
    print(f"artifact_names={_format_csv([artifact.name for artifact in snapshot.artifacts])}")
    print("\nDecision topics:")
    print(f"decision_topics={_format_csv([decision.topic for decision in snapshot.decisions])}")


if __name__ == "__main__":
    main()
