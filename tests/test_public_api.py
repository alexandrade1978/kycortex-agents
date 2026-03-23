import kycortex_agents
from pathlib import Path
import tomllib
from kycortex_agents import config as config_module
from kycortex_agents import exceptions as exceptions_module
from kycortex_agents import types as types_module
from kycortex_agents.agents import registry as registry_module
from kycortex_agents.memory import state_store as state_store_module
from kycortex_agents.providers import factory as provider_factory_module
from kycortex_agents import (
    AgentRegistry,
    AnthropicProvider,
    ArchitectAgent,
    BaseStateStore,
    BaseAgent,
    CodeEngineerAgent,
    CodeReviewerAgent,
    DEFAULT_CONFIG,
    DocsWriterAgent,
    KYCortexConfig,
    JsonStateStore,
    LegalAdvisorAgent,
    OllamaProvider,
    Orchestrator,
    ProjectState,
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


def test_public_extension_modules_define_explicit_exports():
    assert registry_module.__all__ == ["AgentRegistry", "build_default_registry"]
    assert provider_factory_module.__all__ == ["create_provider"]
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


def test_example_defines_dependency_aware_workflow_chain():
    example_path = Path(__file__).resolve().parents[1] / "examples" / "example_simple_project.py"
    example = example_path.read_text(encoding="utf-8")

    assert 'id="task_1_arch"' in example
    assert 'id="task_2_code"' in example
    assert 'id="task_3_review"' in example
    assert 'dependencies=["task_1_arch"]' in example
    assert 'dependencies=["task_2_code"]' in example