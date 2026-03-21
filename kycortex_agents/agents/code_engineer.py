from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput

SYSTEM_PROMPT = """You are a Senior Python Engineer at KYCortex AI Software House.
You write clean, well-documented, production-quality Python code.
Always include: type hints, docstrings, error handling, logging.
Follow PEP8. Write modular code with clear separation of concerns.
Do NOT include placeholder comments like # TODO without implementation."""

class CodeEngineerAgent(BaseAgent):
    required_context_keys = ("architecture",)

    def __init__(self, config: KYCortexConfig):
        super().__init__("CodeEngineer", "Python Software Development", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        architecture = self.require_context_value(agent_input, "architecture")
        existing_code = agent_input.context.get("existing_code", "")
        user_msg = f"""Project: {agent_input.project_name}
Goal: {agent_input.project_goal}

Architecture:
{architecture}

Existing code context:
{existing_code}

Task: {agent_input.task_description}

Write the complete Python code for this task."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        architecture = context.get("architecture", "")
        existing_code = context.get("existing_code", "")
        user_msg = f"""Architecture:
{architecture}

Existing code context:
{existing_code}

Task: {task_description}

Write the complete Python code for this task."""
        return self.chat(SYSTEM_PROMPT, user_msg)
