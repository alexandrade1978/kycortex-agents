"""Workflow-control helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import Any, Callable, Optional, cast

from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.providers.base import redact_sensitive_data
from kycortex_agents.types import AgentOutput


def log_event(logger: Any, level: str, event: str, **fields: Any) -> None:
    log_method = getattr(logger, level)
    safe_fields = cast(dict[str, Any], redact_sensitive_data(privacy_safe_log_fields(fields)))
    log_method(event, extra={"event": event, **safe_fields})


def privacy_safe_log_fields(fields: dict[str, Any]) -> dict[str, Any]:
    safe_fields: dict[str, Any] = {}
    for field_name, value in fields.items():
        minimized_field_name = task_id_count_log_field_name(field_name)
        if minimized_field_name is not None:
            count = task_id_collection_count(value)
            if count is not None:
                safe_fields[minimized_field_name] = count
                continue
        safe_fields[field_name] = value
    return safe_fields


def task_id_collection_count(value: Any) -> Optional[int]:
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(value, str):
        return 1 if value else 0
    if value is None:
        return 0
    return None


def task_id_count_log_field_name(field_name: str) -> Optional[str]:
    if field_name == "task_ids" or field_name.endswith("_task_ids"):
        return f"{field_name[:-len('_ids')]}_count"
    return None


def emit_workflow_progress(logger: Any, project: ProjectState, *, task: Optional[Task] = None) -> None:
    workflow_telemetry = project.record_workflow_progress(
        task_id=task.id if task is not None else None,
        task_status=task.status if task is not None else None,
    )
    log_event(
        logger,
        "info",
        "workflow_progress",
        project_name=project.project_name,
        phase=project.phase,
        task_id=task.id if task is not None else None,
        task_status=task.status if task is not None else None,
        workflow_telemetry=workflow_telemetry,
    )


def pause_workflow(logger: Any, project: ProjectState, *, reason: str) -> bool:
    changed = project.pause_workflow(reason=reason)
    if changed:
        project.save()
        log_event(
            logger,
            "info",
            "workflow_paused",
            project_name=project.project_name,
            phase=project.phase,
            reason=project.workflow_pause_reason,
        )
    return changed


def resume_workflow(logger: Any, project: ProjectState, *, reason: str = "paused_workflow") -> bool:
    changed = project.resume_workflow(reason=reason)
    if changed:
        project.save()
        log_event(
            logger,
            "info",
            "workflow_resumed",
            project_name=project.project_name,
            phase=project.phase,
            reason=reason,
        )
    return changed


def cancel_workflow(logger: Any, project: ProjectState, *, reason: str = "manual_cancel") -> list[str]:
    was_cancelled = project.is_workflow_cancelled()
    cancelled_task_ids = project.cancel_workflow(reason=reason)
    if not was_cancelled and project.is_workflow_cancelled():
        project.save()
        log_event(
            logger,
            "warning",
            "workflow_cancelled",
            project_name=project.project_name,
            phase=project.phase,
            reason=reason,
            cancelled_task_ids=list(cancelled_task_ids),
        )
    return cancelled_task_ids


def skip_task(logger: Any, project: ProjectState, task_id: str, *, reason: str) -> bool:
    task = project.get_task(task_id)
    if task is None:
        return False
    project.skip_task(task_id, reason, reason_type="manual")
    project.save()
    log_event(
        logger,
        "info",
        "task_skipped",
        project_name=project.project_name,
        task_id=task_id,
        phase=project.phase,
        reason=reason,
    )
    return True


def override_task(
    logger: Any,
    project: ProjectState,
    task_id: str,
    output: str | AgentOutput,
    *,
    reason: str,
) -> bool:
    changed = project.override_task(task_id, output, reason=reason)
    if changed:
        project.save()
        log_event(
            logger,
            "info",
            "task_overridden",
            project_name=project.project_name,
            task_id=task_id,
            phase=project.phase,
            reason=reason,
        )
    return changed


def replay_workflow(logger: Any, project: ProjectState, *, reason: str = "manual_replay") -> list[str]:
    replayed_task_ids = project.replay_workflow(reason=reason)
    if replayed_task_ids:
        project.save()
        log_event(
            logger,
            "info",
            "workflow_replayed",
            project_name=project.project_name,
            phase=project.phase,
            reason=reason,
            replayed_task_ids=list(replayed_task_ids),
        )
    return replayed_task_ids


def ensure_budget_decomposition_task(
    project: ProjectState,
    task: Task,
    repair_context: dict[str, Any],
    *,
    requires_budget_decomposition: Callable[[dict[str, Any]], bool],
    build_budget_decomposition_task_context: Callable[[Task, dict[str, Any]], dict[str, Any]],
) -> Optional[Task]:
    decomposition_task_id = repair_context.get("budget_decomposition_plan_task_id")
    if isinstance(decomposition_task_id, str) and decomposition_task_id.strip():
        existing = project.get_task(decomposition_task_id)
        if existing is not None:
            return existing
    if not requires_budget_decomposition(repair_context):
        return None
    decomposition_task = project._create_budget_decomposition_task(
        task.id,
        build_budget_decomposition_task_context(task, repair_context),
    )
    if decomposition_task is not None:
        repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
    return decomposition_task


def exit_if_workflow_paused(logger: Any, project: ProjectState) -> bool:
    if not project.is_workflow_paused():
        return False
    project.save()
    log_event(
        logger,
        "info",
        "workflow_paused",
        project_name=project.project_name,
        phase=project.phase,
        reason=project.workflow_pause_reason,
    )
    return True


def exit_if_workflow_cancelled(logger: Any, project: ProjectState) -> bool:
    if not project.is_workflow_cancelled():
        return False
    project.save()
    log_event(
        logger,
        "warning",
        "workflow_cancelled",
        project_name=project.project_name,
        phase=project.phase,
        terminal_outcome=project.terminal_outcome,
    )
    return True


def validate_agent_resolution(registry: Any, project: ProjectState) -> None:
    for task in project.tasks:
        if not registry.has(task.assigned_to):
            raise AgentExecutionError(
                f"Task '{task.id}' is assigned to unknown agent '{task.assigned_to}'"
            )