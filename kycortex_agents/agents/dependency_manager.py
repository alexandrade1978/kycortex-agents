import re

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactRecord, ArtifactType

NO_EXTERNAL_DEPENDENCIES = "# No external runtime dependencies"

SYSTEM_PROMPT = """You are a Python Dependency and Packaging Specialist at KYCortex AI Software House.
Your job is to infer the minimal runtime dependency manifest for the generated Python project.
Return only the plain text content of a requirements.txt file.
List one dependency specifier per line.
Prefer the smallest viable dependency set.
Do not include standard library modules.
If no third-party runtime dependencies are required, return exactly: # No external runtime dependencies"""


class DependencyManagerAgent(BaseAgent):
    required_context_keys = ("code",)
    output_artifact_type = ArtifactType.CONFIG
    output_artifact_name = "requirements"

    def __init__(self, config: KYCortexConfig):
        super().__init__("DependencyManager", "Dependency & Packaging", config)

    def after_execute(self, agent_input: AgentInput, output: AgentOutput) -> AgentOutput:
        normalized_requirements = self._normalize_requirements(output.raw_content)
        output.raw_content = normalized_requirements
        output.summary = normalized_requirements.splitlines()[0].strip()[:120]
        for artifact in output.artifacts:
            if artifact.path == "artifacts/requirements.txt":
                artifact.content = normalized_requirements
        return super().after_execute(agent_input, output)

    def run_with_input(self, agent_input: AgentInput) -> AgentOutput:
        code = self.require_context_value(agent_input, "code")
        module_name = agent_input.context.get("module_name", "module")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        code_summary = agent_input.context.get("code_summary", "")
        code_public_api = agent_input.context.get("code_public_api", "")
        user_msg = f"""Project: {agent_input.project_name}
Goal: {agent_input.project_goal}
Module: {module_filename}
Code summary: {code_summary}
Public API contract:
{code_public_api}

Generated code:
```python
{code}
```

Task: {agent_input.task_description}

Infer the minimal runtime requirements.txt for this generated module.
Do not include Python itself.
Do not include development-only tools such as pytest unless the task explicitly asks for them.
Exclude standard library imports.
If the module has no external runtime dependencies, return exactly `# No external runtime dependencies`."""
        raw_requirements = self.chat(SYSTEM_PROMPT, user_msg).strip()
        normalized_requirements = self._normalize_requirements(raw_requirements)
        summary = normalized_requirements.splitlines()[0].strip()[:120]
        return AgentOutput(
            summary=summary,
            raw_content=normalized_requirements,
            artifacts=[
                ArtifactRecord(
                    name=f"{agent_input.task_id}_requirements",
                    artifact_type=ArtifactType.CONFIG,
                    path="artifacts/requirements.txt",
                    content=normalized_requirements,
                    metadata={
                        "agent_name": self.name,
                        "task_id": agent_input.task_id,
                        "project_name": agent_input.project_name,
                    },
                )
            ],
        )

    def run(self, task_description: str, context: dict) -> str:
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        code_summary = context.get("code_summary", "")
        code_public_api = context.get("code_public_api", "")
        code = context.get("code", "")
        user_msg = f"""Module: {module_filename}
Code summary: {code_summary}
Public API contract:
{code_public_api}

Generated code:
```python
{code}
```

Task: {task_description}

Infer the minimal runtime requirements.txt for this generated module.
Do not include Python itself.
Do not include development-only tools such as pytest unless the task explicitly asks for them.
Exclude standard library imports.
If the module has no external runtime dependencies, return exactly `# No external runtime dependencies`."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def _normalize_requirements(self, raw_requirements: str) -> str:
        if not raw_requirements.strip():
            return NO_EXTERNAL_DEPENDENCIES

        code_blocks = re.findall(r"```(?:[A-Za-z0-9_+.-]+)?\n(.*?)```", raw_requirements, flags=re.DOTALL)
        candidate_text = "\n".join(block.strip() for block in code_blocks if block.strip()) or raw_requirements

        requirement_lines: list[str] = []
        for raw_line in candidate_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#") and "external runtime dependencies" in line.lower():
                return NO_EXTERNAL_DEPENDENCIES
            if line.startswith(("- `", "* `")) and line.endswith("`"):
                line = line[3:-1].strip()
            elif line.startswith(("- ", "* ")):
                line = line[2:].strip()
            if self._looks_like_requirement(line):
                requirement_lines.append(line)

        if requirement_lines:
            unique_lines: list[str] = []
            for line in requirement_lines:
                if line not in unique_lines:
                    unique_lines.append(line)
            return "\n".join(unique_lines)

        if NO_EXTERNAL_DEPENDENCIES in raw_requirements:
            return NO_EXTERNAL_DEPENDENCIES
        return NO_EXTERNAL_DEPENDENCIES

    def _looks_like_requirement(self, line: str) -> bool:
        if line.lower().startswith(("import ", "from ", "therefore", "however", "after analyzing", "the only ")):
            return False
        if " " in line and not any(op in line for op in ("==", ">=", "<=", "~=", "!=", ">", "<", "[")):
            return False
        return bool(re.match(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?(?:\s*(?:==|>=|<=|~=|!=|>|<)\s*[A-Za-z0-9*_.+-]+)?$", line))