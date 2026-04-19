import ast
import copy
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

from kycortex_agents.agents.dependency_manager import extract_requirement_name, is_provenance_unsafe_requirement
from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.agents.registry import AgentRegistry, build_default_registry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestration.agent_runtime import build_agent_input, execute_agent
from kycortex_agents.orchestration.ast_tools import (
    AstNameReplacer,
    ast_name,
    callable_name,
    first_call_argument,
    is_pytest_fixture,
    render_expression,
)
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.output_helpers import (
    normalize_agent_result,
    semantic_output_key,
    summarize_output,
    unredacted_agent_result,
)
from kycortex_agents.orchestration.module_ast_analysis import (
    annotation_accepts_sequence_input,
    comparison_required_field,
    call_signature_details,
    call_expression_basename,
    dataclass_field_has_default,
    dataclass_field_is_init_enabled,
    extract_indirect_required_fields,
    extract_lookup_field_rules,
    extract_required_fields,
    field_selector_name,
    first_user_parameter,
    has_dataclass_decorator,
    method_binding_kind,
    parameter_is_iterated,
    self_assigned_attributes,
)
from kycortex_agents.orchestration.repair_analysis import (
    dataclass_default_order_repair_examples,
    class_field_annotations_from_failed_artifact,
    class_field_names_from_failed_artifact,
    default_value_for_annotation,
    duplicate_constructor_argument_call_details,
    duplicate_constructor_argument_call_hint,
    duplicate_constructor_argument_details,
    duplicate_constructor_explicit_rewrite_hint,
    first_non_import_line_with_name,
    internal_constructor_strictness_details,
    invalid_outcome_missing_audit_trail_details,
    missing_import_nameerror_details,
    missing_object_attribute_details,
    missing_required_constructor_details,
    nested_payload_wrapper_field_validation_details,
    plain_class_field_default_factory_details,
    render_name_list,
    required_field_list_from_failed_artifact,
    suggest_declared_attribute_replacement,
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
    analyze_test_repair_surface,
    is_helper_alias_like_name,
    module_defined_symbol_names,
    normalized_helper_surface_symbols,
    previous_valid_test_surface,
    validation_summary_helper_alias_names,
    validation_summary_symbols,
)
from kycortex_agents.orchestration.repair_focus import (
    build_repair_focus_lines,
)
from kycortex_agents.orchestration.repair_instructions import (
    build_code_repair_instruction_from_test_failure,
    build_repair_instruction,
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
    compact_architecture_context,
    should_compact_architecture_context,
    task_exact_top_level_test_count,
    task_fixture_budget,
    task_line_budget,
    task_max_top_level_test_count,
    task_requires_cli_entrypoint,
)
from kycortex_agents.orchestration.test_ast_analysis import (
    ast_contains_node,
    bound_target_names,
    collect_local_bindings,
    collect_local_name_bindings,
    collect_module_defined_names,
    collect_mock_support,
    collect_parametrized_argument_names,
    collect_test_local_types,
    collect_undefined_local_names,
    count_test_assertion_like_checks,
    extract_parametrize_argument_names,
    find_unsupported_mock_assertions,
    function_argument_names,
    is_mock_factory_call,
    is_patch_call,
    iter_relevant_test_body_nodes,
    known_type_allows_member,
    patched_target_name_from_call,
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
    cancel_workflow,
    emit_workflow_progress,
    exit_if_workflow_cancelled,
    exit_if_workflow_paused,
    log_event,
    override_task,
    pause_workflow,
    privacy_safe_log_fields,
    replay_workflow,
    resume_workflow,
    skip_task,
    task_id_collection_count,
    task_id_count_log_field_name,
    validate_agent_resolution,
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


_THIRD_PARTY_PACKAGE_ALIASES = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "crypto": "pycryptodome",
    "pil": "pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}

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
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return "True" if v else "False"
        if isinstance(v, int):
            return str(max(v, 1)) if v >= 0 else str(v)
        if isinstance(v, float):
            return str(max(v, 1.0)) if v >= 0 else str(v)
        if isinstance(v, str):
            return f"'{v}'" if v else "'sample'"
        if v is None:
            return None
    if isinstance(node, ast.List):
        if not node.elts:
            return "['sample']"
        try:
            return ast.unparse(node)
        except Exception:
            return "['sample']"
    if isinstance(node, ast.Dict):
        if not node.keys:
            return "{'key': 'value'}"
        try:
            return ast.unparse(node)
        except Exception:
            return "{'key': 'value'}"
    if isinstance(node, ast.Set):
        return "{'sample'}"
    if isinstance(node, ast.Tuple):
        return "('sample',)"
    return None


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
        if task is None or not code_analysis.get("syntax_ok", True):
            return None

        task_public_contract_anchor = self._task_public_contract_anchor(task.description)
        if not task_public_contract_anchor:
            return None

        class_map = code_analysis.get("classes") or {}
        function_map = {
            item["name"]: item
            for item in code_analysis.get("functions") or []
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        issues: list[str] = []
        public_facade = ""
        primary_request_model = ""
        required_surfaces: list[str] = []

        for line in task_public_contract_anchor.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue

            label, separator, surface = stripped[2:].partition(":")
            if not separator:
                continue

            normalized_label = label.strip().lower()
            normalized_surface = surface.strip()
            if not normalized_surface:
                continue

            if normalized_label == "public facade":
                public_facade = normalized_surface
                if normalized_surface not in class_map:
                    issues.append(f"missing public facade {normalized_surface}")
                continue

            if normalized_label == "primary request model":
                primary_request_model = normalized_surface
                _, model_name, expected_params = self._parse_task_public_contract_surface(normalized_surface)
                class_info = class_map.get(model_name)
                if not isinstance(class_info, dict):
                    issues.append(f"missing primary request model {model_name}")
                    continue

                actual_params = list(class_info.get("constructor_params") or [])
                min_required_params = class_info.get("constructor_min_args")
                expected_prefix = actual_params[: len(expected_params)]
                if expected_params and expected_prefix != expected_params:
                    issues.append(
                        f"primary request model {model_name} must start with constructor fields ({', '.join(expected_params)})"
                    )
                    continue
                if isinstance(min_required_params, int) and min_required_params > len(expected_params):
                    issues.append(
                        f"primary request model {model_name} requires additional constructor fields beyond ({', '.join(expected_params)})"
                    )
                continue

            required_surfaces.append(normalized_surface)
            owner_name, callable_name, _ = self._parse_task_public_contract_surface(normalized_surface)
            if owner_name:
                class_info = class_map.get(owner_name)
                method_signatures = (class_info or {}).get("method_signatures") or {}
                method_info = method_signatures.get(callable_name) if isinstance(method_signatures, dict) else None
                if not isinstance(class_info, dict) or not isinstance(method_info, dict):
                    issues.append(f"missing required surface {owner_name}.{callable_name}")
                continue
            function_info = function_map.get(callable_name)
            if not isinstance(function_info, dict):
                issues.append(f"missing required surface {callable_name}")
                continue
            _, _, expected_params = self._parse_task_public_contract_surface(normalized_surface)
            actual_params = list(function_info.get("params") or [])
            if expected_params and actual_params[: len(expected_params)] != expected_params:
                issues.append(
                    f"required surface {callable_name} must expose parameters ({', '.join(expected_params)})"
                )
                continue
            if callable_name == "main" and "__main__" in normalized_surface and not code_analysis.get("has_main_guard", False):
                issues.append("missing required surface main guard")

        return {
            "anchor_present": True,
            "anchor": task_public_contract_anchor,
            "public_facade": public_facade,
            "primary_request_model": primary_request_model,
            "required_surfaces": required_surfaces,
            "issues": issues,
            "passed": not issues,
        }

    def _parse_task_public_contract_surface(self, surface: str) -> tuple[Optional[str], str, list[str]]:
        normalized_surface = surface.strip()
        match = re.match(
            r"^(?:(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\.)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\((?P<args>[^)]*)\)",
            normalized_surface,
        )
        if not match:
            return None, normalized_surface, []

        args_text = match.group("args").strip()
        args: list[str] = []
        if args_text:
            for part in args_text.split(","):
                cleaned = part.strip()
                if not cleaned:
                    continue
                cleaned = cleaned.split("=", 1)[0].strip()
                cleaned = cleaned.split(":", 1)[0].strip()
                cleaned = cleaned.lstrip("*")
                if cleaned and cleaned not in {"/", "*"}:
                    args.append(cleaned)
        return match.group("owner"), match.group("name"), args

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
        owner_by_category = {
            FailureCategory.CODE_VALIDATION.value: "code_engineer",
            FailureCategory.TEST_VALIDATION.value: "qa_tester",
            FailureCategory.DEPENDENCY_VALIDATION.value: "dependency_manager",
        }
        return owner_by_category.get(failure_category, task.assigned_to)

    def _validation_payload(self, task: Task) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        metadata = task.output_payload.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        validation = metadata.get("validation")
        return validation if isinstance(validation, dict) else {}

    def _failed_artifact_content(self, task: Task, artifact_type: Optional[ArtifactType] = None) -> str:
        if not isinstance(task.output_payload, dict):
            return task.output or ""
        artifacts = task.output_payload.get("artifacts")
        if not isinstance(artifacts, list):
            return task.output or task.output_payload.get("raw_content", "")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            if artifact_type is not None and artifact.get("artifact_type") != artifact_type.value:
                continue
            content = artifact.get("content")
            if isinstance(content, str) and content.strip():
                return content
        raw_content = task.output_payload.get("raw_content")
        return raw_content if isinstance(raw_content, str) else (task.output or "")

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
        if AgentRegistry.normalize_key(task.assigned_to) != "qa_tester":
            return False
        if task.last_error_category != FailureCategory.TEST_VALIDATION.value:
            return False

        validation = self._validation_payload(task)
        if not validation:
            return False

        test_execution = validation.get("test_execution")
        if not isinstance(test_execution, dict):
            return False
        if not test_execution.get("ran") or test_execution.get("returncode") in (None, 0):
            return False

        failure_origin = validation.get("pytest_failure_origin")
        if not isinstance(failure_origin, str) or not failure_origin:
            failure_origin = self._pytest_failure_origin(
                test_execution,
                validation.get("module_filename") if isinstance(validation.get("module_filename"), str) else None,
                validation.get("test_filename") if isinstance(validation.get("test_filename"), str) else None,
            )

        if failure_origin == "tests" and self._pytest_contract_overreach_signals(test_execution):
            return False

        if failure_origin == "code_under_test":
            return True

        if self._test_validation_has_blocking_issues(validation):
            return False

        return (
            failure_origin == "tests"
            and self._pytest_failure_is_semantic_assertion_mismatch(test_execution)
        )

    def _upstream_code_task_for_test_failure(self, project: ProjectState, task: Task) -> Optional[Task]:
        imported_code_task = self._imported_code_task_for_failed_test(project, task)
        preferred_dependency: Optional[Task] = None
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

    @staticmethod
    def _python_import_roots(raw_content: object) -> set[str]:
        if not isinstance(raw_content, str) or not raw_content.strip():
            return set()

        try:
            tree = ast.parse(raw_content)
        except SyntaxError:
            return set()

        import_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name:
                        import_roots.add(root_name)
                continue
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                module_name = (node.module or "").split(".", 1)[0]
                if module_name:
                    import_roots.add(module_name)
        return import_roots

    def _imported_code_task_for_failed_test(self, project: ProjectState, task: Task) -> Optional[Task]:
        import_roots = self._python_import_roots(
            self._failed_artifact_content(task, ArtifactType.TEST)
        )
        if not import_roots:
            return None

        preferred_task: Optional[Task] = None
        for existing_task in reversed(project.tasks):
            if AgentRegistry.normalize_key(existing_task.assigned_to) != "code_engineer":
                continue
            module_name = self._default_module_name_for_task(existing_task)
            if not module_name or module_name not in import_roots:
                continue
            if existing_task.repair_origin_task_id:
                return existing_task
            if preferred_task is None:
                preferred_task = existing_task
        return preferred_task

    def _build_code_repair_context_from_test_failure(
        self,
        code_task: Task,
        test_task: Task,
        cycle: Dict[str, Any],
    ) -> Dict[str, Any]:
        existing_tests = self._failed_artifact_content(test_task, ArtifactType.TEST)
        validation_summary = self._build_repair_validation_summary(
            test_task,
            FailureCategory.TEST_VALIDATION.value,
        )
        repair_context = {
            "cycle": cycle.get("cycle"),
            "failure_category": FailureCategory.CODE_VALIDATION.value,
            "failure_message": test_task.last_error or test_task.output or "",
            "failure_error_type": test_task.last_error_type,
            "repair_owner": "code_engineer",
            "original_assigned_to": code_task.assigned_to,
            "source_failure_task_id": test_task.id,
            "source_failure_category": test_task.last_error_category or FailureCategory.TEST_VALIDATION.value,
            "instruction": self._build_code_repair_instruction_from_test_failure(
                code_task,
                validation_summary,
                existing_tests,
            ),
            "validation_summary": validation_summary,
            "existing_tests": existing_tests,
            "failed_output": code_task.output or "",
            "failed_artifact_content": self._failed_artifact_content(code_task, ArtifactType.CODE),
            "provider_call": code_task.last_provider_call,
        }
        self._merge_prior_repair_context(code_task, repair_context)
        return repair_context

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
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        return repair_context.get("decomposition_mode") == "budget_compaction_planner"

    @staticmethod
    def _summary_limit_exceeded(validation_summary: object, label: str) -> bool:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return False
        pattern = rf"^- {re.escape(label)}:\s*(\d+)\s*/\s*(\d+)"
        for line in validation_summary.splitlines():
            match = re.match(pattern, line.strip(), re.IGNORECASE)
            if match is None:
                continue
            actual = int(match.group(1))
            limit = int(match.group(2))
            return actual > limit
        return False

    def _repair_requires_budget_decomposition(self, repair_context: Dict[str, Any]) -> bool:
        failure_category = repair_context.get("failure_category")
        if failure_category not in {
            FailureCategory.CODE_VALIDATION.value,
            FailureCategory.TEST_VALIDATION.value,
        }:
            return False
        validation_summary = repair_context.get("validation_summary")
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return False
        normalized = validation_summary.lower()
        if "completion diagnostics:" in normalized and "likely truncated" in normalized:
            return True
        if (
            failure_category == FailureCategory.CODE_VALIDATION.value
            and "completion diagnostics:" in normalized
            and "completion limit reached" in normalized
            and "missing required cli entrypoint" in normalized
        ):
            return True
        if self._summary_limit_exceeded(validation_summary, "Line count"):
            return True
        if failure_category == FailureCategory.TEST_VALIDATION.value:
            return any(
                self._summary_limit_exceeded(validation_summary, label)
                for label in ("Top-level test functions", "Fixture count")
            )
        return False

    def _build_budget_decomposition_instruction(self, failure_category: str) -> str:
        if failure_category == FailureCategory.TEST_VALIDATION.value:
            return (
                "Produce a compact budget decomposition brief for the next pytest repair. "
                "Distill only the minimum required imports, scenarios, helper removals, and rewrite order needed to keep the suite under budget while preserving the validated contract."
            )
        return (
            "Produce a compact budget decomposition brief for the next module repair. "
            "Distill only the minimum required public surface, behaviors, optional cuts, and rewrite order needed to keep the implementation under budget while preserving the validated contract."
        )

    def _build_budget_decomposition_task_context(
        self,
        task: Task,
        repair_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        failure_category = str(repair_context.get("failure_category") or FailureCategory.UNKNOWN.value)
        return {
            "cycle": repair_context.get("cycle"),
            "decomposition_mode": "budget_compaction_planner",
            "decomposition_target_task_id": task.id,
            "decomposition_target_agent": self._execution_agent_name(task),
            "decomposition_failure_category": failure_category,
            "failure_category": failure_category,
            "failure_message": repair_context.get("failure_message") or "",
            "instruction": self._build_budget_decomposition_instruction(failure_category),
            "validation_summary": repair_context.get("validation_summary") or "",
        }

    def _ensure_budget_decomposition_task(
        self,
        project: ProjectState,
        task: Task,
        repair_context: Dict[str, Any],
    ) -> Optional[Task]:
        decomposition_task_id = repair_context.get("budget_decomposition_plan_task_id")
        if isinstance(decomposition_task_id, str) and decomposition_task_id.strip():
            existing = project.get_task(decomposition_task_id)
            if existing is not None:
                return existing
        if not self._repair_requires_budget_decomposition(repair_context):
            return None
        decomposition_task = project._create_budget_decomposition_task(
            task.id,
            self._build_budget_decomposition_task_context(task, repair_context),
        )
        if decomposition_task is not None:
            repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
        return decomposition_task

    def _active_repair_cycle(self, project: ProjectState) -> Optional[Dict[str, Any]]:
        if not project.repair_history:
            return None
        current_cycle = project.repair_history[-1]
        if not isinstance(current_cycle, dict):
            return None
        return current_cycle

    def _build_repair_context(self, task: Task, cycle: Dict[str, Any]) -> Dict[str, Any]:
        failure_category = task.last_error_category or FailureCategory.UNKNOWN.value
        repair_context = {
            "cycle": cycle.get("cycle"),
            "failure_category": failure_category,
            "failure_message": task.last_error or task.output or "",
            "failure_error_type": task.last_error_type,
            "repair_owner": self._repair_owner_for_category(task, failure_category),
            "original_assigned_to": task.assigned_to,
            "instruction": self._build_repair_instruction(task, failure_category),
            "validation_summary": self._build_repair_validation_summary(task, failure_category),
            "failed_output": task.output or "",
            "failed_artifact_content": self._failed_artifact_content_for_category(task, failure_category),
            "provider_call": task.last_provider_call,
        }
        helper_surface_usages = self._test_repair_helper_surface_usages(task, failure_category)
        if helper_surface_usages:
            repair_context["helper_surface_usages"] = helper_surface_usages
            repair_context["helper_surface_symbols"] = self._normalized_helper_surface_symbols(
                helper_surface_usages
            )
        self._merge_prior_repair_context(task, repair_context)
        return repair_context

    def _merge_prior_repair_context(self, task: Task, repair_context: Dict[str, Any]) -> None:
        if not isinstance(repair_context, dict) or not task.repair_origin_task_id:
            return

        prior_repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        if not prior_repair_context:
            return

        current_instruction = str(repair_context.get("instruction") or "").strip()
        prior_instruction = str(prior_repair_context.get("instruction") or "").strip()
        if prior_instruction and prior_instruction not in current_instruction:
            merged_instruction_parts = [current_instruction] if current_instruction else []
            merged_instruction_parts.append(
                f"Also preserve and fully satisfy the prior unresolved repair objective from {task.repair_origin_task_id}: {prior_instruction}"
            )
            repair_context["instruction"] = " ".join(merged_instruction_parts).strip()

        current_validation_summary = str(repair_context.get("validation_summary") or "").strip()
        prior_validation_summary = str(prior_repair_context.get("validation_summary") or "").strip()
        if prior_validation_summary and prior_validation_summary not in current_validation_summary:
            merged_validation_parts = [current_validation_summary] if current_validation_summary else []
            merged_validation_parts.extend(
                [
                    "",
                    "Prior unresolved repair context:",
                    f"- Prior failure category: {prior_repair_context.get('failure_category') or FailureCategory.UNKNOWN.value}",
                ]
            )
            if prior_instruction:
                merged_validation_parts.append(f"- Prior repair objective: {prior_instruction}")
            merged_validation_parts.extend([
                "- Prior validation summary:",
                prior_validation_summary,
            ])
            repair_context["validation_summary"] = "\n".join(merged_validation_parts).strip()

    def _test_repair_helper_surface_usages(self, task: Task, failure_category: str) -> list[str]:
        if failure_category != FailureCategory.TEST_VALIDATION.value:
            return []

        validation = self._validation_payload(task)
        test_analysis = validation.get("test_analysis")
        if not isinstance(test_analysis, dict):
            return []

        raw_usages = test_analysis.get("helper_surface_usages")
        if not isinstance(raw_usages, list):
            return []

        return [item.strip() for item in raw_usages if isinstance(item, str) and item.strip()]

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

    @staticmethod
    def _string_literal_sequence(node: ast.AST | None) -> list[str]:
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return []

        values: list[str] = []
        for element in node.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                return []
            values.append(element.value)
        return values

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
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return True
        analysis = analyze_test_repair_surface(
            validation_summary,
            implementation_code,
            failed_artifact_content,
        )
        has_reusable_missing_imports = bool(analysis.undefined_available_module_symbols)
        has_required_evidence_runtime_issue = self._validation_summary_has_required_evidence_runtime_issue(
            validation_summary,
            failed_artifact_content,
            implementation_code,
        )
        if analysis.helper_alias_names:
            return False
        if has_required_evidence_runtime_issue and not has_reusable_missing_imports:
            return False
        if self._validation_summary_has_missing_datetime_import_issue(
            validation_summary,
            failed_artifact_content,
        ) and not has_reusable_missing_imports:
            return False
        return not any(
            self._validation_summary_symbols(validation_summary, label)
            for label in (
                "Tests without assertion-like checks",
                "Contract overreach signals",
            )
        )

    @staticmethod
    def _append_unique_mapping_value(mapping: dict[str, list[str]], key: str, value: str) -> None:
        values = mapping.setdefault(key, [])
        if value not in values:
            values.append(value)

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
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return []
        return list(dict.fromkeys(re.findall(r"::([A-Za-z_][A-Za-z0-9_]*)\b", validation_summary)))

    @staticmethod
    def _compare_mentions_invalid_literal(node: ast.Compare) -> bool:
        values = [node.left, *node.comparators]
        return any(
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and value.value.strip().lower() == "invalid"
            for value in values
        )

    @classmethod
    def _test_function_targets_invalid_path(
        cls,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        name_lower = node.name.lower()
        if any(token in name_lower for token in ("invalid", "validation", "reject", "error", "failure")):
            return True
        for child in ast.walk(node):
            if isinstance(child, ast.Compare) and cls._compare_mentions_invalid_literal(child):
                return True
        return False

    @staticmethod
    def _attribute_is_field_reference(node: ast.AST, field_name: str) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == field_name

    @classmethod
    def _is_len_of_field_reference(cls, node: ast.AST, field_name: str) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and len(node.args) == 1
            and cls._attribute_is_field_reference(node.args[0], field_name)
        )

    @classmethod
    def _test_requires_non_empty_result_field(
        cls,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        field_name: str,
    ) -> bool:
        for child in ast.walk(node):
            if not isinstance(child, ast.Assert):
                continue
            test_expr = child.test
            if cls._attribute_is_field_reference(test_expr, field_name):
                return True
            if not isinstance(test_expr, ast.Compare):
                continue
            if cls._is_len_of_field_reference(test_expr.left, field_name):
                return True
            if any(cls._is_len_of_field_reference(comparator, field_name) for comparator in test_expr.comparators):
                return True
            if cls._attribute_is_field_reference(test_expr.left, field_name) or any(
                cls._attribute_is_field_reference(comparator, field_name)
                for comparator in test_expr.comparators
            ):
                return True
        return False

    @staticmethod
    def _ast_is_empty_literal(node: ast.AST | None) -> bool:
        if node is None:
            return False
        if isinstance(node, ast.Constant):
            return node.value in {"", None}
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return len(node.elts) == 0
        if isinstance(node, ast.Dict):
            return len(node.keys) == 0
        if isinstance(node, ast.Call):
            if node.args or node.keywords:
                return False
            if isinstance(node.func, ast.Name) and node.func.id in {"str", "list", "tuple", "set", "dict"}:
                return True
        return False

    @classmethod
    def _class_field_uses_empty_default(
        cls,
        failed_artifact_content: object,
        class_name: str,
        field_name: str,
    ) -> bool:
        if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
            return False

        try:
            tree = ast.parse(failed_artifact_content)
        except SyntaxError:
            return False

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != class_name:
                continue
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign):
                    continue
                if isinstance(statement.target, ast.Name) and statement.target.id == field_name:
                    return cls._ast_is_empty_literal(statement.value)
            return False
        return False

    def _invalid_outcome_audit_return_details(
        self,
        failed_artifact_content: object,
        field_name: str,
    ) -> Optional[tuple[str, bool]]:
        if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
            return None

        try:
            tree = ast.parse(failed_artifact_content)
        except SyntaxError:
            return None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            outcome_keyword = next((keyword for keyword in call.keywords if keyword.arg == "outcome"), None)
            if outcome_keyword is None:
                continue
            if not (
                isinstance(outcome_keyword.value, ast.Constant)
                and isinstance(outcome_keyword.value.value, str)
                and outcome_keyword.value.value.strip().lower() == "invalid"
            ):
                continue

            rendered_call = ast.unparse(call).strip()
            field_keyword = next((keyword for keyword in call.keywords if keyword.arg == field_name), None)
            if field_keyword is not None and self._ast_is_empty_literal(field_keyword.value):
                return rendered_call, False

            class_name = callable_name(call)
            if field_keyword is None and class_name and self._class_field_uses_empty_default(
                failed_artifact_content,
                class_name,
                field_name,
            ):
                return rendered_call, True
        return None

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
        for existing_task in project.tasks:
            if existing_task.repair_origin_task_id != task_id:
                continue
            if existing_task.repair_attempt != cycle_number:
                continue
            return True
        return False

    def _queue_active_cycle_repair(self, project: ProjectState, task: Task) -> bool:
        if self.config.workflow_resume_policy != "resume_failed":
            return False
        if task.repair_origin_task_id is not None:
            return False
        current_cycle = self._active_repair_cycle(project)
        if current_cycle is None:
            return False
        cycle_number = int(current_cycle.get("cycle") or 0)
        if cycle_number <= 0:
            return False
        if self._has_repair_task_for_cycle(project, task.id, cycle_number):
            return False

        self._configure_repair_attempts(project, [task.id], current_cycle)
        repair_task_ids = self._repair_task_ids_for_cycle(project, [task.id])
        if not repair_task_ids:
            return False
        project.resume_failed_tasks(
            include_failed_tasks=False,
            failed_task_ids=[task.id],
            additional_task_ids=repair_task_ids,
        )
        project._record_execution_event(
            event="task_repair_chained",
            task_id=task.id,
            status=task.status,
            details={
                "repair_task_ids": repair_task_ids,
                "repair_cycle_count": project.repair_cycle_count,
            },
        )
        self._log_event(
            "info",
            "task_repair_chained",
            project_name=project.project_name,
            task_id=task.id,
            repair_task_ids=repair_task_ids,
            repair_cycle_count=project.repair_cycle_count,
        )
        return True

    def _failed_artifact_content_for_category(self, task: Task, failure_category: str) -> str:
        if failure_category == FailureCategory.CODE_VALIDATION.value:
            return self._failed_artifact_content(task, ArtifactType.CODE)
        if failure_category == FailureCategory.TEST_VALIDATION.value:
            return self._failed_artifact_content(task, ArtifactType.TEST)
        if failure_category == FailureCategory.DEPENDENCY_VALIDATION.value:
            return self._failed_artifact_content(task, ArtifactType.CONFIG)
        return self._failed_artifact_content(task)

    def _configure_repair_attempts(self, project: ProjectState, failed_task_ids: list[str], cycle: Dict[str, Any]) -> None:
        planned_task_ids: set[str] = set()
        for failed_task_id in failed_task_ids:
            task = project.get_task(failed_task_id)
            if task is None:
                continue

            if self._test_failure_requires_code_repair(task):
                code_task = self._upstream_code_task_for_test_failure(project, task)
                if code_task is not None and code_task.id not in planned_task_ids:
                    code_repair_context = self._build_code_repair_context_from_test_failure(code_task, task, cycle)
                    decomposition_task = self._ensure_budget_decomposition_task(project, code_task, code_repair_context)
                    if decomposition_task is not None:
                        code_repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
                    project._plan_task_repair(code_task.id, code_repair_context)
                    planned_task_ids.add(code_task.id)

            if task.id in planned_task_ids:
                continue

            repair_context = self._build_repair_context(task, cycle)
            decomposition_task = self._ensure_budget_decomposition_task(project, task, repair_context)
            if decomposition_task is not None:
                repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
            project._plan_task_repair(task.id, repair_context)
            planned_task_ids.add(task.id)

    def _repair_task_ids_for_cycle(self, project: ProjectState, failed_task_ids: list[str]) -> list[str]:
        repair_task_ids: list[str] = []
        for task_id in failed_task_ids:
            task = project.get_task(task_id)
            if task is None:
                continue

            code_repair_task: Optional[Task] = None
            if self._test_failure_requires_code_repair(task):
                code_task = self._upstream_code_task_for_test_failure(project, task)
                if code_task is not None:
                    code_repair_context = code_task.repair_context if isinstance(code_task.repair_context, dict) else {}
                    code_decomposition_task = self._ensure_budget_decomposition_task(project, code_task, code_repair_context)
                    if code_decomposition_task is not None and code_decomposition_task.id not in repair_task_ids:
                        repair_task_ids.append(code_decomposition_task.id)
                    code_repair_owner = self._execution_agent_name(code_task)
                    code_repair_task = project._create_repair_task(code_task.id, code_repair_owner, code_repair_context)
                    if code_repair_task is not None:
                        if code_repair_task.id not in task.dependencies:
                            task.dependencies.append(code_repair_task.id)
                        if code_decomposition_task is not None:
                            if code_decomposition_task.id not in code_repair_task.dependencies:
                                code_repair_task.dependencies.append(code_decomposition_task.id)
                            if isinstance(code_repair_task.repair_context, dict):
                                code_repair_task.repair_context["budget_decomposition_plan_task_id"] = code_decomposition_task.id
                        if code_repair_task.id not in repair_task_ids:
                            repair_task_ids.append(code_repair_task.id)

            repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
            decomposition_task = self._ensure_budget_decomposition_task(project, task, repair_context)
            if decomposition_task is not None and decomposition_task.id not in repair_task_ids:
                repair_task_ids.append(decomposition_task.id)
            repair_owner = self._execution_agent_name(task)
            repair_task = project._create_repair_task(task_id, repair_owner, repair_context)
            if repair_task is not None:
                if decomposition_task is not None:
                    if decomposition_task.id not in repair_task.dependencies:
                        repair_task.dependencies.append(decomposition_task.id)
                    if isinstance(repair_task.repair_context, dict):
                        repair_task.repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
                if code_repair_task is not None and code_repair_task.id not in repair_task.dependencies:
                    repair_task.dependencies.append(code_repair_task.id)
                repair_task_ids.append(repair_task.id)
        return repair_task_ids

    def _failed_task_ids_for_repair(self, project: ProjectState) -> list[str]:
        active_repair_origins = {
            task.repair_origin_task_id
            for task in project.tasks
            if task.repair_origin_task_id
            and task.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}
        }
        return [
            task.id
            for task in project.tasks
            if task.status == TaskStatus.FAILED.value
            and not task.repair_origin_task_id
            and task.id not in active_repair_origins
        ]

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
        if not isinstance(task_description, str) or not task_description.strip():
            return ""

        lines = [line.rstrip() for line in task_description.splitlines()]
        collecting = False
        anchor_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not collecting:
                if stripped == "Public contract anchor:":
                    collecting = True
                continue
            if not stripped:
                break
            if stripped.startswith("- "):
                anchor_lines.append(stripped)
                continue
            if line.startswith((" ", "\t")):
                anchor_lines.append(line.rstrip())
                continue
            break
        return "\n".join(anchor_lines)

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
        declared_packages: list[str] = []
        normalized_declared_packages: set[str] = set()
        provenance_violations: list[str] = []
        for raw_line in manifest_content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            package_name = extract_requirement_name(line)
            if not package_name:
                if is_provenance_unsafe_requirement(line):
                    provenance_violations.append(line)
                continue
            declared_packages.append(package_name)
            normalized_declared_packages.add(self._normalize_package_name(package_name))
            if is_provenance_unsafe_requirement(line):
                provenance_violations.append(line)

        required_imports = sorted(code_analysis.get("third_party_imports") or []) if isinstance(code_analysis, dict) else []
        normalized_required_imports = {self._normalize_import_name(module_name) for module_name in required_imports}
        missing_manifest_entries = [
            module_name
            for module_name in required_imports
            if self._normalize_import_name(module_name) not in normalized_declared_packages
        ]
        unused_manifest_entries = [
            package_name
            for package_name in declared_packages
            if self._normalize_package_name(package_name) not in normalized_required_imports
        ]
        return {
            "required_imports": required_imports,
            "declared_packages": declared_packages,
            "missing_manifest_entries": missing_manifest_entries,
            "unused_manifest_entries": unused_manifest_entries,
            "provenance_violations": provenance_violations,
            "is_valid": not missing_manifest_entries and not provenance_violations,
        }

    def _normalize_package_name(self, package_name: str) -> str:
        return package_name.strip().lower().replace("-", "_")

    def _normalize_import_name(self, module_name: str) -> str:
        normalized_name = module_name.strip().lower().replace("-", "_")
        package_name = _THIRD_PARTY_PACKAGE_ALIASES.get(normalized_name, normalized_name)
        return self._normalize_package_name(package_name)

    def _build_code_outline(self, raw_content: str) -> str:
        if not raw_content.strip():
            return ""
        pattern = re.compile(r"^(class\s+\w+.*|def\s+\w+.*|async\s+def\s+\w+.*)$")
        outline_lines = [line.strip() for line in raw_content.splitlines() if pattern.match(line.strip())]
        return "\n".join(outline_lines[:40])

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
        class_name = node.name
        for decorator in node.decorator_list:
            decorator_name = ""
            if isinstance(decorator, ast.Name):
                decorator_name = decorator.id
            elif isinstance(decorator, ast.Attribute):
                decorator_name = decorator.attr
            elif isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Name):
                    decorator_name = decorator.func.id
                elif isinstance(decorator.func, ast.Attribute):
                    decorator_name = decorator.func.attr
            if decorator_name == "dataclass":
                return f"{class_name} is defined as a @dataclass"
        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name == "BaseModel":
                return f"{class_name} is defined as a pydantic BaseModel"
            if base_name in ("TypedDict", "NamedTuple"):
                return f"{class_name} is defined as a {base_name}"
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "__init__":
                return f"{class_name} uses manual __init__"
        return ""

    @staticmethod
    def _extract_return_type_annotation(class_name: str | None, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Return a description of the return type annotation if present."""
        if node.name.startswith("_"):
            return ""
        if node.returns is None:
            return ""
        try:
            annotation = ast.unparse(node.returns)
        except Exception:
            return ""
        if not annotation or annotation in ("None",):
            return ""
        qualified_name = f"{class_name}.{node.name}" if class_name else node.name
        return f"{qualified_name} returns {annotation}"

    def _extract_constructor_storage_rule(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        first_parameter = self._first_user_parameter(node)
        if first_parameter is None:
            return ""

        source_name = first_parameter.arg
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            constructor_name = ast_name(child.func)
            if not constructor_name:
                continue
            for keyword in child.keywords:
                if keyword.arg != "data":
                    continue
                if isinstance(keyword.value, ast.Name) and keyword.value.id == source_name:
                    return f"{node.name} stores full {source_name} in returned {constructor_name}.data"
        return ""

    def _extract_score_derivation_rule(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    ) -> str:
        score_expression_node: Optional[ast.expr] = None

        for child in ast.walk(node):
            if not isinstance(child, ast.Assign) or len(child.targets) != 1:
                continue
            target = child.targets[0]
            if isinstance(target, ast.Name) and target.id == "score":
                score_expression_node = child.value
                break

        if score_expression_node is not None:
            if not self._function_returns_score_value(node):
                return ""
            score_expression = self._render_score_expression(
                self._expand_local_name_aliases(score_expression_node, node),
                function_map,
            )
            if not score_expression:
                return ""
            return f"{node.name} derives score from {score_expression}"

        if "score" not in node.name.lower():
            return ""

        return_expression = self._direct_return_expression(node)
        if return_expression is None:
            return ""
        score_expression = self._render_score_expression(
            self._expand_local_name_aliases(return_expression, node),
            function_map,
        )
        if not score_expression:
            return ""
        return f"{node.name} derives score from {score_expression}"

    def _function_returns_score_value(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and isinstance(child.value, ast.Name) and child.value.id == "score":
                return True
            if not isinstance(child, ast.Call):
                continue
            if any(
                keyword.arg == "score" and isinstance(keyword.value, ast.Name) and keyword.value.id == "score"
                for keyword in child.keywords
            ):
                return True
            if child.args and isinstance(child.args[0], ast.Name) and child.args[0].id == "score":
                return True
        return False

    def _render_score_expression(
        self,
        expression: ast.expr,
        function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    ) -> str:
        rendered_expression = self._inline_score_helper_expression(expression, function_map)
        try:
            return ast.unparse(rendered_expression).strip()
        except Exception:  # pragma: no cover - ast.unparse is available on supported versions
            return ast_name(rendered_expression)

    def _inline_score_helper_expression(
        self,
        expression: ast.expr,
        function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    ) -> ast.expr:
        if not isinstance(expression, ast.Call):
            return expression

        helper_name = self._call_expression_basename(expression.func)
        if not helper_name:
            return expression
        helper_node = function_map.get(helper_name)
        if helper_node is None:
            return expression

        helper_return_expression = self._direct_return_expression(helper_node)
        if helper_return_expression is None:
            return expression
        helper_return_expression = self._expand_local_name_aliases(helper_return_expression, helper_node)

        parameter_names = self._callable_parameter_names(helper_node)
        replacements: dict[str, ast.expr] = {}
        for parameter_name, argument in zip(parameter_names, expression.args):
            replacements[parameter_name] = argument
        for keyword in expression.keywords:
            if keyword.arg is None or keyword.arg not in parameter_names:
                continue
            replacements[keyword.arg] = keyword.value

        if not replacements:
            return expression

        replacer = AstNameReplacer(replacements)
        inlined_expression = replacer.visit(copy.deepcopy(helper_return_expression))
        if isinstance(inlined_expression, ast.expr):
            return ast.fix_missing_locations(inlined_expression)
        return expression

    def _expand_local_name_aliases(
        self,
        expression: ast.expr,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> ast.expr:
        replacements: dict[str, ast.expr] = {}
        for statement in node.body:
            if isinstance(statement, ast.Return):
                break
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            target = statement.targets[0]
            if not isinstance(target, ast.Name):
                continue
            expanded_value = AstNameReplacer(replacements).visit(copy.deepcopy(statement.value))
            if isinstance(expanded_value, ast.expr):
                replacements[target.id] = ast.fix_missing_locations(expanded_value)

        if not replacements:
            return expression

        expanded_expression = AstNameReplacer(replacements).visit(copy.deepcopy(expression))
        if isinstance(expanded_expression, ast.expr):
            return ast.fix_missing_locations(expanded_expression)
        return expression

    def _call_expression_basename(self, node: ast.AST) -> str:
        return call_expression_basename(node)

    def _direct_return_expression(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[ast.expr]:
        for statement in node.body:
            if isinstance(statement, ast.Return) and statement.value is not None:
                return statement.value
        return None

    def _callable_parameter_names(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        positional = [*node.args.posonlyargs, *node.args.args]
        if positional and positional[0].arg in {"self", "cls"}:
            positional = positional[1:]
        return [argument.arg for argument in positional]

    def _extract_sequence_input_rule(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        first_parameter = self._first_user_parameter(node)
        if first_parameter is None:
            return ""
        annotation = ast_name(first_parameter.annotation) if first_parameter.annotation is not None else ""
        if self._annotation_accepts_sequence_input(annotation):
            return f"{node.name} accepts sequence inputs via parameter `{first_parameter.arg}`"
        if self._parameter_is_iterated(node, first_parameter.arg):
            return f"{node.name} accepts sequence inputs via parameter `{first_parameter.arg}`"
        return ""

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
        """Infer example values for dict keys by analysing .get() defaults and comparisons.

        Returns ``{var_name: {key: example_literal}}`` where *example_literal*
        is a Python literal string such as ``"3"`` or ``"[]"``.
        """
        # Track alias assignments: ``d = request.details`` → d → details
        alias_map: Dict[str, str] = {}
        # key → example literal string
        raw: Dict[str, Dict[str, str]] = {}

        for node in ast.walk(tree):
            # Detect alias assignments
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                value = node.value
                if (
                    isinstance(target, ast.Name)
                    and isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                ):
                    alias_map[target.id] = value.attr

            # Pattern: name.get('key', default)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                var_name = node.func.value.id
                key_name = node.args[0].value
                if len(node.args) >= 2:
                    default_node = node.args[1]
                    example = _example_from_default(default_node)
                    if example is not None:
                        raw.setdefault(var_name, {})[key_name] = example

        # Resolve aliases
        merged: Dict[str, Dict[str, str]] = {}
        for var_name, key_examples in raw.items():
            real_name = alias_map.get(var_name, var_name)
            if real_name not in merged:
                merged[real_name] = {}
            merged[real_name].update(key_examples)
        return merged

    @staticmethod
    def _dict_accessed_keys_from_tree(tree: ast.AST) -> Dict[str, list[str]]:
        """Scan an AST for dict subscript/membership patterns and return keys by variable name.

        Detects patterns like ``name['key']``, ``name["key"]``,
        ``'key' in name``, and ``name.get('key')``.
        Also resolves aliases: if the implementation has
        ``d = request.details`` and accesses ``d['key']``, the keys are
        attributed to ``details`` (the attribute name) instead of ``d``.
        Returns a mapping from variable name to the list of string keys accessed.
        """
        keys_by_name: Dict[str, list[str]] = {}
        # Track alias assignments: ``alias = something.attr`` → alias → attr
        alias_map: Dict[str, str] = {}
        for node in ast.walk(tree):
            # Detect alias assignments like ``d = request.details``
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                value = node.value
                if (
                    isinstance(target, ast.Name)
                    and isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                ):
                    alias_map[target.id] = value.attr

            var_name: str = ""
            key_value: str = ""
            if isinstance(node, ast.Subscript):
                if isinstance(node.value, ast.Name) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    var_name = node.value.id
                    key_value = node.slice.value
            elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.In):
                if (
                    isinstance(node.left, ast.Constant)
                    and isinstance(node.left.value, str)
                    and len(node.comparators) == 1
                    and isinstance(node.comparators[0], ast.Name)
                ):
                    var_name = node.comparators[0].id
                    key_value = node.left.value
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "get" and isinstance(node.func.value, ast.Name):
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        var_name = node.func.value.id
                        key_value = node.args[0].value
            if var_name and key_value and key_value not in keys_by_name.get(var_name, []):
                keys_by_name.setdefault(var_name, []).append(key_value)

        # Resolve aliases: merge keys from aliased vars into the real
        # parameter name.  E.g. ``d = request.details; d['key']`` →
        # ``details: ['key']`` instead of ``d: ['key']``.
        merged: Dict[str, list[str]] = {}
        for var_name, keys in keys_by_name.items():
            real_name = alias_map.get(var_name, var_name)
            if real_name in merged:
                for k in keys:
                    if k not in merged[real_name]:
                        merged[real_name].append(k)
            else:
                merged[real_name] = list(keys)
        return merged

    def _extract_type_constraints(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> Dict[str, list[str]]:
        """Extract isinstance() type checks from if-guards and raise blocks."""
        constraints: Dict[str, list[str]] = {}
        for child in ast.walk(node):
            if not isinstance(child, (ast.If, ast.Assert)):
                continue
            isinstance_calls: list[ast.Call] = []
            test_node = child.test if isinstance(child, ast.If) else child.test
            self._collect_isinstance_calls(test_node, isinstance_calls)
            for call in isinstance_calls:
                if len(call.args) < 2:
                    continue
                field_name = self._isinstance_subject_name(call.args[0])
                if not field_name:
                    continue
                type_names = self._isinstance_type_names(call.args[1])
                if not type_names:
                    continue
                existing = constraints.get(field_name) or []
                for type_name in type_names:
                    if type_name not in existing:
                        existing.append(type_name)
                constraints[field_name] = existing
        return constraints

    def _collect_isinstance_calls(self, node: ast.AST, result: list[ast.Call]) -> None:
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "isinstance") or (
                isinstance(func, ast.Attribute) and func.attr == "isinstance"
            ):
                result.append(node)
                return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            self._collect_isinstance_calls(node.operand, result)
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                self._collect_isinstance_calls(value, result)

    def _isinstance_subject_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return node.attr
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            return node.slice.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return node.args[0].value
        return ""

    def _isinstance_type_names(self, node: ast.AST) -> list[str]:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            return [ast_name(node)]
        if isinstance(node, ast.Tuple):
            names: list[str] = []
            for elt in node.elts:
                if isinstance(elt, ast.Name):
                    names.append(elt.id)
                elif isinstance(elt, ast.Attribute):
                    names.append(ast_name(elt))
            return names
        return []

    def _extract_valid_literal_examples(self, raw_content: str) -> Dict[str, str]:
        """Extract sample dict/list literals from top-level constant assignments."""
        examples: Dict[str, str] = {}
        try:
            tree = ast.parse(raw_content)
        except SyntaxError:
            return examples
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            name_lower = target.id.lower()
            if not any(
                keyword in name_lower
                for keyword in ("default", "sample", "example", "valid", "template")
            ):
                continue
            if isinstance(node.value, (ast.Dict, ast.List)):
                try:
                    examples[target.id] = ast.unparse(node.value)
                except Exception:
                    pass
        return examples

    def _extract_batch_rule(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        validation_rules: Dict[str, list[str]],
    ) -> str:
        if "batch" not in node.name:
            return ""
        for child in ast.walk(node):
            if not isinstance(child, ast.For) or not isinstance(child.target, ast.Name):
                continue
            iter_var = child.target.id
            for nested in ast.walk(child):
                if not isinstance(nested, ast.Call):
                    continue
                callable_name = ""
                if isinstance(nested.func, ast.Name):
                    callable_name = nested.func.id
                elif isinstance(nested.func, ast.Attribute):  # pragma: no branch
                    callable_name = nested.func.attr
                if callable_name != "intake_request":
                    continue
                required_fields = validation_rules.get(callable_name) or []
                if len(nested.args) < 2:
                    continue
                payload_arg = nested.args[1]
                request_id_arg = nested.args[0]
                if isinstance(payload_arg, ast.Name) and payload_arg.id == iter_var:
                    batch_fields = list(required_fields)
                    if isinstance(request_id_arg, ast.Subscript) and isinstance(request_id_arg.slice, ast.Constant):
                        request_key = request_id_arg.slice.value
                        if isinstance(request_key, str):  # pragma: no branch
                            batch_fields = [request_key, *batch_fields]
                    if batch_fields:
                        return (
                            f"{node.name} expects each batch item to include: {', '.join(dict.fromkeys(batch_fields))}"
                        )
                if (
                    isinstance(payload_arg, ast.Subscript)
                    and isinstance(payload_arg.value, ast.Name)
                    and payload_arg.value.id == iter_var
                    and isinstance(payload_arg.slice, ast.Constant)
                    and isinstance(payload_arg.slice.value, str)
                ):
                    wrapper_key = payload_arg.slice.value
                    batch_fields = list(required_fields)
                    if isinstance(request_id_arg, ast.Subscript) and isinstance(request_id_arg.slice, ast.Constant):
                        request_key = request_id_arg.slice.value
                        if isinstance(request_key, str):  # pragma: no branch
                            return (
                                f"{node.name} expects each batch item to include key `{request_key}` and nested `{wrapper_key}` fields: {', '.join(batch_fields)}"
                            )
                    if batch_fields:
                        return (
                            f"{node.name} expects nested `{wrapper_key}` fields: {', '.join(batch_fields)}"
                        )
        return ""

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
        if payload_node is None:
            return ""
        resolved = self._resolve_bound_value(payload_node, bindings)
        field_value: Optional[ast.AST] = None
        if isinstance(resolved, ast.Dict):
            for key_node, value_node in zip(resolved.keys, resolved.values):
                if isinstance(key_node, ast.Constant) and key_node.value == field_name:
                    field_value = value_node
                    break
        elif isinstance(resolved, ast.Call):
            field_value = self._call_argument_value(resolved, field_name, class_map)
        if field_value is None:
            return ""
        field_value = self._resolve_bound_value(field_value, bindings)
        if isinstance(field_value, ast.Constant):
            return type(field_value.value).__name__
        if isinstance(field_value, ast.Dict):
            return "dict"
        if isinstance(field_value, ast.List):
            return "list"
        if isinstance(field_value, ast.Tuple):
            return "tuple"
        if isinstance(field_value, ast.Set):
            return "set"
        if isinstance(field_value, ast.Call):
            func_name = ast_name(field_value.func)
            if func_name in ("dict", "list", "set", "tuple", "str", "int", "float", "bool"):
                return func_name
        return ""

    def _parent_map(self, root: ast.AST) -> Dict[ast.AST, ast.AST]:
        return {
            child: parent
            for parent in ast.walk(root)
            for child in ast.iter_child_nodes(parent)
        }

    def _call_has_negative_expectation(self, node: ast.Call, parent_map: Dict[ast.AST, ast.AST]) -> bool:
        current: Optional[ast.AST] = node
        while current is not None:
            parent = parent_map.get(current)
            if parent is None:
                return False
            if isinstance(parent, ast.Assert) and self._assert_expects_false(parent, node):
                return True
            if isinstance(parent, (ast.With, ast.AsyncWith)) and self._with_uses_pytest_raises(parent):
                return True
            current = parent
        return False

    def _call_expects_invalid_outcome(
        self,
        test_node: ast.FunctionDef | ast.AsyncFunctionDef,
        call_node: ast.Call,
        parent_map: Dict[ast.AST, ast.AST],
    ) -> bool:
        result_name = self._assigned_name_for_call(call_node, parent_map)
        payload_arg = first_call_argument(call_node)
        payload_name = payload_arg.id if isinstance(payload_arg, ast.Name) else None

        for child in ast.walk(test_node):
            if not isinstance(child, ast.Assert) or getattr(child, "lineno", 0) <= getattr(call_node, "lineno", 0):
                continue
            if self._assert_expects_invalid_outcome(child.test, result_name, payload_name):
                return True
        return False

    def _assert_expects_invalid_outcome(
        self,
        node: ast.AST,
        result_name: Optional[str],
        payload_name: Optional[str],
    ) -> bool:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self._invalid_outcome_subject_matches(node.operand, result_name, payload_name)

        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            return False
        if not isinstance(node.ops[0], (ast.Eq, ast.Is)):
            return False

        left = node.left
        right = node.comparators[0]
        return (
            self._invalid_outcome_subject_matches(left, result_name, payload_name)
            and self._invalid_outcome_marker_matches(right)
        ) or (
            self._invalid_outcome_subject_matches(right, result_name, payload_name)
            and self._invalid_outcome_marker_matches(left)
        )

    def _invalid_outcome_subject_matches(
        self,
        node: ast.AST,
        result_name: Optional[str],
        payload_name: Optional[str],
    ) -> bool:
        if result_name and isinstance(node, ast.Name) and node.id == result_name:
            return True
        if (
            result_name is not None
            and isinstance(node, ast.Attribute)
            and node.attr in {"status", "state", "outcome", "result", "valid", "is_valid", "success", "accepted"}
            and isinstance(node.value, ast.Name)
            and node.value.id == result_name
        ):
            return True
        return (
            payload_name is not None
            and isinstance(node, ast.Attribute)
            and node.attr in {"status", "state", "outcome", "result", "valid", "is_valid", "success", "accepted"}
            and isinstance(node.value, ast.Name)
            and node.value.id == payload_name
        )

    def _invalid_outcome_marker_matches(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Constant):
            return False
        if node.value is False or node.value is None:
            return True
        return isinstance(node.value, str) and node.value.strip().lower() in {
            "invalid",
            "failed",
            "error",
            "pending",
            "rejected",
            "reject",
        }

    def _batch_call_allows_partial_invalid_items(
        self,
        test_node: ast.FunctionDef | ast.AsyncFunctionDef,
        call_node: ast.Call,
        bindings: Dict[str, ast.AST],
        parent_map: Dict[ast.AST, ast.AST],
    ) -> bool:
        batch_items = self._extract_literal_list_items(first_call_argument(call_node), bindings)
        if batch_items is None or len(batch_items) <= 1:
            return False

        result_name = self._assigned_name_for_call(call_node, parent_map)
        batch_size = len(batch_items)
        for child in ast.walk(test_node):
            if not isinstance(child, ast.Assert):
                continue
            if self._assert_limits_batch_result(child.test, result_name, call_node, batch_size):
                return True
        return False

    def _assigned_name_for_call(self, call_node: ast.Call, parent_map: Dict[ast.AST, ast.AST]) -> Optional[str]:
        parent = parent_map.get(call_node)
        if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
            return parent.targets[0].id
        if isinstance(parent, ast.AnnAssign) and isinstance(parent.target, ast.Name):
            return parent.target.id
        return None

    def _assert_limits_batch_result(
        self,
        test: ast.AST,
        result_name: Optional[str],
        call_node: ast.Call,
        batch_size: int,
    ) -> bool:
        if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
            return False
        op = test.ops[0]

        if self._len_call_matches_batch_result(test.left, result_name, call_node):
            compared_value = self._int_constant_value(test.comparators[0])
            return self._comparison_implies_partial_batch_result(op, compared_value, batch_size)

        if self._len_call_matches_batch_result(test.comparators[0], result_name, call_node):
            compared_value = self._int_constant_value(test.left)
            reversed_op = {
                ast.Lt: ast.Gt,
                ast.LtE: ast.GtE,
                ast.Gt: ast.Lt,
                ast.GtE: ast.LtE,
            }.get(type(op), type(op))
            return self._comparison_implies_partial_batch_result(reversed_op(), compared_value, batch_size)

        return False

    def _len_call_matches_batch_result(
        self,
        node: ast.AST,
        result_name: Optional[str],
        call_node: ast.Call,
    ) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if not isinstance(node.func, ast.Name) or node.func.id != "len" or len(node.args) != 1:
            return False
        candidate = node.args[0]
        if result_name is not None and isinstance(candidate, ast.Name) and candidate.id == result_name:
            return True
        return candidate is call_node

    def _int_constant_value(self, node: ast.AST) -> Optional[int]:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        return None

    def _comparison_implies_partial_batch_result(
        self,
        op: ast.cmpop,
        compared_value: Optional[int],
        batch_size: int,
    ) -> bool:
        if compared_value is None:
            return False
        if isinstance(op, ast.Eq):
            return compared_value < batch_size
        if isinstance(op, ast.Lt):
            return compared_value <= batch_size
        if isinstance(op, ast.LtE):
            return compared_value < batch_size
        return False

    @staticmethod
    def _test_name_suggests_validation_failure(test_name: str) -> bool:
        normalized_test_name = test_name.lower()
        return any(
            token in normalized_test_name
            for token in ("validation", "invalid", "reject", "failure", "error")
        )

    @staticmethod
    def _is_internal_score_state_target(rendered_target: str) -> bool:
        normalized_target = rendered_target.replace(" ", "").lower()
        if "score" not in normalized_target:
            return False
        if not ("." in normalized_target or "get_" in normalized_target):
            return False
        return bool(
            re.search(r"\.(?:get_)?(?:risk_)?scores?\b", normalized_target)
            or any(
                token in normalized_target
                for token in (
                    "score_record",
                    "score_records",
                    "score_cache",
                    "score_map",
                )
            )
        )

    @staticmethod
    def _behavior_contract_explicitly_limits_score_state_to_valid_requests(
        code_behavior_contract: str,
        rendered_target: str,
    ) -> bool:
        normalized_target = rendered_target.replace(" ", "").lower()
        if "risk_score" not in normalized_target:
            return False

        normalized_contract = code_behavior_contract.lower()
        if not re.search(r"risk[_ ]scores?", normalized_contract):
            return False

        return bool(
            re.search(r"risk[_ ]scores?.*\bonly\b.*\bvalid\b", normalized_contract)
            or re.search(r"appends?.*risk[_ ]scores?.*\bonly\b.*\bvalid\b", normalized_contract)
            or re.search(r"only\s+valid\s+requests?.*risk[_ ]scores?", normalized_contract)
            or re.search(r"valid\s+requests?.*append.*risk[_ ]scores?", normalized_contract)
        )

    def _find_contract_overreach_signals(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        bindings: Dict[str, ast.AST],
        code_behavior_contract: str = "",
    ) -> list[str]:
        visible_batch_sizes = self._visible_repeated_single_call_batch_sizes(node, bindings)
        signals: set[str] = set()
        largest_batch_size = max(visible_batch_sizes) if visible_batch_sizes else None
        for child in ast.walk(node):
            if not isinstance(child, ast.Assert):
                continue
            exact_len_assertion = self._exact_len_assertion(child.test)
            if exact_len_assertion is None:
                continue
            asserted_target, compared_value = exact_len_assertion
            normalized_target = asserted_target.replace(" ", "").lower()
            if largest_batch_size is not None and (
                "audit_log" in normalized_target or "audit_logs" in normalized_target
            ):
                if compared_value > largest_batch_size:
                    signals.add(
                        f"exact batch audit length {compared_value} exceeds visible batch size {largest_batch_size} in {node.name} (line {child.lineno})"
                    )

            if not self._test_name_suggests_validation_failure(node.name):
                continue
            if compared_value != 0:
                continue
            if not self._is_internal_score_state_target(asserted_target):
                continue
            if self._behavior_contract_explicitly_limits_score_state_to_valid_requests(
                code_behavior_contract,
                asserted_target,
            ):
                continue
            signals.add(
                "exact validation-failure score-state emptiness assertion on "
                f"'{asserted_target}' in {node.name} (line {child.lineno}) assumes rejected input leaves internal score state empty"
            )
        return sorted(signals)

    def _visible_repeated_single_call_batch_sizes(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        bindings: Dict[str, ast.AST],
    ) -> list[int]:
        batch_sizes: list[int] = []
        for child in ast.walk(node):
            if not isinstance(child, (ast.For, ast.AsyncFor)):
                continue
            batch_items = self._extract_literal_list_items(child.iter, bindings)
            if batch_items is None or len(batch_items) <= 1:
                continue
            if not self._loop_contains_non_batch_call(child):
                continue
            batch_sizes.append(len(batch_items))
        return batch_sizes

    def _loop_contains_non_batch_call(self, node: ast.AST) -> bool:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            called_name = callable_name(child)
            if not called_name or called_name == "len":
                continue
            if "batch" in called_name.lower():
                continue
            return True
        return False

    def _exact_len_assertion(self, node: ast.AST) -> Optional[tuple[str, int]]:
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            return None
        if not isinstance(node.ops[0], ast.Eq):
            return None

        left = node.left
        right = node.comparators[0]
        if self._is_len_call(left):
            compared_value = self._int_constant_value(right)
            if compared_value is None:
                return None
            left_call = cast(ast.Call, left)
            return render_expression(left_call.args[0]), compared_value
        if self._is_len_call(right):
            compared_value = self._int_constant_value(left)
            if compared_value is None:
                return None
            right_call = cast(ast.Call, right)
            return render_expression(right_call.args[0]), compared_value
        return None

    def _is_len_call(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and len(node.args) == 1
            and not node.keywords
        )

    def _assert_expects_false(self, node: ast.Assert, call_node: ast.Call) -> bool:
        test = node.test
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return self._ast_contains_node(test.operand, call_node)
        if not isinstance(test, ast.Compare):
            return False

        def false_constant(item: ast.AST) -> bool:
            return isinstance(item, ast.Constant) and item.value is False

        if self._ast_contains_node(test.left, call_node):
            return any(false_constant(comparator) for comparator in test.comparators) and any(
                isinstance(op, (ast.Is, ast.Eq)) for op in test.ops
            )
        if any(self._ast_contains_node(comparator, call_node) for comparator in test.comparators):
            return false_constant(test.left) and any(isinstance(op, (ast.Is, ast.Eq)) for op in test.ops)
        return False

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
        return len(node.args) + sum(1 for keyword in node.keywords if keyword.arg is not None)

    def _infer_expression_type(
        self,
        node: Optional[ast.AST],
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
        function_map: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        if isinstance(node, ast.Name):
            owner_type = local_types.get(node.id)
            return owner_type if owner_type in class_map else None
        if isinstance(node, ast.Call):
            return self._infer_call_result_type(node, local_types, class_map, function_map)
        return None

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
        if not isinstance(node, ast.Call):
            return None
        if isinstance(node.func, ast.Name):
            if node.func.id in class_map:
                return node.func.id
            function_info = function_map.get(node.func.id)
            if not isinstance(function_info, dict):
                return None
            return_annotation = function_info.get("return_annotation")
            return return_annotation if isinstance(return_annotation, str) and return_annotation in class_map else None
        if not isinstance(node.func, ast.Attribute):
            return None
        owner_type = self._infer_expression_type(node.func.value, local_types, class_map, function_map)
        if owner_type not in class_map:
            return None
        method_info = (class_map.get(owner_type, {}).get("method_signatures") or {}).get(node.func.attr)
        if not isinstance(method_info, dict):
            return None
        return_annotation = method_info.get("return_annotation")
        return return_annotation if isinstance(return_annotation, str) and return_annotation in class_map else None

    def _analyze_typed_test_member_usage(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
        function_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[list[str], list[str]]:
        invalid_member_refs: set[str] = set()
        call_arity_mismatches: set[str] = set()
        resolved_function_map = function_map or {}
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                owner_type = self._infer_expression_type(
                    child.func.value,
                    local_types,
                    class_map,
                    resolved_function_map,
                )
                if owner_type not in class_map:
                    continue
                method_info = (class_map.get(owner_type, {}).get("method_signatures") or {}).get(child.func.attr)
                if not isinstance(method_info, dict):
                    invalid_member_refs.add(f"{owner_type}.{child.func.attr} (line {child.lineno})")
                    continue
                actual_count = self._call_argument_count(child)
                min_expected = method_info.get("min_args")
                max_expected = method_info.get("max_args")
                if not isinstance(min_expected, int) or not isinstance(max_expected, int):
                    continue
                if min_expected <= actual_count <= max_expected:
                    continue
                if min_expected == max_expected:
                    call_arity_mismatches.add(
                        f"{owner_type}.{child.func.attr} expects {max_expected} args but test uses {actual_count} at line {child.lineno}"
                    )
                else:
                    call_arity_mismatches.add(
                        f"{owner_type}.{child.func.attr} expects {min_expected}-{max_expected} args but test uses {actual_count} at line {child.lineno}"
                    )
            elif isinstance(child, ast.Attribute):
                owner_type = self._infer_expression_type(
                    child.value,
                    local_types,
                    class_map,
                    resolved_function_map,
                )
                if owner_type not in class_map:
                    continue
                class_info = class_map.get(owner_type, {})
                allowed = set(class_info.get("attributes") or [])
                if not class_info.get("is_enum"):
                    allowed.update(class_info.get("fields") or [])
                allowed.update((class_info.get("method_signatures") or {}).keys())
                if child.attr not in allowed:
                    invalid_member_refs.add(f"{owner_type}.{child.attr} (line {child.lineno})")
        return sorted(invalid_member_refs), sorted(call_arity_mismatches)

    def _iter_relevant_test_body_nodes(self, node: ast.AST):
        yield from iter_relevant_test_body_nodes(node)

    def _bound_target_names(self, target: ast.AST) -> set[str]:
        return bound_target_names(target)

    def _payload_argument_for_validation(self, node: ast.Call, callable_name: str) -> Optional[ast.expr]:
        if callable_name == "validate_request":
            return first_call_argument(node)
        if len(node.args) >= 2:
            return node.args[1]
        if node.keywords:
            for keyword in node.keywords:
                if keyword.arg in {"data", "payload", "request", "item"}:
                    return keyword.value
        return first_call_argument(node)

    def _resolve_bound_value(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        *,
        max_depth: int = 3,
    ) -> Optional[ast.AST]:
        current = node
        depth = 0
        while isinstance(current, ast.Name) and depth < max_depth:
            current = bindings.get(current.id, current)
            depth += 1
        return current

    def _extract_literal_dict_keys(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        class_map: Optional[Dict[str, Any]] = None,
    ) -> Optional[set[str]]:
        resolved = self._resolve_bound_value(node, bindings)
        if isinstance(resolved, ast.Dict):
            keys = {
                key.value
                for key in resolved.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            return keys
        if (
            isinstance(resolved, ast.Subscript)
            and isinstance(resolved.slice, ast.Constant)
            and isinstance(resolved.slice.value, str)
        ):
            source = self._resolve_bound_value(resolved.value, bindings)
            if isinstance(source, ast.Dict):
                for key_node, value_node in zip(source.keys, source.values):
                    if (
                        isinstance(key_node, ast.Constant)
                        and key_node.value == resolved.slice.value
                    ):
                        return self._extract_literal_dict_keys(value_node, bindings, class_map)
        if isinstance(resolved, ast.Call):
            for candidate_name in ("data", "payload", "request", "item"):  # pragma: no branch
                candidate_value = self._call_argument_value(resolved, candidate_name, class_map or {})
                nested_keys = self._extract_literal_dict_keys(candidate_value, bindings, class_map)
                if nested_keys is not None:  # pragma: no branch
                    return nested_keys
        return None

    def _extract_literal_field_values(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        field_name: str,
        class_map: Dict[str, Any],
    ) -> list[str]:
        resolved = self._resolve_bound_value(node, bindings)
        if isinstance(resolved, ast.Dict):
            for key_node, value_node in zip(resolved.keys, resolved.values):
                if isinstance(key_node, ast.Constant) and key_node.value == field_name:
                    return self._extract_string_literals(value_node, bindings)
            return []
        if isinstance(resolved, ast.Call):  # pragma: no branch
            direct_value = self._call_argument_value(resolved, field_name, class_map)
            if direct_value is not None:
                return self._extract_string_literals(direct_value, bindings)
            nested_payload = self._call_argument_value(resolved, "data", class_map)
            if nested_payload is not None:
                return self._extract_literal_field_values(nested_payload, bindings, field_name, class_map)
        return []

    def _extract_string_literals(self, node: Optional[ast.AST], bindings: Dict[str, ast.AST]) -> list[str]:
        resolved = self._resolve_bound_value(node, bindings)
        if isinstance(resolved, ast.Constant) and isinstance(resolved.value, str):
            return [resolved.value]
        return []

    def _call_argument_value(
        self,
        node: ast.Call,
        argument_name: str,
        class_map: Dict[str, Any],
    ) -> Optional[ast.AST]:
        for keyword in node.keywords:
            if keyword.arg == argument_name:
                return keyword.value
        if not isinstance(node.func, ast.Name):
            return None
        constructor_params = class_map.get(node.func.id, {}).get("constructor_params") or []
        if argument_name not in constructor_params:
            return None
        argument_index = constructor_params.index(argument_name)
        if argument_index < len(node.args):
            return node.args[argument_index]
        return None

    def _extract_literal_list_items(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
    ) -> Optional[list[ast.AST]]:
        resolved = self._resolve_bound_value(node, bindings)
        if isinstance(resolved, ast.List):
            return list(resolved.elts)
        return None

    def _validate_batch_call(
        self,
        node: ast.Call,
        bindings: Dict[str, ast.AST],
        callable_name: str,
        batch_rule: Dict[str, Any],
    ) -> list[str]:
        violations: list[str] = []
        batch_arg = first_call_argument(node)
        batch_items = self._extract_literal_list_items(batch_arg, bindings)
        if batch_items is None:
            return violations

        required_fields = batch_rule.get("fields") or []
        request_key = batch_rule.get("request_key")
        wrapper_key = batch_rule.get("wrapper_key")
        for item in batch_items:
            resolved_item = self._resolve_bound_value(item, bindings)
            if not isinstance(resolved_item, ast.Dict):
                violations.append(
                    f"{callable_name} expects dict-like batch items, but test uses {type(resolved_item).__name__} at line {getattr(item, 'lineno', node.lineno)}"
                )
                continue

            item_keys = self._extract_literal_dict_keys(resolved_item, bindings) or set()
            if request_key and request_key not in item_keys:
                violations.append(
                    f"{callable_name} batch item missing required key: {request_key} at line {getattr(item, 'lineno', node.lineno)}"
                )
            if wrapper_key:
                nested_keys = self._extract_literal_dict_keys(
                    ast.Subscript(value=resolved_item, slice=ast.Constant(value=wrapper_key)),
                    bindings,
                )
                if nested_keys is None:
                    violations.append(
                        f"{callable_name} batch item missing nested payload `{wrapper_key}` at line {getattr(item, 'lineno', node.lineno)}"
                    )
                    continue
                missing_nested_fields = [field for field in required_fields if field not in nested_keys]
                if missing_nested_fields:
                    violations.append(
                        f"{callable_name} batch item nested `{wrapper_key}` missing required fields: {', '.join(missing_nested_fields)} at line {getattr(item, 'lineno', node.lineno)}"
                    )
                continue

            missing_fields = [field for field in required_fields if field not in item_keys]
            if missing_fields:
                violations.append(
                    f"{callable_name} batch item missing required fields: {', '.join(missing_fields)} at line {getattr(item, 'lineno', node.lineno)}"
                )

        return violations

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
        resumed_task_ids = project.resume_interrupted_tasks()
        failed_task_ids = self._failed_task_ids_for_repair(project)
        if self.config.workflow_resume_policy == "resume_failed":
            if failed_task_ids:
                failure_categories = {
                    task.last_error_category or FailureCategory.UNKNOWN.value
                    for task in project.tasks
                    if task.id in failed_task_ids
                }
                non_repairable_categories = {
                    category for category in failure_categories if not self._is_repairable_failure(category)
                }
                if non_repairable_categories:
                    resolved_category = (
                        next(iter(non_repairable_categories))
                        if len(non_repairable_categories) == 1
                        else FailureCategory.UNKNOWN.value
                    )
                    acceptance_evaluation = evaluate_workflow_acceptance(
                        project,
                        self.config.workflow_acceptance_policy,
                        _ZERO_BUDGET_FAILURE_CATEGORIES,
                    )
                    project.mark_workflow_finished(
                        "failed",
                        acceptance_policy=self.config.workflow_acceptance_policy,
                        terminal_outcome=WorkflowOutcome.FAILED.value,
                        failure_category=resolved_category,
                        acceptance_criteria_met=False,
                        acceptance_evaluation=acceptance_evaluation,
                    )
                    project.save()
                    raise AgentExecutionError(
                        "Workflow contains non-repairable failed tasks and cannot resume automatically"
                    )
                if not project.can_start_repair_cycle():
                    acceptance_evaluation = evaluate_workflow_acceptance(
                        project,
                        self.config.workflow_acceptance_policy,
                        _ZERO_BUDGET_FAILURE_CATEGORIES,
                    )
                    project.mark_workflow_finished(
                        "failed",
                        acceptance_policy=self.config.workflow_acceptance_policy,
                        terminal_outcome=WorkflowOutcome.FAILED.value,
                        failure_category=FailureCategory.REPAIR_BUDGET_EXHAUSTED.value,
                        acceptance_criteria_met=False,
                        acceptance_evaluation=acceptance_evaluation,
                    )
                    project.save()
                    self._log_event(
                        "error",
                        "workflow_repair_budget_exhausted",
                        project_name=project.project_name,
                        failed_task_ids=list(failed_task_ids),
                        repair_cycle_count=project.repair_cycle_count,
                        repair_max_cycles=project.repair_max_cycles,
                    )
                    raise AgentExecutionError(
                        "Workflow repair budget exhausted before resuming failed tasks"
                    )
                project.start_repair_cycle(
                    reason="resume_failed_tasks",
                    failure_category=(
                        next(iter(failure_categories)) if len(failure_categories) == 1 else FailureCategory.UNKNOWN.value
                    ),
                    failed_task_ids=failed_task_ids,
                )
                self._configure_repair_attempts(project, failed_task_ids, project.repair_history[-1])
                repair_task_ids = self._repair_task_ids_for_cycle(project, failed_task_ids)
                resumed_task_ids.extend(repair_task_ids)
                resumed_task_ids.extend(
                    project.resume_failed_tasks(
                        include_failed_tasks=False,
                        failed_task_ids=failed_task_ids,
                        additional_task_ids=repair_task_ids,
                    )
                )
        if resumed_task_ids:
            self._log_event("info", "workflow_resumed", project_name=project.project_name, task_ids=list(resumed_task_ids))
            project.save()
        if self._exit_if_workflow_cancelled(project):
            return
        if self._exit_if_workflow_paused(project):
            return
        if project.workflow_started_at is None or project.phase != "execution":
            project.mark_workflow_running(
                acceptance_policy=self.config.workflow_acceptance_policy,
                repair_max_cycles=self.config.workflow_max_repair_cycles,
            )
            self._log_event("info", "workflow_started", project_name=project.project_name, phase=project.phase)
        while True:
            if self._exit_if_workflow_cancelled(project):
                return
            pending = project.pending_tasks()
            if not pending:
                acceptance_evaluation = evaluate_workflow_acceptance(
                    project,
                    self.config.workflow_acceptance_policy,
                    _ZERO_BUDGET_FAILURE_CATEGORIES,
                )
                acceptance_criteria_met = bool(acceptance_evaluation["accepted"])
                project.mark_workflow_finished(
                    "completed",
                    acceptance_policy=self.config.workflow_acceptance_policy,
                    terminal_outcome=(
                        WorkflowOutcome.COMPLETED.value
                        if acceptance_criteria_met
                        else WorkflowOutcome.DEGRADED.value
                    ),
                    acceptance_criteria_met=acceptance_criteria_met,
                    acceptance_evaluation=acceptance_evaluation,
                )
                project.save()
                self._log_event("info", "workflow_completed", project_name=project.project_name, phase=project.phase)
                break
            if self._exit_if_workflow_cancelled(project):
                return
            if self._exit_if_workflow_paused(project):
                return
            try:
                runnable = project.runnable_tasks()
            except WorkflowDefinitionError:
                project.mark_workflow_finished(
                    "failed",
                    acceptance_policy=self.config.workflow_acceptance_policy,
                    terminal_outcome=WorkflowOutcome.FAILED.value,
                    failure_category=FailureCategory.WORKFLOW_DEFINITION.value,
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
            if not runnable:
                blocked_task_ids = ", ".join(task.id for task in project.blocked_tasks())
                project.mark_workflow_finished(
                    "failed",
                    acceptance_policy=self.config.workflow_acceptance_policy,
                    terminal_outcome=WorkflowOutcome.FAILED.value,
                    failure_category=FailureCategory.WORKFLOW_BLOCKED.value,
                    acceptance_criteria_met=False,
                    acceptance_evaluation=evaluate_workflow_acceptance(
                        project,
                        self.config.workflow_acceptance_policy,
                        _ZERO_BUDGET_FAILURE_CATEGORIES,
                    ),
                )
                project.save()
                self._log_event(
                    "error",
                    "workflow_blocked",
                    project_name=project.project_name,
                    phase=project.phase,
                    blocked_task_ids=blocked_task_ids,
                )
                raise AgentExecutionError(
                    f"Workflow is blocked because pending tasks have unsatisfied dependencies: {blocked_task_ids}"
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
                            skipped = project.skip_dependent_tasks(
                                task.id,
                                f"Skipped because dependency '{task.id}' failed",
                            )
                            self._emit_workflow_progress(project, task=task)
                            project.save()
                            if skipped:
                                self._log_event(
                                    "warning",
                                    "dependent_tasks_skipped",
                                    project_name=project.project_name,
                                    task_id=task.id,
                                    skipped_task_ids=list(skipped),
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
                        skipped = project.skip_dependent_tasks(
                            task.id,
                            f"Skipped because dependency '{task.id}' failed",
                        )
                        self._emit_workflow_progress(project, task=task)
                        project.save()
                        if skipped:
                            self._log_event(
                                "warning",
                                "dependent_tasks_skipped",
                                project_name=project.project_name,
                                task_id=task.id,
                                skipped_task_ids=list(skipped),
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
