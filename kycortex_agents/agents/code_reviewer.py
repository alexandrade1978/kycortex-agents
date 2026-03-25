from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType

SYSTEM_PROMPT = """You are a Senior Code Reviewer at KYCortex AI Software House.
Review Python code for: correctness, security vulnerabilities, performance issues,
code style (PEP8), missing tests, missing docstrings, bad practices.
Output a structured review with: PASS/FAIL verdict, list of issues ordered by severity,
and a short remediation plan.
Fail the review if you see runtime errors, inconsistent types, invalid imports, impossible tests,
or documentation that does not match the actual generated module.
Treat the provided validation summary as ground truth. If it lists broken imports, invalid members,
constructor mismatches, or missing dependency manifest entries, the verdict must be FAIL."""

class CodeReviewerAgent(BaseAgent):
    required_context_keys = ("code",)
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "review"

    def __init__(self, config: KYCortexConfig):
        super().__init__("CodeReviewer", "Code Quality & Security Review", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        code = self.require_context_value(agent_input, "code")
        module_name = agent_input.context.get("module_name", "module")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        code_public_api = agent_input.context.get("code_public_api", "")
        tests = agent_input.context.get("tests", "")
        test_validation_summary = agent_input.context.get("test_validation_summary", "")
        dependency_validation_summary = agent_input.context.get("dependency_validation_summary", "")
        user_msg = f"""Project: {agent_input.project_name}
    Module name: {module_name}
    Module file: {module_filename}
    Public API contract:
    {code_public_api}
Review this code:

```python
{code}
```

    Generated tests:
    ```python
    {tests}
    ```
    Test validation summary:
    {test_validation_summary}
    Dependency validation summary:
    {dependency_validation_summary}

Task context: {agent_input.task_description}

Provide structured review with verdict and issues."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        code = context.get("code", "")
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        code_public_api = context.get("code_public_api", "")
        tests = context.get("tests", "")
        test_validation_summary = context.get("test_validation_summary", "")
        dependency_validation_summary = context.get("dependency_validation_summary", "")
        user_msg = f"""Review this code:

    Module name: {module_name}
    Module file: {module_filename}
    Public API contract:
    {code_public_api}

```python
{code}
```

    Generated tests:
    ```python
    {tests}
    ```
    Test validation summary:
    {test_validation_summary}
    Dependency validation summary:
    {dependency_validation_summary}

Task context: {task_description}

Provide structured review with verdict and issues."""
        return self.chat(SYSTEM_PROMPT, user_msg)
