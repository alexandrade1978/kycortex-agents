from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput

SYSTEM_PROMPT = """You are a Legal & Compliance Advisor at KYCortex AI Software House.
You specialise in open-source software licensing, intellectual property, and GDPR.
For each request: identify license compatibility, flag GPL/AGPL risks, draft NOTICE files,
check third-party dependency licenses, and draft Privacy Policy / ToS templates.
Always note: this is informational only and not legal advice."""

class LegalAdvisorAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("LegalAdvisor", "Legal & Compliance", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        dependencies = agent_input.context.get("dependencies", [])
        chosen_license = agent_input.context.get("license", "Apache-2.0")
        dep_list = "\n".join(f"- {dependency}" for dependency in dependencies) if dependencies else "Not specified"
        user_msg = f"""Project: {agent_input.project_name}
Goal: {agent_input.project_goal}
Project License: {chosen_license}
Dependencies:
{dep_list}

Task: {agent_input.task_description}

Provide legal analysis and draft any required legal documents."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        dependencies = context.get("dependencies", [])
        chosen_license = context.get("license", "Apache-2.0")
        dep_list = "\n".join(f"- {d}" for d in dependencies) if dependencies else "Not specified"
        user_msg = f"""Project License: {chosen_license}
Dependencies:
{dep_list}

Task: {task_description}

Provide legal analysis and draft any required legal documents."""
        return self.chat(SYSTEM_PROMPT, user_msg)
