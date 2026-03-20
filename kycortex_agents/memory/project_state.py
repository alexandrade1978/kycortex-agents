import json, os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime

@dataclass
class Task:
    id: str
    title: str
    description: str
    assigned_to: str
    status: str = "pending"
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

    def complete_task(self, task_id: str, output: str):
        for t in self.tasks:
            if t.id == task_id:
                t.status = "done"
                t.output = output
                t.completed_at = datetime.utcnow().isoformat()

    def add_decision(self, topic: str, decision: str, rationale: str):
        self.decisions.append({"topic": topic, "decision": decision, "rationale": rationale, "at": datetime.utcnow().isoformat()})

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
        return [t for t in self.tasks if t.status == "pending"]

    def summary(self) -> str:
        done = sum(1 for t in self.tasks if t.status == "done")
        return f"Project: {self.project_name} | Phase: {self.phase} | Tasks: {done}/{len(self.tasks)} done"
