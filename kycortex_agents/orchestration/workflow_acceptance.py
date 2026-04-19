"""Workflow-acceptance helpers used by the Orchestrator facade."""

from __future__ import annotations

from kycortex_agents.memory.project_state import ProjectState
from kycortex_agents.orchestration.contracts import AcceptanceEvaluation, AcceptanceLane, TaskAcceptanceLists
from kycortex_agents.types import TaskStatus


def task_acceptance_lists(project: ProjectState, acceptance_policy: str) -> TaskAcceptanceLists:
	if acceptance_policy == "required_tasks":
		evaluated_tasks = [task for task in project.tasks if task.required_for_acceptance]
	else:
		evaluated_tasks = list(project.tasks)
	return {
		"evaluated_task_ids": [task.id for task in evaluated_tasks],
		"required_task_ids": [task.id for task in project.tasks if task.required_for_acceptance],
		"completed_task_ids": [task.id for task in evaluated_tasks if task.status == TaskStatus.DONE.value],
		"failed_task_ids": [task.id for task in evaluated_tasks if task.status == TaskStatus.FAILED.value],
		"skipped_task_ids": [task.id for task in evaluated_tasks if task.status == TaskStatus.SKIPPED.value],
		"pending_task_ids": [
			task.id
			for task in evaluated_tasks
			if task.status not in {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.SKIPPED.value}
		],
	}


def observed_failure_categories(project: ProjectState) -> set[str]:
	categories: set[str] = set()
	if isinstance(project.failure_category, str) and project.failure_category:
		categories.add(project.failure_category)
	for task in project.tasks:
		if isinstance(task.last_error_category, str) and task.last_error_category:
			categories.add(task.last_error_category)
	return categories


def evaluate_workflow_acceptance(
	project: ProjectState,
	acceptance_policy: str,
	zero_budget_failure_categories: frozenset[str],
) -> AcceptanceEvaluation:
	productivity_lists = task_acceptance_lists(project, acceptance_policy)
	if acceptance_policy == "required_tasks" and not productivity_lists["evaluated_task_ids"]:
		productivity_accepted = False
		productivity_reason = "no_required_tasks"
	else:
		productivity_accepted = bool(productivity_lists["evaluated_task_ids"]) and len(
			productivity_lists["completed_task_ids"]
		) == len(productivity_lists["evaluated_task_ids"])
		productivity_reason = "all_evaluated_tasks_done" if productivity_accepted else "evaluated_tasks_incomplete"

	real_workflow_lists = task_acceptance_lists(project, "all_tasks")
	real_workflow_accepted = bool(real_workflow_lists["evaluated_task_ids"]) and len(
		real_workflow_lists["completed_task_ids"]
	) == len(real_workflow_lists["evaluated_task_ids"])
	real_workflow_reason = "all_workflow_tasks_done" if real_workflow_accepted else "workflow_tasks_incomplete"

	observed_categories = observed_failure_categories(project)
	zero_budget_categories = sorted(observed_categories & zero_budget_failure_categories)
	safety_accepted = not zero_budget_categories
	safety_reason = "no_zero_budget_incident_detected" if safety_accepted else "safety_validation_failed"

	acceptance_lanes: dict[str, AcceptanceLane] = {
		"productivity": {
			"accepted": productivity_accepted,
			"reason": productivity_reason,
			"policy": acceptance_policy,
			**productivity_lists,
		},
		"real_workflow": {
			"accepted": real_workflow_accepted,
			"reason": real_workflow_reason,
			"policy": "all_tasks",
			**real_workflow_lists,
		},
		"safety": {
			"accepted": safety_accepted,
			"reason": safety_reason,
			"observed_failure_categories": sorted(observed_categories),
			"zero_budget_failure_categories": zero_budget_categories,
		},
	}
	failed_lane_ids = [lane_id for lane_id, lane in acceptance_lanes.items() if not bool(lane["accepted"])]
	accepted = not failed_lane_ids
	reason = productivity_reason if not productivity_accepted else (
		real_workflow_reason if not real_workflow_accepted else (
			safety_reason if not safety_accepted else productivity_reason
		)
	)
	return {
		"policy": acceptance_policy,
		"accepted": accepted,
		"reason": reason,
		**productivity_lists,
		"acceptance_lanes": acceptance_lanes,
		"failed_lane_ids": failed_lane_ids,
	}