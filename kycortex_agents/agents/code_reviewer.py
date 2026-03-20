from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig

SYSTEM_PROMPT = """You are a Senior Code Reviewer at KYCortex AI Software House.
Review Python code for: correctness, security vulnerabilities, performance issues,
code style (PEP8), missing tests, missing docstrings, bad practices.
Output a structured review with: PASS/FAIL verdict, list of issues (critical/minor),
and corrected code if needed."""

class CodeReviewerAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig):
        super().__init__("CodeReviewer", "Code Quality & Security Review", config)

    def run(self, task_description: str, context: dict) -> str:
        code = context.get("code", "")
        user_msg = f"""Review this code:

```python
{code}
```

Task context: {task_description}

Provide structured review with verdict and issues."""
        return self.chat(SYSTEM_PROMPT, user_msg)
