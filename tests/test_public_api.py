import kycortex_agents
import importlib
import os
from pathlib import Path
import subprocess
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 in CI
    tomllib = importlib.import_module("tomli")

from kycortex_agents import config as config_module
from kycortex_agents import exceptions as exceptions_module
from kycortex_agents import types as types_module
from kycortex_agents.agents import registry as registry_module
from kycortex_agents.memory import project_state as project_state_module
from kycortex_agents.memory import state_store as state_store_module
from kycortex_agents.providers import BaseLLMProvider as ProviderBaseLLMProvider
from kycortex_agents.providers import AnthropicProvider as ProviderAnthropicProvider
from kycortex_agents.providers import OllamaProvider as ProviderOllamaProvider
from kycortex_agents.providers import OpenAIProvider as ProviderOpenAIProvider
from kycortex_agents.providers import probe_provider_health
from kycortex_agents.providers import factory as provider_factory_module
from kycortex_agents import (
    AgentRegistry,
    AnthropicProvider,
    ArchitectAgent,
    BaseStateStore,
    BaseAgent,
    CodeEngineerAgent,
    CodeReviewerAgent,
    DependencyManagerAgent,
    DEFAULT_CONFIG,
    DocsWriterAgent,
    KYCortexConfig,
    JsonStateStore,
    LegalAdvisorAgent,
    OllamaProvider,
    Orchestrator,
    ProjectState,
    ProviderTransientError,
    QATesterAgent,
    SqliteStateStore,
    StatePersistenceError,
    Task,
    WorkflowDefinitionError,
    __version__,
    resolve_state_store,
)
from kycortex_agents.memory import ProjectState as MemoryProjectState
from kycortex_agents.memory import Task as MemoryTask
from kycortex_agents.workflows import (
    Orchestrator as WorkflowOrchestrator,
    ProjectState as WorkflowProjectState,
    Task as WorkflowTask,
    TaskStatus as WorkflowTaskStatus,
    WorkflowDefinitionError as WorkflowModuleDefinitionError,
    WorkflowStatus as WorkflowModuleStatus,
)


def test_public_api_exports_core_symbols():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert kycortex_agents.__version__ == pyproject["project"]["version"]
    assert __version__ == pyproject["project"]["version"]
    assert Orchestrator is not None
    assert KYCortexConfig is not None
    assert ProjectState is MemoryProjectState
    assert Task is MemoryTask
    assert AgentRegistry is not None
    assert AnthropicProvider is not None
    assert BaseAgent is not None
    assert BaseStateStore is not None
    assert JsonStateStore is not None
    assert OllamaProvider is not None
    assert resolve_state_store is not None
    assert SqliteStateStore is not None
    assert DEFAULT_CONFIG is not None
    assert StatePersistenceError is not None
    assert ProviderTransientError is not None
    assert probe_provider_health is not None
    assert WorkflowDefinitionError is not None


