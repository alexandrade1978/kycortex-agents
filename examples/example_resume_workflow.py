from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task


class RecordingAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig, name: str, role: str, response: str):
        super().__init__(name=name, role=role, config=config)
        self.response = response

    def run(self, task_description: str, context: dict) -> str:
        return self.response


if __name__ == "__main__":
    state_path = "./output_resume_demo/project_state.sqlite"
    config = KYCortexConfig(
        project_name="resume-demo",
        output_dir="./output_resume_demo",
        workflow_resume_policy="resume_failed",
    )

    registry = AgentRegistry(
        {
            "architect": RecordingAgent(config, "Recording Architect", "architect", "ARCHITECTURE DOC"),
            "code_reviewer": RecordingAgent(config, "Recording Reviewer", "code_reviewer", "REVIEWED ARCHITECTURE"),
        }
    )

    project = ProjectState(
        project_name="ResumeDemo",
        goal="Demonstrate reloading a persisted workflow and resuming execution",
        state_file=state_path,
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status="running",
            attempts=1,
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

    project.save()
    reloaded = ProjectState.load(state_path)

    orchestrator = Orchestrator(config, registry=registry)
    orchestrator.execute_workflow(reloaded)

    print("Reloaded workflow summary:")
    print(reloaded.summary())
    print(f"State file: {state_path}")
    print(f"Workflow resumed at: {reloaded.workflow_last_resumed_at}")