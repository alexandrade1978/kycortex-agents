from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig

SYSTEM_PROMPT = """You are a Technical Documentation Writer at KYCortex AI Software House.
You write clear, complete documentation: README files, API docs, architecture docs,
getting-started guides, and tutorials.
Always include: installation, usage examples, configuration reference, contributing guide.
Use Markdown. Be concise but thorough."""

class DocsWriterAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("DocsWriter", "Technical Documentation", config)

    def run(self, task_description: str, context: dict) -> str:
        project_name = context.get("project_name", "KYCortex")
        architecture = context.get("architecture", "")
        code_summary = context.get("code_summary", "")
        user_msg = f"""Project: {project_name}
Architecture: {architecture}
Code summary: {code_summary}

Task: {task_description}

Write complete documentation in Markdown."""
        return self.chat(SYSTEM_PROMPT, user_msg)
