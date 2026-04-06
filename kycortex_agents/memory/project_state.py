from collections import deque
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Callable, cast
from datetime import datetime, timezone

from kycortex_agents.exceptions import StatePersistenceError, WorkflowDefinitionError
from kycortex_agents.memory.state_store import _public_state_path_label, resolve_state_store
from kycortex_agents.providers.base import (
    redact_sensitive_data,
    redact_sensitive_text,
    sanitize_provider_call_metadata,
)
from kycortex_agents.types import (
    AgentOutput,
    ArtifactRecord,
    ArtifactType,
    DecisionRecord,
    FailureCategory,
    FailureRecord,
    MetricDistribution,
    NumericMetricMap,
    ProjectSnapshot,
    TaskResult,
    TaskResourceTelemetry,
    TaskStatus,
    WorkflowAcceptanceSummary,
    WorkflowOutcome,
    WorkflowProgressSummary,
    WorkflowProviderHealthSummary,
    WorkflowRepairHistoryEntry,
    WorkflowProviderSummary,
    WorkflowRepairSummary,
    WorkflowResumeSummary,
    WorkflowStatus,
    WorkflowTelemetry,
)

PROJECT_STATE_SCHEMA_VERSION = 1
_LEGACY_PROJECT_STATE_SCHEMA_VERSION = 0


def _migrate_project_state_v0_to_v1(data: Dict[str, Any]) -> Dict[str, Any]:
    migrated = dict(data)
    migrated["schema_version"] = PROJECT_STATE_SCHEMA_VERSION
    return migrated


_PROJECT_STATE_SCHEMA_MIGRATIONS: Dict[int, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    _LEGACY_PROJECT_STATE_SCHEMA_VERSION: _migrate_project_state_v0_to_v1,
}


def _redact_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return redact_sensitive_text(value)


def _redact_payload(value: Any) -> Any:
    return redact_sensitive_data(value)


