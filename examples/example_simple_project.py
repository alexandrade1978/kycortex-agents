from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.provider_matrix import _public_path_label


def main() -> None:
    config = KYCortexConfig(
        llm_model="gpt-4o-mini",
        project_name="simple-api",
        output_dir="./output_simple_api",
    )

    project = ProjectState(
        project_name="SimpleRESTAPI",
        goal="Build a simple FastAPI REST API with 2 endpoints: GET /status and POST /data",
    )

    project.add_task(
        Task(
            id="task_1_arch",
            title="Design architecture",
            description="Design module structure for a simple FastAPI project with 2 endpoints.",
            assigned_to="architect",
        )
    )

    project.add_task(
        Task(
            id="task_2_code",
            title="Implement code",
            description="Write the FastAPI application code based on architecture.",
            assigned_to="code_engineer",
            dependencies=["task_1_arch"],
        )
    )

    project.add_task(
        Task(
            id="task_3_review",
            title="Code review",
            description="Review the FastAPI code for issues.",
            assigned_to="code_reviewer",
            dependencies=["task_2_code"],
        )
    )

    orchestrator = Orchestrator(config)
    orchestrator.execute_workflow(project)

    print("\nProject Summary:")
    print(project.summary())
    print(f"\nArtifact files saved to {_public_path_label(config.output_dir or '')}")


if __name__ == "__main__":
    main()
