"""Validation-runtime helpers used by the Orchestrator facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, cast

from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.orchestration.validation_analysis import (
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