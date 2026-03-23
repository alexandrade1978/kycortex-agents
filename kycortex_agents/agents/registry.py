from __future__ import annotations

from typing import Dict, Iterable, Optional

from kycortex_agents.agents.architect import ArchitectAgent
from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.code_engineer import CodeEngineerAgent
from kycortex_agents.agents.code_reviewer import CodeReviewerAgent
from kycortex_agents.agents.docs_writer import DocsWriterAgent
from kycortex_agents.agents.legal_advisor import LegalAdvisorAgent
from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError

__all__ = ["AgentRegistry", "build_default_registry"]


class AgentRegistry:
    """Registry that normalizes agent keys and resolves workflow agent instances."""

    def __init__(self, agents: Optional[Dict[str, BaseAgent]] = None):
        self._agents: Dict[str, BaseAgent] = {}
        for key, agent in (agents or {}).items():
            self.register(key, agent)

    def register(self, key: str, agent: BaseAgent) -> None:
        """Register or replace an agent under the normalized registry key."""

        self._agents[self.normalize_key(key)] = agent

    def get(self, key: str) -> BaseAgent:
        """Return the agent bound to the normalized key or raise when it is unknown."""

        normalized_key = self.normalize_key(key)
        if normalized_key not in self._agents:
            raise AgentExecutionError(f"Unknown agent: {key}")
        return self._agents[normalized_key]

    def has(self, key: str) -> bool:
        """Return whether an agent is registered for the normalized key."""

        return self.normalize_key(key) in self._agents

    def keys(self) -> Iterable[str]:
        """Return the normalized registry keys currently available."""

        return self._agents.keys()

    @staticmethod
    def normalize_key(key: str) -> str:
        """Normalize a registry key so workflow task assignments resolve consistently."""

        return key.strip().lower().replace(" ", "_")


def build_default_registry(config: KYCortexConfig) -> AgentRegistry:
    return AgentRegistry(
        {
            "architect": ArchitectAgent(config),
            "code_engineer": CodeEngineerAgent(config),
            "code_reviewer": CodeReviewerAgent(config),
            "qa_tester": QATesterAgent(config),
            "docs_writer": DocsWriterAgent(config),
            "legal_advisor": LegalAdvisorAgent(config),
        }
    )