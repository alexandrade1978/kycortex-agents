from collections import deque
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from kycortex_agents.exceptions import StatePersistenceError, WorkflowDefinitionError
from kycortex_agents.memory.state_store import resolve_state_store
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
    WorkflowProviderSummary,
    WorkflowRepairSummary,
    WorkflowResumeSummary,
    WorkflowStatus,
    WorkflowTelemetry,
)

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
    workflow_last_resumed_at: Optional[str] = None
    repair_cycle_count: int = 0
    repair_max_cycles: int = 0
    repair_history: List[Dict[str, Any]] = field(default_factory=list)
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
                error_type = type(error).__name__ if isinstance(error, Exception) else "runtime_error"
                task.last_error = error_message
                task.last_error_type = error_type
                task.last_error_category = error_category or FailureCategory.TASK_EXECUTION.value
                task.last_provider_call = provider_call
                if task.attempts <= task.retry_limit:
                    task.status = TaskStatus.PENDING.value
                    task.completed_at = None
                    self._record_task_event(task, "retry_scheduled")
                    self._record_execution_event(
                        event="task_retry_scheduled",
                        task_id=task.id,
                        status=task.status,
                        details={
                            "attempts": task.attempts,
                            "retry_limit": task.retry_limit,
                            "error_type": task.last_error_type,
                            "error_category": task.last_error_category,
                            "provider_call": provider_call,
                            "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, datetime.now(timezone.utc).isoformat()),
                        },
                    )
                    self._sync_repair_origin_failure(
                        task,
                        error_message=error_message,
                        error_type=error_type,
                        provider_call=provider_call,
                        output=output,
                        completed_at=None,
                        final_failure=False,
                    )
                    self._touch()
                    return
                task.status = TaskStatus.FAILED.value
                task.output = error_message
                if isinstance(output, AgentOutput) and output.raw_content.strip():
                    task.output_payload = asdict(output)
                else:
                    task.output_payload = None
                task.completed_at = datetime.now(timezone.utc).isoformat()
                self._record_task_event(task, "failed", task.completed_at, error_message=error_message)
                self._record_execution_event(
                    event="task_failed",
                    timestamp=task.completed_at,
                    task_id=task.id,
                    status=task.status,
                    details={
                        "attempts": task.attempts,
                        "error_message": error_message,
                        "error_type": error_type,
                        "error_category": task.last_error_category,
                        "provider_call": provider_call,
                        "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, task.completed_at),
                    },
                )
                self._sync_repair_origin_failure(
                    task,
                    error_message=error_message,
                    error_type=error_type,
                    provider_call=provider_call,
                    output=output,
                    completed_at=task.completed_at,
                    final_failure=True,
                )
                self._touch(task.completed_at)
                return

    def complete_task(self, task_id: str, output: str | AgentOutput, provider_call: Optional[Dict[str, Any]] = None):
        """Mark a task complete and persist its raw or structured output payload."""

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
                t.last_provider_call = provider_call
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
                        "provider_call": provider_call,
                        "last_attempt_duration_ms": self._duration_ms(t.last_attempt_started_at, t.completed_at),
                        "task_duration_ms": self._duration_ms(t.started_at, t.completed_at),
                    },
                )
                self._sync_repair_origin_completion(t, provider_call)
                self._touch(t.completed_at)

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
            self.workflow_last_resumed_at = resumed_at
            self.workflow_finished_at = None
            self._record_execution_event(
                event="workflow_resumed",
                timestamp=resumed_at,
                status=self.phase,
                details={"reason": "interrupted_tasks", "task_ids": resumed_task_ids},
            )
            self._touch(resumed_at)
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
        self._record_workflow_resumed(resumed_at, resumed_ids)
        return resumed_task_ids

    def _record_workflow_resumed(self, resumed_at: str, task_ids: List[str]) -> None:
        self.workflow_last_resumed_at = resumed_at
        self.workflow_finished_at = None
        self._record_execution_event(
            event="workflow_resumed",
            timestamp=resumed_at,
            status=self.phase,
            details={"reason": "failed_workflow", "task_ids": task_ids},
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
        output: Optional[str | AgentOutput],
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
            if isinstance(output, AgentOutput) and output.raw_content.strip():
                origin.output_payload = asdict(output)
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
        origin.status = TaskStatus.DONE.value
        origin.output = task.output
        origin.output_payload = task.output_payload
        origin.last_error = None
        origin.last_error_type = None
        origin.last_error_category = None
        origin.repair_context = {}
        origin.last_provider_call = provider_call
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
        workflow_telemetry = self._workflow_telemetry_summary()
        self._record_execution_event(
            event="workflow_finished",
            timestamp=finished_at,
            status=self.phase,
            details={
                "workflow_duration_ms": self._duration_ms(self.workflow_started_at, finished_at),
                "acceptance_policy": self.acceptance_policy,
                "terminal_outcome": self.terminal_outcome,
                "failure_category": self.failure_category,
                "acceptance_criteria_met": self.acceptance_criteria_met,
                "acceptance_evaluation": self.acceptance_evaluation,
                "workflow_telemetry": workflow_telemetry,
            },
        )
        self._touch(finished_at)

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
        state_store.save(self.state_file, asdict(self))

    @classmethod
    def load(cls, path: str) -> "ProjectState":
        """Load a project state from disk and normalize legacy persisted fields."""

        data = resolve_state_store(path).load(path)
        tasks = [Task(**t) for t in data.pop("tasks", [])]
        try:
            obj = cls(**{k: v for k, v in data.items() if k != "tasks"})
        except TypeError as exc:
            raise StatePersistenceError(f"Project state data is invalid: {path}") from exc
        obj.tasks = tasks
        obj.state_file = path
        obj._normalize_legacy_decision_timestamps()
        obj._normalize_legacy_artifact_timestamps()
        obj._infer_legacy_skip_reason_types()
        return obj

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
        task.status = TaskStatus.SKIPPED.value
        task.last_error = reason
        task.last_error_type = None
        task.last_error_category = None
        task.repair_context = {}
        task.output = reason
        task.output_payload = None
        task.skip_reason_type = reason_type
        task.last_provider_call = None
        task.started_at = None
        task.last_attempt_started_at = None
        task.last_resumed_at = None
        task.completed_at = datetime.now(timezone.utc).isoformat()
        self._record_task_event(task, "skipped", task.completed_at, error_message=reason)
        self._record_execution_event(
            event="task_skipped",
            timestamp=task.completed_at,
            task_id=task.id,
            status=task.status,
            details={"reason": reason},
        )
        self._touch(task.completed_at)

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
            if task_status == TaskStatus.FAILED:
                failure = FailureRecord(
                    message=task.output or task.last_error or "Task failed without output",
                    error_type=task.last_error_type or "runtime_error",
                    category=task.last_error_category or FailureCategory.UNKNOWN.value,
                    retryable=task.attempts <= task.retry_limit,
                    details={
                        "attempts": task.attempts,
                        "retry_limit": task.retry_limit,
                        "error_type": task.last_error_type,
                        "error_category": task.last_error_category,
                        "provider_call": task.last_provider_call,
                        "provider_budget": self._provider_budget_summary(task.last_provider_call),
                        "started_at": task.started_at,
                        "last_attempt_started_at": task.last_attempt_started_at,
                        "last_resumed_at": task.last_resumed_at,
                        "task_duration_ms": self._duration_ms(task.started_at, task.completed_at),
                        "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, task.completed_at),
                        "repair_context": task.repair_context,
                        "repair_origin_task_id": task.repair_origin_task_id,
                        "repair_attempt": task.repair_attempt,
                        "history": task.history,
                    },
                )
            if task.output or task.output_payload:
                output = self._build_agent_output(task)
            results[task.id] = TaskResult(
                task_id=task.id,
                status=task_status,
                agent_name=task.assigned_to,
                output=output,
                failure=failure,
                resource_telemetry=resource_telemetry,
                details={
                    "attempts": task.attempts,
                    "retry_limit": task.retry_limit,
                    "required_for_acceptance": task.required_for_acceptance,
                    "last_error": task.last_error,
                    "last_error_type": task.last_error_type,
                    "last_error_category": task.last_error_category,
                    "last_provider_call": task.last_provider_call,
                    "provider_budget": self._provider_budget_summary(task.last_provider_call),
                    "repair_context": task.repair_context,
                    "repair_origin_task_id": task.repair_origin_task_id,
                    "repair_attempt": task.repair_attempt,
                    "last_attempt_started_at": task.last_attempt_started_at,
                    "last_resumed_at": task.last_resumed_at,
                    "task_duration_ms": self._duration_ms(task.started_at, task.completed_at),
                    "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, task.completed_at),
                    "history": task.history,
                },
                started_at=task.started_at,
                completed_at=task.completed_at,
            )
        return results

    def snapshot(self) -> ProjectSnapshot:
        """Build a normalized project snapshot for downstream orchestration and inspection."""

        self._normalize_legacy_decision_timestamps()
        self._normalize_legacy_artifact_timestamps()
        workflow_telemetry = self._workflow_telemetry_summary()
        return ProjectSnapshot(
            project_name=self.project_name,
            goal=self.goal,
            workflow_status=self._workflow_status(),
            phase=self.phase,
            acceptance_policy=self.acceptance_policy,
            terminal_outcome=self.terminal_outcome,
            failure_category=self.failure_category,
            acceptance_criteria_met=self.acceptance_criteria_met,
            acceptance_evaluation=dict(self.acceptance_evaluation),
            started_at=self.workflow_started_at,
            finished_at=self.workflow_finished_at,
            last_resumed_at=self.workflow_last_resumed_at,
            repair_cycle_count=self.repair_cycle_count,
            repair_max_cycles=self.repair_max_cycles,
            repair_budget_remaining=max(self.repair_max_cycles - self.repair_cycle_count, 0),
            repair_history=list(self.repair_history),
            task_results=self.task_results(),
            workflow_telemetry=workflow_telemetry,
            decisions=[
                DecisionRecord(
                    topic=decision.get("topic", ""),
                    decision=decision.get("decision", ""),
                    rationale=decision.get("rationale", ""),
                    created_at=decision.get("at", self._legacy_timestamp_fallback()),
                    metadata=decision.get("metadata", {}),
                )
                for decision in self.decisions
            ],
            artifacts=[self._deserialize_artifact_record(artifact) for artifact in self.artifacts],
            execution_events=list(self.execution_events),
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
                "error_message": error_message,
            }
        )

    def _record_execution_event(
        self,
        event: str,
        timestamp: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        normalized_details = dict(details or {})
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

    def _provider_budget_summary(
        self,
        provider_call: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(provider_call, dict):
            return None
        return {
            "total_calls": provider_call.get("provider_call_count"),
            "calls_by_provider": dict(provider_call.get("provider_call_counts_by_provider") or {}),
            "max_calls_per_agent": provider_call.get("provider_max_calls_per_agent"),
            "max_calls_by_provider": dict(provider_call.get("provider_max_calls_per_provider") or {}),
            "remaining_calls": provider_call.get("provider_remaining_calls"),
            "remaining_calls_by_provider": dict(provider_call.get("provider_remaining_calls_by_provider") or {}),
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
        fallback_by_provider: Dict[str, int] = {}
        fallback_by_status: Dict[str, int] = {}
        final_error_types: Dict[str, int] = {}
        fallback_error_types: Dict[str, int] = {}

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
                            "last_error_types": {},
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
                    if raw_health_entry.get("circuit_breaker_open") is True:
                        health_summary["circuit_open_count"] += 1
                    if raw_health_entry.get("last_failure_retryable") is True:
                        health_summary["retryable_failure_count"] += 1
                    last_error_type = raw_health_entry.get("last_error_type")
                    if isinstance(last_error_type, str) and last_error_type:
                        health_summary["last_error_types"][last_error_type] = (
                            health_summary["last_error_types"].get(last_error_type, 0) + 1
                        )
                    last_health_check = raw_health_entry.get("last_health_check")
                    if (
                        isinstance(last_health_check, dict)
                        and last_health_check.get("active_check") is True
                        and last_health_check.get("cooldown_cached") is not True
                    ):
                        health_summary["active_health_check_count"] += 1

            if provider_call.get("success") is False:
                error_type = provider_call.get("error_type")
                if isinstance(error_type, str) and error_type:
                    final_error_types[error_type] = final_error_types.get(error_type, 0) + 1

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
                    fallback_by_provider[fallback_provider] = fallback_by_provider.get(fallback_provider, 0) + 1
                fallback_status = entry.get("status")
                if isinstance(fallback_status, str) and fallback_status:
                    fallback_by_status[fallback_status] = fallback_by_status.get(fallback_status, 0) + 1
                fallback_error_type = entry.get("error_type")
                if isinstance(fallback_error_type, str) and fallback_error_type:
                    fallback_error_types[fallback_error_type] = fallback_error_types.get(fallback_error_type, 0) + 1

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
                "last_error_types": dict(sorted(raw_health_summary.get("last_error_types", {}).items())),
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
            "final_providers": sorted(final_providers),
            "observed_providers": sorted(observed_providers),
            "provider_summary": normalized_provider_summary,
            "provider_health_summary": normalized_provider_health_summary,
            "attempt_count": attempt_count,
            "retry_attempt_count": retry_attempt_count,
            "duration_ms": self._metric_distribution(duration_values),
            "usage": self._sorted_numeric_metrics(usage_totals),
            "fallback_summary": {
                "task_count": fallback_task_count,
                "entry_count": fallback_entry_count,
                "by_provider": dict(sorted(fallback_by_provider.items())),
                "by_status": dict(sorted(fallback_by_status.items())),
            },
            "error_summary": {
                "final_error_types": dict(sorted(final_error_types.items())),
                "fallback_error_types": dict(sorted(fallback_error_types.items())),
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
        acceptance_evaluation = self.acceptance_evaluation if isinstance(self.acceptance_evaluation, dict) else {}
        return {
            "policy": self.acceptance_policy,
            "accepted": self.acceptance_criteria_met,
            "reason": acceptance_evaluation.get("reason"),
            "terminal_outcome": self.terminal_outcome,
            "failure_category": self.failure_category,
            "evaluated_task_count": len(self._list_like_values(acceptance_evaluation.get("evaluated_task_ids"))),
            "required_task_count": len(self._list_like_values(acceptance_evaluation.get("required_task_ids"))),
            "completed_task_count": len(self._list_like_values(acceptance_evaluation.get("completed_task_ids"))),
            "failed_task_count": len(self._list_like_values(acceptance_evaluation.get("failed_task_ids"))),
            "skipped_task_count": len(self._list_like_values(acceptance_evaluation.get("skipped_task_ids"))),
            "pending_task_count": len(self._list_like_values(acceptance_evaluation.get("pending_task_ids"))),
        }

    def _resume_summary(self) -> WorkflowResumeSummary:
        resumed_events = [
            event for event in self.execution_events
            if isinstance(event, dict) and event.get("event") == "workflow_resumed"
        ]
        reasons: Dict[str, int] = {}
        resumed_task_ids: List[str] = []
        for event in resumed_events:
            raw_details = event.get("details")
            details: Dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
            reason = details.get("reason")
            if isinstance(reason, str) and reason:
                reasons[reason] = reasons.get(reason, 0) + 1
            resumed_task_ids.extend(self._string_list(details.get("task_ids")))
        unique_task_ids = sorted(set(resumed_task_ids))
        return {
            "count": len(resumed_events),
            "reasons": dict(sorted(reasons.items())),
            "task_count": len(resumed_task_ids),
            "unique_task_count": len(unique_task_ids),
            "unique_task_ids": unique_task_ids,
            "last_resumed_at": self.workflow_last_resumed_at,
        }

    def _repair_summary(self) -> WorkflowRepairSummary:
        reasons: Dict[str, int] = {}
        last_reason: Optional[str] = None
        failure_categories: Dict[str, int] = {}
        failed_task_ids: List[str] = []
        for entry in self.repair_history:
            if not isinstance(entry, dict):
                continue
            reason = entry.get("reason")
            if isinstance(reason, str) and reason:
                reasons[reason] = reasons.get(reason, 0) + 1
                last_reason = reason
            failure_category = entry.get("failure_category")
            if isinstance(failure_category, str) and failure_category:
                failure_categories[failure_category] = failure_categories.get(failure_category, 0) + 1
            failed_task_ids.extend(self._string_list(entry.get("failed_task_ids")))
        unique_failed_task_ids = sorted(set(failed_task_ids))
        return {
            "cycle_count": self.repair_cycle_count,
            "max_cycles": self.repair_max_cycles,
            "budget_remaining": max(self.repair_max_cycles - self.repair_cycle_count, 0),
            "history_count": len([entry for entry in self.repair_history if isinstance(entry, dict)]),
            "reasons": dict(sorted(reasons.items())),
            "last_reason": last_reason,
            "failure_categories": dict(sorted(failure_categories.items())),
            "failed_task_count": len(unique_failed_task_ids),
            "failed_task_ids": unique_failed_task_ids,
        }

    def _list_like_values(self, value: Any) -> List[Any]:
        if not isinstance(value, list):
            return []
        return list(value)

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
        provider = provider_call.get("provider") if isinstance(provider_call.get("provider"), str) else None
        model = provider_call.get("model") if isinstance(provider_call.get("model"), str) else None
        provider_duration_ms = self._provider_call_duration_ms(provider_call) if provider_call else None
        return {
            "has_provider_call": bool(provider_call),
            "provider": provider,
            "model": model,
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
        statuses = {task.status for task in self.tasks}
        if not self.tasks:
            return WorkflowStatus.INIT
        if self.workflow_finished_at and self.terminal_outcome == WorkflowOutcome.COMPLETED.value:
            return WorkflowStatus.COMPLETED
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
        return f"Project: {self.project_name} | Phase: {self.phase} | Tasks: {done}/{len(self.tasks)} done"
