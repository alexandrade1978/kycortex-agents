import re

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType


def _low_budget_code_section(max_tokens: object) -> str:
    if not isinstance(max_tokens, int) or max_tokens <= 0 or max_tokens > 1200:
        return ""
    return (
        f"Provider completion budget: {max_tokens} tokens.\n"
        "This is a tight completion budget. Compress more aggressively than usual: implement only the minimum contract-required surface, prefer one main facade plus the anchored request model, and omit optional response wrappers, validation-result dataclasses, internal audit-record dataclasses, long constant tables, and non-essential prose unless the task explicitly requires them.\n"
        "Prefer built-in containers for optional return details instead of extra named types when the public contract does not require those named types. Do not introduce any extra dataclass beyond the anchored request model unless the task explicitly requires it. Under this budget, keep the required CLI or demo path minimal but mandatory: preserve a working main() plus a literal if __name__ == \"__main__\": block before spending tokens on optional helper types or richer return models.\n"
        "If you must trade optional structure for required surfaces, keep the anchored facade, validate_request(...), handle_request(...), and the minimal CLI entrypoint, and collapse audit or scoring detail into the smallest valid implementation that still satisfies the task.\n"
        "Order the module so acceptance-critical surfaces appear first: define the request model, then ComplianceIntakeService.validate_request(...), then ComplianceIntakeService.handle_request(...), then a minimal main() and literal main guard. Under this budget, inline scoring and audit work inside handle_request(...) instead of spending lines on private helper methods placed ahead of the required public surface.\n\n"
    )


def _compact_task_constraints_block(task_description: str) -> str:
    if not isinstance(task_description, str) or not task_description.strip():
        return ""

    summary_source = task_description.split("Public contract anchor:", 1)[0]
    normalized = re.sub(r"\s+", " ", summary_source).strip()
    if not normalized:
        normalized = re.sub(r"\s+", " ", task_description).strip()
    if not normalized:
        return ""

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized)
        if sentence.strip()
    ]
    selected = sentences[:5] if sentences else [normalized]
    lines = ["Task constraints summary:"]
    lines.extend(f"- {sentence}" for sentence in selected)
    return "\n".join(lines)


def _budget_decomposition_block(brief: object) -> str:
    if not isinstance(brief, str) or not brief.strip():
        return ""
    return f"Budget decomposition brief:\n{brief}\n\n"

