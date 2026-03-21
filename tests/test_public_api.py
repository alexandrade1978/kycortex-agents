import kycortex_agents
from kycortex_agents import (
    AgentRegistry,
    ArchitectAgent,
    BaseAgent,
    CodeEngineerAgent,
    CodeReviewerAgent,
    DocsWriterAgent,
    KYCortexConfig,
    LegalAdvisorAgent,
    Orchestrator,
    ProjectState,
    QATesterAgent,
    Task,
    __version__,
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
    assert BaseAgent is not None


def test_public_api_exports_core_agent_types():
    assert ArchitectAgent is not None
    assert CodeEngineerAgent is not None
    assert CodeReviewerAgent is not None
    assert DocsWriterAgent is not None
    assert LegalAdvisorAgent is not None
    assert QATesterAgent is not None