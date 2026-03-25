from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType

SYSTEM_PROMPT = """You are a Senior Python Engineer at KYCortex AI Software House.
You write clean, well-documented, production-quality Python code.
Always include: type hints, docstrings, error handling, logging.
Follow PEP8. Write modular code with clear separation of concerns.
Do NOT include placeholder comments like # TODO without implementation.
Return only raw Python source code.
Do not include markdown fences, file trees, headings, or explanatory prose.
You are writing exactly one importable Python module.
The module must run as-is, keep its types internally consistent, and expose a coherent public API.
Do not invent extra files, package layouts, or persistence layers unless the task explicitly requires them.
Prefer the Python standard library only.
Do not add third-party dependencies or imports unless the task explicitly requires them and they are necessary to solve the task.
Before finalizing, mentally execute the module entrypoint and fix any obvious attribute, name, or type errors.
Write complete code only. Do not stop mid-function, mid-string, or mid-docstring.
If the architecture contains markdown, pseudo-code, or illustrative snippets, convert it into valid Python rather than copying it verbatim.
Keep constructor signatures, helper function parameters, and internal call sites mutually consistent.
If you define a helper to accept a domain object, every caller must pass that domain object; if you need a scalar helper, define it that way explicitly.
Avoid placeholder demo logic that contradicts your own type hints or public API."""

class CodeEngineerAgent(BaseAgent):
    required_context_keys = ("architecture",)
    output_artifact_type = ArtifactType.CODE
    output_artifact_name = "implementation"

    def __init__(self, config: KYCortexConfig):
        super().__init__("CodeEngineer", "Python Software Development", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        architecture = self.require_context_value(agent_input, "architecture")
        existing_code = agent_input.context.get("existing_code", "")
        module_name = agent_input.context.get("module_name", f"{agent_input.task_id}_implementation")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        user_msg = f"""Project: {agent_input.project_name}
Goal: {agent_input.project_goal}
Target module: {module_filename}

Architecture:
{architecture}

Existing code context:
{existing_code}

Task: {agent_input.task_description}

Write the complete Python code for this task as a single raw Python file.
The file will be saved as `{module_filename}` and imported as `{module_name}`.
Do not rely on any files other than this module unless the task explicitly requires that dependency.
Do not add third-party imports such as numpy or pandas unless the task explicitly requires them.
Keep the module under 260 lines.
Before you finalize, verify this checklist against your own output:
- the file starts with valid imports or declarations and ends cleanly with no truncated block
- every opened string, bracket, parenthesis, and docstring is closed
- every constructor call matches the constructor you defined
- every function call matches the parameter types you defined
- the CLI/demo path exercises real module functions without introducing a separate API shape"""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        architecture = context.get("architecture", "")
        existing_code = context.get("existing_code", "")
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        user_msg = f"""Architecture:
{architecture}
Target module: {module_filename}

Existing code context:
{existing_code}

Task: {task_description}

Write the complete Python code for this task as a single raw Python file.
The file will be saved as `{module_filename}` and imported as `{module_name}`.
Do not add third-party imports such as numpy or pandas unless the task explicitly requires them.
Keep the module under 260 lines.
Before you finalize, verify this checklist against your own output:
- the file starts with valid imports or declarations and ends cleanly with no truncated block
- every opened string, bracket, parenthesis, and docstring is closed
- every constructor call matches the constructor you defined
- every function call matches the parameter types you defined
- the CLI/demo path exercises real module functions without introducing a separate API shape"""
        return self.chat(SYSTEM_PROMPT, user_msg)
