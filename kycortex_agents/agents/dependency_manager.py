import re

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactRecord, ArtifactType

NO_EXTERNAL_DEPENDENCIES = "# No external runtime dependencies"
_UNSAFE_REQUIREMENT_PREFIXES = (
    "-e ",
    "--editable ",
    "-r ",
    "--requirement ",
    "-c ",
    "--constraint ",
    "-f ",
    "--find-links ",
    "--index-url ",
    "--extra-index-url ",
    "--trusted-host ",
    "--no-binary ",
    "--only-binary ",
)
_UNSAFE_DIRECT_REFERENCE_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?\s*@\s*)?(?:git\+|hg\+|svn\+|bzr\+|https?://|file://|\./|\.\./|/)",
    flags=re.IGNORECASE,
)

SYSTEM_PROMPT = """You are a Python Dependency and Packaging Specialist at KYCortex AI Software House.
Your job is to infer the minimal runtime dependency manifest for the generated Python project.
Return only the plain text content of a requirements.txt file.
List one dependency specifier per line.
Prefer the smallest viable dependency set.
Do not include standard library modules.
Do not use editable installs, local paths, direct URLs, VCS references, or pip installer directives.
If no third-party runtime dependencies are required, return exactly: # No external runtime dependencies"""


def normalize_requirement_line(raw_line: str) -> str:
    line = raw_line.strip()
    if line.startswith(("- `", "* `")) and line.endswith("`"):
        return line[3:-1].strip()
    if line.startswith(("- ", "* ")):
        return line[2:].strip()
    return line


def is_provenance_unsafe_requirement(line: str) -> bool:
    normalized_line = normalize_requirement_line(line)
    if not normalized_line or normalized_line.startswith("#"):
        return False
    lowered_line = normalized_line.lower()
    if lowered_line.startswith(_UNSAFE_REQUIREMENT_PREFIXES):
        return True
    return bool(_UNSAFE_DIRECT_REFERENCE_PATTERN.match(normalized_line))


def extract_requirement_name(line: str) -> str:
    normalized_line = normalize_requirement_line(line)
    if not normalized_line or normalized_line.startswith("#"):
        return ""
    editable_prefixes = ("-e ", "--editable ")
    lowered_line = normalized_line.lower()
    if lowered_line.startswith(editable_prefixes):
        normalized_line = normalized_line.split(None, 1)[1].strip() if " " in normalized_line else ""
    direct_reference_match = re.match(
        r"^([A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?)\s*@\s+",
        normalized_line,
        flags=re.IGNORECASE,
    )
    if direct_reference_match is not None:
        return direct_reference_match.group(1)
    if is_provenance_unsafe_requirement(normalized_line):
        return ""
    return re.split(r"\s*(?:==|>=|<=|~=|!=|>|<)", normalized_line, maxsplit=1)[0].strip()


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
Do not use editable installs, local paths, direct URLs, VCS references, or pip installer directives.
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
Do not use editable installs, local paths, direct URLs, VCS references, or pip installer directives.
If the module has no external runtime dependencies, return exactly `# No external runtime dependencies`."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def _normalize_requirements(self, raw_requirements: str) -> str:
        if not raw_requirements.strip():
            return NO_EXTERNAL_DEPENDENCIES

        code_blocks = re.findall(r"```(?:[A-Za-z0-9_+.-]+)?\n(.*?)```", raw_requirements, flags=re.DOTALL)
        candidate_text = "\n".join(block.strip() for block in code_blocks if block.strip()) or raw_requirements

        requirement_lines: list[str] = []
        for raw_line in candidate_text.splitlines():
            line = normalize_requirement_line(raw_line)
            if not line:
                continue
            if line.startswith("#") and "external runtime dependencies" in line.lower():
                return NO_EXTERNAL_DEPENDENCIES
            if self._looks_like_requirement(line) or self._looks_like_provenance_unsafe_requirement(line):
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

    def _looks_like_provenance_unsafe_requirement(self, line: str) -> bool:
        return is_provenance_unsafe_requirement(line)