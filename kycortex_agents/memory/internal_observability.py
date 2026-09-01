"""Internal read-model adapter for operator-facing observability surfaces."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict, cast

from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import (
    InternalMetricDistribution,
    InternalTaskRuntimeTelemetry,
    InternalWorkflowErrorSummary,
    InternalWorkflowFallbackSummary,
    InternalWorkflowProviderHealthSummary,
    InternalWorkflowProviderSummary,
    InternalWorkflowRepairSummary,
    InternalWorkflowResumeSummary,
    NumericMetricMap,
    WorkflowStatus,
)


class InternalObservabilitySource(TypedDict):
    """Persisted-state source metadata for internal observability surfaces."""

    state_file: Optional[str]
    state_store_kind: str
    schema_version: int


class InternalObservabilityWorkflowOverview(TypedDict):
    """Workflow-level observability overview derived from internal telemetry."""

    project_name: str
    goal: str
    workflow_status: WorkflowStatus
    phase: str
    acceptance_policy: Optional[str]
    terminal_outcome: Optional[str]
    failure_category: Optional[str]
    acceptance_criteria_met: bool
    acceptance_evaluation: Dict[str, Any]
    updated_at: str
    task_count: int
    task_status_counts: Dict[str, int]
    tasks_with_provider_calls: int
    tasks_without_provider_calls: int
    final_providers: List[str]
    observed_providers: List[str]
    attempt_count: int
    retry_attempt_count: int
    duration_ms: InternalMetricDistribution
    usage: NumericMetricMap


class InternalObservabilityTaskTimelineEntry(TypedDict):
    """Panel-ready task timeline entry for internal observability UI shells."""

    task_id: str
    title: str
    description: str
    dependencies: List[str]
    repair_origin_task_id: Optional[str]
    assigned_to: str
    status: str
    has_output: bool
    has_failure: bool
    started_at: Optional[str]
    last_attempt_started_at: Optional[str]
    completed_at: Optional[str]
    provider: Optional[str]
    model: Optional[str]
    success: Optional[bool]
    attempts_used: int
    retry_attempt_count: int
    task_duration_ms: int | float | None
    last_attempt_duration_ms: int | float | None
    provider_duration_ms: int | float | None
    provider_latency_ms: int | float | None
    usage: NumericMetricMap
    provider_health: Dict[str, Dict[str, Any]]


class InternalObservabilityProviderPanel(TypedDict):
    """Panel-ready provider rollup for internal observability UI shells."""

    provider: str
    task_count: int
    success_count: int
    failure_count: int
    attempt_count: int
    retry_attempt_count: int
    models: List[str]
    duration_ms: InternalMetricDistribution
    usage: NumericMetricMap
    status_counts: Dict[str, int]
    last_outcome_counts: Dict[str, int]
    retryable_failure_count: int
    active_health_check_count: int


class InternalObservabilityExecutionPanel(TypedDict):
    """Execution diagnostics grouped for internal observability UI shells."""

    resume_summary: InternalWorkflowResumeSummary
    repair_summary: InternalWorkflowRepairSummary
    fallback_summary: InternalWorkflowFallbackSummary
    error_summary: InternalWorkflowErrorSummary


class InternalObservabilityEvidencePanel(TypedDict):
    """Audit-evidence summary for internal observability UI shells."""

    state_sha256: Optional[str]
    event_chain_head: Optional[str]
    event_count: int
    verification_checks: Dict[str, str]
    verification_passed: bool
    legal_hold: bool
    snapshot_history_limit: int
    run_identity: Dict[str, Any]


class InternalObservabilityView(TypedDict):
    """Top-level internal read model for observability UI shells."""

    source: InternalObservabilitySource
    workflow_overview: InternalObservabilityWorkflowOverview
    task_timeline: List[InternalObservabilityTaskTimelineEntry]
    provider_panels: List[InternalObservabilityProviderPanel]
    execution_panel: InternalObservabilityExecutionPanel
    evidence_panel: InternalObservabilityEvidencePanel


def load_internal_observability_view(state_file: str) -> InternalObservabilityView:
    """Load persisted workflow state and derive a panel-ready internal view."""

    return build_internal_observability_view(ProjectState.load(state_file))


def build_internal_observability_view(project: ProjectState) -> InternalObservabilityView:
    """Project a persisted workflow state into a read-only internal UI model."""

    telemetry = project.internal_runtime_telemetry()
    workflow = telemetry["workflow"]

    state_payload = project._serialized_state() if hasattr(project, "_serialized_state") else {}
    integrity = state_payload.get("integrity", {}) if isinstance(state_payload, dict) else {}
    execution_events = state_payload.get("execution_events", []) if isinstance(state_payload, dict) else []
    raw_state_sha256 = integrity.get("state_sha256") if isinstance(integrity, dict) else None
    state_sha256 = raw_state_sha256 if isinstance(raw_state_sha256, str) else None
    raw_chain_head = integrity.get("event_chain_head") if isinstance(integrity, dict) else None
    event_chain_head = raw_chain_head if isinstance(raw_chain_head, str) else None
    evidence_panel: InternalObservabilityEvidencePanel = {
        "state_sha256": state_sha256,
        "event_chain_head": event_chain_head,
        "event_count": len(execution_events) if isinstance(execution_events, list) else 0,
        "verification_checks": {
            "state_digest": "passed" if state_sha256 is not None else "skipped",
            "event_chain": "passed" if isinstance(execution_events, list) and execution_events else "skipped",
            "integrity_sidecar": "skipped",
            "artifact_manifest": "skipped",
        },
        "verification_passed": state_sha256 is not None,
        "legal_hold": bool(getattr(project, "legal_hold", False)),
        "snapshot_history_limit": int(getattr(project, "snapshot_history_limit", 0) or 0),
        "run_identity": cast(Dict[str, Any], dict(getattr(project, "run_identity", {}) or {})),
    }
    return {
        "source": {
            "state_file": project.state_file,
            "state_store_kind": _state_store_kind(project.state_file),
            "schema_version": int(project.schema_version),
        },
        "workflow_overview": {
            "project_name": telemetry["project_name"],
            "goal": telemetry["goal"],
            "workflow_status": telemetry["workflow_status"],
            "phase": telemetry["phase"],
            "acceptance_policy": telemetry["acceptance_policy"],
            "terminal_outcome": telemetry["terminal_outcome"],
            "failure_category": telemetry["failure_category"],
            "acceptance_criteria_met": telemetry["acceptance_criteria_met"],
            "acceptance_evaluation": cast(Dict[str, Any], dict(workflow["acceptance_evaluation"])),
            "updated_at": telemetry["updated_at"],
            "task_count": int(workflow["task_count"]),
            "task_status_counts": _sorted_count_map(workflow["task_status_counts"]),
            "tasks_with_provider_calls": int(workflow["tasks_with_provider_calls"]),
            "tasks_without_provider_calls": int(workflow["tasks_without_provider_calls"]),
            "final_providers": list(workflow["final_providers"]),
            "observed_providers": list(workflow["observed_providers"]),
            "attempt_count": int(workflow["attempt_count"]),
            "retry_attempt_count": int(workflow["retry_attempt_count"]),
            "duration_ms": cast(InternalMetricDistribution, dict(workflow["duration_ms"])),
            "usage": _sorted_numeric_map(workflow["usage"]),
        },
        "task_timeline": _build_task_timeline(project, telemetry["tasks"]),
        "provider_panels": _build_provider_panels(
            workflow["provider_summary"],
            workflow["provider_health_summary"],
        ),
        "execution_panel": {
            "resume_summary": cast(InternalWorkflowResumeSummary, dict(workflow["resume_summary"])),
            "repair_summary": cast(InternalWorkflowRepairSummary, dict(workflow["repair_summary"])),
            "fallback_summary": cast(InternalWorkflowFallbackSummary, dict(workflow["fallback_summary"])),
            "error_summary": cast(InternalWorkflowErrorSummary, dict(workflow["error_summary"])),
        },
        "evidence_panel": evidence_panel,
    }


def _state_store_kind(state_file: Optional[str]) -> str:
    if not isinstance(state_file, str) or not state_file:
        return "memory"
    lowered = state_file.lower()
    if lowered.endswith((".sqlite", ".db")):
        return "sqlite"
    return "json"


def _build_task_timeline(
    project: ProjectState,
    task_telemetry: Dict[str, InternalTaskRuntimeTelemetry],
) -> List[InternalObservabilityTaskTimelineEntry]:
    timeline: List[InternalObservabilityTaskTimelineEntry] = []
    seen_task_ids: set[str] = set()

    for task in project.tasks:
        seen_task_ids.add(task.id)
        timeline.append(_timeline_entry_from_task(task, task_telemetry.get(task.id)))

    for task_id in sorted(task_telemetry):
        if task_id in seen_task_ids:
            continue
        timeline.append(_timeline_entry_from_telemetry_only(task_id, task_telemetry[task_id]))

    return timeline


def _timeline_entry_from_task(
    task: Task,
    telemetry: Optional[InternalTaskRuntimeTelemetry],
) -> InternalObservabilityTaskTimelineEntry:
    dependencies = [dependency for dependency in task.dependencies if isinstance(dependency, str)]
    return {
        "task_id": task.id,
        "title": task.title,
        "description": task.description,
        "dependencies": dependencies,
        "repair_origin_task_id": task.repair_origin_task_id,
        "assigned_to": telemetry["agent_name"] if isinstance(telemetry, dict) else task.assigned_to,
        "status": telemetry["status"] if isinstance(telemetry, dict) else task.status,
        "has_output": task.output is not None or task.output_payload is not None,
        "has_failure": task.last_error is not None or task.last_error_category is not None,
        "started_at": task.started_at,
        "last_attempt_started_at": task.last_attempt_started_at,
        "completed_at": task.completed_at,
        "provider": telemetry["provider"] if isinstance(telemetry, dict) else None,
        "model": telemetry["model"] if isinstance(telemetry, dict) else None,
        "success": telemetry["success"] if isinstance(telemetry, dict) else None,
        "attempts_used": int(telemetry["attempts_used"]) if isinstance(telemetry, dict) else 0,
        "retry_attempt_count": int(telemetry["retry_attempt_count"]) if isinstance(telemetry, dict) else 0,
        "task_duration_ms": telemetry["task_duration_ms"] if isinstance(telemetry, dict) else None,
        "last_attempt_duration_ms": telemetry["last_attempt_duration_ms"] if isinstance(telemetry, dict) else None,
        "provider_duration_ms": telemetry["provider_duration_ms"] if isinstance(telemetry, dict) else None,
        "provider_latency_ms": telemetry["provider_latency_ms"] if isinstance(telemetry, dict) else None,
        "usage": _sorted_numeric_map(telemetry["usage"]) if isinstance(telemetry, dict) else {},
        "provider_health": _copied_provider_health(telemetry["provider_health"]) if isinstance(telemetry, dict) else {},
    }


def _timeline_entry_from_telemetry_only(
    task_id: str,
    telemetry: InternalTaskRuntimeTelemetry,
) -> InternalObservabilityTaskTimelineEntry:
    return {
        "task_id": task_id,
        "title": task_id,
        "description": "",
        "dependencies": [],
        "repair_origin_task_id": None,
        "assigned_to": telemetry["agent_name"],
        "status": telemetry["status"],
        "has_output": False,
        "has_failure": False,
        "started_at": None,
        "last_attempt_started_at": None,
        "completed_at": None,
        "provider": telemetry["provider"],
        "model": telemetry["model"],
        "success": telemetry["success"],
        "attempts_used": int(telemetry["attempts_used"]),
        "retry_attempt_count": int(telemetry["retry_attempt_count"]),
        "task_duration_ms": telemetry["task_duration_ms"],
        "last_attempt_duration_ms": telemetry["last_attempt_duration_ms"],
        "provider_duration_ms": telemetry["provider_duration_ms"],
        "provider_latency_ms": telemetry["provider_latency_ms"],
        "usage": _sorted_numeric_map(telemetry["usage"]),
        "provider_health": _copied_provider_health(telemetry["provider_health"]),
    }


def _build_provider_panels(
    provider_summary: Dict[str, InternalWorkflowProviderSummary],
    provider_health_summary: Dict[str, InternalWorkflowProviderHealthSummary],
) -> List[InternalObservabilityProviderPanel]:
    provider_names = sorted(set(provider_summary) | set(provider_health_summary))
    panels: List[InternalObservabilityProviderPanel] = []

    for provider_name in provider_names:
        summary = provider_summary.get(provider_name)
        health = provider_health_summary.get(provider_name)
        merged_models = sorted(
            set(summary["models"] if isinstance(summary, dict) else [])
            | set(health["models"] if isinstance(health, dict) else [])
        )
        panels.append(
            {
                "provider": provider_name,
                "task_count": int(summary["task_count"]) if isinstance(summary, dict) else 0,
                "success_count": int(summary["success_count"]) if isinstance(summary, dict) else 0,
                "failure_count": int(summary["failure_count"]) if isinstance(summary, dict) else 0,
                "attempt_count": int(summary["attempt_count"]) if isinstance(summary, dict) else 0,
                "retry_attempt_count": int(summary["retry_attempt_count"]) if isinstance(summary, dict) else 0,
                "models": merged_models,
                "duration_ms": cast(
                    InternalMetricDistribution,
                    dict(summary["duration_ms"]) if isinstance(summary, dict) else _empty_metric_distribution(),
                ),
                "usage": _sorted_numeric_map(summary["usage"] if isinstance(summary, dict) else {}),
                "status_counts": _sorted_count_map(health["status_counts"] if isinstance(health, dict) else {}),
                "last_outcome_counts": _sorted_count_map(
                    health["last_outcome_counts"] if isinstance(health, dict) else {}
                ),
                "retryable_failure_count": int(health["retryable_failure_count"]) if isinstance(health, dict) else 0,
                "active_health_check_count": int(health["active_health_check_count"]) if isinstance(health, dict) else 0,
            }
        )

    return panels


def _empty_metric_distribution() -> InternalMetricDistribution:
    return {"count": 0, "total": None, "min": None, "max": None, "avg": None}


def _sorted_count_map(counts: Dict[str, int]) -> Dict[str, int]:
    return {key: int(counts[key]) for key in sorted(counts)}


def _sorted_numeric_map(metrics: Dict[str, int | float]) -> NumericMetricMap:
    return {key: metrics[key] for key in sorted(metrics)}


def _copied_provider_health(provider_health: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    copied: Dict[str, Dict[str, Any]] = {}
    for provider_name in sorted(provider_health):
        copied[provider_name] = cast(Dict[str, Any], dict(provider_health[provider_name]))
    return copied