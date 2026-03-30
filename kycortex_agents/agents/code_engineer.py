from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType

SYSTEM_PROMPT = """You are a Senior Python Engineer at KYCortex AI Software House.
You write clean, production-quality Python code.
Use accurate type hints throughout.
Add docstrings, logging, and explicit error handling when they materially improve correctness or the task explicitly needs them.
Follow PEP8. Write modular code with clear separation of concerns.
Task-specific scope and size limits override generic polish. When the task is line-constrained, prefer the smallest complete implementation over extra helper layers, repetitive docstrings, or optional abstractions.
When the task gives a hard line cap, plan the full module before writing and stay comfortably under that ceiling so imports, the main guard, and any required repairs still fit.
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
Treat the architecture as guidance for required behavior, not as a requirement to mirror every optional layer, extension point, or future enhancement.
Keep constructor signatures, helper function parameters, and internal call sites mutually consistent.
If you define a helper to accept a domain object, every caller must pass that domain object; if you need a scalar helper, define it that way explicitly.
Avoid placeholder demo logic that contradicts your own type hints or public API.
If the task includes validation, implement concrete reject conditions for clearly invalid input rather than returning a constant success placeholder.
If the task includes scoring or other numeric derivation, use a transparent deterministic formula and avoid hidden caps, clamps, or arbitrary thresholds unless the task explicitly requires them.
If repair context suggests truncation or incomplete output, remove non-essential docstrings, comments, blank lines, and optional helper layers before dropping any required behavior.
When repair context includes failing pytest assertions from a valid test suite, treat those assertions as exact behavioral requirements for the module.
Make the smallest code change that makes every cited assertion pass, but do not stop at a nearby constant tweak or branch edit if the cited predicate would still fail afterward.
Preserve the documented public API while repairing behavior unless the validation summary explicitly says the API shape itself is wrong.
If repair context includes an existing pytest module, use its concrete fixtures, inputs, and assertions as the most specific behavioral contract available.
If you are repairing a previously invalid or truncated file, rewrite the complete module from the top instead of continuing from a partial tail."""

