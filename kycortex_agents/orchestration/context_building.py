"""Context-building helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import Any, Callable, Optional


def apply_task_public_contract_context(
    ctx: dict[str, Any],
    *,
    task_public_contract_anchor: str,
    should_compact_architecture_context: Callable[[], bool],
    compact_architecture_context: Callable[[], str],
) -> Optional[str]:
    if not task_public_contract_anchor:
        return None

    ctx["task_public_contract_anchor"] = task_public_contract_anchor
    if should_compact_architecture_context():
        return compact_architecture_context()
    return None


def apply_completed_task_artifact_contexts(
    ctx: dict[str, Any],
    *,
    normalized_assigned_to: str,
    code_artifact_context: Callable[[], dict[str, Any]],
    dependency_artifact_context: Callable[[], dict[str, Any]],
    test_artifact_context: Callable[[], dict[str, Any]],
) -> None:
    if normalized_assigned_to == "code_engineer":
        ctx.update(code_artifact_context())
    if normalized_assigned_to == "dependency_manager":
        ctx.update(dependency_artifact_context())
    if normalized_assigned_to == "qa_tester":
        ctx.update(test_artifact_context())


def apply_completed_task_output_to_context(
    ctx: dict[str, Any],
    *,
    task_id: str,
    assigned_to: str,
    title: str,
    visible_output: str,
    budget_decomposition_plan_task_id: Optional[str],
    compact_architecture_context: Optional[str],
    is_budget_decomposition_planner: Callable[[], bool],
    semantic_output_key: Callable[[str, str], Optional[str]],
) -> bool:
    ctx[task_id] = visible_output
    completed_tasks = ctx.setdefault("completed_tasks", {})
    if isinstance(completed_tasks, dict):
        completed_tasks[task_id] = visible_output

    if budget_decomposition_plan_task_id == task_id:
        ctx["budget_decomposition_brief"] = visible_output
    if is_budget_decomposition_planner():
        return False

    semantic_key = semantic_output_key(assigned_to, title)
    if semantic_key:
        semantic_output = visible_output
        if semantic_key == "architecture" and compact_architecture_context:
            semantic_output = compact_architecture_context
        ctx[semantic_key] = semantic_output
    return True


def apply_repair_context_to_context(
    ctx: dict[str, Any],
    repair_context: dict[str, Any],
    execution_agent_name: str,
    budget_decomposition_plan_task_id: Optional[str],
    *,
    agent_visible_repair_context: Callable[[dict[str, Any], str], dict[str, Any]],
    normalized_execution_agent: str,
    normalized_helper_surface_symbols: Callable[[object], list[str]],
    qa_repair_should_reuse_failed_test_artifact: Callable[[object, object, object], bool],
) -> None:
    ctx["repair_context"] = agent_visible_repair_context(repair_context, execution_agent_name)
    if budget_decomposition_plan_task_id is not None:
        ctx["budget_decomposition_plan_task_id"] = budget_decomposition_plan_task_id

    validation_summary = repair_context.get("validation_summary")
    if isinstance(validation_summary, str) and validation_summary.strip():
        ctx["repair_validation_summary"] = validation_summary

    helper_surface_usages = [
        item.strip()
        for item in repair_context.get("helper_surface_usages", [])
        if isinstance(item, str) and item.strip()
    ]
    helper_surface_symbols = normalized_helper_surface_symbols(
        repair_context.get("helper_surface_symbols") or helper_surface_usages
    )
    existing_tests = repair_context.get("existing_tests")
    failed_artifact_content = repair_context.get("failed_artifact_content")
    failed_output = repair_context.get("failed_output")
    repair_content = failed_artifact_content if isinstance(failed_artifact_content, str) and failed_artifact_content.strip() else failed_output

    if normalized_execution_agent == "code_engineer" and isinstance(repair_content, str) and repair_content.strip():
        ctx["existing_code"] = repair_content
    if normalized_execution_agent == "code_engineer" and isinstance(existing_tests, str) and existing_tests.strip():
        ctx["existing_tests"] = existing_tests
    if normalized_execution_agent == "qa_tester":
        if (
            isinstance(repair_content, str)
            and repair_content.strip()
            and qa_repair_should_reuse_failed_test_artifact(
                validation_summary,
                ctx.get("code", ""),
                repair_content,
            )
        ):
            ctx["existing_tests"] = repair_content
        if "test_validation_summary" not in ctx and isinstance(validation_summary, str) and validation_summary.strip():
            ctx["test_validation_summary"] = validation_summary
        if helper_surface_usages:
            ctx["repair_helper_surface_usages"] = helper_surface_usages
        if helper_surface_symbols:
            ctx["repair_helper_surface_symbols"] = helper_surface_symbols
    if normalized_execution_agent == "dependency_manager":
        if isinstance(repair_content, str) and repair_content.strip():
            ctx["existing_dependency_manifest"] = repair_content
        if "dependency_validation_summary" not in ctx and isinstance(validation_summary, str) and validation_summary.strip():
            ctx["dependency_validation_summary"] = validation_summary