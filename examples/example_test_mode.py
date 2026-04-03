from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task


class RecordingAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig, response: str):
        super().__init__(name="Recording Agent", role="deterministic", config=config)
        self.response = response

    def run(self, task_description: str, context: dict) -> str:
        return self.response


def build_test_registry(config: KYCortexConfig) -> AgentRegistry:
    return AgentRegistry(
        {
            "architect": RecordingAgent(config, "ARCHITECTURE READY"),
            "code_engineer": RecordingAgent(config, "IMPLEMENTATION READY"),
            "code_reviewer": RecordingAgent(config, "REVIEW COMPLETE"),
        }
    )


def build_test_project() -> ProjectState:
    project = ProjectState(
        project_name="TestModeDemo",
        goal="Demonstrate deterministic local workflow execution without live providers",
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
            id="code",
            title="Implementation",
            description="Implement the solution",
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
    return project


def _format_output_presence(output: str | None) -> str:
    return "present" if output else "none"


def main() -> None:
    config = KYCortexConfig(
        project_name="test-mode-demo",
        output_dir="./output_test_mode_demo",
    )
    registry = build_test_registry(config)
    project = build_test_project()

    orchestrator = Orchestrator(config, registry=registry)
    orchestrator.execute_workflow(project)

    print("Deterministic test-mode workflow summary:")
    print(project.summary())
    print("\nCompleted outputs:")
    for task_id in ["arch", "code", "review"]:
        task = project.get_task(task_id)
        if task is None:
            raise RuntimeError(f"missing task: {task_id}")
        print(f"- {task_id}: status={task.status}, output_present={_format_output_presence(task.output)}")


if __name__ == "__main__":
    main()