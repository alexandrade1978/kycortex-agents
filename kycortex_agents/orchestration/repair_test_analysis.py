from __future__ import annotations

import ast
from dataclasses import dataclass

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestration.repair_signals import (
    validation_summary_has_missing_datetime_import_issue,
    validation_summary_has_required_evidence_runtime_issue,
)
from kycortex_agents.types import ArtifactType, FailureCategory


@dataclass(frozen=True)
class TestRepairSurfaceAnalysis:
    imported_module_symbols: list[str]
    undefined_local_names: list[str]
    undefined_available_module_symbols: list[str]
    helper_alias_names: list[str]
    unknown_module_symbols: list[str]
    previous_member_calls: dict[str, list[str]]
    previous_constructor_keywords: dict[str, list[str]]


def normalized_helper_surface_symbols(raw_values: object) -> list[str]:
    if not isinstance(raw_values, list):
        return []

    seen: set[str] = set()
    symbols: list[str] = []
    for value in raw_values:
        if not isinstance(value, str):
            continue
        symbol = value.split(" (line ", 1)[0].strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def helper_surface_usages_for_test_repair(
    validation_payload: object,
    failure_category: str,
) -> list[str]:
    if failure_category != "test_validation":
        return []
    if not isinstance(validation_payload, dict):
        return []

    test_analysis = validation_payload.get("test_analysis")
    if not isinstance(test_analysis, dict):
        return []

    raw_usages = test_analysis.get("helper_surface_usages")
    if not isinstance(raw_usages, list):
        return []

    return [item.strip() for item in raw_usages if isinstance(item, str) and item.strip()]


def helper_surface_usages_for_test_repair_runtime(
    task: Task,
    failure_category: str,
    *,
    validation_payload,
) -> list[str]:
    return helper_surface_usages_for_test_repair(
        validation_payload(task),
        failure_category,
    )


def validation_summary_symbols(validation_summary: str, label: str) -> list[str]:
    prefix = f"- {label}:"
    for line in validation_summary.splitlines():
        if not line.startswith(prefix):
            continue
        raw_value = line[len(prefix):].strip()
        if not raw_value or raw_value.lower() == "none":
            return []
        return [item.strip() for item in raw_value.split(",") if item.strip()]
    return []


def module_defined_symbol_names(implementation_code: object) -> list[str]:
    if not isinstance(implementation_code, str) or not implementation_code.strip():
        return []
    try:
        tree = ast.parse(implementation_code)
    except SyntaxError:
        return []

    names: list[str] = []
    seen: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in seen:
            continue
        seen.add(node.name)
        names.append(node.name)
    return names


def is_helper_alias_like_name(name: str) -> bool:
    normalized = name.strip().lower()
    if not normalized:
        return False
    return normalized.endswith((
        "logger",
        "scorer",
        "processor",
        "manager",
        "repository",
        "validator",
        "engine",
        "service",
    ))


def validation_summary_helper_alias_names(
    validation_summary: object,
    implementation_code: object = "",
) -> list[str]:
    if not isinstance(validation_summary, str) or not validation_summary.strip():
        return []
    module_defined_symbols = {
        name.lower() for name in module_defined_symbol_names(implementation_code)
    }
    undefined_names = normalized_helper_surface_symbols(
        validation_summary_symbols(validation_summary, "Undefined local names")
    )
    return [
        name
        for name in undefined_names
        if name.lower() not in module_defined_symbols and is_helper_alias_like_name(name)
    ]


