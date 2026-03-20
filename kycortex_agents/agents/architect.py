from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig

SYSTEM_PROMPT = """You are a Senior Software Architect at KYCortex AI Software House.
Your job is to design modular, scalable Python project architectures.
Output structured architecture documents including: module breakdown, file structure,
interfaces, data flows, technology choices and rationale.
Always think about extensibility, testability and open-source best practices."""

class ArchitectAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("Architect", "Software Architecture Design", config)

    def run(self, task_description: str, context: dict) -> str:
        goal = context.get("goal", "")
        constraints = context.get("constraints", "Apache 2.0, Python 3.10+, no GPL deps")
        user_msg = f"""Project Goal: {goal}
Constraints: {constraints}
Task: {task_description}

Provide a detailed architecture document."""
        return self.chat(SYSTEM_PROMPT, user_msg)
