from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig

SYSTEM_PROMPT = """You are a Senior Python Engineer at KYCortex AI Software House.
You write clean, well-documented, production-quality Python code.
Always include: type hints, docstrings, error handling, logging.
Follow PEP8. Write modular code with clear separation of concerns.
Do NOT include placeholder comments like # TODO without implementation."""

class CodeEngineerAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("CodeEngineer", "Python Software Development", config)

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
