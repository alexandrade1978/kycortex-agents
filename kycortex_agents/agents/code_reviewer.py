from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType

SYSTEM_PROMPT = """You are a Senior Code Reviewer at KYCortex AI Software House.
Review Python code for: correctness, security vulnerabilities, performance issues,
code style (PEP8), missing tests, missing docstrings, bad practices.
Output a structured review with: PASS/FAIL verdict, list of issues (critical/minor),
and corrected code if needed."""

class CodeReviewerAgent(BaseAgent):
    required_context_keys = ("code",)
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "review"

    def __init__(self, config: KYCortexConfig):
        super().__init__("CodeReviewer", "Code Quality & Security Review", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        code = self.require_context_value(agent_input, "code")
        user_msg = f"""Project: {agent_input.project_name}
Review this code:

```python
{code}
```

Task context: {agent_input.task_description}

Provide structured review with verdict and issues."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        code = context.get("code", "")
        user_msg = f"""Review this code:

```python
{code}
```

Task context: {task_description}

Provide structured review with verdict and issues."""
        return self.chat(SYSTEM_PROMPT, user_msg)
