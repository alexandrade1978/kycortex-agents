"""Agent runtime helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import Any

from kycortex_agents.types import AgentInput


def execute_agent(agent: Any, agent_input: AgentInput) -> Any:
	if hasattr(agent, "execute"):
		return agent.execute(agent_input)
	if hasattr(agent, "run_with_input"):
		return agent.run_with_input(agent_input)
	return agent.run(agent_input.task_description, agent_input.context)