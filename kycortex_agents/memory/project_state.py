import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime

from kycortex_agents.types import (
    ArtifactRecord,
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
    status: str = TaskStatus.PENDING.value
    output: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
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

    def start_task(self, task_id: str):
        for task in self.tasks:
            if task.id == task_id:
                task.status = TaskStatus.RUNNING.value
                return

    def fail_task(self, task_id: str, error_message: str):
        for task in self.tasks:
            if task.id == task_id:
                task.status = TaskStatus.FAILED.value
                task.output = error_message
                task.completed_at = datetime.utcnow().isoformat()
                return

    def complete_task(self, task_id: str, output: str):
        for t in self.tasks:
            if t.id == task_id:
                t.status = TaskStatus.DONE.value
                t.output = output
                t.completed_at = datetime.utcnow().isoformat()

    def add_decision(self, topic: str, decision: str, rationale: str):
        self.decisions.append({"topic": topic, "decision": decision, "rationale": rationale, "at": datetime.utcnow().isoformat()})

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
        with open(self.state_file, "w") as f:
            json.dump(asdict(self), f, indent=2, default=str)

    @classmethod
    def load(cls, path: str) -> "ProjectState":
        with open(path) as f:
            data = json.load(f)
        tasks = [Task(**t) for t in data.pop("tasks", [])]
        obj = cls(**{k: v for k, v in data.items() if k != "tasks"})
        obj.tasks = tasks
        return obj

    def pending_tasks(self) -> List[Task]:
        return [t for t in self.tasks if t.status == TaskStatus.PENDING.value]

    def task_results(self) -> Dict[str, TaskResult]:
        results: Dict[str, TaskResult] = {}
        for task in self.tasks:
            task_status = self._normalize_task_status(task.status)
            failure = None
            if task_status == TaskStatus.FAILED and task.output:
                failure = FailureRecord(message=task.output)
            results[task.id] = TaskResult(
                task_id=task.id,
                status=task_status,
                agent_name=task.assigned_to,
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
                    created_at=decision.get("at", datetime.utcnow().isoformat()),
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

    def summary(self) -> str:
        done = sum(1 for t in self.tasks if t.status == TaskStatus.DONE.value)
        return f"Project: {self.project_name} | Phase: {self.phase} | Tasks: {done}/{len(self.tasks)} done"
