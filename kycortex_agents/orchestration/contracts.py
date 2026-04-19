"""Typed internal contracts for orchestrator subcomponents.

These contracts do not change the public runtime API. They exist to make the
current refactor explicit and to reduce the amount of unstructured dict traffic
inside the orchestrator implementation.
"""

from __future__ import annotations

from typing import TypedDict


class TaskAcceptanceLists(TypedDict):
	"""Task-id buckets used by workflow acceptance lanes."""

	evaluated_task_ids: list[str]
	required_task_ids: list[str]
	completed_task_ids: list[str]
	failed_task_ids: list[str]
	skipped_task_ids: list[str]
	pending_task_ids: list[str]


class AcceptanceLaneRequired(TypedDict):
	"""Acceptance-lane fields that are always present."""

	accepted: bool
	reason: str


class AcceptanceLane(AcceptanceLaneRequired, total=False):
	"""Single acceptance lane summary.

	Task-oriented lanes carry the task-id buckets above plus acceptance metadata.
	Safety-oriented lanes only use the acceptance metadata and failure-category
	lists.
	"""

	policy: str
	evaluated_task_ids: list[str]
	required_task_ids: list[str]
	completed_task_ids: list[str]
	failed_task_ids: list[str]
	skipped_task_ids: list[str]
	pending_task_ids: list[str]
	observed_failure_categories: list[str]
	zero_budget_failure_categories: list[str]


class AcceptanceEvaluation(TaskAcceptanceLists):
	"""Full acceptance decision returned by the orchestrator."""

	policy: str
	accepted: bool
	reason: str
	acceptance_lanes: dict[str, AcceptanceLane]
	failed_lane_ids: list[str]