SYSTEM_PROMPT = """You are a Senior Python Engineer at KYCortex AI Software House.
You write clean, production-quality Python code.
Use accurate type hints throughout.
Add docstrings, logging, and explicit error handling when they materially improve correctness or the task explicitly needs them.
Follow PEP8. Write modular code with clear separation of concerns.
Task-specific scope and size limits override generic polish. When the task is line-constrained, prefer the smallest complete implementation over extra helper layers, repetitive docstrings, or optional abstractions.
When the task gives a hard line cap, plan the full module before writing and stay comfortably under that ceiling so imports, the main guard, and any required repairs still fit.
Leave visible headroom below the ceiling; if the draft is still within roughly 10 to 15 lines of the cap, compress it further before finalizing.
Do NOT include placeholder comments like # TODO without implementation.
Return only raw Python source code.
Do not include markdown fences, file trees, headings, or explanatory prose.
You are writing exactly one importable Python module.
The module must run as-is, keep its types internally consistent, and expose a coherent public API.
Do not invent extra files, package layouts, or persistence layers unless the task explicitly requires them.
Prefer in-memory state and simple standard-library containers unless the task explicitly requires durable persistence, SQL, or filesystem-backed storage.
Prefer the Python standard library only.
Do not add third-party dependencies or imports unless the task explicitly requires them and they are necessary to solve the task.
Before finalizing, mentally execute the module entrypoint and fix any obvious attribute, name, or type errors.
Write complete code only. Do not stop mid-function, mid-string, or mid-docstring.
If the architecture contains markdown, pseudo-code, or illustrative snippets, convert it into valid Python rather than copying it verbatim.
Treat the architecture as guidance for required behavior, not as a requirement to mirror every optional layer, extension point, or future enhancement.
For compact single-module service tasks, prefer one cohesive public service surface plus domain models over separate helper-only collaborator classes.
Do not split validation, scoring, audit logging, or batch handling into separate Logger, Scorer, Processor, Manager, or interface classes unless the task or validated public contract explicitly requires those public types.
If an architecture sketch names optional collaborators such as RiskScorer, AuditLogger, or BatchProcessor but the task only requires those behaviors, collapse them into methods on the main service or the smallest importable API instead of mirroring every helper.
Keep constructor signatures, helper function parameters, and internal call sites mutually consistent.
If you define a helper to accept a domain object, every caller must pass that domain object; if you need a scalar helper, define it that way explicitly.
If you model requests or records as dataclasses or other typed objects, access them consistently through attributes. Do not mix object-style APIs with dict membership tests or subscripting unless you explicitly convert them to mappings first.
If you define dataclasses or typed record models with defaults, keep every required non-default field before every defaulted field so the module imports cleanly. Never place a non-default dataclass field after a defaulted field.
Example: if AuditLog has required action and details fields plus a defaulted timestamp, declare action and details before timestamp = field(default_factory=...).
If the architecture or task description lists entity fields in a conflicting order, treat that list as descriptive only and reorder the actual dataclass fields so required fields still come first.
Example: even if the architecture says AuditLog(action, timestamp, details), implement AuditLog(action, details, timestamp=field(default_factory=...)).
If you use dataclasses.field(...) or field(default_factory=...) anywhere in the module, import field explicitly from dataclasses so the module imports cleanly.
Keep imports consistent with the names you reference. If you call datetime.datetime.now() or datetime.date.today(), import datetime. If you import a symbol such as from datetime import datetime, call datetime.now() instead of datetime.datetime.now(). Do not leave module-qualified references pointing at names you never imported.
Avoid placeholder demo logic that contradicts your own type hints or public API.
If the task includes validation, implement concrete reject conditions for clearly invalid input rather than returning a constant success placeholder.
If the task includes scoring or other numeric derivation, use a transparent deterministic formula and avoid hidden caps, clamps, or arbitrary thresholds unless the task explicitly requires them.
If a boolean or toggle-like field influences validation, scoring, or routing, read the field's actual truth value instead of treating mere key presence as a positive signal unless the task explicitly defines presence-only semantics.
If repair context suggests truncation or incomplete output, remove non-essential docstrings, comments, blank lines, and optional helper layers before dropping any required behavior.
When repair context includes failing pytest assertions from a valid test suite, treat those assertions as exact behavioral requirements for the module.
Make the smallest code change that makes every cited assertion pass, but do not stop at a nearby constant tweak or branch edit if the cited predicate would still fail afterward.
Preserve the documented public API while repairing behavior unless the validation summary explicitly says the API shape itself is wrong.
If repair context includes an existing pytest module, use its concrete fixtures, inputs, and assertions as the most specific behavioral contract available.
Treat existing tests and repair summaries as behavioral evidence only. Do not copy pytest test functions, bare assert statements, or test-only scaffolding into the implementation module.
If you are repairing a previously invalid or truncated file, rewrite the complete module from the top instead of continuing from a partial tail.
If the task requires a CLI or demo entrypoint, preserve or restore a minimal main() plus a literal if __name__ == "__main__": block during repair. Do not drop the entrypoint just to save lines or mirror a failing test snippet.
When a task-level public contract anchor is provided, treat it as the highest-priority public API contract unless the validation summary explicitly says that API shape is wrong. Preserve listed facade, model, method, and constructor-field names exactly and do not invent alternate aliases or competing entrypoints."""

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
        budget_decomposition_block = _budget_decomposition_block(
            agent_input.context.get("budget_decomposition_brief")
        )
        module_name = agent_input.context.get("module_name", f"{agent_input.task_id}_implementation")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        low_budget_section = _low_budget_code_section(agent_input.context.get("provider_max_tokens"))
        task_public_contract_anchor = agent_input.context.get("task_public_contract_anchor", "")
        public_contract_section = ""
        if isinstance(task_public_contract_anchor, str) and task_public_contract_anchor.strip():
            public_contract_section = f"Task-level public contract anchor:\n{task_public_contract_anchor}\n\n"
        task_block = f"Task: {agent_input.task_description}"
        if low_budget_section and isinstance(task_public_contract_anchor, str) and task_public_contract_anchor.strip():
            compact_task_block = _compact_task_constraints_block(agent_input.task_description)
            if compact_task_block:
                task_block = compact_task_block
        user_msg = f"""Project: {agent_input.project_name}
Goal: {agent_input.project_goal}
Target module: {module_filename}

    {low_budget_section}{public_contract_section}Architecture:
{architecture}

Existing code context:
{existing_code}

Existing tests context:
{existing_tests}

Previous validation summary:
{repair_validation_summary}

{budget_decomposition_block}If a budget decomposition brief is provided, treat it as the compact execution plan for this rewrite. Preserve the required public surface it names, follow its write order, and omit the optional structures it explicitly says to cut unless the task, anchor, or validation summary requires them.

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.
Use the existing tests context, when provided, as the most specific source of concrete inputs, edge cases, and expected outputs for the repair.
Treat that tests context as behavioral evidence only. Do not copy pytest test functions, bare assert statements, or test-only scaffolding into this module.

{task_block}

Write the complete Python code for this task as a single raw Python file.
The file will be saved as `{module_filename}` and imported as `{module_name}`.
Do not rely on any files other than this module unless the task explicitly requires that dependency.
Do not add third-party imports such as numpy or pandas unless the task explicitly requires them.
Prefer in-memory state and simple standard-library containers unless the task explicitly requires durable persistence, SQL, or filesystem-backed storage.
Respect the task's requested size budget exactly. If the task does not specify one, keep the module under 260 lines. When the task gives a hard line cap, stay comfortably under that ceiling instead of aiming for the exact limit. Prefer one small cohesive API over optional manager classes, wrappers, per-method docstrings, or verbose CLI plumbing when the task is compact.
For compact service tasks, keep validation, scoring, audit logging, and batch behavior on one main service surface or a very small set of top-level functions.
Do not split those behaviors into separate Logger, Scorer, Processor, Manager, or interface classes unless the task or validated public API explicitly requires those public collaborators.
If the architecture sketch mentions optional helper collaborators such as RiskScorer, AuditLogger, or BatchProcessor, collapse them into the smallest importable API instead of mirroring every helper layer.
If the draft is still within roughly 10 to 15 lines of the ceiling, compress it further by removing optional helper layers, repeated convenience wrappers, and non-essential docstrings before finalizing.
If the previous validation summary includes pytest failures, treat each listed failing assertion as an exact behavior contract for this module and update the implementation until those cited assertions would pass.
Do not stop at a nearby constant tweak, renamed helper, or signature change if the same listed assertion would still fail after that edit.
If a task-level public contract anchor is provided, treat it as higher priority than optional architecture wording and preserve every listed facade, model, method, and constructor field name exactly.
Do not replace anchored names with guessed aliases, shortened variants, or convenience batch wrappers that are not listed in the anchor.
If the architecture sketch drifts from the task-level public contract anchor, mentally repair that sketch and implement the anchored public surface instead.
If you define dataclasses or typed record models with defaults, keep every required field before any defaulted field so the module imports cleanly and does not fail at import time.
Example: if AuditLog has required action and details fields plus a defaulted timestamp, declare action and details before timestamp = field(default_factory=...).
If the architecture or task description lists entity fields in a conflicting order, treat that list as descriptive only and reorder the actual dataclass fields so required fields still come first.
Example: even if the architecture says AuditLog(action, timestamp, details), implement AuditLog(action, details, timestamp=field(default_factory=...)).
If you use dataclasses.field(...) or field(default_factory=...) anywhere in the module, import field explicitly from dataclasses so the module imports cleanly.
Keep imports consistent with how you reference names. If you call datetime.datetime.now() or datetime.date.today(), import datetime. If you import datetime directly with from datetime import datetime, call datetime.now() instead of datetime.datetime.now(). Do not leave module-qualified references pointing at names you never imported.
Before you finalize, verify this checklist against your own output:
- the file starts with valid imports or declarations and ends cleanly with no truncated block
- every opened string, bracket, parenthesis, and docstring is closed
- if the task is line-constrained, you stayed comfortably under the ceiling rather than using the full budget
- if the task is line-constrained, you left visible headroom below the ceiling; if the draft was still within roughly 10 to 15 lines of the cap, you compressed it further before finalizing
- if the previous file was syntax-invalid or truncated, you rewrote the full module from the top instead of appending a partial continuation
- if the previous validation mentions truncation or completion diagnostics, you reduced non-essential docstrings, comments, blank lines, and optional helpers so the whole module fits cleanly in one response
- you implemented only the required behavior from the architecture and skipped optional layers, future extension points, and extra persistence scaffolding that the task did not require
- if the task described a compact service module, you kept validation, scoring, audit logging, and batch behavior on one main service surface or the smallest importable API
- you did not invent separate Logger, Scorer, Processor, Manager, or interface classes unless the task or validated public API explicitly required those public types
- if the task did not explicitly require durable persistence, you kept service state in memory instead of adding sqlite or filesystem-backed storage
- if the task includes validation, your validator rejects at least one clearly invalid input shape instead of returning a constant success placeholder
- if the task includes numeric scoring, the formula is transparent and avoids hidden caps, clamps, or arbitrary thresholds unless the task explicitly requires them
- if boolean or toggle-like fields influence behavior, you used the field's truth value rather than mere key presence unless the contract explicitly defines presence-only semantics
- if you modeled requests or records as dataclasses or typed objects, you accessed them consistently through attributes instead of mixing in dict membership checks or subscripting
- if you used dataclasses or typed record models with defaults, every required field appears before any field with a default so the module imports cleanly
- if you used dataclasses.field(...) or field(default_factory=...) anywhere in the module, you imported field explicitly from dataclasses so the module imports cleanly
- every referenced module or symbol is imported consistently; if you call datetime.datetime.now() you imported datetime, and if you imported datetime directly you call datetime.now()
- if the task requires a CLI or demo entrypoint, you included it in this same module with a working main guard or equivalent entry function
- if the task requires a CLI or demo entrypoint, prefer a minimal `main()` plus a literal `if __name__ == "__main__":` block at the end of the file
- the file stays implementation code rather than turning into a pytest module, copied test function, or bare assertion snippet from the tests context
- every constructor call matches the constructor you defined
- every function call matches the parameter types you defined
- the CLI/demo path exercises real module functions without introducing a separate API shape"""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        architecture = context.get("architecture", "")
        existing_code = context.get("existing_code", "")
        existing_tests = context.get("existing_tests", "")
        repair_validation_summary = context.get("repair_validation_summary", "")
        budget_decomposition_block = _budget_decomposition_block(
            context.get("budget_decomposition_brief")
        )
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        low_budget_section = _low_budget_code_section(context.get("provider_max_tokens"))
        task_public_contract_anchor = context.get("task_public_contract_anchor", "")
        public_contract_section = ""
        if isinstance(task_public_contract_anchor, str) and task_public_contract_anchor.strip():
            public_contract_section = f"Task-level public contract anchor:\n{task_public_contract_anchor}\n\n"
        task_block = f"Task: {task_description}"
        if low_budget_section and isinstance(task_public_contract_anchor, str) and task_public_contract_anchor.strip():
            compact_task_block = _compact_task_constraints_block(task_description)
            if compact_task_block:
                task_block = compact_task_block
        user_msg = f"""Architecture:
{architecture}
Target module: {module_filename}

    {low_budget_section}{public_contract_section}Existing code context:
{existing_code}

Existing tests context:
{existing_tests}

    Previous validation summary:
    {repair_validation_summary}

{budget_decomposition_block}If a budget decomposition brief is provided, treat it as the compact execution plan for this rewrite. Preserve the required public surface it names, follow its write order, and omit the optional structures it explicitly says to cut unless the task, anchor, or validation summary requires them.

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.
Use the existing tests context, when provided, as the most specific source of concrete inputs, edge cases, and expected outputs for the repair.
Treat that tests context as behavioral evidence only. Do not copy pytest test functions, bare assert statements, or test-only scaffolding into this module.

{task_block}

Write the complete Python code for this task as a single raw Python file.
The file will be saved as `{module_filename}` and imported as `{module_name}`.
Do not add third-party imports such as numpy or pandas unless the task explicitly requires them.
Prefer in-memory state and simple standard-library containers unless the task explicitly requires durable persistence, SQL, or filesystem-backed storage.
Respect the task's requested size budget exactly. If the task does not specify one, keep the module under 260 lines. When the task gives a hard line cap, stay comfortably under that ceiling instead of aiming for the exact limit. Prefer one small cohesive API over optional manager classes, wrappers, per-method docstrings, or verbose CLI plumbing when the task is compact.
For compact service tasks, keep validation, scoring, audit logging, and batch behavior on one main service surface or a very small set of top-level functions.
Do not split those behaviors into separate Logger, Scorer, Processor, Manager, or interface classes unless the task or validated public API explicitly requires those public collaborators.
If the architecture sketch mentions optional helper collaborators such as RiskScorer, AuditLogger, or BatchProcessor, collapse them into the smallest importable API instead of mirroring every helper layer.
If the draft is still within roughly 10 to 15 lines of the ceiling, compress it further by removing optional helper layers, repeated convenience wrappers, and non-essential docstrings before finalizing.
If the previous validation summary includes pytest failures, treat each listed failing assertion as an exact behavior contract for this module and update the implementation until those cited assertions would pass.
Do not stop at a nearby constant tweak, renamed helper, or signature change if the same listed assertion would still fail after that edit.
If a task-level public contract anchor is provided, treat it as higher priority than optional architecture wording and preserve every listed facade, model, method, and constructor field name exactly.
Do not replace anchored names with guessed aliases, shortened variants, or convenience batch wrappers that are not listed in the anchor.
If the architecture sketch drifts from the task-level public contract anchor, mentally repair that sketch and implement the anchored public surface instead.
If you define dataclasses or typed record models with defaults, keep every required field before any defaulted field so the module imports cleanly and does not fail at import time.
Example: if AuditLog has required action and details fields plus a defaulted timestamp, declare action and details before timestamp = field(default_factory=...).
If the architecture or task description lists entity fields in a conflicting order, treat that list as descriptive only and reorder the actual dataclass fields so required fields still come first.
Example: even if the architecture says AuditLog(action, timestamp, details), implement AuditLog(action, details, timestamp=field(default_factory=...)).
If you use dataclasses.field(...) or field(default_factory=...) anywhere in the module, import field explicitly from dataclasses so the module imports cleanly.
Keep imports consistent with how you reference names. If you call datetime.datetime.now() or datetime.date.today(), import datetime. If you import datetime directly with from datetime import datetime, call datetime.now() instead of datetime.datetime.now(). Do not leave module-qualified references pointing at names you never imported.
Before you finalize, verify this checklist against your own output:
- the file starts with valid imports or declarations and ends cleanly with no truncated block
- every opened string, bracket, parenthesis, and docstring is closed
- if the task is line-constrained, you stayed comfortably under the ceiling rather than using the full budget
- if the task is line-constrained, you left visible headroom below the ceiling; if the draft was still within roughly 10 to 15 lines of the cap, you compressed it further before finalizing
- if the previous file was syntax-invalid or truncated, you rewrote the full module from the top instead of appending a partial continuation
- if the previous validation mentions truncation or completion diagnostics, you reduced non-essential docstrings, comments, blank lines, and optional helpers so the whole module fits cleanly in one response
- you implemented only the required behavior from the architecture and skipped optional layers, future extension points, and extra persistence scaffolding that the task did not require
- if the task described a compact service module, you kept validation, scoring, audit logging, and batch behavior on one main service surface or the smallest importable API
- you did not invent separate Logger, Scorer, Processor, Manager, or interface classes unless the task or validated public API explicitly required those public types
- if the task did not explicitly require durable persistence, you kept service state in memory instead of adding sqlite or filesystem-backed storage
- if the task includes validation, your validator rejects at least one clearly invalid input shape instead of returning a constant success placeholder
- if the task includes numeric scoring, the formula is transparent and avoids hidden caps, clamps, or arbitrary thresholds unless the task explicitly requires them
- if boolean or toggle-like fields influence behavior, you used the field's truth value rather than mere key presence unless the contract explicitly defines presence-only semantics
- if you modeled requests or records as dataclasses or typed objects, you accessed them consistently through attributes instead of mixing in dict membership checks or subscripting
- if you used dataclasses or typed record models with defaults, every required field appears before any field with a default so the module imports cleanly
- if you used dataclasses.field(...) or field(default_factory=...) anywhere in the module, you imported field explicitly from dataclasses so the module imports cleanly
- every referenced module or symbol is imported consistently; if you call datetime.datetime.now() you imported datetime, and if you imported datetime directly you call datetime.now()
- if the task requires a CLI or demo entrypoint, you included it in this same module with a working main guard or equivalent entry function
- if the task requires a CLI or demo entrypoint, prefer a minimal `main()` plus a literal `if __name__ == "__main__":` block at the end of the file
- the file stays implementation code rather than turning into a pytest module, copied test function, or bare assertion snippet from the tests context
- every constructor call matches the constructor you defined
- every function call matches the parameter types you defined
- the CLI/demo path exercises real module functions without introducing a separate API shape"""
        return self.chat(SYSTEM_PROMPT, user_msg)