def test_public_package_import_does_not_create_output_dir(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    env = {
        key: value
        for key, value in os.environ.items()
        if not (key.startswith("COV_CORE_") or key.startswith("COVERAGE"))
    }
    python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(repo_root) if not python_path else f"{repo_root}{os.pathsep}{python_path}"

    completed = subprocess.run(
        [sys.executable, "-c", "import kycortex_agents"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "output").exists()


def test_public_api_exports_core_agent_types():
    assert ArchitectAgent is not None
    assert CodeEngineerAgent is not None
    assert CodeReviewerAgent is not None
    assert DependencyManagerAgent is not None
    assert DocsWriterAgent is not None
    assert LegalAdvisorAgent is not None
    assert QATesterAgent is not None


def test_workflows_module_exports_stable_workflow_surface():
    assert WorkflowOrchestrator is Orchestrator
    assert WorkflowProjectState is MemoryProjectState
    assert WorkflowTask is MemoryTask
    assert WorkflowTaskStatus is not None
    assert WorkflowModuleStatus is not None
    assert WorkflowModuleDefinitionError is WorkflowDefinitionError


def test_public_contract_modules_define_explicit_exports():
    assert config_module.__all__ == [
        "DEFAULT_CONFIG",
        "DEFAULT_PROVIDER_BASE_URLS",
        "KYCortexConfig",
        "PROVIDER_ENV_VARS",
    ]
    assert exceptions_module.__all__ == [
        "AgentExecutionError",
        "ConfigValidationError",
        "KYCortexError",
        "ProviderConfigurationError",
        "ProviderTransientError",
        "StatePersistenceError",
        "WorkflowDefinitionError",
    ]
    assert types_module.__all__ == [
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


def test_public_extension_modules_define_explicit_exports():
    assert registry_module.__all__ == ["AgentRegistry", "build_default_registry"]
    assert provider_factory_module.__all__ == ["create_provider", "probe_provider_health"]
    assert state_store_module.__all__ == [
        "BaseStateStore",
        "JsonStateStore",
        "SqliteStateStore",
        "resolve_state_store",
    ]


def test_root_package_exposes_public_module_namespaces():
    assert kycortex_agents.agents is not None
    assert kycortex_agents.config is config_module
    assert kycortex_agents.exceptions is exceptions_module
    assert kycortex_agents.memory is not None
    assert kycortex_agents.providers is not None
    assert kycortex_agents.types is types_module
    assert kycortex_agents.workflows is not None


def test_public_package_modules_define_module_docstrings():
    assert kycortex_agents.__doc__ == "Public agent orchestration and configuration for multi-provider LLM workflows."
    assert kycortex_agents.agents.__doc__ == "Public agent implementations and registry helpers for workflow execution."
    assert kycortex_agents.providers.__doc__ == "Public provider interfaces and built-in OpenAI, Anthropic, and Ollama integrations."
    assert kycortex_agents.memory.__doc__ == "Public project-state models and persistence backends for workflow storage."
    assert kycortex_agents.workflows.__doc__ == "Public workflow-facing imports for orchestration state, tasks, and statuses."


def test_public_state_store_module_defines_docstrings():
    assert state_store_module.__doc__ == "Public persistence backends for JSON and SQLite project-state storage."
    assert state_store_module.JsonStateStore.__doc__ == "JSON-file persistence backend that saves project state atomically on disk."
    assert state_store_module.SqliteStateStore.__doc__ == "SQLite persistence backend that stores the latest project-state payload transactionally."
    assert state_store_module.resolve_state_store.__doc__ == "Return the built-in persistence backend that matches the target state-file extension."


def test_public_config_and_factory_modules_define_docstrings():
    assert config_module.__doc__ == "Public runtime configuration model and provider environment-variable mappings."
    assert config_module.KYCortexConfig.__doc__ == "Public runtime configuration for providers, workflow behavior, and outputs."
    assert config_module.KYCortexConfig.__post_init__.__doc__ == "Normalize defaults, resolve provider settings, validate config, and create output storage."
    assert config_module.KYCortexConfig._resolve_api_key.__doc__ == "Resolve the configured provider API key from the matching environment variable."
    assert config_module.KYCortexConfig._validate_static_config.__doc__ == "Validate static configuration values that do not require provider instantiation."
    assert config_module.KYCortexConfig.validate_runtime.__doc__ == "Validate provider-specific runtime requirements such as credentials and base URLs."
    assert provider_factory_module.__doc__ == "Public provider-factory helpers for resolving built-in LLM backends."
    assert provider_factory_module.create_provider.__doc__ == "Instantiate the built-in provider configured by the supplied runtime settings."
    assert provider_factory_module.probe_provider_health.__doc__ == "Instantiate the built-in provider and return a structured health snapshot."


def test_public_type_module_defines_docstrings():
    assert types_module.__doc__ == "Public typed contracts for agent input/output, workflow state, and persisted records."
    assert types_module.utc_now_iso.__doc__ == "Return the current UTC timestamp in ISO-8601 format."
    assert types_module.TaskStatus.__doc__ == "Lifecycle states for persisted workflow tasks."
    assert types_module.WorkflowStatus.__doc__ == "Lifecycle states for overall workflow execution."
    assert types_module.ArtifactType.__doc__ == "Normalized artifact categories emitted by agents and snapshots."
    assert types_module.MetricDistribution.__doc__ == "Normalized numeric distribution used by aggregate telemetry summaries."
    assert types_module.ArtifactRecord.__doc__ == "Structured artifact entry captured from an agent output or project snapshot."
    assert types_module.DecisionRecord.__doc__ == "Structured project decision captured during workflow execution."
    assert types_module.FailureRecord.__doc__ == "Normalized failure details exposed through task results and snapshots."
    assert types_module.TaskResourceTelemetry.__doc__ == "Per-task normalized timing and provider-usage summary exposed through task results."
    assert types_module.AgentInput.__doc__ == "Validated input payload passed into an agent execution entrypoint."
    assert types_module.AgentOutput.__doc__ == "Normalized agent result payload persisted back into workflow state."
    assert types_module.TaskResult.__doc__ == "Public task-result view exposed through workflow snapshots."
    assert types_module.WorkflowAcceptanceSummary.__doc__ == "Workflow-level acceptance outcome summary embedded in aggregate telemetry."
    assert types_module.WorkflowProgressSummary.__doc__ == "Workflow execution-progress summary embedded in aggregate telemetry."
    assert types_module.WorkflowResumeSummary.__doc__ == "Workflow resume activity summary embedded in aggregate telemetry."
    assert types_module.WorkflowRepairHistoryEntry.__doc__ == "Public workflow repair-history entry exposed through snapshots."
    assert types_module.WorkflowRepairSummary.__doc__ == "Workflow repair-cycle usage summary embedded in aggregate telemetry."
    assert types_module.WorkflowProviderHealthSummary.__doc__ == "Per-provider health-state aggregate rolled up across workflow execution."
    assert types_module.WorkflowProviderSummary.__doc__ == "Per-provider aggregate telemetry rolled up across workflow execution."
    assert types_module.WorkflowFallbackSummary.__doc__ == "Workflow-level fallback routing summary embedded in aggregate telemetry."
    assert types_module.WorkflowErrorSummary.__doc__ == "Workflow-level final and fallback error tallies."
    assert types_module.WorkflowTelemetry.__doc__ == "Aggregate workflow observability payload exposed through public snapshots."
    assert types_module.ProjectSnapshot.__doc__ == "Immutable workflow snapshot consumed by agents, callers, and tests."


def test_private_empty_telemetry_helpers_return_zeroed_payloads():
    assert types_module._empty_metric_distribution() == {
        "count": 0,
        "total": 0,
        "min": None,
        "max": None,
        "avg": None,
    }
    assert types_module.empty_task_resource_telemetry() == {
        "has_provider_call": False,
        "task_duration_ms": None,
        "last_attempt_duration_ms": None,
        "provider_duration_ms": None,
        "usage": {},
    }
    assert types_module.empty_workflow_telemetry() == {
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
        "has_tasks_with_provider_calls": False,
        "has_tasks_without_provider_calls": False,
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
            "reason_count": 0,
            "task_count": 0,
            "unique_task_count": 0,
            "last_resumed_at": None,
        },
        "repair_summary": {
            "cycle_count": 0,
            "max_cycles": 0,
            "budget_remaining": 0,
            "history_count": 0,
            "reason_count": 0,
            "last_reason_present": False,
            "failure_category_count": 0,
            "failed_task_count": 0,
        },
        "final_provider_count": 0,
        "observed_provider_count": 0,
        "provider_summary": {},
        "provider_health_summary": {},
        "has_attempts": False,
        "has_retry_attempts": False,
        "duration_ms": {
            "count": 0,
            "total": 0,
            "min": None,
            "max": None,
            "avg": None,
        },
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


def test_public_extension_types_define_class_docstrings():
    assert ProviderBaseLLMProvider.__doc__ == "Abstract provider contract for model-backed agent text generation."
    assert ProviderOpenAIProvider.__doc__ == "OpenAI-backed provider implementation for chat completion models."
    assert ProviderAnthropicProvider.__doc__ == "Anthropic-backed provider implementation for Claude message models."
    assert ProviderOllamaProvider.__doc__ == "Ollama-backed provider implementation for local or remote open-source models."
    assert state_store_module.BaseStateStore.__doc__ == "Abstract persistence backend for saving and loading project state payloads."
    assert registry_module.AgentRegistry.__doc__ == "Registry that normalizes agent keys and resolves workflow agent instances."


def test_public_extension_types_define_method_docstrings():
    assert ProviderBaseLLMProvider.generate.__doc__ == "Return a model response for the given system and user prompts."
    assert ProviderBaseLLMProvider.get_last_call_metadata.__doc__ == "Return provider-specific metadata captured from the most recent model call."
    assert ProviderBaseLLMProvider.health_check.__doc__ == "Return a lightweight provider health snapshot without generating model output."
    assert state_store_module.BaseStateStore.save.__doc__ == "Persist the serialized project-state payload to the target path."
    assert state_store_module.BaseStateStore.load.__doc__ == "Load and return the serialized project-state payload from the target path."
    assert registry_module.AgentRegistry.register.__doc__ == "Register or replace an agent under the normalized registry key."
    assert registry_module.AgentRegistry.get.__doc__ == "Return the agent bound to the normalized key or raise when it is unknown."
    assert registry_module.AgentRegistry.has.__doc__ == "Return whether an agent is registered for the normalized key."
    assert registry_module.AgentRegistry.keys.__doc__ == "Return the normalized registry keys currently available."
    assert registry_module.AgentRegistry.normalize_key.__doc__ == "Normalize a registry key so workflow task assignments resolve consistently."


def test_project_state_public_api_defines_docstrings():
    assert project_state_module.Task.__doc__ == "Serializable workflow task record tracked inside a project state."
    assert project_state_module.ProjectState.__doc__ == "Mutable workflow state for tasks, decisions, artifacts, and execution metadata."
    assert project_state_module.ProjectState.add_task.__doc__ == "Append a task to the workflow and refresh the project timestamp."
    assert project_state_module.ProjectState.get_task.__doc__ == "Return the task with the matching identifier, if it exists."
    assert project_state_module.ProjectState.is_task_ready.__doc__ == "Return whether a pending task has all dependencies completed."
    assert project_state_module.ProjectState.start_task.__doc__ == "Mark a task as running and record timing plus audit metadata."
    assert project_state_module.ProjectState.fail_task.__doc__ == "Record a task failure, re-queueing it when retry budget remains."
    assert project_state_module.ProjectState.complete_task.__doc__ == "Mark a task complete and persist its raw or structured output payload."
    assert project_state_module.ProjectState.resume_interrupted_tasks.__doc__ == "Re-queue tasks left running by an interrupted workflow execution."
    assert project_state_module.ProjectState.resume_failed_tasks.__doc__ == "Re-queue failed tasks and dependency-skipped descendants for another run."
    assert project_state_module.ProjectState.should_retry_task.__doc__ == "Return whether a pending task is currently in its retry window."
    assert project_state_module.ProjectState.can_start_repair_cycle.__doc__ == "Return whether the workflow still has repair-cycle budget remaining."
    assert project_state_module.ProjectState.start_repair_cycle.__doc__ == "Record the start of a bounded repair cycle and persist its audit metadata."
    assert project_state_module.ProjectState.add_decision.__doc__ == "Append a lightweight project-level decision entry with a fresh timestamp."
    assert project_state_module.ProjectState.add_decision_record.__doc__ == "Append a structured decision record to the project history."
    assert project_state_module.ProjectState.add_artifact_record.__doc__ == "Append a structured artifact record to the project artifact list."
    assert project_state_module.ProjectState.mark_workflow_running.__doc__ == "Mark the workflow execution as active and emit a workflow-start event."
    assert project_state_module.ProjectState.mark_workflow_finished.__doc__ == "Mark the workflow finished under the supplied phase label."
    assert project_state_module.ProjectState.save.__doc__ == "Persist the current project state through the configured state-store backend."
    assert project_state_module.ProjectState.load.__doc__ == "Load a project state from disk and normalize legacy persisted fields."
    assert project_state_module.ProjectState.pending_tasks.__doc__ == "Return all tasks that are still pending execution."
    assert project_state_module.ProjectState.execution_plan.__doc__ == "Return tasks in dependency-safe topological execution order."
    assert project_state_module.ProjectState.runnable_tasks.__doc__ == "Return pending tasks whose dependencies are already satisfied."
    assert project_state_module.ProjectState.blocked_tasks.__doc__ == "Return pending tasks that are blocked by unfinished dependencies."
    assert project_state_module.ProjectState.skip_task.__doc__ == "Mark a task skipped and clear stale execution payloads or timing data."
    assert project_state_module.ProjectState.skip_dependent_tasks.__doc__ == "Skip all pending descendants of a failed dependency and return their ids."
    assert project_state_module.ProjectState.task_results.__doc__ == "Return normalized task-result snapshots keyed by task identifier."
    assert project_state_module.ProjectState.snapshot.__doc__ == "Build a normalized project snapshot for downstream orchestration and inspection."
    assert project_state_module.ProjectState.summary.__doc__ == "Return a compact human-readable summary of workflow progress."


def test_root_package_does_not_expose_internal_runtime_helpers():
    assert not hasattr(kycortex_agents, "_build_context")
    assert not hasattr(kycortex_agents, "_execute_agent")
    assert not hasattr(kycortex_agents, "_normalize_agent_result")


def test_readme_quick_start_uses_top_level_public_imports():
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    assert "from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task" in readme
    assert "from kycortex_agents.workflows import Orchestrator, ProjectState, Task" not in readme


def test_example_uses_top_level_public_imports():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_simple_project.py"
    example = example_path.read_text(encoding="utf-8")

    assert "from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task" in example
    assert "from kycortex_agents.workflows import Orchestrator, ProjectState, Task" not in example


def test_resume_example_uses_top_level_public_imports():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_resume_workflow.py"
    example = example_path.read_text(encoding="utf-8")

    assert "from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task" in example
    assert "from kycortex_agents.workflows import" not in example


def test_custom_agent_example_uses_top_level_public_imports():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_custom_agent.py"
    example = example_path.read_text(encoding="utf-8")

    assert "from kycortex_agents import AgentRegistry, ArtifactType, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task" in example
    assert "from kycortex_agents.types import AgentInput, AgentOutput" in example
    assert "from kycortex_agents.workflows import" not in example


def test_multi_provider_example_uses_top_level_public_imports():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_multi_provider.py"
    example = example_path.read_text(encoding="utf-8")

    assert "from kycortex_agents import KYCortexConfig, ProjectState, Task" in example
    assert "from kycortex_agents.workflows import" not in example


def test_test_mode_example_uses_top_level_public_imports():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_test_mode.py"
    example = example_path.read_text(encoding="utf-8")

    assert "from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task" in example
    assert "from kycortex_agents.workflows import" not in example


def test_complex_workflow_example_uses_top_level_public_imports():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_complex_workflow.py"
    example = example_path.read_text(encoding="utf-8")

    assert "from kycortex_agents import AgentRegistry, ArtifactType, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task" in example
    assert "from kycortex_agents.types import AgentInput, AgentOutput, DecisionRecord" in example
    assert "from kycortex_agents.workflows import" not in example


def test_failure_recovery_example_uses_top_level_public_imports():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_failure_recovery.py"
    example = example_path.read_text(encoding="utf-8")

    assert "from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task" in example
    assert "from kycortex_agents.workflows import" not in example


def test_snapshot_inspection_example_uses_public_runtime_imports():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_snapshot_inspection.py"
    example = example_path.read_text(encoding="utf-8")

    assert "from kycortex_agents import AgentRegistry, ArtifactType, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task" in example
    assert "from kycortex_agents.providers import BaseLLMProvider" in example
    assert "from kycortex_agents.types import AgentInput, AgentOutput, DecisionRecord" in example
    assert "from kycortex_agents.workflows import" not in example


def test_example_defines_dependency_aware_workflow_chain():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_simple_project.py"
    example = example_path.read_text(encoding="utf-8")

    assert 'id="task_1_arch"' in example
    assert 'id="task_2_code"' in example
    assert 'id="task_3_review"' in example
    assert 'dependencies=["task_1_arch"]' in example
    assert 'dependencies=["task_2_code"]' in example


def test_resume_example_documents_persisted_reload_and_resume_flow():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_resume_workflow.py"
    example = example_path.read_text(encoding="utf-8")

    assert 'state_file=state_path' in example
    assert 'workflow_resume_policy="resume_failed"' in example
    assert 'status="running"' in example
    assert 'project.save()' in example
    assert 'ProjectState.load(state_path)' in example
    assert 'orchestrator.execute_workflow(reloaded)' in example


def test_custom_agent_example_documents_public_extension_flow():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_custom_agent.py"
    example = example_path.read_text(encoding="utf-8")

    assert 'class SummaryAgent(BaseAgent):' in example
    assert 'required_context_keys = ("architecture",)' in example
    assert 'output_artifact_type = ArtifactType.DOCUMENT' in example
    assert 'def run_with_input(self, agent_input: AgentInput) -> AgentOutput:' in example
    assert 'self.require_context_value(agent_input, "architecture")' in example
    assert 'registry = AgentRegistry(' in example
    assert 'assigned_to="summary_agent"' in example
    assert 'dependencies=["arch"]' in example
    assert 'Orchestrator(config, registry=registry)' in example


def test_multi_provider_example_documents_supported_provider_switching():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_multi_provider.py"
    example = example_path.read_text(encoding="utf-8")

    assert 'def build_provider_configs() -> dict[str, KYCortexConfig]:' in example
    assert 'llm_provider="openai"' in example
    assert 'llm_provider="anthropic"' in example
    assert 'llm_provider="ollama"' in example
    assert 'llm_model="gpt-4o-mini"' in example
    assert 'llm_model="claude-haiku-4-5-20251001"' in example
    assert 'llm_model="qwen2.5-coder:7b"' in example
    assert 'base_url="http://localhost:11434"' in example
    assert 'ollama_num_ctx=16384' in example
    assert 'dependencies=["arch"]' in example
    assert 'Use one of these configurations with Orchestrator(config).execute_workflow(project).' in example


def test_test_mode_example_documents_deterministic_local_execution():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_test_mode.py"
    example = example_path.read_text(encoding="utf-8")

    assert 'class RecordingAgent(BaseAgent):' in example
    assert 'def build_test_registry(config: KYCortexConfig) -> AgentRegistry:' in example
    assert '"architect": RecordingAgent(config, "ARCHITECTURE READY")' in example
    assert '"code_engineer": RecordingAgent(config, "IMPLEMENTATION READY")' in example
    assert '"code_reviewer": RecordingAgent(config, "REVIEW COMPLETE")' in example
    assert 'def build_test_project() -> ProjectState:' in example
    assert 'dependencies=["arch"]' in example
    assert 'dependencies=["code"]' in example
    assert 'Orchestrator(config, registry=registry)' in example
    assert 'Deterministic test-mode workflow summary:' in example


def test_complex_workflow_example_documents_converging_dag_and_merge_context():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_complex_workflow.py"
    example = example_path.read_text(encoding="utf-8")

    assert 'class MergeDocumentationAgent(BaseAgent):' in example
    assert 'required_context_keys = ("architecture", "code", "review", "tests")' in example
    assert 'agent_input.context["artifacts"]' in example
    assert 'agent_input.context["decisions"]' in example
    assert 'dependencies=["arch"]' in example
    assert 'dependencies=["code"]' in example
    assert 'dependencies=["review", "tests"]' in example
    assert 'Complex workflow summary:' in example


def test_failure_recovery_example_documents_reload_and_resume_failed_flow():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_failure_recovery.py"
    example = example_path.read_text(encoding="utf-8")

    assert 'state_file=state_path' in example
    assert 'retry_limit=1' in example
    assert 'workflow_failure_policy="fail_fast"' in example
    assert 'workflow_resume_policy="resume_failed"' in example
    assert 'ProjectState.load(state_path)' in example
    assert 'resume_orchestrator.execute_workflow(failed)' in example
    assert 'Task histories:' in example


def test_snapshot_inspection_example_documents_snapshot_outputs_and_provider_metadata():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_snapshot_inspection.py"
    example = example_path.read_text(encoding="utf-8")

    assert 'class FakeMetadataProvider(BaseLLMProvider):' in example
    assert 'def health_check(self) -> dict[str, Any]:' in example
    assert 'snapshot = project.snapshot()' in example
    assert 'snapshot.workflow_status' in example
    assert 'snapshot.task_results.items()' in example
    assert 'resource_telemetry = task_result.resource_telemetry' in example
    assert 'snapshot.workflow_telemetry["progress_summary"]' in example
    assert 'snapshot.workflow_telemetry["provider_health_summary"]' in example
    assert 'snapshot.artifacts' in example
    assert 'snapshot.decisions' in example
    assert 'snapshot.execution_events' in example