from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType

DEFAULT_CONSTRAINTS = "Python 3.10+, production-ready dependencies, licensing suitable for open-source or commercial distribution"


def _adaptive_prompt_mode(context: object) -> str | None:
    if not isinstance(context, dict):
        return None
    policy = context.get("adaptive_prompt_policy")
    if not isinstance(policy, dict):
        return None
    mode = policy.get("mode")
    if isinstance(mode, str) and mode.strip():
        return mode.strip().lower()
    return None


def _low_budget_architecture_section(max_tokens: object, prompt_mode: object = None) -> str:
    resolved_mode = prompt_mode.strip().lower() if isinstance(prompt_mode, str) else None
    if resolved_mode is not None and resolved_mode != "compact":
        return ""
    if resolved_mode is None and (
        not isinstance(max_tokens, int) or max_tokens <= 0 or max_tokens > 1200
    ):
        return ""
    budget_line = (
        f"Provider completion budget: {max_tokens} tokens.\n"
        if isinstance(max_tokens, int) and max_tokens > 0
        else "Provider completion budget: adaptive compact mode.\n"
    )
    return (
        budget_line +
        "This is a tight completion budget. Keep the architecture under roughly 200 words, list only the minimum required public surface, and omit optional helper types, response wrappers, validation-result types, internal audit-record types, future extensions, and long operational-risk prose unless the task explicitly requires them.\n"
        "Do not introduce extra named result, scoring, or audit dataclasses unless the public contract explicitly requires them. Under this budget, prefer the smallest facade-centered shape that still leaves room for the required CLI entrypoint in the eventual implementation.\n"
        "Prefer one facade, one request model, and only the smallest supporting surface needed for correct code generation under this budget.\n"
        "Return a compact bullet list only. Do not use markdown tables, section headings, or long rationale under this budget.\n\n"
    )


def _architecture_request_block(context: object) -> str:
    repair_context = context if isinstance(context, dict) else {}
    if repair_context.get("decomposition_mode") == "budget_compaction_planner":
        return """Provide a compact budget decomposition brief for the next repair step.
    Return 4 to 8 short bullets only.
    Return plain `- ` bullets only. Do not add headings, bold section labels, or markdown emphasis.
    Cover only the minimum public surface or pytest surface to preserve, the required behaviors or scenarios that cannot be dropped, the optional structures or coverage to omit, and the write order that should appear first to avoid another oversized completion.
    If the failure evidence mentions completion-limit pressure or likely truncation, make the size target materially smaller than the failed output, usually at least 25 to 35 percent below the reported line count unless the task already has a stricter hard cap.
    Prefer the smallest importable API that still preserves the required facade, request model, validator, handler, and any mandatory CLI entrypoint.
    Do not include file trees, package layouts, headings, markdown tables, or long rationale."""
    return """Provide a detailed architecture document.
    Respect the task scope exactly: if the requested deliverable is a single Python module, the architecture must describe a single-module design.
    If a target module is provided, document only that one file and do not include a package tree.
    Prefer one cohesive public service surface plus domain models over separate helper interfaces for scoring, logging, or batch processing.
    Do not introduce standalone RiskScorer, AuditLogger, BatchProcessor, Manager, or Processor collaborators unless the task explicitly requires those public types.
    If you describe typed entities or dataclasses, list required fields before defaulted fields and mark defaulted fields explicitly so the document does not imply an invalid constructor order.
    If a task-level public contract anchor is provided, preserve every listed facade, model, method, and constructor field name exactly.
    Do not rename anchored symbols, invent aliases, or introduce alternate public entrypoints that compete with the anchor.
    If the broader task wording and the task-level public contract anchor pull in different directions, keep the anchor exact and adjust the rest of the architecture around it."""

SYSTEM_PROMPT = """You are a Senior Software Architect at KYCortex AI Software House.
Your job is to design modular, scalable Python project architectures.
Output structured architecture documents including: module breakdown, file structure,
interfaces, data flows, technology choices and rationale.
Always think about extensibility, testability and open-source best practices.
If the task asks for a single Python module or single file, keep the architecture scoped to that single module and do not invent a multi-file package layout.
When a target module filename is provided, describe only that file and avoid directory trees.
For compact single-module service tasks, prefer one cohesive public service surface plus domain models over separate helper-only collaborators or interface sections.
Do not invent standalone RiskScorer, AuditLogger, BatchProcessor, Manager, Processor, or similar public helper types unless the task explicitly requires those public surfaces.
When describing typed entities or dataclasses, list required fields before defaulted fields and call out defaults explicitly so downstream code generation does not infer an invalid constructor order.
Prefer @dataclass for data containers and typed collections such as list[SpecificType] over generic dicts. Include type annotations on all public methods so test generation can match return shapes precisely.
Example: describe AuditLog as action, details, timestamp(default now) rather than action, timestamp, details.
When a task-level public contract anchor is provided, treat it as the exact public API ground truth. Preserve listed facade, model, method, and constructor-field names exactly and do not invent alternate aliases or competing public entrypoints."""

class ArchitectAgent(BaseAgent):
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "architecture"

    def __init__(self, config: KYCortexConfig):
        super().__init__("Architect", "Software Architecture Design", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        constraints = ", ".join(agent_input.constraints) if agent_input.constraints else DEFAULT_CONSTRAINTS
        planned_module_filename = agent_input.context.get("planned_module_filename", "")
        low_budget_section = _low_budget_architecture_section(
            agent_input.context.get("provider_max_tokens"),
            prompt_mode=_adaptive_prompt_mode(agent_input.context),
        )
        task_public_contract_anchor = agent_input.context.get("task_public_contract_anchor", "")
        repair_context = agent_input.context.get("repair_context", {})
        public_contract_section = ""
        if isinstance(task_public_contract_anchor, str) and task_public_contract_anchor.strip():
            public_contract_section = f"Task-level public contract anchor:\n{task_public_contract_anchor}\n\n"
        request_block = _architecture_request_block(repair_context)
        user_msg = f"""Project Name: {agent_input.project_name}
Project Goal: {agent_input.project_goal}
Constraints: {constraints}
    Target module: {planned_module_filename or 'Not specified'}
{low_budget_section}{public_contract_section}Task: {agent_input.task_description}

{request_block}"""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        goal = context.get("goal", "")
        constraints = context.get("constraints", DEFAULT_CONSTRAINTS)
        planned_module_filename = context.get("planned_module_filename", "")
        low_budget_section = _low_budget_architecture_section(
            context.get("provider_max_tokens"),
            prompt_mode=_adaptive_prompt_mode(context),
        )
        task_public_contract_anchor = context.get("task_public_contract_anchor", "")
        repair_context = context.get("repair_context", {})
        public_contract_section = ""
        if isinstance(task_public_contract_anchor, str) and task_public_contract_anchor.strip():
            public_contract_section = f"Task-level public contract anchor:\n{task_public_contract_anchor}\n\n"
        request_block = _architecture_request_block(repair_context)
        user_msg = f"""Project Goal: {goal}
Constraints: {constraints}
    Target module: {planned_module_filename or 'Not specified'}
{low_budget_section}{public_contract_section}Task: {task_description}

{request_block}"""
        return self.chat(SYSTEM_PROMPT, user_msg)