def failed_test_requires_code_repair(
    task: Task,
    validation_payload: object,
    *,
    pytest_failure_origin,
    pytest_contract_overreach_signals,
    test_validation_has_blocking_issues,
    pytest_failure_is_semantic_assertion_mismatch,
) -> bool:
    if AgentRegistry.normalize_key(task.assigned_to) != "qa_tester":
        return False
    if task.last_error_category != FailureCategory.TEST_VALIDATION.value:
        return False
    if not isinstance(validation_payload, dict) or not validation_payload:
        return False

    test_execution = validation_payload.get("test_execution")
    if not isinstance(test_execution, dict):
        return False
    if not test_execution.get("ran") or test_execution.get("returncode") in (None, 0):
        return False

    failure_origin = validation_payload.get("pytest_failure_origin")
    if not isinstance(failure_origin, str) or not failure_origin:
        failure_origin = pytest_failure_origin(
            test_execution,
            validation_payload.get("module_filename") if isinstance(validation_payload.get("module_filename"), str) else None,
            validation_payload.get("test_filename") if isinstance(validation_payload.get("test_filename"), str) else None,
        )

    if failure_origin == "tests" and pytest_contract_overreach_signals(test_execution):
        return False

    if failure_origin == "code_under_test":
        return True

    if test_validation_has_blocking_issues(validation_payload):
        return False

    return failure_origin == "tests" and pytest_failure_is_semantic_assertion_mismatch(test_execution)


def failed_test_requires_code_repair_runtime(
    task: Task,
    *,
    validation_payload,
    pytest_failure_origin,
    pytest_contract_overreach_signals,
    test_validation_has_blocking_issues,
    pytest_failure_is_semantic_assertion_mismatch,
) -> bool:
    return failed_test_requires_code_repair(
        task,
        validation_payload(task),
        pytest_failure_origin=pytest_failure_origin,
        pytest_contract_overreach_signals=pytest_contract_overreach_signals,
        test_validation_has_blocking_issues=test_validation_has_blocking_issues,
        pytest_failure_is_semantic_assertion_mismatch=pytest_failure_is_semantic_assertion_mismatch,
    )


def imported_code_task_for_failed_test(
    project: ProjectState,
    task: Task,
    *,
    failed_artifact_content,
    python_import_roots,
    default_module_name_for_task,
) -> Task | None:
    import_roots = python_import_roots(
        failed_artifact_content(task, ArtifactType.TEST)
    )
    if not import_roots:
        return None

    preferred_task: Task | None = None
    for existing_task in reversed(project.tasks):
        if AgentRegistry.normalize_key(existing_task.assigned_to) != "code_engineer":
            continue
        module_name = default_module_name_for_task(existing_task)
        if not module_name or module_name not in import_roots:
            continue
        if existing_task.repair_origin_task_id:
            return existing_task
        if preferred_task is None:
            preferred_task = existing_task
    return preferred_task


def upstream_code_task_for_test_failure(
    project: ProjectState,
    task: Task,
    *,
    imported_code_task_for_failed_test,
) -> Task | None:
    imported_code_task = imported_code_task_for_failed_test(project, task)
    preferred_dependency: Task | None = None
    for dependency_id in reversed(task.dependencies):
        dependency = project.get_task(dependency_id)
        if dependency is None:
            continue
        if AgentRegistry.normalize_key(dependency.assigned_to) == "code_engineer":
            if dependency.repair_origin_task_id:
                return dependency
            if preferred_dependency is None:
                preferred_dependency = dependency
    return imported_code_task or preferred_dependency


def _append_unique_mapping_value(mapping: dict[str, list[str]], key: str, value: str) -> None:
    values = mapping.setdefault(key, [])
    if value not in values:
        values.append(value)


def previous_valid_test_surface(
    failed_artifact_content: object,
    imported_module_symbols: list[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
        return {}, {}
    if not imported_module_symbols:
        return {}, {}

    try:
        tree = ast.parse(failed_artifact_content)
    except SyntaxError:
        return {}, {}

    imported_symbol_set = set(imported_module_symbols)
    instance_bindings: dict[str, str] = {}
    member_calls_by_class: dict[str, list[str]] = {}
    constructor_keywords_by_class: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in imported_symbol_set
        ):
            continue

        for target in node.targets:
            if isinstance(target, ast.Name):
                instance_bindings[target.id] = value.func.id
        for keyword in value.keywords:
            if keyword.arg:
                _append_unique_mapping_value(
                    constructor_keywords_by_class,
                    value.func.id,
                    keyword.arg,
                )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Name) and node.func.id in imported_symbol_set:
            for keyword in node.keywords:
                if keyword.arg:
                    _append_unique_mapping_value(
                        constructor_keywords_by_class,
                        node.func.id,
                        keyword.arg,
                    )
            continue

        if not isinstance(node.func, ast.Attribute):
            continue

        owner_class: str | None = None
        value = node.func.value
        if isinstance(value, ast.Name):
            owner_class = instance_bindings.get(value.id)
        elif (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in imported_symbol_set
        ):
            owner_class = value.func.id
            for keyword in value.keywords:
                if keyword.arg:
                    _append_unique_mapping_value(
                        constructor_keywords_by_class,
                        value.func.id,
                        keyword.arg,
                    )

        if owner_class:
            _append_unique_mapping_value(
                member_calls_by_class,
                owner_class,
                node.func.attr,
            )

    return member_calls_by_class, constructor_keywords_by_class