class CodeEngineerAgent(BaseAgent):
    required_context_keys = ("architecture",)
    output_artifact_type = ArtifactType.CODE
    output_artifact_name = "implementation"

    def __init__(self, config: KYCortexConfig):
        super().__init__("CodeEngineer", "Python Software Development", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        architecture = self.require_context_value(agent_input, "architecture")
        existing_code = agent_input.context.get("existing_code", "")
        existing_tests = agent_input.context.get("existing_tests", "")
        repair_validation_summary = agent_input.context.get("repair_validation_summary", "")
        module_name = agent_input.context.get("module_name", f"{agent_input.task_id}_implementation")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        user_msg = f"""Project: {agent_input.project_name}
Goal: {agent_input.project_goal}
Target module: {module_filename}

Architecture:
{architecture}

Existing code context:
{existing_code}

Existing tests context:
{existing_tests}

Previous validation summary:
{repair_validation_summary}

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.
Use the existing tests context, when provided, as the most specific source of concrete inputs, edge cases, and expected outputs for the repair.

Task: {agent_input.task_description}

Write the complete Python code for this task as a single raw Python file.
The file will be saved as `{module_filename}` and imported as `{module_name}`.
Do not rely on any files other than this module unless the task explicitly requires that dependency.
Do not add third-party imports such as numpy or pandas unless the task explicitly requires them.
Respect the task's requested size budget exactly. If the task does not specify one, keep the module under 260 lines. When the task gives a hard line cap, stay comfortably under that ceiling instead of aiming for the exact limit. Prefer one small cohesive API over optional manager classes, wrappers, per-method docstrings, or verbose CLI plumbing when the task is compact.
If the previous validation summary includes pytest failures, treat each listed failing assertion as an exact behavior contract for this module and update the implementation until those cited assertions would pass.
Do not stop at a nearby constant tweak, renamed helper, or signature change if the same listed assertion would still fail after that edit.
Before you finalize, verify this checklist against your own output:
- the file starts with valid imports or declarations and ends cleanly with no truncated block
- every opened string, bracket, parenthesis, and docstring is closed
- if the task is line-constrained, you stayed comfortably under the ceiling rather than using the full budget
- if the previous file was syntax-invalid or truncated, you rewrote the full module from the top instead of appending a partial continuation
- if the previous validation mentions truncation or completion diagnostics, you reduced non-essential docstrings, comments, blank lines, and optional helpers so the whole module fits cleanly in one response
- you implemented only the required behavior from the architecture and skipped optional layers, future extension points, and extra persistence scaffolding that the task did not require
- if the task includes validation, your validator rejects at least one clearly invalid input shape instead of returning a constant success placeholder
- if the task includes numeric scoring, the formula is transparent and avoids hidden caps, clamps, or arbitrary thresholds unless the task explicitly requires them
- if the task requires a CLI or demo entrypoint, you included it in this same module with a working main guard or equivalent entry function
- if the task requires a CLI or demo entrypoint, prefer a minimal `main()` plus a literal `if __name__ == "__main__":` block at the end of the file
- every constructor call matches the constructor you defined
- every function call matches the parameter types you defined
- the CLI/demo path exercises real module functions without introducing a separate API shape"""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        architecture = context.get("architecture", "")
        existing_code = context.get("existing_code", "")
        existing_tests = context.get("existing_tests", "")
        repair_validation_summary = context.get("repair_validation_summary", "")
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        user_msg = f"""Architecture:
{architecture}
Target module: {module_filename}

Existing code context:
{existing_code}

Existing tests context:
{existing_tests}

    Previous validation summary:
    {repair_validation_summary}

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.
Use the existing tests context, when provided, as the most specific source of concrete inputs, edge cases, and expected outputs for the repair.

Task: {task_description}

Write the complete Python code for this task as a single raw Python file.
The file will be saved as `{module_filename}` and imported as `{module_name}`.
Do not add third-party imports such as numpy or pandas unless the task explicitly requires them.
Respect the task's requested size budget exactly. If the task does not specify one, keep the module under 260 lines. When the task gives a hard line cap, stay comfortably under that ceiling instead of aiming for the exact limit. Prefer one small cohesive API over optional manager classes, wrappers, per-method docstrings, or verbose CLI plumbing when the task is compact.
If the previous validation summary includes pytest failures, treat each listed failing assertion as an exact behavior contract for this module and update the implementation until those cited assertions would pass.
Do not stop at a nearby constant tweak, renamed helper, or signature change if the same listed assertion would still fail after that edit.
Before you finalize, verify this checklist against your own output:
- the file starts with valid imports or declarations and ends cleanly with no truncated block
- every opened string, bracket, parenthesis, and docstring is closed
- if the task is line-constrained, you stayed comfortably under the ceiling rather than using the full budget
- if the previous file was syntax-invalid or truncated, you rewrote the full module from the top instead of appending a partial continuation
- if the previous validation mentions truncation or completion diagnostics, you reduced non-essential docstrings, comments, blank lines, and optional helpers so the whole module fits cleanly in one response
- you implemented only the required behavior from the architecture and skipped optional layers, future extension points, and extra persistence scaffolding that the task did not require
- if the task includes validation, your validator rejects at least one clearly invalid input shape instead of returning a constant success placeholder
- if the task includes numeric scoring, the formula is transparent and avoids hidden caps, clamps, or arbitrary thresholds unless the task explicitly requires them
- if the task requires a CLI or demo entrypoint, you included it in this same module with a working main guard or equivalent entry function
- if the task requires a CLI or demo entrypoint, prefer a minimal `main()` plus a literal `if __name__ == "__main__":` block at the end of the file
- every constructor call matches the constructor you defined
- every function call matches the parameter types you defined
- the CLI/demo path exercises real module functions without introducing a separate API shape"""
        return self.chat(SYSTEM_PROMPT, user_msg)
