"""Task-constraint helpers used by the Orchestrator facade."""

from __future__ import annotations

import re
from typing import Any, Optional

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.memory.project_state import Task
from kycortex_agents.types import FailureCategory


_LINE_BUDGET_PATTERNS = (
    re.compile(r"\bunder\s+(\d+)\s+lines?\b"),
    re.compile(r"\bwithin\s+(\d+)\s+lines?\b"),
    re.compile(r"\bat\s+most\s+(\d+)\s+lines?\b"),
    re.compile(r"\bno\s+more\s+than\s+(\d+)\s+lines?\b"),
)
_EXACT_TEST_COUNT_PATTERN = re.compile(r"\bexactly\s+(\d+)\s+top-level\s+test\s+functions?\b")
_MAX_TEST_COUNT_PATTERN = re.compile(r"\bat\s+most\s+(\d+)\s+top-level\s+test\s+functions?\b")
_FIXTURE_BUDGET_PATTERN = re.compile(r"\bat\s+most\s+(\d+)\s+fixtures?\b")


def task_line_budget(task: Optional[Task]) -> Optional[int]:
    if task is None or not isinstance(task.description, str):
        return None
    description = task.description.lower()
    for pattern in _LINE_BUDGET_PATTERNS:
        match = pattern.search(description)
        if match is None:
            continue
        return int(match.group(1))
    return None


def task_requires_cli_entrypoint(task: Optional[Task]) -> bool:
    if task is None or not isinstance(task.description, str):
        return False
    description = task.description.lower()
    return any(keyword in description for keyword in ("cli", "entrypoint", "__main__", "command-line"))


def parse_task_public_contract_surface(surface: str) -> tuple[Optional[str], str, list[str]]:
    normalized_surface = surface.strip()
    match = re.match(
        r"^(?:(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\.)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\((?P<args>[^)]*)\)",
        normalized_surface,
    )
    if not match:
        return None, normalized_surface, []

    args_text = match.group("args").strip()
    args: list[str] = []
    if args_text:
        for part in args_text.split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            cleaned = cleaned.split("=", 1)[0].strip()
            cleaned = cleaned.split(":", 1)[0].strip()
            cleaned = cleaned.lstrip("*")
            if cleaned and cleaned not in {"/", "*"}:
                args.append(cleaned)
    return match.group("owner"), match.group("name"), args


def task_public_contract_anchor(task_description: str) -> str:
    if not isinstance(task_description, str) or not task_description.strip():
        return ""

    lines = [line.rstrip() for line in task_description.splitlines()]
    collecting = False
    anchor_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not collecting:
            if stripped == "Public contract anchor:":
                collecting = True
            continue
        if not stripped:
            break
        if stripped.startswith("- "):
            anchor_lines.append(stripped)
            continue
        if line.startswith((" ", "\t")):
            anchor_lines.append(line.rstrip())
            continue
        break
    return "\n".join(anchor_lines)