def analyze_test_repair_surface(
    validation_summary: object,
    implementation_code: object = "",
    failed_artifact_content: object = "",
) -> TestRepairSurfaceAnalysis:
    if not isinstance(validation_summary, str) or not validation_summary.strip():
        return TestRepairSurfaceAnalysis([], [], [], [], [], {}, {})

    available_module_symbol_map = {
        name.lower(): name for name in module_defined_symbol_names(implementation_code)
    }
    imported_module_symbols = validation_summary_symbols(
        validation_summary,
        "Imported module symbols",
    )
    undefined_local_names = normalized_helper_surface_symbols(
        validation_summary_symbols(validation_summary, "Undefined local names")
    )

    undefined_available_module_symbols: list[str] = []
    for name in undefined_local_names:
        normalized_name = name.lower()
        if normalized_name in {"pytest", "datetime"}:
            continue
        actual_name = available_module_symbol_map.get(normalized_name)
        if (
            actual_name
            and actual_name not in imported_module_symbols
            and actual_name not in undefined_available_module_symbols
        ):
            undefined_available_module_symbols.append(actual_name)

    helper_alias_names = [
        name
        for name in undefined_local_names
        if name not in imported_module_symbols
        and name.lower() not in available_module_symbol_map
        and is_helper_alias_like_name(name)
    ]
    unknown_module_symbols = validation_summary_symbols(
        validation_summary,
        "Unknown module symbols",
    )
    previous_member_calls, previous_constructor_keywords = previous_valid_test_surface(
        failed_artifact_content,
        imported_module_symbols,
    )
    return TestRepairSurfaceAnalysis(
        imported_module_symbols=imported_module_symbols,
        undefined_local_names=undefined_local_names,
        undefined_available_module_symbols=undefined_available_module_symbols,
        helper_alias_names=helper_alias_names,
        unknown_module_symbols=unknown_module_symbols,
        previous_member_calls=previous_member_calls,
        previous_constructor_keywords=previous_constructor_keywords,
    )


def qa_repair_should_reuse_failed_test_artifact(
    validation_summary: object,
    implementation_code: object = "",
    failed_artifact_content: object = "",
) -> bool:
    if not isinstance(validation_summary, str) or not validation_summary.strip():
        return True

    analysis = analyze_test_repair_surface(
        validation_summary,
        implementation_code,
        failed_artifact_content,
    )
    has_reusable_missing_imports = bool(analysis.undefined_available_module_symbols)
    has_required_evidence_runtime_issue = validation_summary_has_required_evidence_runtime_issue(
        validation_summary,
        failed_artifact_content,
        implementation_code,
    )
    if analysis.helper_alias_names:
        return False
    if has_required_evidence_runtime_issue and not has_reusable_missing_imports:
        return False
    if validation_summary_has_missing_datetime_import_issue(
        validation_summary,
        failed_artifact_content,
    ) and not has_reusable_missing_imports:
        return False
    return not any(
        validation_summary_symbols(validation_summary, label)
        for label in (
            "Tests without assertion-like checks",
            "Contract overreach signals",
        )
    )


__all__ = [
    "TestRepairSurfaceAnalysis",
    "analyze_test_repair_surface",
    "is_helper_alias_like_name",
    "module_defined_symbol_names",
    "normalized_helper_surface_symbols",
    "previous_valid_test_surface",
    "qa_repair_should_reuse_failed_test_artifact",
    "validation_summary_helper_alias_names",
    "validation_summary_symbols",
]