def _redact_provider_call(provider_call: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if provider_call is None:
        return None
    return sanitize_provider_call_metadata(provider_call)


def _provider_health_entry_has_retryable_failure(raw_health_entry: Dict[str, Any]) -> bool:
    if raw_health_entry.get("last_failure_retryable") is True:
        return True
    last_outcome = raw_health_entry.get("last_outcome")
    health_status = raw_health_entry.get("status")
    return last_outcome == "failure" and health_status in {"degraded", "open_circuit"}


def _provider_health_entry_has_open_circuit(raw_health_entry: Dict[str, Any]) -> bool:
    if raw_health_entry.get("circuit_breaker_open") is True:
        return True
    return raw_health_entry.get("status") == "open_circuit"


def _normalized_redacted_reason(reason: Any, default: str) -> str:
    if isinstance(reason, str) and reason.strip():
        return _redact_text(reason.strip()) or default
    return default

@dataclass
class Task:
    """Serializable workflow task record tracked inside a project state."""

    id: str
    title: str
    description: str
    assigned_to: str
    dependencies: List[str] = field(default_factory=list)
    required_for_acceptance: bool = False
    retry_limit: int = 0
    attempts: int = 0
    last_error: Optional[str] = None
    last_error_type: Optional[str] = None
    last_error_category: Optional[str] = None
    repair_context: Dict[str, Any] = field(default_factory=dict)
    repair_origin_task_id: Optional[str] = None
    repair_attempt: int = 0
    status: str = TaskStatus.PENDING.value
    output: Optional[str] = None
    output_payload: Optional[Dict[str, Any]] = None
    skip_reason_type: Optional[str] = None
    last_provider_call: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    last_attempt_started_at: Optional[str] = None
    last_resumed_at: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    completed_at: Optional[str] = None

@dataclass
class ProjectState:
    """Mutable workflow state for tasks, decisions, artifacts, and execution metadata."""

    project_name: str
    goal: str
    tasks: List[Task] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any] | str] = field(default_factory=list)
    execution_events: List[Dict[str, Any]] = field(default_factory=list)
    phase: str = "init"
    acceptance_policy: Optional[str] = None
    terminal_outcome: Optional[str] = None
    failure_category: Optional[str] = None
    acceptance_criteria_met: bool = False
    acceptance_evaluation: Dict[str, Any] = field(default_factory=dict)
    workflow_started_at: Optional[str] = None
    workflow_finished_at: Optional[str] = None
    workflow_paused_at: Optional[str] = None
    workflow_pause_reason: Optional[str] = None
    workflow_last_resumed_at: Optional[str] = None
    repair_cycle_count: int = 0
    repair_max_cycles: int = 0
    repair_history: List[Dict[str, Any]] = field(default_factory=list)
    schema_version: int = field(default=PROJECT_STATE_SCHEMA_VERSION, init=False)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    state_file: str = "project_state.json"

    def add_task(self, task: Task):
        """Append a task to the workflow and refresh the project timestamp."""

        self.tasks.append(task)
        self._touch()

    def get_task(self, task_id: str) -> Optional[Task]:
        """Return the task with the matching identifier, if it exists."""

        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def is_task_ready(self, task: Task) -> bool:
        """Return whether a pending task has all dependencies completed."""

        if task.status != TaskStatus.PENDING.value:
            return False
        for dependency_id in task.dependencies:
            dependency = self.get_task(dependency_id)
            if dependency is None:
                return False
            if dependency.status != TaskStatus.DONE.value:
                return False
        return True

    def start_task(self, task_id: str):
        """Mark a task as running and record timing plus audit metadata."""

        for task in self.tasks:
            if task.id == task_id:
                started_at = datetime.now(timezone.utc).isoformat()
                task.status = TaskStatus.RUNNING.value
                task.attempts += 1
                task.last_error = None
                task.last_error_type = None
                task.last_error_category = None
                if task.started_at is None:
                    task.started_at = started_at
                task.last_attempt_started_at = started_at
                self._record_task_event(task, "started", started_at)
                self._record_execution_event(
                    event="task_started",
                    timestamp=started_at,
                    task_id=task.id,
                    status=task.status,
                    details={"attempts": task.attempts, "assigned_to": task.assigned_to},
                )
                self._sync_repair_origin_start(task, started_at)
                self._touch(started_at)
                return

    def fail_task(
        self,
        task_id: str,
        error: str | Exception,
        provider_call: Optional[Dict[str, Any]] = None,
        output: Optional[str | AgentOutput] = None,
        error_category: Optional[str] = None,
    ):
        """Record a task failure, re-queueing it when retry budget remains."""

        for task in self.tasks:
            if task.id == task_id:
                error_message = str(error)
                redacted_error_message = _redact_text(error_message) or ""
                redacted_provider_call = _redact_provider_call(provider_call)
                redacted_output_payload = (
                    cast(Dict[str, Any], _redact_payload(asdict(output)))
                    if isinstance(output, AgentOutput) and output.raw_content.strip()
                    else None
                )
                error_type = type(error).__name__ if isinstance(error, Exception) else "runtime_error"
                task.last_error = redacted_error_message
                task.last_error_type = error_type
                task.last_error_category = error_category or FailureCategory.TASK_EXECUTION.value
                task.last_provider_call = redacted_provider_call
                if task.attempts <= task.retry_limit:
                    task.status = TaskStatus.PENDING.value
                    task.completed_at = None
                    self._record_task_event(task, "retry_scheduled")
                    self._record_policy_enforcement_event(
                        source_event="task_retry_scheduled",
                        timestamp=task.history[-1]["timestamp"],
                        task_id=task.id,
                        status=task.status,
                        category=task.last_error_category,
                        message=redacted_error_message,
                        error_type=task.last_error_type,
                        provider_call=redacted_provider_call,
                        retryable=True,
                    )
                    self._record_execution_event(
                        event="task_retry_scheduled",
                        task_id=task.id,
                        status=task.status,
                        details={
                            "attempts": task.attempts,
                            "retry_limit": task.retry_limit,
                            "error_type": task.last_error_type,
                            "error_category": task.last_error_category,
                            "provider_call": redacted_provider_call,
                            "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, datetime.now(timezone.utc).isoformat()),
                        },
                    )
                    self._sync_repair_origin_failure(
                        task,
                        error_message=redacted_error_message,
                        error_type=error_type,
                        provider_call=redacted_provider_call,
                        output_payload=redacted_output_payload,
                        completed_at=None,
                        final_failure=False,
                    )
                    self._touch()
                    return
                task.status = TaskStatus.FAILED.value
                task.output = redacted_error_message
                task.output_payload = redacted_output_payload
                task.completed_at = datetime.now(timezone.utc).isoformat()
                self._record_task_event(task, "failed", task.completed_at, error_message=redacted_error_message)
                self._record_policy_enforcement_event(
                    source_event="task_failed",
                    timestamp=task.completed_at,
                    task_id=task.id,
                    status=task.status,
                    category=task.last_error_category,
                    message=redacted_error_message,
                    error_type=error_type,
                    provider_call=redacted_provider_call,
                    retryable=False,
                )
                self._record_execution_event(
                    event="task_failed",
                    timestamp=task.completed_at,
                    task_id=task.id,
                    status=task.status,
                    details={
                        "attempts": task.attempts,
                        "error_message": redacted_error_message,
                        "error_type": error_type,
                        "error_category": task.last_error_category,
                        "provider_call": redacted_provider_call,
                        "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, task.completed_at),
                    },
                )
                self._sync_repair_origin_failure(
                    task,
                    error_message=redacted_error_message,
                    error_type=error_type,
                    provider_call=redacted_provider_call,
                    output_payload=redacted_output_payload,
                    completed_at=task.completed_at,
                    final_failure=True,
                )
                self._touch(task.completed_at)
                return

    def complete_task(self, task_id: str, output: str | AgentOutput, provider_call: Optional[Dict[str, Any]] = None):
        """Mark a task complete and persist its raw or structured output payload."""

        redacted_provider_call = _redact_provider_call(provider_call)
        for t in self.tasks:
            if t.id == task_id:
                t.status = TaskStatus.DONE.value
                if isinstance(output, AgentOutput):
                    t.output = output.raw_content
                    t.output_payload = asdict(output)
                else:
                    t.output = output
                    t.output_payload = None
                t.last_error = None
                t.last_error_type = None
                t.last_error_category = None
                if t.repair_origin_task_id is None:
                    t.repair_context = {}
                t.last_provider_call = redacted_provider_call
                t.completed_at = datetime.now(timezone.utc).isoformat()
                self._record_task_event(t, "completed", t.completed_at)
                self._record_execution_event(
                    event="task_completed",
                    timestamp=t.completed_at,
                    task_id=t.id,
                    status=t.status,
                    details={
                        "attempts": t.attempts,
                        "assigned_to": t.assigned_to,
                        "provider_call": redacted_provider_call,
                        "last_attempt_duration_ms": self._duration_ms(t.last_attempt_started_at, t.completed_at),
                        "task_duration_ms": self._duration_ms(t.started_at, t.completed_at),
                    },
                )
                self._sync_repair_origin_completion(t, redacted_provider_call)
                self._touch(t.completed_at)

    def is_workflow_paused(self) -> bool:
        """Return whether the workflow is explicitly paused awaiting operator action."""

        return self.phase == WorkflowStatus.PAUSED.value

    def is_workflow_cancelled(self) -> bool:
        """Return whether the workflow has been cancelled by an operator."""

        return self.phase == WorkflowStatus.CANCELLED.value or self.terminal_outcome == WorkflowOutcome.CANCELLED.value

    def pause_workflow(self, *, reason: str) -> bool:
        """Mark the workflow paused so new runnable tasks are not dispatched."""

        if self._workflow_status() in {WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED, WorkflowStatus.FAILED}:
            raise ValueError("Cannot pause a finished workflow")

        paused_at = datetime.now(timezone.utc).isoformat()
        pause_reason = _normalized_redacted_reason(reason, "manual_pause")
        self.phase = WorkflowStatus.PAUSED.value
        self.workflow_finished_at = None
        self.workflow_paused_at = paused_at
        self.workflow_pause_reason = pause_reason
        self._record_execution_event(
            event="workflow_paused",
            timestamp=paused_at,
            status=self.phase,
            details={"reason": pause_reason},
        )
        self._touch(paused_at)
        return True

    def resume_workflow(self, *, reason: str = "paused_workflow") -> bool:
        """Resume a previously paused workflow and record resume metadata."""

        if not self.is_workflow_paused():
            return False

        resumed_at = datetime.now(timezone.utc).isoformat()
        resume_reason = reason.strip() if isinstance(reason, str) and reason.strip() else "paused_workflow"
        self.phase = "execution"
        self._record_workflow_resumed(resumed_at, [], reason=resume_reason)
        return True

    def replay_workflow(self, *, reason: str = "manual_replay") -> List[str]:
        """Reset the workflow to its initial runnable state for a fresh replay."""

        if any(task.status == TaskStatus.RUNNING.value for task in self.tasks):
            raise ValueError("Cannot replay a workflow while tasks are still running")

        replayed_at = datetime.now(timezone.utc).isoformat()
        replay_reason = reason.strip() if isinstance(reason, str) and reason.strip() else "manual_replay"
        removed_task_ids = [task.id for task in self.tasks if self._is_repair_lineage_task(task)]
        replayable_tasks = [task for task in self.tasks if not self._is_repair_lineage_task(task)]
        replayed_task_ids = [task.id for task in replayable_tasks]

        for task in replayable_tasks:
            task.status = TaskStatus.PENDING.value
            task.attempts = 0
            task.last_error = None
            task.last_error_type = None
            task.last_error_category = None
            task.repair_context = {}
            task.repair_origin_task_id = None
            task.repair_attempt = 0
            task.output = None
            task.output_payload = None
            task.skip_reason_type = None
            task.last_provider_call = None
            task.started_at = None
            task.last_attempt_started_at = None
            task.last_resumed_at = None
            task.completed_at = None
            self._record_task_event(task, "replayed", replayed_at, error_message=replay_reason)

        cleared_decision_count = len(self.decisions)
        cleared_artifact_count = len(self.artifacts)
        self.tasks = replayable_tasks
        self.decisions = []
        self.artifacts = []
        self.phase = "init"
        self.terminal_outcome = None
        self.failure_category = None
        self.acceptance_criteria_met = False
        self.acceptance_evaluation = {}
        self.workflow_started_at = None
        self.workflow_finished_at = None
        self.workflow_paused_at = None
        self.workflow_pause_reason = None
        self.workflow_last_resumed_at = None
        self.repair_cycle_count = 0
        self.repair_max_cycles = 0
        self.repair_history = []
        self._record_execution_event(
            event="workflow_replayed",
            timestamp=replayed_at,
            status=self.phase,
            details={
                "reason": replay_reason,
                "replayed_task_ids": replayed_task_ids,
                "removed_task_ids": removed_task_ids,
                "cleared_decision_count": cleared_decision_count,
                "cleared_artifact_count": cleared_artifact_count,
            },
        )
        self._touch(replayed_at)
        return replayed_task_ids

    def cancel_workflow(self, *, reason: str = "manual_cancel") -> List[str]:
        """Cancel a workflow and prevent any further runnable work from being dispatched."""

        current_status = self._workflow_status()
        if current_status == WorkflowStatus.CANCELLED:
            return []
        if current_status in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED}:
            raise ValueError("Cannot cancel a finished workflow")

        cancelled_at = datetime.now(timezone.utc).isoformat()
        cancel_reason = _normalized_redacted_reason(reason, "manual_cancel")
        cancelled_task_ids: List[str] = []
        for task in self.tasks:
            if task.status != TaskStatus.PENDING.value:
                continue
            task.status = TaskStatus.SKIPPED.value
            task.last_error = cancel_reason
            task.last_error_type = None
            task.last_error_category = None
            task.output = cancel_reason
            task.output_payload = None
            task.skip_reason_type = "workflow_cancelled"
            task.last_provider_call = None
            task.last_resumed_at = None
            task.completed_at = cancelled_at
            self._record_task_event(task, "cancelled", cancelled_at, error_message=cancel_reason)
            self._record_execution_event(
                event="task_cancelled",
                timestamp=cancelled_at,
                task_id=task.id,
                status=task.status,
                details={"reason": cancel_reason},
            )
            cancelled_task_ids.append(task.id)

        self.mark_workflow_finished(
            WorkflowStatus.CANCELLED.value,
            acceptance_policy=self.acceptance_policy,
            terminal_outcome=WorkflowOutcome.CANCELLED.value,
            failure_category=FailureCategory.WORKFLOW_CANCELLED.value,
            acceptance_criteria_met=False,
            acceptance_evaluation=self._cancelled_acceptance_evaluation(),
        )
        self._record_execution_event(
            event="workflow_cancelled",
            timestamp=cancelled_at,
            status=self.phase,
            details={
                "reason": cancel_reason,
                "cancelled_task_ids": cancelled_task_ids,
                "terminal_outcome": self.terminal_outcome,
            },
        )
        self._touch(cancelled_at)
        return cancelled_task_ids

    def resume_interrupted_tasks(self) -> List[str]:
        """Re-queue tasks left running by an interrupted workflow execution."""

        resumed_task_ids: List[str] = []
        resumed_at: Optional[str] = None
        for task in self.tasks:
            if task.status == TaskStatus.RUNNING.value:
                resumed_at = resumed_at or datetime.now(timezone.utc).isoformat()
                task.last_resumed_at = resumed_at
                task.status = TaskStatus.PENDING.value
                task.last_error = "Task resumed after interrupted execution"
                task.last_error_type = None
                task.last_error_category = None
                task.last_provider_call = None
                task.completed_at = None
                self._record_task_event(task, "resumed", resumed_at, error_message=task.last_error)
                self._record_execution_event(
                    event="task_resumed",
                    timestamp=resumed_at,
                    task_id=task.id,
                    status=task.status,
                    details={"reason": task.last_error},
                )
                resumed_task_ids.append(task.id)
        if resumed_at is not None:
            self._record_workflow_resumed(resumed_at, resumed_task_ids, reason="interrupted_tasks")
        return resumed_task_ids

    def resume_failed_tasks(
        self,
        *,
        include_failed_tasks: bool = True,
        failed_task_ids: Optional[List[str]] = None,
        additional_task_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Re-queue failed tasks and dependency-skipped descendants for another run."""

        failed_task_ids = list(failed_task_ids or [task.id for task in self.tasks if task.status == TaskStatus.FAILED.value])
        if not failed_task_ids:
            if additional_task_ids:
                resumed_at = datetime.now(timezone.utc).isoformat()
                self._record_workflow_resumed(
                    resumed_at,
                    [task_id for task_id in additional_task_ids if isinstance(task_id, str) and task_id],
                    reason="failed_workflow",
                )
            return []

        resumed_at = datetime.now(timezone.utc).isoformat()
        resumed_task_ids: List[str] = []
        resumable_dependency_ids = set(failed_task_ids)

        while True:
            changed = False
            for task in self.tasks:
                should_resume = (
                    include_failed_tasks
                    and task.status == TaskStatus.FAILED.value
                    and task.id in failed_task_ids
                ) or (
                    task.status == TaskStatus.SKIPPED.value
                    and self._is_dependency_failed_skip(task)
                    and any(dep in resumable_dependency_ids for dep in task.dependencies)
                )
                if not should_resume or task.id in resumed_task_ids:
                    continue
                was_failed_task = task.status == TaskStatus.FAILED.value
                task.status = TaskStatus.PENDING.value
                task.last_error = "Task resumed after failed workflow execution"
                task.last_error_type = None
                task.last_error_category = None
                if not was_failed_task:
                    task.repair_context = {}
                task.output = None
                task.output_payload = None
                task.skip_reason_type = None
                task.last_provider_call = None
                task.completed_at = None
                task.last_resumed_at = resumed_at
                self._record_task_event(task, "requeued", resumed_at, error_message=task.last_error)
                self._record_execution_event(
                    event="task_requeued",
                    timestamp=resumed_at,
                    task_id=task.id,
                    status=task.status,
                    details={"reason": task.last_error},
                )
                resumed_task_ids.append(task.id)
                resumable_dependency_ids.add(task.id)
                changed = True
            if not changed:
                break

        resumed_ids = resumed_task_ids + [task_id for task_id in additional_task_ids or [] if task_id not in resumed_task_ids]
        self._record_workflow_resumed(resumed_at, resumed_ids, reason="failed_workflow")
        return resumed_task_ids

    def _record_workflow_resumed(self, resumed_at: str, task_ids: List[str], *, reason: str) -> None:
        self.workflow_last_resumed_at = resumed_at
        self.workflow_finished_at = None
        self.workflow_paused_at = None
        self.workflow_pause_reason = None
        self._record_execution_event(
            event="workflow_resumed",
            timestamp=resumed_at,
            status=self.phase,
            details={"reason": reason, "task_ids": task_ids},
        )
        self._touch(resumed_at)

    def _plan_task_repair(self, task_id: str, repair_context: Dict[str, Any]) -> None:
        task = self.get_task(task_id)
        if task is None:
            return
        planned_at = datetime.now(timezone.utc).isoformat()
        task.repair_context = dict(repair_context)
        self._record_execution_event(
            event="task_repair_planned",
            timestamp=planned_at,
            task_id=task.id,
            status=task.status,
            details=dict(repair_context),
        )
        self._touch(planned_at)

    def _create_budget_decomposition_task(self, task_id: str, repair_context: Dict[str, Any]) -> Optional[Task]:
        source_task = self.get_task(task_id)
        if source_task is None:
            return None
        repair_attempt = int(repair_context.get("cycle") or 0)
        if repair_attempt <= 0:
            return None
        decomposition_task_id = f"{task_id}__repair_{repair_attempt}__budget_plan"
        existing = self.get_task(decomposition_task_id)
        if existing is not None:
            if isinstance(existing.repair_context, dict):
                existing.repair_context.update(dict(repair_context))
            return existing
        created_at = datetime.now(timezone.utc).isoformat()
        decomposition_task = Task(
            id=decomposition_task_id,
            title=f"Budget plan for {source_task.title}",
            description=source_task.description,
            assigned_to="architect",
            dependencies=list(source_task.dependencies),
            required_for_acceptance=False,
            retry_limit=source_task.retry_limit,
            repair_context=dict(repair_context),
            created_at=created_at,
        )
        self.tasks.append(decomposition_task)
        self._record_execution_event(
            event="task_budget_decomposition_created",
            timestamp=created_at,
            task_id=decomposition_task.id,
            status=decomposition_task.status,
            details={
                "decomposition_target_task_id": source_task.id,
                "repair_attempt": repair_attempt,
                "assigned_to": decomposition_task.assigned_to,
            },
        )
        self._touch(created_at)
        return decomposition_task

    def _create_repair_task(self, task_id: str, repair_owner: str, repair_context: Dict[str, Any]) -> Optional[Task]:
        source_task = self.get_task(task_id)
        if source_task is None:
            return None
        repair_attempt = int(repair_context.get("cycle") or 0)
        repair_task_id = f"{task_id}__repair_{repair_attempt}"
        existing = self.get_task(repair_task_id)
        if existing is not None:
            return existing
        created_at = datetime.now(timezone.utc).isoformat()
        repair_task = Task(
            id=repair_task_id,
            title=f"Repair {source_task.title}",
            description=source_task.description,
            assigned_to=repair_owner,
            dependencies=list(source_task.dependencies),
            required_for_acceptance=False,
            retry_limit=source_task.retry_limit,
            repair_context=dict(repair_context),
            repair_origin_task_id=source_task.id,
            repair_attempt=repair_attempt,
            created_at=created_at,
        )
        self.tasks.append(repair_task)
        source_task.last_resumed_at = created_at
        self._record_task_event(
            source_task,
            "requeued",
            created_at,
            error_message="Task resumed after failed workflow execution",
        )
        self._record_execution_event(
            event="task_repair_created",
            timestamp=created_at,
            task_id=repair_task.id,
            status=repair_task.status,
            details={
                "repair_origin_task_id": source_task.id,
                "repair_attempt": repair_attempt,
                "assigned_to": repair_owner,
            },
        )
        self._record_execution_event(
            event="task_requeued",
            timestamp=created_at,
            task_id=source_task.id,
            status=source_task.status,
            details={"reason": "Task resumed after failed workflow execution", "repair_task_id": repair_task.id},
        )
        self._touch(created_at)
        return repair_task

    def _sync_repair_origin_start(self, task: Task, started_at: str) -> None:
        if not task.repair_origin_task_id:
            return
        origin = self.get_task(task.repair_origin_task_id)
        if origin is None:
            return
        origin.attempts += 1
        if origin.started_at is None:
            origin.started_at = started_at
        origin.last_attempt_started_at = started_at
        origin.last_resumed_at = started_at
        self._record_task_event(
            origin,
            "repair_started",
            started_at,
            error_message=f"Repair attempt {task.repair_attempt} started via {task.id}",
        )
        self._record_execution_event(
            event="task_repair_started",
            timestamp=started_at,
            task_id=origin.id,
            status=origin.status,
            details={"repair_task_id": task.id, "repair_attempt": task.repair_attempt, "assigned_to": task.assigned_to},
        )

    def _sync_repair_origin_failure(
        self,
        task: Task,
        *,
        error_message: str,
        error_type: str,
        provider_call: Optional[Dict[str, Any]],
        output_payload: Optional[Dict[str, Any]],
        completed_at: Optional[str],
        final_failure: bool,
    ) -> None:
        if not task.repair_origin_task_id:
            return
        origin = self.get_task(task.repair_origin_task_id)
        if origin is None:
            return
        origin.status = TaskStatus.FAILED.value
        origin.last_error = error_message
        origin.last_error_type = error_type
        origin.last_error_category = task.last_error_category
        origin.last_provider_call = provider_call
        if final_failure:
            origin.output = error_message
            origin.output_payload = output_payload
            origin.completed_at = completed_at
        self._record_task_event(
            origin,
            "repair_failed" if final_failure else "repair_retry_scheduled",
            completed_at,
            error_message=error_message,
        )
        self._record_execution_event(
            event="task_repair_failed" if final_failure else "task_repair_retry_scheduled",
            timestamp=completed_at,
            task_id=origin.id,
            status=origin.status,
            details={
                "repair_task_id": task.id,
                "repair_attempt": task.repair_attempt,
                "error_type": error_type,
                "error_category": task.last_error_category,
            },
        )

    def _sync_repair_origin_completion(self, task: Task, provider_call: Optional[Dict[str, Any]]) -> None:
        if not task.repair_origin_task_id:
            return
        origin = self.get_task(task.repair_origin_task_id)
        if origin is None:
            return
        redacted_provider_call = _redact_provider_call(provider_call)
        origin.status = TaskStatus.DONE.value
        origin.output = task.output
        origin.output_payload = task.output_payload
        origin.last_error = None
        origin.last_error_type = None
        origin.last_error_category = None
        origin.repair_context = {}
        origin.last_provider_call = redacted_provider_call
        origin.completed_at = task.completed_at
        origin.last_resumed_at = task.completed_at
        self._record_task_event(
            origin,
            "repaired",
            task.completed_at,
            error_message=f"Repair task {task.id} completed successfully",
        )
        self._record_execution_event(
            event="task_repaired",
            timestamp=task.completed_at,
            task_id=origin.id,
            status=origin.status,
            details={"repair_task_id": task.id, "repair_attempt": task.repair_attempt, "assigned_to": task.assigned_to},
        )

    def _is_dependency_failed_skip(self, task: Task) -> bool:
        if task.skip_reason_type is not None:
            return task.skip_reason_type == "dependency_failed"
        return self._matching_dependency_failed_reason_task_id(task) is not None

    def should_retry_task(self, task_id: str) -> bool:
        """Return whether a pending task is currently in its retry window."""

        task = self.get_task(task_id)
        if task is None:
            return False
        return task.status == TaskStatus.PENDING.value and task.attempts > 0 and task.attempts <= task.retry_limit

    def can_start_repair_cycle(self) -> bool:
        """Return whether the workflow still has repair-cycle budget remaining."""

        return self.repair_cycle_count < self.repair_max_cycles

    def start_repair_cycle(
        self,
        *,
        reason: str,
        failure_category: Optional[str] = None,
        failed_task_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Record the start of a bounded repair cycle and persist its audit metadata."""

        started_at = datetime.now(timezone.utc).isoformat()
        self.repair_cycle_count += 1
        entry = {
            "cycle": self.repair_cycle_count,
            "started_at": started_at,
            "reason": reason,
            "failure_category": failure_category,
            "failed_task_ids": list(failed_task_ids or []),
            "budget_remaining": max(self.repair_max_cycles - self.repair_cycle_count, 0),
        }
        self.repair_history.append(entry)
        self._record_execution_event(
            event="workflow_repair_cycle_started",
            timestamp=started_at,
            status=self.phase,
            details=entry,
        )
        self._touch(started_at)
        return entry

    def add_decision(self, topic: str, decision: str, rationale: str):
        """Append a lightweight project-level decision entry with a fresh timestamp."""

        self.decisions.append({"topic": topic, "decision": decision, "rationale": rationale, "at": datetime.now(timezone.utc).isoformat()})
        self._touch()

    def add_decision_record(self, record: DecisionRecord):
        """Append a structured decision record to the project history."""

        self.decisions.append(
            {
                "topic": record.topic,
                "decision": record.decision,
                "rationale": record.rationale,
                "at": record.created_at,
                "metadata": record.metadata,
            }
        )
        self._touch(record.created_at)

    def add_artifact_record(self, record: ArtifactRecord):
        """Append a structured artifact record to the project artifact list."""

        self.artifacts.append(asdict(record))
        self._touch(record.created_at)

    def mark_workflow_running(self, *, acceptance_policy: Optional[str] = None, repair_max_cycles: Optional[int] = None):
        """Mark the workflow execution as active and emit a workflow-start event."""

        started_at = datetime.now(timezone.utc).isoformat()
        if self.workflow_started_at is None:
            self.workflow_started_at = started_at
        self.workflow_finished_at = None
        self.workflow_paused_at = None
        self.workflow_pause_reason = None
        self.phase = "execution"
        if acceptance_policy is not None:
            self.acceptance_policy = acceptance_policy
        if repair_max_cycles is not None:
            self.repair_max_cycles = repair_max_cycles
        self.terminal_outcome = None
        self.failure_category = None
        self.acceptance_criteria_met = False
        self.acceptance_evaluation = {}
        self._record_execution_event(
            event="workflow_started",
            timestamp=started_at,
            status=self.phase,
            details={
                "acceptance_policy": self.acceptance_policy,
                "repair_cycle_count": self.repair_cycle_count,
                "repair_max_cycles": self.repair_max_cycles,
            },
        )
        self._touch(started_at)

    def mark_workflow_finished(
        self,
        phase: str,
        *,
        acceptance_policy: Optional[str] = None,
        terminal_outcome: Optional[str] = None,
        failure_category: Optional[str] = None,
        acceptance_criteria_met: Optional[bool] = None,
        acceptance_evaluation: Optional[Dict[str, Any]] = None,
    ):
        """Mark the workflow finished under the supplied phase label."""

        finished_at = datetime.now(timezone.utc).isoformat()
        self.phase = phase
        self.workflow_finished_at = finished_at
        self.workflow_paused_at = None
        self.workflow_pause_reason = None
        if acceptance_policy is not None:
            self.acceptance_policy = acceptance_policy
        resolved_outcome = terminal_outcome or (
            WorkflowOutcome.COMPLETED.value if phase == "completed" else WorkflowOutcome.FAILED.value
        )
        self.terminal_outcome = resolved_outcome
        self.failure_category = failure_category
        self.acceptance_criteria_met = (
            acceptance_criteria_met
            if acceptance_criteria_met is not None
            else resolved_outcome == WorkflowOutcome.COMPLETED.value
        )
        self.acceptance_evaluation = dict(acceptance_evaluation or {})
        terminal_failure_context = self._terminal_failure_context(self.failure_category)
        workflow_telemetry = self._workflow_telemetry_summary()
        public_acceptance_evaluation = cast(Dict[str, Any], dict(workflow_telemetry["acceptance_summary"]))
        self._record_policy_enforcement_event(
            source_event="workflow_finished",
            timestamp=finished_at,
            task_id=cast(Optional[str], terminal_failure_context.get("task_id")),
            status=self.phase,
            category=self.failure_category,
            message=cast(Optional[str], terminal_failure_context.get("message")),
            error_type=cast(Optional[str], terminal_failure_context.get("error_type")),
            provider_call=cast(Optional[Dict[str, Any]], terminal_failure_context.get("provider_call")),
            terminal_outcome=self.terminal_outcome,
        )
        workflow_finished_details: Dict[str, Any] = {
            "workflow_duration_ms": self._duration_ms(self.workflow_started_at, finished_at),
            "acceptance_policy": self.acceptance_policy,
            "terminal_outcome": self.terminal_outcome,
            "failure_category": self.failure_category,
            "acceptance_criteria_met": self.acceptance_criteria_met,
            "acceptance_evaluation": public_acceptance_evaluation,
            "workflow_telemetry": workflow_telemetry,
        }
        if terminal_failure_context:
            failure_task_id = terminal_failure_context.get("task_id")
            failure_message = terminal_failure_context.get("message")
            failure_error_type = terminal_failure_context.get("error_type")
            failure_provider_call = terminal_failure_context.get("provider_call")
            if isinstance(failure_task_id, str) and failure_task_id:
                workflow_finished_details["failure_task_id"] = failure_task_id
            if isinstance(failure_message, str) and failure_message:
                workflow_finished_details["failure_message"] = failure_message
            if isinstance(failure_error_type, str) and failure_error_type:
                workflow_finished_details["failure_error_type"] = failure_error_type
            if isinstance(failure_provider_call, dict):
                workflow_finished_details["provider_call"] = failure_provider_call
        self._record_execution_event(
            event="workflow_finished",
            timestamp=finished_at,
            status=self.phase,
            details=workflow_finished_details,
        )
        self._touch(finished_at)

    def _terminal_failure_context(self, category: Optional[str]) -> Dict[str, Any]:
        if category is None:
            return {}
        matching_tasks = [
            task
            for task in self.tasks
            if task.last_error_category == category
            and (
                (isinstance(task.last_error, str) and task.last_error)
                or (isinstance(task.last_error_type, str) and task.last_error_type)
                or isinstance(task.last_provider_call, dict)
            )
        ]
        if not matching_tasks:
            return {}
        task = max(matching_tasks, key=lambda current: ((current.completed_at or ""), current.id))
        details: Dict[str, Any] = {"task_id": task.id}
        if isinstance(task.last_error, str) and task.last_error:
            details["message"] = task.last_error
        if isinstance(task.last_error_type, str) and task.last_error_type:
            details["error_type"] = task.last_error_type
        if isinstance(task.last_provider_call, dict):
            details["provider_call"] = task.last_provider_call
        return details

    def record_workflow_progress(
        self,
        *,
        task_id: Optional[str] = None,
        task_status: Optional[str] = None,
    ) -> WorkflowTelemetry:
        """Append a streaming workflow telemetry event for the current execution state."""

        recorded_at = datetime.now(timezone.utc).isoformat()
        workflow_telemetry = self._workflow_telemetry_summary()
        details: Dict[str, Any] = {
            "workflow_telemetry": workflow_telemetry,
        }
        if task_status is not None:
            details["task_status"] = task_status
        self._record_execution_event(
            event="workflow_progress",
            timestamp=recorded_at,
            task_id=task_id,
            status=self.phase,
            details=details,
        )
        self._touch(recorded_at)
        return workflow_telemetry

    def save(self):
        """Persist the current project state through the configured state-store backend."""

        self._touch()
        state_store = resolve_state_store(self.state_file)
        state_store.save(self.state_file, cast(Dict[str, Any], _redact_payload(self._serialized_state())))

    @classmethod
    def load(cls, path: str) -> "ProjectState":
        """Load a project state from disk and normalize legacy persisted fields."""

        data = cls._migrate_persisted_state(resolve_state_store(path).load(path), path)
        tasks = [Task(**t) for t in data.pop("tasks", [])]
        schema_version = data.pop("schema_version", PROJECT_STATE_SCHEMA_VERSION)
        try:
            obj = cls(**{k: v for k, v in data.items() if k != "tasks"})
        except TypeError as exc:
            raise StatePersistenceError(
                f"Project state data is invalid: {_public_state_path_label(path)}"
            ) from exc
        obj.tasks = tasks
        obj.schema_version = schema_version
        obj.state_file = path
        obj._normalize_legacy_decision_timestamps()
        obj._normalize_legacy_artifact_timestamps()
        obj._infer_legacy_skip_reason_types()
        return obj

    def _serialized_state(self) -> Dict[str, Any]:
        self.schema_version = PROJECT_STATE_SCHEMA_VERSION
        return asdict(self)

    @classmethod
    def _migrate_persisted_state(cls, data: Any, path: str) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise StatePersistenceError(
                f"Project state data is invalid: {_public_state_path_label(path)}"
            )

        raw_schema_version = data.get("schema_version", _LEGACY_PROJECT_STATE_SCHEMA_VERSION)
        if type(raw_schema_version) is not int:
            raise StatePersistenceError(
                f"Project state schema version is invalid: {_public_state_path_label(path)}"
            )
        if raw_schema_version < _LEGACY_PROJECT_STATE_SCHEMA_VERSION:
            raise StatePersistenceError(
                f"Project state schema version is invalid: {_public_state_path_label(path)}"
            )
        if raw_schema_version > PROJECT_STATE_SCHEMA_VERSION:
            raise StatePersistenceError(
                "Project state schema version "
                f"{raw_schema_version} is newer than supported version {PROJECT_STATE_SCHEMA_VERSION}: "
                f"{_public_state_path_label(path)}"
            )

        migrated = dict(data)
        schema_version = raw_schema_version
        while schema_version < PROJECT_STATE_SCHEMA_VERSION:
            migration = _PROJECT_STATE_SCHEMA_MIGRATIONS.get(schema_version)
            if migration is None:
                raise StatePersistenceError(
                    "Project state schema version "
                    f"{schema_version} has no migration path: {_public_state_path_label(path)}"
                )
            migrated = migration(dict(migrated))
            next_schema_version = migrated.get("schema_version")
            if type(next_schema_version) is not int or next_schema_version <= schema_version:
                raise StatePersistenceError(
                    "Project state schema migration did not advance the version: "
                    f"{_public_state_path_label(path)}"
                )
            schema_version = next_schema_version

        migrated["schema_version"] = schema_version
        return migrated

    def _normalize_legacy_decision_timestamps(self) -> None:
        normalized_decisions: List[Dict[str, Any]] = []
        for decision in self.decisions:
            if not isinstance(decision, dict):
                continue
            if not decision.get("at"):
                decision["at"] = decision.get("created_at") or self._legacy_timestamp_fallback()
            normalized_decisions.append(decision)
        self.decisions = normalized_decisions

    def _normalize_legacy_artifact_timestamps(self) -> None:
        normalized_artifacts: List[Dict[str, Any] | str] = []
        for artifact in self.artifacts:
            if not isinstance(artifact, dict):
                normalized_artifacts.append(artifact)
                continue
            if not artifact.get("created_at"):
                artifact["created_at"] = self._legacy_timestamp_fallback()
            normalized_artifacts.append(artifact)
        self.artifacts = normalized_artifacts

    def _legacy_timestamp_fallback(self) -> str:
        return (
            self.updated_at
            or self.workflow_finished_at
            or self.workflow_last_resumed_at
            or self.workflow_started_at
            or datetime.now(timezone.utc).isoformat()
        )

    def _infer_legacy_skip_reason_types(self) -> None:
        for task in self.tasks:
            if task.status != TaskStatus.SKIPPED.value or task.skip_reason_type is not None:
                continue
            task.skip_reason_type = self._infer_legacy_skip_reason_type(task)

    def _infer_legacy_skip_reason_type(self, task: Task) -> str:
        dependency_id = self._matching_dependency_failed_reason_task_id(task)
        if dependency_id is None:
            return "manual"
        dependency = self.get_task(dependency_id)
        if dependency is None or dependency.status != TaskStatus.FAILED.value:
            return "manual"
        return "dependency_failed"

    def _is_repair_lineage_task(self, task: Task) -> bool:
        return bool(task.repair_origin_task_id) or "__repair_" in task.id

    def _extract_dependency_failed_task_id(self, task: Task) -> Optional[str]:
        reason = task.last_error or task.output or ""
        prefix = "Skipped because dependency '"
        suffix = "' failed"
        if not reason.startswith(prefix) or not reason.endswith(suffix):
            return None
        return reason[len(prefix):-len(suffix)]

    def _depends_on_task(self, task: Task, dependency_id: str) -> bool:
        pending_dependency_ids = list(task.dependencies)
        visited: set[str] = set()

        while pending_dependency_ids:
            current_id = pending_dependency_ids.pop()
            if current_id in visited:
                continue
            if current_id == dependency_id:
                return True
            visited.add(current_id)
            dependency = self.get_task(current_id)
            if dependency is None:
                continue
            pending_dependency_ids.extend(dependency.dependencies)
        return False

    def _matching_dependency_failed_reason_task_id(self, task: Task) -> Optional[str]:
        dependency_id = self._extract_dependency_failed_task_id(task)
        if dependency_id is None:
            return None
        if not self._depends_on_task(task, dependency_id):
            return None
        return dependency_id

    def pending_tasks(self) -> List[Task]:
        """Return all tasks that are still pending execution."""

        return [t for t in self.tasks if t.status == TaskStatus.PENDING.value]

    def execution_plan(self) -> List[Task]:
        """Return tasks in dependency-safe topological execution order."""

        task_by_id = {task.id: task for task in self.tasks}
        indegree: Dict[str, int] = {task.id: 0 for task in self.tasks}
        adjacency: Dict[str, List[str]] = {task.id: [] for task in self.tasks}

        for task in self.tasks:
            for dependency_id in task.dependencies:
                dependency = task_by_id.get(dependency_id)
                if dependency is None:
                    raise WorkflowDefinitionError(
                        f"Task '{task.id}' depends on unknown task '{dependency_id}'"
                    )
                adjacency[dependency_id].append(task.id)
                indegree[task.id] += 1

        queue = deque(task.id for task in self.tasks if indegree[task.id] == 0)
        ordered_ids: List[str] = []

        while queue:
            task_id = queue.popleft()
            ordered_ids.append(task_id)
            for dependent_id in adjacency[task_id]:
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(ordered_ids) != len(self.tasks):
            raise WorkflowDefinitionError("Workflow contains cyclic task dependencies")

        return [task_by_id[task_id] for task_id in ordered_ids]

    def runnable_tasks(self) -> List[Task]:
        """Return pending tasks whose dependencies are already satisfied."""

        if self.is_workflow_paused() or self.is_workflow_cancelled():
            return []
        return [task for task in self.execution_plan() if self.is_task_ready(task)]

    def blocked_tasks(self) -> List[Task]:
        """Return pending tasks that are blocked by unfinished dependencies."""

        return [
            task
            for task in self.execution_plan()
            if task.status == TaskStatus.PENDING.value and not self.is_task_ready(task)
        ]

    def skip_task(self, task_id: str, reason: str, reason_type: str = "manual"):
        """Mark a task skipped and clear stale execution payloads or timing data."""

        task = self.get_task(task_id)
        if task is None:
            return
        skip_reason = _redact_text(reason) if isinstance(reason, str) else ""
        task.status = TaskStatus.SKIPPED.value
        task.last_error = skip_reason
        task.last_error_type = None
        task.last_error_category = None
        task.repair_context = {}
        task.output = skip_reason
        task.output_payload = None
        task.skip_reason_type = reason_type
        task.last_provider_call = None
        task.started_at = None
        task.last_attempt_started_at = None
        task.last_resumed_at = None
        task.completed_at = datetime.now(timezone.utc).isoformat()
        self._record_task_event(task, "skipped", task.completed_at, error_message=skip_reason)
        self._record_execution_event(
            event="task_skipped",
            timestamp=task.completed_at,
            task_id=task.id,
            status=task.status,
            details={"reason": skip_reason},
        )
        self._touch(task.completed_at)

    def override_task(self, task_id: str, output: str | AgentOutput, *, reason: str) -> bool:
        """Mark a task done manually and record the operator override in audit history."""

        task = self.get_task(task_id)
        if task is None:
            return False

        overridden_at = datetime.now(timezone.utc).isoformat()
        override_reason = reason.strip() if isinstance(reason, str) and reason.strip() else "manual_override"
        task.status = TaskStatus.DONE.value
        if isinstance(output, AgentOutput):
            task.output = output.raw_content
            task.output_payload = asdict(output)
        else:
            task.output = output
            task.output_payload = None
        task.last_error = None
        task.last_error_type = None
        task.last_error_category = None
        task.repair_context = {}
        task.skip_reason_type = None
        task.last_provider_call = None
        task.last_resumed_at = overridden_at
        task.completed_at = overridden_at
        self._record_task_event(task, "overridden", overridden_at, error_message=override_reason)
        self._record_execution_event(
            event="task_overridden",
            timestamp=overridden_at,
            task_id=task.id,
            status=task.status,
            details={"reason": override_reason},
        )
        self._touch(overridden_at)
        return True

    def skip_dependent_tasks(self, dependency_id: str, reason: str) -> List[str]:
        """Skip all pending descendants of a failed dependency and return their ids."""

        skipped: List[str] = []
        dependents_map: Dict[str, List[Task]] = {}
        for task in self.tasks:
            for task_dependency_id in task.dependencies:
                dependents_map.setdefault(task_dependency_id, []).append(task)

        queue = deque([dependency_id])
        visited: set[str] = set()
        while queue:
            current_id = queue.popleft()
            for dependent in dependents_map.get(current_id, []):
                if dependent.id in visited:
                    continue
                if dependent.status == TaskStatus.PENDING.value:
                    self.skip_task(dependent.id, reason, reason_type="dependency_failed")
                    skipped.append(dependent.id)
                visited.add(dependent.id)
                queue.append(dependent.id)
        return skipped

    def task_results(self) -> Dict[str, TaskResult]:
        """Return normalized task-result snapshots keyed by task identifier."""

        results: Dict[str, TaskResult] = {}
        for task in self.tasks:
            task_status = self._normalize_task_status(task.status)
            failure = None
            output = None
            resource_telemetry = self._task_resource_telemetry(task)
            public_repair_context = self._public_task_results_repair_context(task.repair_context)
            public_history = self._public_task_history(task.history)
            has_provider_call = isinstance(task.last_provider_call, dict)
            last_error_present = bool(task.last_error or task.last_error_type or task.last_error_category)
            if task_status == TaskStatus.FAILED:
                failure_details: Dict[str, Any] = {
                    "attempts": task.attempts,
                    "retry_limit": task.retry_limit,
                    "error_category": task.last_error_category,
                    "has_provider_call": has_provider_call,
                    "started_at": task.started_at,
                    "last_attempt_started_at": task.last_attempt_started_at,
                    "last_resumed_at": task.last_resumed_at,
                    "task_duration_ms": self._duration_ms(task.started_at, task.completed_at),
                    "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, task.completed_at),
                    "repair_context": public_repair_context,
                    "repair_attempt": task.repair_attempt,
                    "history": public_history,
                }
                if self._identifier_present(task.repair_origin_task_id):
                    failure_details["has_repair_origin"] = True
                failure = FailureRecord(
                    message=_redact_text(task.output or task.last_error or "Task failed without output") or "Task failed without output",
                    error_type=task.last_error_type or "runtime_error",
                    category=task.last_error_category or FailureCategory.UNKNOWN.value,
                    retryable=task.attempts <= task.retry_limit,
                    details=cast(
                        Dict[str, Any],
                        _redact_payload(failure_details),
                    ),
                )
            if task.output or task.output_payload:
                output = self._redacted_agent_output(self._build_agent_output(task))
            public_details: Dict[str, Any] = {
                "attempts": task.attempts,
                "retry_limit": task.retry_limit,
                "required_for_acceptance": task.required_for_acceptance,
                "last_error_present": last_error_present,
                "last_error_category": task.last_error_category,
                "has_provider_call": has_provider_call,
                "repair_context": public_repair_context,
                "repair_attempt": task.repair_attempt,
                "last_attempt_started_at": task.last_attempt_started_at,
                "last_resumed_at": task.last_resumed_at,
                "task_duration_ms": self._duration_ms(task.started_at, task.completed_at),
                "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, task.completed_at),
                "history": public_history,
            }
            if self._identifier_present(task.repair_origin_task_id):
                public_details["has_repair_origin"] = True
            results[task.id] = TaskResult(
                task_id=task.id,
                status=task_status,
                agent_name=task.assigned_to,
                output=output,
                failure=failure,
                resource_telemetry=resource_telemetry,
                details=cast(
                    Dict[str, Any],
                    _redact_payload(public_details),
                ),
                started_at=task.started_at,
                completed_at=task.completed_at,
            )
        return results

    def snapshot(self) -> ProjectSnapshot:
        """Build a normalized project snapshot for downstream orchestration and inspection."""

        self._normalize_legacy_decision_timestamps()
        self._normalize_legacy_artifact_timestamps()
        workflow_telemetry = self._workflow_telemetry_summary()
        public_acceptance_evaluation = cast(
            WorkflowAcceptanceSummary,
            dict(workflow_telemetry["acceptance_summary"]),
        )
        return ProjectSnapshot(
            project_name=_redact_text(self.project_name) or "",
            goal=_redact_text(self.goal) or "",
            workflow_status=self._workflow_status(),
            phase=self.phase,
            acceptance_policy=self.acceptance_policy,
            terminal_outcome=self.terminal_outcome,
            failure_category=self.failure_category,
            acceptance_criteria_met=self.acceptance_criteria_met,
            acceptance_evaluation=public_acceptance_evaluation,
            started_at=self.workflow_started_at,
            finished_at=self.workflow_finished_at,
            last_resumed_at=self.workflow_last_resumed_at,
            repair_cycle_count=self.repair_cycle_count,
            repair_max_cycles=self.repair_max_cycles,
            repair_budget_remaining=max(self.repair_max_cycles - self.repair_cycle_count, 0),
            repair_history=[self._public_repair_history_entry(entry) for entry in self.repair_history if isinstance(entry, dict)],
            task_results=self.task_results(),
            workflow_telemetry=workflow_telemetry,
            decisions=[
                self._redacted_decision_record(
                    DecisionRecord(
                        topic=decision.get("topic", ""),
                        decision=decision.get("decision", ""),
                        rationale=decision.get("rationale", ""),
                        created_at=decision.get("at", self._legacy_timestamp_fallback()),
                        metadata=decision.get("metadata", {}),
                    )
                )
                for decision in self.decisions
            ],
            artifacts=[self._redacted_artifact_record(self._deserialize_artifact_record(artifact)) for artifact in self.artifacts],
            execution_events=[self._redacted_execution_event(event) for event in self.execution_events],
            updated_at=self.updated_at,
        )

    def _touch(self, timestamp: Optional[str] = None):
        self.updated_at = timestamp or datetime.now(timezone.utc).isoformat()

    def _record_task_event(
        self,
        task: Task,
        event: str,
        timestamp: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        task.history.append(
            {
                "event": event,
                "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                "status": task.status,
                "attempts": task.attempts,
                "error_message": _redact_text(error_message),
            }
        )

    def _policy_area_for_category(self, category: Optional[str]) -> Optional[str]:
        if category == FailureCategory.SANDBOX_SECURITY_VIOLATION.value:
            return "sandbox"
        if category == FailureCategory.DEPENDENCY_VALIDATION.value:
            return "dependency_manifest"
        return None

    def _record_policy_enforcement_event(
        self,
        *,
        source_event: str,
        timestamp: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        message: Optional[str] = None,
        error_type: Optional[str] = None,
        provider_call: Optional[Dict[str, Any]] = None,
        retryable: Optional[bool] = None,
        terminal_outcome: Optional[str] = None,
    ) -> None:
        policy_area = self._policy_area_for_category(category)
        if policy_area is None:
            return
        details: Dict[str, Any] = {
            "policy_area": policy_area,
            "source_event": source_event,
            "failure_category": category,
        }
        if message is not None:
            details["message"] = message
        if error_type is not None:
            details["error_type"] = error_type
        if provider_call is not None:
            details["provider_call"] = provider_call
        if retryable is not None:
            details["retryable"] = retryable
        if terminal_outcome is not None:
            details["terminal_outcome"] = terminal_outcome
        self._record_execution_event(
            event="policy_enforcement",
            timestamp=timestamp,
            task_id=task_id,
            status=status,
            details=details,
        )

    def _record_execution_event(
        self,
        event: str,
        timestamp: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        normalized_details = cast(Dict[str, Any], _redact_payload(dict(details or {})))
        if "provider_budget" not in normalized_details:
            normalized_details["provider_budget"] = self._provider_budget_summary(
                normalized_details.get("provider_call")
            )
        self.execution_events.append(
            {
                "event": event,
                "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                "task_id": task_id,
                "status": status,
                "details": normalized_details,
            }
        )

    def _redacted_execution_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        redacted_event = cast(Dict[str, Any], _redact_payload(dict(event)))
        event_name = redacted_event.get("event")
        if event_name == "workflow_resumed":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_resume_details = self._public_workflow_resumed_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_resume_details))
            return redacted_event
        if event_name == "workflow_cancelled":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_cancelled_details = self._public_workflow_cancelled_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_cancelled_details))
            return redacted_event
        if event_name == "workflow_replayed":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_replayed_details = self._public_workflow_replayed_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_replayed_details))
            return redacted_event
        if event_name == "task_repair_planned":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_repair_context = self._public_repair_context(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_repair_context))
            return redacted_event
        if event_name == "task_budget_decomposition_created":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_decomposition_details = self._public_task_budget_decomposition_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_decomposition_details))
            return redacted_event
        if event_name == "task_repair_created":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_repair_created_details = self._public_task_repair_created_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_repair_created_details))
            return redacted_event
        if event_name == "task_requeued":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_requeued_details = self._public_task_requeued_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_requeued_details))
            return redacted_event
        if event_name == "task_started":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_started_details = self._public_task_started_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_started_details))
            return redacted_event
        if event_name == "task_retry_scheduled":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_retry_scheduled_details = self._public_task_retry_scheduled_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_retry_scheduled_details))
            return redacted_event
        if event_name == "task_repair_started":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_repair_started_details = self._public_task_repair_started_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_repair_started_details))
            return redacted_event
        if event_name == "task_repair_retry_scheduled":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_repair_failure_details = self._public_task_repair_failure_details(
                details,
                minimize_error_type=True,
            )
            details.clear()
            details.update(cast(Dict[str, Any], public_repair_failure_details))
            return redacted_event
        if event_name == "task_repair_failed":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_repair_failure_details = self._public_task_repair_failure_details(
                details,
                minimize_error_type=True,
            )
            details.clear()
            details.update(cast(Dict[str, Any], public_repair_failure_details))
            return redacted_event
        if event_name == "task_repaired":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_repaired_details = self._public_task_repaired_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_repaired_details))
            return redacted_event
        if event_name == "workflow_progress":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_progress_details = self._public_workflow_progress_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_progress_details))
            return redacted_event
        if event_name == "workflow_repair_cycle_started":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_repair_details = self._public_repair_history_entry(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_repair_details))
            return redacted_event
        if event_name == "task_completed":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_task_completed_details = self._public_task_completed_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_task_completed_details))
            return redacted_event
        if event_name == "task_failed":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_task_failed_details = self._public_task_failed_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_task_failed_details))
            return redacted_event
        if event_name == "policy_enforcement":
            details = redacted_event.get("details")
            if not isinstance(details, dict):
                return redacted_event
            public_policy_details = self._public_policy_enforcement_details(details)
            details.clear()
            details.update(cast(Dict[str, Any], public_policy_details))
            return redacted_event
        if event_name != "workflow_finished":
            return redacted_event
        details = redacted_event.get("details")
        if not isinstance(details, dict):
            return redacted_event
        public_finished_details = self._public_workflow_finished_details(details)
        details.clear()
        details.update(cast(Dict[str, Any], public_finished_details))
        return redacted_event

    def _provider_budget_summary(
        self,
        provider_call: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(provider_call, dict):
            return None
        sanitized_provider_call = sanitize_provider_call_metadata(provider_call)
        return {
            "call_budget_limited": bool(sanitized_provider_call.get("provider_call_budget_limited")),
            "call_budget_exhausted": bool(
                sanitized_provider_call.get("provider_call_budget_exhausted")
            ),
            "limited_providers": list(
                sanitized_provider_call.get("provider_call_budget_limited_providers") or []
            ),
            "exhausted_providers": list(
                sanitized_provider_call.get("provider_call_budget_exhausted_providers") or []
            ),
        }

    def _workflow_telemetry_summary(self) -> WorkflowTelemetry:
        task_status_counts: Dict[str, int] = {}
        tasks_with_provider_calls = 0
        final_providers: set[str] = set()
        observed_providers: set[str] = set()
        provider_summary: Dict[str, Dict[str, Any]] = {}
        provider_health_summary: Dict[str, Dict[str, Any]] = {}
        usage_totals: Dict[str, float] = {}
        duration_values: List[float] = []
        attempt_count = 0
        retry_attempt_count = 0
        fallback_task_count = 0
        fallback_entry_count = 0
        fallback_providers: set[str] = set()
        fallback_statuses: set[str] = set()
        final_error_count = 0
        fallback_error_count = 0

        for task in self.tasks:
            task_status_counts[task.status] = task_status_counts.get(task.status, 0) + 1
            provider_call = task.last_provider_call
            if not isinstance(provider_call, dict):
                continue
            tasks_with_provider_calls += 1

            provider_name = provider_call.get("provider")
            summary_for_provider: Optional[Dict[str, Any]] = None
            if isinstance(provider_name, str) and provider_name:
                final_providers.add(provider_name)
                observed_providers.add(provider_name)
                summary_for_provider = provider_summary.setdefault(
                    provider_name,
                    {
                        "task_count": 0,
                        "success_count": 0,
                        "failure_count": 0,
                        "attempt_count": 0,
                        "retry_attempt_count": 0,
                        "duration_values": [],
                        "usage": {},
                    },
                )
                summary_for_provider["task_count"] += 1
                if provider_call.get("success") is True:
                    summary_for_provider["success_count"] += 1
                elif provider_call.get("success") is False:
                    summary_for_provider["failure_count"] += 1

            attempts_used = self._provider_attempt_count(provider_call)
            attempt_count += attempts_used
            if summary_for_provider is not None:
                summary_for_provider["attempt_count"] += attempts_used

            retry_attempts = self._provider_retry_attempt_count(provider_call, attempts_used)
            retry_attempt_count += retry_attempts
            if summary_for_provider is not None:
                summary_for_provider["retry_attempt_count"] += retry_attempts

            duration_ms = self._provider_call_duration_ms(provider_call)
            if duration_ms is not None:
                duration_values.append(duration_ms)
                if summary_for_provider is not None:
                    summary_for_provider["duration_values"].append(duration_ms)

            usage = provider_call.get("usage")
            if isinstance(usage, dict):
                self._accumulate_numeric_metrics(usage_totals, usage)
                if summary_for_provider is not None:
                    self._accumulate_numeric_metrics(summary_for_provider["usage"], usage)

            raw_provider_health = provider_call.get("provider_health")
            if isinstance(raw_provider_health, dict):
                for health_provider_name, raw_health_entry in raw_provider_health.items():
                    if not isinstance(health_provider_name, str) or not health_provider_name:
                        continue
                    if not isinstance(raw_health_entry, dict):
                        continue
                    health_summary = provider_health_summary.setdefault(
                        health_provider_name,
                        {
                            "models": set(),
                            "status_counts": {},
                            "last_outcome_counts": {},
                            "circuit_open_count": 0,
                            "retryable_failure_count": 0,
                            "active_health_check_count": 0,
                        },
                    )
                    model_name = raw_health_entry.get("model")
                    if isinstance(model_name, str) and model_name:
                        health_summary["models"].add(model_name)
                    health_status = raw_health_entry.get("status")
                    if isinstance(health_status, str) and health_status:
                        health_summary["status_counts"][health_status] = (
                            health_summary["status_counts"].get(health_status, 0) + 1
                        )
                    last_outcome = raw_health_entry.get("last_outcome")
                    if isinstance(last_outcome, str) and last_outcome:
                        health_summary["last_outcome_counts"][last_outcome] = (
                            health_summary["last_outcome_counts"].get(last_outcome, 0) + 1
                        )
                    if _provider_health_entry_has_open_circuit(raw_health_entry):
                        health_summary["circuit_open_count"] += 1
                    if _provider_health_entry_has_retryable_failure(raw_health_entry):
                        health_summary["retryable_failure_count"] += 1
                    last_health_check = raw_health_entry.get("last_health_check")
                    if (
                        isinstance(last_health_check, dict)
                        and last_health_check.get("active_check") is True
                        and last_health_check.get("cooldown_cached") is not True
                    ):
                        health_summary["active_health_check_count"] += 1

            if provider_call.get("success") is False:
                error_type = provider_call.get("error_type")
                if (
                    (isinstance(error_type, str) and error_type)
                    or provider_call.get("has_error_type") is True
                ):
                    final_error_count += 1

            fallback_history = provider_call.get("fallback_history")
            if not isinstance(fallback_history, list) or not fallback_history:
                continue
            fallback_task_count += 1
            fallback_entry_count += len(fallback_history)
            for entry in fallback_history:
                if not isinstance(entry, dict):
                    continue
                fallback_provider = entry.get("provider")
                if isinstance(fallback_provider, str) and fallback_provider:
                    observed_providers.add(fallback_provider)
                    fallback_providers.add(fallback_provider)
                fallback_status = entry.get("status")
                if isinstance(fallback_status, str) and fallback_status:
                    fallback_statuses.add(fallback_status)
                fallback_error_type = entry.get("error_type")
                if (
                    (isinstance(fallback_error_type, str) and fallback_error_type)
                    or entry.get("has_error_type") is True
                ):
                    fallback_error_count += 1

        normalized_provider_summary: Dict[str, WorkflowProviderSummary] = {}
        for provider_name in sorted(provider_summary):
            raw_summary = provider_summary[provider_name]
            raw_duration_series = raw_summary.get("duration_values")
            duration_series = [
                float(value)
                for value in raw_duration_series
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ] if isinstance(raw_duration_series, list) else []
            usage_metrics: Dict[str, float] = {}
            raw_usage_metrics = raw_summary.get("usage")
            if isinstance(raw_usage_metrics, dict):
                for metric_name, metric_value in raw_usage_metrics.items():
                    if not isinstance(metric_name, str):
                        continue
                    if not isinstance(metric_value, (int, float)) or isinstance(metric_value, bool):
                        continue
                    usage_metrics[metric_name] = float(metric_value)
            normalized_provider_summary[provider_name] = {
                "task_count": int(raw_summary.get("task_count", 0)),
                "success_count": int(raw_summary.get("success_count", 0)),
                "failure_count": int(raw_summary.get("failure_count", 0)),
                "attempt_count": int(raw_summary.get("attempt_count", 0)),
                "retry_attempt_count": int(raw_summary.get("retry_attempt_count", 0)),
                "duration_ms": self._metric_distribution(duration_series),
                "usage": self._sorted_numeric_metrics(usage_metrics),
            }

        normalized_provider_health_summary: Dict[str, WorkflowProviderHealthSummary] = {}
        for provider_name in sorted(provider_health_summary):
            raw_health_summary = provider_health_summary[provider_name]
            raw_models = raw_health_summary.get("models")
            normalized_provider_health_summary[provider_name] = {
                "models": sorted(raw_models) if isinstance(raw_models, set) else [],
                "status_counts": dict(sorted(raw_health_summary.get("status_counts", {}).items())),
                "last_outcome_counts": dict(sorted(raw_health_summary.get("last_outcome_counts", {}).items())),
                "circuit_open_count": int(raw_health_summary.get("circuit_open_count", 0)),
                "retryable_failure_count": int(raw_health_summary.get("retryable_failure_count", 0)),
                "active_health_check_count": int(raw_health_summary.get("active_health_check_count", 0)),
            }

        return {
            "task_count": len(self.tasks),
            "task_status_counts": self._ordered_task_status_counts(task_status_counts),
            "progress_summary": self._progress_summary(task_status_counts),
            "tasks_with_provider_calls": tasks_with_provider_calls,
            "tasks_without_provider_calls": max(len(self.tasks) - tasks_with_provider_calls, 0),
            "acceptance_summary": self._acceptance_summary(),
            "resume_summary": self._resume_summary(),
            "repair_summary": self._repair_summary(),
            "final_provider_count": len(final_providers),
            "observed_provider_count": len(observed_providers),
            "provider_summary": normalized_provider_summary,
            "provider_health_summary": normalized_provider_health_summary,
            "attempt_count": attempt_count,
            "retry_attempt_count": retry_attempt_count,
            "duration_ms": self._metric_distribution(duration_values),
            "usage": self._sorted_numeric_metrics(usage_totals),
            "fallback_summary": {
                "task_count": fallback_task_count,
                "entry_count": fallback_entry_count,
                "provider_count": len(fallback_providers),
                "status_count": len(fallback_statuses),
            },
            "error_summary": {
                "final_error_count": final_error_count,
                "fallback_error_count": fallback_error_count,
            },
        }

    def _progress_summary(self, task_status_counts: Dict[str, int]) -> WorkflowProgressSummary:
        total_task_count = len(self.tasks)
        pending_task_count = task_status_counts.get(TaskStatus.PENDING.value, 0)
        running_task_count = task_status_counts.get(TaskStatus.RUNNING.value, 0)
        terminal_task_count = sum(
            task_status_counts.get(status.value, 0)
            for status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.SKIPPED)
        )
        try:
            runnable_task_count = len(self.runnable_tasks())
            blocked_task_count = len(self.blocked_tasks())
        except WorkflowDefinitionError:
            runnable_task_count = 0
            blocked_task_count = pending_task_count
        completion_percent = (
            self._normalize_metric_number((terminal_task_count / total_task_count) * 100.0)
            if total_task_count > 0
            else 0
        )
        return {
            "pending_task_count": pending_task_count,
            "running_task_count": running_task_count,
            "runnable_task_count": runnable_task_count,
            "blocked_task_count": blocked_task_count,
            "terminal_task_count": terminal_task_count,
            "completion_percent": completion_percent,
        }

    def _acceptance_summary(self) -> WorkflowAcceptanceSummary:
        return self._public_acceptance_evaluation(
            self.acceptance_evaluation,
            acceptance_policy=self.acceptance_policy,
            acceptance_criteria_met=self.acceptance_criteria_met,
            terminal_outcome=self.terminal_outcome,
            failure_category=self.failure_category,
        )

    def _public_acceptance_evaluation(
        self,
        acceptance_evaluation: Any,
        *,
        acceptance_policy: Any,
        acceptance_criteria_met: Any,
        terminal_outcome: Any,
        failure_category: Any,
    ) -> WorkflowAcceptanceSummary:
        normalized_evaluation = acceptance_evaluation if isinstance(acceptance_evaluation, dict) else {}
        policy = acceptance_policy if isinstance(acceptance_policy, str) and acceptance_policy else None
        if policy is None:
            raw_policy = normalized_evaluation.get("policy")
            policy = raw_policy if isinstance(raw_policy, str) and raw_policy else None
        accepted = acceptance_criteria_met if isinstance(acceptance_criteria_met, bool) else False
        if not isinstance(acceptance_criteria_met, bool):
            raw_accepted = normalized_evaluation.get("accepted")
            accepted = raw_accepted if isinstance(raw_accepted, bool) else False
        outcome = terminal_outcome if isinstance(terminal_outcome, str) and terminal_outcome else None
        if outcome is None:
            raw_outcome = normalized_evaluation.get("terminal_outcome")
            outcome = raw_outcome if isinstance(raw_outcome, str) and raw_outcome else None
        category = failure_category if isinstance(failure_category, str) and failure_category else None
        if category is None:
            raw_category = normalized_evaluation.get("failure_category")
            category = raw_category if isinstance(raw_category, str) and raw_category else None
        return {
            "policy": policy,
            "accepted": accepted,
            "reason": normalized_evaluation.get("reason") if isinstance(normalized_evaluation.get("reason"), str) else None,
            "terminal_outcome": outcome,
            "failure_category": category,
            "evaluated_task_count": self._acceptance_task_count(normalized_evaluation, "evaluated_task_ids", "evaluated_task_count"),
            "required_task_count": self._acceptance_task_count(normalized_evaluation, "required_task_ids", "required_task_count"),
            "completed_task_count": self._acceptance_task_count(normalized_evaluation, "completed_task_ids", "completed_task_count"),
            "failed_task_count": self._acceptance_task_count(normalized_evaluation, "failed_task_ids", "failed_task_count"),
            "skipped_task_count": self._acceptance_task_count(normalized_evaluation, "skipped_task_ids", "skipped_task_count"),
            "pending_task_count": self._acceptance_task_count(normalized_evaluation, "pending_task_ids", "pending_task_count"),
        }

    def _resume_summary(self) -> WorkflowResumeSummary:
        resumed_events = [
            event for event in self.execution_events
            if isinstance(event, dict) and event.get("event") == "workflow_resumed"
        ]
        reasons: set[str] = set()
        resumed_task_ids: List[str] = []
        for event in resumed_events:
            raw_details = event.get("details")
            details: Dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
            reason = details.get("reason")
            if isinstance(reason, str) and reason:
                reasons.add(reason)
            resumed_task_ids.extend(self._string_list(details.get("task_ids")))
        unique_task_count = len(set(resumed_task_ids))
        return {
            "count": len(resumed_events),
            "reason_count": len(reasons),
            "task_count": len(resumed_task_ids),
            "unique_task_count": unique_task_count,
            "last_resumed_at": self.workflow_last_resumed_at,
        }

    def _repair_summary(self) -> WorkflowRepairSummary:
        reasons: set[str] = set()
        last_reason_present = False
        failure_categories: set[str] = set()
        failed_task_ids: set[str] = set()
        for entry in self.repair_history:
            if not isinstance(entry, dict):
                continue
            reason = entry.get("reason")
            if isinstance(reason, str) and reason:
                reasons.add(reason)
                last_reason_present = True
            failure_category = entry.get("failure_category")
            if isinstance(failure_category, str) and failure_category:
                failure_categories.add(failure_category)
            failed_task_ids.update(self._string_list(entry.get("failed_task_ids")))
        return {
            "cycle_count": self.repair_cycle_count,
            "max_cycles": self.repair_max_cycles,
            "budget_remaining": max(self.repair_max_cycles - self.repair_cycle_count, 0),
            "history_count": len([entry for entry in self.repair_history if isinstance(entry, dict)]),
            "reason_count": len(reasons),
            "last_reason_present": last_reason_present,
            "failure_category_count": len(failure_categories),
            "failed_task_count": len(failed_task_ids),
        }

    def _public_repair_history_entry(self, entry: Dict[str, Any]) -> WorkflowRepairHistoryEntry:
        started_at = entry.get("started_at") if isinstance(entry.get("started_at"), str) else None
        reason = entry.get("reason") if isinstance(entry.get("reason"), str) else None
        failure_category = entry.get("failure_category") if isinstance(entry.get("failure_category"), str) else None
        cycle = entry.get("cycle")
        budget_remaining = entry.get("budget_remaining")
        return {
            "cycle": max(int(cycle), 0) if isinstance(cycle, (int, float)) and not isinstance(cycle, bool) else 0,
            "started_at": started_at,
            "reason": reason,
            "failure_category": failure_category,
            "failed_task_count": self._repair_history_failed_task_count(entry),
            "budget_remaining": max(int(budget_remaining), 0) if isinstance(budget_remaining, (int, float)) and not isinstance(budget_remaining, bool) else 0,
        }

    def _public_workflow_resumed_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        reason = details.get("reason") if isinstance(details.get("reason"), str) else None
        task_ids = self._string_list(details.get("task_ids"))
        if task_ids:
            task_count = len(task_ids)
            unique_task_count = len(set(task_ids))
        else:
            raw_task_count = details.get("task_count")
            task_count = (
                max(int(raw_task_count), 0)
                if isinstance(raw_task_count, (int, float)) and not isinstance(raw_task_count, bool)
                else 0
            )
            raw_unique_task_count = details.get("unique_task_count")
            unique_task_count = (
                max(int(raw_unique_task_count), 0)
                if isinstance(raw_unique_task_count, (int, float)) and not isinstance(raw_unique_task_count, bool)
                else task_count
            )
            if unique_task_count > task_count:
                unique_task_count = task_count
        return {
            "reason": reason,
            "task_count": task_count,
            "unique_task_count": unique_task_count,
        }

    def _public_workflow_cancelled_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        reason = details.get("reason") if isinstance(details.get("reason"), str) else None
        terminal_outcome = details.get("terminal_outcome") if isinstance(details.get("terminal_outcome"), str) else None
        cancelled_task_ids = self._string_list(details.get("cancelled_task_ids"))
        if cancelled_task_ids:
            cancelled_task_count = len(cancelled_task_ids)
        else:
            raw_cancelled_task_count = details.get("cancelled_task_count")
            cancelled_task_count = (
                max(int(raw_cancelled_task_count), 0)
                if isinstance(raw_cancelled_task_count, (int, float)) and not isinstance(raw_cancelled_task_count, bool)
                else 0
            )
        return {
            "reason": reason,
            "terminal_outcome": terminal_outcome,
            "cancelled_task_count": cancelled_task_count,
        }

    def _public_workflow_replayed_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        reason = details.get("reason") if isinstance(details.get("reason"), str) else None
        replayed_task_ids = self._string_list(details.get("replayed_task_ids"))
        removed_task_ids = self._string_list(details.get("removed_task_ids"))
        if replayed_task_ids:
            replayed_task_count = len(replayed_task_ids)
        else:
            raw_replayed_task_count = details.get("replayed_task_count")
            replayed_task_count = (
                max(int(raw_replayed_task_count), 0)
                if isinstance(raw_replayed_task_count, (int, float)) and not isinstance(raw_replayed_task_count, bool)
                else 0
            )
        if removed_task_ids:
            removed_task_count = len(removed_task_ids)
        else:
            raw_removed_task_count = details.get("removed_task_count")
            removed_task_count = (
                max(int(raw_removed_task_count), 0)
                if isinstance(raw_removed_task_count, (int, float)) and not isinstance(raw_removed_task_count, bool)
                else 0
            )
        cleared_decision_count = details.get("cleared_decision_count")
        cleared_artifact_count = details.get("cleared_artifact_count")
        return {
            "reason": reason,
            "replayed_task_count": replayed_task_count,
            "removed_task_count": removed_task_count,
            "cleared_decision_count": (
                max(int(cleared_decision_count), 0)
                if isinstance(cleared_decision_count, (int, float)) and not isinstance(cleared_decision_count, bool)
                else 0
            ),
            "cleared_artifact_count": (
                max(int(cleared_artifact_count), 0)
                if isinstance(cleared_artifact_count, (int, float)) and not isinstance(cleared_artifact_count, bool)
                else 0
            ),
        }

    def _public_task_completed_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        public_details = cast(Dict[str, Any], _redact_payload(dict(details)))

        if self._presence_flag(details, "assigned_to", "has_assigned_to"):
            public_details["has_assigned_to"] = True
        public_details.pop("assigned_to", None)

        if isinstance(details.get("provider_call"), dict) or public_details.get("has_provider_call") is True:
            public_details["has_provider_call"] = True
        public_details.pop("provider_call", None)
        return public_details

    def _public_task_history_entry(self, entry: Any) -> Dict[str, Any]:
        if not isinstance(entry, dict):
            return {}

        public_entry: Dict[str, Any] = {
            "event": entry.get("event"),
            "timestamp": entry.get("timestamp"),
            "status": entry.get("status"),
        }

        raw_attempts = entry.get("attempts")
        if (
            (isinstance(raw_attempts, (int, float)) and not isinstance(raw_attempts, bool) and bool(int(raw_attempts)))
            or entry.get("has_attempts") is True
        ):
            public_entry["has_attempts"] = True

        raw_error_message = entry.get("error_message")
        if (isinstance(raw_error_message, str) and bool(raw_error_message)) or entry.get("has_error_message") is True:
            public_entry["has_error_message"] = True

        return cast(Dict[str, Any], _redact_payload(public_entry))

    def _public_task_history(self, history: Any) -> List[Dict[str, Any]]:
        if not isinstance(history, list):
            return []

        public_history: List[Dict[str, Any]] = []
        for entry in history:
            public_entry = self._public_task_history_entry(entry)
            if public_entry:
                public_history.append(public_entry)
        return public_history

    def _public_task_failed_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        public_details = cast(Dict[str, Any], _redact_payload(dict(details)))

        raw_error_message = details.get("error_message")
        if (isinstance(raw_error_message, str) and bool(raw_error_message)) or public_details.get("has_error_message") is True:
            public_details["has_error_message"] = True
        public_details.pop("error_message", None)

        raw_error_type = details.get("error_type")
        if (isinstance(raw_error_type, str) and bool(raw_error_type)) or public_details.get("has_error_type") is True:
            public_details["has_error_type"] = True
        public_details.pop("error_type", None)

        if isinstance(details.get("provider_call"), dict) or public_details.get("has_provider_call") is True:
            public_details["has_provider_call"] = True
        public_details.pop("provider_call", None)
        return public_details

    def _public_task_retry_scheduled_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        public_details = cast(Dict[str, Any], _redact_payload(dict(details)))

        raw_error_type = details.get("error_type")
        if (isinstance(raw_error_type, str) and bool(raw_error_type)) or public_details.get("has_error_type") is True:
            public_details["has_error_type"] = True
        public_details.pop("error_type", None)

        if isinstance(details.get("provider_call"), dict) or public_details.get("has_provider_call") is True:
            public_details["has_provider_call"] = True
        public_details.pop("provider_call", None)
        return public_details

    def _public_policy_enforcement_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        public_details = cast(Dict[str, Any], _redact_payload(dict(details)))

        raw_message = details.get("message")
        if (isinstance(raw_message, str) and bool(raw_message)) or public_details.get("has_message") is True:
            public_details["has_message"] = True
        public_details.pop("message", None)

        raw_error_type = details.get("error_type")
        if (isinstance(raw_error_type, str) and bool(raw_error_type)) or public_details.get("has_error_type") is True:
            public_details["has_error_type"] = True
        public_details.pop("error_type", None)

        if isinstance(details.get("provider_call"), dict) or public_details.get("has_provider_call") is True:
            public_details["has_provider_call"] = True
        public_details.pop("provider_call", None)
        return public_details

    def _public_workflow_progress_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        public_details = cast(Dict[str, Any], _redact_payload(dict(details)))

        if isinstance(details.get("workflow_telemetry"), dict) or public_details.get("has_workflow_telemetry") is True:
            public_details["has_workflow_telemetry"] = True
        public_details.pop("workflow_telemetry", None)
        public_details.pop("provider_budget", None)
        return public_details

    def _public_workflow_finished_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        public_details = cast(Dict[str, Any], _redact_payload(dict(details)))
        workflow_telemetry = public_details.get("workflow_telemetry")
        if isinstance(workflow_telemetry, dict):
            acceptance_summary = workflow_telemetry.get("acceptance_summary")
            if isinstance(acceptance_summary, dict):
                public_details["acceptance_evaluation"] = cast(Dict[str, Any], _redact_payload(dict(acceptance_summary)))
            else:
                public_details["acceptance_evaluation"] = cast(
                    Dict[str, Any],
                    self._public_acceptance_evaluation(
                        public_details.get("acceptance_evaluation"),
                        acceptance_policy=public_details.get("acceptance_policy"),
                        acceptance_criteria_met=public_details.get("acceptance_criteria_met"),
                        terminal_outcome=public_details.get("terminal_outcome"),
                        failure_category=public_details.get("failure_category"),
                    ),
                )
        else:
            public_details["acceptance_evaluation"] = cast(
                Dict[str, Any],
                self._public_acceptance_evaluation(
                    public_details.get("acceptance_evaluation"),
                    acceptance_policy=public_details.get("acceptance_policy"),
                    acceptance_criteria_met=public_details.get("acceptance_criteria_met"),
                    terminal_outcome=public_details.get("terminal_outcome"),
                    failure_category=public_details.get("failure_category"),
                ),
            )

        if self._presence_flag(details, "failure_task_id", "has_failure_task"):
            public_details["has_failure_task"] = True
        public_details.pop("failure_task_id", None)

        raw_failure_message = details.get("failure_message")
        if (isinstance(raw_failure_message, str) and bool(raw_failure_message)) or public_details.get("has_failure_message") is True:
            public_details["has_failure_message"] = True
        public_details.pop("failure_message", None)

        raw_failure_error_type = details.get("failure_error_type")
        if (isinstance(raw_failure_error_type, str) and bool(raw_failure_error_type)) or public_details.get("has_failure_error_type") is True:
            public_details["has_failure_error_type"] = True
        public_details.pop("failure_error_type", None)

        if isinstance(details.get("provider_call"), dict) or public_details.get("has_provider_call") is True:
            public_details["has_provider_call"] = True
        public_details.pop("provider_call", None)
        return public_details

    def _identifier_present(self, value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def _presence_flag(self, details: Dict[str, Any], identifier_key: str, flag_key: str) -> bool:
        if self._identifier_present(details.get(identifier_key)):
            return True
        raw_flag = details.get(flag_key)
        return raw_flag is True

    def _public_task_results_repair_context(self, repair_context: Any) -> Dict[str, Any]:
        raw_context = repair_context if isinstance(repair_context, dict) else {}
        public_context = self._public_repair_context(raw_context)

        raw_failed_artifact_content = raw_context.get("failed_artifact_content")
        if (
            isinstance(raw_failed_artifact_content, str)
            and bool(raw_failed_artifact_content.strip())
        ) or raw_context.get("has_failed_artifact_content") is True:
            public_context["has_failed_artifact_content"] = True
        public_context.pop("failed_artifact_content", None)

        raw_validation_summary = raw_context.get("validation_summary")
        if (
            isinstance(raw_validation_summary, str)
            and bool(raw_validation_summary.strip())
        ) or raw_context.get("has_validation_summary") is True:
            public_context["has_validation_summary"] = True
        public_context.pop("validation_summary", None)

        raw_existing_tests = raw_context.get("existing_tests")
        if (
            isinstance(raw_existing_tests, str)
            and bool(raw_existing_tests.strip())
        ) or raw_context.get("has_existing_tests") is True:
            public_context["has_existing_tests"] = True
        public_context.pop("existing_tests", None)

        raw_instruction = raw_context.get("instruction")
        if (
            isinstance(raw_instruction, str)
            and bool(raw_instruction.strip())
        ) or raw_context.get("has_instruction") is True:
            public_context["has_instruction"] = True
        public_context.pop("instruction", None)

        raw_repair_owner = raw_context.get("repair_owner")
        if (
            isinstance(raw_repair_owner, str)
            and bool(raw_repair_owner.strip())
        ) or raw_context.get("has_repair_owner") is True:
            public_context["has_repair_owner"] = True
        public_context.pop("repair_owner", None)

        raw_original_assigned_to = raw_context.get("original_assigned_to")
        if (
            isinstance(raw_original_assigned_to, str)
            and bool(raw_original_assigned_to.strip())
        ) or raw_context.get("has_original_assigned_to") is True:
            public_context["has_original_assigned_to"] = True
        public_context.pop("original_assigned_to", None)

        raw_helper_surface_usages = raw_context.get("helper_surface_usages")
        if (
            isinstance(raw_helper_surface_usages, list)
            and any(isinstance(item, str) and bool(item.strip()) for item in raw_helper_surface_usages)
        ) or raw_context.get("has_helper_surface_usages") is True:
            public_context["has_helper_surface_usages"] = True
        public_context.pop("helper_surface_usages", None)

        raw_helper_surface_symbols = raw_context.get("helper_surface_symbols")
        if (
            isinstance(raw_helper_surface_symbols, list)
            and any(isinstance(item, str) and bool(item.strip()) for item in raw_helper_surface_symbols)
        ) or raw_context.get("has_helper_surface_symbols") is True:
            public_context["has_helper_surface_symbols"] = True
        public_context.pop("helper_surface_symbols", None)

        raw_decomposition_mode = raw_context.get("decomposition_mode")
        if (
            isinstance(raw_decomposition_mode, str)
            and bool(raw_decomposition_mode.strip())
        ) or raw_context.get("has_decomposition_mode") is True:
            public_context["has_decomposition_mode"] = True
        public_context.pop("decomposition_mode", None)

        raw_decomposition_target_agent = raw_context.get("decomposition_target_agent")
        if (
            isinstance(raw_decomposition_target_agent, str)
            and bool(raw_decomposition_target_agent.strip())
        ) or raw_context.get("has_decomposition_target_agent") is True:
            public_context["has_decomposition_target_agent"] = True
        public_context.pop("decomposition_target_agent", None)

        raw_decomposition_failure_category = raw_context.get("decomposition_failure_category")
        if (
            isinstance(raw_decomposition_failure_category, str)
            and bool(raw_decomposition_failure_category.strip())
        ) or raw_context.get("has_decomposition_failure_category") is True:
            public_context["has_decomposition_failure_category"] = True
        public_context.pop("decomposition_failure_category", None)

        raw_failure_message = raw_context.get("failure_message")
        if (
            isinstance(raw_failure_message, str)
            and bool(raw_failure_message.strip())
        ) or raw_context.get("has_failure_message") is True:
            public_context["has_failure_message"] = True
        public_context.pop("failure_message", None)

        raw_failure_error_type = raw_context.get("failure_error_type")
        if (
            isinstance(raw_failure_error_type, str)
            and bool(raw_failure_error_type.strip())
        ) or raw_context.get("has_failure_error_type") is True:
            public_context["has_failure_error_type"] = True
        public_context.pop("failure_error_type", None)

        raw_failed_output = raw_context.get("failed_output")
        if (
            isinstance(raw_failed_output, str)
            and bool(raw_failed_output.strip())
        ) or raw_context.get("has_failed_output") is True:
            public_context["has_failed_output"] = True
        public_context.pop("failed_output", None)

        return public_context

    def _public_repair_context(self, repair_context: Any) -> Dict[str, Any]:
        raw_context = repair_context if isinstance(repair_context, dict) else {}
        public_context = cast(Dict[str, Any], _redact_payload(dict(raw_context)))

        if self._presence_flag(raw_context, "source_failure_task_id", "has_source_failure_task"):
            public_context["has_source_failure_task"] = True
        public_context.pop("source_failure_task_id", None)

        if self._presence_flag(raw_context, "budget_decomposition_plan_task_id", "has_budget_decomposition_plan"):
            public_context["has_budget_decomposition_plan"] = True
        public_context.pop("budget_decomposition_plan_task_id", None)

        if self._presence_flag(raw_context, "decomposition_target_task_id", "has_decomposition_target_task"):
            public_context["has_decomposition_target_task"] = True
        public_context.pop("decomposition_target_task_id", None)

        if isinstance(raw_context.get("provider_call"), dict) or raw_context.get("has_provider_call") is True:
            public_context["has_provider_call"] = True
        public_context.pop("provider_call", None)
        public_context.pop("provider_budget", None)

        return public_context

    def _public_task_budget_decomposition_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        raw_repair_attempt = details.get("repair_attempt")
        public_details: Dict[str, Any] = {
            "repair_attempt": (
                max(int(raw_repair_attempt), 0)
                if isinstance(raw_repair_attempt, (int, float)) and not isinstance(raw_repair_attempt, bool)
                else 0
            ),
        }
        if self._presence_flag(details, "assigned_to", "has_assigned_to"):
            public_details["has_assigned_to"] = True
        if self._presence_flag(details, "decomposition_target_task_id", "has_decomposition_target_task"):
            public_details["has_decomposition_target_task"] = True
        return public_details

    def _public_task_repair_created_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        raw_repair_attempt = details.get("repair_attempt")
        public_details: Dict[str, Any] = {
            "repair_attempt": (
                max(int(raw_repair_attempt), 0)
                if isinstance(raw_repair_attempt, (int, float)) and not isinstance(raw_repair_attempt, bool)
                else 0
            ),
        }
        if self._presence_flag(details, "assigned_to", "has_assigned_to"):
            public_details["has_assigned_to"] = True
        if self._presence_flag(details, "repair_origin_task_id", "has_repair_origin"):
            public_details["has_repair_origin"] = True
        return public_details

    def _public_task_requeued_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        public_details: Dict[str, Any] = {
            "reason": details.get("reason") if isinstance(details.get("reason"), str) else None,
        }
        if self._presence_flag(details, "repair_task_id", "has_repair_task"):
            public_details["has_repair_task"] = True
        return public_details

    def _public_task_started_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        public_details = cast(Dict[str, Any], _redact_payload(dict(details)))

        if self._presence_flag(details, "assigned_to", "has_assigned_to"):
            public_details["has_assigned_to"] = True
        public_details.pop("assigned_to", None)
        public_details.pop("provider_budget", None)
        return public_details

    def _public_task_repair_started_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        raw_repair_attempt = details.get("repair_attempt")
        public_details: Dict[str, Any] = {
            "repair_attempt": (
                max(int(raw_repair_attempt), 0)
                if isinstance(raw_repair_attempt, (int, float)) and not isinstance(raw_repair_attempt, bool)
                else 0
            ),
        }
        if self._presence_flag(details, "assigned_to", "has_assigned_to"):
            public_details["has_assigned_to"] = True
        if self._presence_flag(details, "repair_task_id", "has_repair_task"):
            public_details["has_repair_task"] = True
        return public_details

    def _public_task_repair_failure_details(
        self,
        details: Dict[str, Any],
        *,
        minimize_error_type: bool,
    ) -> Dict[str, Any]:
        raw_repair_attempt = details.get("repair_attempt")
        public_details: Dict[str, Any] = {
            "repair_attempt": (
                max(int(raw_repair_attempt), 0)
                if isinstance(raw_repair_attempt, (int, float)) and not isinstance(raw_repair_attempt, bool)
                else 0
            ),
            "error_category": details.get("error_category") if isinstance(details.get("error_category"), str) else None,
        }
        if minimize_error_type:
            if self._presence_flag(details, "error_type", "has_error_type"):
                public_details["has_error_type"] = True
        else:
            public_details["error_type"] = details.get("error_type") if isinstance(details.get("error_type"), str) else None
        if self._presence_flag(details, "repair_task_id", "has_repair_task"):
            public_details["has_repair_task"] = True
        return public_details

    def _public_task_repaired_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        raw_repair_attempt = details.get("repair_attempt")
        public_details: Dict[str, Any] = {
            "repair_attempt": (
                max(int(raw_repair_attempt), 0)
                if isinstance(raw_repair_attempt, (int, float)) and not isinstance(raw_repair_attempt, bool)
                else 0
            ),
        }
        if self._presence_flag(details, "assigned_to", "has_assigned_to"):
            public_details["has_assigned_to"] = True
        if self._presence_flag(details, "repair_task_id", "has_repair_task"):
            public_details["has_repair_task"] = True
        return public_details

    def _list_like_values(self, value: Any) -> List[Any]:
        if not isinstance(value, list):
            return []
        return list(value)

    def _acceptance_task_count(self, acceptance_evaluation: Dict[str, Any], task_ids_key: str, count_key: str) -> int:
        task_ids = self._list_like_values(acceptance_evaluation.get(task_ids_key))
        if task_ids:
            return len(task_ids)
        raw_count = acceptance_evaluation.get(count_key)
        if isinstance(raw_count, (int, float)) and not isinstance(raw_count, bool):
            return max(int(raw_count), 0)
        return 0

    def _repair_history_failed_task_count(self, entry: Dict[str, Any]) -> int:
        failed_task_ids = self._string_list(entry.get("failed_task_ids"))
        if failed_task_ids:
            return len(failed_task_ids)
        raw_count = entry.get("failed_task_count")
        if isinstance(raw_count, (int, float)) and not isinstance(raw_count, bool):
            return max(int(raw_count), 0)
        return 0

    def _string_list(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item]

    def _provider_attempt_count(self, provider_call: Dict[str, Any]) -> int:
        attempt_history = provider_call.get("attempt_history")
        if isinstance(attempt_history, list):
            return sum(1 for entry in attempt_history if isinstance(entry, dict))
        attempts_used = provider_call.get("attempts_used")
        if isinstance(attempts_used, (int, float)) and not isinstance(attempts_used, bool):
            return max(int(attempts_used), 0)
        return 0

    def _provider_retry_attempt_count(self, provider_call: Dict[str, Any], attempts_used: int) -> int:
        attempt_history = provider_call.get("attempt_history")
        if isinstance(attempt_history, list):
            return sum(
                1
                for entry in attempt_history
                if isinstance(entry, dict)
                and entry.get("success") is False
                and entry.get("retryable") is True
            )
        if attempts_used <= 1:
            return 0
        return attempts_used - 1

    def _provider_call_duration_ms(self, provider_call: Dict[str, Any]) -> Optional[float]:
        for value in (
            provider_call.get("duration_ms"),
            provider_call.get("latency_ms"),
            (provider_call.get("timing") or {}).get("total_duration_ms") if isinstance(provider_call.get("timing"), dict) else None,
            (provider_call.get("timing") or {}).get("duration_ms") if isinstance(provider_call.get("timing"), dict) else None,
            (provider_call.get("timing") or {}).get("latency_ms") if isinstance(provider_call.get("timing"), dict) else None,
        ):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return round(float(value), 3)
        return None

    def _task_resource_telemetry(self, task: Task) -> TaskResourceTelemetry:
        task_duration_ms = self._duration_ms(task.started_at, task.completed_at)
        last_attempt_duration_ms = self._duration_ms(task.last_attempt_started_at, task.completed_at)
        provider_call = task.last_provider_call if isinstance(task.last_provider_call, dict) else {}
        usage_metrics: Dict[str, float] = {}
        usage = provider_call.get("usage")
        if isinstance(usage, dict):
            self._accumulate_numeric_metrics(usage_metrics, usage)
        provider_duration_ms = self._provider_call_duration_ms(provider_call) if provider_call else None
        return {
            "has_provider_call": bool(provider_call),
            "task_duration_ms": self._normalize_metric_number(task_duration_ms) if task_duration_ms is not None else None,
            "last_attempt_duration_ms": self._normalize_metric_number(last_attempt_duration_ms) if last_attempt_duration_ms is not None else None,
            "provider_duration_ms": self._normalize_metric_number(provider_duration_ms) if provider_duration_ms is not None else None,
            "usage": self._sorted_numeric_metrics(usage_metrics),
        }

    def _accumulate_numeric_metrics(self, target: Dict[str, float], metrics: Dict[str, Any]) -> None:
        for key, value in metrics.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            target[key] = target.get(key, 0.0) + float(value)

    def _sorted_numeric_metrics(self, metrics: Dict[str, float]) -> NumericMetricMap:
        return {
            key: self._normalize_metric_number(value)
            for key, value in sorted(metrics.items())
        }

    def _metric_distribution(self, values: List[float]) -> MetricDistribution:
        if not values:
            return {
                "count": 0,
                "total": 0,
                "min": None,
                "max": None,
                "avg": None,
            }
        total = sum(values)
        return {
            "count": len(values),
            "total": self._normalize_metric_number(total),
            "min": self._normalize_metric_number(min(values)),
            "max": self._normalize_metric_number(max(values)),
            "avg": self._normalize_metric_number(total / len(values)),
        }

    def _normalize_metric_number(self, value: float) -> int | float:
        rounded = round(float(value), 3)
        if rounded.is_integer():
            return int(rounded)
        return rounded

    def _ordered_task_status_counts(self, counts: Dict[str, int]) -> Dict[str, int]:
        ordered_counts = {status.value: counts.get(status.value, 0) for status in TaskStatus}
        for status, count in sorted(counts.items()):
            if status in ordered_counts:
                continue
            ordered_counts[status] = count
        return ordered_counts

    def _duration_ms(self, start: Optional[str], end: Optional[str]) -> Optional[float]:
        if not start or not end:
            return None
        try:
            started_at = datetime.fromisoformat(start)
            finished_at = datetime.fromisoformat(end)
        except ValueError:
            return None
        return round((finished_at - started_at).total_seconds() * 1000, 3)

    def _workflow_status(self) -> WorkflowStatus:
        if self.is_workflow_paused():
            return WorkflowStatus.PAUSED
        if self.is_workflow_cancelled():
            return WorkflowStatus.CANCELLED
        statuses = {task.status for task in self.tasks}
        if not self.tasks:
            return WorkflowStatus.INIT
        if self.workflow_finished_at and self.terminal_outcome == WorkflowOutcome.COMPLETED.value:
            return WorkflowStatus.COMPLETED
        if self.workflow_finished_at and self.terminal_outcome == WorkflowOutcome.CANCELLED.value:
            return WorkflowStatus.CANCELLED
        if self.workflow_finished_at and self.terminal_outcome == WorkflowOutcome.FAILED.value:
            return WorkflowStatus.FAILED
        if TaskStatus.FAILED.value in statuses:
            return WorkflowStatus.FAILED
        if statuses.issubset({TaskStatus.DONE.value, TaskStatus.SKIPPED.value}):
            return WorkflowStatus.COMPLETED
        if TaskStatus.RUNNING.value in statuses:
            return WorkflowStatus.RUNNING
        return WorkflowStatus.INIT

    def _normalize_task_status(self, status: str) -> TaskStatus:
        try:
            return TaskStatus(status)
        except ValueError:
            return TaskStatus.PENDING

    def _cancelled_acceptance_evaluation(self) -> Dict[str, Any]:
        completed_task_ids = [task.id for task in self.tasks if task.status == TaskStatus.DONE.value]
        failed_task_ids = [task.id for task in self.tasks if task.status == TaskStatus.FAILED.value]
        skipped_task_ids = [task.id for task in self.tasks if task.status == TaskStatus.SKIPPED.value]
        pending_task_ids = [
            task.id
            for task in self.tasks
            if task.status not in {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.SKIPPED.value}
        ]
        return {
            "policy": self.acceptance_policy,
            "accepted": False,
            "reason": "workflow_cancelled",
            "evaluated_task_ids": [task.id for task in self.tasks],
            "required_task_ids": [task.id for task in self.tasks if task.required_for_acceptance],
            "completed_task_ids": completed_task_ids,
            "failed_task_ids": failed_task_ids,
            "skipped_task_ids": skipped_task_ids,
            "pending_task_ids": pending_task_ids,
        }

    def _build_agent_output(self, task: Task) -> AgentOutput:
        if task.output_payload:
            return self._deserialize_agent_output(task.output_payload)
        raw_content = task.output or ""
        summary = self._summarize_output(raw_content)
        artifact = ArtifactRecord(
            name=f"{task.id}_output",
            artifact_type=self._artifact_type_for_task(task),
            content=raw_content,
            metadata={
                "task_id": task.id,
                "task_title": task.title,
                "assigned_to": task.assigned_to,
            },
        )
        return AgentOutput(
            summary=summary,
            raw_content=raw_content,
            artifacts=[artifact],
            metadata={
                "task_id": task.id,
                "task_title": task.title,
                "assigned_to": task.assigned_to,
                "status": task.status,
            },
        )

    def _redacted_agent_output(self, output: AgentOutput) -> AgentOutput:
        return AgentOutput(
            summary=_redact_text(output.summary) or "",
            raw_content=_redact_text(output.raw_content) or "",
            artifacts=[self._redacted_artifact_record(artifact) for artifact in output.artifacts],
            decisions=[self._redacted_decision_record(decision) for decision in output.decisions],
            metadata=cast(Dict[str, Any], _redact_payload(output.metadata)),
        )

    def _redacted_artifact_record(self, artifact: ArtifactRecord) -> ArtifactRecord:
        return ArtifactRecord(
            name=_redact_text(artifact.name) or "artifact",
            artifact_type=artifact.artifact_type,
            path=_redact_text(artifact.path),
            content=_redact_text(artifact.content),
            created_at=artifact.created_at,
            metadata=cast(Dict[str, Any], _redact_payload(artifact.metadata)),
        )

    def _redacted_decision_record(self, decision: DecisionRecord) -> DecisionRecord:
        return DecisionRecord(
            topic=_redact_text(decision.topic) or "",
            decision=_redact_text(decision.decision) or "",
            rationale=_redact_text(decision.rationale) or "",
            created_at=decision.created_at,
            metadata=cast(Dict[str, Any], _redact_payload(decision.metadata)),
        )

    def _deserialize_agent_output(self, payload: Dict[str, Any]) -> AgentOutput:
        raw_artifacts = payload.get("artifacts", [])
        artifacts = [
            self._deserialize_artifact_record(item)
            for item in raw_artifacts
            if isinstance(item, (dict, str))
        ] if isinstance(raw_artifacts, list) else []
        raw_decisions = payload.get("decisions", [])
        decisions = [
            DecisionRecord(
                topic=item.get("topic", ""),
                decision=item.get("decision", ""),
                rationale=item.get("rationale", ""),
                created_at=item.get("created_at") or item.get("at") or self._legacy_timestamp_fallback(),
                metadata=item.get("metadata", {}),
            )
            for item in raw_decisions
            if isinstance(item, dict)
        ]
        return AgentOutput(
            summary=payload.get("summary", self._summarize_output(payload.get("raw_content", ""))),
            raw_content=payload.get("raw_content", ""),
            artifacts=artifacts,
            decisions=decisions,
            metadata=payload.get("metadata", {}),
        )

    def _deserialize_artifact_record(self, artifact: Dict[str, Any] | str) -> ArtifactRecord:
        if isinstance(artifact, dict):
            raw_type = artifact.get("artifact_type", ArtifactType.OTHER.value)
            try:
                artifact_type = ArtifactType(raw_type)
            except ValueError:
                artifact_type = ArtifactType.OTHER
            name = artifact.get("name") or artifact.get("path") or "artifact"
            return ArtifactRecord(
                name=str(name),
                artifact_type=artifact_type,
                path=artifact.get("path"),
                content=artifact.get("content"),
                created_at=artifact.get("created_at") or self._legacy_timestamp_fallback(),
                metadata=artifact.get("metadata", {}),
            )
        return ArtifactRecord(name=artifact)

    def _summarize_output(self, raw_content: str) -> str:
        stripped = raw_content.strip()
        if not stripped:
            return ""
        first_line = stripped.splitlines()[0].strip()
        return first_line[:120]

    def _artifact_type_for_task(self, task: Task) -> ArtifactType:
        role_key = task.assigned_to.strip().lower().replace(" ", "_")
        if role_key == "architect":
            return ArtifactType.DOCUMENT
        if role_key == "code_engineer":
            return ArtifactType.CODE
        if role_key == "qa_tester":
            return ArtifactType.TEST
        if role_key == "docs_writer":
            return ArtifactType.DOCUMENT
        if role_key == "legal_advisor":
            return ArtifactType.DOCUMENT
        return ArtifactType.TEXT

    def summary(self) -> str:
        """Return a compact human-readable summary of workflow progress."""

        done = sum(1 for t in self.tasks if t.status == TaskStatus.DONE.value)
        project_name = _redact_text(self.project_name) or ""
        return f"Project: {project_name} | Phase: {self.phase} | Tasks: {done}/{len(self.tasks)} done"
