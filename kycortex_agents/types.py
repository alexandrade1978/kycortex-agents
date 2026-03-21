from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    INIT = "init"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"


class ArtifactType(str, Enum):
    TEXT = "text"
    CODE = "code"
    DOCUMENT = "document"
    TEST = "test"
    CONFIG = "config"
    OTHER = "other"


@dataclass
class ArtifactRecord:
    name: str
    artifact_type: ArtifactType = ArtifactType.OTHER
    path: Optional[str] = None
    content: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionRecord:
    topic: str
    decision: str
    rationale: str
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureRecord:
    message: str
    error_type: str = "runtime_error"
    retryable: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentInput:
    task_id: str
    task_title: str
    task_description: str
    project_name: str
    project_goal: str
    context: Dict[str, Any] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)


@dataclass
class AgentOutput:
    summary: str
    raw_content: str
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    decisions: List[DecisionRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    task_id: str
    status: TaskStatus
    agent_name: str
    output: Optional[AgentOutput] = None
    failure: Optional[FailureRecord] = None
    started_at: str = field(default_factory=utc_now_iso)
    completed_at: Optional[str] = None


@dataclass
class ProjectSnapshot:
    project_name: str
    goal: str
    workflow_status: WorkflowStatus = WorkflowStatus.INIT
    phase: str = "init"
    task_results: Dict[str, TaskResult] = field(default_factory=dict)
    decisions: List[DecisionRecord] = field(default_factory=list)
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)
