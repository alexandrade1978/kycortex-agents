"""Public typed contracts for agent input/output, workflow state, and persisted records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "AgentInput",
    "AgentOutput",
    "ExecutionSandboxPolicy",
    "ArtifactRecord",
    "ArtifactType",
    "DecisionRecord",
    "FailureCategory",
    "FailureRecord",
    "ProjectSnapshot",
    "TaskResult",
    "TaskStatus",
    "WorkflowOutcome",
    "WorkflowStatus",
    "utc_now_iso",
]


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""

    return datetime.now(timezone.utc).isoformat()


class TaskStatus(str, Enum):
    """Lifecycle states for persisted workflow tasks."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    """Lifecycle states for overall workflow execution."""

    INIT = "init"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"


class WorkflowOutcome(str, Enum):
    """Terminal outcomes for workflow executions under the production contract."""

    COMPLETED = "completed"
    FAILED = "failed"
    DEGRADED = "degraded"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class FailureCategory(str, Enum):
    """Normalized failure categories for task and workflow failures."""

    UNKNOWN = "unknown"
    TASK_EXECUTION = "task_execution"
    CODE_VALIDATION = "code_validation"
    TEST_VALIDATION = "test_validation"
    DEPENDENCY_VALIDATION = "dependency_validation"
    WORKFLOW_BLOCKED = "workflow_blocked"
    WORKFLOW_DEFINITION = "workflow_definition"
    REPAIR_BUDGET_EXHAUSTED = "repair_budget_exhausted"


class ArtifactType(str, Enum):
    """Normalized artifact categories emitted by agents and snapshots."""

    TEXT = "text"
    CODE = "code"
    DOCUMENT = "document"
    TEST = "test"
    CONFIG = "config"
    OTHER = "other"


@dataclass
class ExecutionSandboxPolicy:
    """Runtime policy describing how generated artifacts are isolated during execution."""

    enabled: bool = True
    allow_network: bool = False
    allow_subprocesses: bool = False
    max_cpu_seconds: float = 30.0
    max_memory_mb: int = 512
    temp_root: Optional[str] = None
    disable_pytest_plugin_autoload: bool = True
    sanitized_env: Dict[str, str] = field(default_factory=dict)


@dataclass
class ArtifactRecord:
    """Structured artifact entry captured from an agent output or project snapshot."""

    name: str
    artifact_type: ArtifactType = ArtifactType.OTHER
    path: Optional[str] = None
    content: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionRecord:
    """Structured project decision captured during workflow execution."""

    topic: str
    decision: str
    rationale: str
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureRecord:
    """Normalized failure details exposed through task results and snapshots."""

    message: str
    error_type: str = "runtime_error"
    category: str = FailureCategory.UNKNOWN.value
    retryable: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentInput:
    """Validated input payload passed into an agent execution entrypoint."""

    task_id: str
    task_title: str
    task_description: str
    project_name: str
    project_goal: str
    context: Dict[str, Any] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)


@dataclass
class AgentOutput:
    """Normalized agent result payload persisted back into workflow state."""

    summary: str
    raw_content: str
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    decisions: List[DecisionRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Public task-result view exposed through workflow snapshots."""

    task_id: str
    status: TaskStatus
    agent_name: str
    output: Optional[AgentOutput] = None
    failure: Optional[FailureRecord] = None
    details: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class ProjectSnapshot:
    """Immutable workflow snapshot consumed by agents, callers, and tests."""

    project_name: str
    goal: str
    workflow_status: WorkflowStatus = WorkflowStatus.INIT
    phase: str = "init"
    acceptance_policy: Optional[str] = None
    terminal_outcome: Optional[str] = None
    failure_category: Optional[str] = None
    acceptance_criteria_met: bool = False
    acceptance_evaluation: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_resumed_at: Optional[str] = None
    repair_cycle_count: int = 0
    repair_max_cycles: int = 0
    repair_budget_remaining: int = 0
    repair_history: List[Dict[str, Any]] = field(default_factory=list)
    task_results: Dict[str, TaskResult] = field(default_factory=dict)
    decisions: List[DecisionRecord] = field(default_factory=list)
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    execution_events: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)
