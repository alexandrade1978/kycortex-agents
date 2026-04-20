import ast
import importlib.util
import logging
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Any, Optional, cast

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None  # type: ignore[assignment]

from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.agents.registry import AgentRegistry, build_default_registry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestration.agent_runtime import build_agent_input, execute_agent
from kycortex_agents.orchestration.ast_tools import (
    ast_name,
    callable_name,
    first_call_argument,
    is_pytest_fixture,
    python_import_roots,
)
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.artifacts import failed_artifact_content
from kycortex_agents.orchestration.dependency_analysis import (
    analyze_dependency_manifest,
    normalize_import_name,
    normalize_package_name,
)
from kycortex_agents.orchestration.output_helpers import (
    normalize_agent_result,
    semantic_output_key,
    summarize_output,
    unredacted_agent_result,
)
from kycortex_agents.orchestration.module_ast_analysis import (
    annotation_accepts_sequence_input,
    build_code_outline,
    callable_parameter_names,
    collect_isinstance_calls,
    comparison_required_field,
    call_signature_details,
    call_expression_basename,
    dataclass_field_has_default,
    dataclass_field_is_init_enabled,
    dict_accessed_keys_from_tree,
    direct_return_expression,
    example_from_default,
    extract_batch_rule,
    extract_class_definition_style,
    extract_constructor_storage_rule,
    extract_indirect_required_fields,
    extract_lookup_field_rules,
    extract_required_fields,
    extract_score_derivation_rule,
    extract_return_type_annotation,
    extract_sequence_input_rule,
    extract_type_constraints,
    extract_valid_literal_examples,
    expand_local_name_aliases,
    field_selector_name,
    first_user_parameter,
    function_returns_score_value,
    has_dataclass_decorator,
    infer_dict_key_value_examples,
    inline_score_helper_expression,
    isinstance_subject_name,
    isinstance_type_names,
    method_binding_kind,
    parameter_is_iterated,
    render_score_expression,
    self_assigned_attributes,
)
from kycortex_agents.orchestration.repair_analysis import (
    ast_is_empty_literal,
    attribute_is_field_reference,
    class_field_uses_empty_default,
    compare_mentions_invalid_literal,
    dataclass_default_order_repair_examples,
    class_field_annotations_from_failed_artifact,
    class_field_names_from_failed_artifact,
    default_value_for_annotation,
    duplicate_constructor_argument_call_details,
    duplicate_constructor_argument_call_hint,
    duplicate_constructor_argument_details,
    duplicate_constructor_explicit_rewrite_hint,
    failing_pytest_test_names,
    failed_artifact_content_for_category,
    first_non_import_line_with_name,
    internal_constructor_strictness_details,
    invalid_outcome_audit_return_details,
    invalid_outcome_missing_audit_trail_details,
    is_len_of_field_reference,
    missing_import_nameerror_details,
    missing_object_attribute_details,
    missing_required_constructor_details,
    nested_payload_wrapper_field_validation_details,
    plain_class_field_default_factory_details,
    render_name_list,
    required_field_list_from_failed_artifact,
    suggest_declared_attribute_replacement,
    test_function_targets_invalid_path,
    test_requires_non_empty_result_field,
)
from kycortex_agents.orchestration.repair_signals import (
    content_has_bare_datetime_reference,
    content_has_incomplete_required_evidence_payload,
    content_has_matching_datetime_import,
    implementation_prefers_direct_datetime_import,
    implementation_required_evidence_items,
    validation_summary_has_missing_datetime_import_issue,
    validation_summary_has_required_evidence_runtime_issue,
)
from kycortex_agents.orchestration.repair_test_analysis import (
    failed_test_requires_code_repair,
    imported_code_task_for_failed_test,
    is_helper_alias_like_name,
    module_defined_symbol_names,
    normalized_helper_surface_symbols,
    previous_valid_test_surface,
    qa_repair_should_reuse_failed_test_artifact,
    helper_surface_usages_for_test_repair,
    upstream_code_task_for_test_failure,
    validation_summary_helper_alias_names,
    validation_summary_symbols,
)
from kycortex_agents.orchestration.repair_focus import (
    build_repair_focus_lines,
)
from kycortex_agents.orchestration.repair_instructions import (
    build_code_repair_instruction_from_test_failure,
    build_repair_instruction,
    repair_owner_for_category,
)
from kycortex_agents.orchestration.sandbox_execution import (
    execute_generated_module_import,
    execute_generated_tests,
    sandbox_security_violation,
    write_generated_import_runner,
    write_generated_test_runner,
)
from kycortex_agents.orchestration.sandbox_runtime import build_generated_test_env, build_sandbox_preexec_fn, sanitize_generated_filename
from kycortex_agents.orchestration.task_constraints import (
    build_budget_decomposition_instruction,
    build_budget_decomposition_task_context,
    compact_architecture_context,
    is_budget_decomposition_planner,
    parse_task_public_contract_surface,
    repair_requires_budget_decomposition,
    should_compact_architecture_context,
    summary_limit_exceeded,
    task_public_contract_anchor,
    task_public_contract_preflight,
    task_exact_top_level_test_count,
    task_fixture_budget,
    task_line_budget,
    task_max_top_level_test_count,
    task_requires_cli_entrypoint,
)
from kycortex_agents.orchestration.test_ast_analysis import (
    assert_expects_false,
    assert_expects_invalid_outcome,
    assert_limits_batch_result,
    assigned_name_for_call,
    analyze_typed_test_member_usage,
    ast_contains_node,
    behavior_contract_explicitly_limits_score_state_to_valid_requests,
    batch_call_allows_partial_invalid_items,
    call_argument_count,
    bound_target_names,
    call_argument_value,
    call_expects_invalid_outcome,
    call_has_negative_expectation,
    collect_local_bindings,
    collect_local_name_bindings,
    collect_module_defined_names,
    collect_mock_support,
    collect_parametrized_argument_names,
    collect_test_local_types,
    collect_undefined_local_names,
    comparison_implies_partial_batch_result,
    count_test_assertion_like_checks,
    exact_len_assertion,
    extract_literal_dict_keys,
    extract_literal_field_values,
    extract_literal_list_items,
    extract_parametrize_argument_names,
    extract_string_literals,
    find_contract_overreach_signals,
    find_unsupported_mock_assertions,
    function_argument_names,
    infer_argument_type,
    infer_call_result_type,
    infer_expression_type,
    int_constant_value,
    invalid_outcome_marker_matches,
    invalid_outcome_subject_matches,
    is_internal_score_state_target,
    is_len_call,
    is_mock_factory_call,
    is_patch_call,
    iter_relevant_test_body_nodes,
    known_type_allows_member,
    len_call_matches_batch_result,
    loop_contains_non_batch_call,
    parent_map,
    payload_argument_for_validation,
    patched_target_name_from_call,
    resolve_bound_value,
    name_suggests_validation_failure,
    validate_batch_call,
    visible_repeated_single_call_batch_sizes,
    with_uses_pytest_assertion_context,
    with_uses_pytest_raises,
    supports_mock_assertion_target,
)
from kycortex_agents.orchestration.validation_reporting import (
    build_code_validation_summary,
    build_dependency_validation_summary,
    build_test_validation_summary,
    completion_diagnostics_from_provider_call,
    completion_diagnostics_summary,
    completion_hit_limit,
    completion_validation_issue,
    looks_structurally_truncated,
)
from kycortex_agents.orchestration.validation_runtime import (
    provider_call_metadata,
    redact_validation_execution_result,
    sanitize_output_provider_call_metadata,
    summarize_pytest_output,
)
from kycortex_agents.orchestration.validation_analysis import (
    BLOCKING_TEST_ISSUE_KEYS as _BLOCKING_TEST_ISSUE_KEYS,
    pytest_contract_overreach_signals,
    pytest_failure_details,
    pytest_failure_is_semantic_assertion_mismatch,
    pytest_failure_origin,
    validation_has_blocking_issues,
    validation_has_only_warnings,
    validation_has_static_issues,
)
from kycortex_agents.orchestration.workflow_control import (
    active_repair_cycle,
    build_code_repair_context_from_test_failure,
    configure_repair_attempts,
    continue_workflow_after_task_failure,
    build_repair_context,
    ensure_workflow_running,
    ensure_budget_decomposition_task,
    fail_workflow_for_definition_error,
    fail_workflow_when_blocked,
    failed_task_ids_for_repair,
    finish_workflow_if_no_pending_tasks,
    has_repair_task_for_cycle,
    cancel_workflow,
    emit_workflow_progress,
    exit_if_workflow_cancelled,
    exit_if_workflow_paused,
    log_event,
    merge_prior_repair_context,
    override_task,
    pause_workflow,
    privacy_safe_log_fields,
    repair_task_ids_for_cycle,
    resume_failed_workflow_tasks,
    resume_failed_tasks_with_repair_cycle,
    resume_workflow_tasks,
    replay_workflow,
    resume_workflow,
    skip_task,
    task_id_collection_count,
    task_id_count_log_field_name,
    validate_agent_resolution,
    queue_active_cycle_repair,
)
from kycortex_agents.orchestration.workflow_acceptance import evaluate_workflow_acceptance
from kycortex_agents.providers.base import (
    redact_sensitive_data,
    sanitize_provider_call_metadata,
)
from kycortex_agents.types import (
    AgentView,
    AgentViewArtifactRecord,
    AgentViewDecisionRecord,
    AgentViewTaskResult,
    AgentInput,
    AgentOutput,
    ArtifactRecord,
    ArtifactType,
    ExecutionSandboxPolicy,
    FailureCategory,
    ProjectSnapshot,
    TaskStatus,
    TaskResult,
    WorkflowOutcome,
)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


_STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", set()))
_PYTEST_BUILTIN_FIXTURES = {
    "cache",
    "capfd",
    "capfdbinary",
    "caplog",
    "capsys",
    "capsysbinary",
    "capteesys",
    "doctest_namespace",
    "monkeypatch",
    "pytestconfig",
    "record_property",
    "record_testsuite_property",
    "record_xml_attribute",
    "recwarn",
    "tmp_path",
    "tmp_path_factory",
    "tmpdir",
    "tmpdir_factory",
}
_ZERO_BUDGET_FAILURE_CATEGORIES = frozenset({FailureCategory.SANDBOX_SECURITY_VIOLATION.value})
_RESERVED_FIXTURE_NAMES = {"request"}

# ---------------------------------------------------------------------------
# Test issue severity classification — Phase 3 (Model Adaptation Layer)
# BLOCKING issues prevent test execution or indicate security risks.
# WARNING issues may be false positives for models that generate structurally
# different but functionally correct code; the pytest arbiter decides.
# ---------------------------------------------------------------------------
def _example_from_default(node: ast.expr) -> str | None:
    """Return an example literal string for a .get() default AST node."""
    return example_from_default(node)


