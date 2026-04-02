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
constructor mismatches, or missing dependency manifest entries, the verdict must be FAIL.
Keep the review concise and materially grounded.
Return exactly these sections: Verdict, Issues, Remediation.
Report at most 3 distinct issues.
Do not repeat the same issue or category with different wording.
Prioritize correctness, API contract mismatches, validation failures, security, and dependency problems
over generic style, docstring, or line-length nits.
If the validation summaries are clean and you do not see a material defect, return PASS and say
"No material issues found."
For compact generated modules, do not pad the review with repeated PEP8, naming, or docstring-only comments."""

class CodeReviewerAgent(BaseAgent):
    required_context_keys = ("code",)
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "review"

    def __init__(self, config: KYCortexConfig):
        super().__init__("CodeReviewer", "Code Quality & Security Review", config)

    @staticmethod
    def _clean_text(value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    @classmethod
    def _top_level_test_names(cls, tests: str) -> list[str]:
        names: list[str] = []
        for line in tests.splitlines():
            stripped = line.strip()
            if stripped.startswith("def test_") and "(" in stripped:
                names.append(stripped.split("(", 1)[0].removeprefix("def ").strip())
        return names

    @classmethod
    def _generated_tests_block(cls, tests: object) -> str:
        tests_text = cls._clean_text(tests)
        if not tests_text:
            return "Generated tests:\n- none provided"

        test_lines = tests_text.splitlines()
        if len(test_lines) <= 20:
            return f"Generated tests:\n```python\n{tests_text}\n```"

        top_level_tests = cls._top_level_test_names(tests_text)
        tests_label = ", ".join(top_level_tests) if top_level_tests else "unknown"
        excerpt = "\n".join(test_lines[:14])
        return (
            "Generated tests:\n"
            f"- Total lines: {len(test_lines)}\n"
            f"- Top-level tests: {tests_label}\n"
            "- Use the validation summary as ground truth for suite validity and missing coverage.\n"
            "Representative excerpt:\n"
            "```python\n"
            f"{excerpt}\n"
            "```"
        )

    @classmethod
    def _build_user_message(
        cls,
        *,
        project_name: str,
        module_name: str,
        module_filename: str,
        code_public_api: str,
        code: str,
        tests: object,
        test_validation_summary: str,
        dependency_validation_summary: str,
        task_description: str,
    ) -> str:
        project_block = f"Project: {project_name}\n" if project_name else ""
        return f"""{project_block}Module name: {module_name}
Module file: {module_filename}
Public API contract:
{code_public_api}

Review this code:

```python
{code}
```

{cls._generated_tests_block(tests)}
Test validation summary:
{test_validation_summary}
Dependency validation summary:
{dependency_validation_summary}

Task context: {task_description}

Review constraints:
- Keep the review under 180 words.
- Report at most 3 distinct issues.
- Do not repeat the same issue or category with different wording.
- Prioritize correctness, API contract mismatches, validation failures, security, and dependency issues over generic style or docstring nits.
- If the validation summaries are clean and you see no material defect, return PASS and say "No material issues found."

Provide structured review with verdict and issues."""

    def run_with_input(self, agent_input: AgentInput) -> str:
        code = self.require_context_value(agent_input, "code")
        module_name = agent_input.context.get("module_name", "module")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        code_public_api = agent_input.context.get("code_public_api", "")
        tests = agent_input.context.get("tests", "")
        test_validation_summary = agent_input.context.get("test_validation_summary", "")
        dependency_validation_summary = agent_input.context.get("dependency_validation_summary", "")
        user_msg = self._build_user_message(
            project_name=agent_input.project_name,
            module_name=module_name,
            module_filename=module_filename,
            code_public_api=code_public_api,
            code=code,
            tests=tests,
            test_validation_summary=test_validation_summary,
            dependency_validation_summary=dependency_validation_summary,
            task_description=agent_input.task_description,
        )
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        code = context.get("code", "")
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        code_public_api = context.get("code_public_api", "")
        tests = context.get("tests", "")
        test_validation_summary = context.get("test_validation_summary", "")
        dependency_validation_summary = context.get("dependency_validation_summary", "")
        user_msg = self._build_user_message(
            project_name="",
            module_name=module_name,
            module_filename=module_filename,
            code_public_api=code_public_api,
            code=code,
            tests=tests,
            test_validation_summary=test_validation_summary,
            dependency_validation_summary=dependency_validation_summary,
            task_description=task_description,
        )
        return self.chat(SYSTEM_PROMPT, user_msg)
