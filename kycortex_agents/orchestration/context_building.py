"""Context-building helpers used by the Orchestrator facade."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast
from typing import Any, Callable, Optional

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestration.dependency_analysis import analyze_dependency_manifest
from kycortex_agents.orchestration.module_ast_analysis import (
    analyze_python_module,
    build_code_behavior_contract,
    build_code_exact_test_contract,
    build_code_outline,
    build_code_public_api,
    build_code_test_targets,
    build_module_run_command,
)
from kycortex_agents.orchestration.output_helpers import summarize_output
from kycortex_agents.orchestration.test_ast_analysis import analyze_test_module_runtime
from kycortex_agents.orchestration.validation_reporting import build_dependency_validation_summary
from kycortex_agents.orchestration.validation_reporting import build_test_validation_summary
from kycortex_agents.types import (
    AgentView,
    AgentViewArtifactRecord,
    AgentViewDecisionRecord,
    AgentViewTaskResult,
    ArtifactType,
    ProjectSnapshot,
    TaskResult,
)


@dataclass(frozen=True)
class TaskContextRuntimeCallbacks:
    build_agent_view: Callable[[Any, Any, Any], Any]
    task_dependency_closure_ids: Callable[[Any, Any], set[str]]
    execution_agent_name: Callable[[Any], str]
    planned_module_context: Callable[[Any, set[str], Any], dict[str, Any]]
    task_public_contract_anchor: Callable[[str], str]
    should_compact_architecture_context: Callable[[Any, str], bool]
    compact_architecture_context: Callable[[Any, str], str]
    task_context_output: Callable[[Any], Optional[str]]
    is_budget_decomposition_planner: Callable[[Any], bool]
    semantic_output_key: Callable[[str, str], Optional[str]]
    normalize_assigned_to: Callable[[str], str]
    code_artifact_context: Callable[[Any, Any], dict[str, Any]]
    dependency_artifact_context: Callable[[Any, dict[str, Any]], dict[str, Any]]
    test_artifact_context: Callable[[Any, dict[str, Any]], dict[str, Any]]
    agent_visible_repair_context: Callable[[dict[str, Any], str], dict[str, Any]]
    normalized_helper_surface_symbols: Callable[[object], list[str]]
    qa_repair_should_reuse_failed_test_artifact: Callable[[object, object, object], bool]
    redact_sensitive_data: Callable[[Any], Any]


def agent_visible_repair_context(repair_context: dict[str, Any], execution_agent_name: str) -> dict[str, Any]:
    normalized_execution_agent = AgentRegistry.normalize_key(execution_agent_name)
    if normalized_execution_agent not in {"code_engineer", "qa_tester", "dependency_manager"}:
        return dict(repair_context)
    visible_keys = (
        "cycle",
        "failure_category",
        "repair_owner",
        "original_assigned_to",
        "source_failure_task_id",
        "source_failure_category",
    )
    return {
        key: repair_context[key]
        for key in visible_keys
        if key in repair_context
    }


def default_module_name_for_task(task: Task) -> str | None:
    assigned_to = (task.assigned_to or "").strip().lower()
    if assigned_to != "code_engineer":
        return None
    return f"{task.id}_implementation"


def context_module_task_runtime(
    project: ProjectState,
    current_task: Task | None,
    visible_task_ids: set[str] | None = None,
) -> Task | None:
    if current_task is not None and current_task.repair_origin_task_id:
        origin_task = project.get_task(current_task.repair_origin_task_id)
        if (
            origin_task is not None
            and (origin_task.assigned_to or "").strip().lower() == "code_engineer"
            and (visible_task_ids is None or origin_task.id in visible_task_ids)
            and default_module_name_for_task(origin_task)
        ):
            return origin_task

    for existing_task in project.tasks:
        if visible_task_ids is not None and existing_task.id not in visible_task_ids:
            continue
        if (existing_task.assigned_to or "").strip().lower() != "code_engineer":
            continue
        if existing_task.repair_origin_task_id:
            continue
        if default_module_name_for_task(existing_task):
            return existing_task

    if current_task is not None and default_module_name_for_task(current_task):
        return current_task

    for existing_task in project.tasks:
        if visible_task_ids is not None and existing_task.id not in visible_task_ids:
            continue
        if (existing_task.assigned_to or "").strip().lower() != "code_engineer":
            continue
        if default_module_name_for_task(existing_task):
            return existing_task

    return None


def planned_module_context_runtime(
    project: ProjectState,
    visible_task_ids: set[str] | None = None,
    current_task: Task | None = None,
) -> dict[str, Any]:
    module_task = context_module_task_runtime(project, current_task, visible_task_ids)
    if module_task is not None:
        module_name = default_module_name_for_task(module_task)
        if module_name:
            return {
                "planned_module_name": module_name,
                "planned_module_filename": f"{module_name}.py",
            }
    return {}


def code_artifact_context_runtime(
    task: Task,
    project: ProjectState | None = None,
) -> dict[str, Any]:
    if project is None:
        module_name = default_module_name_for_task(task)
    else:
        current_task = task
        visited_task_ids: set[str] = set()
        while current_task.repair_origin_task_id:
            origin_task = project.get_task(current_task.repair_origin_task_id)
            if (
                origin_task is None
                or origin_task.id in visited_task_ids
                or (origin_task.assigned_to or "").strip().lower() != "code_engineer"
            ):
                break
            visited_task_ids.add(origin_task.id)
            current_task = origin_task
        module_name = default_module_name_for_task(current_task)
    if not module_name:
        return {}

    artifact_path = f"artifacts/{module_name}.py"
    code_content = task.output or ""
    task_module_name = default_module_name_for_task(task)
    allow_artifact_path_override = task_module_name == module_name

    if isinstance(task.output_payload, dict):
        artifacts = task.output_payload.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    continue
                if artifact.get("artifact_type") != "code":
                    continue
                candidate_path = artifact.get("path")
                if allow_artifact_path_override and isinstance(candidate_path, str) and candidate_path.strip():
                    artifact_path = candidate_path
                candidate_content = artifact.get("content")
                if isinstance(candidate_content, str) and candidate_content.strip():
                    code_content = candidate_content
                break
        raw_content = task.output_payload.get("raw_content")
        if (not isinstance(code_content, str) or not code_content.strip()) and isinstance(raw_content, str):
            code_content = raw_content

    if not isinstance(code_content, str) or not code_content.strip():
        return {}

    path_obj = Path(artifact_path)
    code_analysis = analyze_python_module(code_content)
    return {
        "code_artifact_path": artifact_path,
        "module_name": path_obj.stem,
        "module_filename": path_obj.name,
        "code_summary": summarize_output(code_content),
        "code_outline": build_code_outline(code_content),
        "code_analysis": code_analysis,
        "code_public_api": build_code_public_api(code_analysis),
        "code_exact_test_contract": build_code_exact_test_contract(code_analysis),
        "code_test_targets": build_code_test_targets(code_analysis),
        "code_behavior_contract": build_code_behavior_contract(code_content),
        "module_run_command": build_module_run_command(path_obj.name, code_analysis),
    }


def test_artifact_context_runtime(task: Task, context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(task.output_payload, dict):
        return {}
    artifacts = task.output_payload.get("artifacts")
    if not isinstance(artifacts, list):
        return {}
    metadata = task.output_payload.get("metadata")
    validation = metadata.get("validation") if isinstance(metadata, dict) else None
    module_name = context.get("module_name")
    code_analysis = context.get("code_analysis")
    if not isinstance(module_name, str) or not module_name or not isinstance(code_analysis, dict):
        return {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("artifact_type") != ArtifactType.TEST.value:
            continue
        artifact_path = artifact.get("path")
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            continue
        test_analysis = validation.get("test_analysis") if isinstance(validation, dict) else None
        if not isinstance(test_analysis, dict):
            test_analysis = analyze_test_module_runtime(task.output or "", module_name, code_analysis)
        test_execution = validation.get("test_execution") if isinstance(validation, dict) else None
        return {
            "tests_artifact_path": artifact_path,
            "test_analysis": test_analysis,
            "test_execution": test_execution if isinstance(test_execution, dict) else None,
            "test_validation_summary": build_test_validation_summary(
                test_analysis,
                test_execution if isinstance(test_execution, dict) else None,
            ),
        }
    return {}


def dependency_artifact_context_runtime(task: Task, context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(task.output_payload, dict):
        return {}
    artifacts = task.output_payload.get("artifacts")
    if not isinstance(artifacts, list):
        return {}
    raw_code_analysis = context.get("code_analysis")
    code_analysis = cast(dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_path = artifact.get("path")
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            continue
        path_obj = Path(artifact_path)
        if path_obj.name != "requirements.txt":
            continue
        dependency_analysis = analyze_dependency_manifest(task.output or "", code_analysis)
        return {
            "dependency_manifest": task.output or "",
            "dependency_manifest_path": artifact_path,
            "dependency_analysis": dependency_analysis,
            "dependency_validation_summary": build_dependency_validation_summary(dependency_analysis),
        }
    return {}


def build_task_context_base(
    task: Any,
    project: Any,
    *,
    execution_agent_name: str,
    provider_max_tokens: int,
    agent_view: AgentView,
    agent_view_snapshot: dict[str, Any],
    planned_module_context: dict[str, Any],
) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "goal": project.goal,
        "project_name": project.project_name,
        "phase": project.phase,
        "provider_max_tokens": provider_max_tokens,
        "task": {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "assigned_to": task.assigned_to,
            "execution_agent": execution_agent_name,
        },
        "snapshot": agent_view_snapshot,
        "completed_tasks": {},
        "decisions": list(agent_view.decisions),
        "artifacts": list(agent_view.artifacts),
    }
    ctx.update(planned_module_context)
    planned_module_name = ctx.get("planned_module_name")
    planned_module_filename = ctx.get("planned_module_filename")
    if isinstance(planned_module_name, str) and planned_module_name.strip():
        ctx["module_name"] = planned_module_name
    if isinstance(planned_module_filename, str) and planned_module_filename.strip():
        ctx["module_filename"] = planned_module_filename
    return ctx


def apply_task_public_contract_context(
    ctx: dict[str, Any],
    *,
    task_public_contract_anchor: str,
    should_compact_architecture_context: Callable[[], bool],
    compact_architecture_context: Callable[[], str],
) -> Optional[str]:
    if not task_public_contract_anchor:
        return None

    ctx["task_public_contract_anchor"] = task_public_contract_anchor
    if should_compact_architecture_context():
        return compact_architecture_context()
    return None


def apply_completed_tasks_to_context(
    ctx: dict[str, Any],
    *,
    project_tasks: list[Any],
    visible_task_ids: set[str],
    budget_decomposition_plan_task_id: Optional[str],
    compact_architecture_context: Optional[str],
    task_context_output: Callable[[Any], Optional[str]],
    is_budget_decomposition_planner: Callable[[Any], bool],
    semantic_output_key: Callable[[str, str], Optional[str]],
    normalize_assigned_to: Callable[[str], str],
    code_artifact_context: Callable[[Any], dict[str, Any]],
    dependency_artifact_context: Callable[[Any, dict[str, Any]], dict[str, Any]],
    test_artifact_context: Callable[[Any, dict[str, Any]], dict[str, Any]],
) -> None:
    for prev_task in project_tasks:
        if prev_task.id not in visible_task_ids:
            continue
        visible_output = task_context_output(prev_task)
        if prev_task.status != "done" or not visible_output:
            continue
        should_apply_artifact_context = apply_completed_task_output_to_context(
            ctx,
            task_id=prev_task.id,
            assigned_to=prev_task.assigned_to,
            title=prev_task.title,
            visible_output=visible_output,
            budget_decomposition_plan_task_id=budget_decomposition_plan_task_id,
            compact_architecture_context=compact_architecture_context,
            is_budget_decomposition_planner=lambda: is_budget_decomposition_planner(prev_task),
            semantic_output_key=semantic_output_key,
        )
        if not should_apply_artifact_context:
            continue
        apply_completed_task_artifact_contexts(
            ctx,
            normalized_assigned_to=normalize_assigned_to(prev_task.assigned_to),
            code_artifact_context=lambda: code_artifact_context(prev_task),
            dependency_artifact_context=lambda: dependency_artifact_context(prev_task, ctx),
            test_artifact_context=lambda: test_artifact_context(prev_task, ctx),
        )


def apply_completed_task_artifact_contexts(
    ctx: dict[str, Any],
    *,
    normalized_assigned_to: str,
    code_artifact_context: Callable[[], dict[str, Any]],
    dependency_artifact_context: Callable[[], dict[str, Any]],
    test_artifact_context: Callable[[], dict[str, Any]],
) -> None:
    if normalized_assigned_to == "code_engineer":
        ctx.update(code_artifact_context())
    if normalized_assigned_to == "dependency_manager":
        ctx.update(dependency_artifact_context())
    if normalized_assigned_to == "qa_tester":
        ctx.update(test_artifact_context())


def apply_completed_task_output_to_context(
    ctx: dict[str, Any],
    *,
    task_id: str,
    assigned_to: str,
    title: str,
    visible_output: str,
    budget_decomposition_plan_task_id: Optional[str],
    compact_architecture_context: Optional[str],
    is_budget_decomposition_planner: Callable[[], bool],
    semantic_output_key: Callable[[str, str], Optional[str]],
) -> bool:
    ctx[task_id] = visible_output
    completed_tasks = ctx.setdefault("completed_tasks", {})
    if isinstance(completed_tasks, dict):
        completed_tasks[task_id] = visible_output

    if budget_decomposition_plan_task_id == task_id:
        ctx["budget_decomposition_brief"] = visible_output
    if is_budget_decomposition_planner():
        return False

    semantic_key = semantic_output_key(assigned_to, title)
    if semantic_key:
        semantic_output = visible_output
        if semantic_key == "architecture" and compact_architecture_context:
            semantic_output = compact_architecture_context
        ctx[semantic_key] = semantic_output
    return True


def apply_repair_context_to_context(
    ctx: dict[str, Any],
    repair_context: dict[str, Any],
    execution_agent_name: str,
    budget_decomposition_plan_task_id: Optional[str],
    *,
    agent_visible_repair_context: Callable[[dict[str, Any], str], dict[str, Any]],
    normalized_execution_agent: str,
    normalized_helper_surface_symbols: Callable[[object], list[str]],
    qa_repair_should_reuse_failed_test_artifact: Callable[[object, object, object], bool],
) -> None:
    ctx["repair_context"] = agent_visible_repair_context(repair_context, execution_agent_name)
    if budget_decomposition_plan_task_id is not None:
        ctx["budget_decomposition_plan_task_id"] = budget_decomposition_plan_task_id

    validation_summary = repair_context.get("validation_summary")
    if isinstance(validation_summary, str) and validation_summary.strip():
        ctx["repair_validation_summary"] = validation_summary

    helper_surface_usages = [
        item.strip()
        for item in repair_context.get("helper_surface_usages", [])
        if isinstance(item, str) and item.strip()
    ]
    helper_surface_symbols = normalized_helper_surface_symbols(
        repair_context.get("helper_surface_symbols") or helper_surface_usages
    )
    existing_tests = repair_context.get("existing_tests")
    failed_artifact_content = repair_context.get("failed_artifact_content")
    failed_output = repair_context.get("failed_output")
    repair_content = failed_artifact_content if isinstance(failed_artifact_content, str) and failed_artifact_content.strip() else failed_output

    if normalized_execution_agent == "code_engineer" and isinstance(repair_content, str) and repair_content.strip():
        ctx["existing_code"] = repair_content
    if normalized_execution_agent == "code_engineer" and isinstance(existing_tests, str) and existing_tests.strip():
        ctx["existing_tests"] = existing_tests
    if normalized_execution_agent == "qa_tester":
        if (
            isinstance(repair_content, str)
            and repair_content.strip()
            and qa_repair_should_reuse_failed_test_artifact(
                validation_summary,
                ctx.get("code", ""),
                repair_content,
            )
        ):
            ctx["existing_tests"] = repair_content
        if "test_validation_summary" not in ctx and isinstance(validation_summary, str) and validation_summary.strip():
            ctx["test_validation_summary"] = validation_summary
        if helper_surface_usages:
            ctx["repair_helper_surface_usages"] = helper_surface_usages
        if helper_surface_symbols:
            ctx["repair_helper_surface_symbols"] = helper_surface_symbols
    if normalized_execution_agent == "dependency_manager":
        if isinstance(repair_content, str) and repair_content.strip():
            ctx["existing_dependency_manifest"] = repair_content
        if "dependency_validation_summary" not in ctx and isinstance(validation_summary, str) and validation_summary.strip():
            ctx["dependency_validation_summary"] = validation_summary


def build_task_context_runtime(
    task: Any,
    project: Any,
    *,
    provider_max_tokens: int,
    callbacks: TaskContextRuntimeCallbacks,
) -> dict[str, Any]:
    snapshot = project.snapshot()
    agent_view = callbacks.build_agent_view(task, project, snapshot)
    agent_view_snapshot = asdict(agent_view)
    visible_task_ids = callbacks.task_dependency_closure_ids(task, project)
    current_execution_agent_name = callbacks.execution_agent_name(task)
    repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
    budget_decomposition_plan_task_id = repair_context.get("budget_decomposition_plan_task_id")
    if not isinstance(budget_decomposition_plan_task_id, str) or not budget_decomposition_plan_task_id.strip():
        budget_decomposition_plan_task_id = None
    ctx = build_task_context_base(
        task,
        project,
        execution_agent_name=current_execution_agent_name,
        provider_max_tokens=provider_max_tokens,
        agent_view=agent_view,
        agent_view_snapshot=agent_view_snapshot,
        planned_module_context=callbacks.planned_module_context(project, visible_task_ids, task),
    )
    public_contract_anchor = callbacks.task_public_contract_anchor(task.description)
    compacted_architecture_context = apply_task_public_contract_context(
        ctx,
        task_public_contract_anchor=public_contract_anchor,
        should_compact_architecture_context=lambda: callbacks.should_compact_architecture_context(task, public_contract_anchor),
        compact_architecture_context=lambda: callbacks.compact_architecture_context(task, public_contract_anchor),
    )
    apply_completed_tasks_to_context(
        ctx,
        project_tasks=project.tasks,
        visible_task_ids=visible_task_ids,
        budget_decomposition_plan_task_id=budget_decomposition_plan_task_id,
        compact_architecture_context=compacted_architecture_context,
        task_context_output=callbacks.task_context_output,
        is_budget_decomposition_planner=callbacks.is_budget_decomposition_planner,
        semantic_output_key=callbacks.semantic_output_key,
        normalize_assigned_to=callbacks.normalize_assigned_to,
        code_artifact_context=lambda prev_task: callbacks.code_artifact_context(prev_task, project),
        dependency_artifact_context=callbacks.dependency_artifact_context,
        test_artifact_context=callbacks.test_artifact_context,
    )
    if repair_context:
        apply_repair_context_to_context(
            ctx,
            repair_context,
            current_execution_agent_name,
            budget_decomposition_plan_task_id,
            agent_visible_repair_context=callbacks.agent_visible_repair_context,
            normalized_execution_agent=callbacks.normalize_assigned_to(current_execution_agent_name),
            normalized_helper_surface_symbols=callbacks.normalized_helper_surface_symbols,
            qa_repair_should_reuse_failed_test_artifact=callbacks.qa_repair_should_reuse_failed_test_artifact,
        )
    return cast(dict[str, Any], callbacks.redact_sensitive_data(ctx))


def build_agent_view_runtime(
    task: Any,
    project: Any,
    snapshot: ProjectSnapshot,
    *,
    task_dependency_closure_ids: Callable[[Any, Any], set[str]],
    direct_dependency_ids: Callable[[Any], set[str]],
) -> AgentView:
    visible_task_ids = task_dependency_closure_ids(task, project)
    current_direct_dependency_ids = direct_dependency_ids(task)
    acceptance_evaluation = snapshot.acceptance_evaluation
    acceptance_policy = acceptance_evaluation.get("policy")
    if not isinstance(acceptance_policy, str):
        acceptance_policy = None
    terminal_outcome = acceptance_evaluation.get("terminal_outcome")
    if not isinstance(terminal_outcome, str):
        terminal_outcome = None
    failure_category = acceptance_evaluation.get("failure_category")
    if not isinstance(failure_category, str):
        failure_category = None
    acceptance_criteria_met = bool(acceptance_evaluation.get("accepted"))
    return AgentView(
        project_name=snapshot.project_name,
        goal=snapshot.goal,
        workflow_status=snapshot.workflow_status,
        phase=snapshot.phase,
        acceptance_policy=acceptance_policy,
        terminal_outcome=terminal_outcome,
        failure_category=failure_category,
        acceptance_criteria_met=acceptance_criteria_met,
        task_results=build_agent_view_task_results(snapshot.task_results, visible_task_ids),
        decisions=build_agent_view_decisions(snapshot.decisions),
        artifacts=build_agent_view_artifacts(snapshot.artifacts, visible_task_ids, current_direct_dependency_ids),
    )


def build_agent_view_task_results(
    task_results: dict[str, TaskResult],
    visible_task_ids: set[str],
) -> dict[str, AgentViewTaskResult]:
    filtered_results: dict[str, AgentViewTaskResult] = {}
    for task_id, task_result in task_results.items():
        if task_id not in visible_task_ids:
            continue
        failure_category = None
        if task_result.failure is not None:
            failure_category = task_result.failure.category
        filtered_results[task_id] = AgentViewTaskResult(
            task_id=task_result.task_id,
            status=task_result.status,
            agent_name=task_result.agent_name,
            has_output=task_result.output is not None,
            failure_category=failure_category,
            started_at=task_result.started_at,
            completed_at=task_result.completed_at,
        )
    return filtered_results


def build_agent_view_decisions(decisions: list[Any]) -> list[AgentViewDecisionRecord]:
    filtered_decisions: list[AgentViewDecisionRecord] = []
    for decision in decisions:
        if isinstance(decision, dict):
            topic = decision.get("topic")
            decision_text = decision.get("decision")
            rationale = decision.get("rationale")
            created_at = decision.get("created_at")
        else:
            topic = getattr(decision, "topic", None)
            decision_text = getattr(decision, "decision", None)
            rationale = getattr(decision, "rationale", None)
            created_at = getattr(decision, "created_at", None)
        if isinstance(topic, str) and isinstance(decision_text, str) and isinstance(rationale, str):
            filtered_decisions.append(
                AgentViewDecisionRecord(
                    topic=topic,
                    decision=decision_text,
                    rationale=rationale,
                    created_at=created_at if isinstance(created_at, str) else "",
                )
            )
    return filtered_decisions


def build_agent_view_artifacts(
    artifacts: list[Any],
    visible_task_ids: set[str],
    direct_dependency_ids: set[str],
) -> list[AgentViewArtifactRecord]:
    filtered_artifacts: list[AgentViewArtifactRecord] = []
    for artifact in artifacts:
        if isinstance(artifact, dict):
            metadata = artifact.get("metadata")
            source_task_id = metadata.get("task_id") if isinstance(metadata, dict) else None
            artifact_name = artifact.get("name")
            artifact_type = artifact.get("artifact_type", ArtifactType.OTHER)
            artifact_content = artifact.get("content")
            created_at = artifact.get("created_at")
        else:
            metadata = artifact.metadata if isinstance(artifact.metadata, dict) else None
            source_task_id = metadata.get("task_id") if isinstance(metadata, dict) else None
            artifact_name = getattr(artifact, "name", None)
            artifact_type = getattr(artifact, "artifact_type", ArtifactType.OTHER)
            artifact_content = getattr(artifact, "content", None)
            created_at = getattr(artifact, "created_at", None)
        if isinstance(source_task_id, str) and source_task_id not in visible_task_ids:
            continue
        include_content = isinstance(source_task_id, str) and source_task_id in direct_dependency_ids
        if not isinstance(artifact_name, str):
            continue
        filtered_artifacts.append(
            AgentViewArtifactRecord(
                name=artifact_name,
                artifact_type=artifact_type if isinstance(artifact_type, ArtifactType) else ArtifactType(str(artifact_type)),
                content=artifact_content if include_content and isinstance(artifact_content, str) else None,
                created_at=created_at if isinstance(created_at, str) else "",
                source_task_id=source_task_id if isinstance(source_task_id, str) else None,
            )
        )
    return filtered_artifacts


def task_dependency_closure_ids(task: Any, project: Any) -> set[str]:
    visible_task_ids = {task.id}
    pending_task_ids = list(task.dependencies)
    repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
    budget_decomposition_plan_task_id = repair_context.get("budget_decomposition_plan_task_id")
    if isinstance(budget_decomposition_plan_task_id, str) and budget_decomposition_plan_task_id.strip():
        pending_task_ids.append(budget_decomposition_plan_task_id)
    if task.repair_origin_task_id:
        pending_task_ids.append(task.repair_origin_task_id)

    while pending_task_ids:
        dependency_id = pending_task_ids.pop()
        if dependency_id in visible_task_ids:
            continue
        visible_task_ids.add(dependency_id)
        dependency_task = project.get_task(dependency_id)
        if dependency_task is None:
            continue
        pending_task_ids.extend(dependency_task.dependencies)

    return visible_task_ids


def direct_dependency_ids(task: Any) -> set[str]:
    current_direct_dependency_ids = set(task.dependencies)
    if task.repair_origin_task_id:
        current_direct_dependency_ids.add(task.repair_origin_task_id)
    repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
    budget_decomposition_plan_task_id = repair_context.get("budget_decomposition_plan_task_id")
    if isinstance(budget_decomposition_plan_task_id, str) and budget_decomposition_plan_task_id.strip():
        current_direct_dependency_ids.add(budget_decomposition_plan_task_id)
    return current_direct_dependency_ids