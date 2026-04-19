"""Task-constraint helpers used by the Orchestrator facade."""

from __future__ import annotations

import re
from typing import Optional

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.memory.project_state import Task


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