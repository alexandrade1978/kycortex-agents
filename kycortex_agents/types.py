"""Public typed contracts for agent input/output, workflow state, and persisted records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, TypeAlias, TypedDict

__all__ = [
    "AgentInput",
    "AgentOutput",
    "ExecutionSandboxPolicy",
    "ArtifactRecord",
    "ArtifactType",
    "DecisionRecord",
    "FailureCategory",
    "FailureRecord",
    "MetricDistribution",
    "ProjectSnapshot",
    "TaskResult",
    "TaskResourceTelemetry",
    "TaskStatus",
    "WorkflowAcceptanceSummary",
    "WorkflowErrorSummary",
    "WorkflowFallbackSummary",
    "WorkflowOutcome",
    "WorkflowProgressSummary",
    "WorkflowProviderHealthSummary",
    "WorkflowProviderSummary",
    "WorkflowRepairSummary",
    "WorkflowResumeSummary",
    "WorkflowStatus",
    "WorkflowTelemetry",
    "utc_now_iso",
]


MetricNumber: TypeAlias = int | float
MetricValue: TypeAlias = int | float | None
NumericMetricMap: TypeAlias = Dict[str, MetricNumber]


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
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class WorkflowOutcome(str, Enum):
    """Terminal outcomes for workflow executions under the production contract."""

    COMPLETED = "completed"
    FAILED = "failed"
    DEGRADED = "degraded"
    CANCELLED = "cancelled"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class FailureCategory(str, Enum):
    """Normalized failure categories for task and workflow failures."""

    UNKNOWN = "unknown"
    TASK_EXECUTION = "task_execution"
    PROVIDER_TRANSIENT = "provider_transient"
    SANDBOX_SECURITY_VIOLATION = "sandbox_security_violation"
    CODE_VALIDATION = "code_validation"
    TEST_VALIDATION = "test_validation"
    DEPENDENCY_VALIDATION = "dependency_validation"
    WORKFLOW_BLOCKED = "workflow_blocked"
    WORKFLOW_CANCELLED = "workflow_cancelled"
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


class MetricDistribution(TypedDict):
    """Normalized numeric distribution used by aggregate telemetry summaries."""

    count: int
    total: MetricNumber
    min: MetricValue
    max: MetricValue
    avg: MetricValue


class TaskResourceTelemetry(TypedDict):
    """Per-task normalized timing and provider-usage summary exposed through task results."""

    has_provider_call: bool
    provider: Optional[str]
    model: Optional[str]
    task_duration_ms: MetricValue
    last_attempt_duration_ms: MetricValue
    provider_duration_ms: MetricValue
    usage: NumericMetricMap


class WorkflowAcceptanceSummary(TypedDict):
    """Workflow-level acceptance outcome summary embedded in aggregate telemetry."""

    policy: Optional[str]
    accepted: bool
    reason: Optional[str]
    terminal_outcome: Optional[str]
    failure_category: Optional[str]
    evaluated_task_count: int
    required_task_count: int
    completed_task_count: int
    failed_task_count: int
    skipped_task_count: int
    pending_task_count: int


class WorkflowProgressSummary(TypedDict):
    """Workflow execution-progress summary embedded in aggregate telemetry."""

    pending_task_count: int
    running_task_count: int
    runnable_task_count: int
    blocked_task_count: int
    terminal_task_count: int
    completion_percent: MetricValue


class WorkflowResumeSummary(TypedDict):
    """Workflow resume activity summary embedded in aggregate telemetry."""

    count: int
    reasons: Dict[str, int]
    task_count: int
    unique_task_count: int
    unique_task_ids: List[str]
    last_resumed_at: Optional[str]


class WorkflowRepairSummary(TypedDict):
    """Workflow repair-cycle usage summary embedded in aggregate telemetry."""

    cycle_count: int
    max_cycles: int
    budget_remaining: int
    history_count: int
    reasons: Dict[str, int]
    last_reason: Optional[str]
    failure_categories: Dict[str, int]
    failed_task_count: int
    failed_task_ids: List[str]


class WorkflowProviderSummary(TypedDict):
    """Per-provider aggregate telemetry rolled up across workflow execution."""

    task_count: int
    success_count: int
    failure_count: int
    attempt_count: int
    retry_attempt_count: int
    duration_ms: MetricDistribution
    usage: NumericMetricMap


class WorkflowProviderHealthSummary(TypedDict):
    """Per-provider health-state aggregate rolled up across workflow execution."""

    models: List[str]
    status_counts: Dict[str, int]
    last_outcome_counts: Dict[str, int]
    circuit_open_count: int
    retryable_failure_count: int
    active_health_check_count: int
    last_error_types: Dict[str, int]


class WorkflowFallbackSummary(TypedDict):
    """Workflow-level fallback routing summary embedded in aggregate telemetry."""

    task_count: int
    entry_count: int
    by_provider: Dict[str, int]
    by_status: Dict[str, int]


class WorkflowErrorSummary(TypedDict):
    """Workflow-level final and fallback error-type tallies."""

    final_error_types: Dict[str, int]
    fallback_error_types: Dict[str, int]


class WorkflowTelemetry(TypedDict):
    """Aggregate workflow observability payload exposed through public snapshots."""

    task_count: int
    task_status_counts: Dict[str, int]
    progress_summary: WorkflowProgressSummary
    tasks_with_provider_calls: int
    tasks_without_provider_calls: int
    acceptance_summary: WorkflowAcceptanceSummary
    resume_summary: WorkflowResumeSummary
    repair_summary: WorkflowRepairSummary
    final_providers: List[str]
    observed_providers: List[str]
    provider_summary: Dict[str, WorkflowProviderSummary]
    provider_health_summary: Dict[str, WorkflowProviderHealthSummary]
    attempt_count: int
    retry_attempt_count: int
    duration_ms: MetricDistribution
    usage: NumericMetricMap
    fallback_summary: WorkflowFallbackSummary
    error_summary: WorkflowErrorSummary


def _empty_metric_distribution() -> MetricDistribution:
    return {
        "count": 0,
        "total": 0,
        "min": None,
        "max": None,
        "avg": None,
    }


def empty_task_resource_telemetry() -> TaskResourceTelemetry:
    return {
        "has_provider_call": False,
        "provider": None,
        "model": None,
        "task_duration_ms": None,
        "last_attempt_duration_ms": None,
        "provider_duration_ms": None,
        "usage": {},
    }


def empty_workflow_telemetry() -> WorkflowTelemetry:
    return {
        "task_count": 0,
        "task_status_counts": {},
        "progress_summary": {
            "pending_task_count": 0,
            "running_task_count": 0,
            "runnable_task_count": 0,
            "blocked_task_count": 0,
            "terminal_task_count": 0,
            "completion_percent": 0,
        },
        "tasks_with_provider_calls": 0,
        "tasks_without_provider_calls": 0,
        "acceptance_summary": {
            "policy": None,
            "accepted": False,
            "reason": None,
            "terminal_outcome": None,
            "failure_category": None,
            "evaluated_task_count": 0,
            "required_task_count": 0,
            "completed_task_count": 0,
            "failed_task_count": 0,
            "skipped_task_count": 0,
            "pending_task_count": 0,
        },
        "resume_summary": {
            "count": 0,
            "reasons": {},
            "task_count": 0,
            "unique_task_count": 0,
            "unique_task_ids": [],
            "last_resumed_at": None,
        },
        "repair_summary": {
            "cycle_count": 0,
            "max_cycles": 0,
            "budget_remaining": 0,
            "history_count": 0,
            "reasons": {},
            "last_reason": None,
            "failure_categories": {},
            "failed_task_count": 0,
            "failed_task_ids": [],
        },
        "final_providers": [],
        "observed_providers": [],
        "provider_summary": {},
        "provider_health_summary": {},
        "attempt_count": 0,
        "retry_attempt_count": 0,
        "duration_ms": _empty_metric_distribution(),
        "usage": {},
        "fallback_summary": {
            "task_count": 0,
            "entry_count": 0,
            "by_provider": {},
            "by_status": {},
        },
        "error_summary": {
            "final_error_types": {},
            "fallback_error_types": {},
        },
    }


@dataclass
class ExecutionSandboxPolicy:
    """Runtime policy describing how generated artifacts are isolated during execution."""

    enabled: bool = True
    allow_network: bool = False
    allow_subprocesses: bool = False
    max_cpu_seconds: float = 30.0
    max_wall_clock_seconds: float = 60.0
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
    resource_telemetry: TaskResourceTelemetry = field(default_factory=empty_task_resource_telemetry)
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
    workflow_telemetry: WorkflowTelemetry = field(default_factory=empty_workflow_telemetry)
    decisions: List[DecisionRecord] = field(default_factory=list)
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    execution_events: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)
