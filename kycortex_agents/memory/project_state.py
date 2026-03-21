import os
import json
import tempfile
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import UTC, datetime

from kycortex_agents.exceptions import StatePersistenceError
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
    status: str = TaskStatus.PENDING.value
    output: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: Optional[str] = None

@dataclass
class ProjectState:
    project_name: str
    goal: str
    tasks: List[Task] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    phase: str = "init"
    state_file: str = "project_state.json"

    def add_task(self, task: Task):
        self.tasks.append(task)

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
                task.status = TaskStatus.RUNNING.value
                task.attempts += 1
                task.last_error = None
                return

    def fail_task(self, task_id: str, error_message: str):
        for task in self.tasks:
            if task.id == task_id:
                task.last_error = error_message
                if task.attempts <= task.retry_limit:
                    task.status = TaskStatus.PENDING.value
                    task.completed_at = None
                    return
                task.status = TaskStatus.FAILED.value
                task.output = error_message
                task.completed_at = datetime.now(UTC).isoformat()
                return

    def complete_task(self, task_id: str, output: str):
        for t in self.tasks:
            if t.id == task_id:
                t.status = TaskStatus.DONE.value
                t.output = output
                t.last_error = None
                t.completed_at = datetime.now(UTC).isoformat()

    def resume_interrupted_tasks(self) -> List[str]:
        resumed_task_ids: List[str] = []
        for task in self.tasks:
            if task.status == TaskStatus.RUNNING.value:
                task.status = TaskStatus.PENDING.value
                task.last_error = "Task resumed after interrupted execution"
                task.completed_at = None
                resumed_task_ids.append(task.id)
        return resumed_task_ids

    def should_retry_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False
        return task.status == TaskStatus.PENDING.value and task.attempts > 0 and task.attempts <= task.retry_limit

    def add_decision(self, topic: str, decision: str, rationale: str):
        self.decisions.append({"topic": topic, "decision": decision, "rationale": rationale, "at": datetime.now(UTC).isoformat()})

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

    def add_artifact_record(self, record: ArtifactRecord):
        self.artifacts.append(record.path or record.name)

    def save(self):
        state_path = self.state_file
        state_dir = os.path.dirname(state_path)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(prefix="project_state_", suffix=".json", dir=state_dir or None)
        try:
            with os.fdopen(fd, "w") as file_handle:
                json.dump(asdict(self), file_handle, indent=2, default=str)
            os.replace(temp_path, state_path)
        except OSError as exc:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise StatePersistenceError(f"Failed to save project state to {state_path}") from exc

    @classmethod
    def load(cls, path: str) -> "ProjectState":
        try:
            with open(path) as file_handle:
                data = json.load(file_handle)
        except FileNotFoundError as exc:
            raise StatePersistenceError(f"Project state file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise StatePersistenceError(f"Project state file is invalid JSON: {path}") from exc
        tasks = [Task(**t) for t in data.pop("tasks", [])]
        try:
            obj = cls(**{k: v for k, v in data.items() if k != "tasks"})
        except TypeError as exc:
            raise StatePersistenceError(f"Project state data is invalid: {path}") from exc
        obj.tasks = tasks
        return obj

    def pending_tasks(self) -> List[Task]:
        return [t for t in self.tasks if t.status == TaskStatus.PENDING.value]

    def runnable_tasks(self) -> List[Task]:
        return [task for task in self.tasks if self.is_task_ready(task)]

    def blocked_tasks(self) -> List[Task]:
        return [
            task
            for task in self.tasks
            if task.status == TaskStatus.PENDING.value and not self.is_task_ready(task)
        ]

    def task_results(self) -> Dict[str, TaskResult]:
        results: Dict[str, TaskResult] = {}
        for task in self.tasks:
            task_status = self._normalize_task_status(task.status)
            failure = None
            output = None
            if task_status == TaskStatus.FAILED and task.output:
                failure = FailureRecord(message=task.output)
            if task.output:
                output = self._build_agent_output(task)
            results[task.id] = TaskResult(
                task_id=task.id,
                status=task_status,
                agent_name=task.assigned_to,
                output=output,
                failure=failure,
                completed_at=task.completed_at,
            )
        return results

    def snapshot(self) -> ProjectSnapshot:
        return ProjectSnapshot(
            project_name=self.project_name,
            goal=self.goal,
            workflow_status=self._workflow_status(),
            phase=self.phase,
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
            artifacts=[ArtifactRecord(name=artifact) for artifact in self.artifacts],
        )

    def _workflow_status(self) -> WorkflowStatus:
        statuses = {task.status for task in self.tasks}
        if not self.tasks:
            return WorkflowStatus.INIT
        if TaskStatus.FAILED.value in statuses:
            return WorkflowStatus.FAILED
        if all(status == TaskStatus.DONE.value for status in statuses):
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
