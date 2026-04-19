"""Output summarization and semantic-key helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import Optional

from kycortex_agents.agents.registry import AgentRegistry


def summarize_output(raw_content: str) -> str:
	stripped = raw_content.strip()
	if not stripped:
		return ""
	return stripped.splitlines()[0].strip()[:120]


def semantic_output_key(assigned_to: str, task_title: str) -> Optional[str]:
	role_key = AgentRegistry.normalize_key(assigned_to)
	semantic_map = {
		"architect": "architecture",
		"code_engineer": "code",
		"dependency_manager": "dependencies",
		"code_reviewer": "review",
		"qa_tester": "tests",
		"docs_writer": "documentation",
		"legal_advisor": "legal",
	}
	if role_key in semantic_map:
		return semantic_map[role_key]

	title_key = task_title.lower().replace(" ", "_")
	if "architect" in title_key or "architecture" in title_key:
		return "architecture"
	if "review" in title_key:
		return "review"
	if "test" in title_key:
		return "tests"
	if "depend" in title_key or "requirement" in title_key or "package" in title_key:
		return "dependencies"
	if "doc" in title_key:
		return "documentation"
	if "legal" in title_key or "license" in title_key:
		return "legal"
	return None