class Orchestrator:
    """Public workflow runtime for executing tasks with a configured or custom registry.

    Pass a custom AgentRegistry when consumers need to register their own agent
    implementations while keeping `execute_workflow()` and `run_task()` as the
    supported execution entry points.
    """

    def __init__(self, config: Optional[KYCortexConfig] = None, registry: Optional[AgentRegistry] = None):
        self.config = config or KYCortexConfig()
        self.registry = registry or build_default_registry(self.config)
        self.logger = logging.getLogger("Orchestrator")

    def _log_event(self, level: str, event: str, **fields: Any) -> None:
        log_event(self.logger, level, event, **fields)

    @staticmethod
    def _privacy_safe_log_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
        return privacy_safe_log_fields(fields)

    @staticmethod
    def _task_id_collection_count(value: Any) -> Optional[int]:
        return task_id_collection_count(value)

    @staticmethod
    def _task_id_count_log_field_name(field_name: str) -> Optional[str]:
        return task_id_count_log_field_name(field_name)

    def _emit_workflow_progress(self, project: ProjectState, *, task: Optional[Task] = None) -> None:
        emit_workflow_progress(self.logger, project, task=task)

    def pause_workflow(self, project: ProjectState, *, reason: str) -> bool:
        """Pause a workflow so the orchestrator stops dispatching new runnable tasks."""

        return pause_workflow(self.logger, project, reason=reason)

    def resume_workflow(self, project: ProjectState, *, reason: str = "paused_workflow") -> bool:
        """Resume a paused workflow so execution can continue on the next run."""

        return resume_workflow(self.logger, project, reason=reason)

    def cancel_workflow(self, project: ProjectState, *, reason: str = "manual_cancel") -> list[str]:
        """Cancel a workflow through the orchestrator control surface."""

        return cancel_workflow(self.logger, project, reason=reason)

    def skip_task(self, project: ProjectState, task_id: str, *, reason: str) -> bool:
        """Skip a task manually through the orchestrator control surface."""

        return skip_task(self.logger, project, task_id, reason=reason)

    def override_task(self, project: ProjectState, task_id: str, output: str | AgentOutput, *, reason: str) -> bool:
        """Complete a task manually through the orchestrator control surface."""

        return override_task(self.logger, project, task_id, output, reason=reason)

    def replay_workflow(self, project: ProjectState, *, reason: str = "manual_replay") -> list[str]:
        """Reset a workflow so it can be executed again from its initial task set."""

        return replay_workflow(self.logger, project, reason=reason)

    def _exit_if_workflow_paused(self, project: ProjectState) -> bool:
        return exit_if_workflow_paused(self.logger, project)

    def _exit_if_workflow_cancelled(self, project: ProjectState) -> bool:
        return exit_if_workflow_cancelled(self.logger, project)

    def run_task(self, task: Task, project: ProjectState) -> str:
        """Execute one task through the public orchestrator runtime contract."""
        execution_agent_name = self._execution_agent_name(task)
        self._log_event(
            "info",
            "task_started",
            project_name=project.project_name,
            task_id=task.id,
            task_title=task.title,
            assigned_to=execution_agent_name,
            attempt=task.attempts + 1,
        )
        agent = self.registry.get(execution_agent_name)
        agent_input = self._build_agent_input(task, project)
        project.start_task(task.id)
        normalized_output: Optional[AgentOutput] = None
        try:
            output = execute_agent(agent, agent_input)
            normalized_output = normalize_agent_result(output)
            normalized_output = unredacted_agent_result(agent, normalized_output)
            normalized_output = self._sanitize_output_provider_call_metadata(normalized_output)
            self._validate_task_output(task, agent_input.context, normalized_output)
            self._persist_artifacts(normalized_output.artifacts)
            for decision in normalized_output.decisions:
                project.add_decision_record(decision)
            for artifact in normalized_output.artifacts:
                project.add_artifact_record(artifact)
            provider_call = self._provider_call_metadata(agent, normalized_output)
            project.complete_task(task.id, normalized_output, provider_call=provider_call)
        except Exception as exc:
            failure_category = self._classify_task_failure(task, exc)
            project.fail_task(
                task.id,
                exc,
                provider_call=self._provider_call_metadata(agent, normalized_output),
                output=normalized_output,
                error_category=failure_category,
            )
            if project.should_retry_task(task.id):
                self._log_event(
                    "warning",
                    "task_retry_scheduled",
                    project_name=project.project_name,
                    task_id=task.id,
                    task_title=task.title,
                    assigned_to=execution_agent_name,
                    attempt=task.attempts,
                    error_type=type(exc).__name__,
                )
            else:
                provider_call = self._provider_call_metadata(agent, normalized_output)
                self._log_event(
                    "error",
                    "task_failed",
                    project_name=project.project_name,
                    task_id=task.id,
                    task_title=task.title,
                    assigned_to=execution_agent_name,
                    attempt=task.attempts,
                    error_type=type(exc).__name__,
                    provider=provider_call.get("provider") if provider_call else None,
                    model=provider_call.get("model") if provider_call else None,
                )
            raise
        self._log_event(
            "info",
            "task_completed",
            project_name=project.project_name,
            task_id=task.id,
            task_title=task.title,
            assigned_to=execution_agent_name,
            attempt=task.attempts,
            provider=provider_call.get("provider") if provider_call else None,
            model=provider_call.get("model") if provider_call else None,
            total_tokens=(provider_call.get("usage") or {}).get("total_tokens") if provider_call else None,
        )
        return normalized_output.raw_content

    def _validate_task_output(self, task: Task, context: Dict[str, Any], output: AgentOutput) -> None:
        normalized_role = AgentRegistry.normalize_key(self._execution_agent_name(task))
        if normalized_role == "code_engineer":
            self._validate_code_output(output, task=task)
            return
        if normalized_role == "qa_tester":
            self._validate_test_output(context, output, task=task)
            return
        if normalized_role != "dependency_manager":
            return
        raw_code_analysis = context.get("code_analysis")
        code_analysis = cast(Dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
        dependency_analysis = self._analyze_dependency_manifest(output.raw_content, code_analysis)
        self._record_output_validation(output, "dependency_analysis", dependency_analysis)
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

    def _validate_code_output(self, output: AgentOutput, task: Optional[Task] = None) -> None:
        code_artifact_content = self._artifact_content(output, ArtifactType.CODE)
        code_content = code_artifact_content or output.raw_content
        if not self._should_validate_code_content(code_content, has_typed_artifact=bool(code_artifact_content)):
            return
        code_analysis = self._analyze_python_module(code_content)
        code_analysis["line_count"] = self._output_line_count(code_content)
        line_budget = self._task_line_budget(task)
        if line_budget is not None:
            code_analysis["line_budget"] = line_budget
        if self._task_requires_cli_entrypoint(task):
            code_analysis["main_guard_required"] = True
        task_public_contract_preflight = self._task_public_contract_preflight(task, code_analysis)
        completion_diagnostics = self._completion_diagnostics_from_output(
            output,
            raw_content=code_content,
            syntax_ok=code_analysis.get("syntax_ok", True),
            syntax_error=code_analysis.get("syntax_error"),
        )
        import_validation: Optional[Dict[str, Any]] = None
        third_party_imports = code_analysis.get("third_party_imports") or []
        if code_analysis.get("syntax_ok", True) and not third_party_imports:
            module_filename = self._artifact_filename(
                output,
                ArtifactType.CODE,
                default_filename="code_implementation.py",
            )
            import_validation = self._execute_generated_module_import(module_filename, code_content)
        self._record_output_validation(output, "code_analysis", code_analysis)
        if task_public_contract_preflight is not None:
            self._record_output_validation(output, "task_public_contract_preflight", task_public_contract_preflight)
        if import_validation is not None:
            self._record_output_validation(output, "import_validation", import_validation)
        self._record_output_validation(output, "completion_diagnostics", completion_diagnostics)
        validation_issues: list[str] = []
        if not code_analysis.get("syntax_ok", True):
            validation_issues.append(f"syntax error {code_analysis.get('syntax_error') or 'unknown syntax error'}")
        if isinstance(line_budget, int) and code_analysis["line_count"] > line_budget:
            validation_issues.append(f"line count {code_analysis['line_count']} exceeds maximum {line_budget}")
        if code_analysis.get("main_guard_required") and not code_analysis.get("has_main_guard"):
            validation_issues.append("missing required CLI entrypoint")
        if (
            isinstance(import_validation, dict)
            and import_validation.get("ran")
            and import_validation.get("returncode") not in (None, 0)
        ):
            import_summary = import_validation.get("summary") or "generated module failed to import"
            validation_issues.append(f"module import failed: {import_summary}")
        if isinstance(task_public_contract_preflight, dict):
            contract_issues = task_public_contract_preflight.get("issues") or []
            if contract_issues:
                validation_issues.append(f"task public contract mismatch: {', '.join(contract_issues)}")
        invalid_dataclass_field_usages = code_analysis.get("invalid_dataclass_field_usages") or []
        if invalid_dataclass_field_usages:
            validation_issues.append(
                f"non-dataclass field(...) usage: {', '.join(invalid_dataclass_field_usages)}"
            )
        if completion_diagnostics.get("likely_truncated"):
            validation_issues.append(self._completion_validation_issue(completion_diagnostics))
        if validation_issues:
            raise AgentExecutionError(f"Generated code validation failed: {'; '.join(validation_issues)}")

    def _task_public_contract_preflight(
        self,
        task: Optional[Task],
        code_analysis: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return task_public_contract_preflight(task, code_analysis)

    def _parse_task_public_contract_surface(self, surface: str) -> tuple[Optional[str], str, list[str]]:
        return parse_task_public_contract_surface(surface)

    def _execute_generated_module_import(self, module_filename: str, code_content: str) -> Dict[str, Any]:
        return execute_generated_module_import(
            module_filename,
            code_content,
            self.config.execution_sandbox_policy(),
            python_executable=sys.executable,
            host_env=os.environ,
            subprocess_run=subprocess.run,
            sanitize_filename=self._sanitize_generated_filename,
            write_import_runner_fn=self._write_generated_import_runner,
            build_env_fn=self._build_generated_test_env,
            build_preexec_fn=self._sandbox_preexec_fn,
            redact_result=self._redact_validation_execution_result,
        )

    def _validate_test_output(self, context: Dict[str, Any], output: AgentOutput, task: Optional[Task] = None) -> None:
        raw_code_analysis = context.get("code_analysis")
        code_analysis = cast(Dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
        if code_analysis and not code_analysis.get("syntax_ok", True):
            raise AgentExecutionError(
                f"Generated test validation failed: code under test has syntax error {code_analysis.get('syntax_error') or 'unknown syntax error'}"
            )

        module_name = context.get("module_name")
        module_filename = context.get("module_filename")
        code_content = context.get("code")
        if not isinstance(module_name, str) or not module_name.strip():
            return
        if not isinstance(module_filename, str) or not module_filename.strip():
            module_filename = f"{module_name}.py"
        if not isinstance(code_content, str) or not code_content.strip():
            return

        test_artifact_content = self._artifact_content(output, ArtifactType.TEST)
        test_content = test_artifact_content or output.raw_content
        code_exact_test_contract = context.get("code_exact_test_contract", "")
        finalized_test_content = QATesterAgent._finalize_generated_test_suite(
            test_content,
            module_name=module_name,
            implementation_code=code_content,
            code_exact_test_contract=code_exact_test_contract if isinstance(code_exact_test_contract, str) else "",
        )
        if finalized_test_content != test_content:
            output.raw_content = finalized_test_content
            output.summary = summarize_output(finalized_test_content)
            for artifact in output.artifacts:
                if artifact.artifact_type != ArtifactType.TEST:
                    continue
                artifact.content = finalized_test_content
            test_artifact_content = finalized_test_content if test_artifact_content else test_artifact_content
            test_content = finalized_test_content
        if not self._should_validate_test_content(test_content, has_typed_artifact=bool(test_artifact_content)):
            return
        test_filename = self._artifact_filename(output, ArtifactType.TEST, default_filename="tests_tests.py")
        code_behavior_contract = context.get("code_behavior_contract")
        test_analysis = self._analyze_test_module(
            test_content,
            module_name,
            code_analysis,
            code_behavior_contract if isinstance(code_behavior_contract, str) else "",
        )

        # --- Auto-fix type mismatches (str → dict) before pytest ---
        if isinstance(code_content, str):
            fixed_test_content = self._auto_fix_test_type_mismatches(
                test_content, code_content
            )
            if fixed_test_content != test_content:
                test_content = fixed_test_content
                output.raw_content = test_content
                output.summary = summarize_output(test_content)
                for artifact in output.artifacts:
                    if artifact.artifact_type != ArtifactType.TEST:
                        continue
                    artifact.content = test_content
                test_artifact_content = test_content if test_artifact_content else test_artifact_content
                test_analysis = self._analyze_test_module(
                    test_content,
                    module_name,
                    code_analysis,
                    code_behavior_contract if isinstance(code_behavior_contract, str) else "",
                )

        test_analysis["line_count"] = self._output_line_count(test_content)
        line_budget = self._task_line_budget(task)
        if line_budget is not None:
            test_analysis["line_budget"] = line_budget
        exact_test_count = self._task_exact_top_level_test_count(task)
        if exact_test_count is not None:
            test_analysis["expected_top_level_test_count"] = exact_test_count
        max_test_count = self._task_max_top_level_test_count(task)
        if max_test_count is not None:
            test_analysis["max_top_level_test_count"] = max_test_count
        fixture_budget = self._task_fixture_budget(task)
        if fixture_budget is not None:
            test_analysis["fixture_budget"] = fixture_budget
        test_execution = self._execute_generated_tests(module_filename, code_content, test_filename, test_content)
        completion_diagnostics = self._completion_diagnostics_from_output(
            output,
            raw_content=test_content,
            syntax_ok=test_analysis.get("syntax_ok", True),
            syntax_error=test_analysis.get("syntax_error"),
        )
        self._record_output_validation(output, "test_analysis", test_analysis)
        self._record_output_validation(output, "test_execution", test_execution)
        self._record_output_validation(output, "completion_diagnostics", completion_diagnostics)
        self._record_output_validation(output, "module_filename", module_filename)
        self._record_output_validation(output, "test_filename", test_filename)
        self._record_output_validation(
            output,
            "pytest_failure_origin",
            self._pytest_failure_origin(test_execution, module_filename, test_filename),
        )

        validation_issues: list[str] = []
        warning_issues: list[str] = []
        if not test_analysis.get("syntax_ok", True):
            validation_issues.append(f"test syntax error {test_analysis.get('syntax_error') or 'unknown syntax error'}")
        if isinstance(line_budget, int) and test_analysis["line_count"] > line_budget:
            validation_issues.append(f"line count {test_analysis['line_count']} exceeds maximum {line_budget}")
        if isinstance(exact_test_count, int) and test_analysis.get("top_level_test_count") != exact_test_count:
            validation_issues.append(
                f"top-level test count {test_analysis.get('top_level_test_count')} does not match required {exact_test_count}"
            )
        if isinstance(max_test_count, int) and test_analysis.get("top_level_test_count", 0) > max_test_count:
            validation_issues.append(
                f"top-level test count {test_analysis.get('top_level_test_count')} exceeds maximum {max_test_count}"
            )
        if isinstance(fixture_budget, int) and test_analysis.get("fixture_count", 0) > fixture_budget:
            validation_issues.append(
                f"fixture count {test_analysis.get('fixture_count')} exceeds maximum {fixture_budget}"
            )
        tests_without_assertions = test_analysis.get("tests_without_assertions") or []
        if tests_without_assertions:
            warning_issues.append(
                f"tests without assertion-like checks: {', '.join(tests_without_assertions)}"
            )
        contract_overreach_signals = test_analysis.get("contract_overreach_signals") or []
        if contract_overreach_signals:
            warning_issues.append(
                f"contract overreach signals: {', '.join(contract_overreach_signals)}"
            )
        if test_analysis.get("helper_surface_usages") and (
            isinstance(line_budget, int) or isinstance(max_test_count, int) or isinstance(fixture_budget, int)
        ):
            validation_issues.append(
                f"helper surface usages: {', '.join(test_analysis.get('helper_surface_usages') or [])}"
            )
        for issue_key, label in (
            ("missing_function_imports", "missing function imports"),
            ("unknown_module_symbols", "unknown module symbols"),
            ("invalid_member_references", "invalid member references"),
            ("call_arity_mismatches", "call arity mismatches"),
            ("constructor_arity_mismatches", "constructor arity mismatches"),
            ("payload_contract_violations", "payload contract violations"),
            ("non_batch_sequence_calls", "non-batch sequence calls"),
            ("reserved_fixture_names", "reserved fixture names"),
            ("undefined_fixtures", "undefined test fixtures"),
            ("undefined_local_names", "undefined local names"),
            ("imported_entrypoint_symbols", "imported entrypoint symbols"),
            ("unsafe_entrypoint_calls", "unsafe entrypoint calls"),
            ("unsupported_mock_assertions", "unsupported mock assertions"),
        ):
            issues = test_analysis.get(issue_key) or []
            if issues:
                target = validation_issues if issue_key in _BLOCKING_TEST_ISSUE_KEYS else warning_issues
                target.append(f"{label}: {', '.join(issues)}")

        if completion_diagnostics.get("likely_truncated"):
            validation_issues.append(self._completion_validation_issue(completion_diagnostics))

        # --- Pytest arbiter: warnings are accepted when tests pass ---
        pytest_ran = test_execution.get("ran")
        pytest_passed = pytest_ran and test_execution.get("returncode") in (None, 0)

        if test_execution.get("ran") and test_execution.get("returncode") not in (None, 0):
            validation_issues.append(f"pytest failed: {test_execution.get('summary') or 'generated tests failed'}")

        if validation_issues:
            all_issues = validation_issues + [f"(warning) {w}" for w in warning_issues]
            raise AgentExecutionError(f"Generated test validation failed: {'; '.join(all_issues)}")

        if warning_issues and not pytest_passed:
            raise AgentExecutionError(
                f"Generated test validation failed: {'; '.join(warning_issues)} (pytest did not confirm correctness)"
            )
        # If only warnings and pytest passed → accept (warnings are false positives)

    def _output_line_count(self, raw_content: str) -> int:
        if not raw_content:
            return 0
        return len(raw_content.splitlines())

    def _task_line_budget(self, task: Optional[Task]) -> Optional[int]:
        return task_line_budget(task)

    def _task_requires_cli_entrypoint(self, task: Optional[Task]) -> bool:
        return task_requires_cli_entrypoint(task)

    def _should_compact_architecture_context(self, task: Optional[Task], task_public_contract_anchor: str) -> bool:
        execution_agent_name = self._execution_agent_name(task) if task is not None else None
        return should_compact_architecture_context(task, task_public_contract_anchor, execution_agent_name, self.config.max_tokens)

    def _compact_architecture_context(self, task: Task, task_public_contract_anchor: str) -> str:
        return compact_architecture_context(task, task_public_contract_anchor)

    def _task_exact_top_level_test_count(self, task: Optional[Task]) -> Optional[int]:
        return task_exact_top_level_test_count(task)

    def _task_max_top_level_test_count(self, task: Optional[Task]) -> Optional[int]:
        return task_max_top_level_test_count(task)

    def _task_fixture_budget(self, task: Optional[Task]) -> Optional[int]:
        return task_fixture_budget(task)

    def _classify_task_failure(self, task: Task, exc: Exception) -> str:
        normalized_role = AgentRegistry.normalize_key(self._execution_agent_name(task))
        if isinstance(exc, WorkflowDefinitionError):
            return FailureCategory.WORKFLOW_DEFINITION.value
        if isinstance(exc, ProviderTransientError):
            return FailureCategory.PROVIDER_TRANSIENT.value
        if self._is_sandbox_security_violation(exc):
            return FailureCategory.SANDBOX_SECURITY_VIOLATION.value
        if isinstance(exc, AgentExecutionError):
            if normalized_role == "code_engineer":
                return FailureCategory.CODE_VALIDATION.value
            if normalized_role == "qa_tester":
                return FailureCategory.TEST_VALIDATION.value
            if normalized_role == "dependency_manager":
                return FailureCategory.DEPENDENCY_VALIDATION.value
        return FailureCategory.TASK_EXECUTION.value

    def _is_sandbox_security_violation(self, exc: Exception) -> bool:
        return sandbox_security_violation(exc)

    def _is_repairable_failure(self, failure_category: str) -> bool:
        return failure_category in {
            FailureCategory.UNKNOWN.value,
            FailureCategory.TASK_EXECUTION.value,
            FailureCategory.CODE_VALIDATION.value,
            FailureCategory.TEST_VALIDATION.value,
            FailureCategory.DEPENDENCY_VALIDATION.value,
            FailureCategory.PROVIDER_TRANSIENT.value,
        }

    def _execution_agent_name(self, task: Task) -> str:
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        repair_owner = repair_context.get("repair_owner")
        if isinstance(repair_owner, str) and repair_owner.strip():
            return repair_owner
        return task.assigned_to

    def _artifact_content(self, output: AgentOutput, artifact_type: ArtifactType) -> str:
        for artifact in output.artifacts:
            if artifact.artifact_type != artifact_type:
                continue
            if isinstance(artifact.content, str) and artifact.content.strip():
                return artifact.content
        return ""

    def _artifact_filename(self, output: AgentOutput, artifact_type: ArtifactType, default_filename: str) -> str:
        for artifact in output.artifacts:
            if artifact.artifact_type != artifact_type:
                continue
            if artifact.path:
                return Path(artifact.path).name
        return default_filename

    def _record_output_validation(self, output: AgentOutput, key: str, value: Any) -> None:
        validation = output.metadata.setdefault("validation", {})
        if isinstance(validation, dict):
            validation[key] = value

    def _should_validate_code_content(self, content: str, has_typed_artifact: bool) -> bool:
        if has_typed_artifact:
            return True
        stripped = content.strip()
        if not stripped:
            return False
        return any(token in stripped for token in ("def ", "class ", "import ", "from ", "if __name__"))

    def _should_validate_test_content(self, content: str, has_typed_artifact: bool) -> bool:
        if has_typed_artifact:
            return True
        stripped = content.strip()
        if not stripped:
            return False
        return any(token in stripped for token in ("def test_", "assert ", "import pytest", "pytest."))

    def _execute_generated_tests(
        self,
        module_filename: str,
        code_content: str,
        test_filename: str,
        test_content: str,
    ) -> Dict[str, Any]:
        return execute_generated_tests(
            module_filename,
            code_content,
            test_filename,
            test_content,
            self.config.execution_sandbox_policy(),
            python_executable=sys.executable,
            host_env=os.environ,
            pytest_spec_finder=importlib.util.find_spec,
            subprocess_run=subprocess.run,
            sanitize_filename=self._sanitize_generated_filename,
            write_test_runner_fn=self._write_generated_test_runner,
            build_env_fn=self._build_generated_test_env,
            build_preexec_fn=self._sandbox_preexec_fn,
            summarize_output=self._summarize_pytest_output,
            redact_result=self._redact_validation_execution_result,
        )

    def _build_generated_test_env(
        self,
        tmp_path: Path,
        sandbox_policy: ExecutionSandboxPolicy,
    ) -> Dict[str, str]:
        return build_generated_test_env(tmp_path, sandbox_policy, host_env=os.environ)

    def _write_generated_test_runner(
        self,
        tmp_path: Path,
        test_filename: str,
        sandbox_enabled: bool,
    ) -> Path:
        return write_generated_test_runner(tmp_path, test_filename, sandbox_enabled)

    def _write_generated_import_runner(
        self,
        tmp_path: Path,
        module_filename: str,
        sandbox_enabled: bool,
    ) -> Path:
        return write_generated_import_runner(tmp_path, module_filename, sandbox_enabled)

    def _sanitize_generated_filename(self, filename: str, default_filename: str) -> str:
        return sanitize_generated_filename(filename, default_filename)

    def _sandbox_preexec_fn(self, sandbox_policy: ExecutionSandboxPolicy):
        return build_sandbox_preexec_fn(sandbox_policy, os_module=os, resource_module=resource)

    def _summarize_pytest_output(self, stdout: str, stderr: str, returncode: int) -> str:
        return summarize_pytest_output(stdout, stderr, returncode)

    @staticmethod
    def _redact_validation_execution_result(result: Dict[str, Any]) -> Dict[str, Any]:
        return redact_validation_execution_result(result)

    def _sanitize_provider_call_metadata(self, provider_call: Dict[str, Any]) -> Dict[str, Any]:
        return sanitize_provider_call_metadata(provider_call)

    def _sanitize_output_provider_call_metadata(self, output: AgentOutput) -> AgentOutput:
        return sanitize_output_provider_call_metadata(output)

    def _provider_call_metadata(self, agent: Any, output: Optional[AgentOutput] = None) -> Optional[Dict[str, Any]]:
        return provider_call_metadata(agent, output)

    def _persist_artifacts(self, artifacts: list[ArtifactRecord]) -> None:
        self._artifact_persistence_support().persist_artifacts(artifacts)

    def _resolve_artifact_output_path(self, artifact: ArtifactRecord) -> Path:
        return self._artifact_persistence_support().resolve_artifact_output_path(artifact)

    def _validate_artifact_output_path(self, target_path: Path) -> None:
        self._artifact_persistence_support().validate_artifact_output_path(target_path)

    def _sanitize_artifact_relative_path(self, artifact_path: str) -> Path:
        return self._artifact_persistence_support().sanitize_artifact_relative_path(artifact_path)

    def _artifact_record_path(self, target_path: Path) -> str:
        return self._artifact_persistence_support().artifact_record_path(target_path)

    def _default_artifact_path(self, artifact: ArtifactRecord) -> str:
        return self._artifact_persistence_support().default_artifact_path(artifact)

    def _artifact_persistence_support(self) -> ArtifactPersistenceSupport:
        return ArtifactPersistenceSupport(self.config.output_dir, sanitize_sub=re.sub)

    @staticmethod
    def _agent_visible_repair_context(repair_context: Dict[str, Any], execution_agent_name: str) -> Dict[str, Any]:
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

    def _build_context(self, task: Task, project: ProjectState) -> Dict[str, Any]:
        snapshot = project.snapshot()
        agent_view = self._build_agent_view(task, project, snapshot)
        visible_task_ids = self._task_dependency_closure_ids(task, project)
        execution_agent_name = self._execution_agent_name(task)
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        budget_decomposition_plan_task_id = repair_context.get("budget_decomposition_plan_task_id")
        if not isinstance(budget_decomposition_plan_task_id, str) or not budget_decomposition_plan_task_id.strip():
            budget_decomposition_plan_task_id = None
        ctx: Dict[str, Any] = {
            "goal": project.goal,
            "project_name": project.project_name,
            "phase": project.phase,
            "provider_max_tokens": self.config.max_tokens,
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "assigned_to": task.assigned_to,
                "execution_agent": execution_agent_name,
            },
            "snapshot": asdict(agent_view),
            "completed_tasks": {},
            "decisions": agent_view.decisions,
            "artifacts": agent_view.artifacts,
        }
        ctx.update(self._planned_module_context(project, visible_task_ids, current_task=task))
        planned_module_name = ctx.get("planned_module_name")
        planned_module_filename = ctx.get("planned_module_filename")
        if isinstance(planned_module_name, str) and planned_module_name.strip():
            ctx["module_name"] = planned_module_name
        if isinstance(planned_module_filename, str) and planned_module_filename.strip():
            ctx["module_filename"] = planned_module_filename
        task_public_contract_anchor = self._task_public_contract_anchor(task.description)
        compact_architecture_context: Optional[str] = None
        if task_public_contract_anchor:
            ctx["task_public_contract_anchor"] = task_public_contract_anchor
            if self._should_compact_architecture_context(task, task_public_contract_anchor):
                compact_architecture_context = self._compact_architecture_context(task, task_public_contract_anchor)
        for prev_task in project.tasks:
            if prev_task.id not in visible_task_ids:
                continue
            visible_output = self._task_context_output(prev_task)
            if prev_task.status == TaskStatus.DONE.value and visible_output:
                ctx[prev_task.id] = visible_output
                ctx["completed_tasks"][prev_task.id] = visible_output
                if budget_decomposition_plan_task_id == prev_task.id:
                    ctx["budget_decomposition_brief"] = visible_output
                if self._is_budget_decomposition_planner(prev_task):
                    continue
                semantic_key = semantic_output_key(prev_task.assigned_to, prev_task.title)
                if semantic_key:
                    semantic_output = visible_output
                    if semantic_key == "architecture" and compact_architecture_context:
                        semantic_output = compact_architecture_context
                    ctx[semantic_key] = semantic_output
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "code_engineer":
                    ctx.update(self._code_artifact_context(prev_task, project))
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "dependency_manager":
                    ctx.update(self._dependency_artifact_context(prev_task, ctx))
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "qa_tester":
                    ctx.update(self._test_artifact_context(prev_task, ctx))
        if repair_context:
            ctx["repair_context"] = self._agent_visible_repair_context(repair_context, execution_agent_name)
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
            helper_surface_symbols = self._normalized_helper_surface_symbols(
                repair_context.get("helper_surface_symbols") or helper_surface_usages
            )
            existing_tests = repair_context.get("existing_tests")
            failed_artifact_content = repair_context.get("failed_artifact_content")
            failed_output = repair_context.get("failed_output")
            repair_content = failed_artifact_content if isinstance(failed_artifact_content, str) and failed_artifact_content.strip() else failed_output
            normalized_execution_agent = AgentRegistry.normalize_key(execution_agent_name)
            if normalized_execution_agent == "code_engineer" and isinstance(repair_content, str) and repair_content.strip():
                ctx["existing_code"] = repair_content
            if normalized_execution_agent == "code_engineer" and isinstance(existing_tests, str) and existing_tests.strip():
                ctx["existing_tests"] = existing_tests
            if normalized_execution_agent == "qa_tester":
                if (
                    isinstance(repair_content, str)
                    and repair_content.strip()
                    and self._qa_repair_should_reuse_failed_test_artifact(
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
        return cast(Dict[str, Any], redact_sensitive_data(ctx))

    def _task_dependency_closure_ids(self, task: Task, project: ProjectState) -> set[str]:
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

    @staticmethod
    def _direct_dependency_ids(task: Task) -> set[str]:
        direct_dependency_ids = set(task.dependencies)
        if task.repair_origin_task_id:
            direct_dependency_ids.add(task.repair_origin_task_id)
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        budget_decomposition_plan_task_id = repair_context.get("budget_decomposition_plan_task_id")
        if isinstance(budget_decomposition_plan_task_id, str) and budget_decomposition_plan_task_id.strip():
            direct_dependency_ids.add(budget_decomposition_plan_task_id)
        return direct_dependency_ids

    def _build_agent_view(self, task: Task, project: ProjectState, snapshot: ProjectSnapshot) -> AgentView:
        visible_task_ids = self._task_dependency_closure_ids(task, project)
        direct_dependency_ids = self._direct_dependency_ids(task)
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
            task_results=self._agent_view_task_results(snapshot.task_results, visible_task_ids),
            decisions=self._agent_view_decisions(snapshot.decisions),
            artifacts=self._agent_view_artifacts(snapshot.artifacts, visible_task_ids, direct_dependency_ids),
        )

    @staticmethod
    def _agent_view_task_results(
        task_results: Dict[str, TaskResult],
        visible_task_ids: set[str],
    ) -> Dict[str, AgentViewTaskResult]:
        filtered_results: Dict[str, AgentViewTaskResult] = {}
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

    @staticmethod
    def _agent_view_decisions(decisions: list[Any]) -> list[AgentViewDecisionRecord]:
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

    @staticmethod
    def _agent_view_artifacts(
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

    def _build_repair_instruction(self, task: Task, failure_category: str) -> str:
        return build_repair_instruction(
            task.id,
            failure_category,
            last_error=task.last_error if isinstance(task.last_error, str) else "",
            failed_code=self._failed_artifact_content(task, ArtifactType.CODE),
            validation=self._validation_payload(task),
            dataclass_default_order_repair_examples=self._dataclass_default_order_repair_examples,
            missing_import_nameerror_details=self._missing_import_nameerror_details,
            plain_class_field_default_factory_details=self._plain_class_field_default_factory_details,
            test_validation_has_only_warnings=self._test_validation_has_only_warnings,
        )

    def _repair_owner_for_category(self, task: Task, failure_category: str) -> str:
        return repair_owner_for_category(task.assigned_to, failure_category)

    def _validation_payload(self, task: Task) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        metadata = task.output_payload.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        validation = metadata.get("validation")
        return validation if isinstance(validation, dict) else {}

    def _failed_artifact_content(self, task: Task, artifact_type: Optional[ArtifactType] = None) -> str:
        return failed_artifact_content(task.output, task.output_payload, artifact_type)

    def _task_context_output(self, task: Task) -> str:
        if isinstance(task.output, str) and task.output.strip():
            return task.output
        if isinstance(task.output_payload, dict):
            raw_content = task.output_payload.get("raw_content")
            if isinstance(raw_content, str) and raw_content.strip():
                return raw_content
        return task.output or ""

    def _completion_diagnostics_from_output(
        self,
        output: AgentOutput,
        *,
        raw_content: str = "",
        syntax_ok: bool,
        syntax_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        provider_call = output.metadata.get("provider_call") if isinstance(output.metadata, dict) else None
        return self._completion_diagnostics_from_provider_call(
            provider_call,
            raw_content=raw_content,
            syntax_ok=syntax_ok,
            syntax_error=syntax_error,
        )

    def _completion_diagnostics_from_provider_call(
        self,
        provider_call: Any,
        *,
        raw_content: str = "",
        syntax_ok: bool,
        syntax_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        return completion_diagnostics_from_provider_call(
            provider_call,
            raw_content=raw_content,
            syntax_ok=syntax_ok,
            syntax_error=syntax_error,
        )

    def _looks_structurally_truncated(self, raw_content: str, syntax_error: Optional[str]) -> bool:
        return looks_structurally_truncated(raw_content, syntax_error)

    def _completion_hit_limit(self, completion_diagnostics: Dict[str, Any]) -> bool:
        return completion_hit_limit(completion_diagnostics)

    def _completion_validation_issue(self, completion_diagnostics: Dict[str, Any]) -> str:
        return completion_validation_issue(completion_diagnostics)

    def _completion_diagnostics_summary(self, completion_diagnostics: Dict[str, Any]) -> str:
        return completion_diagnostics_summary(completion_diagnostics)

    def _pytest_failure_details(self, test_execution: Optional[Dict[str, Any]], limit: int = 3) -> list[str]:
        return pytest_failure_details(test_execution, limit=limit)

    def _pytest_failure_origin(
        self,
        test_execution: Optional[Dict[str, Any]],
        module_filename: Optional[str],
        test_filename: Optional[str],
    ) -> str:
        return pytest_failure_origin(test_execution, module_filename, test_filename)

    def _pytest_failure_is_semantic_assertion_mismatch(
        self,
        test_execution: Optional[Dict[str, Any]],
    ) -> bool:
        return pytest_failure_is_semantic_assertion_mismatch(test_execution)

    def _pytest_contract_overreach_signals(
        self,
        test_execution: Optional[Dict[str, Any]],
    ) -> list[str]:
        return pytest_contract_overreach_signals(test_execution)

    def _test_validation_has_static_issues(self, validation: Dict[str, Any]) -> bool:
        return validation_has_static_issues(validation)

    def _test_validation_has_blocking_issues(self, validation: Dict[str, Any]) -> bool:
        """Return *True* only when the test has issues that prevent execution.

        Unlike ``_test_validation_has_static_issues`` (which flags any issue),
        this method ignores WARNING-level findings so the pytest arbiter can
        make the final accept/reject decision.
        """
        return validation_has_blocking_issues(validation)

    def _test_validation_has_only_warnings(self, validation: Dict[str, Any]) -> bool:
        """Return *True* when the test has static findings but all are WARNING-level."""
        return validation_has_only_warnings(validation)

    def _build_repair_validation_summary(self, task: Task, failure_category: str) -> str:
        validation = self._validation_payload(task)
        fallback_message = task.last_error or task.output or ""
        if failure_category == FailureCategory.CODE_VALIDATION.value:
            code_analysis = validation.get("code_analysis")
            if isinstance(code_analysis, dict):
                completion_diagnostics = validation.get("completion_diagnostics")
                import_validation = validation.get("import_validation")
                task_public_contract_preflight = validation.get("task_public_contract_preflight")
                return build_code_validation_summary(
                    code_analysis,
                    fallback_message,
                    completion_diagnostics if isinstance(completion_diagnostics, dict) else None,
                    import_validation if isinstance(import_validation, dict) else None,
                    task_public_contract_preflight if isinstance(task_public_contract_preflight, dict) else None,
                )
        if failure_category == FailureCategory.TEST_VALIDATION.value:
            test_analysis = validation.get("test_analysis")
            test_execution = validation.get("test_execution")
            if isinstance(test_analysis, dict):
                completion_diagnostics = validation.get("completion_diagnostics")
                return build_test_validation_summary(
                    test_analysis,
                    test_execution if isinstance(test_execution, dict) else None,
                    completion_diagnostics if isinstance(completion_diagnostics, dict) else None,
                )
        if failure_category == FailureCategory.DEPENDENCY_VALIDATION.value:
            dependency_analysis = validation.get("dependency_analysis")
            if isinstance(dependency_analysis, dict):
                return build_dependency_validation_summary(dependency_analysis)
        return fallback_message

    def _test_failure_requires_code_repair(self, task: Task) -> bool:
        return failed_test_requires_code_repair(
            task,
            self._validation_payload(task),
            pytest_failure_origin=self._pytest_failure_origin,
            pytest_contract_overreach_signals=self._pytest_contract_overreach_signals,
            test_validation_has_blocking_issues=self._test_validation_has_blocking_issues,
            pytest_failure_is_semantic_assertion_mismatch=self._pytest_failure_is_semantic_assertion_mismatch,
        )

    def _upstream_code_task_for_test_failure(self, project: ProjectState, task: Task) -> Optional[Task]:
        return upstream_code_task_for_test_failure(
            project,
            task,
            imported_code_task_for_failed_test=self._imported_code_task_for_failed_test,
        )

    @staticmethod
    def _python_import_roots(raw_content: object) -> set[str]:
        return python_import_roots(raw_content)

    def _imported_code_task_for_failed_test(self, project: ProjectState, task: Task) -> Optional[Task]:
        return imported_code_task_for_failed_test(
            project,
            task,
            failed_artifact_content=self._failed_artifact_content,
            python_import_roots=self._python_import_roots,
            default_module_name_for_task=self._default_module_name_for_task,
        )

    def _build_code_repair_context_from_test_failure(
        self,
        code_task: Task,
        test_task: Task,
        cycle: Dict[str, Any],
    ) -> Dict[str, Any]:
        return build_code_repair_context_from_test_failure(
            code_task,
            test_task,
            cycle,
            failed_artifact_content=self._failed_artifact_content,
            build_repair_validation_summary=self._build_repair_validation_summary,
            build_code_repair_instruction_from_test_failure=self._build_code_repair_instruction_from_test_failure,
            merge_prior_repair_context=self._merge_prior_repair_context,
        )

    def _build_code_repair_instruction_from_test_failure(
        self,
        code_task: Task,
        validation_summary: str,
        existing_tests: object = "",
    ) -> str:
        return build_code_repair_instruction_from_test_failure(
            validation_summary,
            self._failed_artifact_content(code_task, ArtifactType.CODE),
            duplicate_constructor_argument_details=self._duplicate_constructor_argument_details,
            duplicate_constructor_argument_call_hint=self._duplicate_constructor_argument_call_hint,
            duplicate_constructor_explicit_rewrite_hint=self._duplicate_constructor_explicit_rewrite_hint,
            plain_class_field_default_factory_details=self._plain_class_field_default_factory_details,
            missing_object_attribute_details=self._missing_object_attribute_details,
            suggest_declared_attribute_replacement=self._suggest_declared_attribute_replacement,
            render_name_list=self._render_name_list,
            nested_payload_wrapper_field_validation_details=self._nested_payload_wrapper_field_validation_details,
            invalid_outcome_missing_audit_trail_details=self._invalid_outcome_missing_audit_trail_details,
            internal_constructor_strictness_details=self._internal_constructor_strictness_details,
            existing_tests=existing_tests,
        )

    def _is_budget_decomposition_planner(self, task: Task) -> bool:
        return is_budget_decomposition_planner(task)

    @staticmethod
    def _summary_limit_exceeded(validation_summary: object, label: str) -> bool:
        return summary_limit_exceeded(validation_summary, label)

    def _repair_requires_budget_decomposition(self, repair_context: Dict[str, Any]) -> bool:
        return repair_requires_budget_decomposition(repair_context)

    def _build_budget_decomposition_instruction(self, failure_category: str) -> str:
        return build_budget_decomposition_instruction(failure_category)

    def _build_budget_decomposition_task_context(
        self,
        task: Task,
        repair_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        return build_budget_decomposition_task_context(
            task,
            repair_context,
            self._execution_agent_name(task),
        )

    def _ensure_budget_decomposition_task(
        self,
        project: ProjectState,
        task: Task,
        repair_context: Dict[str, Any],
    ) -> Optional[Task]:
        return ensure_budget_decomposition_task(
            project,
            task,
            repair_context,
            requires_budget_decomposition=self._repair_requires_budget_decomposition,
            build_budget_decomposition_task_context=self._build_budget_decomposition_task_context,
        )

    def _active_repair_cycle(self, project: ProjectState) -> Optional[Dict[str, Any]]:
        return active_repair_cycle(project)

    def _build_repair_context(self, task: Task, cycle: Dict[str, Any]) -> Dict[str, Any]:
        return build_repair_context(
            task,
            cycle,
            repair_owner_for_category=self._repair_owner_for_category,
            build_repair_instruction=self._build_repair_instruction,
            build_repair_validation_summary=self._build_repair_validation_summary,
            failed_artifact_content_for_category=self._failed_artifact_content_for_category,
            test_repair_helper_surface_usages=self._test_repair_helper_surface_usages,
            normalized_helper_surface_symbols=self._normalized_helper_surface_symbols,
            merge_prior_repair_context=self._merge_prior_repair_context,
        )

    def _merge_prior_repair_context(self, task: Task, repair_context: Dict[str, Any]) -> None:
        merge_prior_repair_context(task, repair_context)

    def _test_repair_helper_surface_usages(self, task: Task, failure_category: str) -> list[str]:
        return helper_surface_usages_for_test_repair(self._validation_payload(task), failure_category)

    def _normalized_helper_surface_symbols(self, raw_values: object) -> list[str]:
        return normalized_helper_surface_symbols(raw_values)

    @staticmethod
    def _validation_summary_symbols(validation_summary: str, label: str) -> list[str]:
        return validation_summary_symbols(validation_summary, label)

    @staticmethod
    def _module_defined_symbol_names(implementation_code: object) -> list[str]:
        return module_defined_symbol_names(implementation_code)

    @staticmethod
    def _is_helper_alias_like_name(name: str) -> bool:
        return is_helper_alias_like_name(name)

    def _validation_summary_helper_alias_names(
        self,
        validation_summary: object,
        implementation_code: object = "",
    ) -> list[str]:
        return validation_summary_helper_alias_names(
            validation_summary,
            implementation_code,
        )

    @staticmethod
    def _first_non_import_line_with_name(content: object, symbol_name: str) -> str:
        return first_non_import_line_with_name(content, symbol_name)

    def _missing_import_nameerror_details(
        self,
        validation_summary: object,
        failed_artifact_content: object = "",
    ) -> tuple[str, str] | None:
        return missing_import_nameerror_details(validation_summary, failed_artifact_content)

    @staticmethod
    def _content_has_matching_datetime_import(content: object) -> bool:
        return content_has_matching_datetime_import(content)

    @staticmethod
    def _content_has_bare_datetime_reference(content: object) -> bool:
        return content_has_bare_datetime_reference(content)

    def _validation_summary_has_missing_datetime_import_issue(
        self,
        validation_summary: object,
        failed_artifact_content: object = "",
    ) -> bool:
        return validation_summary_has_missing_datetime_import_issue(
            validation_summary,
            failed_artifact_content,
        )

    @staticmethod
    def _implementation_prefers_direct_datetime_import(implementation_code: object) -> bool:
        return implementation_prefers_direct_datetime_import(implementation_code)

    def _implementation_required_evidence_items(self, implementation_code: object) -> list[str]:
        return implementation_required_evidence_items(implementation_code)

    def _content_has_incomplete_required_evidence_payload(
        self,
        content: object,
        implementation_code: object,
    ) -> bool:
        return content_has_incomplete_required_evidence_payload(
            content,
            implementation_code,
        )

    def _validation_summary_has_required_evidence_runtime_issue(
        self,
        validation_summary: object,
        failed_artifact_content: object = "",
        implementation_code: object = "",
    ) -> bool:
        return validation_summary_has_required_evidence_runtime_issue(
            validation_summary,
            failed_artifact_content,
            implementation_code,
        )

    def _qa_repair_should_reuse_failed_test_artifact(
        self,
        validation_summary: object,
        implementation_code: object = "",
        failed_artifact_content: object = "",
    ) -> bool:
        return qa_repair_should_reuse_failed_test_artifact(
            validation_summary,
            implementation_code,
            failed_artifact_content,
        )

    @staticmethod
    def _has_dataclass_decorator(node: ast.ClassDef) -> bool:
        return has_dataclass_decorator(node)

    def _dataclass_default_order_repair_examples(
        self,
        failed_artifact_content: object,
    ) -> list[str]:
        return dataclass_default_order_repair_examples(failed_artifact_content)

    @staticmethod
    def _render_name_list(names: list[str]) -> str:
        return render_name_list(names)

    @staticmethod
    def _missing_required_constructor_details(
        validation_summary: object,
    ) -> Optional[tuple[str, list[str]]]:
        return missing_required_constructor_details(validation_summary)

    @staticmethod
    def _required_field_list_from_failed_artifact(
        failed_artifact_content: object,
    ) -> list[str]:
        return required_field_list_from_failed_artifact(failed_artifact_content)

    def _nested_payload_wrapper_field_validation_details(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[str, list[str], str]]:
        return nested_payload_wrapper_field_validation_details(
            validation_summary,
            failed_artifact_content,
        )

    def _internal_constructor_strictness_details(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[str, list[str], list[str]]]:
        return internal_constructor_strictness_details(
            validation_summary,
            failed_artifact_content,
        )

    def _plain_class_field_default_factory_details(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[str, str]]:
        return plain_class_field_default_factory_details(
            validation_summary,
            failed_artifact_content,
        )

    @staticmethod
    def _failing_pytest_test_names(validation_summary: object) -> list[str]:
        return failing_pytest_test_names(validation_summary)

    @staticmethod
    def _compare_mentions_invalid_literal(node: ast.Compare) -> bool:
        return compare_mentions_invalid_literal(node)

    @classmethod
    def _test_function_targets_invalid_path(
        cls,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        return test_function_targets_invalid_path(node)

    @staticmethod
    def _attribute_is_field_reference(node: ast.AST, field_name: str) -> bool:
        return attribute_is_field_reference(node, field_name)

    @classmethod
    def _is_len_of_field_reference(cls, node: ast.AST, field_name: str) -> bool:
        return is_len_of_field_reference(node, field_name)

    @classmethod
    def _test_requires_non_empty_result_field(
        cls,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        field_name: str,
    ) -> bool:
        return test_requires_non_empty_result_field(node, field_name)

    @staticmethod
    def _ast_is_empty_literal(node: ast.AST | None) -> bool:
        return ast_is_empty_literal(node)

    @classmethod
    def _class_field_uses_empty_default(
        cls,
        failed_artifact_content: object,
        class_name: str,
        field_name: str,
    ) -> bool:
        return class_field_uses_empty_default(failed_artifact_content, class_name, field_name)

    def _invalid_outcome_audit_return_details(
        self,
        failed_artifact_content: object,
        field_name: str,
    ) -> Optional[tuple[str, bool]]:
        return invalid_outcome_audit_return_details(failed_artifact_content, field_name)

    def _invalid_outcome_missing_audit_trail_details(
        self,
        validation_summary: object,
        existing_tests: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[list[str], str, str, bool]]:
        return invalid_outcome_missing_audit_trail_details(
            validation_summary,
            existing_tests,
            failed_artifact_content,
        )

    @staticmethod
    def _duplicate_constructor_argument_details(
        validation_summary: object,
    ) -> Optional[tuple[str, str]]:
        return duplicate_constructor_argument_details(validation_summary)

    def _duplicate_constructor_argument_call_hint(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[str]:
        return duplicate_constructor_argument_call_hint(
            validation_summary,
            failed_artifact_content,
        )

    def _duplicate_constructor_argument_call_details(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[str, str, str, str, str]]:
        return duplicate_constructor_argument_call_details(
            validation_summary,
            failed_artifact_content,
        )

    def _duplicate_constructor_explicit_rewrite_hint(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[str]:
        return duplicate_constructor_explicit_rewrite_hint(
            validation_summary,
            failed_artifact_content,
        )

    @staticmethod
    def _class_field_annotations_from_failed_artifact(
        failed_artifact_content: object,
        class_name: str,
    ) -> dict[str, str]:
        return class_field_annotations_from_failed_artifact(failed_artifact_content, class_name)

    @staticmethod
    def _default_value_for_annotation(annotation: str) -> str:
        return default_value_for_annotation(annotation)

    @staticmethod
    def _class_field_names_from_failed_artifact(
        failed_artifact_content: object,
        class_name: str,
    ) -> list[str]:
        return class_field_names_from_failed_artifact(failed_artifact_content, class_name)

    def _missing_object_attribute_details(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[str, str, list[str]]]:
        return missing_object_attribute_details(validation_summary, failed_artifact_content)

    @staticmethod
    def _suggest_declared_attribute_replacement(attribute_name: str, class_fields: list[str]) -> Optional[str]:
        return suggest_declared_attribute_replacement(attribute_name, class_fields)

    def _previous_valid_test_surface(
        self, failed_artifact_content: object, imported_module_symbols: list[str]
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        return previous_valid_test_surface(
            failed_artifact_content,
            imported_module_symbols,
        )

    def _has_repair_task_for_cycle(self, project: ProjectState, task_id: str, cycle_number: int) -> bool:
        return has_repair_task_for_cycle(project, task_id, cycle_number)

    def _queue_active_cycle_repair(self, project: ProjectState, task: Task) -> bool:
        return queue_active_cycle_repair(
            project,
            task,
            workflow_resume_policy=self.config.workflow_resume_policy,
            active_repair_cycle=self._active_repair_cycle,
            has_repair_task_for_cycle=self._has_repair_task_for_cycle,
            configure_repair_attempts=self._configure_repair_attempts,
            repair_task_ids_for_cycle=self._repair_task_ids_for_cycle,
            log_event=self._log_event,
        )

    def _failed_artifact_content_for_category(self, task: Task, failure_category: str) -> str:
        return failed_artifact_content_for_category(task.output, task.output_payload, failure_category)

    def _configure_repair_attempts(self, project: ProjectState, failed_task_ids: list[str], cycle: Dict[str, Any]) -> None:
        configure_repair_attempts(
            project,
            failed_task_ids,
            cycle,
            test_failure_requires_code_repair=self._test_failure_requires_code_repair,
            upstream_code_task_for_test_failure=self._upstream_code_task_for_test_failure,
            build_code_repair_context_from_test_failure=self._build_code_repair_context_from_test_failure,
            ensure_budget_decomposition_task=self._ensure_budget_decomposition_task,
            build_repair_context=self._build_repair_context,
        )

    def _repair_task_ids_for_cycle(self, project: ProjectState, failed_task_ids: list[str]) -> list[str]:
        return repair_task_ids_for_cycle(
            project,
            failed_task_ids,
            test_failure_requires_code_repair=self._test_failure_requires_code_repair,
            upstream_code_task_for_test_failure=self._upstream_code_task_for_test_failure,
            ensure_budget_decomposition_task=self._ensure_budget_decomposition_task,
            execution_agent_name=self._execution_agent_name,
        )

    def _failed_task_ids_for_repair(self, project: ProjectState) -> list[str]:
        return failed_task_ids_for_repair(project)

    def _planned_module_context(
        self,
        project: ProjectState,
        visible_task_ids: Optional[set[str]] = None,
        current_task: Optional[Task] = None,
    ) -> Dict[str, Any]:
        module_task = self._context_module_task(project, current_task, visible_task_ids)
        if module_task is not None:
            module_name = self._default_module_name_for_task(module_task)
            if module_name:
                return {
                    "planned_module_name": module_name,
                    "planned_module_filename": f"{module_name}.py",
                }
        return {}

    def _context_module_task(
        self,
        project: ProjectState,
        current_task: Optional[Task],
        visible_task_ids: Optional[set[str]] = None,
    ) -> Optional[Task]:
        if current_task is not None and current_task.repair_origin_task_id:
            origin_task = project.get_task(current_task.repair_origin_task_id)
            if (
                origin_task is not None
                and AgentRegistry.normalize_key(origin_task.assigned_to) == "code_engineer"
                and (visible_task_ids is None or origin_task.id in visible_task_ids)
                and self._default_module_name_for_task(origin_task)
            ):
                return origin_task

        for existing_task in project.tasks:
            if visible_task_ids is not None and existing_task.id not in visible_task_ids:
                continue
            if AgentRegistry.normalize_key(existing_task.assigned_to) != "code_engineer":
                continue
            if existing_task.repair_origin_task_id:
                continue
            if self._default_module_name_for_task(existing_task):
                return existing_task

        if current_task is not None and self._default_module_name_for_task(current_task):
            return current_task

        for existing_task in project.tasks:
            if visible_task_ids is not None and existing_task.id not in visible_task_ids:
                continue
            if AgentRegistry.normalize_key(existing_task.assigned_to) != "code_engineer":
                continue
            if self._default_module_name_for_task(existing_task):
                return existing_task

        return None

    def _default_module_name_for_task(self, task: Task) -> Optional[str]:
        if AgentRegistry.normalize_key(task.assigned_to) != "code_engineer":
            return None
        return f"{task.id}_implementation"

    def _context_code_module_name(self, task: Task, project: Optional[ProjectState] = None) -> Optional[str]:
        if project is None:
            return self._default_module_name_for_task(task)

        current_task = task
        visited_task_ids: set[str] = set()
        while current_task.repair_origin_task_id:
            origin_task = project.get_task(current_task.repair_origin_task_id)
            if (
                origin_task is None
                or origin_task.id in visited_task_ids
                or AgentRegistry.normalize_key(origin_task.assigned_to) != "code_engineer"
            ):
                break
            visited_task_ids.add(origin_task.id)
            current_task = origin_task
        return self._default_module_name_for_task(current_task)

    def _task_public_contract_anchor(self, task_description: str) -> str:
        return task_public_contract_anchor(task_description)

    def _code_artifact_context(
        self,
        task: Task,
        project: Optional[ProjectState] = None,
    ) -> Dict[str, Any]:
        module_name = self._context_code_module_name(task, project)
        if not module_name:
            return {}

        artifact_path = f"artifacts/{module_name}.py"
        code_content = task.output or ""
        task_module_name = self._default_module_name_for_task(task)
        allow_artifact_path_override = task_module_name == module_name

        if isinstance(task.output_payload, dict):
            artifacts = task.output_payload.get("artifacts")
            if isinstance(artifacts, list):
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        continue
                    if artifact.get("artifact_type") != ArtifactType.CODE.value:
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
        code_analysis = self._analyze_python_module(code_content)
        return {
            "code_artifact_path": artifact_path,
            "module_name": path_obj.stem,
            "module_filename": path_obj.name,
            "code_summary": summarize_output(code_content),
            "code_outline": self._build_code_outline(code_content),
            "code_analysis": code_analysis,
            "code_public_api": self._build_code_public_api(code_analysis),
            "code_exact_test_contract": self._build_code_exact_test_contract(code_analysis),
            "code_test_targets": self._build_code_test_targets(code_analysis),
            "code_behavior_contract": self._build_code_behavior_contract(code_content),
            "module_run_command": self._build_module_run_command(path_obj.name, code_analysis),
        }
        return {}

    def _test_artifact_context(self, task: Task, context: Dict[str, Any]) -> Dict[str, Any]:
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
                test_analysis = self._analyze_test_module(task.output or "", module_name, code_analysis)
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

    def _dependency_artifact_context(self, task: Task, context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        artifacts = task.output_payload.get("artifacts")
        if not isinstance(artifacts, list):
            return {}
        raw_code_analysis = context.get("code_analysis")
        code_analysis = cast(Dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_path = artifact.get("path")
            if not isinstance(artifact_path, str) or not artifact_path.strip():
                continue
            path_obj = Path(artifact_path)
            if path_obj.name != "requirements.txt":
                continue
            dependency_analysis = self._analyze_dependency_manifest(task.output or "", code_analysis)
            return {
                "dependency_manifest": task.output or "",
                "dependency_manifest_path": artifact_path,
                "dependency_analysis": dependency_analysis,
                "dependency_validation_summary": build_dependency_validation_summary(dependency_analysis),
            }
        return {}

    def _analyze_dependency_manifest(self, manifest_content: str, code_analysis: Dict[str, Any]) -> Dict[str, Any]:
        return analyze_dependency_manifest(manifest_content, code_analysis)

    def _normalize_package_name(self, package_name: str) -> str:
        return normalize_package_name(package_name)

    def _normalize_import_name(self, module_name: str) -> str:
        return normalize_import_name(module_name)

    def _build_code_outline(self, raw_content: str) -> str:
        return build_code_outline(raw_content)

    def _analyze_python_module(self, raw_content: str) -> Dict[str, Any]:
        analysis: Dict[str, Any] = {
            "syntax_ok": True,
            "syntax_error": None,
            "functions": [],
            "classes": {},
            "imports": [],
            "third_party_imports": [],
            "invalid_dataclass_field_usages": [],
            "module_variables": [],
            "symbols": [],
            "has_main_guard": '__name__ == "__main__"' in raw_content or "__name__ == '__main__'" in raw_content,
        }
        if not raw_content.strip():
            return analysis
        try:
            tree = ast.parse(raw_content)
        except SyntaxError as exc:
            analysis["syntax_ok"] = False
            analysis["syntax_error"] = f"{exc.msg} at line {exc.lineno}"
            return analysis

        functions: list[Dict[str, Any]] = []
        classes: Dict[str, Dict[str, Any]] = {}
        import_roots: set[str] = set()
        invalid_dataclass_field_usages: list[str] = []
        module_variables: set[str] = set()

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                signature = self._call_signature_details(node)
                functions.append({
                    "name": node.name,
                    "params": signature["params"],
                    "param_annotations": signature["param_annotations"],
                    "min_args": signature["min_args"],
                    "max_args": signature["max_args"],
                    "return_annotation": signature["return_annotation"],
                    "signature": f"{node.name}({', '.join(signature['params'])})",
                    "accepts_sequence_input": signature["accepts_sequence_input"],
                    "async": isinstance(node, ast.AsyncFunctionDef),
                })
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in self._bound_target_names(target):
                        if not name.startswith("_"):
                            module_variables.add(name)
                continue
            if isinstance(node, ast.AnnAssign):
                if node.value is not None:
                    for name in self._bound_target_names(node.target):
                        if not name.startswith("_"):
                            module_variables.add(name)
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:  # pragma: no branch
                    root_name = alias.name.split(".", 1)[0]
                    if root_name:  # pragma: no branch
                        import_roots.add(root_name)
                continue
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                module_name = (node.module or "").split(".", 1)[0]
                if module_name:  # pragma: no branch
                    import_roots.add(module_name)
                continue
            if not isinstance(node, ast.ClassDef):
                continue

            field_names: list[str] = []
            dataclass_init_params: list[str] = []
            dataclass_required_params: list[str] = []
            class_attributes: list[str] = []
            init_params: list[str] = []
            constructor_min_args: Optional[int] = None
            constructor_max_args: Optional[int] = None
            methods: list[str] = []
            method_signatures: Dict[str, Dict[str, Any]] = {}
            bases = [ast_name(base) for base in node.bases]
            is_enum = any(base.endswith("Enum") for base in bases)
            is_dataclass = self._has_dataclass_decorator(node)

            for stmt in node.body:  # pragma: no branch
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    field_name = stmt.target.id
                    field_names.append(field_name)
                    if (
                        not is_dataclass
                        and isinstance(stmt.value, ast.Call)
                        and self._call_expression_basename(stmt.value.func) == "field"
                    ):
                        invalid_dataclass_field_usages.append(
                            f"{node.name}.{field_name} uses field(...) on a non-dataclass class"
                        )
                    if is_dataclass:
                        has_default = self._dataclass_field_has_default(stmt.value)
                        if self._dataclass_field_is_init_enabled(stmt.value):
                            dataclass_init_params.append(field_name)
                            if not has_default:
                                dataclass_required_params.append(field_name)
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:  # pragma: no branch
                        if isinstance(target, ast.Name):  # pragma: no branch
                            class_attributes.append(target.id)
                            if (
                                not is_dataclass
                                and isinstance(stmt.value, ast.Call)
                                and self._call_expression_basename(stmt.value.func) == "field"
                            ):
                                invalid_dataclass_field_usages.append(
                                    f"{node.name}.{target.id} uses field(...) on a non-dataclass class"
                                )
                elif isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
                    signature = self._call_signature_details(stmt, skip_first_param=True)
                    init_params = signature["params"]
                    constructor_min_args = signature["min_args"]
                    constructor_max_args = signature["max_args"]
                    class_attributes.extend(self._self_assigned_attributes(stmt))
                elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and not stmt.name.startswith("_"):  # pragma: no branch
                    binding_kind = self._method_binding_kind(stmt)
                    signature = self._call_signature_details(
                        stmt,
                        skip_first_param=binding_kind != "static",
                    )
                    if binding_kind == "static":
                        params = list(signature["params"])
                    elif binding_kind == "class":
                        params = ["cls", *signature["params"]]
                    else:
                        params = ["self", *signature["params"]]
                    methods.append(f"{stmt.name}({', '.join(params)})")
                    method_signatures[stmt.name] = signature

            if init_params:
                constructor_params = init_params
            elif is_dataclass:
                constructor_params = dataclass_init_params
            else:
                constructor_params = []
            if constructor_min_args is None and constructor_max_args is None:
                if is_dataclass:
                    constructor_min_args = len(dataclass_required_params)
                    constructor_max_args = len(dataclass_init_params)
                else:
                    constructor_min_args = 0
                    constructor_max_args = 0
            classes[node.name] = {
                "name": node.name,
                "bases": bases,
                "is_enum": is_enum,
                "fields": field_names,
                "attributes": sorted(set(class_attributes)),
                "constructor_params": constructor_params,
                "constructor_min_args": constructor_min_args if constructor_min_args is not None else len(constructor_params),
                "constructor_max_args": constructor_max_args if constructor_max_args is not None else len(constructor_params),
                "methods": methods,
                "method_signatures": method_signatures,
            }

        analysis["functions"] = functions
        analysis["classes"] = classes
        analysis["imports"] = sorted(import_roots)
        analysis["third_party_imports"] = [
            module_name for module_name in sorted(import_roots) if self._is_probable_third_party_import(module_name)
        ]
        analysis["invalid_dataclass_field_usages"] = sorted(dict.fromkeys(invalid_dataclass_field_usages))
        analysis["module_variables"] = sorted(module_variables)
        analysis["symbols"] = sorted([item["name"] for item in functions] + list(classes.keys()))
        return analysis

    def _dataclass_field_has_default(self, value: Optional[ast.expr]) -> bool:
        return dataclass_field_has_default(value)

    def _dataclass_field_is_init_enabled(self, value: Optional[ast.expr]) -> bool:
        return dataclass_field_is_init_enabled(value)

    def _is_probable_third_party_import(self, module_name: str) -> bool:
        normalized_name = module_name.strip()
        if not normalized_name:
            return False
        if normalized_name == "__future__":
            return False
        if normalized_name in _STDLIB_MODULES:
            return False
        return True

    def _build_code_public_api(self, code_analysis: Dict[str, Any]) -> str:
        if not code_analysis.get("syntax_ok", True):
            return f"Module syntax error: {code_analysis.get('syntax_error') or 'unknown syntax error'}"

        lines: list[str] = []
        functions = code_analysis.get("functions") or []
        classes = code_analysis.get("classes") or {}

        if functions:
            lines.append("Functions:")
            for function in functions:
                lines.append(f"- {function['signature']}")
        else:
            lines.append("Functions:\n- none")

        if classes:
            lines.append("Classes:")
            for class_name in sorted(classes):
                class_info = classes[class_name]
                if class_info.get("is_enum"):
                    members = ", ".join(class_info.get("attributes") or []) or "none"
                    lines.append(f"- {class_name} enum members: {members}")
                    continue
                constructor = ", ".join(class_info.get("constructor_params") or [])
                class_attrs = ", ".join(class_info.get("attributes") or class_info.get("fields") or [])
                methods = ", ".join(class_info.get("methods") or [])
                suffix = f"({constructor})" if constructor else "()"
                if class_attrs:
                    lines.append(f"- {class_name}{suffix}; class attributes/fields: {class_attrs}")
                else:
                    lines.append(f"- {class_name}{suffix}")
                if constructor:
                    lines.append(
                        f"  tests must instantiate with all listed constructor fields explicitly: {constructor}"
                    )
                if methods:
                    lines.append(f"  methods: {methods}")
        else:
            lines.append("Classes:\n- none")

        lines.append(
            f"Entrypoint: {'python ' + 'MODULE_FILE' if code_analysis.get('has_main_guard') else 'no __main__ entrypoint detected'}"
        )
        return "\n".join(lines)

    def _build_code_exact_test_contract(self, code_analysis: Dict[str, Any]) -> str:
        if not code_analysis.get("syntax_ok", True):
            return "Exact test contract unavailable because module syntax is invalid."

        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        functions = code_analysis.get("functions") or []
        classes = code_analysis.get("classes") or {}
        preferred_classes = self._preferred_test_class_names(code_analysis)
        exposed_class_names = self._exposed_test_class_names(code_analysis, preferred_classes)
        allowed_imports = sorted(
            [item["name"] for item in functions if item["name"] not in entrypoint_names]
            + exposed_class_names
        )
        exact_method_refs: list[str] = []
        constructor_refs: list[str] = []

        for class_name in exposed_class_names:
            class_info = classes[class_name]
            constructor_params = class_info.get("constructor_params") or []
            if constructor_params:
                constructor_refs.append(f"{class_name}({', '.join(constructor_params)})")
            for method_name in class_info.get("methods") or []:
                if method_name.startswith("_"):
                    continue
                exact_method_refs.append(f"{class_name}.{method_name}")

        callable_refs = [
            item["signature"]
            for item in functions
            if item["name"] not in entrypoint_names
        ]

        lines = ["Exact test contract:"]
        lines.append(f"- Allowed production imports: {', '.join(allowed_imports or ['none'])}")
        lines.append(f"- Preferred service or workflow facades: {', '.join(preferred_classes or ['none'])}")
        lines.append(f"- Exact public callables: {', '.join(callable_refs or ['none'])}")
        lines.append(f"- Exact public class methods: {', '.join(exact_method_refs or ['none'])}")
        lines.append(f"- Exact constructor fields: {', '.join(constructor_refs or ['none'])}")
        lines.append(
            "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
        )
        return "\n".join(lines)

    def _build_module_run_command(self, module_filename: str, code_analysis: Dict[str, Any]) -> str:
        if code_analysis.get("has_main_guard"):
            return f"python {module_filename}"
        return ""

    def _entrypoint_function_names(self, code_analysis: Dict[str, Any]) -> set[str]:
        function_names = {item["name"] for item in code_analysis.get("functions") or []}
        return {
            name
            for name in function_names
            if name == "main" or name.startswith("cli_") or name.endswith("_cli") or name.endswith("_demo")
        }

    def _entrypoint_class_names(self, code_analysis: Dict[str, Any]) -> set[str]:
        class_names = set((code_analysis.get("classes") or {}).keys())
        return {
            name
            for name in class_names
            if name.lower().endswith("cli") or name.lower().endswith("_cli") or name.lower().endswith("demo")
        }

    def _entrypoint_symbol_names(self, code_analysis: Dict[str, Any]) -> set[str]:
        return self._entrypoint_function_names(code_analysis) | self._entrypoint_class_names(code_analysis)

    def _exposed_test_class_names(
        self,
        code_analysis: Dict[str, Any],
        preferred_classes: Optional[list[str]] = None,
    ) -> list[str]:
        class_map = code_analysis.get("classes") or {}
        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        preferred = preferred_classes or self._preferred_test_class_names(code_analysis)
        helper_classes_to_avoid = set(self._helper_classes_to_avoid(code_analysis, preferred))
        return sorted(
            class_name
            for class_name in class_map.keys()
            if class_name not in entrypoint_names and class_name not in helper_classes_to_avoid
        )

    def _build_code_test_targets(self, code_analysis: Dict[str, Any]) -> str:
        if not code_analysis.get("syntax_ok", True):
            return "Test targets unavailable because module syntax is invalid."

        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        preferred_classes = self._preferred_test_class_names(code_analysis)
        helper_classes_to_avoid = self._helper_classes_to_avoid(code_analysis, preferred_classes)
        batch_capable_functions = [
            item["signature"]
            for item in code_analysis.get("functions") or []
            if item["name"] not in entrypoint_names and item.get("accepts_sequence_input")
        ]
        scalar_functions = [
            item["signature"]
            for item in code_analysis.get("functions") or []
            if item["name"] not in entrypoint_names and not item.get("accepts_sequence_input")
        ]
        testable_functions = [
            item["signature"]
            for item in code_analysis.get("functions") or []
            if item["name"] not in entrypoint_names
        ]
        classes = self._exposed_test_class_names(code_analysis, preferred_classes)
        lines = ["Test targets:"]
        lines.append(f"- Functions to test: {', '.join(testable_functions or ['none'])}")
        lines.append(f"- Batch-capable functions: {', '.join(batch_capable_functions or ['none'])}")
        lines.append(f"- Scalar-only functions: {', '.join(scalar_functions or ['none'])}")
        lines.append(f"- Classes to test: {', '.join(classes or ['none'])}")
        lines.append(f"- Preferred workflow classes: {', '.join(preferred_classes or ['none'])}")
        lines.append(
            f"- Helper classes to avoid in compact workflow tests: {', '.join(helper_classes_to_avoid or ['none'])}"
        )
        lines.append(f"- Entry points to avoid in tests: {', '.join(sorted(entrypoint_names) or ['none'])}")
        return "\n".join(lines)

    def _preferred_test_class_names(self, code_analysis: Dict[str, Any]) -> list[str]:
        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        workflow_method_prefixes = (
            "process_",
            "validate_",
            "intake_",
            "handle_",
            "submit_",
            "batch_",
            "export_",
        )
        preferred: list[str] = []
        for class_name, class_info in sorted((code_analysis.get("classes") or {}).items()):
            if class_name in entrypoint_names:
                continue
            method_names = list((class_info.get("method_signatures") or {}).keys())
            if any(method_name.startswith(workflow_method_prefixes) for method_name in method_names):
                preferred.append(class_name)
        return preferred

    def _constructor_param_matches_class(self, param_name: str, class_name: str) -> bool:
        normalized_param = param_name.strip().lower()
        if not normalized_param:
            return False

        snake_name = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
        candidate_names = {snake_name}
        parts = snake_name.split("_")
        if len(parts) > 2:
            for start in range(1, len(parts) - 1):
                candidate_names.add("_".join(parts[start:]))

        if normalized_param in candidate_names:
            return True

        suffix = snake_name.split("_")[-1]
        return suffix in {"logger", "repository", "service"} and normalized_param == suffix

    def _helper_classes_to_avoid(
        self,
        code_analysis: Dict[str, Any],
        preferred_classes: Optional[list[str]] = None,
    ) -> list[str]:
        preferred = set(preferred_classes or self._preferred_test_class_names(code_analysis))
        if not preferred:
            return []
        class_map = code_analysis.get("classes") or {}
        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        helper_suffixes = ("service", "repository", "logger")
        required_constructor_helpers: set[str] = set()
        for preferred_name in preferred:
            class_info = class_map.get(preferred_name) or {}
            constructor_params = [
                param_name
                for param_name in (class_info.get("constructor_params") or [])
                if isinstance(param_name, str)
            ]
            for helper_name in class_map.keys():
                if helper_name in preferred or helper_name in entrypoint_names:
                    continue
                if not helper_name.lower().endswith(helper_suffixes):
                    continue
                if any(
                    self._constructor_param_matches_class(param_name, helper_name)
                    for param_name in constructor_params
                ):
                    required_constructor_helpers.add(helper_name)
        helper_names: list[str] = []
        for class_name in sorted(class_map.keys()):
            if class_name in entrypoint_names or class_name in preferred or class_name in required_constructor_helpers:
                continue
            if class_name.lower().endswith(helper_suffixes):
                helper_names.append(class_name)
        return helper_names

    def _build_code_behavior_contract(self, raw_content: str) -> str:
        if not raw_content.strip():
            return ""
        try:
            tree = ast.parse(raw_content)
        except SyntaxError:
            return ""

        validation_rules: dict[str, list[str]] = {}
        field_value_rules: dict[str, Dict[str, list[str]]] = {}
        type_constraints: dict[str, Dict[str, list[str]]] = {}
        batch_rules: list[str] = []
        constructor_storage_rules: list[str] = []
        score_derivation_rules: list[str] = []
        sequence_input_rules: list[str] = []
        function_map: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                function_nodes = [stmt for stmt in node.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_nodes = [node]
            else:
                continue

            for function_node in function_nodes:
                function_map[function_node.name] = function_node
                required_fields = self._extract_required_fields(function_node)
                if required_fields:
                    validation_rules[function_node.name] = required_fields

        for function_name, function_node in function_map.items():
            if function_name in validation_rules:
                continue
            propagated_fields = self._extract_indirect_required_fields(function_node, validation_rules)
            if propagated_fields:
                validation_rules[function_name] = propagated_fields

        for function_name, function_node in function_map.items():
            lookup_rules = self._extract_lookup_field_rules(function_node)
            if lookup_rules:
                field_value_rules[function_name] = lookup_rules

        for function_name, function_node in function_map.items():
            constraints = self._extract_type_constraints(function_node)
            if constraints:
                type_constraints[function_name] = constraints

        for function_node in function_map.values():
            batch_rule = self._extract_batch_rule(function_node, validation_rules)
            if batch_rule:
                batch_rules.append(batch_rule)

        for function_node in function_map.values():
            constructor_storage_rule = self._extract_constructor_storage_rule(function_node)
            if constructor_storage_rule:
                constructor_storage_rules.append(constructor_storage_rule)

        for function_node in function_map.values():
            score_derivation_rule = self._extract_score_derivation_rule(function_node, function_map)
            if score_derivation_rule:
                score_derivation_rules.append(score_derivation_rule)

        for function_node in function_map.values():
            sequence_rule = self._extract_sequence_input_rule(function_node)
            if sequence_rule:
                sequence_input_rules.append(sequence_rule)

        literal_examples = self._extract_valid_literal_examples(raw_content)

        class_definition_styles: list[str] = []
        return_type_annotations: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                style = self._extract_class_definition_style(node)
                if style:
                    class_definition_styles.append(style)
                for stmt in node.body:
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        annotation = self._extract_return_type_annotation(node.name, stmt)
                        if annotation:
                            return_type_annotations.append(annotation)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                annotation = self._extract_return_type_annotation(None, node)
                if annotation:
                    return_type_annotations.append(annotation)

        if not (
            validation_rules
            or field_value_rules
            or type_constraints
            or batch_rules
            or constructor_storage_rules
            or score_derivation_rules
            or sequence_input_rules
            or literal_examples
            or class_definition_styles
            or return_type_annotations
        ):
            return ""

        lines = ["Behavior contract:"]
        for function_name in sorted(validation_rules):
            lines.append(
                f"- {function_name} requires fields: {', '.join(validation_rules[function_name])}"
            )
        dict_accessed_keys = self._dict_accessed_keys_from_tree(tree) if type_constraints else {}
        dict_key_examples = self._infer_dict_key_value_examples(tree) if type_constraints else {}
        for function_name in sorted(type_constraints):
            for field_name in sorted(type_constraints[function_name]):
                type_list = ", ".join(type_constraints[function_name][field_name])
                keys_hint = ""
                dict_example = ""
                if "dict" in type_constraints[function_name][field_name]:
                    keys = dict_accessed_keys.get(field_name)
                    if keys:
                        sorted_keys = sorted(keys)
                        keys_hint = f" (keys used: {', '.join(sorted_keys)})"
                        inferred = dict_key_examples.get(field_name, {})
                        example_pairs = ", ".join(
                            f"'{k}': {inferred.get(k, repr('value'))}"
                            for k in sorted_keys
                        )
                        dict_example = (
                            f"- EXAMPLE: {field_name}={{{example_pairs}}} "
                            f"— NEVER pass a plain string for `{field_name}`"
                        )
                lines.append(
                    f"- {function_name} requires parameter `{field_name}` to be of type: {type_list}{keys_hint}"
                )
                if dict_example:
                    lines.append(dict_example)
        for function_name in sorted(field_value_rules):
            for field_name in sorted(field_value_rules[function_name]):
                lines.append(
                    f"- {function_name} expects field `{field_name}` to be one of: {', '.join(field_value_rules[function_name][field_name])}"
                )
        for rule in sorted(dict.fromkeys(constructor_storage_rules)):
            lines.append(f"- {rule}")
        for rule in sorted(dict.fromkeys(score_derivation_rules)):
            lines.append(f"- {rule}")
        for rule in sorted(sequence_input_rules):
            lines.append(f"- {rule}")
        for rule in batch_rules:
            lines.append(f"- {rule}")
        for style in class_definition_styles:
            lines.append(f"- {style}")
        for annotation in return_type_annotations:
            lines.append(f"- {annotation}")
        if literal_examples:
            lines.append("")
            lines.append("Fixture example patterns:")
            for var_name, example_literal in sorted(literal_examples.items()):
                lines.append(f"- {var_name} = {example_literal}")
        return "\n".join(lines)

    @staticmethod
    def _extract_class_definition_style(node: ast.ClassDef) -> str:
        """Return a human-readable description of how the class is defined."""
        return extract_class_definition_style(node)

    @staticmethod
    def _extract_return_type_annotation(class_name: str | None, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Return a description of the return type annotation if present."""
        return extract_return_type_annotation(class_name, node)

    def _extract_constructor_storage_rule(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        return extract_constructor_storage_rule(node)

    def _extract_score_derivation_rule(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    ) -> str:
        return extract_score_derivation_rule(node, function_map)

    def _function_returns_score_value(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return function_returns_score_value(node)

    def _render_score_expression(
        self,
        expression: ast.expr,
        function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    ) -> str:
        return render_score_expression(expression, function_map)

    def _inline_score_helper_expression(
        self,
        expression: ast.expr,
        function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    ) -> ast.expr:
        return inline_score_helper_expression(expression, function_map)

    def _expand_local_name_aliases(
        self,
        expression: ast.expr,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> ast.expr:
        return expand_local_name_aliases(expression, node)

    def _call_expression_basename(self, node: ast.AST) -> str:
        return call_expression_basename(node)

    def _direct_return_expression(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[ast.expr]:
        return direct_return_expression(node)

    def _callable_parameter_names(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        return callable_parameter_names(node)

    def _extract_sequence_input_rule(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        return extract_sequence_input_rule(node)

    def _first_user_parameter(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[ast.arg]:
        return first_user_parameter(node)

    def _annotation_accepts_sequence_input(self, annotation: str) -> bool:
        return annotation_accepts_sequence_input(annotation)

    def _parameter_is_iterated(self, node: ast.FunctionDef | ast.AsyncFunctionDef, parameter_name: str) -> bool:
        return parameter_is_iterated(node, parameter_name)

    def _extract_required_fields(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        return extract_required_fields(node)

    def _comparison_required_field(self, node: ast.Compare) -> str:
        return comparison_required_field(node)

    def _extract_indirect_required_fields(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        validation_rules: Dict[str, list[str]],
    ) -> list[str]:
        return extract_indirect_required_fields(node, validation_rules)

    def _extract_lookup_field_rules(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, list[str]]:
        return extract_lookup_field_rules(node)

    def _field_selector_name(self, node: ast.AST) -> str:
        return field_selector_name(node)

    @staticmethod
    def _infer_dict_key_value_examples(tree: ast.AST) -> Dict[str, Dict[str, str]]:
        return infer_dict_key_value_examples(tree)

    @staticmethod
    def _dict_accessed_keys_from_tree(tree: ast.AST) -> Dict[str, list[str]]:
        return dict_accessed_keys_from_tree(tree)

    def _extract_type_constraints(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> Dict[str, list[str]]:
        """Extract isinstance() type checks from if-guards and raise blocks."""
        return extract_type_constraints(node)

    def _collect_isinstance_calls(self, node: ast.AST, result: list[ast.Call]) -> None:
        collect_isinstance_calls(node, result)

    def _isinstance_subject_name(self, node: ast.AST) -> str:
        return isinstance_subject_name(node)

    def _isinstance_type_names(self, node: ast.AST) -> list[str]:
        return isinstance_type_names(node)

    def _extract_valid_literal_examples(self, raw_content: str) -> Dict[str, str]:
        """Extract sample dict/list literals from top-level constant assignments."""
        return extract_valid_literal_examples(raw_content)

    def _extract_batch_rule(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        validation_rules: Dict[str, list[str]],
    ) -> str:
        return extract_batch_rule(node, validation_rules)

    def _analyze_test_module(
        self,
        raw_content: str,
        module_name: str,
        code_analysis: Dict[str, Any],
        code_behavior_contract: str = "",
    ) -> Dict[str, Any]:
        analysis: Dict[str, Any] = {
            "syntax_ok": True,
            "syntax_error": None,
            "imported_module_symbols": [],
            "missing_function_imports": [],
            "unknown_module_symbols": [],
            "invalid_member_references": [],
            "call_arity_mismatches": [],
            "constructor_arity_mismatches": [],
            "payload_contract_violations": [],
            "non_batch_sequence_calls": [],
            "helper_surface_usages": [],
            "reserved_fixture_names": [],
            "undefined_fixtures": [],
            "undefined_local_names": [],
            "imported_entrypoint_symbols": [],
            "unsafe_entrypoint_calls": [],
            "unsupported_mock_assertions": [],
            "top_level_test_count": 0,
            "fixture_count": 0,
            "assertion_like_count": 0,
            "tests_without_assertions": [],
            "contract_overreach_signals": [],
            "type_mismatches": [],
        }
        if not raw_content.strip():
            return analysis
        try:
            tree = ast.parse(raw_content)
        except SyntaxError as exc:
            analysis["syntax_ok"] = False
            analysis["syntax_error"] = f"{exc.msg} at line {exc.lineno}"
            return analysis

        module_symbols = set(code_analysis.get("symbols") or []) | set(code_analysis.get("module_variables") or [])
        function_names = {item["name"] for item in code_analysis.get("functions") or []}
        function_map = {item["name"]: item for item in code_analysis.get("functions") or []}
        class_map = code_analysis.get("classes") or {}
        helper_classes_to_avoid = set(self._helper_classes_to_avoid(code_analysis))
        module_defined_names = self._collect_module_defined_names(tree)
        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        validation_rules, field_value_rules, batch_rules, sequence_input_functions, type_constraint_rules = self._parse_behavior_contract(
            code_behavior_contract
        )
        analysis["top_level_test_count"] = sum(
            1
            for stmt in tree.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("test_")
        )
        analysis["fixture_count"] = sum(
            1
            for stmt in tree.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_pytest_fixture(stmt)
        )

        imported_symbols: set[str] = set()
        called_names: list[tuple[str, int]] = []
        attribute_refs: list[tuple[str, str, int]] = []
        constructor_calls: list[tuple[str, int, int]] = []
        call_arity_mismatches: list[str] = []
        defined_fixtures: set[str] = set()
        reserved_fixture_names: list[str] = []
        referenced_fixtures: list[tuple[str, int]] = []
        undefined_local_names: set[str] = set()
        unsafe_entrypoint_calls: list[str] = []
        assertion_like_count = 0
        tests_without_assertions: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == module_name:
                for alias in node.names:
                    imported_symbols.add(alias.asname or alias.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if is_pytest_fixture(node):
                    defined_fixtures.add(node.name)
                    undefined_local_names.update(
                        self._collect_undefined_local_names(node, module_defined_names)
                    )
                    if node.name in _RESERVED_FIXTURE_NAMES:
                        reserved_fixture_names.append(f"{node.name} (line {node.lineno})")
                if node.name.startswith("test_"):
                    test_assertion_like_count = self._count_test_assertion_like_checks(node)
                    assertion_like_count += test_assertion_like_count
                    if test_assertion_like_count == 0:
                        tests_without_assertions.append(f"{node.name} (line {node.lineno})")
                    parametrized_arguments = self._collect_parametrized_argument_names(node)
                    for arg_name in self._function_argument_names(node):
                        if arg_name not in parametrized_arguments:
                            referenced_fixtures.append((arg_name, node.lineno))
                    undefined_local_names.update(
                        self._collect_undefined_local_names(node, module_defined_names)
                    )
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.append((node.func.id, node.lineno))
                    if node.func.id in class_map:
                        constructor_calls.append((node.func.id, len(node.args) + len(node.keywords), node.lineno))
                    if node.func.id in imported_symbols and node.func.id in entrypoint_names:
                        unsafe_entrypoint_calls.append(f"{node.func.id}() (line {node.lineno})")
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):  # pragma: no branch
                    attribute_refs.append((node.func.value.id, node.func.attr, node.lineno))
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                attribute_refs.append((node.value.id, node.attr, node.lineno))

        missing_imports = sorted(
            {
                f"{name} (line {lineno})"
                for name, lineno in called_names
                if name in function_names and name not in imported_symbols
            }
        )
        unknown_symbols = sorted(symbol for symbol in imported_symbols if symbol not in module_symbols)

        invalid_member_refs: list[str] = []
        unsupported_mock_assertions: list[str] = []
        contract_overreach_signals: list[str] = []
        for owner, member, lineno in attribute_refs:
            if owner not in imported_symbols or owner not in class_map:
                continue
            class_info = class_map[owner]
            allowed = set(class_info.get("attributes") or [])
            if not class_info.get("is_enum"):
                allowed.update(class_info.get("fields") or [])
            allowed.update((class_info.get("method_signatures") or {}).keys())
            if member not in allowed:
                invalid_member_refs.append(f"{owner}.{member} (line {lineno})")

        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            bindings = self._collect_local_bindings(node)
            local_types = self._collect_test_local_types(node, class_map, function_map)
            typed_invalid_refs, typed_arity_mismatches = self._analyze_typed_test_member_usage(
                node,
                local_types,
                class_map,
                function_map,
            )
            invalid_member_refs.extend(typed_invalid_refs)
            call_arity_mismatches.extend(typed_arity_mismatches)
            unsupported_mock_assertions.extend(
                self._find_unsupported_mock_assertions(node, local_types, class_map)
            )
            contract_overreach_signals.extend(
                self._find_contract_overreach_signals(
                    node,
                    bindings,
                    code_behavior_contract if isinstance(code_behavior_contract, str) else "",
                )
            )

        arity_mismatches: list[str] = []
        for class_name, actual_count, lineno in constructor_calls:
            class_info = class_map.get(class_name, {})
            expected_params = class_info.get("constructor_params") or []
            min_expected = class_info.get("constructor_min_args")
            max_expected = class_info.get("constructor_max_args")
            if not isinstance(min_expected, int) or not isinstance(max_expected, int):
                min_expected = len(expected_params)
                max_expected = len(expected_params)
            if min_expected <= actual_count <= max_expected:
                continue
            if min_expected == max_expected:
                arity_mismatches.append(
                    f"{class_name} expects {max_expected} args but test uses {actual_count} at line {lineno}"
                )
                continue
            arity_mismatches.append(
                f"{class_name} expects {min_expected}-{max_expected} args but test uses {actual_count} at line {lineno}"
            )

        undefined_fixtures = sorted(
            {
                f"{fixture_name} (line {lineno})"
                for fixture_name, lineno in referenced_fixtures
                if fixture_name not in defined_fixtures and fixture_name not in _PYTEST_BUILTIN_FIXTURES
            }
        )
        imported_entrypoint_symbols = sorted(symbol for symbol in imported_symbols if symbol in entrypoint_names)
        helper_surface_usages = sorted(
            {symbol for symbol in imported_symbols if symbol in helper_classes_to_avoid}
            | {
                f"{name} (line {lineno})"
                for name, lineno in called_names
                if name in helper_classes_to_avoid
            }
        )
        payload_contract_violations, non_batch_sequence_calls = self._analyze_test_behavior_contracts(
            tree,
            validation_rules,
            field_value_rules,
            batch_rules,
            sequence_input_functions,
            function_names,
            class_map,
        )
        type_mismatches = self._analyze_test_type_mismatches(
            tree,
            type_constraint_rules,
            class_map,
        )

        analysis["imported_module_symbols"] = sorted(imported_symbols)
        analysis["missing_function_imports"] = missing_imports
        analysis["unknown_module_symbols"] = unknown_symbols
        analysis["invalid_member_references"] = sorted(set(invalid_member_refs))
        analysis["call_arity_mismatches"] = sorted(set(call_arity_mismatches))
        analysis["constructor_arity_mismatches"] = sorted(set(arity_mismatches))
        analysis["payload_contract_violations"] = payload_contract_violations
        analysis["non_batch_sequence_calls"] = non_batch_sequence_calls
        analysis["helper_surface_usages"] = helper_surface_usages
        analysis["reserved_fixture_names"] = sorted(set(reserved_fixture_names))
        analysis["undefined_fixtures"] = undefined_fixtures
        analysis["undefined_local_names"] = sorted(undefined_local_names)
        analysis["imported_entrypoint_symbols"] = imported_entrypoint_symbols
        analysis["unsafe_entrypoint_calls"] = sorted(set(unsafe_entrypoint_calls))
        analysis["unsupported_mock_assertions"] = sorted(set(unsupported_mock_assertions))
        analysis["assertion_like_count"] = assertion_like_count
        analysis["tests_without_assertions"] = sorted(set(tests_without_assertions))
        analysis["contract_overreach_signals"] = sorted(set(contract_overreach_signals))
        analysis["type_mismatches"] = type_mismatches
        return analysis

    def _parse_behavior_contract(
        self,
        contract: str,
    ) -> tuple[Dict[str, list[str]], Dict[str, Dict[str, list[str]]], Dict[str, Dict[str, Any]], set[str], Dict[str, Dict[str, list[str]]]]:
        validation_rules: Dict[str, list[str]] = {}
        field_value_rules: Dict[str, Dict[str, list[str]]] = {}
        type_constraint_rules: Dict[str, Dict[str, list[str]]] = {}
        batch_rules: Dict[str, Dict[str, Any]] = {}
        sequence_input_functions: set[str] = set()
        if not contract.strip():
            return validation_rules, field_value_rules, batch_rules, sequence_input_functions, type_constraint_rules

        for raw_line in contract.splitlines():
            line = raw_line.strip()
            if not line.startswith("- "):
                continue
            validation_match = re.match(r"-\s+(\w+) requires fields: (.+)$", line)
            if validation_match:
                function_name = validation_match.group(1)
                fields = [field.strip() for field in validation_match.group(2).split(",") if field.strip()]
                if fields:
                    validation_rules[function_name] = fields
                continue

            type_constraint_match = re.match(r"-\s+(\w+) requires parameter `([^`]+)` to be of type: (.+)$", line)
            if type_constraint_match:
                function_name = type_constraint_match.group(1)
                field_name = type_constraint_match.group(2)
                raw_types = re.sub(r"\s*\(keys used:[^)]*\)", "", type_constraint_match.group(3))
                types = [t.strip() for t in raw_types.split(",") if t.strip()]
                if types:
                    type_constraint_rules.setdefault(function_name, {})[field_name] = types
                continue

            field_value_match = re.match(r"-\s+(\w+) expects field `([^`]+)` to be one of: (.+)$", line)
            if field_value_match:
                function_name = field_value_match.group(1)
                field_name = field_value_match.group(2)
                values = [value.strip() for value in field_value_match.group(3).split(",") if value.strip()]
                if values:
                    field_value_rules.setdefault(function_name, {})[field_name] = values
                continue

            sequence_input_match = re.match(r"-\s+(\w+) accepts sequence inputs via parameter `([^`]+)`$", line)
            if sequence_input_match:
                sequence_input_functions.add(sequence_input_match.group(1))
                continue

            nested_match = re.match(
                r"-\s+(\w+) expects each batch item to include key `([^`]+)` and nested `([^`]+)` fields: (.+)$",
                line,
            )
            if nested_match:
                batch_rules[nested_match.group(1)] = {
                    "request_key": nested_match.group(2),
                    "wrapper_key": nested_match.group(3),
                    "fields": [field.strip() for field in nested_match.group(4).split(",") if field.strip()],
                }
                continue

            direct_match = re.match(r"-\s+(\w+) expects each batch item to include: (.+)$", line)
            if direct_match:
                batch_rules[direct_match.group(1)] = {
                    "request_key": None,
                    "wrapper_key": None,
                    "fields": [field.strip() for field in direct_match.group(2).split(",") if field.strip()],
                }
                continue

            wrapper_match = re.match(r"-\s+(\w+) expects nested `([^`]+)` fields: (.+)$", line)
            if wrapper_match:  # pragma: no branch
                batch_rules[wrapper_match.group(1)] = {
                    "request_key": None,
                    "wrapper_key": wrapper_match.group(2),
                    "fields": [field.strip() for field in wrapper_match.group(3).split(",") if field.strip()],
                }

        return validation_rules, field_value_rules, batch_rules, sequence_input_functions, type_constraint_rules

    def _analyze_test_behavior_contracts(
        self,
        tree: ast.AST,
        validation_rules: Dict[str, list[str]],
        field_value_rules: Dict[str, Dict[str, list[str]]],
        batch_rules: Dict[str, Dict[str, Any]],
        sequence_input_functions: set[str],
        function_names: set[str],
        class_map: Dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        payload_violations: set[str] = set()
        non_batch_calls: set[str] = set()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue

            bindings = self._collect_local_bindings(node)
            parent_map = self._parent_map(node)
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                called_name = callable_name(child)
                if not called_name:
                    continue
                negative_expectation = self._call_has_negative_expectation(child, parent_map)
                invalid_outcome_expectation = negative_expectation or self._call_expects_invalid_outcome(
                    node,
                    child,
                    parent_map,
                )

                if called_name in validation_rules:
                    payload_arg = self._payload_argument_for_validation(child, called_name)
                    payload_node = self._resolve_bound_value(payload_arg, bindings)
                    payload_keys = self._extract_literal_dict_keys(payload_node, bindings, class_map)
                    if payload_keys is not None:
                        missing_fields = [field for field in validation_rules[called_name] if field not in payload_keys]
                        if missing_fields and not invalid_outcome_expectation:  # pragma: no branch
                            payload_violations.add(
                                f"{called_name} payload missing required fields: {', '.join(missing_fields)} at line {child.lineno}"
                            )

                if called_name in field_value_rules:
                    payload_arg = self._payload_argument_for_validation(child, called_name)
                    payload_node = self._resolve_bound_value(payload_arg, bindings)
                    for field_name, allowed_values in field_value_rules[called_name].items():
                        observed_values = self._extract_literal_field_values(payload_node, bindings, field_name, class_map)
                        invalid_values = [value for value in observed_values if value not in allowed_values]
                        if invalid_values and not invalid_outcome_expectation:
                            payload_violations.add(
                                f"{called_name} field `{field_name}` uses unsupported values: {', '.join(invalid_values)} at line {child.lineno}"
                            )

                if called_name in batch_rules:
                    batch_allows_partial_invalid = self._batch_call_allows_partial_invalid_items(
                        node,
                        child,
                        bindings,
                        parent_map,
                    )
                    batch_violations = [] if negative_expectation or batch_allows_partial_invalid else self._validate_batch_call(
                        child,
                        bindings,
                        called_name,
                        batch_rules[called_name],
                    )
                    payload_violations.update(batch_violations)
                    continue

                if called_name in sequence_input_functions:
                    continue

                if called_name in function_names and "batch" not in called_name:
                    sequence_arg = first_call_argument(child)
                    sequence_node = self._resolve_bound_value(sequence_arg, bindings)
                    if isinstance(sequence_node, ast.List):
                        non_batch_calls.add(
                            f"{called_name} does not accept batch/list inputs at line {child.lineno}"
                        )

        return sorted(payload_violations), sorted(non_batch_calls)

    def _auto_fix_test_type_mismatches(
        self,
        test_content: str,
        code_content: str,
    ) -> str:
        """Auto-fix str→dict type mismatches in generated test code.

        Scans the implementation code to discover which parameters are used
        as dicts (via subscript/key-access patterns).  Then replaces any
        ``param='...'`` string literal in the test with a dict literal
        containing the discovered keys.  This catches mismatches in ALL
        call sites (constructors, handle_request, validate_request, etc.)
        rather than only the specific lines reported by the type checker.

        Lines inside test functions that intentionally test validation
        failure (name contains ``validation_failure`` / ``invalid``, or
        the body asserts ``is False``) are left untouched so that the
        deliberately-wrong type continues to trigger a validation error.
        """
        try:
            impl_tree = ast.parse(code_content)
        except SyntaxError:
            return test_content
        dict_keys = self._dict_accessed_keys_from_tree(impl_tree)
        if not dict_keys:
            return test_content

        # Determine line ranges belonging to negative-expectation tests
        # so the auto-fix does not "correct" intentionally-wrong types.
        skip_lines: set[int] = set()
        try:
            test_tree = ast.parse(test_content)
            for node in ast.walk(test_tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not node.name.startswith("test_"):
                    continue
                name_lower = node.name.lower()
                is_negative = "validation_failure" in name_lower or "invalid" in name_lower
                if not is_negative:
                    # Check body for `is_valid is False` / `is False` patterns
                    func_src = ast.get_source_segment(test_content, node) or ""
                    if "is False" in func_src or "is_valid is False" in func_src:
                        is_negative = True
                if is_negative:
                    start = node.lineno - 1  # 0-based
                    end = node.end_lineno or node.lineno
                    for ln in range(start, end):
                        skip_lines.add(ln)
        except SyntaxError:
            pass

        # Build per-function variable maps: if a test function already
        # assigns ``param = {dict_literal}``, reuse the variable instead
        # of injecting a generic ``{'key': 'value'}`` replacement.
        func_var_dict_ranges: list[tuple[int, int, set[str]]] = []
        try:
            _tree = ast.parse(test_content)
            for node in ast.walk(_tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not node.name.startswith("test_"):
                    continue
                dict_assigned_vars: set[str] = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Assign) and len(child.targets) == 1:
                        target = child.targets[0]
                        if isinstance(target, ast.Name) and isinstance(child.value, ast.Dict):
                            dict_assigned_vars.add(target.id)
                start = node.lineno - 1
                end = node.end_lineno or node.lineno
                func_var_dict_ranges.append((start, end, dict_assigned_vars))
        except SyntaxError:
            pass

        lines = test_content.split("\n")
        for param_name, keys in dict_keys.items():
            if not keys:
                continue
            dict_literal = (
                "{"
                + ", ".join(f"'{k}': 'value'" for k in sorted(keys))
                + "}"
            )
            str_pattern = re.compile(
                rf"\b({re.escape(param_name)})\s*=\s*(?:'[^']*'|\"[^\"]*\")"
            )
            for i, line in enumerate(lines):
                if i in skip_lines:
                    continue
                if str_pattern.search(line):
                    # If the same function already has ``param_name = {dict}``,
                    # substitute with the variable reference instead of a
                    # generic dict literal.
                    replacement = dict_literal
                    for fstart, fend, dvars in func_var_dict_ranges:
                        if fstart <= i < fend and param_name in dvars:
                            replacement = param_name
                            break
                    lines[i] = str_pattern.sub(
                        rf"\1={replacement}", line
                    )
        return "\n".join(lines)

    def _analyze_test_type_mismatches(
        self,
        tree: ast.AST,
        type_constraint_rules: Dict[str, Dict[str, list[str]]],
        class_map: Dict[str, Any],
    ) -> list[str]:
        if not type_constraint_rules:
            return []
        mismatches: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            bindings = self._collect_local_bindings(node)
            parent_map = self._parent_map(node)
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                called_name = callable_name(child)
                if not called_name or called_name not in type_constraint_rules:
                    continue
                if self._call_has_negative_expectation(child, parent_map):
                    continue
                constraints = type_constraint_rules[called_name]
                payload_arg = self._payload_argument_for_validation(child, called_name)
                payload_node = self._resolve_bound_value(payload_arg, bindings)
                for field_name, allowed_types in constraints.items():
                    observed_type = self._infer_argument_type(
                        payload_node, bindings, field_name, class_map,
                    )
                    if not observed_type:
                        continue
                    allowed_lower = {t.lower() for t in allowed_types}
                    if observed_type.lower() not in allowed_lower:
                        mismatches.add(
                            f"{called_name} passes {observed_type} for `{field_name}` (expected {', '.join(allowed_types)}) at line {child.lineno}"
                        )
        return sorted(mismatches)

    def _infer_argument_type(
        self,
        payload_node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        field_name: str,
        class_map: Dict[str, Any],
    ) -> str:
        return infer_argument_type(payload_node, bindings, field_name, class_map)

    def _parent_map(self, root: ast.AST) -> Dict[ast.AST, ast.AST]:
        return parent_map(root)

    def _call_has_negative_expectation(self, node: ast.Call, parent_map: Dict[ast.AST, ast.AST]) -> bool:
        return call_has_negative_expectation(node, parent_map)

    def _call_expects_invalid_outcome(
        self,
        test_node: ast.FunctionDef | ast.AsyncFunctionDef,
        call_node: ast.Call,
        parent_map: Dict[ast.AST, ast.AST],
    ) -> bool:
        return call_expects_invalid_outcome(test_node, call_node, parent_map)

    def _assert_expects_invalid_outcome(
        self,
        node: ast.AST,
        result_name: Optional[str],
        payload_name: Optional[str],
    ) -> bool:
        return assert_expects_invalid_outcome(node, result_name, payload_name)

    def _invalid_outcome_subject_matches(
        self,
        node: ast.AST,
        result_name: Optional[str],
        payload_name: Optional[str],
    ) -> bool:
        return invalid_outcome_subject_matches(node, result_name, payload_name)

    def _invalid_outcome_marker_matches(self, node: ast.AST) -> bool:
        return invalid_outcome_marker_matches(node)

    def _batch_call_allows_partial_invalid_items(
        self,
        test_node: ast.FunctionDef | ast.AsyncFunctionDef,
        call_node: ast.Call,
        bindings: Dict[str, ast.AST],
        parent_map: Dict[ast.AST, ast.AST],
    ) -> bool:
        return batch_call_allows_partial_invalid_items(test_node, call_node, bindings, parent_map)

    def _assigned_name_for_call(self, call_node: ast.Call, parent_map: Dict[ast.AST, ast.AST]) -> Optional[str]:
        return assigned_name_for_call(call_node, parent_map)

    def _assert_limits_batch_result(
        self,
        test: ast.AST,
        result_name: Optional[str],
        call_node: ast.Call,
        batch_size: int,
    ) -> bool:
        return assert_limits_batch_result(test, result_name, call_node, batch_size)

    def _len_call_matches_batch_result(
        self,
        node: ast.AST,
        result_name: Optional[str],
        call_node: ast.Call,
    ) -> bool:
        return len_call_matches_batch_result(node, result_name, call_node)

    def _int_constant_value(self, node: ast.AST) -> Optional[int]:
        return int_constant_value(node)

    def _comparison_implies_partial_batch_result(
        self,
        op: ast.cmpop,
        compared_value: Optional[int],
        batch_size: int,
    ) -> bool:
        return comparison_implies_partial_batch_result(op, compared_value, batch_size)

    @staticmethod
    def _test_name_suggests_validation_failure(test_name: str) -> bool:
        return name_suggests_validation_failure(test_name)

    @staticmethod
    def _is_internal_score_state_target(rendered_target: str) -> bool:
        return is_internal_score_state_target(rendered_target)

    @staticmethod
    def _behavior_contract_explicitly_limits_score_state_to_valid_requests(
        code_behavior_contract: str,
        rendered_target: str,
    ) -> bool:
        return behavior_contract_explicitly_limits_score_state_to_valid_requests(
            code_behavior_contract,
            rendered_target,
        )

    def _find_contract_overreach_signals(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        bindings: Dict[str, ast.AST],
        code_behavior_contract: str = "",
    ) -> list[str]:
        return find_contract_overreach_signals(node, bindings, code_behavior_contract)

    def _visible_repeated_single_call_batch_sizes(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        bindings: Dict[str, ast.AST],
    ) -> list[int]:
        return visible_repeated_single_call_batch_sizes(node, bindings)

    def _loop_contains_non_batch_call(self, node: ast.AST) -> bool:
        return loop_contains_non_batch_call(node)

    def _exact_len_assertion(self, node: ast.AST) -> Optional[tuple[str, int]]:
        return exact_len_assertion(node)

    def _is_len_call(self, node: ast.AST) -> bool:
        return is_len_call(node)

    def _assert_expects_false(self, node: ast.Assert, call_node: ast.Call) -> bool:
        return assert_expects_false(node, call_node)

    def _with_uses_pytest_raises(self, node: ast.With | ast.AsyncWith) -> bool:
        return with_uses_pytest_raises(node)

    def _with_uses_pytest_assertion_context(self, node: ast.With | ast.AsyncWith) -> bool:
        return with_uses_pytest_assertion_context(node)

    def _count_test_assertion_like_checks(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        return count_test_assertion_like_checks(node)

    def _ast_contains_node(self, root: ast.AST, target: ast.AST) -> bool:
        return ast_contains_node(root, target)

    def _collect_local_bindings(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, ast.AST]:
        return collect_local_bindings(node)

    def _collect_module_defined_names(self, tree: ast.AST) -> set[str]:
        return collect_module_defined_names(tree)

    def _function_argument_names(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        return function_argument_names(node)

    def _collect_parametrized_argument_names(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> set[str]:
        return collect_parametrized_argument_names(node)

    def _extract_parametrize_argument_names(self, decorator: ast.Call) -> set[str]:
        return extract_parametrize_argument_names(decorator)

    def _collect_undefined_local_names(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        module_defined_names: set[str],
    ) -> list[str]:
        return collect_undefined_local_names(node, module_defined_names)

    def _collect_local_name_bindings(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        return collect_local_name_bindings(node)

    def _call_signature_details(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        skip_first_param: bool = False,
    ) -> Dict[str, Any]:
        return call_signature_details(node, skip_first_param=skip_first_param)

    def _method_binding_kind(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        return method_binding_kind(node)

    def _self_assigned_attributes(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        return self_assigned_attributes(node)

    def _call_argument_count(self, node: ast.Call) -> int:
        return call_argument_count(node)

    def _infer_expression_type(
        self,
        node: Optional[ast.AST],
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
        function_map: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        return infer_expression_type(node, local_types, class_map, function_map)

    def _collect_test_local_types(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_map: Dict[str, Any],
        function_map: Dict[str, Dict[str, Any]],
    ) -> Dict[str, str]:
        return collect_test_local_types(
            node,
            class_map,
            function_map,
            self._infer_call_result_type,
        )

    def _find_unsupported_mock_assertions(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
    ) -> list[str]:
        return find_unsupported_mock_assertions(node, local_types, class_map)

    def _collect_mock_support(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> tuple[set[str], set[str]]:
        return collect_mock_support(node)

    def _supports_mock_assertion_target(
        self,
        node: ast.AST,
        mock_bindings: set[str],
        patched_targets: set[str],
    ) -> bool:
        return supports_mock_assertion_target(node, mock_bindings, patched_targets)

    def _known_type_allows_member(
        self,
        node: ast.Attribute,
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
    ) -> bool:
        return known_type_allows_member(node, local_types, class_map)

    def _is_mock_factory_call(self, node: ast.AST) -> bool:
        return is_mock_factory_call(node)

    def _is_patch_call(self, node: ast.AST) -> bool:
        return is_patch_call(node)

    def _patched_target_name_from_call(self, node: ast.Call) -> Optional[str]:
        return patched_target_name_from_call(node)

    def _infer_call_result_type(
        self,
        node: Optional[ast.AST],
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
        function_map: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        return infer_call_result_type(node, local_types, class_map, function_map)

    def _analyze_typed_test_member_usage(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
        function_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[list[str], list[str]]:
        return analyze_typed_test_member_usage(node, local_types, class_map, function_map)

    def _iter_relevant_test_body_nodes(self, node: ast.AST):
        yield from iter_relevant_test_body_nodes(node)

    def _bound_target_names(self, target: ast.AST) -> set[str]:
        return bound_target_names(target)

    def _payload_argument_for_validation(self, node: ast.Call, callable_name: str) -> Optional[ast.expr]:
        return payload_argument_for_validation(node, callable_name)

    def _resolve_bound_value(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        *,
        max_depth: int = 3,
    ) -> Optional[ast.AST]:
        return resolve_bound_value(node, bindings, max_depth=max_depth)

    def _extract_literal_dict_keys(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        class_map: Optional[Dict[str, Any]] = None,
    ) -> Optional[set[str]]:
        return extract_literal_dict_keys(node, bindings, class_map)

    def _extract_literal_field_values(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        field_name: str,
        class_map: Dict[str, Any],
    ) -> list[str]:
        return extract_literal_field_values(node, bindings, field_name, class_map)

    def _extract_string_literals(self, node: Optional[ast.AST], bindings: Dict[str, ast.AST]) -> list[str]:
        return extract_string_literals(node, bindings)

    def _call_argument_value(
        self,
        node: ast.Call,
        argument_name: str,
        class_map: Dict[str, Any],
    ) -> Optional[ast.AST]:
        return call_argument_value(node, argument_name, class_map)

    def _extract_literal_list_items(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
    ) -> Optional[list[ast.AST]]:
        return extract_literal_list_items(node, bindings)

    def _validate_batch_call(
        self,
        node: ast.Call,
        bindings: Dict[str, ast.AST],
        callable_name: str,
        batch_rule: Dict[str, Any],
    ) -> list[str]:
        return validate_batch_call(node, bindings, callable_name, batch_rule)

    def _build_agent_input(self, task: Task, project: ProjectState) -> AgentInput:
        context = self._build_context(task, project)
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        repair_focus_lines = build_repair_focus_lines(repair_context, context) if repair_context else []
        return build_agent_input(
            task,
            project,
            context,
            repair_focus_lines=repair_focus_lines,
        )

    def execute_workflow(self, project: ProjectState):
        """Execute the full workflow until completion or an unrecoverable failure."""
        if self._exit_if_workflow_cancelled(project):
            return
        project.execution_plan()
        validate_agent_resolution(self.registry, project)
        project.repair_max_cycles = self.config.workflow_max_repair_cycles
        resume_workflow_tasks(
            project,
            workflow_resume_policy=self.config.workflow_resume_policy,
            failed_task_ids_for_repair=self._failed_task_ids_for_repair,
            resume_failed_workflow_tasks=lambda current_project, current_failed_task_ids, current_failure_categories: resume_failed_workflow_tasks(
                current_project,
                current_failed_task_ids,
                current_failure_categories,
                is_repairable_failure=self._is_repairable_failure,
                workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                resume_failed_tasks_with_repair_cycle=lambda resume_project, resume_failed_task_ids, resume_failure_categories, **kwargs: resume_failed_tasks_with_repair_cycle(
                    resume_project,
                    resume_failed_task_ids,
                    resume_failure_categories,
                    configure_repair_attempts=self._configure_repair_attempts,
                    repair_task_ids_for_cycle=self._repair_task_ids_for_cycle,
                    log_event=self._log_event,
                    **kwargs,
                ),
            ),
            log_event=self._log_event,
        )
        if self._exit_if_workflow_cancelled(project):
            return
        if self._exit_if_workflow_paused(project):
            return
        ensure_workflow_running(
            project,
            workflow_acceptance_policy=self.config.workflow_acceptance_policy,
            workflow_max_repair_cycles=self.config.workflow_max_repair_cycles,
            log_event=self._log_event,
        )
        while True:
            if self._exit_if_workflow_cancelled(project):
                return
            pending = project.pending_tasks()
            if finish_workflow_if_no_pending_tasks(
                project,
                pending,
                workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                log_event=self._log_event,
            ):
                break
            if self._exit_if_workflow_cancelled(project):
                return
            if self._exit_if_workflow_paused(project):
                return
            try:
                runnable = project.runnable_tasks()
            except WorkflowDefinitionError:
                fail_workflow_for_definition_error(
                    project,
                    workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                    zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                    evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                    log_event=self._log_event,
                )
                raise
            if not runnable:
                fail_workflow_when_blocked(
                    project,
                    blocked_tasks=list(project.blocked_tasks()),
                    workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                    zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                    evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                    log_event=self._log_event,
                )
            for task in runnable:
                if self._exit_if_workflow_cancelled(project):
                    return
                if self._exit_if_workflow_paused(project):
                    return
                try:
                    self.run_task(task, project)
                except Exception as exc:
                    if self._exit_if_workflow_cancelled(project):
                        return
                    failure_category = self._classify_task_failure(task, exc)
                    if project.should_retry_task(task.id):
                        self._emit_workflow_progress(project, task=task)
                        project.save()
                        continue
                    if not self._is_repairable_failure(failure_category):
                        if self.config.workflow_failure_policy == "continue":
                            continue_workflow_after_task_failure(
                                project,
                                task=task,
                                emit_workflow_progress=self._emit_workflow_progress,
                                log_event=self._log_event,
                            )
                            continue
                        project.mark_workflow_finished(
                            "failed",
                            acceptance_policy=self.config.workflow_acceptance_policy,
                            terminal_outcome=WorkflowOutcome.FAILED.value,
                            failure_category=failure_category,
                            acceptance_criteria_met=False,
                            acceptance_evaluation=evaluate_workflow_acceptance(
                                project,
                                self.config.workflow_acceptance_policy,
                                _ZERO_BUDGET_FAILURE_CATEGORIES,
                            ),
                        )
                        project.save()
                        self._log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)
                        raise
                    if self._queue_active_cycle_repair(project, task):
                        self._emit_workflow_progress(project, task=task)
                        project.save()
                        continue
                    if self.config.workflow_failure_policy == "continue":
                        continue_workflow_after_task_failure(
                            project,
                            task=task,
                            emit_workflow_progress=self._emit_workflow_progress,
                            log_event=self._log_event,
                        )
                        continue
                    project.mark_workflow_finished(
                        "failed",
                        acceptance_policy=self.config.workflow_acceptance_policy,
                        terminal_outcome=WorkflowOutcome.FAILED.value,
                        failure_category=failure_category,
                        acceptance_criteria_met=False,
                        acceptance_evaluation=evaluate_workflow_acceptance(
                            project,
                            self.config.workflow_acceptance_policy,
                            _ZERO_BUDGET_FAILURE_CATEGORIES,
                        ),
                    )
                    project.save()
                    self._log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)
                    raise
                self._emit_workflow_progress(project, task=task)
                project.save()
        self._log_event(
            "info",
            "workflow_finished",
            project_name=project.project_name,
            phase=project.phase,
            terminal_outcome=project.terminal_outcome,
            workflow_telemetry=project.internal_runtime_telemetry()["workflow"],
        )
