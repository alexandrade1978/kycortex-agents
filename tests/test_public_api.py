import kycortex_agents
from kycortex_agents import config as config_module
from kycortex_agents import exceptions as exceptions_module
from kycortex_agents import types as types_module
from kycortex_agents import (
    AgentRegistry,
    AnthropicProvider,
    ArchitectAgent,
    BaseStateStore,
    BaseAgent,
    CodeEngineerAgent,
    CodeReviewerAgent,
    DocsWriterAgent,
    KYCortexConfig,
    JsonStateStore,
    LegalAdvisorAgent,
    OllamaProvider,
    Orchestrator,
    ProjectState,
    QATesterAgent,
    SqliteStateStore,
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
    assert kycortex_agents.__version__ == "0.1.0"
    assert __version__ == "0.1.0"
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
    assert WorkflowDefinitionError is not None


def test_public_api_exports_core_agent_types():
    assert ArchitectAgent is not None
    assert CodeEngineerAgent is not None
    assert CodeReviewerAgent is not None
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
        "StatePersistenceError",
        "WorkflowDefinitionError",
    ]
    assert types_module.__all__ == [
        "AgentInput",
        "AgentOutput",
        "ArtifactRecord",
        "ArtifactType",
        "DecisionRecord",
        "FailureRecord",
        "ProjectSnapshot",
        "TaskResult",
        "TaskStatus",
        "WorkflowStatus",
        "utc_now_iso",
    ]