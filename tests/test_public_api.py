import kycortex_agents
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
    __version__,
    resolve_state_store,
)
from kycortex_agents.memory import ProjectState as MemoryProjectState
from kycortex_agents.memory import Task as MemoryTask


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


def test_public_api_exports_core_agent_types():
    assert ArchitectAgent is not None
    assert CodeEngineerAgent is not None
    assert CodeReviewerAgent is not None
    assert DocsWriterAgent is not None
    assert LegalAdvisorAgent is not None
    assert QATesterAgent is not None