def task_public_contract_preflight(
    task: Optional[Task],
    code_analysis: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if task is None or not code_analysis.get("syntax_ok", True):
        return None

    anchor = task_public_contract_anchor(task.description)
    if not anchor:
        return None

    class_map = code_analysis.get("classes") or {}
    function_map = {
        item["name"]: item
        for item in code_analysis.get("functions") or []
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    issues: list[str] = []
    public_facade = ""
    primary_request_model = ""
    required_surfaces: list[str] = []

    for line in anchor.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue

        label, separator, surface = stripped[2:].partition(":")
        if not separator:
            continue

        normalized_label = label.strip().lower()
        normalized_surface = surface.strip()
        if not normalized_surface:
            continue

        if normalized_label == "public facade":
            public_facade = normalized_surface
            if normalized_surface not in class_map:
                issues.append(f"missing public facade {normalized_surface}")
            continue

        if normalized_label == "primary request model":
            primary_request_model = normalized_surface
            _, model_name, expected_params = parse_task_public_contract_surface(normalized_surface)
            class_info = class_map.get(model_name)
            if not isinstance(class_info, dict):
                issues.append(f"missing primary request model {model_name}")
                continue

            actual_params = list(class_info.get("constructor_params") or [])
            min_required_params = class_info.get("constructor_min_args")
            expected_prefix = actual_params[: len(expected_params)]
            if expected_params and expected_prefix != expected_params:
                issues.append(
                    f"primary request model {model_name} must start with constructor fields ({', '.join(expected_params)})"
                )
                continue
            if isinstance(min_required_params, int) and min_required_params > len(expected_params):
                issues.append(
                    f"primary request model {model_name} requires additional constructor fields beyond ({', '.join(expected_params)})"
                )
            continue

        required_surfaces.append(normalized_surface)
        owner_name, callable_name, expected_params = parse_task_public_contract_surface(normalized_surface)
        if owner_name:
            class_info = class_map.get(owner_name)
            method_signatures = (class_info or {}).get("method_signatures") or {}
            method_info = method_signatures.get(callable_name) if isinstance(method_signatures, dict) else None
            if not isinstance(class_info, dict) or not isinstance(method_info, dict):
                issues.append(f"missing required surface {owner_name}.{callable_name}")
            continue

        function_info = function_map.get(callable_name)
        if not isinstance(function_info, dict):
            issues.append(f"missing required surface {callable_name}")
            continue
        actual_params = list(function_info.get("params") or [])
        if expected_params and actual_params[: len(expected_params)] != expected_params:
            issues.append(
                f"required surface {callable_name} must expose parameters ({', '.join(expected_params)})"
            )
            continue
        if callable_name == "main" and "__main__" in normalized_surface and not code_analysis.get("has_main_guard", False):
            issues.append("missing required surface main guard")

    return {
        "anchor_present": True,
        "anchor": anchor,
        "public_facade": public_facade,
        "primary_request_model": primary_request_model,
        "required_surfaces": required_surfaces,
        "issues": issues,
        "passed": not issues,
    }


def should_compact_architecture_context(
    task: Optional[Task],
    task_public_contract_anchor: str,
    execution_agent_name: Optional[str],
    max_tokens: Optional[int],
) -> bool:
    if task is None or not isinstance(task_public_contract_anchor, str) or not task_public_contract_anchor.strip():
        return False
    if not isinstance(execution_agent_name, str) or AgentRegistry.normalize_key(execution_agent_name) != "code_engineer":
        return False
    if isinstance(task.repair_context, dict) and bool(task.repair_context):
        return True
    return isinstance(max_tokens, int) and 0 < max_tokens <= 1200


def compact_architecture_context(task: Task, task_public_contract_anchor: str) -> str:
    repair_focused = isinstance(task.repair_context, dict) and bool(task.repair_context)
    compact_lines = [
        "Repair-focused architecture summary:" if repair_focused else "Low-budget architecture summary:",
        "- Keep one main facade plus the exact anchored request model and method names.",
        "- Public contract anchor:",
    ]
    compact_lines.extend(
        f"  {line}"
        for line in task_public_contract_anchor.splitlines()
        if isinstance(line, str) and line.strip()
    )
    if repair_focused:
        compact_lines.append(
            "- Treat prior architecture snippets as behavioral guidance only. Do not copy illustrative code blocks over the failing implementation, validation summary, or cited pytest failures."
        )
        compact_lines.append(
            "- During repair, prefer the existing failing module, the validation summary, and the cited pytest details over any stale field names or helper flows shown in the architecture sketch."
        )
    compact_lines.append(
        "- Keep validation, scoring, audit logging, and batch behavior on that same facade unless the task explicitly requires another public collaborator."
    )
    compact_lines.append(
        "- Inline optional scoring or audit detail instead of separate Logger, Scorer, Processor, Manager, or extra result dataclasses when the public contract does not require them."
    )
    line_budget = task_line_budget(task)
    if line_budget is not None:
        compact_lines.append(
            f"- Stay comfortably under {line_budget} lines and leave visible headroom for imports and the CLI."
        )
    if task_requires_cli_entrypoint(task):
        compact_lines.append(
            '- Include a minimal main() plus a literal if __name__ == "__main__": block in the same module.'
        )
    return "\n".join(compact_lines)


def task_exact_top_level_test_count(task: Optional[Task]) -> Optional[int]:
    if task is None or not isinstance(task.description, str):
        return None
    match = _EXACT_TEST_COUNT_PATTERN.search(task.description.lower())
    if match is None:
        return None
    return int(match.group(1))


def task_max_top_level_test_count(task: Optional[Task]) -> Optional[int]:
    if task is None or not isinstance(task.description, str):
        return None
    match = _MAX_TEST_COUNT_PATTERN.search(task.description.lower())
    if match is None:
        return None
    return int(match.group(1))


def task_fixture_budget(task: Optional[Task]) -> Optional[int]:
    if task is None or not isinstance(task.description, str):
        return None
    match = _FIXTURE_BUDGET_PATTERN.search(task.description.lower())
    if match is None:
        return None
    return int(match.group(1))


def summary_limit_exceeded(validation_summary: object, label: str) -> bool:
    if not isinstance(validation_summary, str) or not validation_summary.strip():
        return False
    pattern = rf"^- {re.escape(label)}:\s*(\d+)\s*/\s*(\d+)"
    for line in validation_summary.splitlines():
        match = re.match(pattern, line.strip(), re.IGNORECASE)
        if match is None:
            continue
        actual = int(match.group(1))
        limit = int(match.group(2))
        return actual > limit
    return False


def is_budget_decomposition_planner(task: Task) -> bool:
    repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
    return repair_context.get("decomposition_mode") == "budget_compaction_planner"


def build_budget_decomposition_instruction(failure_category: str) -> str:
    if failure_category == FailureCategory.TEST_VALIDATION.value:
        return (
            "Produce a compact budget decomposition brief for the next pytest repair. "
            "Distill only the minimum required imports, scenarios, helper removals, and rewrite order needed to keep the suite under budget while preserving the validated contract."
        )
    return (
        "Produce a compact budget decomposition brief for the next module repair. "
        "Distill only the minimum required public surface, behaviors, optional cuts, and rewrite order needed to keep the implementation under budget while preserving the validated contract."
    )


def build_budget_decomposition_task_context(
    task: Task,
    repair_context: dict[str, Any],
    execution_agent_name: str,
) -> dict[str, Any]:
    failure_category = str(repair_context.get("failure_category") or FailureCategory.UNKNOWN.value)
    return {
        "cycle": repair_context.get("cycle"),
        "decomposition_mode": "budget_compaction_planner",
        "decomposition_target_task_id": task.id,
        "decomposition_target_agent": execution_agent_name,
        "decomposition_failure_category": failure_category,
        "failure_category": failure_category,
        "failure_message": repair_context.get("failure_message") or "",
        "instruction": build_budget_decomposition_instruction(failure_category),
        "validation_summary": repair_context.get("validation_summary") or "",
    }


def repair_requires_budget_decomposition(repair_context: dict[str, Any]) -> bool:
    failure_category = repair_context.get("failure_category")
    if failure_category not in {
        FailureCategory.CODE_VALIDATION.value,
        FailureCategory.TEST_VALIDATION.value,
    }:
        return False
    validation_summary = repair_context.get("validation_summary")
    if not isinstance(validation_summary, str) or not validation_summary.strip():
        return False
    normalized = validation_summary.lower()
    if "completion diagnostics:" in normalized and "likely truncated" in normalized:
        return True
    if (
        failure_category == FailureCategory.CODE_VALIDATION.value
        and "completion diagnostics:" in normalized
        and "completion limit reached" in normalized
        and "missing required cli entrypoint" in normalized
    ):
        return True
    if summary_limit_exceeded(validation_summary, "Line count"):
        return True
    if failure_category == FailureCategory.TEST_VALIDATION.value:
        return any(
            summary_limit_exceeded(validation_summary, label)
            for label in ("Top-level test functions", "Fixture count")
        )
    return False