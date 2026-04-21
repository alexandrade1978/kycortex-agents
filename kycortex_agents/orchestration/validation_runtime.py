"""Validation-runtime helpers used by the Orchestrator facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, cast

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.memory.project_state import Task
from kycortex_agents.orchestration.dependency_analysis import analyze_dependency_manifest
from kycortex_agents.orchestration.validation_analysis import (
    collect_code_validation_issues,
    collect_test_validation_issues,
    validation_error_message_for_test_result,
)
from kycortex_agents.providers.base import redact_sensitive_data, sanitize_provider_call_metadata
from kycortex_agents.types import AgentOutput, ArtifactType


@dataclass(slots=True)
class ValidationRuntimeState:
    test_content: str
    test_artifact_content: str
    test_analysis: dict[str, Any]
    test_execution: dict[str, Any]
    completion_diagnostics: dict[str, Any]
    module_filename: str
    test_filename: str
    pytest_failure_origin: str


@dataclass(slots=True)
class ValidationRuntimeInput:
    module_name: str
    module_filename: str
    code_content: str
    test_artifact_content: str
    test_content: str
    test_filename: str
    code_exact_test_contract: str
    code_behavior_contract: str


def should_validate_code_content(content: str, has_typed_artifact: bool) -> bool:
    if has_typed_artifact:
        return True
    stripped = content.strip()
    if not stripped:
        return False
    return any(token in stripped for token in ("def ", "class ", "import ", "from ", "if __name__"))


def should_validate_test_content(content: str, has_typed_artifact: bool) -> bool:
    if has_typed_artifact:
        return True
    stripped = content.strip()
    if not stripped:
        return False
    return any(token in stripped for token in ("def test_", "assert ", "import pytest", "pytest."))


def summarize_pytest_output(stdout: str, stderr: str, returncode: int) -> str:
    combined_lines = [line.strip() for line in f"{stdout}\n{stderr}".splitlines() if line.strip()]
    if not combined_lines:
        return f"pytest exited with code {returncode}"
    for line in reversed(combined_lines):
        if line.startswith("=") or line.startswith("FAILED") or line.startswith("ERROR") or "passed" in line:
            return line
    return combined_lines[-1][:240]


def redact_validation_execution_result(result: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], redact_sensitive_data(result))


def sanitize_output_provider_call_metadata(output: AgentOutput) -> AgentOutput:
    provider_call = output.metadata.get("provider_call") if isinstance(output.metadata, dict) else None
    if not isinstance(provider_call, dict):
        return output
    output.metadata = dict(output.metadata)
    output.metadata["provider_call"] = sanitize_provider_call_metadata(provider_call)
    return output


def provider_call_metadata(agent: Any, output: Optional[AgentOutput] = None) -> Optional[dict[str, Any]]:
    if output is not None:
        output_provider_call = output.metadata.get("provider_call")
        if isinstance(output_provider_call, dict):
            return sanitize_provider_call_metadata(output_provider_call)
    getter = getattr(agent, "get_last_provider_call_metadata", None)
    if callable(getter):
        metadata = getter()
        if isinstance(metadata, dict):
            return sanitize_provider_call_metadata(metadata)
    return None


def build_test_validation_runtime_input(
    context: dict[str, Any],
    output: AgentOutput,
) -> Optional[ValidationRuntimeInput]:
    module_name = context.get("module_name")
    module_filename = context.get("module_filename")
    code_content = context.get("code")
    if not isinstance(module_name, str) or not module_name.strip():
        return None
    if not isinstance(module_filename, str) or not module_filename.strip():
        module_filename = f"{module_name}.py"
    if not isinstance(code_content, str) or not code_content.strip():
        return None

    test_artifact_content = ""
    test_filename = "tests_tests.py"
    for artifact in output.artifacts:
        if artifact.artifact_type != ArtifactType.TEST:
            continue
        if isinstance(artifact.content, str) and artifact.content.strip() and not test_artifact_content:
            test_artifact_content = artifact.content
        if artifact.path and test_filename == "tests_tests.py":
            test_filename = artifact.path.rsplit("/", 1)[-1]

    test_content = test_artifact_content or output.raw_content
    code_exact_test_contract = context.get("code_exact_test_contract", "")
    code_behavior_contract = context.get("code_behavior_contract")
    return ValidationRuntimeInput(
        module_name=module_name,
        module_filename=module_filename,
        code_content=code_content,
        test_artifact_content=test_artifact_content,
        test_content=test_content,
        test_filename=test_filename,
        code_exact_test_contract=code_exact_test_contract if isinstance(code_exact_test_contract, str) else "",
        code_behavior_contract=code_behavior_contract if isinstance(code_behavior_contract, str) else "",
    )


def replace_test_output_content(
    output: AgentOutput,
    test_artifact_content: str,
    new_test_content: str,
    summarize_output: Any,
) -> tuple[str, str]:
    output.raw_content = new_test_content
    output.summary = summarize_output(new_test_content)
    for artifact in output.artifacts:
        if artifact.artifact_type != ArtifactType.TEST:
            continue
        artifact.content = new_test_content
    updated_test_artifact_content = new_test_content if test_artifact_content else test_artifact_content
    return new_test_content, updated_test_artifact_content


def record_test_validation_metadata(
    output: AgentOutput,
    test_analysis: dict[str, Any],
    test_execution: dict[str, Any],
    completion_diagnostics: dict[str, Any],
    module_filename: str,
    test_filename: str,
    pytest_failure_origin: str,
    record_output_validation: Any,
) -> None:
    record_output_validation(output, "test_analysis", test_analysis)
    record_output_validation(output, "test_execution", test_execution)
    record_output_validation(output, "completion_diagnostics", completion_diagnostics)
    record_output_validation(output, "module_filename", module_filename)
    record_output_validation(output, "test_filename", test_filename)
    record_output_validation(output, "pytest_failure_origin", pytest_failure_origin)


def record_code_validation_metadata(
    output: AgentOutput,
    code_analysis: dict[str, Any],
    task_public_contract_preflight: Optional[dict[str, Any]],
    import_validation: Optional[dict[str, Any]],
    completion_diagnostics: dict[str, Any],
    record_output_validation: Any,
) -> None:
    record_output_validation(output, "code_analysis", code_analysis)
    if task_public_contract_preflight is not None:
        record_output_validation(output, "task_public_contract_preflight", task_public_contract_preflight)
    if import_validation is not None:
        record_output_validation(output, "import_validation", import_validation)
    record_output_validation(output, "completion_diagnostics", completion_diagnostics)


def validate_code_output_runtime(
    output: AgentOutput,
    line_budget: Optional[int],
    requires_cli_entrypoint: bool,
    should_validate_code_content: Any,
    analyze_python_module: Any,
    output_line_count: Any,
    task_public_contract_preflight: Any,
    completion_diagnostics_from_output: Any,
    artifact_filename: Any,
    execute_generated_module_import: Any,
    record_output_validation: Any,
    completion_validation_issue: Any,
) -> None:
    code_artifact_content = ""
    for artifact in output.artifacts:
        if artifact.artifact_type != ArtifactType.CODE:
            continue
        if isinstance(artifact.content, str) and artifact.content.strip():
            code_artifact_content = artifact.content
            break
    code_content = code_artifact_content or output.raw_content
    if not should_validate_code_content(code_content, has_typed_artifact=bool(code_artifact_content)):
        return

    code_analysis = analyze_python_module(code_content)
    code_analysis["line_count"] = output_line_count(code_content)
    if line_budget is not None:
        code_analysis["line_budget"] = line_budget
    if requires_cli_entrypoint:
        code_analysis["main_guard_required"] = True
    task_public_contract_preflight_result = task_public_contract_preflight(code_analysis)
    completion_diagnostics = completion_diagnostics_from_output(
        output,
        raw_content=code_content,
        syntax_ok=code_analysis.get("syntax_ok", True),
        syntax_error=code_analysis.get("syntax_error"),
    )
    import_validation: Optional[dict[str, Any]] = None
    third_party_imports = code_analysis.get("third_party_imports") or []
    if code_analysis.get("syntax_ok", True) and not third_party_imports:
        module_filename = artifact_filename(output, ArtifactType.CODE, default_filename="code_implementation.py")
        import_validation = execute_generated_module_import(module_filename, code_content)

    record_code_validation_metadata(
        output,
        code_analysis,
        task_public_contract_preflight_result,
        import_validation,
        completion_diagnostics,
        record_output_validation,
    )
    validation_issues = collect_code_validation_issues(
        code_analysis,
        line_budget,
        task_public_contract_preflight_result,
        import_validation,
        completion_diagnostics,
        completion_validation_issue,
    )
    if validation_issues:
        raise AgentExecutionError(f"Generated code validation failed: {'; '.join(validation_issues)}")


def validate_dependency_output_runtime(
    context: dict[str, Any],
    output: AgentOutput,
    analyze_dependency_manifest: Any,
    record_output_validation: Any,
) -> None:
    raw_code_analysis = context.get("code_analysis")
    code_analysis = cast(dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
    dependency_analysis = analyze_dependency_manifest(output.raw_content, code_analysis)
    record_output_validation(output, "dependency_analysis", dependency_analysis)
    if dependency_analysis.get("is_valid"):
        return
    validation_failures: list[str] = []
    missing_entries = ", ".join(dependency_analysis.get("missing_manifest_entries") or [])
    if missing_entries:
        validation_failures.append(f"missing manifest entries for {missing_entries}")
    provenance_violations = ", ".join(dependency_analysis.get("provenance_violations") or [])
    if provenance_violations:
        validation_failures.append(
            f"unsupported dependency sources or installer directives: {provenance_violations}"
        )
    failure_summary = "; ".join(validation_failures) or "unknown dependency validation failure"
    raise AgentExecutionError(f"Dependency manifest validation failed: {failure_summary}")


def validate_task_output(
    task: Task,
    context: dict[str, Any],
    output: AgentOutput,
    *,
    validate_code_output: Callable[..., None],
    validate_test_output: Callable[..., None],
) -> None:
    from kycortex_agents.orchestration.workflow_control import execution_agent_name

    normalized_role = AgentRegistry.normalize_key(execution_agent_name(task))
    if normalized_role == "code_engineer":
        validate_code_output(output, task=task)
        return
    if normalized_role == "qa_tester":
        validate_test_output(context, output, task=task)
        return
    if normalized_role != "dependency_manager":
        return
    validate_dependency_output_runtime(
        context,
        output,
        analyze_dependency_manifest,
        lambda current_output, key, value: current_output.metadata.setdefault("validation", {}).__setitem__(key, value)
        if isinstance(current_output.metadata.setdefault("validation", {}), dict)
        else None,
    )


def build_test_validation_runtime_state(
    output: AgentOutput,
    test_artifact_content: str,
    test_content: str,
    module_name: str,
    module_filename: str,
    code_content: str,
    code_analysis: dict[str, Any],
    code_exact_test_contract: str,
    code_behavior_contract: str,
    test_filename: str,
    line_budget: Optional[int],
    exact_test_count: Optional[int],
    max_test_count: Optional[int],
    fixture_budget: Optional[int],
    finalize_generated_test_suite: Any,
    should_validate_test_content: Any,
    analyze_test_module: Any,
    auto_fix_test_type_mismatches: Any,
    output_line_count: Any,
    execute_generated_tests: Any,
    completion_diagnostics_from_output: Any,
    pytest_failure_origin: Any,
    summarize_output: Any,
) -> Optional[ValidationRuntimeState]:
    finalized_test_content = finalize_generated_test_suite(
        test_content,
        module_name=module_name,
        implementation_code=code_content,
        code_exact_test_contract=code_exact_test_contract,
    )
    if finalized_test_content != test_content:
        test_content, test_artifact_content = replace_test_output_content(
            output,
            test_artifact_content,
            finalized_test_content,
            summarize_output,
        )

    if not should_validate_test_content(test_content, has_typed_artifact=bool(test_artifact_content)):
        return None

    test_analysis = analyze_test_module(
        test_content,
        module_name,
        code_analysis,
        code_behavior_contract,
    )

    fixed_test_content = auto_fix_test_type_mismatches(test_content, code_content)
    if fixed_test_content != test_content:
        test_content, test_artifact_content = replace_test_output_content(
            output,
            test_artifact_content,
            fixed_test_content,
            summarize_output,
        )
        test_analysis = analyze_test_module(
            test_content,
            module_name,
            code_analysis,
            code_behavior_contract,
        )

    test_analysis["line_count"] = output_line_count(test_content)
    if line_budget is not None:
        test_analysis["line_budget"] = line_budget
    if exact_test_count is not None:
        test_analysis["expected_top_level_test_count"] = exact_test_count
    if max_test_count is not None:
        test_analysis["max_top_level_test_count"] = max_test_count
    if fixture_budget is not None:
        test_analysis["fixture_budget"] = fixture_budget

    test_execution = execute_generated_tests(module_filename, code_content, test_filename, test_content)
    completion_diagnostics = completion_diagnostics_from_output(
        output,
        raw_content=test_content,
        syntax_ok=test_analysis.get("syntax_ok", True),
        syntax_error=test_analysis.get("syntax_error"),
    )
    return ValidationRuntimeState(
        test_content=test_content,
        test_artifact_content=test_artifact_content,
        test_analysis=test_analysis,
        test_execution=test_execution,
        completion_diagnostics=completion_diagnostics,
        module_filename=module_filename,
        test_filename=test_filename,
        pytest_failure_origin=pytest_failure_origin(test_execution, module_filename, test_filename),
    )


def validate_test_output_runtime(
    context: dict[str, Any],
    output: AgentOutput,
    line_budget: Optional[int],
    exact_test_count: Optional[int],
    max_test_count: Optional[int],
    fixture_budget: Optional[int],
    finalize_generated_test_suite: Any,
    should_validate_test_content: Any,
    analyze_test_module: Any,
    auto_fix_test_type_mismatches: Any,
    output_line_count: Any,
    execute_generated_tests: Any,
    completion_diagnostics_from_output: Any,
    pytest_failure_origin: Any,
    record_output_validation: Any,
    completion_validation_issue: Any,
    summarize_output: Any,
) -> None:
    raw_code_analysis = context.get("code_analysis")
    code_analysis = cast(dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
    if code_analysis and not code_analysis.get("syntax_ok", True):
        raise AgentExecutionError(
            f"Generated test validation failed: code under test has syntax error {code_analysis.get('syntax_error') or 'unknown syntax error'}"
        )

    runtime_input = build_test_validation_runtime_input(context, output)
    if runtime_input is None:
        return
    runtime_state = build_test_validation_runtime_state(
        output,
        runtime_input.test_artifact_content,
        runtime_input.test_content,
        runtime_input.module_name,
        runtime_input.module_filename,
        runtime_input.code_content,
        code_analysis,
        runtime_input.code_exact_test_contract,
        runtime_input.code_behavior_contract,
        runtime_input.test_filename,
        line_budget,
        exact_test_count,
        max_test_count,
        fixture_budget,
        finalize_generated_test_suite,
        should_validate_test_content,
        analyze_test_module,
        auto_fix_test_type_mismatches,
        output_line_count,
        execute_generated_tests,
        completion_diagnostics_from_output,
        pytest_failure_origin,
        summarize_output,
    )
    if runtime_state is None:
        return

    record_test_validation_metadata(
        output,
        runtime_state.test_analysis,
        runtime_state.test_execution,
        runtime_state.completion_diagnostics,
        runtime_state.module_filename,
        runtime_state.test_filename,
        runtime_state.pytest_failure_origin,
        record_output_validation,
    )
    validation_issues, warning_issues, pytest_passed = collect_test_validation_issues(
        runtime_state.test_analysis,
        runtime_state.test_execution,
        runtime_state.completion_diagnostics,
        completion_validation_issue,
    )
    error_message = validation_error_message_for_test_result(
        validation_issues,
        warning_issues,
        pytest_passed,
    )
    if error_message:
        raise AgentExecutionError(error_message)