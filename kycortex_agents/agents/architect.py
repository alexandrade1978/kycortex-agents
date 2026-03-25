from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType

DEFAULT_CONSTRAINTS = "Python 3.10+, production-ready dependencies, licensing suitable for open-source or commercial distribution"

SYSTEM_PROMPT = """You are a Senior Software Architect at KYCortex AI Software House.
Your job is to design modular, scalable Python project architectures.
Output structured architecture documents including: module breakdown, file structure,
interfaces, data flows, technology choices and rationale.
Always think about extensibility, testability and open-source best practices.
If the task asks for a single Python module or single file, keep the architecture scoped to that single module and do not invent a multi-file package layout.
When a target module filename is provided, describe only that file and avoid directory trees."""

class ArchitectAgent(BaseAgent):
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "architecture"

    def __init__(self, config: KYCortexConfig):
        super().__init__("Architect", "Software Architecture Design", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        constraints = ", ".join(agent_input.constraints) if agent_input.constraints else DEFAULT_CONSTRAINTS
        planned_module_filename = agent_input.context.get("planned_module_filename", "")
        user_msg = f"""Project Name: {agent_input.project_name}
Project Goal: {agent_input.project_goal}
Constraints: {constraints}
    Target module: {planned_module_filename or 'Not specified'}
Task: {agent_input.task_description}

Provide a detailed architecture document.
    Respect the task scope exactly: if the requested deliverable is a single Python module, the architecture must describe a single-module design.
    If a target module is provided, document only that one file and do not include a package tree."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        goal = context.get("goal", "")
        constraints = context.get("constraints", DEFAULT_CONSTRAINTS)
        planned_module_filename = context.get("planned_module_filename", "")
        user_msg = f"""Project Goal: {goal}
Constraints: {constraints}
    Target module: {planned_module_filename or 'Not specified'}
Task: {task_description}

Provide a detailed architecture document.
    Respect the task scope exactly: if the requested deliverable is a single Python module, the architecture must describe a single-module design.
    If a target module is provided, document only that one file and do not include a package tree."""
        return self.chat(SYSTEM_PROMPT, user_msg)
