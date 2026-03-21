from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput

SYSTEM_PROMPT = """You are a QA Engineer at KYCortex AI Software House.
You write comprehensive pytest test suites.
For each module/function, write: unit tests, edge case tests, integration test stubs.
Use fixtures, parametrize where appropriate. Aim for 80%+ coverage."""

class QATesterAgent(BaseAgent):
    required_context_keys = ("code",)

    def __init__(self, config: KYCortexConfig):
        super().__init__("QATester", "Quality Assurance & Testing", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        code = self.require_context_value(agent_input, "code")
        module_name = agent_input.context.get("module_name", "module")
        user_msg = f"""Project: {agent_input.project_name}
Write pytest tests for this Python code:

```python
{code}
```

Module name: {module_name}
Task: {agent_input.task_description}

Write complete test file."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        code = context.get("code", "")
        module_name = context.get("module_name", "module")
        user_msg = f"""Write pytest tests for this Python code:

```python
{code}
```

Module name: {module_name}
Task: {task_description}

Write complete test file."""
        return self.chat(SYSTEM_PROMPT, user_msg)
