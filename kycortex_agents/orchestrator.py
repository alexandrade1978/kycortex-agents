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
)
from kycortex_agents.orchestration.context_building import (
    build_agent_view_runtime,
    build_task_context_runtime,
    direct_dependency_ids,
    task_dependency_closure_ids,
)
from kycortex_agents.orchestration.output_helpers import (
    normalize_agent_result,
    semantic_output_key,
    summarize_output,
    task_context_output,
    unredacted_agent_result,
    validation_payload,
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
    extract_constructor_storage_rule,
    extract_indirect_required_fields,
    extract_lookup_field_rules,
    extract_required_fields,
    extract_score_derivation_rule,
    extract_sequence_input_rule,
    expand_local_name_aliases,
    field_selector_name,
    first_user_parameter,
    function_returns_score_value,
    helper_classes_to_avoid,
    inline_score_helper_expression,
    is_probable_third_party_import,
    parameter_is_iterated,
    parse_behavior_contract,
    render_score_expression,
)
from kycortex_agents.orchestration.repair_analysis import (
    dataclass_default_order_repair_examples,
    duplicate_constructor_argument_call_hint,
    duplicate_constructor_argument_details,
    duplicate_constructor_explicit_rewrite_hint,
    failed_artifact_content_for_category,
    internal_constructor_strictness_details,
    invalid_outcome_missing_audit_trail_details,
    missing_import_nameerror_details,
    missing_object_attribute_details,
    nested_payload_wrapper_field_validation_details,
    plain_class_field_default_factory_details,
    render_name_list,
    suggest_declared_attribute_replacement,
)
from kycortex_agents.orchestration.repair_test_analysis import (
    imported_code_task_for_failed_test,
    normalized_helper_surface_symbols,
    qa_repair_should_reuse_failed_test_artifact,
    helper_surface_usages_for_test_repair_runtime,
    failed_test_requires_code_repair_runtime,
    upstream_code_task_for_test_failure,
)
from kycortex_agents.orchestration.repair_focus import (
    build_repair_focus_lines,
)
from kycortex_agents.orchestration.repair_instructions import (
    build_code_repair_instruction_from_test_failure_runtime,
    build_repair_instruction_runtime,
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
    build_budget_decomposition_task_context,
    compact_architecture_context,
    is_budget_decomposition_planner,
    repair_requires_budget_decomposition,
    should_compact_architecture_context,
    task_public_contract_anchor as extract_task_public_contract_anchor,
    task_public_contract_preflight,
    task_exact_top_level_test_count,
    task_fixture_budget,
    task_line_budget,
    task_max_top_level_test_count,
    task_requires_cli_entrypoint,
)
from kycortex_agents.orchestration.test_ast_analysis import (
    analyze_test_module,
    analyze_test_behavior_contracts,
    auto_fix_test_type_mismatches,
)
from kycortex_agents.orchestration.validation_reporting import (
    build_dependency_validation_summary,
    build_repair_validation_summary,
    build_test_validation_summary,
    completion_diagnostics_from_provider_call,
    completion_validation_issue,
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
    pytest_failure_is_semantic_assertion_mismatch,
    pytest_failure_origin,
    validation_has_blocking_issues,
    validation_has_only_warnings,
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
    repair_task_ids_for_cycle,
    resume_failed_workflow_tasks,
    resume_failed_tasks_with_repair_cycle,
    resume_workflow_tasks,
    replay_workflow,
    resume_workflow,
    skip_task,
    validate_agent_resolution,
    queue_active_cycle_repair,
)
from kycortex_agents.orchestration.workflow_acceptance import evaluate_workflow_acceptance
from kycortex_agents.providers.base import (
    redact_sensitive_data,
)
from kycortex_agents.types import (
    AgentInput,
    AgentOutput,
    ArtifactRecord,
    ArtifactType,
    FailureCategory,
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
            normalized_output = sanitize_output_provider_call_metadata(normalized_output)
            self._validate_task_output(task, agent_input.context, normalized_output)
            self._persist_artifacts(normalized_output.artifacts)
            for decision in normalized_output.decisions:
                project.add_decision_record(decision)
            for artifact in normalized_output.artifacts:
                project.add_artifact_record(artifact)
            provider_call = provider_call_metadata(agent, normalized_output)
            project.complete_task(task.id, normalized_output, provider_call=provider_call)
        except Exception as exc:
            failure_category = self._classify_task_failure(task, exc)
            project.fail_task(
                task.id,
                exc,
                provider_call=provider_call_metadata(agent, normalized_output),
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
                provider_call = provider_call_metadata(agent, normalized_output)
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
            analyze_dependency_manifest,
            self._record_output_validation,
        )

    def _validate_code_output(self, output: AgentOutput, task: Optional[Task] = None) -> None:
        validate_code_output_runtime(
            output,
            task_line_budget(task),
            task_requires_cli_entrypoint(task),
            self._should_validate_code_content,
            self._analyze_python_module,
            self._output_line_count,
            lambda code_analysis: task_public_contract_preflight(task, code_analysis),
            self._completion_diagnostics_from_output,
            self._artifact_filename,
            self._execute_generated_module_import,
            self._record_output_validation,
            completion_validation_issue,
        )

    def _execute_generated_module_import(self, module_filename: str, code_content: str) -> Dict[str, Any]:
        return execute_generated_module_import(
            module_filename,
            code_content,
            self.config.execution_sandbox_policy(),
            python_executable=sys.executable,
            host_env=os.environ,
            subprocess_run=subprocess.run,
            sanitize_filename=sanitize_generated_filename,
            write_import_runner_fn=write_generated_import_runner,
            build_env_fn=lambda tmp_path, sandbox_policy: build_generated_test_env(
                tmp_path,
                sandbox_policy,
                host_env=os.environ,
            ),
            build_preexec_fn=lambda sandbox_policy: build_sandbox_preexec_fn(
                sandbox_policy,
                os_module=os,
                resource_module=resource,
            ),
            redact_result=redact_validation_execution_result,
        )

    def _validate_test_output(self, context: Dict[str, Any], output: AgentOutput, task: Optional[Task] = None) -> None:
        validate_test_output_runtime(
            context,
            output,
            task_line_budget(task),
            task_exact_top_level_test_count(task),
            task_max_top_level_test_count(task),
            task_fixture_budget(task),
            QATesterAgent._finalize_generated_test_suite,
            self._should_validate_test_content,
            self._analyze_test_module,
            auto_fix_test_type_mismatches,
            self._output_line_count,
            self._execute_generated_tests,
            self._completion_diagnostics_from_output,
            pytest_failure_origin,
            self._record_output_validation,
            completion_validation_issue,
            summarize_output,
        )
        # If only warnings and pytest passed → accept (warnings are false positives)

    def _output_line_count(self, raw_content: str) -> int:
        if not raw_content:
            return 0
        return len(raw_content.splitlines())

    def _should_compact_architecture_context(self, task: Optional[Task], task_public_contract_anchor: str) -> bool:
        execution_agent_name = self._execution_agent_name(task) if task is not None else None
        return should_compact_architecture_context(task, task_public_contract_anchor, execution_agent_name, self.config.max_tokens)

    def _classify_task_failure(self, task: Task, exc: Exception) -> str:
        normalized_role = (task.assigned_to or "").strip().lower()
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
            sanitize_filename=sanitize_generated_filename,
            write_test_runner_fn=write_generated_test_runner,
            build_env_fn=lambda tmp_path, sandbox_policy: build_generated_test_env(
                tmp_path,
                sandbox_policy,
                host_env=os.environ,
            ),
            build_preexec_fn=lambda sandbox_policy: build_sandbox_preexec_fn(
                sandbox_policy,
                os_module=os,
                resource_module=resource,
            ),
            summarize_output=summarize_pytest_output,
            redact_result=redact_validation_execution_result,
        )

    def _persist_artifacts(self, artifacts: list[ArtifactRecord]) -> None:
        ArtifactPersistenceSupport(self.config.output_dir, sanitize_sub=re.sub).persist_artifacts(artifacts)

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

    def _completion_diagnostics_from_output(
        self,
        output: AgentOutput,
        *,
        raw_content: str = "",
        syntax_ok: bool,
        syntax_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        provider_call = output.metadata.get("provider_call") if isinstance(output.metadata, dict) else None
        return completion_diagnostics_from_provider_call(
            provider_call,
            raw_content=raw_content,
            syntax_ok=syntax_ok,
            syntax_error=syntax_error,
        )

    def _build_code_repair_context_from_test_failure(
        self,
        code_task: Task,
        test_task: Task,
        cycle: Dict[str, Any],
    ) -> Dict[str, Any]:
        def current_failed_artifact_content(current_task: Task, artifact_type: Any) -> str:
            return failed_artifact_content(
                current_task.output,
                current_task.output_payload,
                artifact_type,
            )

        def current_repair_validation_summary(current_task: Task, failure_category: str) -> str:
            return build_repair_validation_summary(
                current_task,
                failure_category,
                validation_payload(current_task),
            )

        def current_code_repair_instruction(
            current_code_task: Task,
            validation_summary: str,
            existing_tests: object,
        ) -> str:
            return build_code_repair_instruction_from_test_failure_runtime(
                current_code_task,
                validation_summary,
                failed_artifact_content=current_failed_artifact_content,
                artifact_type=ArtifactType.CODE,
                duplicate_constructor_argument_details=duplicate_constructor_argument_details,
                duplicate_constructor_argument_call_hint=duplicate_constructor_argument_call_hint,
                duplicate_constructor_explicit_rewrite_hint=duplicate_constructor_explicit_rewrite_hint,
                plain_class_field_default_factory_details=plain_class_field_default_factory_details,
                missing_object_attribute_details=missing_object_attribute_details,
                suggest_declared_attribute_replacement=suggest_declared_attribute_replacement,
                render_name_list=render_name_list,
                nested_payload_wrapper_field_validation_details=nested_payload_wrapper_field_validation_details,
                invalid_outcome_missing_audit_trail_details=invalid_outcome_missing_audit_trail_details,
                internal_constructor_strictness_details=internal_constructor_strictness_details,
                existing_tests=existing_tests,
            )

        return build_code_repair_context_from_test_failure(
            code_task,
            test_task,
            cycle,
            failed_artifact_content=current_failed_artifact_content,
            build_repair_validation_summary=current_repair_validation_summary,
            build_code_repair_instruction_from_test_failure=current_code_repair_instruction,
            merge_prior_repair_context=merge_prior_repair_context,
        )

    def _ensure_budget_decomposition_task(
        self,
        project: ProjectState,
        task: Task,
        repair_context: Dict[str, Any],
    ) -> Optional[Task]:
        def current_budget_decomposition_task_context(
            current_task: Task,
            current_repair_context: Dict[str, Any],
        ) -> Dict[str, Any]:
            return build_budget_decomposition_task_context(
                current_task,
                current_repair_context,
                self._execution_agent_name(current_task),
            )

        return ensure_budget_decomposition_task(
            project,
            task,
            repair_context,
            requires_budget_decomposition=repair_requires_budget_decomposition,
            build_budget_decomposition_task_context=current_budget_decomposition_task_context,
        )

    def _build_repair_context(self, task: Task, cycle: Dict[str, Any]) -> Dict[str, Any]:
        def current_repair_owner_for_category(current_task: Task, failure_category: str) -> str:
            return repair_owner_for_category(
                current_task.assigned_to,
                failure_category,
            )

        def current_failed_artifact_content(current_task: Task, artifact_type: Any) -> str:
            return failed_artifact_content(
                current_task.output,
                current_task.output_payload,
                artifact_type,
            )

        def current_repair_instruction(current_task: Task, failure_category: str) -> str:
            return build_repair_instruction_runtime(
                current_task,
                failure_category,
                failed_artifact_content=current_failed_artifact_content,
                artifact_type=ArtifactType.CODE,
                validation_payload=validation_payload,
                dataclass_default_order_repair_examples=dataclass_default_order_repair_examples,
                missing_import_nameerror_details=missing_import_nameerror_details,
                plain_class_field_default_factory_details=plain_class_field_default_factory_details,
                test_validation_has_only_warnings=validation_has_only_warnings,
            )

        def current_repair_validation_summary(current_task: Task, failure_category: str) -> str:
            return build_repair_validation_summary(
                current_task,
                failure_category,
                validation_payload(current_task),
            )

        def current_failed_artifact_content_for_category(current_task: Task, failure_category: str) -> str:
            return failed_artifact_content_for_category(
                current_task.output,
                current_task.output_payload,
                failure_category,
            )

        def current_test_repair_helper_surface_usages(current_task: Task, failure_category: str) -> list[str]:
            return helper_surface_usages_for_test_repair_runtime(
                current_task,
                failure_category,
                validation_payload=validation_payload,
            )

        return build_repair_context(
            task,
            cycle,
            repair_owner_for_category=current_repair_owner_for_category,
            build_repair_instruction=current_repair_instruction,
            build_repair_validation_summary=current_repair_validation_summary,
            failed_artifact_content_for_category=current_failed_artifact_content_for_category,
            test_repair_helper_surface_usages=current_test_repair_helper_surface_usages,
            normalized_helper_surface_symbols=normalized_helper_surface_symbols,
            merge_prior_repair_context=merge_prior_repair_context,
        )

    def _queue_active_cycle_repair(self, project: ProjectState, task: Task) -> bool:
        return queue_active_cycle_repair(
            project,
            task,
            workflow_resume_policy=self.config.workflow_resume_policy,
            active_repair_cycle=active_repair_cycle,
            has_repair_task_for_cycle=has_repair_task_for_cycle,
            configure_repair_attempts=self._configure_repair_attempts,
            repair_task_ids_for_cycle=self._repair_task_ids_for_cycle,
            log_event=self._log_event,
        )

    def _configure_repair_attempts(self, project: ProjectState, failed_task_ids: list[str], cycle: Dict[str, Any]) -> None:
        configure_repair_attempts(
            project,
            failed_task_ids,
            cycle,
            test_failure_requires_code_repair=lambda task: failed_test_requires_code_repair_runtime(
                task,
                validation_payload=validation_payload,
                pytest_failure_origin=pytest_failure_origin,
                pytest_contract_overreach_signals=pytest_contract_overreach_signals,
                test_validation_has_blocking_issues=validation_has_blocking_issues,
                pytest_failure_is_semantic_assertion_mismatch=pytest_failure_is_semantic_assertion_mismatch,
            ),
            upstream_code_task_for_test_failure=lambda current_project, current_task: upstream_code_task_for_test_failure(
                current_project,
                current_task,
                imported_code_task_for_failed_test=lambda imported_project, imported_task: imported_code_task_for_failed_test(
                    imported_project,
                    imported_task,
                    failed_artifact_content=lambda artifact_task, artifact_type=None: failed_artifact_content(
                        artifact_task.output,
                        artifact_task.output_payload,
                        artifact_type,
                    ),
                    python_import_roots=python_import_roots,
                    default_module_name_for_task=self._default_module_name_for_task,
                ),
            ),
            build_code_repair_context_from_test_failure=self._build_code_repair_context_from_test_failure,
            ensure_budget_decomposition_task=self._ensure_budget_decomposition_task,
            build_repair_context=self._build_repair_context,
        )

    def _repair_task_ids_for_cycle(self, project: ProjectState, failed_task_ids: list[str]) -> list[str]:
        return repair_task_ids_for_cycle(
            project,
            failed_task_ids,
            test_failure_requires_code_repair=lambda task: failed_test_requires_code_repair_runtime(
                task,
                validation_payload=validation_payload,
                pytest_failure_origin=pytest_failure_origin,
                pytest_contract_overreach_signals=pytest_contract_overreach_signals,
                test_validation_has_blocking_issues=validation_has_blocking_issues,
                pytest_failure_is_semantic_assertion_mismatch=pytest_failure_is_semantic_assertion_mismatch,
            ),
            upstream_code_task_for_test_failure=lambda current_project, current_task: upstream_code_task_for_test_failure(
                current_project,
                current_task,
                imported_code_task_for_failed_test=lambda imported_project, imported_task: imported_code_task_for_failed_test(
                    imported_project,
                    imported_task,
                    failed_artifact_content=lambda artifact_task, artifact_type=None: failed_artifact_content(
                        artifact_task.output,
                        artifact_task.output_payload,
                        artifact_type,
                    ),
                    python_import_roots=python_import_roots,
                    default_module_name_for_task=self._default_module_name_for_task,
                ),
            ),
            ensure_budget_decomposition_task=self._ensure_budget_decomposition_task,
            execution_agent_name=self._execution_agent_name,
        )

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
            dependency_analysis = analyze_dependency_manifest(task.output or "", code_analysis)
            return {
                "dependency_manifest": task.output or "",
                "dependency_manifest_path": artifact_path,
                "dependency_analysis": dependency_analysis,
                "dependency_validation_summary": build_dependency_validation_summary(dependency_analysis),
            }
        return {}

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
    def _dict_accessed_keys_from_tree(tree: ast.AST) -> Dict[str, list[str]]:
        return dict_accessed_keys_from_tree(tree)

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

    def _call_signature_details(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        skip_first_param: bool = False,
    ) -> Dict[str, Any]:
        return call_signature_details(node, skip_first_param=skip_first_param)

    def _build_agent_input(self, task: Task, project: ProjectState) -> AgentInput:
        context = build_task_context_runtime(
            task,
            project,
            provider_max_tokens=self.config.max_tokens,
            build_agent_view=lambda current_task, current_project, snapshot: build_agent_view_runtime(
                current_task,
                current_project,
                snapshot,
                task_dependency_closure_ids=task_dependency_closure_ids,
                direct_dependency_ids=direct_dependency_ids,
            ),
            task_dependency_closure_ids=task_dependency_closure_ids,
            execution_agent_name=self._execution_agent_name,
            planned_module_context=lambda current_project, visible_task_ids, current_task: self._planned_module_context(
                current_project,
                visible_task_ids,
                current_task=current_task,
            ),
            task_public_contract_anchor=extract_task_public_contract_anchor,
            should_compact_architecture_context=self._should_compact_architecture_context,
            compact_architecture_context=compact_architecture_context,
            task_context_output=task_context_output,
            is_budget_decomposition_planner=is_budget_decomposition_planner,
            semantic_output_key=semantic_output_key,
            normalize_assigned_to=AgentRegistry.normalize_key,
            code_artifact_context=self._code_artifact_context,
            dependency_artifact_context=self._dependency_artifact_context,
            test_artifact_context=self._test_artifact_context,
            agent_visible_repair_context=self._agent_visible_repair_context,
            normalized_helper_surface_symbols=normalized_helper_surface_symbols,
            qa_repair_should_reuse_failed_test_artifact=qa_repair_should_reuse_failed_test_artifact,
            redact_sensitive_data=redact_sensitive_data,
        )
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
            exit_if_workflow_cancelled=lambda current_project: exit_if_workflow_cancelled(self.logger, current_project),
            execution_plan=project.execution_plan,
            validate_agent_resolution=validate_agent_resolution,
            registry=self.registry,
            workflow_max_repair_cycles=self.config.workflow_max_repair_cycles,
            resume_workflow_tasks=lambda current_project: resume_workflow_tasks(
                current_project,
                workflow_resume_policy=self.config.workflow_resume_policy,
                failed_task_ids_for_repair=failed_task_ids_for_repair,
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
                exit_if_workflow_cancelled=lambda active_project: exit_if_workflow_cancelled(self.logger, active_project),
                exit_if_workflow_paused=lambda active_project: exit_if_workflow_paused(self.logger, active_project),
                ensure_workflow_running=lambda active_project: ensure_workflow_running(
                    active_project,
                    workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                    workflow_max_repair_cycles=self.config.workflow_max_repair_cycles,
                    log_event=self._log_event,
                ),
                execute_workflow_loop=lambda active_project: execute_workflow_loop(
                    active_project,
                    exit_if_workflow_cancelled=lambda loop_project: exit_if_workflow_cancelled(self.logger, loop_project),
                    exit_if_workflow_paused=lambda loop_project: exit_if_workflow_paused(self.logger, loop_project),
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
                                exit_if_workflow_cancelled=lambda current_task_project: exit_if_workflow_cancelled(self.logger, current_task_project),
                                exit_if_workflow_paused=lambda current_task_project: exit_if_workflow_paused(self.logger, current_task_project),
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
                                    emit_workflow_progress=lambda progress_project, *, task=None: emit_workflow_progress(
                                        self.logger,
                                        progress_project,
                                        task=task,
                                    ),
                                    evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                                    log_event=self._log_event,
                                ),
                                emit_workflow_progress=lambda progress_project, *, task=None: emit_workflow_progress(
                                    self.logger,
                                    progress_project,
                                    task=task,
                                ),
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
