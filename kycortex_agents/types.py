"""Public typed contracts for agent input/output, workflow state, and persisted records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, TypeAlias, TypedDict

__all__ = [
    "AgentView",
    "AgentViewArtifactRecord",
    "AgentViewDecisionRecord",
    "AgentViewTaskResult",
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
    "WorkflowRepairHistoryEntry",
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

    has_samples: bool
    has_multiple_samples: bool


class TaskResourceTelemetry(TypedDict):
    """Per-task normalized timing and provider-usage summary exposed through task results."""

    has_provider_call: bool
    has_task_duration: bool
    has_last_attempt_duration: bool
    has_provider_duration: bool
    usage: NumericMetricMap


class InternalMetricDistribution(TypedDict):
    """Exact numeric distribution used by internal runtime telemetry."""

    count: int
    total: MetricValue
    min: MetricValue
    max: MetricValue
    avg: MetricValue


class InternalTaskRuntimeTelemetry(TypedDict):
    """Internal per-task runtime telemetry intended for operator-only surfaces."""

    status: str
    agent_name: str
    has_provider_call: bool
    provider: Optional[str]
    model: Optional[str]
    success: Optional[bool]
    attempts_used: int
    retry_attempt_count: int
    task_duration_ms: MetricValue
    last_attempt_duration_ms: MetricValue
    provider_duration_ms: MetricValue
    provider_latency_ms: MetricValue
    usage: NumericMetricMap
    provider_health: Dict[str, Dict[str, Any]]


class InternalWorkflowResumeSummary(TypedDict):
    """Exact workflow resume telemetry intended for internal operator surfaces."""

    resume_event_count: int
    reason_counts: Dict[str, int]
    resumed_task_count: int
    unique_task_count: int
    last_resumed_at: Optional[str]


class InternalWorkflowRepairSummary(TypedDict):
    """Exact workflow repair telemetry intended for internal operator surfaces."""

    cycle_count: int
    max_cycles: int
    budget_remaining: int
    history_count: int
    reason_counts: Dict[str, int]
    failure_category_counts: Dict[str, int]
    failed_task_count: int


class InternalWorkflowProviderSummary(TypedDict):
    """Exact per-provider workflow telemetry intended for internal operator surfaces."""

    task_count: int
    success_count: int
    failure_count: int
    attempt_count: int
    retry_attempt_count: int
    models: List[str]
    duration_ms: InternalMetricDistribution
    usage: NumericMetricMap


class InternalWorkflowProviderHealthSummary(TypedDict):
    """Exact per-provider health telemetry intended for internal operator surfaces."""

    models: List[str]
    status_counts: Dict[str, int]
    last_outcome_counts: Dict[str, int]
    retryable_failure_count: int
    active_health_check_count: int


class InternalWorkflowFallbackSummary(TypedDict):
    """Exact workflow fallback telemetry intended for internal operator surfaces."""

    task_count: int
    entry_count: int
    providers: List[str]
    statuses: List[str]


class InternalWorkflowErrorSummary(TypedDict):
    """Exact workflow error telemetry intended for internal operator surfaces."""

    final_error_count: int
    fallback_error_count: int


class InternalWorkflowTelemetry(TypedDict):
    """Exact aggregate workflow telemetry intended for internal operator surfaces."""

    task_count: int
    task_status_counts: Dict[str, int]
    tasks_with_provider_calls: int
    tasks_without_provider_calls: int
    acceptance_evaluation: Dict[str, Any]
    resume_summary: InternalWorkflowResumeSummary
    repair_summary: InternalWorkflowRepairSummary
    final_providers: List[str]
    observed_providers: List[str]
    provider_summary: Dict[str, InternalWorkflowProviderSummary]
    provider_health_summary: Dict[str, InternalWorkflowProviderHealthSummary]
    attempt_count: int
    retry_attempt_count: int
    duration_ms: InternalMetricDistribution
    usage: NumericMetricMap
    fallback_summary: InternalWorkflowFallbackSummary
    error_summary: InternalWorkflowErrorSummary


class InternalRuntimeTelemetry(TypedDict):
    """Internal runtime telemetry view intended for operator and UI surfaces."""

    project_name: str
    goal: str
    workflow_status: WorkflowStatus
    phase: str
    acceptance_policy: Optional[str]
    terminal_outcome: Optional[str]
    failure_category: Optional[str]
    acceptance_criteria_met: bool
    workflow: InternalWorkflowTelemetry
    tasks: Dict[str, InternalTaskRuntimeTelemetry]
    updated_at: str


class WorkflowAcceptanceSummary(TypedDict):
    """Workflow-level acceptance outcome summary embedded in aggregate telemetry."""

    policy: Optional[str]
    accepted: bool
    has_reason: bool
    terminal_outcome: Optional[str]
    failure_category: Optional[str]
    has_evaluated_tasks: bool
    has_required_tasks: bool
    has_completed_tasks: bool
    has_failed_tasks: bool
    has_skipped_tasks: bool
    has_pending_tasks: bool


def empty_workflow_acceptance_summary() -> WorkflowAcceptanceSummary:
    return {
        "policy": None,
        "accepted": False,
        "has_reason": False,
        "terminal_outcome": None,
        "failure_category": None,
        "has_evaluated_tasks": False,
        "has_required_tasks": False,
        "has_completed_tasks": False,
        "has_failed_tasks": False,
        "has_skipped_tasks": False,
        "has_pending_tasks": False,
    }


class WorkflowProgressSummary(TypedDict):
    """Workflow execution-progress summary embedded in aggregate telemetry."""

    has_pending_tasks: bool
    has_running_tasks: bool
    has_runnable_tasks: bool
    has_blocked_tasks: bool
    has_terminal_tasks: bool
    all_tasks_terminal: bool


class WorkflowResumeSummary(TypedDict):
    """Workflow resume activity summary embedded in aggregate telemetry."""

    has_multiple_resume_events: bool
    has_multiple_reasons: bool
    has_multiple_resumed_tasks: bool
    has_multiple_unique_tasks: bool
    has_last_resumed_at: bool


class WorkflowRepairSummary(TypedDict):
    """Workflow repair-cycle usage summary embedded in aggregate telemetry."""

    has_repair_cycles: bool
    max_cycles: int
    budget_remaining: int
    has_multiple_history_entries: bool
    has_multiple_reasons: bool
    last_reason_present: bool
    has_multiple_failure_categories: bool
    has_failed_tasks: bool


class WorkflowRepairHistoryEntry(TypedDict):
    """Public workflow repair-history entry exposed through snapshots."""

    cycle: int
    has_started_at: bool
    has_reason: bool
    failure_category: Optional[str]
    has_failed_tasks: bool
    has_budget_remaining: bool


class WorkflowProviderSummary(TypedDict):
    """Per-provider aggregate telemetry rolled up across workflow execution."""

    has_multiple_tasks: bool
    has_successes: bool
    has_failures: bool
    has_attempts: bool
    has_retry_attempts: bool
    duration_ms: MetricDistribution
    usage: NumericMetricMap


class WorkflowProviderHealthSummary(TypedDict):
    """Per-provider health-state aggregate rolled up across workflow execution."""

    models: List[str]
    status_presence: Dict[str, bool]
    last_outcome_presence: Dict[str, bool]
    has_retryable_failures: bool
    has_active_checks: bool


class WorkflowFallbackSummary(TypedDict):
    """Workflow-level fallback routing summary embedded in aggregate telemetry."""

    has_multiple_tasks: bool
    has_entries: bool
    has_multiple_providers: bool
    has_multiple_statuses: bool


class WorkflowErrorSummary(TypedDict):
    """Workflow-level final and fallback error tallies."""

    has_final_errors: bool
    has_fallback_errors: bool


class WorkflowTelemetry(TypedDict):
    """Aggregate workflow observability payload exposed through public snapshots."""

    has_multiple_tasks: bool
    task_status_presence: Dict[str, bool]
    progress_summary: WorkflowProgressSummary
    has_tasks_with_provider_calls: bool
    has_tasks_without_provider_calls: bool
    acceptance_summary: WorkflowAcceptanceSummary
    resume_summary: WorkflowResumeSummary
    repair_summary: WorkflowRepairSummary
    has_multiple_final_providers: bool
    has_multiple_observed_providers: bool
    provider_summary: Dict[str, WorkflowProviderSummary]
    provider_health_summary: Dict[str, WorkflowProviderHealthSummary]
    has_attempts: bool
    has_retry_attempts: bool
    duration_ms: MetricDistribution
    usage: NumericMetricMap
    fallback_summary: WorkflowFallbackSummary
    error_summary: WorkflowErrorSummary


def _empty_metric_distribution() -> MetricDistribution:
    return {
        "has_samples": False,
        "has_multiple_samples": False,
    }


def empty_task_resource_telemetry() -> TaskResourceTelemetry:
    return {
        "has_provider_call": False,
        "has_task_duration": False,
        "has_last_attempt_duration": False,
        "has_provider_duration": False,
        "usage": {},
    }


def empty_workflow_telemetry() -> WorkflowTelemetry:
    return {
        "has_multiple_tasks": False,
        "task_status_presence": {},
        "progress_summary": {
            "has_pending_tasks": False,
            "has_running_tasks": False,
            "has_runnable_tasks": False,
            "has_blocked_tasks": False,
            "has_terminal_tasks": False,
            "all_tasks_terminal": False,
        },
        "has_tasks_with_provider_calls": False,
        "has_tasks_without_provider_calls": False,
        "acceptance_summary": empty_workflow_acceptance_summary(),
        "resume_summary": {
            "has_multiple_resume_events": False,
            "has_multiple_reasons": False,
            "has_multiple_resumed_tasks": False,
            "has_multiple_unique_tasks": False,
            "has_last_resumed_at": False,
        },
        "repair_summary": {
            "has_repair_cycles": False,
            "max_cycles": 0,
            "budget_remaining": 0,
            "has_multiple_history_entries": False,
            "has_multiple_reasons": False,
            "last_reason_present": False,
            "has_multiple_failure_categories": False,
            "has_failed_tasks": False,
        },
        "has_multiple_final_providers": False,
        "has_multiple_observed_providers": False,
        "provider_summary": {},
        "provider_health_summary": {},
        "has_attempts": False,
        "has_retry_attempts": False,
        "duration_ms": _empty_metric_distribution(),
        "usage": {},
        "fallback_summary": {
            "has_multiple_tasks": False,
            "has_entries": False,
            "has_multiple_providers": False,
            "has_multiple_statuses": False,
        },
        "error_summary": {
            "has_final_errors": False,
            "has_fallback_errors": False,
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
class AgentViewDecisionRecord:
    """Filtered decision record exposed to agent prompt context."""

    topic: str
    decision: str
    rationale: str
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class AgentViewArtifactRecord:
    """Filtered artifact record exposed to agent prompt context."""

    name: str
    artifact_type: ArtifactType = ArtifactType.OTHER
    content: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    source_task_id: Optional[str] = None


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
class AgentViewTaskResult:
    """Filtered task-result summary exposed to agent prompt context."""

    task_id: str
    status: TaskStatus
    agent_name: str
    has_output: bool = False
    failure_category: Optional[str] = None
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
    acceptance_evaluation: WorkflowAcceptanceSummary = field(default_factory=empty_workflow_acceptance_summary)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_resumed_at: Optional[str] = None
    repair_cycle_count: int = 0
    repair_history: List[WorkflowRepairHistoryEntry] = field(default_factory=list)
    task_results: Dict[str, TaskResult] = field(default_factory=dict)
    decisions: List[DecisionRecord] = field(default_factory=list)
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    execution_events: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class AgentView:
    """Filtered workflow view consumed by agents during task execution."""

    project_name: str
    goal: str
    workflow_status: WorkflowStatus = WorkflowStatus.INIT
    phase: str = "init"
    acceptance_policy: Optional[str] = None
    terminal_outcome: Optional[str] = None
    failure_category: Optional[str] = None
    acceptance_criteria_met: bool = False
    task_results: Dict[str, AgentViewTaskResult] = field(default_factory=dict)
    decisions: List[AgentViewDecisionRecord] = field(default_factory=list)
    artifacts: List[AgentViewArtifactRecord] = field(default_factory=list)
