from kycortex_agents import AgentRegistry, KYCortexConfig, Orchestrator, ProjectState, Task


class RecordingAgent:
    def __init__(self, response: str):
        self.response = response

    def run(self, task_description: str, context: dict) -> str:
        return self.response


def build_test_registry() -> AgentRegistry:
    return AgentRegistry(
        {
            "architect": RecordingAgent("ARCHITECTURE READY"),
            "code_engineer": RecordingAgent("IMPLEMENTATION READY"),
            "code_reviewer": RecordingAgent("REVIEW COMPLETE"),
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


if __name__ == "__main__":
    config = KYCortexConfig(
        project_name="test-mode-demo",
        output_dir="./output_test_mode_demo",
    )
    registry = build_test_registry()
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
        print(f"- {task_id}: {task.output}")