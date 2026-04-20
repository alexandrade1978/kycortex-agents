import ast
import importlib.util
import logging
import os
import re
import subprocess
import sys
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
    python_import_roots,
)
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.artifacts import failed_artifact_content
from kycortex_agents.orchestration.dependency_analysis import (
    analyze_dependency_manifest,
    normalize_import_name,
    normalize_package_name,
)
from kycortex_agents.orchestration.context_building import (
    build_task_context_runtime,
)
from kycortex_agents.orchestration.output_helpers import (
    normalize_agent_result,
    semantic_output_key,
    summarize_output,
    unredacted_agent_result,
)
from kycortex_agents.orchestration.module_ast_analysis import (
    analyze_python_module,
    annotation_accepts_sequence_input,
    build_code_behavior_contract,
    build_code_exact_test_contract,
    build_module_run_command,
    build_code_public_api,
    build_code_test_targets,
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
    entrypoint_symbol_names,
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
    helper_classes_to_avoid,
    infer_dict_key_value_examples,
    inline_score_helper_expression,
    is_probable_third_party_import,
    isinstance_subject_name,
    isinstance_type_names,
    method_binding_kind,
    parameter_is_iterated,
    parse_behavior_contract,
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
    analyze_test_module,
    analyze_test_behavior_contracts,
    auto_fix_test_type_mismatches,
    analyze_test_type_mismatches,
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
    validate_code_output_runtime,
    validate_dependency_output_runtime,
    validate_test_output_runtime,
)
from kycortex_agents.orchestration.validation_analysis import (
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
    dispatch_task_failure,
    build_repair_context,
    ensure_workflow_running,
    ensure_budget_decomposition_task,
    execute_runnable_frontier,
    execute_workflow_runtime,
    execute_workflow_loop,
    execute_runnable_tasks,
    execute_workflow_task,
    failed_task_ids_for_repair,
    finish_workflow_if_no_pending_tasks,
    run_active_workflow,
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
    TaskResult,
)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


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
        validate_dependency_output_runtime(
            context,
            output,
            self._analyze_dependency_manifest,
            self._record_output_validation,
        )

    def _validate_code_output(self, output: AgentOutput, task: Optional[Task] = None) -> None:
        validate_code_output_runtime(
            output,
            self._task_line_budget(task),
            self._task_requires_cli_entrypoint(task),
            self._should_validate_code_content,
            self._analyze_python_module,
            self._output_line_count,
            lambda code_analysis: self._task_public_contract_preflight(task, code_analysis),
            self._completion_diagnostics_from_output,
            self._artifact_filename,
            self._execute_generated_module_import,
            self._record_output_validation,
            self._completion_validation_issue,
        )

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
        validate_test_output_runtime(
            context,
            output,
            self._task_line_budget(task),
            self._task_exact_top_level_test_count(task),
            self._task_max_top_level_test_count(task),
            self._task_fixture_budget(task),
            QATesterAgent._finalize_generated_test_suite,
            self._should_validate_test_content,
            self._analyze_test_module,
            self._auto_fix_test_type_mismatches,
            self._output_line_count,
            self._execute_generated_tests,
            self._completion_diagnostics_from_output,
            self._pytest_failure_origin,
            self._record_output_validation,
            self._completion_validation_issue,
            summarize_output,
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
        return build_task_context_runtime(
            task,
            project,
            provider_max_tokens=self.config.max_tokens,
            build_agent_view=self._build_agent_view,
            task_dependency_closure_ids=self._task_dependency_closure_ids,
            execution_agent_name=self._execution_agent_name,
            planned_module_context=lambda current_project, visible_task_ids, current_task: self._planned_module_context(
                current_project,
                visible_task_ids,
                current_task=current_task,
            ),
            task_public_contract_anchor=self._task_public_contract_anchor,
            should_compact_architecture_context=self._should_compact_architecture_context,
            compact_architecture_context=self._compact_architecture_context,
            task_context_output=self._task_context_output,
            is_budget_decomposition_planner=self._is_budget_decomposition_planner,
            semantic_output_key=semantic_output_key,
            normalize_assigned_to=AgentRegistry.normalize_key,
            code_artifact_context=self._code_artifact_context,
            dependency_artifact_context=self._dependency_artifact_context,
            test_artifact_context=self._test_artifact_context,
            agent_visible_repair_context=self._agent_visible_repair_context,
            normalized_helper_surface_symbols=self._normalized_helper_surface_symbols,
            qa_repair_should_reuse_failed_test_artifact=self._qa_repair_should_reuse_failed_test_artifact,
            redact_sensitive_data=redact_sensitive_data,
        )

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
        return analyze_python_module(raw_content)

    def _dataclass_field_has_default(self, value: Optional[ast.expr]) -> bool:
        return dataclass_field_has_default(value)

    def _dataclass_field_is_init_enabled(self, value: Optional[ast.expr]) -> bool:
        return dataclass_field_is_init_enabled(value)

    def _is_probable_third_party_import(self, module_name: str) -> bool:
        return is_probable_third_party_import(module_name)

    def _build_code_public_api(self, code_analysis: Dict[str, Any]) -> str:
        return build_code_public_api(code_analysis)

    def _build_code_exact_test_contract(self, code_analysis: Dict[str, Any]) -> str:
        return build_code_exact_test_contract(code_analysis)

    def _build_module_run_command(self, module_filename: str, code_analysis: Dict[str, Any]) -> str:
        return build_module_run_command(module_filename, code_analysis)

    def _build_code_test_targets(self, code_analysis: Dict[str, Any]) -> str:
        return build_code_test_targets(code_analysis)

    def _build_code_behavior_contract(self, raw_content: str) -> str:
        return build_code_behavior_contract(raw_content)

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
        module_symbols = set(code_analysis.get("symbols") or []) | set(code_analysis.get("module_variables") or [])
        function_names = {item["name"] for item in code_analysis.get("functions") or []}
        function_map = {item["name"]: item for item in code_analysis.get("functions") or []}
        class_map = code_analysis.get("classes") or {}
        helper_class_names_to_avoid = set(helper_classes_to_avoid(code_analysis))
        entrypoint_names = entrypoint_symbol_names(code_analysis)
        validation_rules, field_value_rules, batch_rules, sequence_input_functions, type_constraint_rules = self._parse_behavior_contract(
            code_behavior_contract
        )
        return analyze_test_module(
            raw_content,
            module_name,
            module_symbols,
            function_names,
            function_map,
            class_map,
            helper_class_names_to_avoid,
            entrypoint_names,
            validation_rules,
            field_value_rules,
            batch_rules,
            sequence_input_functions,
            type_constraint_rules,
            _RESERVED_FIXTURE_NAMES,
            _PYTEST_BUILTIN_FIXTURES,
            code_behavior_contract,
        )

    def _parse_behavior_contract(
        self,
        contract: str,
    ) -> tuple[Dict[str, list[str]], Dict[str, Dict[str, list[str]]], Dict[str, Dict[str, Any]], set[str], Dict[str, Dict[str, list[str]]]]:
        return parse_behavior_contract(contract)

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
        return analyze_test_behavior_contracts(
            tree,
            validation_rules,
            field_value_rules,
            batch_rules,
            sequence_input_functions,
            function_names,
            class_map,
        )

    def _auto_fix_test_type_mismatches(
        self,
        test_content: str,
        code_content: str,
    ) -> str:
        return auto_fix_test_type_mismatches(
            test_content,
            code_content,
            self._dict_accessed_keys_from_tree,
        )

    def _analyze_test_type_mismatches(
        self,
        tree: ast.AST,
        type_constraint_rules: Dict[str, Dict[str, list[str]]],
        class_map: Dict[str, Any],
    ) -> list[str]:
        return analyze_test_type_mismatches(tree, type_constraint_rules, class_map)

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
        execute_workflow_runtime(
            project,
            exit_if_workflow_cancelled=self._exit_if_workflow_cancelled,
            execution_plan=project.execution_plan,
            validate_agent_resolution=validate_agent_resolution,
            registry=self.registry,
            workflow_max_repair_cycles=self.config.workflow_max_repair_cycles,
            resume_workflow_tasks=lambda current_project: resume_workflow_tasks(
                current_project,
                workflow_resume_policy=self.config.workflow_resume_policy,
                failed_task_ids_for_repair=self._failed_task_ids_for_repair,
                resume_failed_workflow_tasks=lambda resume_project, current_failed_task_ids, current_failure_categories: resume_failed_workflow_tasks(
                    resume_project,
                    current_failed_task_ids,
                    current_failure_categories,
                    is_repairable_failure=self._is_repairable_failure,
                    workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                    zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                    evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                    resume_failed_tasks_with_repair_cycle=lambda repair_project, resume_failed_task_ids, resume_failure_categories, **kwargs: resume_failed_tasks_with_repair_cycle(
                        repair_project,
                        resume_failed_task_ids,
                        resume_failure_categories,
                        configure_repair_attempts=self._configure_repair_attempts,
                        repair_task_ids_for_cycle=self._repair_task_ids_for_cycle,
                        log_event=self._log_event,
                        **kwargs,
                    ),
                ),
                log_event=self._log_event,
            ),
            run_active_workflow=lambda current_project: run_active_workflow(
                current_project,
                exit_if_workflow_cancelled=self._exit_if_workflow_cancelled,
                exit_if_workflow_paused=self._exit_if_workflow_paused,
                ensure_workflow_running=lambda active_project: ensure_workflow_running(
                    active_project,
                    workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                    workflow_max_repair_cycles=self.config.workflow_max_repair_cycles,
                    log_event=self._log_event,
                ),
                execute_workflow_loop=lambda active_project: execute_workflow_loop(
                    active_project,
                    exit_if_workflow_cancelled=self._exit_if_workflow_cancelled,
                    exit_if_workflow_paused=self._exit_if_workflow_paused,
                    pending_tasks=active_project.pending_tasks,
                    finish_workflow_if_no_pending_tasks=lambda loop_project, pending: finish_workflow_if_no_pending_tasks(
                        loop_project,
                        pending,
                        workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                        zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                        evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                        log_event=self._log_event,
                    ),
                    execute_runnable_frontier=lambda loop_project: execute_runnable_frontier(
                        loop_project,
                        runnable_tasks=loop_project.runnable_tasks,
                        blocked_tasks=loop_project.blocked_tasks,
                        execute_runnable_tasks=lambda runnable_project, current_runnable: execute_runnable_tasks(
                            runnable_project,
                            current_runnable,
                            execute_workflow_task=lambda task_project, *, task: execute_workflow_task(
                                task_project,
                                task=task,
                                run_task=self.run_task,
                                exit_if_workflow_cancelled=self._exit_if_workflow_cancelled,
                                exit_if_workflow_paused=self._exit_if_workflow_paused,
                                classify_task_failure=self._classify_task_failure,
                                dispatch_task_failure=lambda dispatch_project, *, task, failure_category: dispatch_task_failure(
                                    dispatch_project,
                                    task=task,
                                    failure_category=failure_category,
                                    workflow_failure_policy=self.config.workflow_failure_policy,
                                    workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                                    zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                                    is_repairable_failure=self._is_repairable_failure,
                                    queue_active_cycle_repair=self._queue_active_cycle_repair,
                                    emit_workflow_progress=self._emit_workflow_progress,
                                    evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                                    log_event=self._log_event,
                                ),
                                emit_workflow_progress=self._emit_workflow_progress,
                            ),
                        ),
                        workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                        zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                        evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                        log_event=self._log_event,
                    ),
                ),
                log_event=self._log_event,
            ),
        )
