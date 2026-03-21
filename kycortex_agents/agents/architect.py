from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput

SYSTEM_PROMPT = """You are a Senior Software Architect at KYCortex AI Software House.
Your job is to design modular, scalable Python project architectures.
Output structured architecture documents including: module breakdown, file structure,
interfaces, data flows, technology choices and rationale.
Always think about extensibility, testability and open-source best practices."""

class ArchitectAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("Architect", "Software Architecture Design", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        constraints = ", ".join(agent_input.constraints) if agent_input.constraints else "Apache 2.0, Python 3.10+, no GPL deps"
        user_msg = f"""Project Name: {agent_input.project_name}
Project Goal: {agent_input.project_goal}
Constraints: {constraints}
Task: {agent_input.task_description}

Provide a detailed architecture document."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        goal = context.get("goal", "")
        constraints = context.get("constraints", "Apache 2.0, Python 3.10+, no GPL deps")
        user_msg = f"""Project Goal: {goal}
Constraints: {constraints}
Task: {task_description}

Provide a detailed architecture document."""
        return self.chat(SYSTEM_PROMPT, user_msg)
