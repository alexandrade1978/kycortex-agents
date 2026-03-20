import os, sys
sys.path.insert(0, os.path.abspath('..'))

from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.config import KYCortexConfig

if __name__ == "__main__":
    config = KYCortexConfig(
        llm_model="gpt-4o-mini",
        project_name="simple-api",
        output_dir="./output_simple_api"
    )

    project = ProjectState(
        project_name="SimpleRESTAPI",
        goal="Build a simple FastAPI REST API with 2 endpoints: GET /status and POST /data"
    )

    project.add_task(Task(
        id="task_1_arch",
        title="Design architecture",
        description="Design module structure for a simple FastAPI project with 2 endpoints.",
        assigned_to="architect"
    ))

    project.add_task(Task(
        id="task_2_code",
        title="Implement code",
        description="Write the FastAPI application code based on architecture.",
        assigned_to="code_engineer"
    ))

    project.add_task(Task(
        id="task_3_review",
        title="Code review",
        description="Review the FastAPI code for issues.",
        assigned_to="code_reviewer"
    ))

    orchestrator = Orchestrator(config)
    orchestrator.execute_workflow(project)

    print("\nProject Summary:")
    print(project.summary())
    print(f"\nAll outputs saved to {config.output_dir}")
