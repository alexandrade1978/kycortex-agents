import os
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import UTC, datetime

from kycortex_agents.exceptions import StatePersistenceError, WorkflowDefinitionError
from kycortex_agents.memory.state_store import resolve_state_store
from kycortex_agents.types import (
    AgentOutput,
    ArtifactRecord,
    ArtifactType,
    DecisionRecord,
    FailureRecord,
    ProjectSnapshot,
    TaskResult,
    TaskStatus,
    WorkflowStatus,
)

@dataclass
class Task:
    id: str
    title: str
    description: str
    assigned_to: str
    dependencies: List[str] = field(default_factory=list)
    retry_limit: int = 0
    attempts: int = 0
    last_error: Optional[str] = None
    last_error_type: Optional[str] = None
    status: str = TaskStatus.PENDING.value
    output: Optional[str] = None
    output_payload: Optional[Dict[str, Any]] = None
    skip_reason_type: Optional[str] = None
    last_provider_call: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: Optional[str] = None
    last_attempt_started_at: Optional[str] = None
    last_resumed_at: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    completed_at: Optional[str] = None

@dataclass
class ProjectState:
    project_name: str
    goal: str
    tasks: List[Task] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any] | str] = field(default_factory=list)
    execution_events: List[Dict[str, Any]] = field(default_factory=list)
    phase: str = "init"
    workflow_started_at: Optional[str] = None
    workflow_finished_at: Optional[str] = None
    workflow_last_resumed_at: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    state_file: str = "project_state.json"

    def add_task(self, task: Task):
        self.tasks.append(task)
        self._touch()

    def get_task(self, task_id: str) -> Optional[Task]:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def is_task_ready(self, task: Task) -> bool:
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
        for task in self.tasks:
            if task.id == task_id:
                started_at = datetime.now(UTC).isoformat()
                task.status = TaskStatus.RUNNING.value
                task.attempts += 1
                task.last_error = None
                task.last_error_type = None
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
                self._touch(started_at)
                return

    def fail_task(self, task_id: str, error: str | Exception, provider_call: Optional[Dict[str, Any]] = None):
        for task in self.tasks:
            if task.id == task_id:
                error_message = str(error)
                error_type = type(error).__name__ if isinstance(error, Exception) else "runtime_error"
                task.last_error = error_message
                task.last_error_type = error_type
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
                            "provider_call": provider_call,
                            "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, datetime.now(UTC).isoformat()),
                        },
                    )
                    self._touch()
                    return
                task.status = TaskStatus.FAILED.value
                task.output = error_message
                task.output_payload = None
                task.completed_at = datetime.now(UTC).isoformat()
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
                        "provider_call": provider_call,
                        "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, task.completed_at),
                    },
                )
                self._touch(task.completed_at)
                return

    def complete_task(self, task_id: str, output: str | AgentOutput, provider_call: Optional[Dict[str, Any]] = None):
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
                t.last_provider_call = provider_call
                t.completed_at = datetime.now(UTC).isoformat()
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
                self._touch(t.completed_at)

    def resume_interrupted_tasks(self) -> List[str]:
        resumed_task_ids: List[str] = []
        resumed_at: Optional[str] = None
        for task in self.tasks:
            if task.status == TaskStatus.RUNNING.value:
                resumed_at = resumed_at or datetime.now(UTC).isoformat()
                task.last_resumed_at = resumed_at
                task.status = TaskStatus.PENDING.value
                task.last_error = "Task resumed after interrupted execution"
                task.last_error_type = None
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

    def resume_failed_tasks(self) -> List[str]:
        failed_task_ids = [task.id for task in self.tasks if task.status == TaskStatus.FAILED.value]
        if not failed_task_ids:
            return []

        resumed_at = datetime.now(UTC).isoformat()
        resumed_task_ids: List[str] = []
        resumable_dependency_ids = set(failed_task_ids)

        while True:
            changed = False
            for task in self.tasks:
                should_resume = task.status == TaskStatus.FAILED.value or (
                    task.status == TaskStatus.SKIPPED.value
                    and self._is_dependency_failed_skip(task)
                    and any(dep in resumable_dependency_ids for dep in task.dependencies)
                )
                if not should_resume or task.id in resumed_task_ids:
                    continue
                task.status = TaskStatus.PENDING.value
                task.last_error = "Task resumed after failed workflow execution"
                task.last_error_type = None
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

        self.workflow_last_resumed_at = resumed_at
        self.workflow_finished_at = None
        self._record_execution_event(
            event="workflow_resumed",
            timestamp=resumed_at,
            status=self.phase,
            details={"reason": "failed_workflow", "task_ids": resumed_task_ids},
        )
        self._touch(resumed_at)
        return resumed_task_ids

    def _is_dependency_failed_skip(self, task: Task) -> bool:
        if task.skip_reason_type is not None:
            return task.skip_reason_type == "dependency_failed"
        reason = task.last_error or task.output or ""
        return reason.startswith("Skipped because dependency '") and reason.endswith("' failed")

    def should_retry_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False
        return task.status == TaskStatus.PENDING.value and task.attempts > 0 and task.attempts <= task.retry_limit

    def add_decision(self, topic: str, decision: str, rationale: str):
        self.decisions.append({"topic": topic, "decision": decision, "rationale": rationale, "at": datetime.now(UTC).isoformat()})
        self._touch()

    def add_decision_record(self, record: DecisionRecord):
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
        self.artifacts.append(asdict(record))
        self._touch(record.created_at)

    def mark_workflow_running(self):
        started_at = datetime.now(UTC).isoformat()
        if self.workflow_started_at is None:
            self.workflow_started_at = started_at
        self.workflow_finished_at = None
        self.phase = "execution"
        self._record_execution_event(event="workflow_started", timestamp=started_at, status=self.phase)
        self._touch(started_at)

    def mark_workflow_finished(self, phase: str):
        finished_at = datetime.now(UTC).isoformat()
        self.phase = phase
        self.workflow_finished_at = finished_at
        self._record_execution_event(
            event="workflow_finished",
            timestamp=finished_at,
            status=self.phase,
            details={"workflow_duration_ms": self._duration_ms(self.workflow_started_at, finished_at)},
        )
        self._touch(finished_at)

    def save(self):
        self._touch()
        state_store = resolve_state_store(self.state_file)
        state_store.save(self.state_file, asdict(self))

    @classmethod
    def load(cls, path: str) -> "ProjectState":
        data = resolve_state_store(path).load(path)
        tasks = [Task(**t) for t in data.pop("tasks", [])]
        try:
            obj = cls(**{k: v for k, v in data.items() if k != "tasks"})
        except TypeError as exc:
            raise StatePersistenceError(f"Project state data is invalid: {path}") from exc
        obj.tasks = tasks
        return obj

    def pending_tasks(self) -> List[Task]:
        return [t for t in self.tasks if t.status == TaskStatus.PENDING.value]

    def execution_plan(self) -> List[Task]:
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
        return [task for task in self.execution_plan() if self.is_task_ready(task)]

    def blocked_tasks(self) -> List[Task]:
        return [
            task
            for task in self.execution_plan()
            if task.status == TaskStatus.PENDING.value and not self.is_task_ready(task)
        ]

    def skip_task(self, task_id: str, reason: str, reason_type: str = "manual"):
        task = self.get_task(task_id)
        if task is None:
            return
        task.status = TaskStatus.SKIPPED.value
        task.last_error = reason
        task.last_error_type = None
        task.output = reason
        task.output_payload = None
        task.skip_reason_type = reason_type
        task.last_provider_call = None
        task.completed_at = datetime.now(UTC).isoformat()
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
        results: Dict[str, TaskResult] = {}
        for task in self.tasks:
            task_status = self._normalize_task_status(task.status)
            failure = None
            output = None
            if task_status == TaskStatus.FAILED and task.output:
                failure = FailureRecord(
                    message=task.output,
                    error_type=task.last_error_type or "runtime_error",
                    retryable=task.attempts <= task.retry_limit,
                    details={
                        "attempts": task.attempts,
                        "retry_limit": task.retry_limit,
                        "error_type": task.last_error_type,
                        "provider_call": task.last_provider_call,
                        "started_at": task.started_at,
                        "last_attempt_started_at": task.last_attempt_started_at,
                        "last_resumed_at": task.last_resumed_at,
                        "task_duration_ms": self._duration_ms(task.started_at, task.completed_at),
                        "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, task.completed_at),
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
                details={
                    "attempts": task.attempts,
                    "retry_limit": task.retry_limit,
                    "last_error": task.last_error,
                    "last_error_type": task.last_error_type,
                    "last_provider_call": task.last_provider_call,
                    "last_attempt_started_at": task.last_attempt_started_at,
                    "last_resumed_at": task.last_resumed_at,
                    "task_duration_ms": self._duration_ms(task.started_at, task.completed_at),
                    "last_attempt_duration_ms": self._duration_ms(task.last_attempt_started_at, task.completed_at),
                    "history": task.history,
                },
                started_at=task.started_at or task.created_at,
                completed_at=task.completed_at,
            )
        return results

    def snapshot(self) -> ProjectSnapshot:
        return ProjectSnapshot(
            project_name=self.project_name,
            goal=self.goal,
            workflow_status=self._workflow_status(),
            phase=self.phase,
            started_at=self.workflow_started_at,
            finished_at=self.workflow_finished_at,
            last_resumed_at=self.workflow_last_resumed_at,
            task_results=self.task_results(),
            decisions=[
                DecisionRecord(
                    topic=decision.get("topic", ""),
                    decision=decision.get("decision", ""),
                    rationale=decision.get("rationale", ""),
                    created_at=decision.get("at", datetime.now(UTC).isoformat()),
                    metadata=decision.get("metadata", {}),
                )
                for decision in self.decisions
            ],
            artifacts=[self._deserialize_artifact_record(artifact) for artifact in self.artifacts],
            execution_events=list(self.execution_events),
            updated_at=self.updated_at,
        )

    def _touch(self, timestamp: Optional[str] = None):
        self.updated_at = timestamp or datetime.now(UTC).isoformat()

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
                "timestamp": timestamp or datetime.now(UTC).isoformat(),
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
        self.execution_events.append(
            {
                "event": event,
                "timestamp": timestamp or datetime.now(UTC).isoformat(),
                "task_id": task_id,
                "status": status,
                "details": details or {},
            }
        )

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
        artifacts = [self._deserialize_artifact_record(item) for item in payload.get("artifacts", [])]
        decisions = [
            DecisionRecord(
                topic=item.get("topic", ""),
                decision=item.get("decision", ""),
                rationale=item.get("rationale", ""),
                created_at=item.get("created_at", datetime.now(UTC).isoformat()),
                metadata=item.get("metadata", {}),
            )
            for item in payload.get("decisions", [])
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
            return ArtifactRecord(
                name=artifact.get("name", artifact.get("path", "artifact")),
                artifact_type=artifact_type,
                path=artifact.get("path"),
                content=artifact.get("content"),
                created_at=artifact.get("created_at", datetime.now(UTC).isoformat()),
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
        done = sum(1 for t in self.tasks if t.status == TaskStatus.DONE.value)
        return f"Project: {self.project_name} | Phase: {self.phase} | Tasks: {done}/{len(self.tasks)} done"
