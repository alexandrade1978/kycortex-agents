from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task


class AlwaysFailAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig, message: str):
        super().__init__(name="Always Fail Agent", role="architect", config=config)
        self.message = message

    def run(self, task_description: str, context: dict) -> str:
        raise RuntimeError(self.message)


class RecordingAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig, name: str, role: str, response: str):
        super().__init__(name=name, role=role, config=config)
        self.response = response

    def run(self, task_description: str, context: dict) -> str:
        return self.response


def build_recovery_project(state_path: str) -> ProjectState:
    project = ProjectState(
        project_name="FailureRecoveryDemo",
        goal="Demonstrate terminal workflow failure, persisted reload, and resume_failed recovery.",
        state_file=state_path,
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            retry_limit=1,
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the architecture after recovery",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )
    return project


if __name__ == "__main__":
    state_path = "./output_failure_recovery_demo/project_state.sqlite"
    config = KYCortexConfig(
        project_name="failure-recovery-demo",
        output_dir="./output_failure_recovery_demo",
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
    )
    project = build_recovery_project(state_path)

    first_registry = AgentRegistry(
        {
            "architect": AlwaysFailAgent(config, "boom-from-first-run"),
            "code_reviewer": RecordingAgent(config, "Recording Reviewer", "code_reviewer", "REVIEWED ARCHITECTURE"),
        }
    )
    first_orchestrator = Orchestrator(config, registry=first_registry)

    try:
        first_orchestrator.execute_workflow(project)
    except Exception as exc:
        print(f"First run failed with {type(exc).__name__}: {exc}")

    failed = ProjectState.load(state_path)
    failed_arch = failed.get_task("arch")
    if failed_arch is None:
        raise RuntimeError("arch task missing after failed run")

    print("\nPersisted failed state:")
    print(f"- arch status: {failed_arch.status}")
    print(f"- arch attempts: {failed_arch.attempts}")
    print(f"- last error type: {failed_arch.last_error_type}")

    resume_registry = AgentRegistry(
        {
            "architect": RecordingAgent(config, "Recovered Architect", "architect", "ARCHITECTURE DOC"),
            "code_reviewer": RecordingAgent(config, "Recovered Reviewer", "code_reviewer", "REVIEWED ARCHITECTURE"),
        }
    )
    resume_orchestrator = Orchestrator(config, registry=resume_registry)
    resume_orchestrator.execute_workflow(failed)

    print("\nResumed workflow summary:")
    print(failed.summary())
    print(f"Workflow resumed at: {failed.workflow_last_resumed_at}")
    print("\nTask histories:")
    for task in failed.tasks:
        history_events = [entry["event"] for entry in task.history]
        print(f"- {task.id}: status={task.status}, attempts={task.attempts}, history={history_events}")
