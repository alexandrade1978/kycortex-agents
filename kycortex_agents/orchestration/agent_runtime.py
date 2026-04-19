"""Agent runtime helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import Any, Sequence

from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.providers.base import redact_sensitive_text
from kycortex_agents.types import FailureCategory
from kycortex_agents.types import AgentInput


def build_agent_input(
	task: Task,
	project: ProjectState,
	context: dict[str, Any],
	*,
	repair_focus_lines: Sequence[str] | None = None,
) -> AgentInput:
	repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
	task_description = task.description
	if repair_context:
		repair_lines = [
			task.description,
			"",
			"Repair objective:",
			str(repair_context.get("instruction") or "Repair the previous failure."),
			"",
			f"Previous failure category: {repair_context.get('failure_category') or FailureCategory.UNKNOWN.value}",
		]
		source_failure_task_id = repair_context.get("source_failure_task_id")
		if isinstance(source_failure_task_id, str) and source_failure_task_id.strip():
			repair_lines.append(f"Source failure task: {source_failure_task_id}")
		source_failure_category = repair_context.get("source_failure_category")
		if isinstance(source_failure_category, str) and source_failure_category.strip():
			repair_lines.append(f"Source failure category: {source_failure_category}")
		failure_message = repair_context.get("failure_message")
		if isinstance(failure_message, str) and failure_message.strip():
			repair_lines.append(f"Previous failure message: {failure_message}")
		validation_summary = repair_context.get("validation_summary")
		if isinstance(validation_summary, str) and validation_summary.strip():
			repair_lines.extend(["", "Validation summary:", validation_summary])
		budget_decomposition_brief = context.get("budget_decomposition_brief")
		if isinstance(budget_decomposition_brief, str) and budget_decomposition_brief.strip():
			repair_lines.extend(["", "Budget decomposition brief:", budget_decomposition_brief])
		if repair_focus_lines:
			repair_lines.extend(["", "Repair priorities:"])
			repair_lines.extend(f"- {line}" for line in repair_focus_lines)
		task_description = "\n".join(repair_lines)
	return AgentInput(
		task_id=task.id,
		task_title=redact_sensitive_text(task.title),
		task_description=redact_sensitive_text(task_description),
		project_name=redact_sensitive_text(project.project_name),
		project_goal=redact_sensitive_text(project.goal),
		context=context,
	)


def execute_agent(agent: Any, agent_input: AgentInput) -> Any:
	if hasattr(agent, "execute"):
		return agent.execute(agent_input)
	if hasattr(agent, "run_with_input"):
		return agent.run_with_input(agent_input)
	return agent.run(agent_input.task_description, agent_input.context)