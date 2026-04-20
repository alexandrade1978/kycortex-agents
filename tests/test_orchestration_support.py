import ast
import os
import re
import stat
from types import SimpleNamespace

import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, WorkflowDefinitionError
from kycortex_agents.orchestration.agent_runtime import build_agent_input, execute_agent
from kycortex_agents.orchestration.ast_tools import (
	AstNameReplacer,
	ast_name,
	attribute_chain,
	callable_name,
	expression_root_name,
	first_call_argument,
	is_pytest_fixture,
	python_import_roots,
	render_expression,
)
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.artifacts import failed_artifact_content
from kycortex_agents.orchestration.dependency_analysis import (
	analyze_dependency_manifest,
	normalize_import_name,
	normalize_package_name,
)
from kycortex_agents.orchestration.context_building import (
	apply_task_public_contract_context,
	apply_completed_task_artifact_contexts,
	apply_completed_tasks_to_context,
	apply_completed_task_output_to_context,
	apply_repair_context_to_context,
	build_agent_view_artifacts,
	build_agent_view_decisions,
	build_agent_view_runtime,
	build_agent_view_task_results,
	build_task_context_runtime,
	build_task_context_base,
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
	parse_behavior_contract,
	build_code_public_api,
	build_code_test_targets,
	build_code_outline,
	callable_parameter_names,
	collect_isinstance_calls,
	comparison_required_field,
	call_signature_details,
	call_expression_basename,
	constructor_param_matches_class,
	dataclass_field_has_default,
	dataclass_field_is_init_enabled,
	dict_accessed_keys_from_tree,
	direct_return_expression,
	entrypoint_symbol_names,
	example_from_default,
	exposed_test_class_names,
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
	preferred_test_class_names,
	render_score_expression,
	self_assigned_attributes,
)
from kycortex_agents.orchestration.test_ast_analysis import (
	analyze_test_module,
	analyze_test_behavior_contracts,
	analyze_test_type_mismatches,
	auto_fix_test_type_mismatches,
)
from kycortex_agents.orchestration.private_files import (
	harden_private_directory_permissions,
	harden_private_file_permissions,
)
from kycortex_agents.orchestration.repair_analysis import (
	artifact_type_for_failure_category,
	ast_is_empty_literal,
	attribute_is_field_reference,
	class_field_uses_empty_default,
	compare_mentions_invalid_literal,
	failing_pytest_test_names,
	failed_artifact_content_for_category,
	duplicate_constructor_explicit_rewrite_hint,
	invalid_outcome_audit_return_details,
	invalid_outcome_missing_audit_trail_details,
	is_len_of_field_reference,
	missing_import_nameerror_details,
	missing_object_attribute_details,
	nested_payload_wrapper_field_validation_details,
	plain_class_field_default_factory_details,
	render_name_list,
	required_field_list_from_failed_artifact,
	suggest_declared_attribute_replacement,
	test_function_targets_invalid_path,
	test_requires_non_empty_result_field,
)
from kycortex_agents.orchestration.repair_code_validation import (
	build_code_validation_repair_lines,
)
from kycortex_agents.orchestration.repair_focus import (
	build_repair_focus_lines,
)
from kycortex_agents.orchestration.repair_test_validation import (
	build_test_validation_repair_lines,
)
from kycortex_agents.orchestration.repair_signals import (
	content_has_incomplete_required_evidence_payload,
	content_has_matching_datetime_import,
	implementation_prefers_direct_datetime_import,
	implementation_required_evidence_items,
	validation_summary_has_missing_datetime_import_issue,
	validation_summary_has_required_evidence_runtime_issue,
)
from kycortex_agents.orchestration.repair_test_analysis import (
	analyze_test_repair_surface,
	failed_test_requires_code_repair,
	failed_test_requires_code_repair_runtime,
	imported_code_task_for_failed_test,
	is_helper_alias_like_name,
	module_defined_symbol_names,
	normalized_helper_surface_symbols,
	previous_valid_test_surface,
	qa_repair_should_reuse_failed_test_artifact,
	helper_surface_usages_for_test_repair,
	helper_surface_usages_for_test_repair_runtime,
	upstream_code_task_for_test_failure,
	validation_summary_helper_alias_names,
)
from kycortex_agents.orchestration.repair_test_runtime import (
	build_runtime_only_test_repair_lines,
)
from kycortex_agents.orchestration.repair_test_structure import (
	build_structural_test_repair_lines,
)
from kycortex_agents.orchestration.repair_instructions import (
	build_code_repair_instruction_from_test_failure,
	build_code_repair_instruction_from_test_failure_runtime,
	build_repair_instruction,
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
from kycortex_agents.orchestration.sandbox_runtime import (
	build_generated_test_env,
	build_sandbox_preexec_fn,
	looks_like_secret_env_var,
	sanitize_generated_filename,
)
from kycortex_agents.orchestration.sandbox_templates import (
	render_generated_import_runner,
	render_generated_test_runner,
	render_sandbox_sitecustomize,
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
	loop_contains_non_batch_call,
	len_call_matches_batch_result,
	parent_map,
	payload_argument_for_validation,
	patched_target_name_from_call,
	resolve_bound_value,
	name_suggests_validation_failure,
	validate_batch_call,
	visible_repeated_single_call_batch_sizes,
	with_uses_pytest_assertion_context,
	with_uses_pytest_raises,
)
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
from kycortex_agents.orchestration.validation_reporting import (
	build_code_validation_summary,
	build_dependency_validation_summary,
	build_repair_validation_summary,
	build_test_validation_summary,
	completion_diagnostics_from_provider_call,
	completion_diagnostics_summary,
	completion_validation_issue,
	looks_structurally_truncated,
)
from kycortex_agents.orchestration.validation_runtime import (
	ValidationRuntimeInput,
	ValidationRuntimeState,
	build_test_validation_runtime_input,
	build_test_validation_runtime_state,
	provider_call_metadata,
	redact_validation_execution_result,
	record_code_validation_metadata,
	record_test_validation_metadata,
	replace_test_output_content,
	sanitize_output_provider_call_metadata,
	summarize_pytest_output,
	validate_code_output_runtime,
	validate_dependency_output_runtime,
	validate_test_output_runtime,
)
from kycortex_agents.orchestration.validation_analysis import (
	collect_code_validation_issues,
	collect_test_validation_issues,
	pytest_contract_overreach_signals,
	pytest_failure_details,
	pytest_failure_is_semantic_assertion_mismatch,
	pytest_failure_origin,
	validation_error_message_for_test_result,
	validation_has_blocking_issues,
	validation_has_only_warnings,
	validation_has_static_issues,
)
from kycortex_agents.orchestration.workflow_control import (
	active_repair_cycle,
	build_code_repair_context_from_test_failure,
	configure_repair_attempts,
	build_repair_context,
	continue_workflow_after_task_failure,
	dispatch_task_failure,
	emit_workflow_progress_and_save,
	ensure_workflow_running,
	ensure_budget_decomposition_task,
	execute_runnable_frontier,
	execute_workflow_runtime,
	execute_workflow_loop,
	execute_runnable_tasks,
	execute_workflow_task,
	prepare_workflow_execution,
	run_active_workflow,
	fail_workflow_after_task_failure,
	fail_workflow_for_definition_error,
	fail_workflow_when_blocked,
	failed_task_ids_for_repair,
	finish_workflow_if_no_pending_tasks,
	has_repair_task_for_cycle,
	merge_prior_repair_context,
	privacy_safe_log_fields,
	queue_active_cycle_repair,
	repair_task_ids_for_cycle,
	resume_failed_workflow_tasks,
	resume_failed_tasks_with_repair_cycle,
	resume_workflow_tasks,
	task_id_collection_count,
	task_id_count_log_field_name,
	validate_agent_resolution,
)
from kycortex_agents.orchestration.workflow_acceptance import (
	evaluate_workflow_acceptance,
	observed_failure_categories,
	task_acceptance_lists,
)
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import AgentInput, AgentOutput, AgentView, AgentViewArtifactRecord, AgentViewDecisionRecord, ArtifactRecord, ArtifactType, ExecutionSandboxPolicy, FailureCategory, TaskResult, TaskStatus, WorkflowOutcome


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")
def test_harden_private_file_permissions_sets_mode_600(tmp_path):
	artifact_path = tmp_path / "artifact.txt"
	artifact_path.write_text("secret", encoding="utf-8")
	artifact_path.chmod(0o644)

	harden_private_file_permissions(artifact_path)

	assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600


def test_failed_artifact_content_prefers_matching_artifact_then_raw_content_directly():
	assert failed_artifact_content(
		"fallback",
		{
			"raw_content": "raw fallback",
			"artifacts": [
				{"artifact_type": ArtifactType.TEST.value, "content": "def test_ok():\n    assert True"},
				{"artifact_type": ArtifactType.CODE.value, "content": "def ok():\n    return 1"},
			],
		},
		ArtifactType.CODE,
	) == "def ok():\n    return 1"
	assert failed_artifact_content(
		"fallback",
		{
			"raw_content": "raw fallback",
			"artifacts": ["invalid", {"artifact_type": ArtifactType.CODE.value, "content": "   "}],
		},
		ArtifactType.CODE,
	) == "raw fallback"
	assert failed_artifact_content("fallback", "not-a-dict", ArtifactType.CODE) == "fallback"


def test_apply_repair_context_to_context_populates_code_repair_fields():
	ctx = {"code": "def current():\n    return 1"}
	repair_context = {
		"validation_summary": "code summary",
		"existing_tests": "def test_existing():\n    assert True",
		"failed_artifact_content": "def repaired():\n    return 2",
	}

	apply_repair_context_to_context(
		ctx,
		repair_context,
		"code_engineer",
		"budget-plan",
		agent_visible_repair_context=lambda current_repair_context, execution_agent_name: {
			"owner": execution_agent_name,
			"summary": current_repair_context["validation_summary"],
		},
		normalized_execution_agent="code_engineer",
		normalized_helper_surface_symbols=lambda raw_values: [str(item).strip() for item in raw_values if str(item).strip()],
		qa_repair_should_reuse_failed_test_artifact=lambda *_args: False,
	)

	assert ctx["repair_context"] == {"owner": "code_engineer", "summary": "code summary"}
	assert ctx["budget_decomposition_plan_task_id"] == "budget-plan"
	assert ctx["repair_validation_summary"] == "code summary"
	assert ctx["existing_code"] == "def repaired():\n    return 2"
	assert ctx["existing_tests"] == "def test_existing():\n    assert True"


def test_build_task_context_runtime_builds_redacted_context_directly():
	task = SimpleNamespace(
		id="code",
		title="Implement",
		description="Public contract: return a dict",
		assigned_to="code_engineer",
		repair_context={
			"validation_summary": "repair summary",
			"failed_artifact_content": "def repaired():\n    return 2",
		},
	)
	completed_task = SimpleNamespace(id="done_task", status="done", assigned_to="code_engineer", title="Implement done")
	project = SimpleNamespace(
		goal="ship",
		project_name="demo",
		phase="build",
		tasks=[completed_task],
		snapshot=lambda: {"workflow_status": "running"},
	)

	ctx = build_task_context_runtime(
		task,
		project,
		provider_max_tokens=4096,
		build_agent_view=lambda current_task, current_project, snapshot: AgentView(
			project_name="demo",
			goal="ship",
			decisions=["d1"],
			artifacts=["a1"],
		),
		task_dependency_closure_ids=lambda current_task, current_project: {"done_task"},
		execution_agent_name=lambda current_task: "code_engineer",
		planned_module_context=lambda current_project, visible_task_ids, current_task: {
			"planned_module_name": "code_implementation",
			"planned_module_filename": "code_implementation.py",
		},
		task_public_contract_anchor=lambda description: "anchor",
		should_compact_architecture_context=lambda current_task, anchor: False,
		compact_architecture_context=lambda current_task, anchor: "compact architecture",
		task_context_output=lambda current_task: "existing output",
		is_budget_decomposition_planner=lambda current_task: False,
		semantic_output_key=lambda assigned_to, title: "code" if assigned_to == "code_engineer" else None,
		normalize_assigned_to=lambda assigned_to: assigned_to,
		code_artifact_context=lambda current_task, current_project: {"code_artifact": current_task.id},
		dependency_artifact_context=lambda current_task, current_ctx: {"dependency_artifact": current_task.id},
		test_artifact_context=lambda current_task, current_ctx: {"test_artifact": current_task.id},
		agent_visible_repair_context=lambda repair_context, execution_agent_name: {"owner": execution_agent_name},
		normalized_helper_surface_symbols=lambda value: [],
		qa_repair_should_reuse_failed_test_artifact=lambda *_args: False,
		redact_sensitive_data=lambda value: {**value, "redacted": True},
	)

	assert ctx["goal"] == "ship"
	assert ctx["task"]["execution_agent"] == "code_engineer"
	assert ctx["task_public_contract_anchor"] == "anchor"
	assert ctx["completed_tasks"] == {"done_task": "existing output"}
	assert ctx["code_artifact"] == "done_task"
	assert ctx["repair_context"] == {"owner": "code_engineer"}
	assert ctx["repair_validation_summary"] == "repair summary"
	assert ctx["existing_code"] == "def repaired():\n    return 2"
	assert ctx["redacted"] is True


def test_build_agent_view_task_results_filters_visible_tasks_directly():
	visible_task = TaskResult(task_id="code", status="done", agent_name="code_engineer")
	visible_task.failure = SimpleNamespace(category="VALIDATION")
	hidden_task = TaskResult(task_id="hidden", status="done", agent_name="qa_tester")

	filtered = build_agent_view_task_results(
		{"code": visible_task, "hidden": hidden_task},
		{"code"},
	)

	assert list(filtered) == ["code"]
	assert filtered["code"].failure_category == "VALIDATION"


def test_build_agent_view_decisions_accepts_dicts_and_objects_directly():
	decisions = build_agent_view_decisions(
		[
			{"topic": "api", "decision": "keep", "rationale": "stable", "created_at": "2026-04-20"},
			SimpleNamespace(topic="tests", decision="add", rationale="coverage", created_at=None),
			{"topic": "bad", "decision": 1, "rationale": "ignored"},
		]
	)

	assert [decision.topic for decision in decisions] == ["api", "tests"]
	assert decisions[1].created_at == ""


def test_build_agent_view_artifacts_filters_visibility_and_dependency_content_directly():
	artifacts = build_agent_view_artifacts(
		[
			{
				"name": "visible.py",
				"artifact_type": ArtifactType.CODE.value,
				"content": "print('visible')",
				"created_at": "2026-04-20",
				"metadata": {"task_id": "code"},
			},
			{
				"name": "hidden.py",
				"artifact_type": ArtifactType.CODE.value,
				"content": "print('hidden')",
				"metadata": {"task_id": "hidden"},
			},
		],
		{"code"},
		{"code"},
	)

	assert len(artifacts) == 1
	assert artifacts[0].name == "visible.py"
	assert artifacts[0].content == "print('visible')"


def test_build_agent_view_runtime_builds_filtered_agent_view_directly():
	snapshot = SimpleNamespace(
		project_name="demo",
		goal="ship",
		workflow_status=WorkflowOutcome.COMPLETED,
		phase="build",
		acceptance_evaluation={
			"policy": "strict",
			"terminal_outcome": "completed",
			"failure_category": "VALIDATION",
			"accepted": True,
		},
		task_results={"code": TaskResult(task_id="code", status="done", agent_name="code_engineer")},
		decisions=[{"topic": "api", "decision": "keep", "rationale": "stable", "created_at": "2026-04-20"}],
		artifacts=[{"name": "visible.py", "artifact_type": ArtifactType.CODE.value, "content": "x", "metadata": {"task_id": "code"}}],
	)

	agent_view = build_agent_view_runtime(
		SimpleNamespace(id="code"),
		SimpleNamespace(),
		snapshot,
		task_dependency_closure_ids=lambda task, project: {"code"},
		direct_dependency_ids=lambda task: {"code"},
	)

	assert agent_view.project_name == "demo"
	assert agent_view.acceptance_policy == "strict"
	assert agent_view.acceptance_criteria_met is True
	assert list(agent_view.task_results) == ["code"]
	assert agent_view.artifacts[0].content == "x"


def test_task_dependency_closure_ids_includes_repair_origin_and_budget_plan_directly():
	task = SimpleNamespace(
		id="repair",
		dependencies=["dep_a"],
		repair_origin_task_id="origin",
		repair_context={"budget_decomposition_plan_task_id": "plan"},
	)
	project = SimpleNamespace(
		get_task=lambda task_id: {
			"dep_a": SimpleNamespace(dependencies=["dep_b"]),
			"dep_b": SimpleNamespace(dependencies=[]),
			"origin": SimpleNamespace(dependencies=[]),
			"plan": SimpleNamespace(dependencies=[]),
		}.get(task_id)
	)

	assert task_dependency_closure_ids(task, project) == {"repair", "dep_a", "dep_b", "origin", "plan"}


def test_direct_dependency_ids_includes_repair_origin_and_budget_plan_directly():
	task = SimpleNamespace(
		dependencies=["dep_a"],
		repair_origin_task_id="origin",
		repair_context={"budget_decomposition_plan_task_id": "plan"},
	)

	assert direct_dependency_ids(task) == {"dep_a", "origin", "plan"}


def test_validation_payload_reads_nested_validation_metadata_directly():
	task = SimpleNamespace(output_payload={"metadata": {"validation": {"result": "ok"}}})

	assert validation_payload(task) == {"result": "ok"}


def test_task_context_output_prefers_output_then_raw_content_directly():
	assert task_context_output(SimpleNamespace(output="rendered", output_payload={})) == "rendered"
	assert task_context_output(SimpleNamespace(output="", output_payload={"raw_content": "raw fallback"})) == "raw fallback"


def test_build_repair_validation_summary_dispatches_by_failure_category_directly():
	task = SimpleNamespace(last_error="fallback error", output="fallback output")

	code_summary = build_repair_validation_summary(
		task,
		FailureCategory.CODE_VALIDATION.value,
		{
			"code_analysis": {"syntax_ok": False, "syntax_error": "bad syntax", "line_count": 1, "third_party_imports": []},
			"completion_diagnostics": {"hit_token_limit": False},
		},
	)
	test_summary = build_repair_validation_summary(
		task,
		FailureCategory.TEST_VALIDATION.value,
		{
			"test_analysis": {"syntax_ok": False, "syntax_error": "bad test", "test_count": 0, "assertion_count": 0, "fixture_count": 0, "issues": []},
			"test_execution": None,
		},
	)
	dependency_summary = build_repair_validation_summary(
		task,
		FailureCategory.DEPENDENCY_VALIDATION.value,
		{"dependency_analysis": {"is_valid": False, "missing_manifest_entries": ["numpy"], "provenance_violations": []}},
	)
	unknown_summary = build_repair_validation_summary(task, FailureCategory.UNKNOWN.value, {})

	assert "bad syntax" in code_summary
	assert "bad test" in test_summary
	assert "numpy" in dependency_summary
	assert unknown_summary == "fallback error"


def test_build_task_context_base_applies_planned_module_aliases_directly():
	task = SimpleNamespace(id="code", title="Implement", description="desc", assigned_to="code_engineer")
	project = SimpleNamespace(goal="ship", project_name="demo", phase="build")
	snapshot = {"decisions": ["d1"], "artifacts": ["a1"], "workflow_status": "running"}
	agent_view = AgentView(
		project_name="demo",
		goal="ship",
		decisions=[AgentViewDecisionRecord(topic="decision-topic", decision="d1", rationale="because")],
		artifacts=[AgentViewArtifactRecord(name="artifact.py", artifact_type=ArtifactType.CODE, content="print('ok')")],
	)

	ctx = build_task_context_base(
		task,
		project,
		execution_agent_name="code_engineer",
		provider_max_tokens=4096,
		agent_view=agent_view,
		agent_view_snapshot=snapshot,
		planned_module_context={
			"planned_module_name": "code_implementation",
			"planned_module_filename": "code_implementation.py",
		},
	)

	assert ctx["goal"] == "ship"
	assert ctx["provider_max_tokens"] == 4096
	assert ctx["snapshot"] is snapshot
	assert [decision.topic for decision in ctx["decisions"]] == ["decision-topic"]
	assert [artifact.name for artifact in ctx["artifacts"]] == ["artifact.py"]
	assert ctx["module_name"] == "code_implementation"
	assert ctx["module_filename"] == "code_implementation.py"


def test_apply_completed_task_output_to_context_tracks_completed_and_semantic_outputs():
	ctx = {"completed_tasks": {}}

	should_apply_artifact_context = apply_completed_task_output_to_context(
		ctx,
		task_id="architecture_task",
		assigned_to="planner",
		title="Architecture",
		visible_output="full architecture",
		budget_decomposition_plan_task_id="architecture_task",
		compact_architecture_context="compact architecture",
		is_budget_decomposition_planner=lambda: False,
		semantic_output_key=lambda assigned_to, title: "architecture" if assigned_to == "planner" and title == "Architecture" else None,
	)

	assert should_apply_artifact_context is True
	assert ctx["architecture_task"] == "full architecture"
	assert ctx["completed_tasks"] == {"architecture_task": "full architecture"}
	assert ctx["budget_decomposition_brief"] == "full architecture"
	assert ctx["architecture"] == "compact architecture"


def test_apply_completed_task_output_to_context_skips_artifact_context_for_budget_planner():
	ctx = {"completed_tasks": {}}

	should_apply_artifact_context = apply_completed_task_output_to_context(
		ctx,
		task_id="budget_task",
		assigned_to="planner",
		title="Budget plan",
		visible_output="budget brief",
		budget_decomposition_plan_task_id=None,
		compact_architecture_context=None,
		is_budget_decomposition_planner=lambda: True,
		semantic_output_key=lambda *_args: "architecture",
	)

	assert should_apply_artifact_context is False
	assert ctx["budget_task"] == "budget brief"
	assert ctx["completed_tasks"] == {"budget_task": "budget brief"}
	assert "architecture" not in ctx


def test_apply_completed_tasks_to_context_tracks_visible_done_outputs_and_dispatches_artifacts():
	ctx = {"completed_tasks": {}}
	tasks = [
		SimpleNamespace(id="code", status="done", assigned_to="code_engineer", title="Implement"),
		SimpleNamespace(id="deps", status="done", assigned_to="dependency_manager", title="Dependencies"),
		SimpleNamespace(id="skip", status="pending", assigned_to="qa_tester", title="Tests"),
	]

	apply_completed_tasks_to_context(
		ctx,
		project_tasks=tasks,
		visible_task_ids={"code", "deps", "skip"},
		budget_decomposition_plan_task_id=None,
		compact_architecture_context=None,
		task_context_output=lambda task: {"code": "code output", "deps": "deps output"}.get(task.id),
		is_budget_decomposition_planner=lambda task: False,
		semantic_output_key=lambda assigned_to, title: f"{assigned_to}:{title}",
		normalize_assigned_to=lambda assigned_to: assigned_to,
		code_artifact_context=lambda task: {"code_artifact": task.id},
		dependency_artifact_context=lambda task, current_ctx: {"dependency_artifact": current_ctx[task.id]},
		test_artifact_context=lambda task, current_ctx: {"test_artifact": current_ctx[task.id]},
	)

	assert ctx["completed_tasks"] == {"code": "code output", "deps": "deps output"}
	assert ctx["code_artifact"] == "code"
	assert ctx["dependency_artifact"] == "deps output"
	assert ctx["code_engineer:Implement"] == "code output"
	assert ctx["dependency_manager:Dependencies"] == "deps output"
	assert "skip" not in ctx


@pytest.mark.parametrize(
	("normalized_assigned_to", "expected_key"),
	[
		("code_engineer", "code"),
		("dependency_manager", "dependency"),
		("qa_tester", "test"),
	],
)
def test_apply_completed_task_artifact_contexts_dispatches_by_role(normalized_assigned_to, expected_key):
	ctx = {}

	apply_completed_task_artifact_contexts(
		ctx,
		normalized_assigned_to=normalized_assigned_to,
		code_artifact_context=lambda: {"code": "code artifact"},
		dependency_artifact_context=lambda: {"dependency": "dependency artifact"},
		test_artifact_context=lambda: {"test": "test artifact"},
	)

	assert ctx == {expected_key: f"{expected_key} artifact" if expected_key != "dependency" else "dependency artifact"}


def test_apply_task_public_contract_context_sets_anchor_and_optional_compaction():
	ctx = {}

	compact_architecture_context = apply_task_public_contract_context(
		ctx,
		task_public_contract_anchor="Anchor",
		should_compact_architecture_context=lambda: True,
		compact_architecture_context=lambda: "compact architecture",
	)

	assert ctx["task_public_contract_anchor"] == "Anchor"
	assert compact_architecture_context == "compact architecture"


def test_apply_task_public_contract_context_skips_empty_anchor():
	ctx = {}

	compact_architecture_context = apply_task_public_contract_context(
		ctx,
		task_public_contract_anchor="",
		should_compact_architecture_context=lambda: True,
		compact_architecture_context=lambda: "compact architecture",
	)

	assert compact_architecture_context is None
	assert ctx == {}


def test_analyze_python_module_reports_public_symbols_and_third_party_imports():
	raw_content = """
from dataclasses import dataclass, field
import requests

PUBLIC_VALUE = 1

async def fetch(items: list[str]) -> str:
	return ",".join(items)

class Plain:
	value = field(default=1)

@dataclass
class Payload:
	name: str
	count: int = 0
"""

	analysis = analyze_python_module(raw_content)

	assert analysis["syntax_ok"] is True
	assert analysis["imports"] == ["dataclasses", "requests"]
	assert analysis["third_party_imports"] == ["requests"]
	assert analysis["module_variables"] == ["PUBLIC_VALUE"]
	assert analysis["symbols"] == ["Payload", "Plain", "fetch"]
	assert analysis["functions"][0]["accepts_sequence_input"] is True
	assert analysis["classes"]["Payload"]["constructor_min_args"] == 1
	assert analysis["invalid_dataclass_field_usages"] == [
		"Plain.value uses field(...) on a non-dataclass class"
	]


def test_is_probable_third_party_import_filters_empty_future_and_stdlib():
	assert is_probable_third_party_import("") is False
	assert is_probable_third_party_import("__future__") is False
	assert is_probable_third_party_import("json") is False


def test_build_code_public_api_formats_constructors_and_entrypoint():
	summary = build_code_public_api(
		{
			"syntax_ok": True,
			"functions": [{"signature": "fetch(items)"}],
			"classes": {
				"Payload": {
					"is_enum": False,
					"constructor_params": ["name", "count"],
					"attributes": ["name", "count"],
					"fields": ["name", "count"],
					"methods": ["render(self)"],
				},
			},
			"has_main_guard": True,
		}
	)

	assert "Functions:" in summary
	assert "- fetch(items)" in summary
	assert "- Payload(name, count); class attributes/fields: name, count" in summary
	assert "tests must instantiate with all listed constructor fields explicitly: name, count" in summary
	assert "methods: render(self)" in summary
	assert "Entrypoint: python MODULE_FILE" in summary


def test_build_code_behavior_contract_reports_storage_score_and_sequence_rules():
	contract = build_code_behavior_contract(
		"from dataclasses import dataclass\n"
		"\n"
		"@dataclass\n"
		"class Payload:\n"
		"    data: dict[str, str]\n"
		"\n"
		"@dataclass\n"
		"class Score:\n"
		"    score: int\n"
		"\n"
		"def process_batch(items: list[dict[str, str]]) -> Score:\n"
		"    score = len(items)\n"
		"    return Score(score=score)\n"
		"\n"
		"def intake_request(request_data: dict[str, str]) -> Payload:\n"
		"    return Payload(data=request_data)\n"
	)

	assert "Behavior contract:" in contract
	assert "process_batch accepts sequence inputs via parameter `items`" in contract
	assert "process_batch derives score from len(items)" in contract
	assert "intake_request stores full request_data in returned Payload.data" in contract


def test_test_target_classification_helpers_exclude_entrypoints_and_optional_helpers():
	code_analysis = {
		"functions": [{"name": "main"}],
		"classes": {
			"AuditLogger": {"constructor_params": [], "method_signatures": {}},
			"BillingCLI": {"constructor_params": [], "method_signatures": {}},
			"InvoiceRepository": {"constructor_params": [], "method_signatures": {}},
			"RequestWorkflow": {
				"constructor_params": ["audit_logger"],
				"method_signatures": {"process_batch": {}, "render": {}},
			},
		},
	}

	preferred = preferred_test_class_names(code_analysis)

	assert preferred == ["RequestWorkflow"]
	assert constructor_param_matches_class("audit_logger", "AuditLogger") is True
	assert entrypoint_symbol_names(code_analysis) == {"BillingCLI", "main"}
	assert helper_classes_to_avoid(code_analysis, preferred) == ["InvoiceRepository"]
	assert exposed_test_class_names(code_analysis, preferred) == ["AuditLogger", "RequestWorkflow"]


def test_build_code_exact_test_contract_formats_allowed_imports_and_methods():
	summary = build_code_exact_test_contract(
		{
			"syntax_ok": True,
			"functions": [{"name": "helper", "signature": "helper(payload)"}, {"name": "main", "signature": "main()"}],
			"classes": {
				"AuditLogger": {"constructor_params": [], "methods": ["log_action"], "method_signatures": {"log_action": {}}},
				"ComplianceRequest": {
					"constructor_params": ["request_id", "details"],
					"methods": [],
					"method_signatures": {},
				},
				"ComplianceWorkflow": {
					"constructor_params": [],
					"methods": ["intake_request", "_private_hook"],
					"method_signatures": {"intake_request": {}, "_private_hook": {}},
				},
			},
		}
	)

	assert "Exact test contract:" in summary
	assert "Allowed production imports: ComplianceRequest, ComplianceWorkflow, helper" in summary
	assert "Preferred service or workflow facades: ComplianceWorkflow" in summary
	assert "Exact public callables: helper(payload)" in summary
	assert "Exact public class methods: ComplianceWorkflow.intake_request" in summary
	assert "Exact constructor fields: ComplianceRequest(request_id, details)" in summary


def test_build_code_test_targets_formats_function_and_class_buckets():
	summary = build_code_test_targets(
		{
			"syntax_ok": True,
			"functions": [
				{"name": "main", "signature": "main()", "accepts_sequence_input": False},
				{"name": "process_batch", "signature": "process_batch(items)", "accepts_sequence_input": True},
				{"name": "score_one", "signature": "score_one(item)", "accepts_sequence_input": False},
			],
			"classes": {
				"AuditLogger": {"constructor_params": [], "method_signatures": {}},
				"BillingCLI": {"constructor_params": [], "method_signatures": {}},
				"ComplianceService": {
					"constructor_params": ["audit_logger"],
					"method_signatures": {"process_batch": {}, "validate_request": {}},
				},
				"ComplianceRepository": {"constructor_params": [], "method_signatures": {}},
			},
		}
	)

	assert "Test targets:" in summary
	assert "Functions to test: process_batch(items), score_one(item)" in summary
	assert "Batch-capable functions: process_batch(items)" in summary
	assert "Scalar-only functions: score_one(item)" in summary
	assert "Classes to test: AuditLogger, ComplianceService" in summary
	assert "Preferred workflow classes: ComplianceService" in summary
	assert "Helper classes to avoid in compact workflow tests: ComplianceRepository" in summary
	assert "Entry points to avoid in tests: BillingCLI, main" in summary


def test_build_module_run_command_returns_python_command_for_main_guard():
	assert build_module_run_command("app.py", {"has_main_guard": True}) == "python app.py"
	assert build_module_run_command("app.py", {"has_main_guard": False}) == ""


def test_parse_behavior_contract_extracts_validation_type_and_batch_rules():
	validation_rules, field_value_rules, batch_rules, sequence_input_functions, type_constraint_rules = parse_behavior_contract(
		"\n".join(
			[
				"- intake_request requires fields: request_id, compliance_data",
				"- intake_request requires parameter `payload` to be of type: dict, list (keys used: request_id)",
				"- intake_request expects field `status` to be one of: approved, denied",
				"- process_batch accepts sequence inputs via parameter `items`",
				"- process_batch expects each batch item to include key `request_id` and nested `payload` fields: compliance_data, status",
				"- process_requests expects each batch item to include: request_id, compliance_data",
				"- process_nested expects nested `payload` fields: compliance_data, status",
			]
		)
	)

	assert validation_rules == {"intake_request": ["request_id", "compliance_data"]}
	assert field_value_rules == {"intake_request": {"status": ["approved", "denied"]}}
	assert type_constraint_rules == {"intake_request": {"payload": ["dict", "list"]}}
	assert sequence_input_functions == {"process_batch"}
	assert batch_rules == {
		"process_batch": {"request_key": "request_id", "wrapper_key": "payload", "fields": ["compliance_data", "status"]},
		"process_requests": {"request_key": None, "wrapper_key": None, "fields": ["request_id", "compliance_data"]},
		"process_nested": {"request_key": None, "wrapper_key": "payload", "fields": ["compliance_data", "status"]},
	}


def test_analyze_test_behavior_contracts_reports_payload_value_and_batch_issues():
	tree = ast.parse(
		"def test_case():\n"
		"    validate_request({'name': 'Ada'})\n"
		"    score_request({'status': 'pending'})\n"
		"    helper([1, 2, 3])\n"
	)

	payload_violations, non_batch_calls = analyze_test_behavior_contracts(
		tree,
		{"validate_request": ["name", "email"]},
		{"score_request": {"status": ["approved"]}},
		{},
		set(),
		{"helper"},
		{},
	)

	assert payload_violations == [
		"score_request field `status` uses unsupported values: pending at line 3",
		"validate_request payload missing required fields: email at line 2",
	]
	assert non_batch_calls == ["helper does not accept batch/list inputs at line 4"]


def test_analyze_test_type_mismatches_reports_only_non_negative_type_mismatches():
	tree = ast.parse(
		"def test_case():\n"
		"    validate_request({'details': ('a', 'b')})\n"
		"    with pytest.raises(ValueError):\n"
		"        validate_request({'details': {'a', 'b'}})\n"
		"    score_request(Request(data={'details': ['ok']}))\n"
	)
	class_map = {"Request": {"constructor_params": ["status", "data"]}}

	mismatches = analyze_test_type_mismatches(
		tree,
		{
			"validate_request": {"details": ["dict"]},
			"score_request": {"details": ["dict"]},
		},
		class_map,
	)

	assert mismatches == [
		"validate_request passes tuple for `details` (expected dict) at line 2"
	]


def test_auto_fix_test_type_mismatches_reuses_existing_dict_variable_and_skips_negative_tests():
	impl_code = (
		"class Service:\n"
		"    def handle(self, details):\n"
		"        return details['name']\n"
	)
	test_code = (
		"def test_handle():\n"
		"    details = {'name': 'alice'}\n"
		"    s = Service()\n"
		"    s.handle(details='test')\n\n"
		"def test_validation_failure():\n"
		"    s = Service()\n"
		"    s.handle(details='bad')\n"
	)

	fixed = auto_fix_test_type_mismatches(
		test_code,
		impl_code,
		lambda tree: {"details": ["name"]},
	)

	assert "s.handle(details=details)" in fixed
	assert "details='bad'" in fixed


def test_analyze_test_module_returns_default_shape_for_blank_and_syntax_invalid_input():
	blank_analysis = analyze_test_module(
		"   ",
		"module_under_test",
		set(),
		set(),
		{},
		{},
		set(),
		set(),
		{},
		{},
		{},
		set(),
		{},
		{"request"},
		{"cache", "capsys", "monkeypatch", "tmp_path"},
	)
	syntax_error_analysis = analyze_test_module(
		"def broken(:\n    pass",
		"module_under_test",
		set(),
		set(),
		{},
		{},
		set(),
		set(),
		{},
		{},
		{},
		set(),
		{},
		{"request"},
		{"cache", "capsys", "monkeypatch", "tmp_path"},
	)

	assert blank_analysis == {
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
	assert syntax_error_analysis["syntax_ok"] is False
	assert syntax_error_analysis["syntax_error"] == "invalid syntax at line 1"


def test_apply_repair_context_to_context_populates_qa_and_dependency_fields():
	qa_context = {"code": "def implementation():\n    return 1"}
	qa_repair_context = {
		"validation_summary": "test summary",
		"helper_surface_usages": [" helper_a ", "", "helper_b"],
		"helper_surface_symbols": [" helper_alias "],
		"failed_output": "def test_generated():\n    assert implementation() == 1",
	}

	apply_repair_context_to_context(
		qa_context,
		qa_repair_context,
		"qa_tester",
		None,
		agent_visible_repair_context=lambda current_repair_context, _execution_agent_name: dict(current_repair_context),
		normalized_execution_agent="qa_tester",
		normalized_helper_surface_symbols=lambda raw_values: [str(item).strip() for item in raw_values if str(item).strip()],
		qa_repair_should_reuse_failed_test_artifact=lambda validation_summary, code_content, repair_content: bool(validation_summary and code_content and repair_content),
	)

	assert qa_context["existing_tests"] == "def test_generated():\n    assert implementation() == 1"
	assert qa_context["test_validation_summary"] == "test summary"
	assert qa_context["repair_helper_surface_usages"] == ["helper_a", "helper_b"]
	assert qa_context["repair_helper_surface_symbols"] == ["helper_alias"]

	dependency_context = {}
	dependency_repair_context = {
		"validation_summary": "dependency summary",
		"failed_output": "requests==2.0.0",
	}

	apply_repair_context_to_context(
		dependency_context,
		dependency_repair_context,
		"dependency_manager",
		None,
		agent_visible_repair_context=lambda current_repair_context, _execution_agent_name: dict(current_repair_context),
		normalized_execution_agent="dependency_manager",
		normalized_helper_surface_symbols=lambda raw_values: [str(item).strip() for item in raw_values if str(item).strip()],
		qa_repair_should_reuse_failed_test_artifact=lambda *_args: False,
	)

	assert dependency_context["existing_dependency_manifest"] == "requests==2.0.0"
	assert dependency_context["dependency_validation_summary"] == "dependency summary"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")
def test_harden_private_directory_permissions_sets_mode_700(tmp_path):
	directory_path = tmp_path / "artifacts"
	directory_path.mkdir()
	directory_path.chmod(0o755)

	harden_private_directory_permissions(directory_path)

	assert stat.S_IMODE(directory_path.stat().st_mode) == 0o700


def test_artifact_persistence_support_redacts_and_updates_relative_path(tmp_path):
	support = ArtifactPersistenceSupport(output_dir=str(tmp_path / "output"))
	artifacts = [
		ArtifactRecord(
			name="Report Draft",
			artifact_type=ArtifactType.DOCUMENT,
			content="Authorization: Bearer sk-ant-secret-987654",
			path="reports/final draft.md",
		)
	]

	support.persist_artifacts(artifacts)
	persisted_path = tmp_path / "output" / "reports" / "final_draft.md"
	persisted_content = persisted_path.read_text(encoding="utf-8")

	assert artifacts[0].path == "reports/final_draft.md"
	assert artifacts[0].content == persisted_content
	assert persisted_content == "Authorization: Bearer [REDACTED]"


def test_execute_agent_prefers_execute_then_run_with_input_then_run_directly():
	agent_input = AgentInput(
		task_id="task-1",
		task_title="Task",
		task_description="Do work",
		project_name="Demo",
		project_goal="Build demo",
		context={"key": "value"},
	)

	class ExecuteAgent:
		def execute(self, received_input: AgentInput) -> str:
			assert received_input is agent_input
			return "execute"

	class RunWithInputAgent:
		def run_with_input(self, received_input: AgentInput) -> str:
			assert received_input is agent_input
			return "run_with_input"

	class RunAgent:
		def run(self, task_description: str, context: dict[str, object]) -> str:
			assert task_description == "Do work"
			assert context == {"key": "value"}
			return "run"

	assert execute_agent(ExecuteAgent(), agent_input) == "execute"
	assert execute_agent(RunWithInputAgent(), agent_input) == "run_with_input"
	assert execute_agent(RunAgent(), agent_input) == "run"


def test_build_agent_input_uses_repair_defaults_directly():
	project = ProjectState(project_name="Demo", goal="Build demo")
	task = Task(
		id="repair",
		title="Repair architecture",
		description="Repair the architecture",
		assigned_to="architect",
		repair_context={
			"instruction": "",
			"failure_category": "",
			"failure_message": "   ",
			"validation_summary": "   ",
		},
	)

	agent_input = build_agent_input(task, project, {}, repair_focus_lines=[])

	assert "Repair objective:" in agent_input.task_description
	assert "Repair the previous failure." in agent_input.task_description
	assert f"Previous failure category: {FailureCategory.UNKNOWN.value}" in agent_input.task_description
	assert "Previous failure message:" not in agent_input.task_description
	assert "Validation summary:" not in agent_input.task_description


def test_build_agent_input_includes_source_failure_metadata_directly():
	project = ProjectState(project_name="Demo", goal="Build demo")
	task = Task(
		id="code",
		title="Implementation",
		description="Write code",
		assigned_to="code_engineer",
		repair_context={
			"cycle": 1,
			"failure_category": FailureCategory.CODE_VALIDATION.value,
			"source_failure_task_id": "tests",
			"source_failure_category": FailureCategory.TEST_VALIDATION.value,
			"instruction": "Repair the generated Python module.",
			"failure_message": "module import failed",
			"validation_summary": "Generated test validation:\n- Verdict: FAIL",
		},
	)

	agent_input = build_agent_input(
		task,
		project,
		{"budget_decomposition_brief": "Stay within the budget."},
		repair_focus_lines=["Repair the failing import first."],
	)

	assert "Source failure task: tests" in agent_input.task_description
	assert "Source failure category: test_validation" in agent_input.task_description
	assert "Previous failure message: module import failed" in agent_input.task_description
	assert "Budget decomposition brief:" in agent_input.task_description
	assert "Repair priorities:" in agent_input.task_description
	assert "- Repair the failing import first." in agent_input.task_description


def test_artifact_persistence_support_rejects_symlink_escape(tmp_path):
	support = ArtifactPersistenceSupport(output_dir=str(tmp_path / "output"))
	escaped_root = tmp_path / "escaped"
	escaped_root.mkdir()
	(tmp_path / "output").mkdir()
	linked_dir = tmp_path / "output" / "artifacts"
	linked_dir.symlink_to(escaped_root, target_is_directory=True)
	artifacts = [
		ArtifactRecord(
			name="Report Draft",
			artifact_type=ArtifactType.DOCUMENT,
			content="hello",
			path="artifacts/final.md",
		)
	]

	with pytest.raises(AgentExecutionError, match="resolves outside the output directory"):
		support.persist_artifacts(artifacts)

	assert not (escaped_root / "final.md").exists()
	assert artifacts[0].path == "artifacts/final.md"


def test_artifact_persistence_support_rejects_invalid_segment_from_injected_sanitizer(tmp_path):
	def fake_sub(pattern: str, replacement: str, value: str) -> str:
		if value == "unsafe":
			return "."
		return re.sub(pattern, replacement, value)

	support = ArtifactPersistenceSupport(
		output_dir=str(tmp_path / "output"),
		sanitize_sub=fake_sub,
	)

	with pytest.raises(AgentExecutionError, match="artifact path contains an invalid segment"):
		support.sanitize_artifact_relative_path("reports/unsafe/summary.md")


def test_ast_name_replacer_rewrites_names_in_expression():
	expression = ast.parse("foo + bar", mode="eval").body
	rewritten = AstNameReplacer(
		{
			"foo": ast.Constant(value=10),
			"bar": ast.Name(id="baz", ctx=ast.Load()),
		}
	).visit(expression)

	assert ast.unparse(ast.fix_missing_locations(rewritten)) == "10 + baz"


def test_test_ast_analysis_helpers_collect_parametrized_names_and_bindings_directly():
	function_node = ast.parse(
		"@pytest.mark.parametrize('item, expected', [('a', 1)])\n"
		"def test_case(item, other_fixture):\n"
		"    first, *rest = [1, 2, 3]\n"
		"    with helper() as alias:\n"
		"        total = first\n"
		"    import logging as log\n"
		"    return alias, rest, total, log, expected\n"
	).body[0]
	assert isinstance(function_node, ast.FunctionDef)

	assert function_argument_names(function_node) == {"item", "other_fixture"}
	assert collect_parametrized_argument_names(function_node) == {"item", "expected"}
	bindings = collect_local_name_bindings(function_node)
	assert {"item", "other_fixture", "expected", "first", "rest", "alias", "total", "log"}.issubset(bindings)
	keyword_decorator = ast.parse(
		"@pytest.mark.parametrize(argnames='left, right', argvalues=[(1, 2)])\n"
		"def test_keyword(left, right):\n"
		"    return left + right\n"
	).body[0]
	assert isinstance(keyword_decorator, ast.FunctionDef)
	keyword_decorator_call = keyword_decorator.decorator_list[0]
	assert isinstance(keyword_decorator_call, ast.Call)
	assert extract_parametrize_argument_names(keyword_decorator_call) == {"left", "right"}


def test_test_ast_analysis_helpers_detect_undefined_names_patch_targets_and_mocks_directly():
	function_node = ast.parse(
		"def test_case(mocker):\n"
		"    from unittest.mock import MagicMock, patch\n"
		"    mock_logger = MagicMock()\n"
		"    patched = patch('logging.getLogger')\n"
		"    with patch.object(logger, 'info') as patched_info:\n"
		"        assert mock_logger.info.call_count == 0\n"
		"    return missing_name\n"
	).body[0]
	assert isinstance(function_node, ast.FunctionDef)

	undefined_names = collect_undefined_local_names(function_node, set())
	assert undefined_names == ["logger (line 5)", "missing_name (line 7)"]
	mock_bindings, patched_targets = collect_mock_support(function_node)
	assert {"mocker", "mock_logger", "patched", "patched_info"}.issubset(mock_bindings)
	assert patched_targets == {"logger.info", "logging.getLogger"}
	assert is_mock_factory_call(ast.parse("MagicMock()", mode="eval").body) is True
	assert is_patch_call(ast.parse("patch.object(logger, 'info')", mode="eval").body) is True
	patch_call = ast.parse("patch.object(logger, 'info')", mode="eval").body
	assert isinstance(patch_call, ast.Call)
	assert patched_target_name_from_call(patch_call) == "logger.info"


def test_test_ast_analysis_helpers_find_unsupported_mock_assertions_and_local_types_directly():
	function_node = ast.parse(
		"def test_case():\n"
		"    service = Service()\n"
		"    assert logging.getLogger().info.call_count == 1\n"
	).body[0]
	assert isinstance(function_node, ast.FunctionDef)
	local_types = collect_test_local_types(
		function_node,
		{"Service": {"method_signatures": {}, "attributes": [], "fields": [], "is_enum": False}},
		{},
		lambda node, local_types, class_map, function_map: "Service"
		if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Service"
		else None,
	)
	assert local_types == {"service": "Service"}
	assert find_unsupported_mock_assertions(function_node, local_types, {}) == [
		"logging.getLogger().info.call_count (line 3)"
	]


def test_test_ast_analysis_helpers_collect_bindings_and_module_symbols_directly():
	function_node = ast.parse(
		"def test_case():\n"
		"    payload = {'status': 'approved'}\n"
		"    typed_payload: dict = payload\n"
	).body[0]
	assert isinstance(function_node, ast.FunctionDef)
	bindings = collect_local_bindings(function_node)
	assert set(bindings) == {"payload", "typed_payload"}
	assert isinstance(bindings["payload"], ast.Dict)

	module_tree = ast.parse(
		"from pkg import *\n"
		"import os as operating_system\n"
		"value = 1\n"
		"annotated: int = 2\n"
		"holder.value: int = 3\n"
	)
	assert collect_module_defined_names(ast.Constant(1)) == set()
	assert collect_module_defined_names(module_tree) == {"operating_system", "value", "annotated"}

	call_tree = ast.parse("service.validate(payload)", mode="eval").body
	inner_name = next(node for node in ast.walk(call_tree) if isinstance(node, ast.Name) and node.id == "payload")
	assert ast_contains_node(call_tree, inner_name) is True

	bindings = {
		"payload": ast.Dict(
			keys=[ast.Constant("payload"), ast.Constant("status")],
			values=[
				ast.Dict(keys=[ast.Constant("name")], values=[ast.Constant("Ada")]),
				ast.Constant("approved"),
			],
		),
		"request_obj": ast.Call(
			func=ast.Name("Request"),
			args=[ast.Constant("pending")],
			keywords=[
				ast.keyword(
					arg="data",
					value=ast.Dict(keys=[ast.Constant("status")], values=[ast.Constant("denied")]),
				)
			],
		),
		"items": ast.List(elts=[ast.Dict(keys=[ast.Constant("request_id")], values=[ast.Constant("id-1")])]),
	}
	class_map = {"Request": {"constructor_params": ["status", "data"]}}
	request_call = bindings["request_obj"]
	assert isinstance(request_call, ast.Call)
	assert isinstance(resolve_bound_value(ast.Name("request_obj"), bindings), ast.Call)
	assert isinstance(call_argument_value(request_call, "status", class_map), ast.Constant)
	assert extract_literal_dict_keys(ast.Subscript(value=ast.Name("payload"), slice=ast.Constant("payload")), bindings, class_map) == {"name"}
	assert extract_literal_dict_keys(ast.Name("request_obj"), bindings, class_map) == {"status"}
	assert extract_literal_field_values(ast.Name("payload"), bindings, "status", class_map) == ["approved"]
	assert extract_literal_field_values(ast.Name("request_obj"), bindings, "status", class_map) == ["pending"]
	assert extract_string_literals(ast.Constant(123), bindings) == []
	assert extract_literal_list_items(ast.Name("items"), bindings) is not None
	assert infer_argument_type(ast.Name("payload"), bindings, "status", class_map) == "str"
	assert infer_argument_type(ast.parse("{'items': list()}", mode="eval").body, {}, "items", class_map) == "list"
	assert call_argument_count(request_call) == 2

	typed_class_map = {
		"Request": {"attributes": ["request_id"], "fields": [], "is_enum": False, "method_signatures": {}},
		"Service": {
			"attributes": [],
			"fields": [],
			"is_enum": False,
			"method_signatures": {
				"fetch": {"min_args": 1, "max_args": 1, "return_annotation": "Request"},
				"range_fetch": {"min_args": 1, "max_args": 2, "return_annotation": "Request"},
			},
		},
	}
	function_map = {"build_request": {"return_annotation": "Request"}}
	test_node = ast.parse(
		"def test_case():\n"
		"    request = build_request()\n"
		"    service = Service()\n"
		"    returned = service.fetch({'request_id': 'req-1'})\n"
		"    service.missing()\n"
		"    service.range_fetch(1, 2, 3)\n"
		"    assert returned.invalid == 1\n"
	).body[0]
	assert isinstance(test_node, ast.FunctionDef)
	local_types = {"request": "Request", "service": "Service", "returned": "Request"}
	assert infer_expression_type(ast.Name("service"), local_types, typed_class_map, function_map) == "Service"
	assert infer_call_result_type(ast.parse("service.fetch()", mode="eval").body, {"service": "Service"}, typed_class_map, function_map) == "Request"
	assert analyze_typed_test_member_usage(test_node, local_types, typed_class_map, function_map) == (
		["Request.invalid (line 7)", "Service.missing (line 5)"],
		["Service.range_fetch expects 1-2 args but test uses 3 at line 6"],
	)

	validation_call = ast.parse("validate_request(payload)", mode="eval").body
	keyword_batch_call = ast.parse("process_batch(payload=batch)", mode="eval").body
	batch_call = ast.fix_missing_locations(
		ast.Call(func=ast.Name("process_batch"), args=[ast.Name("items")], keywords=[])
	)
	assert isinstance(validation_call, ast.Call)
	assert isinstance(keyword_batch_call, ast.Call)
	assert isinstance(payload_argument_for_validation(validation_call, "validate_request"), ast.Name)
	assert isinstance(payload_argument_for_validation(keyword_batch_call, "process_batch"), ast.Name)
	assert validate_batch_call(
		batch_call,
		{"items": ast.List(elts=[ast.Dict(keys=[ast.Constant("name")], values=[ast.Constant("Ada")])])},
		"process_batch",
		{"fields": ["name", "email"], "request_key": None, "wrapper_key": None},
	) == ["process_batch batch item missing required fields: email at line 1"]

	negative_tree = ast.parse(
		"def test_invalid_case():\n"
		"    payload = {'status': 'invalid'}\n"
		"    with pytest.raises(ValueError):\n"
		"        validate_request(payload)\n"
		"    result = validate_request(payload)\n"
		"    assert payload.status == 'Invalid'\n"
	)
	test_case = negative_tree.body[0]
	assert isinstance(test_case, ast.FunctionDef)
	call_nodes = [
		node
		for node in ast.walk(test_case)
		if isinstance(node, ast.Call) and callable_name(node) == "validate_request"
	]
	negative_parent_map = parent_map(negative_tree)
	negative_call = next(node for node in call_nodes if node.lineno == 4)
	followup_call = next(node for node in call_nodes if node.lineno == 5)
	assert call_has_negative_expectation(negative_call, negative_parent_map) is True
	assert call_expects_invalid_outcome(test_case, followup_call, negative_parent_map) is True
	assert assigned_name_for_call(followup_call, negative_parent_map) == "result"
	assert invalid_outcome_subject_matches(ast.parse("result.status", mode="eval").body, "result", None) is True
	assert invalid_outcome_marker_matches(ast.Constant("Pending")) is True
	false_compare = ast.parse("assert False == validate_request(data)").body[0]
	assert isinstance(false_compare, ast.Assert)
	assert isinstance(false_compare.test, ast.Compare)
	assert isinstance(false_compare.test.comparators[0], ast.Call)
	assert assert_expects_false(false_compare, false_compare.test.comparators[0]) is True
	invalid_status_assert = ast.parse("assert request.status == 'Invalid'").body[0]
	assert isinstance(invalid_status_assert, ast.Assert)
	assert assert_expects_invalid_outcome(invalid_status_assert.test, None, "request") is True

	partial_tree = ast.parse(
		"def test_batch():\n"
		"    result = process_batch([1, 2, 3])\n"
		"    assert 1 > len(result)\n"
	)
	partial_function = partial_tree.body[0]
	assert isinstance(partial_function, ast.FunctionDef)
	partial_call = partial_function.body[0]
	assert isinstance(partial_call, ast.Assign)
	assert isinstance(partial_call.value, ast.Call)
	partial_parent_map = parent_map(partial_tree)
	assert batch_call_allows_partial_invalid_items(
		partial_function,
		partial_call.value,
		{},
		partial_parent_map,
	) is True
	assert assert_limits_batch_result(ast.parse("1 > len(result)", mode="eval").body, "result", partial_call.value, 3) is True
	direct_len = ast.parse("len(process_batch(requests))", mode="eval").body
	assert isinstance(direct_len, ast.Call)
	assert isinstance(direct_len.args[0], ast.Call)
	assert len_call_matches_batch_result(direct_len, None, direct_len.args[0]) is True
	assert int_constant_value(ast.Constant("x")) is None
	assert comparison_implies_partial_batch_result(ast.LtE(), 2, 3) is True

	overreach_function = ast.parse(
		"def test_validation_failure():\n"
		"    for item in [{'id': 1}, {'id': 2}]:\n"
		"        handle_request(item)\n"
		"    assert len(service.audit_logs) == 3\n"
		"    assert len(service.get_risk_scores()) == 0\n"
	).body[0]
	assert isinstance(overreach_function, ast.FunctionDef)
	assert name_suggests_validation_failure("test_validation_failure") is True
	assert is_internal_score_state_target("service.get_risk_scores()") is True
	assert behavior_contract_explicitly_limits_score_state_to_valid_requests(
		"Behavior contract:\n- handle_request appends to risk_scores only for valid requests",
		"service.get_risk_scores()",
	) is True
	assert visible_repeated_single_call_batch_sizes(
		overreach_function,
		{},
	) == [2]
	loop_node = overreach_function.body[0]
	assert loop_contains_non_batch_call(loop_node) is True
	audit_assert = overreach_function.body[1]
	assert isinstance(audit_assert, ast.Assert)
	assert exact_len_assertion(audit_assert.test) == ("service.audit_logs", 3)
	assert is_len_call(ast.parse("len(service.audit_logs)", mode="eval").body) is True
	assert find_contract_overreach_signals(overreach_function, {}, "") == [
		"exact batch audit length 3 exceeds visible batch size 2 in test_validation_failure (line 4)",
		"exact validation-failure score-state emptiness assertion on 'service.get_risk_scores()' in test_validation_failure (line 5) assumes rejected input leaves internal score state empty",
	]


def test_test_ast_analysis_helpers_detect_pytest_assertion_contexts_and_count_checks_directly():
	with_node = ast.parse(
		"with pytest.raises(ValueError):\n"
		"    validate_request(data)\n"
	).body[0]
	assert isinstance(with_node, ast.With)
	assert with_uses_pytest_raises(with_node) is True
	assert with_uses_pytest_assertion_context(with_node) is True

	warns_node = ast.parse(
		"with pytest.warns(UserWarning):\n"
		"    emit_warning()\n"
	).body[0]
	assert isinstance(warns_node, ast.With)
	assert with_uses_pytest_raises(warns_node) is False
	assert with_uses_pytest_assertion_context(warns_node) is True

	function_node = ast.parse(
		"def test_case():\n"
		"    mock_logger = MagicMock()\n"
		"    assert True\n"
		"    with pytest.raises(ValueError):\n"
		"        explode()\n"
		"    mock_logger.info('ok')\n"
		"    assert mock_logger.info.call_count == 1\n"
	).body[0]
	assert isinstance(function_node, ast.FunctionDef)
	assert count_test_assertion_like_checks(function_node) == 4


def test_module_ast_analysis_helpers_cover_signatures_binding_kinds_and_self_assignments():
	assert annotation_accepts_sequence_input("Sequence[int]") is True
	assert annotation_accepts_sequence_input("str") is False
	assert build_code_outline("\nclass Example:\n    pass\n\ndef run():\n    return 1\n") == "class Example:\ndef run():"
	assert build_code_outline("   ") == ""

	function_node = ast.parse(
		"def handle(self, payload: list[str], *, strict: bool = False) -> int:\n"
		"    return len(payload)\n"
	).body[0]
	assert isinstance(function_node, ast.FunctionDef)
	signature = call_signature_details(function_node, skip_first_param=True)
	assert signature == {
		"params": ["payload", "strict"],
		"param_annotations": ["list[str]", "bool"],
		"min_args": 1,
		"max_args": 2,
		"accepts_sequence_input": True,
		"return_annotation": "int",
	}

	staticmethod_node = ast.parse(
		"@staticmethod\n"
		"def build(value: str) -> str:\n"
		"    return value\n"
	).body[0]
	classmethod_node = ast.parse(
		"@decorators.classmethod()\n"
		"def make(cls, value: str) -> str:\n"
		"    return value\n"
	).body[0]
	instance_node = ast.parse(
		"def save(self, value: str) -> None:\n"
		"    self.value = value\n"
	).body[0]
	assert isinstance(staticmethod_node, ast.FunctionDef)
	assert isinstance(classmethod_node, ast.FunctionDef)
	assert isinstance(instance_node, ast.FunctionDef)
	assert method_binding_kind(staticmethod_node) == "static"
	assert method_binding_kind(classmethod_node) == "class"
	assert method_binding_kind(instance_node) == "instance"
	assert self_assigned_attributes(instance_node) == ["value"]

	class_node = ast.parse(
		"@dataclasses.dataclass\n"
		"class Payload:\n"
		"    value: int\n"
	).body[0]
	assert isinstance(class_node, ast.ClassDef)
	assert has_dataclass_decorator(class_node) is True
	field_call = ast.parse("field(default=1)", mode="eval").body
	assert isinstance(field_call, ast.Call)
	assert call_expression_basename(field_call.func) == "field"
	assert call_expression_basename(ast.parse("factory.helpers.build", mode="eval").body) == "build"
	assert dataclass_field_has_default(None) is False
	assert dataclass_field_has_default(ast.parse("field(default=1)", mode="eval").body) is True
	assert dataclass_field_has_default(ast.parse("field()", mode="eval").body) is False
	assert dataclass_field_is_init_enabled(ast.parse("field(init=False)", mode="eval").body) is False
	assert dataclass_field_is_init_enabled(ast.parse("field(default=1)", mode="eval").body) is True

	sequence_node = ast.parse(
		"def process(self, items):\n"
		"    for item in items:\n"
		"        consume(item)\n"
	).body[0]
	assert isinstance(sequence_node, ast.FunctionDef)
	sequence_parameter = first_user_parameter(sequence_node)
	assert sequence_parameter is not None
	assert sequence_parameter.arg == "items"
	assert parameter_is_iterated(sequence_node, "items") is True
	assert parameter_is_iterated(sequence_node, "other") is False

	required_fields_node = ast.parse(
		"def validate(payload):\n"
		"    required_fields = ['name', 1, 'email']\n"
		"    return payload\n"
	).body[0]
	assert isinstance(required_fields_node, ast.FunctionDef)
	assert extract_required_fields(required_fields_node) == ["name", "email"]

	comparison_node = ast.Compare(left=ast.Constant("field"), ops=[ast.In()], comparators=[ast.Name("payload")])
	assert comparison_required_field(comparison_node) == "field"
	assert comparison_required_field(ast.Compare(left=ast.Constant("field"), ops=[ast.Eq()], comparators=[ast.Name("payload")])) == ""

	indirect_node = ast.parse(
		"def validate(payload):\n"
		"    return helper.validate_request(payload)\n"
	).body[0]
	assert isinstance(indirect_node, ast.FunctionDef)
	assert extract_indirect_required_fields(indirect_node, {"validate_request": ["request_id"]}) == ["request_id"]

	lookup_node = ast.parse(
		"def score_request(request, payload, selector):\n"
		"    risk_scores = {'approved': 1, 'denied': 0}\n"
		"    return risk_scores[request.status] + risk_scores[payload['state']] + risk_scores[selector]\n"
	).body[0]
	assert isinstance(lookup_node, ast.FunctionDef)
	assert extract_lookup_field_rules(lookup_node) == {
		"status": ["approved", "denied"],
		"state": ["approved", "denied"],
	}
	assert field_selector_name(ast.Subscript(value=ast.Name("payload"), slice=ast.Constant("state"))) == "state"
	assert field_selector_name(ast.Constant("status")) == "status"
	assert field_selector_name(ast.Name("selector")) == ""

	returning_node = ast.parse(
		"def build(self, payload, *, strict=False):\n"
		"    return payload\n"
	).body[0]
	assert isinstance(returning_node, ast.FunctionDef)
	returned_expression = direct_return_expression(returning_node)
	assert isinstance(returned_expression, ast.Name)
	assert returned_expression.id == "payload"
	assert callable_parameter_names(returning_node) == ["payload"]
	assert extract_sequence_input_rule(returning_node) == ""

	annotated_sequence_node = ast.parse(
		"def handle(items: list[str]):\n"
		"    return len(items)\n"
	).body[0]
	iterated_sequence_node = ast.parse(
		"def handle(items):\n"
		"    for item in items:\n"
		"        consume(item)\n"
	).body[0]
	assert isinstance(annotated_sequence_node, ast.FunctionDef)
	assert isinstance(iterated_sequence_node, ast.FunctionDef)
	assert extract_sequence_input_rule(annotated_sequence_node) == "handle accepts sequence inputs via parameter `items`"
	assert extract_sequence_input_rule(iterated_sequence_node) == "handle accepts sequence inputs via parameter `items`"

	assert example_from_default(ast.Constant(True)) == "True"
	assert example_from_default(ast.Constant(0)) == "1"
	assert example_from_default(ast.List(elts=[], ctx=ast.Load())) == "['sample']"
	assert example_from_default(ast.Dict(keys=[], values=[])) == "{'key': 'value'}"

	dict_tree = ast.parse(
		"d = request.details\n"
		"d.get('count', 0)\n"
		"details.get('active', False)\n"
	)
	assert infer_dict_key_value_examples(dict_tree) == {
		"details": {"count": "1", "active": "False"},
	}

	access_tree = ast.parse(
		"d = request.details\n"
		"value = d['count']\n"
		"'status' in details\n"
		"details.get('active', False)\n"
	)
	assert dict_accessed_keys_from_tree(access_tree) == {
		"details": ["count", "status", "active"],
	}

	isinstance_call = ast.parse("isinstance(payload['count'], int)", mode="eval").body
	assert isinstance(isinstance_call, ast.Call)
	assert isinstance_subject_name(isinstance_call.args[0]) == "count"
	assert isinstance_type_names(isinstance_call.args[1]) == ["int"]

	attribute_call = ast.parse("isinstance(item.value, (str, model.Score))", mode="eval").body
	assert isinstance(attribute_call, ast.Call)
	assert isinstance_subject_name(attribute_call.args[0]) == "value"
	assert isinstance_type_names(attribute_call.args[1]) == ["str", "model.Score"]

	compound_test = ast.parse("not isinstance(data, dict) or helper.isinstance(payload.get('field'), str)", mode="eval").body
	collected_calls: list[ast.Call] = []
	collect_isinstance_calls(compound_test, collected_calls)
	assert len(collected_calls) == 2

	constraint_node = ast.parse(
		"def validate(data, payload):\n"
		"    if not isinstance(data, dict):\n"
		"        raise TypeError('bad')\n"
		"    assert helper.isinstance(payload.get('field'), (str, int))\n"
	).body[0]
	assert isinstance(constraint_node, ast.FunctionDef)
	assert extract_type_constraints(constraint_node) == {
		"data": ["dict"],
		"field": ["str", "int"],
	}

	literal_examples = extract_valid_literal_examples(
		"DEFAULT_PROFILE = {'name': 'Ada'}\n"
		"sample_items = ['one']\n"
		"ignored_value = 3\n"
	)
	assert literal_examples == {
		"DEFAULT_PROFILE": "{'name': 'Ada'}",
		"sample_items": "['one']",
	}
	assert extract_valid_literal_examples("def broken(:\n    pass") == {}

	batch_node = ast.parse(
		"def process_batch(items):\n"
		"    for item in items:\n"
		"        intake_request(item['request_id'], item['payload'])\n"
	).body[0]
	assert isinstance(batch_node, ast.FunctionDef)
	assert (
		extract_batch_rule(batch_node, {"intake_request": ["name", "email"]})
		== "process_batch expects each batch item to include key `request_id` and nested `payload` fields: name, email"
	)

	empty_batch_node = ast.parse(
		"def process_items(items):\n"
		"    for item in items:\n"
		"        intake_request(item['request_id'], item)\n"
	).body[0]
	assert isinstance(empty_batch_node, ast.FunctionDef)
	assert extract_batch_rule(empty_batch_node, {"intake_request": ["name"]}) == ""

	dataclass_node = ast.parse(
		"@dataclass\n"
		"class RiskRecord:\n"
		"    score: int\n"
	).body[0]
	manual_class_node = ast.parse(
		"class ManualRisk:\n"
		"    def __init__(self, payload):\n"
		"        self.payload = payload\n"
	).body[0]
	assert isinstance(dataclass_node, ast.ClassDef)
	assert isinstance(manual_class_node, ast.ClassDef)
	assert extract_class_definition_style(dataclass_node) == "RiskRecord is defined as a @dataclass"
	assert extract_class_definition_style(manual_class_node) == "ManualRisk uses manual __init__"

	annotated_method = ast.parse(
		"def export(payload) -> dict[str, int]:\n"
		"    return payload\n"
	).body[0]
	hidden_method = ast.parse(
		"def _hidden() -> str:\n"
		"    return 'x'\n"
	).body[0]
	assert isinstance(annotated_method, ast.FunctionDef)
	assert isinstance(hidden_method, ast.FunctionDef)
	assert extract_return_type_annotation(None, annotated_method) == "export returns dict[str, int]"
	assert extract_return_type_annotation("RiskService", annotated_method) == "RiskService.export returns dict[str, int]"
	assert extract_return_type_annotation(None, hidden_method) == ""

	constructor_rule_node = ast.parse(
		"def build(payload):\n"
		"    return RiskResult(score=1, data=payload)\n"
	).body[0]
	assert isinstance(constructor_rule_node, ast.FunctionDef)
	assert (
		extract_constructor_storage_rule(constructor_rule_node)
		== "build stores full payload in returned RiskResult.data"
	)

	helper_node = ast.parse(
		"def base_score(payload):\n"
		"    factor = payload['weight']\n"
		"    return factor * 2\n"
	).body[0]
	score_node = ast.parse(
		"def derive_score(payload):\n"
		"    score = base_score(payload)\n"
		"    return score\n"
	).body[0]
	assert isinstance(helper_node, ast.FunctionDef)
	assert isinstance(score_node, ast.FunctionDef)
	assert function_returns_score_value(score_node) is True

	helper_call = ast.parse("base_score(payload)", mode="eval").body
	assert isinstance(helper_call, ast.Call)
	inlined = inline_score_helper_expression(helper_call, {"base_score": helper_node})
	assert render_score_expression(inlined, {"base_score": helper_node}) == "payload['weight'] * 2"

	aliased_expression = ast.parse("derived", mode="eval").body
	alias_node = ast.parse(
		"def derive_score(payload):\n"
		"    base = payload['weight']\n"
		"    derived = base * 3\n"
		"    return derived\n"
	).body[0]
	assert isinstance(aliased_expression, ast.Name)
	assert isinstance(alias_node, ast.FunctionDef)
	assert render_score_expression(expand_local_name_aliases(aliased_expression, alias_node), {}) == "payload['weight'] * 3"

	assert (
		extract_score_derivation_rule(score_node, {"base_score": helper_node})
		== "derive_score derives score from payload['weight'] * 2"
	)


def test_render_sandbox_sitecustomize_returns_dedented_script():
	script = render_sandbox_sitecustomize()

	assert script.startswith("import asyncio\n")
	assert "sandbox policy blocked filesystem write outside sandbox root" in script
	assert script.endswith("\n")


def test_render_generated_test_runner_includes_configured_paths(tmp_path):
	script = render_generated_test_runner(
		sandbox_enabled=True,
		pytest_config_path=str(tmp_path / "pytest.ini"),
		rootdir_path=str(tmp_path),
		pytest_log_path=str(tmp_path / "pytest.log"),
		test_filename="generated_tests.py",
	)

	assert 'sandbox_sitecustomize = TMP_PATH / "sitecustomize.py"' in script
	assert repr(str(tmp_path / "pytest.ini")) in script
	assert repr("generated_tests.py") in script
	assert "pytest.main(pytest_args)" in script


def test_render_generated_import_runner_includes_module_filename():
	script = render_generated_import_runner(
		sandbox_enabled=False,
		module_filename="code_under_test.py",
	)

	assert 'TMP_PATH / "sitecustomize.py"' in script
	assert repr("code_under_test.py") in script
	assert '"code_under_test"' in script


def test_looks_like_secret_env_var_detects_generic_secret_markers():
	assert looks_like_secret_env_var("OPENAI_API_KEY") is True
	assert looks_like_secret_env_var("client_secret") is True
	assert looks_like_secret_env_var("NORMAL_ENV") is False


def test_sanitize_generated_filename_strips_traversal_and_preserves_suffix():
	assert sanitize_generated_filename("../../tests generated", "generated_tests.py") == "tests_generated.py"
	assert sanitize_generated_filename("custom-name", "generated_tests.py") == "custom-name.py"


def test_build_generated_test_env_writes_sandbox_bindings_and_sitecustomize(tmp_path):
	policy = KYCortexConfig(output_dir=str(tmp_path / "output")).execution_sandbox_policy()
	env = build_generated_test_env(tmp_path, policy, host_env={"PATH": "/usr/bin", "PYTHONPATH": "/tmp/injected"})

	assert env["PATH"] == str(tmp_path)
	assert env["HOME"] == str(tmp_path)
	assert env["KYCORTEX_SANDBOX_ROOT"] == str(tmp_path)
	assert env["PYTHONDONTWRITEBYTECODE"] == "1"
	assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
	assert "PYTHONPATH" not in env
	assert (tmp_path / "sitecustomize.py").read_text(encoding="utf-8").startswith("import asyncio\n")


def test_build_generated_test_env_omits_sandbox_files_when_disabled(tmp_path):
	policy = ExecutionSandboxPolicy(enabled=False)
	env = build_generated_test_env(tmp_path, policy, host_env={"PATH": "/usr/bin", "PYTHONPATH": "/tmp/injected"})

	assert env["PATH"] == "/usr/bin"
	assert "KYCORTEX_SANDBOX_ROOT" not in env
	assert "XDG_CONFIG_HOME" not in env
	assert "PYTHONPATH" not in env
	assert not (tmp_path / "sitecustomize.py").exists()


def test_build_sandbox_preexec_fn_applies_limits_with_injected_modules():
	policy = ExecutionSandboxPolicy(enabled=True, max_cpu_seconds=5.2, max_memory_mb=128)
	recorded_calls: list[tuple[object, tuple[int, int]]] = []
	recorded_umasks: list[int] = []
	fake_os = SimpleNamespace(name="posix", umask=lambda value: recorded_umasks.append(value) or 0)
	fake_resource = SimpleNamespace(
		RLIMIT_CPU="cpu",
		RLIMIT_AS="as",
		RLIMIT_CORE="core",
		RLIMIT_FSIZE="fsize",
		setrlimit=lambda limit, values: recorded_calls.append((limit, values)),
	)

	preexec = build_sandbox_preexec_fn(policy, os_module=fake_os, resource_module=fake_resource)

	assert callable(preexec)
	preexec()
	assert recorded_umasks == [0o077]
	assert recorded_calls == [
		("cpu", (5, 5)),
		("as", (134217728, 134217728)),
		("core", (0, 0)),
		("fsize", (1048576, 1048576)),
	]


def test_write_generated_runner_helpers_persist_scripts(tmp_path):
	pytest_runner = write_generated_test_runner(tmp_path, "generated_tests.py", sandbox_enabled=True)
	import_runner = write_generated_import_runner(tmp_path, "generated_module.py", sandbox_enabled=False)

	assert pytest_runner.name == "_kycortex_run_pytest.py"
	assert import_runner.name == "_kycortex_import_module.py"
	assert "generated_tests.py" in pytest_runner.read_text(encoding="utf-8")
	assert "generated_module.py" in import_runner.read_text(encoding="utf-8")


def test_execute_generated_tests_returns_unavailable_when_pytest_missing_directly(tmp_path):
	policy = KYCortexConfig(output_dir=str(tmp_path / "output")).execution_sandbox_policy()

	result = execute_generated_tests(
		"generated_module.py",
		"def ok():\n    return 1\n",
		"generated_tests.py",
		"def test_ok():\n    assert True\n",
		policy,
		pytest_spec_finder=lambda name: None,
	)

	assert result == {
		"available": False,
		"ran": False,
		"returncode": None,
		"summary": "pytest is not installed in the current environment",
	}


def test_execute_generated_module_import_redacts_sensitive_output_directly(tmp_path):
	policy = KYCortexConfig(output_dir=str(tmp_path / "output")).execution_sandbox_policy()

	def fake_run(*args, **kwargs):
		return SimpleNamespace(
			returncode=1,
			stdout="api_key=sk-secret-123456",
			stderr="Authorization: Bearer sk-ant-secret-987654",
		)

	result = execute_generated_module_import(
		"generated_module.py",
		"def ok():\n    return 1\n",
		policy,
		subprocess_run=fake_run,
	)

	assert result["ran"] is True
	assert result["returncode"] == 1
	assert "[REDACTED]" in result["stdout"]
	assert "[REDACTED]" in result["stderr"]
	assert "sk-secret-123456" not in result["summary"]


def test_sandbox_security_violation_detects_blocked_message():
	assert sandbox_security_violation(RuntimeError("sandbox policy blocked filesystem write outside sandbox root")) is True
	assert sandbox_security_violation(RuntimeError("provider temporarily unavailable")) is False


def test_validation_reporting_detects_structural_truncation_and_completion_summary():
	assert looks_structurally_truncated("label:\n", "expected an indented block") is True
	assert looks_structurally_truncated("value = 1\n", "invalid syntax") is False
	assert completion_validation_issue({"hit_token_limit": True}) == "output likely truncated at the completion token limit"
	assert completion_diagnostics_summary({"done_reason": "stop"}) == "provider termination reason recorded"


def test_completion_diagnostics_from_provider_call_marks_length_limited_output_as_truncated():
	diagnostics = completion_diagnostics_from_provider_call(
		{
			"requested_max_tokens": 900,
			"finish_reason": "length",
			"usage": {"output_tokens": 900},
		},
		syntax_ok=False,
	)

	assert diagnostics == {
		"requested_max_tokens": 900,
		"output_tokens": 900,
		"finish_reason": "length",
		"stop_reason": None,
		"done_reason": None,
		"hit_token_limit": True,
		"likely_truncated": True,
	}


def test_build_code_validation_summary_reports_import_and_contract_failures_directly():
	summary = build_code_validation_summary(
		{"syntax_ok": True, "third_party_imports": [], "line_count": 12, "line_budget": 20},
		"failed import",
		completion_diagnostics={"output_tokens": 120},
		import_validation={"ran": True, "returncode": 1, "summary": "TypeError"},
		task_public_contract_preflight={
			"anchor_present": True,
			"passed": False,
			"public_facade": "ComplianceIntakeService",
			"issues": ["missing public facade ComplianceIntakeService"],
		},
	)

	assert "Line count: 12/20" in summary
	assert "Completion diagnostics: token usage recorded" in summary
	assert "Module import: FAIL" in summary
	assert "Task public contract: FAIL" in summary


def test_build_test_validation_summary_reports_warning_override_and_pytest_details_directly():
	summary = build_test_validation_summary(
		{
			"syntax_ok": True,
			"constructor_arity_mismatches": ["MyClass (line 5)"],
		},
		{
			"available": True,
			"ran": True,
			"returncode": 0,
			"summary": "1 passed",
		},
	)

	assert "Constructor arity mismatches (warning): MyClass (line 5)" in summary
	assert "Pytest execution: PASS" in summary
	assert summary.endswith("- Verdict: PASS (warnings overridden by pytest)")


def test_python_import_roots_collects_top_level_imports_directly():
	code = "import os\nimport json.decoder\nfrom pathlib import Path\nfrom . import sibling\n"

	assert python_import_roots(code) == {"os", "json", "pathlib"}
	assert python_import_roots("") == set()
	assert python_import_roots(42) == set()


def test_dependency_analysis_helpers_normalize_and_flag_provenance_directly():
	analysis = analyze_dependency_manifest(
		"requests @ https://example.com/requests.whl\nPyYAML>=6.0",
		{"third_party_imports": ["requests", "yaml"]},
	)

	assert normalize_package_name("scikit-learn") == "scikit_learn"
	assert normalize_import_name("yaml") == "pyyaml"
	assert analysis["declared_packages"] == ["requests", "PyYAML"]
	assert analysis["missing_manifest_entries"] == []
	assert analysis["provenance_violations"] == ["requests @ https://example.com/requests.whl"]


def test_build_dependency_validation_summary_formats_failures_directly():
	summary = build_dependency_validation_summary(
		{
			"required_imports": ["requests"],
			"declared_packages": ["urllib3"],
			"missing_manifest_entries": ["requests"],
			"unused_manifest_entries": ["urllib3"],
			"is_valid": False,
		}
	)

	assert summary == (
		"Dependency manifest validation:\n"
		"- Required third-party imports: requests\n"
		"- Declared packages: urllib3\n"
		"- Missing manifest entries: requests\n"
		"- Unused manifest entries: urllib3\n"
		"- Provenance violations: none\n"
		"- Verdict: FAIL"
	)


def test_output_helpers_summarize_and_classify_titles_directly():
	assert summarize_output("   ") == ""
	assert summarize_output("  first line  \nsecond line") == "first line"
	assert len(summarize_output("x" * 200)) == 120
	assert semantic_output_key("unknown", "Architecture Review") == "architecture"
	assert semantic_output_key("unknown", "Misc Task") is None


def test_output_helpers_normalize_and_restore_unredacted_results_directly():
	normalized = normalize_agent_result("  first line  \nsecond line")
	assert normalized.summary == "first line"
	assert normalized.raw_content == "  first line  \nsecond line"

	structured = AgentOutput(summary="ready", raw_content="RAW")
	assert normalize_agent_result(structured) is structured

	class FakeAgent:
		def _consume_last_unredacted_output(self):
			return AgentOutput(summary="unredacted", raw_content="SECRET")

	assert unredacted_agent_result(FakeAgent(), structured).summary == "unredacted"
	assert unredacted_agent_result(object(), structured) is structured


def test_ast_tools_render_names_and_detect_pytest_fixtures_directly():
	node = ast.Attribute(value=ast.Attribute(value=ast.Name("pkg"), attr="module"), attr="Class")
	assert ast_name(node) == "pkg.module.Class"
	assert ast_name(ast.Constant("x")) == "x"

	fixture_function = ast.parse("@pytest.fixture\ndef sample():\n    return 1\n").body[0]
	assert isinstance(fixture_function, ast.FunctionDef)
	assert is_pytest_fixture(fixture_function) is True

	call_node = ast.Call(func=ast.Attribute(value=ast.Name("service"), attr="validate_request"), args=[ast.Constant("payload")], keywords=[])
	keyword_only_call = ast.Call(func=ast.Name("process_request"), args=[], keywords=[ast.keyword(arg="payload", value=ast.Name("payload"))])
	assert callable_name(call_node) == "validate_request"
	assert attribute_chain(call_node.func) == "service.validate_request"
	assert expression_root_name(call_node.func) == "service"
	assert render_expression(call_node) == "service.validate_request('payload')"
	assert isinstance(first_call_argument(keyword_only_call), ast.Name)
	assert ast_name(ast.Subscript(value=ast.Name("Payload"), slice=ast.Constant(None))) == "Payload"
	assert callable_name(ast.Call(func=ast.Lambda(args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=ast.Constant(None)), args=[], keywords=[])) == ""
	assert attribute_chain(ast.Constant(1)) == ""
	assert expression_root_name(ast.Constant(1)) is None
	assert first_call_argument(ast.Call(func=ast.Name("noop"), args=[], keywords=[])) is None


def test_workflow_acceptance_helpers_build_lists_and_zero_budget_safety_directly():
	project = ProjectState(project_name="Demo", goal="Build demo")
	project.add_task(
		Task(
			id="code",
			title="Implementation",
			description="Implement",
			assigned_to="code_engineer",
			required_for_acceptance=True,
		)
	)
	project.add_task(
		Task(
			id="docs",
			title="Documentation",
			description="Document",
			assigned_to="docs_writer",
		)
	)
	project.tasks[0].status = TaskStatus.DONE.value
	project.tasks[1].status = TaskStatus.FAILED.value
	project.tasks[1].last_error_category = FailureCategory.SANDBOX_SECURITY_VIOLATION.value

	required_lists = task_acceptance_lists(project, "required_tasks")
	assert required_lists["evaluated_task_ids"] == ["code"]
	assert required_lists["completed_task_ids"] == ["code"]

	observed_categories = observed_failure_categories(project)
	assert observed_categories == {FailureCategory.SANDBOX_SECURITY_VIOLATION.value}

	evaluation = evaluate_workflow_acceptance(
		project,
		"required_tasks",
		frozenset({FailureCategory.SANDBOX_SECURITY_VIOLATION.value}),
	)
	assert evaluation["accepted"] is False
	assert evaluation["failed_lane_ids"] == ["real_workflow", "safety"]
	assert evaluation["acceptance_lanes"]["productivity"]["accepted"] is True
	assert evaluation["acceptance_lanes"]["safety"].get("zero_budget_failure_categories") == [
		FailureCategory.SANDBOX_SECURITY_VIOLATION.value
	]


def test_validate_agent_resolution_raises_for_unknown_registry_entry_directly():
	project = ProjectState(project_name="Demo", goal="Build demo")
	project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))

	class EmptyRegistry:
		def has(self, _assigned_to: str) -> bool:
			return False

	with pytest.raises(AgentExecutionError, match="unknown agent 'architect'"):
		validate_agent_resolution(EmptyRegistry(), project)


def test_private_file_hardening_raises_agent_error_on_chmod_failure(tmp_path, monkeypatch):
	artifact_path = tmp_path / "artifact.txt"
	artifact_path.write_text("secret", encoding="utf-8")

	def fail_chmod(_self: object, _mode: int) -> None:
		raise OSError("denied")

	monkeypatch.setattr(type(artifact_path), "chmod", fail_chmod)

	with pytest.raises(AgentExecutionError, match="could not harden file permissions"):
		harden_private_file_permissions(artifact_path)


def test_private_directory_hardening_raises_agent_error_on_chmod_failure(tmp_path, monkeypatch):
	directory_path = tmp_path / "artifacts"
	directory_path.mkdir()

	def fail_chmod(_self: object, _mode: int) -> None:
		raise OSError("denied")

	monkeypatch.setattr(type(directory_path), "chmod", fail_chmod)

	with pytest.raises(AgentExecutionError, match="could not harden directory permissions"):
		harden_private_directory_permissions(directory_path)


def test_private_permission_hardening_skips_non_posix_and_attribute_chain_handles_none(tmp_path, monkeypatch):
	monkeypatch.setattr(os, "name", "nt", raising=False)

	harden_private_file_permissions(tmp_path / "missing.txt")
	harden_private_directory_permissions(tmp_path / "missing-dir")

	assert attribute_chain(None) == ""


def test_build_repair_instruction_specializes_missing_import_directly():
	instruction = build_repair_instruction(
		"code-task",
		"code_validation",
		last_error="NameError: name 'logging' is not defined",
		failed_code="logger = logging.getLogger(__name__)",
		validation={},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: ("logging", "logger = logging.getLogger(__name__)"),
		plain_class_field_default_factory_details=lambda error, code: None,
		test_validation_has_only_warnings=lambda validation: False,
	)

	assert "references logging during module import but never imports it" in instruction
	assert "logger = logging.getLogger(__name__)" in instruction


def test_build_repair_instruction_uses_pytest_warning_focus_directly():
	instruction = build_repair_instruction(
		"tests-task",
		"test_validation",
		last_error="",
		failed_code="",
		validation={
			"test_analysis": {"type_mismatches": ["str vs int at line 10"]},
			"test_execution": {"ran": True, "returncode": 1, "summary": "1 failed"},
		},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: None,
		plain_class_field_default_factory_details=lambda error, code: None,
		test_validation_has_only_warnings=lambda validation: True,
	)

	assert "type mismatches in test arguments" in instruction
	assert "Use the correct argument types" in instruction


def test_build_repair_instruction_covers_missing_import_plain_class_and_warning_only_variants_directly():
	instruction = build_repair_instruction(
		"code-task",
		"code_validation",
		last_error="NameError: name 'logging' is not defined",
		failed_code="logger = build_logger()",
		validation={},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: ("logging", "logger = build_logger()"),
		plain_class_field_default_factory_details=lambda error, code: None,
		test_validation_has_only_warnings=lambda validation: False,
	)

	assert "Do not return that line unchanged" in instruction
	assert "logger = build_logger()" in instruction

	plain_class_instruction = build_repair_instruction(
		"code-task",
		"code_validation",
		last_error="AttributeError: 'Field' object has no attribute 'append'",
		failed_code="class AuditService:\n    audit_history = field(default_factory=list)\n",
		validation={},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: None,
		plain_class_field_default_factory_details=lambda error, code: ("AuditService", "audit_history"),
		test_validation_has_only_warnings=lambda validation: False,
	)

	assert "AuditService.audit_history" in plain_class_instruction
	assert "Initialize self.audit_history inside __init__" in plain_class_instruction

	warning_only_instruction = build_repair_instruction(
		"tests-task",
		"test_validation",
		last_error="",
		failed_code="",
		validation={
			"test_analysis": {"type_mismatches": []},
			"test_execution": {"ran": True, "returncode": 1, "summary": "1 failed"},
		},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: None,
		plain_class_field_default_factory_details=lambda error, code: None,
		test_validation_has_only_warnings=lambda validation: True,
	)

	assert "Focus on the actual pytest failure details" in warning_only_instruction


def test_build_repair_instruction_runtime_reads_code_artifact_directly():
	instruction = build_repair_instruction_runtime(
		SimpleNamespace(id="code-task", last_error="NameError: name 'logging' is not defined"),
		FailureCategory.CODE_VALIDATION.value,
		failed_artifact_content=lambda task, artifact_type: "logger = logging.getLogger(__name__)",
		artifact_type=ArtifactType.CODE,
		validation_payload=lambda task: {},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: ("logging", "logger = logging.getLogger(__name__)"),
		plain_class_field_default_factory_details=lambda error, code: None,
		test_validation_has_only_warnings=lambda validation: False,
	)

	assert "references logging during module import but never imports it" in instruction


def test_build_code_repair_instruction_from_test_failure_handles_duplicate_constructor_binding_directly():
	instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: ("ComplianceRequest", "details"),
		duplicate_constructor_argument_call_hint=lambda summary, code: "ComplianceRequest(request_id, details, **request.details)",
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: "ComplianceRequest(request_id=request.request_id, details=request.details)",
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: None,
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: None,
		internal_constructor_strictness_details=lambda summary, code: None,
	)

	assert "passes details twice to ComplianceRequest(...)" in instruction
	assert "ComplianceRequest(request_id, details, **request.details)" in instruction
	assert "ComplianceRequest(request_id=request.request_id, details=request.details)" in instruction


def test_build_code_repair_instruction_from_test_failure_uses_generic_strictness_fallback_directly():
	instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: None,
		duplicate_constructor_argument_call_hint=lambda summary, code: None,
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: None,
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: None,
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: None,
		internal_constructor_strictness_details=lambda summary, code: ("ComplianceRequest", ["details", "status"], ["request_id"]),
	)

	assert "ComplianceRequest(...) still requires details, status" in instruction
	assert "validator only requires request_id" in instruction


def test_build_code_repair_instruction_from_test_failure_covers_remaining_branch_variants_directly():
	missing_attribute_instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: None,
		duplicate_constructor_argument_call_hint=lambda summary, code: None,
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: None,
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: ("VendorProfile", "audit_log", []),
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: None,
		internal_constructor_strictness_details=lambda summary, code: None,
	)

	assert "that attribute is not defined on the returned object" in missing_attribute_instruction
	assert "VendorProfile must declare audit_log" in missing_attribute_instruction

	invalid_outcome_instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: None,
		duplicate_constructor_argument_call_hint=lambda summary, code: None,
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: None,
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: None,
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: (
			["test_invalid_path"],
			"audit_log",
			"TriageOutcome(outcome='invalid', audit_log='')",
			False,
		),
		internal_constructor_strictness_details=lambda summary, code: None,
	)

	assert "returns TriageOutcome(outcome='invalid', audit_log='') with an empty audit_log" in invalid_outcome_instruction


def test_build_code_repair_instruction_from_test_failure_runtime_reads_code_artifact_directly():
	instruction = build_code_repair_instruction_from_test_failure_runtime(
		SimpleNamespace(id="code_task"),
		"TypeError: Example.__init__() got multiple values for argument 'status'",
		failed_artifact_content=lambda task, artifact_type: "Example(status=request.status, **request.details)",
		artifact_type=ArtifactType.CODE,
		duplicate_constructor_argument_details=lambda summary: ("Example", "status"),
		duplicate_constructor_argument_call_hint=lambda summary, content: "Example(status=request.status, **request.details)",
		duplicate_constructor_explicit_rewrite_hint=lambda summary, content: "Example(status=request.status)",
		plain_class_field_default_factory_details=lambda *_args: None,
		missing_object_attribute_details=lambda *_args: None,
		suggest_declared_attribute_replacement=lambda *_args: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda *_args: None,
		invalid_outcome_missing_audit_trail_details=lambda *_args: None,
		internal_constructor_strictness_details=lambda *_args: None,
	)

	assert "status twice" in instruction

	strictness_instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: None,
		duplicate_constructor_argument_call_hint=lambda summary, code: None,
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: None,
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: None,
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: None,
		internal_constructor_strictness_details=lambda summary, code: ("ComplianceRequest", ["details"], []),
	)

	assert "makes ComplianceRequest(...) require details" in strictness_instruction
	assert "instead of demanding new input fields" in strictness_instruction


def test_missing_import_nameerror_details_extracts_symbol_and_line_directly():
	details = missing_import_nameerror_details(
		"Generated code validation:\n- Module import: FAIL\n- Import summary: NameError: name 'logging' is not defined\n- Verdict: FAIL",
		"from dataclasses import dataclass\nlogger = logging.getLogger(__name__)\n",
	)

	assert details == ("logging", "logger = logging.getLogger(__name__)")


def test_required_field_and_nested_wrapper_detection_work_directly():
	failed_code = (
		"def validate_request(request):\n"
		"    required_fields = {'request_id', 'request_type', 'details'}\n"
		"    return required_fields.issubset(request.details)\n"
	)

	assert required_field_list_from_failed_artifact(failed_code) == ["request_id", "request_type", "details"]
	assert nested_payload_wrapper_field_validation_details(
		"FAILED tests_tests.py::test_happy_path - ValueError: Invalid request\nFAILED tests_tests.py::test_batch_processing - ValueError: Invalid request",
		failed_code,
	) == (
		"details",
		["request_id", "request_type", "details"],
		"return required_fields.issubset(request.details)",
	)


def test_plain_class_field_default_factory_details_detects_runtime_placeholder_directly():
	failed_code = (
		"from dataclasses import field\n\n"
		"class ComplianceIntakeService:\n"
		"    audit_history: list[dict] = field(default_factory=list)\n"
	)

	assert plain_class_field_default_factory_details(
		"AttributeError: 'Field' object has no attribute 'append'",
		failed_code,
	) == ("ComplianceIntakeService", "audit_history")


def test_missing_object_attribute_and_replacement_helpers_work_directly():
	failed_code = (
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class VendorProfile:\n"
		"    certifications: list[str]\n"
		"    incidents: list[str]\n"
	)

	attribute_details = missing_object_attribute_details(
		"AttributeError: 'VendorProfile' object has no attribute 'expired_certifications'",
		failed_code,
	)
	assert attribute_details is not None
	class_name, attribute_name, class_fields = attribute_details

	assert (class_name, attribute_name) == ("VendorProfile", "expired_certifications")
	assert class_fields == ["certifications", "incidents"]
	assert suggest_declared_attribute_replacement(attribute_name, class_fields) == "certifications"
	assert render_name_list(class_fields) == "certifications and incidents"


def test_duplicate_constructor_rewrite_hint_and_invalid_audit_detection_work_directly():
	failed_code = (
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class VendorProfile:\n"
		"    vendor_id: str\n"
		"    service_category: str\n"
		"    due_diligence_evidence: list[str]\n"
		"    is_sanctioned: bool\n\n"
		"def validate_request(request):\n"
		"    required_fields = ['vendor_id', 'service_category', 'due_diligence_evidence']\n"
		"    return all(field in request.details for field in required_fields)\n\n"
		"def build_vendor_profile(request):\n"
		"    vendor_id = request.details['vendor_id']\n"
		"    return VendorProfile(vendor_id, **request.details)\n"
	)

	assert duplicate_constructor_explicit_rewrite_hint(
		"TypeError: VendorProfile.__init__() got multiple values for argument 'vendor_id'",
		failed_code,
	) == (
		"VendorProfile(vendor_id=vendor_id, service_category=request.details['service_category'], "
		"due_diligence_evidence=request.details['due_diligence_evidence'], "
		"is_sanctioned=request.details.get('is_sanctioned', False))"
	)

	invalid_path_code = (
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class TriageOutcome:\n"
		"    outcome: str\n"
		"    risk_score: float\n"
		"    audit_log: str = ''\n\n"
		"def handle_request(request):\n"
		"    return TriageOutcome(outcome='invalid', risk_score=0.0)\n"
	)
	tests_code = (
		"def test_validation_failure(service, invalid_request):\n"
		"    result = service.handle_request(invalid_request)\n"
		"    assert result.outcome == 'invalid'\n"
		"    assert len(result.audit_log) > 0\n"
	)

	assert invalid_outcome_missing_audit_trail_details(
		"FAILED tests_tests.py::test_validation_failure - AssertionError: assert 0 > 0",
		tests_code,
		invalid_path_code,
	) == (
		["test_validation_failure"],
		"audit_log",
		"TriageOutcome(outcome='invalid', risk_score=0.0)",
		True,
	)

	invalid_assert = ast.parse("result.outcome == 'invalid'", mode="eval").body
	assert isinstance(invalid_assert, ast.Compare)
	assert compare_mentions_invalid_literal(invalid_assert) is True
	invalid_test = ast.parse(
		"def test_validation_failure():\n"
		"    assert result.outcome == 'invalid'\n"
		"    assert len(result.audit_log) > 0\n"
	).body[0]
	assert isinstance(invalid_test, ast.FunctionDef)
	assert test_function_targets_invalid_path(invalid_test) is True
	assert attribute_is_field_reference(ast.parse("result.audit_log", mode="eval").body, "audit_log") is True
	assert is_len_of_field_reference(ast.parse("len(result.audit_log)", mode="eval").body, "audit_log") is True
	assert test_requires_non_empty_result_field(invalid_test, "audit_log") is True
	assert ast_is_empty_literal(ast.Dict(keys=[], values=[])) is True
	assert class_field_uses_empty_default(invalid_path_code, "TriageOutcome", "audit_log") is True
	assert invalid_outcome_audit_return_details(invalid_path_code, "audit_log") == (
		"TriageOutcome(outcome='invalid', risk_score=0.0)",
		True,
	)


def test_datetime_repair_signals_detect_missing_imports_directly():
	failed_tests = (
		"from code_implementation import ComplianceRequest\n\n"
		"def test_request():\n"
		"    request = ComplianceRequest(request_id='req-1', timestamp=datetime.now())\n"
	)

	assert content_has_matching_datetime_import("from datetime import datetime\n") is True
	assert validation_summary_has_missing_datetime_import_issue(
		"Generated test validation:\n- Undefined local names: datetime (line 5)\n- Verdict: FAIL",
		failed_tests,
	) is True
	assert implementation_prefers_direct_datetime_import("from datetime import datetime\n\ndef build():\n    return datetime.now()\n") is True


def test_required_evidence_repair_signals_detect_incomplete_payloads_directly():
	implementation_code = (
		"def validate_request(request):\n"
		"    required_evidence = ['ID', 'Address', 'Proof of Income']\n"
		"    return all(item in request.details.get('documents', []) for item in required_evidence)\n"
	)
	failed_tests = (
		"def test_happy_path():\n"
		"    request = {'documents': ['ID']}\n"
		"    assert len(service.risk_scores) == 1\n"
	)

	assert implementation_required_evidence_items(implementation_code) == ["ID", "Address", "Proof of Income"]
	assert content_has_incomplete_required_evidence_payload(failed_tests, implementation_code) is True
	assert validation_summary_has_required_evidence_runtime_issue(
		"Generated test validation:\n- Pytest execution: FAIL\n- Pytest failure details: FAILED tests_tests.py::test_happy_path - AssertionError: assert 0 == 1\n- Verdict: FAIL",
		"risk_scores = []\n" + failed_tests,
		implementation_code,
	) is True


def test_module_defined_symbol_names_and_helper_alias_detection_work_directly():
	implementation_code = (
		"class ComplianceIntakeService:\n"
		"    pass\n\n"
		"def validate_request(request):\n"
		"    return True\n"
	)
	validation_summary = (
		"Generated test validation:\n"
		"- Undefined local names: AuditLogger (line 6), validate_request (line 9)\n"
		"- Verdict: FAIL"
	)

	assert module_defined_symbol_names(implementation_code) == ["ComplianceIntakeService", "validate_request"]
	assert validation_summary_helper_alias_names(validation_summary, implementation_code) == ["AuditLogger"]


def test_repair_test_analysis_helpers_cover_duplicate_blank_and_non_string_inputs_directly():
	assert normalized_helper_surface_symbols([1, "AuditLogger (line 2)", "AuditLogger (line 4)", " "]) == ["AuditLogger"]
	assert module_defined_symbol_names("def validate_request():\n    return True\n\ndef validate_request():\n    return False\n") == ["validate_request"]
	assert is_helper_alias_like_name("   ") is False


def test_previous_valid_test_surface_extracts_member_calls_and_constructor_keywords_directly():
	failed_tests = (
		"from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
		"def test_happy_path():\n"
		"    service = ComplianceIntakeService()\n"
		"    request = ComplianceRequest(request_id='req-1', request_type='screening', details={}, timestamp=1.0)\n"
		"    service.handle_request(request)\n"
	)

	member_calls, constructor_keywords = previous_valid_test_surface(
		failed_tests,
		["ComplianceIntakeService", "ComplianceRequest"],
	)

	assert member_calls == {"ComplianceIntakeService": ["handle_request"]}
	assert constructor_keywords == {
		"ComplianceRequest": ["request_id", "request_type", "details", "timestamp"]
	}


def test_analyze_test_repair_surface_collects_reusable_imports_and_alias_drift_directly():
	implementation_code = (
		"class AuditLogger:\n"
		"    pass\n\n"
		"class ComplianceIntakeService:\n"
		"    def handle_request(self, request):\n"
		"        return None\n"
	)
	validation_summary = (
		"Generated test validation:\n"
		"- Imported module symbols: ComplianceIntakeService\n"
		"- Undefined local names: AuditLogger (line 6), AuditService (line 8), pytest (line 10)\n"
		"- Unknown module symbols: none\n"
		"- Verdict: FAIL"
	)
	failed_tests = (
		"from code_implementation import ComplianceIntakeService\n\n"
		"def test_happy_path():\n"
		"    service = ComplianceIntakeService()\n"
		"    service.handle_request(None)\n"
	)

	analysis = analyze_test_repair_surface(
		validation_summary,
		implementation_code,
		failed_tests,
	)

	assert analysis.imported_module_symbols == ["ComplianceIntakeService"]
	assert analysis.undefined_available_module_symbols == ["AuditLogger"]
	assert analysis.helper_alias_names == ["AuditService"]
	assert analysis.previous_member_calls == {"ComplianceIntakeService": ["handle_request"]}


def test_repair_surface_helpers_cover_invalid_inputs_and_inline_constructor_calls_directly():
	assert validation_summary_helper_alias_names(None, "") == []
	assert previous_valid_test_surface("def broken(:\n", ["ComplianceRequest"]) == ({}, {})

	member_calls, constructor_keywords = previous_valid_test_surface(
		(
			"from code_implementation import ComplianceRequest\n\n"
			"def test_inline_call():\n"
			"    ComplianceRequest(request_id='req-1').validate_request()\n"
		),
		["ComplianceRequest"],
	)

	assert member_calls == {"ComplianceRequest": ["validate_request"]}
	assert constructor_keywords == {"ComplianceRequest": ["request_id"]}
	analysis = analyze_test_repair_surface(None)
	assert analysis.imported_module_symbols == []
	assert analysis.previous_constructor_keywords == {}
	assert qa_repair_should_reuse_failed_test_artifact(None) is True


def test_qa_repair_should_not_reuse_failed_suite_for_alias_drift_directly():
	implementation_code = (
		"class AuditLogger:\n"
		"    pass\n\n"
		"class ComplianceIntakeService:\n"
		"    pass\n"
	)
	validation_summary = (
		"Generated test validation:\n"
		"- Imported module symbols: ComplianceIntakeService\n"
		"- Undefined local names: AuditService (line 8)\n"
		"- Verdict: FAIL"
	)

	assert not qa_repair_should_reuse_failed_test_artifact(
		validation_summary,
		implementation_code,
	)


def test_qa_repair_should_reuse_failed_suite_for_missing_real_module_imports_directly():
	implementation_code = (
		"class AuditLogger:\n"
		"    pass\n\n"
		"class ComplianceIntakeService:\n"
		"    pass\n"
	)
	validation_summary = (
		"Generated test validation:\n"
		"- Imported module symbols: ComplianceIntakeService\n"
		"- Undefined local names: AuditLogger (line 6)\n"
		"- Verdict: FAIL"
	)
	failed_tests = (
		"from code_implementation import ComplianceIntakeService\n\n"
		"def test_happy_path():\n"
		"    service = ComplianceIntakeService()\n"
	)

	assert qa_repair_should_reuse_failed_test_artifact(
		validation_summary,
		implementation_code,
		failed_tests,
	)


def test_failing_pytest_test_names_deduplicates_directly():
	validation_summary = (
		"Generated test validation:\n"
		"- Pytest failure details: FAILED tests_tests.py::test_happy_path - AssertionError; "
		"FAILED tests_tests.py::test_batch_processing - AssertionError; "
		"FAILED tests_tests.py::test_happy_path - AssertionError\n"
		"- Verdict: FAIL"
	)

	assert failing_pytest_test_names(validation_summary) == [
		"test_happy_path",
		"test_batch_processing",
	]


def test_build_runtime_only_test_repair_lines_handles_helper_runtime_focus_directly():
	lines = build_runtime_only_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- imported module symbols: validate_request, score_request, log_audit\n"
			"- unknown module symbols: none\n"
			"- constructor arity mismatches: none\n"
			"- pytest execution: fail\n"
		),
		failed_content_lower="def test_log_audit():\n    assert len(service.audit_logs) == 3\n",
		imported_module_symbols=["validate_request", "score_request", "log_audit"],
		unknown_module_symbols=[],
		previous_member_calls={},
		previous_constructor_keywords={},
		required_evidence_runtime_issue=False,
		required_evidence_items=[],
	)

	assert any("collapse the suite to exactly three tests" in line for line in lines)
	assert any("Delete standalone score_request, log_audit, and extra invalid-case tests" in line for line in lines)
	assert any("When behavior is uncertain, prefer stable invariants" in line for line in lines)


def test_build_code_validation_repair_lines_handles_constructor_and_attribute_guidance_directly():
	lines = build_code_validation_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- pytest execution: fail\n"
			"- pytest failure details: failed tests_tests.py::test_happy_path - typeerror: vendorprofile.__init__() got multiple values for argument 'vendor_id'\n"
		),
		failed_content_lower="return vendorprofile(vendor_id, **request.details)\nreturn profile.expired_certifications\n",
		dataclass_order_examples=[],
		duplicate_constructor_argument_details=("VendorProfile", "vendor_id"),
		duplicate_constructor_call_hint="VendorProfile(vendor_id, **request.details)",
		duplicate_constructor_explicit_rewrite_hint=(
			"VendorProfile(vendor_id=vendor_id, service_category=request.details['service_category'], "
			"due_diligence_evidence=request.details['due_diligence_evidence'], "
			"is_sanctioned=request.details.get('is_sanctioned', False))"
		),
		missing_attribute_details=("VendorProfile", "expired_certifications", ["certifications", "incidents"]),
		nested_payload_wrapper_details=None,
		constructor_strictness_details=None,
		plain_class_field_details=None,
		missing_import_details=None,
	)

	assert any("got multiple values for argument 'vendor_id'" in line for line in lines)
	assert any("VendorProfile(vendor_id, **request.details)" in line for line in lines)
	assert any("VendorProfile currently defines certifications and incidents" in line for line in lines)
	assert any("Prefer replacing .expired_certifications with .certifications" in line for line in lines)


def test_build_code_validation_repair_lines_handles_dataclass_import_and_line_budget_directly():
	lines = build_code_validation_repair_lines(
		summary_lower=(
			"generated code validation:\n"
			"- module import: fail\n"
			"- import summary: typeerror: non-default argument 'details' follows default argument\n"
			"- import summary: nameerror: name 'logging' is not defined\n"
			"- line count: 312/300\n"
			"- verdict: fail\n"
		),
		failed_content_lower="logger = logging.getlogger(__name__)\n",
		dataclass_order_examples=[
			"The current failed artifact still has this ordering bug in ReviewAction. Rewrite it as ReviewAction(action_id, action_type, details, timestamp=field(default_factory=datetime.now))."
		],
		duplicate_constructor_argument_details=None,
		duplicate_constructor_call_hint="",
		duplicate_constructor_explicit_rewrite_hint="",
		missing_attribute_details=None,
		nested_payload_wrapper_details=None,
		constructor_strictness_details=None,
		plain_class_field_details=None,
		missing_import_details=("logging", "logger = logging.getLogger(__name__)"),
	)

	assert any("reorder the fields so every required non-default field appears before any field with a default" in line for line in lines)
	assert any("ReviewAction(action_id, action_type, details, timestamp=field(default_factory=datetime.now))" in line for line in lines)
	assert any("add `import logging` before first use" in line for line in lines)
	assert any("Rewrite the full module smaller and leave clear headroom below the reported line ceiling" in line for line in lines)


def test_build_code_validation_repair_lines_handles_nested_payload_and_timezone_guidance_directly():
	lines = build_code_validation_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- pytest execution: fail\n"
			"- pytest failure details: failed tests_tests.py::test_batch_processing - valueerror: invalid return case\n"
			"- pytest failure details: failed tests_tests.py::test_risk_scoring_with_certifications - typeerror: can't compare offset-naive and offset-aware datetimes\n"
		),
		failed_content_lower="required_fields = {'request_id', 'request_type', 'details'}\nreturn required_fields.issubset(request.details)\n",
		dataclass_order_examples=[],
		duplicate_constructor_argument_details=None,
		duplicate_constructor_call_hint="",
		duplicate_constructor_explicit_rewrite_hint="",
		missing_attribute_details=None,
		nested_payload_wrapper_details=("details", ["request_id", "request_type", "details"], "return required_fields.issubset(request.details)"),
		constructor_strictness_details=None,
		plain_class_field_details=None,
		missing_import_details=None,
	)

	assert any("treats request_id, request_type, and details as required keys inside request.details" in line for line in lines)
	assert any("Do not return the broken validation line `return required_fields.issubset(request.details)` unchanged" in line for line in lines)
	assert any("Normalize every datetime comparison to one timezone convention before comparing timestamps." in line for line in lines)


def test_build_code_validation_repair_lines_covers_remaining_guidance_variants_directly():
	lines = build_code_validation_repair_lines(
		summary_lower=(
			"generated code validation:\n"
			"- task public contract: fail\n"
			"- pytest failed: assertionerror: assert true is false\n"
			"- import summary: name 'field' is not defined\n"
			"- import summary: likely truncated\n"
			"- pytest failure details: failed tests_tests.py::test_happy_path - valueerror: invalid request\n"
			"- typeerror: request object is not subscriptable\n"
			"- nameerror: datetime is missing\n"
		),
		failed_content_lower="required_fields = {'request_id'}\nreturn required_fields.issubset(request.payload)\nreturn datetime.datetime.now()\n",
		dataclass_order_examples=[],
		duplicate_constructor_argument_details=None,
		duplicate_constructor_call_hint="",
		duplicate_constructor_explicit_rewrite_hint="",
		missing_attribute_details=("AuditResult", "audit_log", []),
		nested_payload_wrapper_details=("payload", ["request_id", "payload"], None),
		constructor_strictness_details=("ComplianceRequest", ["details", "status"], []),
		plain_class_field_details=("AuditService", "history"),
		missing_import_details=("timezone", None),
	)

	assert any("Treat the task public contract anchor as exact" in line for line in lines)
	assert any("If you keep .audit_log in the rewritten module, declare it on AuditResult" in line for line in lines)
	assert any("Do not make ComplianceRequest(...) additionally require details and status" in line for line in lines)
	assert any("import field explicitly from dataclasses" in line for line in lines)
	assert any("because timezone is referenced before it is imported" in line for line in lines)
	assert any("AuditService.history with field(...) on a non-dataclass class" in line for line in lines)
	assert any("rewrite the full module from the top instead of patching a partial tail" in line for line in lines)


def test_build_code_validation_repair_lines_covers_non_module_qualified_missing_import_directly():
	lines = build_code_validation_repair_lines(
		summary_lower="generated code validation:\n- module import: fail\n",
		failed_content_lower="logger = build_logger()\n",
		dataclass_order_examples=[],
		duplicate_constructor_argument_details=None,
		duplicate_constructor_call_hint="",
		duplicate_constructor_explicit_rewrite_hint="",
		missing_attribute_details=None,
		nested_payload_wrapper_details=None,
		constructor_strictness_details=None,
		plain_class_field_details=None,
		missing_import_details=("logging", "logger = build_logger()"),
	)

	assert any("references logging before it is imported" in line for line in lines)
	assert any("logger = build_logger()" in line for line in lines)


def test_build_runtime_only_test_repair_lines_handles_return_shape_and_did_not_raise_directly():
	lines = build_runtime_only_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- exact return-shape attribute assumption\n"
			"- pytest execution: fail\n"
			"- pytest failure details: failed tests_tests.py::test_validation_failure - failed: did not raise <class 'valueerror'>\n"
		),
		failed_content_lower="def test_happy_path():\n    assert outcome.request_id == '1'\n",
		imported_module_symbols=[],
		unknown_module_symbols=[],
		previous_member_calls={},
		previous_constructor_keywords={},
		required_evidence_runtime_issue=False,
		required_evidence_items=[],
	)

	assert any("wrapped object return shape" in line for line in lines)
	assert any("rebuild that scenario around an input that actually violates the current validator or contract" in line for line in lines)
	assert any("reserve pytest.raises only for an input that the current validator demonstrably rejects" in line for line in lines)


def test_build_structural_test_repair_lines_handles_budget_and_assertionless_guidance_directly():
	lines = build_structural_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- line count: 206/150\n"
			"- top-level test functions: 14/7 max\n"
			"- fixture count: 4/3\n"
			"- tests without assertion-like checks: test_happy_path (line 5), test_batch_processing (line 16)\n"
		),
		failed_content_lower="",
		imported_module_symbols=[],
		undefined_available_module_symbols=[],
		helper_alias_names=[],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=["test_happy_path (line 5)", "test_batch_processing (line 16)"],
		missing_datetime_import_issue=False,
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("Reduce scope aggressively: target 3 to 4 top-level tests" in line for line in lines)
	assert any("The validation summary already flagged these hollow top-level tests" in line for line in lines)
	assert any("discard the current pytest skeleton and rewrite the entire suite from scratch" in line for line in lines)


def test_build_structural_test_repair_lines_handles_alias_drift_and_missing_imports_directly():
	lines = build_structural_test_repair_lines(
		summary_lower="generated test validation:\n- undefined local names: datetime (line 10), auditlogger (line 6)\n- pytest execution: fail\n",
		failed_content_lower="timestamp=request.timestamp",
		imported_module_symbols=["AuditLog", "ComplianceIntakeService", "ComplianceRequest"],
		undefined_available_module_symbols=["AuditLogger"],
		helper_alias_names=["AuditLogger"],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=[],
		missing_datetime_import_issue=True,
		implementation_prefers_direct_datetime_import=True,
	)

	assert any("timestamp=fixed_time instead of timestamp=request.timestamp" in line for line in lines)
	assert any("The previous file referenced real module symbols without importing them: AuditLogger." in line for line in lines)
	assert any("undefined helper or collaborator aliases outside the documented import surface: AuditLogger" in line for line in lines)
	assert any("The current implementation already imports `from datetime import datetime`" in line for line in lines)


def test_build_structural_test_repair_lines_warns_on_helper_alias_near_match_pairs_directly():
	lines = build_structural_test_repair_lines(
		summary_lower="generated test validation:\n- undefined local names: AuditLogger\n",
		failed_content_lower="",
		imported_module_symbols=["AuditLoggerService"],
		undefined_available_module_symbols=[],
		helper_alias_names=["AuditLogger"],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=[],
		missing_datetime_import_issue=False,
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("AuditLogger -> AuditLoggerService" in line for line in lines)


def test_build_structural_test_repair_lines_handles_invalid_member_references_and_exact_alias_match_directly():
	lines = build_structural_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- undefined local names: AuditLogger\n"
			"- invalid member references: ComplianceIntakeService.submit, ComplianceIntakeService.submit_batch\n"
		),
		failed_content_lower="",
		imported_module_symbols=["AuditLogger", "ComplianceIntakeService"],
		undefined_available_module_symbols=[],
		helper_alias_names=["AuditLogger"],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=[],
		missing_datetime_import_issue=False,
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("invalid member references are reported" in line for line in lines)
	assert any("invalid-member list is empty" in line for line in lines)


def test_build_structural_test_repair_lines_handles_payload_and_fixture_constraints_directly():
	lines = build_structural_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- payload contract violations: get_logs payload missing required fields: action, record_id at line 14\n"
			"- non-batch sequence calls: score_request does not accept batch/list inputs at line 46\n"
			"- reserved fixture names: request (line 5)\n"
			"- unsupported mock assertions: mock.assert_called_once() without patch\n"
		),
		failed_content_lower="",
		imported_module_symbols=[],
		undefined_available_module_symbols=[],
		helper_alias_names=[],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=[],
		missing_datetime_import_issue=False,
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("provide every required field or omit that optional payload entirely" in line for line in lines)
	assert any("Keep scalar functions scalar" in line for line in lines)
	assert any("Never define a custom fixture named request." in line for line in lines)
	assert any("Do not use mock-style assertion bookkeeping" in line for line in lines)


def test_build_test_validation_repair_lines_handles_type_mismatch_and_helper_surface_fallback_directly():
	lines = build_test_validation_repair_lines(
		validation_summary=(
			"Generated test validation:\n"
			"- Type mismatches: details expects dict but test uses str at line 8\n"
			"- Imported module symbols: ComplianceIntakeService, ComplianceRequest\n"
			"- Helper surface usages: RiskScoringService (line 33)\n"
			"- Tests without assertion-like checks: test_happy_path (line 5)\n"
			"- Verdict: FAIL"
		),
		failed_artifact_content=(
			"from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
			"def test_happy_path():\n"
			"    service = ComplianceIntakeService()\n"
			"    request = ComplianceRequest(request_id='req-1', request_type='screening', details='details')\n"
			"    service.handle_request(request)\n"
		),
		implementation_code="class RiskScoringService:\n    pass\n",
		helper_surface_symbols=[],
		helper_surface_usages=["RiskScoringService (line 33)"],
		missing_datetime_import_issue=False,
		required_evidence_runtime_issue=False,
		required_evidence_items=[],
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("PRIORITY: Fix type mismatches before other repairs" in line for line in lines)
	assert any("Replace string placeholders like details='details'" in line for line in lines)
	assert any("references these flagged helper surfaces: RiskScoringService" in line for line in lines)
	assert any("The validation summary already flagged these hollow top-level tests: test_happy_path (line 5)." in line for line in lines)


def test_build_test_validation_repair_lines_composes_available_imports_and_runtime_guidance_directly():
	lines = build_test_validation_repair_lines(
		validation_summary=(
			"Generated test validation:\n"
			"- Imported module symbols: AuditLog, ComplianceIntakeService, ComplianceRequest\n"
			"- Undefined local names: datetime (line 18), AuditLogger (line 6)\n"
			"- Pytest execution: FAIL\n"
			"- Constructor arity mismatches: none\n"
			"- Verdict: FAIL"
		),
		failed_artifact_content=(
			"from code_implementation import AuditLog, ComplianceIntakeService, ComplianceRequest\n\n"
			"def test_happy_path():\n"
			"    service = ComplianceIntakeService()\n"
			"    request = ComplianceRequest(request_id='req-1', request_type='screening', details={'source': 'web'}, timestamp=datetime.now())\n"
			"    service.handle_request(request)\n"
		),
		implementation_code=(
			"from datetime import datetime\n\n"
			"class AuditLogger:\n"
			"    pass\n"
		),
		helper_surface_symbols=[],
		helper_surface_usages=[],
		missing_datetime_import_issue=True,
		required_evidence_runtime_issue=False,
		required_evidence_items=[],
		implementation_prefers_direct_datetime_import=True,
	)

	assert any("The previous file referenced real module symbols without importing them: AuditLogger." in line for line in lines)
	assert any("The current implementation already imports `from datetime import datetime`" in line for line in lines)
	assert any("preserve its valid imports, constructor shapes, fixture payload structure, and scenario skeleton" in line for line in lines)


def test_build_repair_focus_lines_dispatches_code_validation_directly():
	lines = build_repair_focus_lines(
		repair_context={
			"failure_category": "code_validation",
			"validation_summary": (
				"Generated code validation:\n"
				"- Module import: FAIL\n"
				"- Import summary: NameError: name 'logging' is not defined\n"
				"- Verdict: FAIL"
			),
			"failed_artifact_content": (
				"from dataclasses import dataclass\n\n"
				"logger = logging.getLogger(__name__)\n"
			),
		},
		context={},
	)

	assert any("logger = logging.getLogger(__name__)" in line for line in lines)
	assert any("import logging" in line for line in lines)


def test_build_repair_focus_lines_dispatches_test_validation_directly():
	lines = build_repair_focus_lines(
		repair_context={
			"failure_category": "test_validation",
			"validation_summary": (
				"Generated test validation:\n"
				"- Type mismatches: details expects dict but test uses str at line 8\n"
				"- Imported module symbols: ComplianceIntakeService, ComplianceRequest\n"
				"- Helper surface usages: RiskScoringService (line 33)\n"
				"- Tests without assertion-like checks: test_happy_path (line 5)\n"
				"- Verdict: FAIL"
			),
			"failed_artifact_content": (
				"from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
				"def test_happy_path():\n"
				"    service = ComplianceIntakeService()\n"
				"    request = ComplianceRequest(request_id='req-1', request_type='screening', details='details')\n"
				"    service.handle_request(request)\n"
			),
			"helper_surface_usages": ["RiskScoringService (line 33)"],
		},
		context={"code": "class RiskScoringService:\n    pass\n"},
	)

	assert any("PRIORITY: Fix type mismatches before other repairs" in line for line in lines)
	assert any("references these flagged helper surfaces: RiskScoringService" in line for line in lines)


def test_summarize_pytest_output_handles_empty_and_fallback_cases_directly():
	assert summarize_pytest_output("", "", 5) == "pytest exited with code 5"
	assert summarize_pytest_output("line one", "line two", 1) == "line two"


def test_redact_validation_execution_result_redacts_sensitive_values():
	result = redact_validation_execution_result(
		{
			"stdout": "api_key=sk-secret-123456",
			"stderr": "Authorization: Bearer sk-ant-secret-987654",
		}
	)

	assert "sk-secret-123456" not in str(result)
	assert "sk-ant-secret-987654" not in str(result)
	assert "[REDACTED]" in result["stdout"]
	assert "[REDACTED]" in result["stderr"]


def test_provider_call_metadata_prefers_output_and_redacts_sensitive_fields():
	output = AgentOutput(
		summary="ok",
		raw_content="ok",
		metadata={
			"provider_call": {
				"provider": "anthropic",
				"model": "claude-test",
				"base_url": "https://bob:secret-pass@example.com/messages",
				"error_message": "Authorization: Bearer sk-ant-secret-987654",
			}
		},
	)

	metadata = provider_call_metadata(object(), output)

	assert metadata is not None
	assert metadata["provider"] == "anthropic"
	assert metadata["model"] == "claude-test"
	assert "secret-pass" not in str(metadata)
	assert "sk-ant-secret-987654" not in str(metadata)


def test_sanitize_output_provider_call_metadata_updates_output_copy_in_place():
	output = AgentOutput(
		summary="ok",
		raw_content="ok",
		metadata={
			"provider_call": {
				"provider": "openai",
				"base_url": "https://alice:secret-pass@example.com/v1",
			}
		},
	)

	sanitized = sanitize_output_provider_call_metadata(output)

	assert sanitized is output
	assert "secret-pass" not in str(sanitized.metadata["provider_call"])
	assert "[REDACTED]" in sanitized.metadata["provider_call"]["base_url"]


def test_task_constraint_helpers_parse_limits_and_optional_inputs_directly():
	task = Task(
		id="tests",
		title="Tests",
		description=(
			"Write exactly 2 top-level test functions at most 3 fixtures and under 40 lines. "
			"Include a CLI demo entrypoint."
		),
		assigned_to="qa_tester",
	)

	assert task_line_budget(task) == 40
	assert task_requires_cli_entrypoint(task) is True
	assert task_exact_top_level_test_count(task) == 2
	assert task_max_top_level_test_count(task) is None
	assert task_fixture_budget(task) == 3
	assert task_line_budget(None) is None
	assert task_requires_cli_entrypoint(None) is False
	assert summary_limit_exceeded("- Line count: 205 / 200", "Line count") is True
	assert summary_limit_exceeded("- Fixture count: 2 / 3", "Fixture count") is False
	assert summary_limit_exceeded("", "Line count") is False
	assert is_budget_decomposition_planner(
		Task(
			id="planner",
			title="Budget Plan",
			description="Produce a compact brief.",
			assigned_to="architect",
			repair_context={"decomposition_mode": "budget_compaction_planner"},
		)
	) is True
	assert is_budget_decomposition_planner(
		Task(
			id="regular",
			title="Regular Task",
			description="Implement the workflow.",
			assigned_to="code_engineer",
		)
	) is False
	assert "next pytest repair" in build_budget_decomposition_instruction(FailureCategory.TEST_VALIDATION.value)
	assert "next module repair" in build_budget_decomposition_instruction(FailureCategory.CODE_VALIDATION.value)
	assert build_budget_decomposition_task_context(
		Task(
			id="repair_code",
			title="Repair",
			description="Fix the module.",
			assigned_to="code_engineer",
		),
		{
			"cycle": 2,
			"failure_category": FailureCategory.CODE_VALIDATION.value,
			"failure_message": "line budget exceeded",
			"validation_summary": "- Line count: 205 / 200",
		},
		"code_engineer",
	) == {
		"cycle": 2,
		"decomposition_mode": "budget_compaction_planner",
		"decomposition_target_task_id": "repair_code",
		"decomposition_target_agent": "code_engineer",
		"decomposition_failure_category": FailureCategory.CODE_VALIDATION.value,
		"failure_category": FailureCategory.CODE_VALIDATION.value,
		"failure_message": "line budget exceeded",
		"instruction": build_budget_decomposition_instruction(FailureCategory.CODE_VALIDATION.value),
		"validation_summary": "- Line count: 205 / 200",
	}
	assert repair_requires_budget_decomposition(
		{
			"failure_category": FailureCategory.CODE_VALIDATION.value,
			"validation_summary": "- Line count: 205 / 200",
		}
	) is True
	assert repair_requires_budget_decomposition(
		{
			"failure_category": FailureCategory.TEST_VALIDATION.value,
			"validation_summary": "- Fixture count: 2 / 3",
		}
	) is False
	assert repair_requires_budget_decomposition(
		{
			"failure_category": FailureCategory.CODE_VALIDATION.value,
			"validation_summary": "Completion diagnostics:\n- Likely truncated due to token budget",
		}
	) is True


def test_should_compact_architecture_context_uses_budget_and_repair_signals_directly():
	anchor = "- Public facade: ComplianceIntakeService"
	budget_task = Task(
		id="code",
		title="Implementation",
		description="Write one Python module under 300 lines.",
		assigned_to="code_engineer",
	)
	repair_task = Task(
		id="code_repair",
		title="Repair",
		description="Write one Python module.",
		assigned_to="code_engineer",
		repair_context={"cycle": 1},
	)

	assert should_compact_architecture_context(budget_task, anchor, "code_engineer", 900) is True
	assert should_compact_architecture_context(budget_task, anchor, "architect", 900) is False
	assert should_compact_architecture_context(repair_task, anchor, "code_engineer", 3200) is True
	assert should_compact_architecture_context(budget_task, "", "code_engineer", 900) is False


def test_compact_architecture_context_builds_low_budget_and_repair_summaries_directly():
	anchor = (
		"- Public facade: ComplianceIntakeService\n"
		"- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)"
	)
	budget_task = Task(
		id="code",
		title="Implementation",
		description="Write one Python module under 300 lines with a CLI demo entrypoint.",
		assigned_to="code_engineer",
	)
	repair_task = Task(
		id="repair",
		title="Repair",
		description="Write one Python module.",
		assigned_to="code_engineer",
		repair_context={"cycle": 1},
	)

	budget_summary = compact_architecture_context(budget_task, anchor)
	repair_summary = compact_architecture_context(repair_task, anchor)

	assert budget_summary.startswith("Low-budget architecture summary:")
	assert "Stay comfortably under 300 lines" in budget_summary
	assert 'main() plus a literal if __name__ == "__main__": block' in budget_summary
	assert repair_summary.startswith("Repair-focused architecture summary:")
	assert "Do not copy illustrative code blocks over the failing implementation" in repair_summary
	assert "prefer the existing failing module, the validation summary, and the cited pytest details" in repair_summary


def test_parse_task_public_contract_surface_handles_owners_defaults_and_markers_directly():
	assert parse_task_public_contract_surface(
		"ComplianceIntakeService.handle_request(request: ComplianceRequest, *, audit: bool = True)"
	) == ("ComplianceIntakeService", "handle_request", ["request", "audit"])
	assert parse_task_public_contract_surface("main() -> None with __main__ guard") == (
		None,
		"main",
		[],
	)
	assert parse_task_public_contract_surface("not a callable surface") == (
		None,
		"not a callable surface",
		[],
	)


def test_task_public_contract_anchor_extracts_bullets_and_indented_continuations_directly():
	description = (
		"Implement the workflow.\n\n"
		"Public contract anchor:\n"
		"- Public facade: ComplianceIntakeService\n"
		"- Required workflow: ComplianceIntakeService.handle_request(request)\n"
		"  Keep the same public entrypoint name.\n"
		"- Required CLI entrypoint: main()\n\n"
		"Additional notes here.\n"
	)

	assert task_public_contract_anchor(description) == (
		"- Public facade: ComplianceIntakeService\n"
		"- Required workflow: ComplianceIntakeService.handle_request(request)\n"
		"  Keep the same public entrypoint name.\n"
		"- Required CLI entrypoint: main()"
	)
	assert task_public_contract_anchor("No anchor here") == ""


def test_task_public_contract_preflight_reports_missing_surfaces_directly():
	task = Task(
		id="code",
		title="Implementation",
		description=(
			"Build the service.\n\n"
			"Public contract anchor:\n"
			"- Public facade: ComplianceIntakeService\n"
			"- Primary request model: ComplianceRequest(request_id, request_type)\n"
			"- Required workflow: ComplianceIntakeService.handle_request(request)\n"
		),
		assigned_to="code_engineer",
	)
	code_analysis = {
		"syntax_ok": True,
		"classes": {
			"ComplianceRequest": {
				"constructor_params": ["request_id", "request_type"],
				"constructor_min_args": 2,
			},
		},
		"functions": [],
		"has_main_guard": False,
	}

	preflight = task_public_contract_preflight(task, code_analysis)

	assert preflight is not None
	assert preflight["public_facade"] == "ComplianceIntakeService"
	assert preflight["primary_request_model"] == "ComplianceRequest(request_id, request_type)"
	assert preflight["required_surfaces"] == ["ComplianceIntakeService.handle_request(request)"]
	assert preflight["issues"] == [
		"missing public facade ComplianceIntakeService",
		"missing required surface ComplianceIntakeService.handle_request",
	]
	assert preflight["passed"] is False


def test_workflow_control_log_helpers_minimize_task_ids_directly():
	fields = privacy_safe_log_fields(
		{
			"task_ids": ["arch", "code"],
			"replayed_task_ids": ["arch"],
			"reason": "manual",
		}
	)

	assert fields == {"task_count": 2, "replayed_task_count": 1, "reason": "manual"}
	assert task_id_collection_count(["arch", "code"]) == 2
	assert task_id_collection_count("arch") == 1

	project = ProjectState(project_name="Demo", goal="Build demo")
	task = Task(
		id="code",
		title="Implementation",
		description="Write one Python module under 80 lines.",
		assigned_to="code_engineer",
	)
	project.add_task(task)
	repair_context = {
		"cycle": 1,
		"failure_category": FailureCategory.CODE_VALIDATION.value,
		"failure_message": "line budget exceeded",
		"validation_summary": "- Line count: 205 / 200",
	}

	decomposition_task = ensure_budget_decomposition_task(
		project,
		task,
		repair_context,
		requires_budget_decomposition=lambda ctx: True,
		build_budget_decomposition_task_context=lambda current_task, current_context: build_budget_decomposition_task_context(
			current_task,
			current_context,
			"code_engineer",
		),
	)
	assert decomposition_task is not None
	assert decomposition_task.id == "code__repair_1__budget_plan"
	assert repair_context["budget_decomposition_plan_task_id"] == decomposition_task.id
	assert ensure_budget_decomposition_task(
		project,
		task,
		repair_context,
		requires_budget_decomposition=lambda ctx: True,
		build_budget_decomposition_task_context=lambda current_task, current_context: build_budget_decomposition_task_context(
			current_task,
			current_context,
			"code_engineer",
		),
	) is decomposition_task
	assert active_repair_cycle(project) is None
	project.repair_history.append({"cycle": 1, "failed_task_ids": ["code"]})
	assert active_repair_cycle(project) == {"cycle": 1, "failed_task_ids": ["code"]}
	project.add_task(
		Task(
			id="code__repair_cycle_1",
			title="Repair implementation",
			description="Repair code",
			assigned_to="code_engineer",
			repair_origin_task_id="code",
			repair_attempt=1,
		)
	)
	assert has_repair_task_for_cycle(project, "code", 1) is True
	assert has_repair_task_for_cycle(project, "code", 2) is False
	repair_task = Task(
		id="code__repair_1",
		title="Repair implementation",
		description="Repair code",
		assigned_to="code_engineer",
		last_error_category=FailureCategory.CODE_VALIDATION.value,
		repair_origin_task_id="code",
		repair_context={
			"failure_category": FailureCategory.CODE_VALIDATION.value,
			"instruction": "Keep constructor bindings unique.",
			"validation_summary": "TypeError: VendorProfile.__init__() got multiple values for argument 'vendor_id'",
		},
	)
	merged_context = {
		"instruction": "Repair the generated Python module by reordering any dataclass fields.",
		"validation_summary": "Generated code validation failed",
	}
	merge_prior_repair_context(repair_task, merged_context)
	assert "Also preserve and fully satisfy the prior unresolved repair objective from code" in merged_context["instruction"]
	assert "Prior unresolved repair context:" in merged_context["validation_summary"]
	built_context = build_repair_context(
		repair_task,
		{"cycle": 2},
		repair_owner_for_category=lambda current_task, failure_category: f"owner:{failure_category}:{current_task.assigned_to}",
		build_repair_instruction=lambda current_task, failure_category: f"instruction:{failure_category}:{current_task.id}",
		build_repair_validation_summary=lambda current_task, failure_category: f"summary:{failure_category}:{current_task.id}",
		failed_artifact_content_for_category=lambda current_task, failure_category: f"artifact:{failure_category}:{current_task.id}",
		test_repair_helper_surface_usages=lambda current_task, failure_category: ["RiskScoringService"] if failure_category == FailureCategory.CODE_VALIDATION.value else [],
		normalized_helper_surface_symbols=lambda values: [str(item).split(" (line ", 1)[0] for item in values] if isinstance(values, list) else [],
		merge_prior_repair_context=merge_prior_repair_context,
	)
	assert built_context["cycle"] == 2
	assert built_context["repair_owner"] == "owner:code_validation:code_engineer"
	assert built_context["failed_artifact_content"] == "artifact:code_validation:code__repair_1"
	assert built_context["helper_surface_symbols"] == ["RiskScoringService"]
	assert "Also preserve and fully satisfy the prior unresolved repair objective from code" in built_context["instruction"]
	code_from_test_context = build_code_repair_context_from_test_failure(
		repair_task,
		Task(
			id="tests__repair_1",
			title="Repair tests",
			description="Repair tests",
			assigned_to="qa_tester",
			last_error_category=FailureCategory.TEST_VALIDATION.value,
			last_error="pytest failed",
		),
		{"cycle": 3},
		failed_artifact_content=lambda current_task, artifact_type: f"artifact:{artifact_type.value}:{current_task.id}",
		build_repair_validation_summary=lambda current_task, failure_category: f"summary:{failure_category}:{current_task.id}",
		build_code_repair_instruction_from_test_failure=lambda current_task, validation_summary, existing_tests: f"instruction:{current_task.id}:{validation_summary}:{existing_tests}",
		merge_prior_repair_context=merge_prior_repair_context,
	)
	assert code_from_test_context["cycle"] == 3
	assert code_from_test_context["failure_category"] == FailureCategory.CODE_VALIDATION.value
	assert code_from_test_context["source_failure_task_id"] == "tests__repair_1"
	assert code_from_test_context["existing_tests"] == "artifact:test:tests__repair_1"
	assert code_from_test_context["failed_artifact_content"] == "artifact:code:code__repair_1"
	assert "Also preserve and fully satisfy the prior unresolved repair objective from code" in code_from_test_context["instruction"]
	assert failed_test_requires_code_repair(
		Task(
			id="tests",
			title="Tests",
			description="Write tests",
			assigned_to="qa_tester",
			last_error_category=FailureCategory.TEST_VALIDATION.value,
		),
		{
			"test_execution": {"ran": True, "returncode": 1, "stdout": "FAILED test_module.py::test_ok\n"},
			"pytest_failure_origin": "code_under_test",
		},
		pytest_failure_origin=lambda *_args: "tests",
		pytest_contract_overreach_signals=lambda _execution: [],
		test_validation_has_blocking_issues=lambda _validation: False,
		pytest_failure_is_semantic_assertion_mismatch=lambda _execution: False,
	) is True
	assert failed_test_requires_code_repair(
		Task(
			id="tests",
			title="Tests",
			description="Write tests",
			assigned_to="qa_tester",
			last_error_category=FailureCategory.TEST_VALIDATION.value,
		),
		{
			"test_execution": {"ran": True, "returncode": 1, "stdout": "FAILED test_module.py::test_ok\n"},
			"pytest_failure_origin": "tests",
		},
		pytest_failure_origin=lambda *_args: "tests",
		pytest_contract_overreach_signals=lambda _execution: ["contract_overreach"],
		test_validation_has_blocking_issues=lambda _validation: False,
		pytest_failure_is_semantic_assertion_mismatch=lambda _execution: True,
	) is False
	assert failed_test_requires_code_repair_runtime(
		Task(
			id="tests",
			title="Tests",
			description="Write tests",
			assigned_to="qa_tester",
			last_error_category=FailureCategory.TEST_VALIDATION.value,
		),
		validation_payload=lambda task: {
			"test_execution": {"ran": True, "returncode": 1, "stdout": "FAILED test_module.py::test_ok\n"},
			"pytest_failure_origin": "code_under_test",
		},
		pytest_failure_origin=lambda *_args: "tests",
		pytest_contract_overreach_signals=lambda _execution: [],
		test_validation_has_blocking_issues=lambda _validation: False,
		pytest_failure_is_semantic_assertion_mismatch=lambda _execution: False,
	) is True
	lookup_project = ProjectState(project_name="Demo", goal="Build demo")
	lookup_project.add_task(Task(id="code", title="Code", description="Code", assigned_to="code_engineer"))
	lookup_project.add_task(Task(id="code__repair_1", title="Repair code", description="Repair code", assigned_to="code_engineer", repair_origin_task_id="code"))
	lookup_test_task = Task(
		id="tests",
		title="Tests",
		description="Tests",
		assigned_to="qa_tester",
		dependencies=["code"],
	)
	lookup_project.add_task(lookup_test_task)
	imported_code_task = imported_code_task_for_failed_test(
		lookup_project,
		lookup_test_task,
		failed_artifact_content=lambda _task, _artifact_type: "from code_implementation import run",
		python_import_roots=lambda _content: {"code_implementation"},
		default_module_name_for_task=lambda current_task: "code_implementation" if current_task.id in {"code", "code__repair_1"} else None,
	)
	assert imported_code_task is not None
	assert imported_code_task.id == "code__repair_1"
	upstream_code_task = upstream_code_task_for_test_failure(
		lookup_project,
		lookup_test_task,
		imported_code_task_for_failed_test=lambda _project, _task: imported_code_task,
	)
	assert upstream_code_task is not None
	assert upstream_code_task.id == "code__repair_1"
	failed_project = ProjectState(project_name="Demo", goal="Build demo")
	failed_project.add_task(Task(id="code", title="Code", description="Code", assigned_to="code_engineer", status=TaskStatus.FAILED.value))
	failed_project.add_task(Task(id="code__repair_1", title="Repair code", description="Repair code", assigned_to="code_engineer", repair_origin_task_id="code", status=TaskStatus.PENDING.value))
	failed_project.add_task(Task(id="tests", title="Tests", description="Tests", assigned_to="qa_tester", status=TaskStatus.FAILED.value))
	assert failed_task_ids_for_repair(failed_project) == ["tests"]
	repair_cycle_project = ProjectState(project_name="Demo", goal="Build demo")
	repair_cycle_project.add_task(Task(id="code", title="Code", description="Code", assigned_to="code_engineer"))
	repair_cycle_project.add_task(Task(id="tests", title="Tests", description="Tests", assigned_to="qa_tester", repair_context={"cycle": 1}))
	assert repair_task_ids_for_cycle(
		repair_cycle_project,
		["missing", "tests"],
		test_failure_requires_code_repair=lambda task: task.id == "tests",
		upstream_code_task_for_test_failure=lambda project, task: project.get_task("code"),
		ensure_budget_decomposition_task=lambda _project, _task, _repair_context: None,
		execution_agent_name=lambda task: task.assigned_to,
	) == ["code__repair_0", "tests__repair_1"]
	configure_project = ProjectState(project_name="Demo", goal="Build demo")
	configure_project.add_task(Task(id="code", title="Code", description="Code", assigned_to="code_engineer"))
	configure_project.add_task(Task(id="tests", title="Tests", description="Tests", assigned_to="qa_tester"))
	configure_repair_attempts(
		configure_project,
		["tests"],
		{"cycle": 2},
		test_failure_requires_code_repair=lambda task: task.id == "tests",
		upstream_code_task_for_test_failure=lambda project, task: project.get_task("code"),
		build_code_repair_context_from_test_failure=lambda code_task, test_task, cycle: {"cycle": cycle.get("cycle"), "source_failure_task_id": test_task.id},
		ensure_budget_decomposition_task=lambda _project, _task, _repair_context: None,
		build_repair_context=lambda task, cycle: {"cycle": cycle.get("cycle"), "failure_category": FailureCategory.UNKNOWN.value},
	)
	assert configure_project.get_task("code").repair_context == {"cycle": 2, "source_failure_task_id": "tests"}
	assert configure_project.get_task("tests").repair_context == {"cycle": 2, "failure_category": FailureCategory.UNKNOWN.value}
	queued_project = ProjectState(project_name="Demo", goal="Build demo")
	queued_task = Task(id="tests", title="Tests", description="Tests", assigned_to="qa_tester", status=TaskStatus.FAILED)
	queued_project.add_task(queued_task)
	logged_events: list[tuple[str, str, dict[str, object]]] = []
	configured_calls: list[tuple[list[str], dict[str, object]]] = []
	repair_task_call_args: list[list[str]] = []
	assert queue_active_cycle_repair(
		queued_project,
		queued_task,
		workflow_resume_policy="resume_failed",
		active_repair_cycle=lambda _project: {"cycle": 2},
		has_repair_task_for_cycle=lambda _project, _task_id, _cycle_number: False,
		configure_repair_attempts=lambda _project, failed_task_ids, cycle: configured_calls.append((failed_task_ids, cycle)),
		repair_task_ids_for_cycle=lambda _project, failed_task_ids: repair_task_call_args.append(failed_task_ids) or ["tests__repair_1"],
		log_event=lambda level, event, **details: logged_events.append((level, event, details)),
	) is True
	assert configured_calls == [(["tests"], {"cycle": 2})]
	assert repair_task_call_args == [["tests"]]
	assert any(
		event["event"] == "task_repair_chained"
		and event["task_id"] == "tests"
		and event["details"]["repair_task_ids"] == ["tests__repair_1"]
		for event in queued_project.execution_events
	)
	assert logged_events == [
		(
			"info",
			"task_repair_chained",
			{
				"project_name": "Demo",
				"task_id": "tests",
				"repair_task_ids": ["tests__repair_1"],
				"repair_cycle_count": 0,
			},
		)
	]
	resume_project = ProjectState(project_name="Demo", goal="Build demo")
	resume_project.repair_max_cycles = 2
	resume_project.add_task(
		Task(
			id="code",
			title="Code",
			description="Code",
			assigned_to="code_engineer",
			status=TaskStatus.FAILED.value,
		)
	)
	resume_configure_calls: list[tuple[list[str], dict[str, object]]] = []
	resumed_ids = resume_failed_tasks_with_repair_cycle(
		resume_project,
		["code"],
		{FailureCategory.CODE_VALIDATION.value},
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		configure_repair_attempts=lambda _project, failed_task_ids, cycle: resume_configure_calls.append((failed_task_ids, cycle)),
		repair_task_ids_for_cycle=lambda _project, failed_task_ids: ["code__repair_1"],
		log_event=lambda *_args, **_kwargs: None,
	)
	assert resumed_ids == ["code__repair_1"]
	assert resume_project.repair_cycle_count == 1
	assert resume_project.repair_history[-1]["failed_task_ids"] == ["code"]
	assert resume_configure_calls == [(["code"], resume_project.repair_history[-1])]
	assert any(
		event["event"] == "workflow_repair_cycle_started"
		and event["details"]["failed_task_ids"] == ["code"]
		for event in resume_project.execution_events
	)
	budget_project = ProjectState(project_name="Demo", goal="Build demo")
	budget_project.repair_max_cycles = 0
	budget_saved: list[bool] = []
	budget_project.save = lambda: budget_saved.append(True)
	budget_logs: list[tuple[str, str, dict[str, object]]] = []
	with pytest.raises(AgentExecutionError, match="Workflow repair budget exhausted before resuming failed tasks"):
		resume_failed_tasks_with_repair_cycle(
			budget_project,
			["code"],
			{FailureCategory.CODE_VALIDATION.value},
			workflow_acceptance_policy="strict",
			zero_budget_failure_categories=set(),
			evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
			configure_repair_attempts=lambda *_args, **_kwargs: None,
			repair_task_ids_for_cycle=lambda *_args, **_kwargs: [],
			log_event=lambda level, event, **details: budget_logs.append((level, event, details)),
		)
	assert budget_saved == [True]
	assert budget_project.phase == "failed"
	assert budget_project.failure_category == FailureCategory.REPAIR_BUDGET_EXHAUSTED.value
	assert budget_logs == [
		(
			"error",
			"workflow_repair_budget_exhausted",
			{
				"project_name": "Demo",
				"failed_task_ids": ["code"],
				"repair_cycle_count": 0,
				"repair_max_cycles": 0,
			},
		)
	]
	delegated_calls: list[tuple[list[str], set[str]]] = []
	delegated_ids = resume_failed_workflow_tasks(
		resume_project,
		["code"],
		{FailureCategory.CODE_VALIDATION.value},
		is_repairable_failure=lambda _category: True,
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		resume_failed_tasks_with_repair_cycle=lambda _project, failed_task_ids, failure_categories, **_kwargs: delegated_calls.append((failed_task_ids, failure_categories)) or ["code__repair_1"],
	)
	assert delegated_ids == ["code__repair_1"]
	assert delegated_calls == [(["code"], {FailureCategory.CODE_VALIDATION.value})]
	hard_stop_project = ProjectState(project_name="Demo", goal="Build demo")
	hard_stop_saved: list[bool] = []
	hard_stop_project.save = lambda: hard_stop_saved.append(True)
	with pytest.raises(AgentExecutionError, match="cannot resume automatically"):
		resume_failed_workflow_tasks(
			hard_stop_project,
			["tests"],
			{FailureCategory.SANDBOX_SECURITY_VIOLATION.value},
			is_repairable_failure=lambda _category: False,
			workflow_acceptance_policy="strict",
			zero_budget_failure_categories={FailureCategory.SANDBOX_SECURITY_VIOLATION.value},
			evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
			resume_failed_tasks_with_repair_cycle=lambda *_args, **_kwargs: [],
		)
	assert hard_stop_saved == [True]
	assert hard_stop_project.phase == "failed"
	assert hard_stop_project.failure_category == FailureCategory.SANDBOX_SECURITY_VIOLATION.value
	resume_stage_project = ProjectState(project_name="Demo", goal="Build demo")
	resume_stage_project.add_task(
		Task(
			id="tests",
			title="Tests",
			description="Tests",
			assigned_to="qa_tester",
			status=TaskStatus.FAILED.value,
			last_error_category=FailureCategory.TEST_VALIDATION.value,
		)
	)
	resume_stage_project.resume_interrupted_tasks = lambda: ["arch"]
	resume_stage_saved: list[bool] = []
	resume_stage_project.save = lambda: resume_stage_saved.append(True)
	resume_stage_calls: list[tuple[list[str], set[str]]] = []
	resume_stage_logs: list[tuple[str, str, dict[str, object]]] = []
	assert resume_workflow_tasks(
		resume_stage_project,
		workflow_resume_policy="resume_failed",
		failed_task_ids_for_repair=lambda _project: ["tests"],
		resume_failed_workflow_tasks=lambda _project, failed_task_ids, failure_categories: resume_stage_calls.append((failed_task_ids, failure_categories)) or ["tests__repair_1"],
		log_event=lambda level, event, **details: resume_stage_logs.append((level, event, details)),
	) == ["arch", "tests__repair_1"]
	assert resume_stage_saved == [True]
	assert resume_stage_calls == [(["tests"], {FailureCategory.TEST_VALIDATION.value})]
	assert resume_stage_logs == [
		(
			"info",
			"workflow_resumed",
			{
				"project_name": "Demo",
				"task_ids": ["arch", "tests__repair_1"],
			},
		)
	]
	start_project = ProjectState(project_name="Demo", goal="Build demo")
	start_logs: list[tuple[str, str, dict[str, object]]] = []
	assert ensure_workflow_running(
		start_project,
		workflow_acceptance_policy="strict",
		workflow_max_repair_cycles=2,
		log_event=lambda level, event, **details: start_logs.append((level, event, details)),
	) is True
	assert start_project.phase == "execution"
	assert start_project.repair_max_cycles == 2
	assert start_logs == [("info", "workflow_started", {"project_name": "Demo", "phase": "execution"})]
	assert ensure_workflow_running(
		start_project,
		workflow_acceptance_policy="strict",
		workflow_max_repair_cycles=2,
		log_event=lambda *_args, **_kwargs: None,
	) is False
	finish_project = ProjectState(project_name="Demo", goal="Build demo")
	finish_saved: list[bool] = []
	finish_project.save = lambda: finish_saved.append(True)
	finish_logs: list[tuple[str, str, dict[str, object]]] = []
	assert finish_workflow_if_no_pending_tasks(
		finish_project,
		[],
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": True},
		log_event=lambda level, event, **details: finish_logs.append((level, event, details)),
	) is True
	assert finish_project.phase == "completed"
	assert finish_project.terminal_outcome == WorkflowOutcome.COMPLETED.value
	assert finish_saved == [True]
	assert finish_logs == [("info", "workflow_completed", {"project_name": "Demo", "phase": "completed"})]
	assert finish_workflow_if_no_pending_tasks(
		finish_project,
		[Task(id="pending", title="Pending", description="Pending", assigned_to="architect")],
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		log_event=lambda *_args, **_kwargs: None,
	) is False
	definition_project = ProjectState(project_name="Demo", goal="Build demo")
	definition_saved: list[bool] = []
	definition_project.save = lambda: definition_saved.append(True)
	definition_logs: list[tuple[str, str, dict[str, object]]] = []
	fail_workflow_for_definition_error(
		definition_project,
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		log_event=lambda level, event, **details: definition_logs.append((level, event, details)),
	)
	assert definition_project.phase == "failed"
	assert definition_project.failure_category == FailureCategory.WORKFLOW_DEFINITION.value
	assert definition_project.terminal_outcome == WorkflowOutcome.FAILED.value
	assert definition_saved == [True]
	assert definition_logs == [("error", "workflow_failed", {"project_name": "Demo", "phase": "failed"})]
	blocked_project = ProjectState(project_name="Demo", goal="Build demo")
	blocked_saved: list[bool] = []
	blocked_project.save = lambda: blocked_saved.append(True)
	blocked_logs: list[tuple[str, str, dict[str, object]]] = []
	with pytest.raises(AgentExecutionError, match="Workflow is blocked"):
		fail_workflow_when_blocked(
			blocked_project,
			blocked_tasks=[Task(id="blocked", title="Blocked", description="Wait", assigned_to="architect")],
			workflow_acceptance_policy="strict",
			zero_budget_failure_categories=set(),
			evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
			log_event=lambda level, event, **details: blocked_logs.append((level, event, details)),
		)
	assert blocked_project.phase == "failed"
	assert blocked_project.failure_category == FailureCategory.WORKFLOW_BLOCKED.value
	assert blocked_project.terminal_outcome == WorkflowOutcome.FAILED.value
	assert blocked_saved == [True]
	assert blocked_logs == [
		(
			"error",
			"workflow_blocked",
			{"project_name": "Demo", "phase": "failed", "blocked_task_ids": "blocked"},
		)
	]
	progress_project = ProjectState(project_name="Demo", goal="Build demo")
	progress_task = Task(id="done", title="Done", description="Done", assigned_to="architect")
	progress_project.add_task(progress_task)
	progress_saved: list[bool] = []
	progress_project.save = lambda: progress_saved.append(True)
	progress_calls: list[tuple[str, str]] = []
	emit_workflow_progress_and_save(
		progress_project,
		task=progress_task,
		emit_workflow_progress=lambda project, *, task: progress_calls.append((project.project_name, task.id)),
	)
	assert progress_saved == [True]
	assert progress_calls == [("Demo", "done")]
	continue_project = ProjectState(project_name="Demo", goal="Build demo")
	continue_project.add_task(
		Task(id="failed", title="Failed", description="Fail", assigned_to="architect", status=TaskStatus.FAILED.value)
	)
	continue_project.add_task(
		Task(
			id="downstream",
			title="Downstream",
			description="Wait",
			assigned_to="architect",
			dependencies=["failed"],
		)
	)
	continue_saved: list[bool] = []
	continue_project.save = lambda: continue_saved.append(True)
	progress_calls: list[tuple[str, str]] = []
	continue_logs: list[tuple[str, str, dict[str, object]]] = []
	failed_task = continue_project.get_task("failed")
	assert failed_task is not None
	continue_workflow_after_task_failure(
		continue_project,
		task=failed_task,
		emit_workflow_progress=lambda project, *, task: progress_calls.append((project.project_name, task.id)),
		log_event=lambda level, event, **details: continue_logs.append((level, event, details)),
	)
	downstream_task = continue_project.get_task("downstream")
	assert downstream_task is not None
	assert downstream_task.status == TaskStatus.SKIPPED.value
	assert continue_saved == [True]
	assert progress_calls == [("Demo", "failed")]
	assert continue_logs == [
		(
			"warning",
			"dependent_tasks_skipped",
			{"project_name": "Demo", "task_id": "failed", "skipped_task_ids": ["downstream"]},
		)
	]
	fail_task_project = ProjectState(project_name="Demo", goal="Build demo")
	fail_task_saved: list[bool] = []
	fail_task_project.save = lambda: fail_task_saved.append(True)
	fail_task_logs: list[tuple[str, str, dict[str, object]]] = []
	fail_workflow_after_task_failure(
		fail_task_project,
		failure_category=FailureCategory.UNKNOWN.value,
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		log_event=lambda level, event, **details: fail_task_logs.append((level, event, details)),
	)
	assert fail_task_project.phase == "failed"
	assert fail_task_project.failure_category == FailureCategory.UNKNOWN.value
	assert fail_task_project.terminal_outcome == WorkflowOutcome.FAILED.value
	assert fail_task_saved == [True]
	assert fail_task_logs == [
		(
			"error",
			"workflow_failed",
			{"project_name": "Demo", "phase": "failed"},
		)
	]
	dispatch_project = ProjectState(project_name="Demo", goal="Build demo")
	retry_task = Task(id="retry", title="Retry", description="Retry", assigned_to="architect")
	dispatch_project.add_task(retry_task)
	dispatch_project.should_retry_task = lambda task_id: task_id == "retry"
	dispatch_saved: list[bool] = []
	dispatch_project.save = lambda: dispatch_saved.append(True)
	dispatch_progress: list[str] = []
	assert dispatch_task_failure(
		dispatch_project,
		task=retry_task,
		failure_category=FailureCategory.UNKNOWN.value,
		workflow_failure_policy="fail_fast",
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		is_repairable_failure=lambda _category: False,
		queue_active_cycle_repair=lambda _project, _task: False,
		emit_workflow_progress=lambda _project, *, task: dispatch_progress.append(task.id),
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		log_event=lambda *_args, **_kwargs: None,
	) == "continue"
	assert dispatch_saved == [True]
	assert dispatch_progress == ["retry"]
	continue_dispatch_project = ProjectState(project_name="Demo", goal="Build demo")
	continue_dispatch_project.add_task(Task(id="failed", title="Failed", description="Fail", assigned_to="architect"))
	continue_dispatch_project.add_task(
		Task(id="downstream_2", title="Downstream", description="Wait", assigned_to="architect", dependencies=["failed"])
	)
	continue_dispatch_logs: list[tuple[str, str, dict[str, object]]] = []
	assert dispatch_task_failure(
		continue_dispatch_project,
		task=continue_dispatch_project.get_task("failed") or Task(id="failed", title="Failed", description="Fail", assigned_to="architect"),
		failure_category=FailureCategory.UNKNOWN.value,
		workflow_failure_policy="continue",
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		is_repairable_failure=lambda _category: False,
		queue_active_cycle_repair=lambda _project, _task: False,
		emit_workflow_progress=lambda *_args, **_kwargs: None,
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		log_event=lambda level, event, **details: continue_dispatch_logs.append((level, event, details)),
	) == "continue"
	downstream_task = continue_dispatch_project.get_task("downstream_2")
	assert downstream_task is not None
	assert downstream_task.status == TaskStatus.SKIPPED.value
	assert continue_dispatch_logs == [
		(
			"warning",
			"dependent_tasks_skipped",
			{"project_name": "Demo", "task_id": "failed", "skipped_task_ids": ["downstream_2"]},
		)
	]
	repair_dispatch_project = ProjectState(project_name="Demo", goal="Build demo")
	repair_task = Task(id="repairable", title="Repairable", description="Repairable", assigned_to="architect")
	repair_dispatch_project.add_task(repair_task)
	repair_progress: list[str] = []
	assert dispatch_task_failure(
		repair_dispatch_project,
		task=repair_task,
		failure_category=FailureCategory.CODE_VALIDATION.value,
		workflow_failure_policy="fail_fast",
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		is_repairable_failure=lambda _category: True,
		queue_active_cycle_repair=lambda _project, _task: True,
		emit_workflow_progress=lambda _project, *, task: repair_progress.append(task.id),
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		log_event=lambda *_args, **_kwargs: None,
	) == "continue"
	assert repair_progress == ["repairable"]
	raise_dispatch_project = ProjectState(project_name="Demo", goal="Build demo")
	raise_logs: list[tuple[str, str, dict[str, object]]] = []
	assert dispatch_task_failure(
		raise_dispatch_project,
		task=Task(id="fatal", title="Fatal", description="Fatal", assigned_to="architect"),
		failure_category=FailureCategory.UNKNOWN.value,
		workflow_failure_policy="fail_fast",
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		is_repairable_failure=lambda _category: False,
		queue_active_cycle_repair=lambda _project, _task: False,
		emit_workflow_progress=lambda *_args, **_kwargs: None,
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		log_event=lambda level, event, **details: raise_logs.append((level, event, details)),
	) == "raise"
	assert raise_dispatch_project.phase == "failed"
	assert raise_logs == [
		(
			"error",
			"workflow_failed",
			{"project_name": "Demo", "phase": "failed"},
		)
	]
	execute_project = ProjectState(project_name="Demo", goal="Build demo")
	execute_task = Task(id="exec", title="Execute", description="Execute", assigned_to="architect")
	execute_project.add_task(execute_task)
	execute_progress: list[str] = []
	assert execute_workflow_task(
		execute_project,
		task=execute_task,
		run_task=lambda current_task, _project: execute_progress.append(f"run:{current_task.id}"),
		exit_if_workflow_cancelled=lambda _project: False,
		exit_if_workflow_paused=lambda _project: False,
		classify_task_failure=lambda _task, _exc: FailureCategory.UNKNOWN.value,
		dispatch_task_failure=lambda *_args, **_kwargs: "raise",
		emit_workflow_progress=lambda _project, *, task: execute_progress.append(f"progress:{task.id}"),
	) == "continue"
	assert execute_progress == ["run:exec", "progress:exec"]
	assert execute_workflow_task(
		execute_project,
		task=execute_task,
		run_task=lambda *_args, **_kwargs: None,
		exit_if_workflow_cancelled=lambda _project: True,
		exit_if_workflow_paused=lambda _project: False,
		classify_task_failure=lambda _task, _exc: FailureCategory.UNKNOWN.value,
		dispatch_task_failure=lambda *_args, **_kwargs: "raise",
		emit_workflow_progress=lambda *_args, **_kwargs: None,
	) == "return"
	failure_dispatch_calls: list[tuple[str, str]] = []
	with pytest.raises(RuntimeError, match="boom"):
		execute_workflow_task(
			execute_project,
			task=execute_task,
			run_task=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
			exit_if_workflow_cancelled=lambda _project: False,
			exit_if_workflow_paused=lambda _project: False,
			classify_task_failure=lambda task, _exc: failure_dispatch_calls.append((task.id, "classified")) or FailureCategory.UNKNOWN.value,
			dispatch_task_failure=lambda current_project, *, task, failure_category: failure_dispatch_calls.append((task.id, failure_category)) or "raise",
			emit_workflow_progress=lambda *_args, **_kwargs: None,
		)
	assert failure_dispatch_calls == [
		("exec", "classified"),
		("exec", FailureCategory.UNKNOWN.value),
	]
	runnable_project = ProjectState(project_name="Demo", goal="Build demo")
	runnable_tasks = [
		Task(id="first", title="First", description="First", assigned_to="architect"),
		Task(id="second", title="Second", description="Second", assigned_to="architect"),
	]
	runnable_calls: list[str] = []
	assert execute_runnable_tasks(
		runnable_project,
		runnable_tasks,
		execute_workflow_task=lambda _project, *, task: runnable_calls.append(task.id) or "continue",
	) is False
	assert runnable_calls == ["first", "second"]
	runnable_calls = []
	assert execute_runnable_tasks(
		runnable_project,
		runnable_tasks,
		execute_workflow_task=lambda _project, *, task: runnable_calls.append(task.id) or ("return" if task.id == "first" else "continue"),
	) is True
	assert runnable_calls == ["first"]
	frontier_project = ProjectState(project_name="Demo", goal="Build demo")
	frontier_logs: list[tuple[str, str, dict[str, object]]] = []
	assert execute_runnable_frontier(
		frontier_project,
		runnable_tasks=lambda: runnable_tasks,
		blocked_tasks=lambda: [],
		execute_runnable_tasks=lambda _project, current_runnable: [task.id for task in current_runnable] == ["first", "second"],
		workflow_acceptance_policy="strict",
		zero_budget_failure_categories=set(),
		evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
		log_event=lambda level, event, **details: frontier_logs.append((level, event, details)),
	) is True
	assert frontier_logs == []
	definition_frontier_project = ProjectState(project_name="Demo", goal="Build demo")
	definition_frontier_logs: list[tuple[str, str, dict[str, object]]] = []
	with pytest.raises(WorkflowDefinitionError, match="cycle"):
		execute_runnable_frontier(
			definition_frontier_project,
			runnable_tasks=lambda: (_ for _ in ()).throw(WorkflowDefinitionError("cycle")),
			blocked_tasks=lambda: [],
			execute_runnable_tasks=lambda _project, _runnable: False,
			workflow_acceptance_policy="strict",
			zero_budget_failure_categories=set(),
			evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
			log_event=lambda level, event, **details: definition_frontier_logs.append((level, event, details)),
		)
	assert definition_frontier_project.phase == "failed"
	assert definition_frontier_logs == [
		(
			"error",
			"workflow_failed",
			{"project_name": "Demo", "phase": "failed"},
		)
	]
	blocked_frontier_project = ProjectState(project_name="Demo", goal="Build demo")
	blocked_frontier_logs: list[tuple[str, str, dict[str, object]]] = []
	with pytest.raises(AgentExecutionError, match="Workflow is blocked"):
		execute_runnable_frontier(
			blocked_frontier_project,
			runnable_tasks=lambda: [],
			blocked_tasks=lambda: [Task(id="blocked_frontier", title="Blocked", description="Wait", assigned_to="architect")],
			execute_runnable_tasks=lambda _project, _runnable: False,
			workflow_acceptance_policy="strict",
			zero_budget_failure_categories=set(),
			evaluate_workflow_acceptance=lambda _project, _policy, _categories: {"accepted": False},
			log_event=lambda level, event, **details: blocked_frontier_logs.append((level, event, details)),
		)
	assert blocked_frontier_project.phase == "failed"
	assert blocked_frontier_logs == [
		(
			"error",
			"workflow_blocked",
			{"project_name": "Demo", "phase": "failed", "blocked_task_ids": "blocked_frontier"},
		)
	]
	loop_project = ProjectState(project_name="Demo", goal="Build demo")
	loop_pending_calls: list[str] = []
	assert execute_workflow_loop(
		loop_project,
		exit_if_workflow_cancelled=lambda _project: False,
		exit_if_workflow_paused=lambda _project: False,
		pending_tasks=lambda: loop_pending_calls.append("pending") or [],
		finish_workflow_if_no_pending_tasks=lambda _project, pending: pending == [],
		execute_runnable_frontier=lambda _project: False,
	) is False
	assert loop_pending_calls == ["pending"]
	loop_return_calls: list[str] = []
	assert execute_workflow_loop(
		loop_project,
		exit_if_workflow_cancelled=lambda _project: False,
		exit_if_workflow_paused=lambda _project: False,
		pending_tasks=lambda: [Task(id="pending", title="Pending", description="Pending", assigned_to="architect")],
		finish_workflow_if_no_pending_tasks=lambda _project, _pending: False,
		execute_runnable_frontier=lambda _project: loop_return_calls.append("frontier") or True,
	) is True
	assert loop_return_calls == ["frontier"]
	active_project = ProjectState(project_name="Demo", goal="Build demo")
	active_project.repair_max_cycles = 1
	active_project.mark_workflow_finished("completed", acceptance_policy="strict", terminal_outcome=WorkflowOutcome.COMPLETED.value)
	active_logs: list[tuple[str, str, dict[str, object]]] = []
	assert run_active_workflow(
		active_project,
		exit_if_workflow_cancelled=lambda _project: False,
		exit_if_workflow_paused=lambda _project: False,
		ensure_workflow_running=lambda _project: None,
		execute_workflow_loop=lambda _project: False,
		log_event=lambda level, event, **details: active_logs.append((level, event, details)),
	) is False
	assert active_logs == [
		(
			"info",
			"workflow_finished",
			{
				"project_name": "Demo",
				"phase": "completed",
				"terminal_outcome": WorkflowOutcome.COMPLETED.value,
				"workflow_telemetry": active_project.internal_runtime_telemetry()["workflow"],
			},
		)
	]
	assert run_active_workflow(
		active_project,
		exit_if_workflow_cancelled=lambda _project: True,
		exit_if_workflow_paused=lambda _project: False,
		ensure_workflow_running=lambda _project: (_ for _ in ()).throw(RuntimeError("should not run")),
		execute_workflow_loop=lambda _project: False,
		log_event=lambda *_args, **_kwargs: None,
	) is True
	prepared_project = ProjectState(project_name="Demo", goal="Build demo")
	prepared_calls: list[str] = []
	registry = object()
	assert prepare_workflow_execution(
		prepared_project,
		exit_if_workflow_cancelled=lambda _project: False,
		execution_plan=lambda: prepared_calls.append("plan"),
		validate_agent_resolution=lambda current_registry, current_project: prepared_calls.append(f"validate:{current_registry is registry}:{current_project.project_name}"),
		registry=registry,
		workflow_max_repair_cycles=3,
		resume_workflow_tasks=lambda current_project: prepared_calls.append(f"resume:{current_project.project_name}"),
		run_active_workflow=lambda current_project: prepared_calls.append(f"active:{current_project.project_name}") or False,
	) is False
	assert prepared_project.repair_max_cycles == 3
	assert prepared_calls == ["plan", "validate:True:Demo", "resume:Demo", "active:Demo"]
	assert prepare_workflow_execution(
		prepared_project,
		exit_if_workflow_cancelled=lambda _project: True,
		execution_plan=lambda: (_ for _ in ()).throw(RuntimeError("should not plan")),
		validate_agent_resolution=lambda *_args, **_kwargs: None,
		registry=registry,
		workflow_max_repair_cycles=3,
		resume_workflow_tasks=lambda *_args, **_kwargs: None,
		run_active_workflow=lambda *_args, **_kwargs: False,
	) is True
	runtime_project = ProjectState(project_name="Demo", goal="Build demo")
	runtime_calls: list[str] = []
	execute_workflow_runtime(
		runtime_project,
		exit_if_workflow_cancelled=lambda _project: False,
		execution_plan=lambda: runtime_calls.append("plan"),
		validate_agent_resolution=lambda _registry, _project: runtime_calls.append("validate"),
		registry=object(),
		workflow_max_repair_cycles=2,
		resume_workflow_tasks=lambda _project: runtime_calls.append("resume"),
		run_active_workflow=lambda _project: runtime_calls.append("active") or False,
	)
	assert runtime_project.repair_max_cycles == 2
	assert runtime_calls == ["plan", "validate", "resume", "active"]


def test_repair_instruction_owner_mapping_directly():
	assert repair_owner_for_category("architect", FailureCategory.CODE_VALIDATION.value) == "code_engineer"
	assert repair_owner_for_category("architect", FailureCategory.TEST_VALIDATION.value) == "qa_tester"
	assert repair_owner_for_category("architect", FailureCategory.DEPENDENCY_VALIDATION.value) == "dependency_manager"
	assert repair_owner_for_category("architect", FailureCategory.UNKNOWN.value) == "architect"
	assert artifact_type_for_failure_category(FailureCategory.CODE_VALIDATION.value) == ArtifactType.CODE
	assert artifact_type_for_failure_category(FailureCategory.TEST_VALIDATION.value) == ArtifactType.TEST
	assert artifact_type_for_failure_category(FailureCategory.DEPENDENCY_VALIDATION.value) == ArtifactType.CONFIG
	assert artifact_type_for_failure_category(FailureCategory.UNKNOWN.value) is None
	assert failed_artifact_content_for_category(
		"fallback",
		{
			"raw_content": "raw fallback",
			"artifacts": [{"artifact_type": ArtifactType.CONFIG.value, "content": "requests>=2.0"}],
		},
		FailureCategory.DEPENDENCY_VALIDATION.value,
	) == "requests>=2.0"
	assert failed_artifact_content_for_category(
		"fallback",
		{"raw_content": "raw fallback", "artifacts": None},
		FailureCategory.UNKNOWN.value,
	) == "raw fallback"
	assert helper_surface_usages_for_test_repair(
		{
			"test_analysis": {
				"helper_surface_usages": [
					"RiskScoringService (line 33)",
					"ComplianceRepository",
					"   ",
				]
			}
		},
		FailureCategory.TEST_VALIDATION.value,
	) == ["RiskScoringService (line 33)", "ComplianceRepository"]
	assert helper_surface_usages_for_test_repair({}, FailureCategory.CODE_VALIDATION.value) == []
	assert helper_surface_usages_for_test_repair_runtime(
		SimpleNamespace(),
		FailureCategory.TEST_VALIDATION.value,
		validation_payload=lambda task: {
			"test_analysis": {
				"helper_surface_usages": [
					"RiskScoringService (line 33)",
					"  ",
					"ComplianceRepository",
				]
			}
		},
	) == ["RiskScoringService (line 33)", "ComplianceRepository"]
	assert task_id_collection_count(None) == 0
	assert task_id_collection_count(3) is None
	assert task_id_count_log_field_name("task_ids") == "task_count"
	assert task_id_count_log_field_name("replayed_task_ids") == "replayed_task_count"
	assert task_id_count_log_field_name("task_id") is None


def test_validation_analysis_helpers_extract_failure_details_and_origin_directly():
	test_execution = {
		"stdout": "FAILED tests_tests.py::test_example - AssertionError: assert 1 == 2\nE   AssertionError: assert 1 == 2\n",
		"stderr": "",
	}

	assert pytest_failure_details(test_execution) == [
		"FAILED tests_tests.py::test_example - AssertionError: assert 1 == 2 | AssertionError: assert 1 == 2"
	]
	assert pytest_failure_origin({"stdout": "tests_tests.py:24: AssertionError\n", "stderr": ""}, "code.py", "tests_tests.py") == "tests"
	assert pytest_failure_is_semantic_assertion_mismatch(test_execution) is True


def test_replace_test_output_content_updates_test_artifact_and_summary_directly():
	output = AgentOutput(
		raw_content="old",
		summary="old summary",
		artifacts=[
			ArtifactRecord(name="tests", artifact_type=ArtifactType.TEST, path="tests.py", content="old"),
			ArtifactRecord(name="code", artifact_type=ArtifactType.CODE, path="code.py", content="def ok():\n    return 1"),
		],
	)

	new_content, updated_artifact_content = replace_test_output_content(
		output,
		"old",
		"def test_example():\n    assert True\n",
		lambda content: f"summary:{len(content)}",
	)

	assert new_content == "def test_example():\n    assert True\n"
	assert updated_artifact_content == "def test_example():\n    assert True\n"
	assert output.raw_content == "def test_example():\n    assert True\n"
	assert output.summary == "summary:36"
	assert output.artifacts[0].content == "def test_example():\n    assert True\n"
	assert output.artifacts[1].content == "def ok():\n    return 1"


def test_record_test_validation_metadata_persists_expected_fields_directly():
	output = AgentOutput(raw_content="tests", summary="tests")
	recorded: dict[str, object] = {}

	def recorder(agent_output, key, value):
		assert agent_output is output
		recorded[key] = value

	record_test_validation_metadata(
		output,
		{"syntax_ok": True},
		{"returncode": 0},
		{"truncated": False},
		"code_implementation.py",
		"tests_tests.py",
		"tests",
		recorder,
	)

	assert recorded == {
		"test_analysis": {"syntax_ok": True},
		"test_execution": {"returncode": 0},
		"completion_diagnostics": {"truncated": False},
		"module_filename": "code_implementation.py",
		"test_filename": "tests_tests.py",
		"pytest_failure_origin": "tests",
	}


def test_record_code_validation_metadata_persists_expected_fields_directly():
	output = AgentOutput(raw_content="code", summary="code")
	recorded: dict[str, object] = {}

	def recorder(agent_output, key, value):
		assert agent_output is output
		recorded[key] = value

	record_code_validation_metadata(
		output,
		{"syntax_ok": True},
		{"passed": True, "issues": []},
		{"ran": True, "returncode": 0},
		{"likely_truncated": False},
		recorder,
	)

	assert recorded == {
		"code_analysis": {"syntax_ok": True},
		"task_public_contract_preflight": {"passed": True, "issues": []},
		"import_validation": {"ran": True, "returncode": 0},
		"completion_diagnostics": {"likely_truncated": False},
	}


def test_validate_code_output_runtime_rejects_missing_cli_entrypoint_directly():
	output = AgentOutput(summary="code", raw_content="def run() -> int:\n    return 1\n")

	with pytest.raises(AgentExecutionError, match="missing required CLI entrypoint"):
		validate_code_output_runtime(
			output,
			None,
			True,
			lambda content, has_typed_artifact: True,
			lambda content: {"syntax_ok": True, "has_main_guard": False, "third_party_imports": []},
			lambda content: len(content.splitlines()),
			lambda code_analysis: None,
			lambda agent_output, **kwargs: {"likely_truncated": False},
			lambda agent_output, artifact_type, default_filename: default_filename,
			lambda module_filename, code_content: {"ran": True, "returncode": 0, "summary": "ok"},
			lambda *args, **kwargs: None,
			lambda diagnostics: "truncated",
		)


def test_validate_dependency_output_runtime_records_analysis_and_rejects_invalid_manifest_directly():
	output = AgentOutput(summary="deps", raw_content="requests>=2\n")
	recorded: dict[str, object] = {}

	with pytest.raises(AgentExecutionError, match="missing manifest entries for numpy"):
		validate_dependency_output_runtime(
			{"code_analysis": {"third_party_imports": ["numpy"]}},
			output,
			lambda manifest_content, code_analysis: {
				"is_valid": False,
				"missing_manifest_entries": ["numpy"],
				"provenance_violations": [],
			},
			lambda agent_output, key, value: recorded.__setitem__(key, value),
		)

	assert recorded == {
		"dependency_analysis": {
			"is_valid": False,
			"missing_manifest_entries": ["numpy"],
			"provenance_violations": [],
		}
	}


def test_build_test_validation_runtime_input_normalizes_context_and_artifacts_directly():
	output = AgentOutput(
		raw_content="fallback tests",
		summary="tests",
		artifacts=[
			ArtifactRecord(name="tests", artifact_type=ArtifactType.TEST, path="nested/generated_tests.py", content="typed tests"),
			ArtifactRecord(name="code", artifact_type=ArtifactType.CODE, path="code.py", content="def ok():\n    return 1"),
		],
	)

	runtime_input = build_test_validation_runtime_input(
		{
			"module_name": "code_implementation",
			"module_filename": "  ",
			"code": "def ok():\n    return 1",
			"code_exact_test_contract": "exact contract",
			"code_behavior_contract": "behavior contract",
		},
		output,
	)

	assert isinstance(runtime_input, ValidationRuntimeInput)
	assert runtime_input.module_name == "code_implementation"
	assert runtime_input.module_filename == "code_implementation.py"
	assert runtime_input.code_content == "def ok():\n    return 1"
	assert runtime_input.test_artifact_content == "typed tests"
	assert runtime_input.test_content == "typed tests"
	assert runtime_input.test_filename == "generated_tests.py"
	assert runtime_input.code_exact_test_contract == "exact contract"
	assert runtime_input.code_behavior_contract == "behavior contract"


def test_build_test_validation_runtime_state_runs_finalize_autofix_analysis_and_execution_directly():
	output = AgentOutput(
		raw_content="initial tests",
		summary="initial summary",
		artifacts=[ArtifactRecord(name="tests", artifact_type=ArtifactType.TEST, path="tests.py", content="initial tests")],
	)
	analyzed_contents: list[str] = []
	execution_calls: list[tuple[str, str, str, str]] = []

	def finalize_generated_test_suite(test_content, *, module_name, implementation_code, code_exact_test_contract):
		assert test_content == "initial tests"
		assert module_name == "code_implementation"
		assert implementation_code == "def ok():\n    return 1"
		assert code_exact_test_contract == "exact contract"
		return "finalized tests"

	def analyze_test_module(test_content, module_name, code_analysis, code_behavior_contract):
		analyzed_contents.append(test_content)
		assert module_name == "code_implementation"
		assert code_analysis == {"syntax_ok": True}
		assert code_behavior_contract == "behavior contract"
		return {"syntax_ok": True, "analysis_of": test_content}

	def auto_fix_test_type_mismatches(test_content, code_content):
		assert test_content == "finalized tests"
		assert code_content == "def ok():\n    return 1"
		return "fixed tests"

	def execute_generated_tests(module_filename, code_content, test_filename, test_content):
		execution_calls.append((module_filename, code_content, test_filename, test_content))
		return {"ran": True, "returncode": 0, "summary": "1 passed"}

	state = build_test_validation_runtime_state(
		output,
		"initial tests",
		"initial tests",
		"code_implementation",
		"code_implementation.py",
		"def ok():\n    return 1",
		{"syntax_ok": True},
		"exact contract",
		"behavior contract",
		"tests_tests.py",
		12,
		3,
		5,
		1,
		finalize_generated_test_suite,
		lambda content, has_typed_artifact: bool(content.strip()) and has_typed_artifact,
		analyze_test_module,
		auto_fix_test_type_mismatches,
		lambda content: len(content.splitlines()),
		execute_generated_tests,
		lambda agent_output, **kwargs: {"raw_content": kwargs["raw_content"], "syntax_ok": kwargs["syntax_ok"]},
		lambda test_execution, module_filename, test_filename: f"{module_filename}:{test_filename}:{test_execution['returncode']}",
		lambda content: f"summary:{content}",
	)

	assert isinstance(state, ValidationRuntimeState)
	assert state.test_content == "fixed tests"
	assert state.test_artifact_content == "fixed tests"
	assert state.test_analysis == {
		"syntax_ok": True,
		"analysis_of": "fixed tests",
		"line_count": 1,
		"line_budget": 12,
		"expected_top_level_test_count": 3,
		"max_top_level_test_count": 5,
		"fixture_budget": 1,
	}
	assert state.test_execution == {"ran": True, "returncode": 0, "summary": "1 passed"}
	assert state.completion_diagnostics == {"raw_content": "fixed tests", "syntax_ok": True}
	assert state.module_filename == "code_implementation.py"
	assert state.test_filename == "tests_tests.py"
	assert state.pytest_failure_origin == "code_implementation.py:tests_tests.py:0"
	assert analyzed_contents == ["finalized tests", "fixed tests"]
	assert execution_calls == [("code_implementation.py", "def ok():\n    return 1", "tests_tests.py", "fixed tests")]
	assert output.raw_content == "fixed tests"
	assert output.summary == "summary:fixed tests"
	assert output.artifacts[0].content == "fixed tests"


def test_validate_test_output_runtime_rejects_syntax_invalid_code_directly():
	output = AgentOutput(summary="tests", raw_content="def test_ok():\n    assert True")

	with pytest.raises(AgentExecutionError, match="code under test has syntax error invalid syntax"):
		validate_test_output_runtime(
			{
				"code_analysis": {"syntax_ok": False, "syntax_error": "invalid syntax"},
				"module_name": "code_implementation",
				"code": "def broken(:\n    pass",
			},
			output,
			None,
			None,
			None,
			None,
			lambda *args, **kwargs: None,
			lambda *args, **kwargs: True,
			lambda *args, **kwargs: {},
			lambda *args, **kwargs: "",
			lambda *args, **kwargs: 0,
			lambda *args, **kwargs: {},
			lambda *args, **kwargs: {},
			lambda *args, **kwargs: "tests",
			lambda *args, **kwargs: None,
			lambda *args, **kwargs: None,
			lambda content: content,
		)


def test_validation_analysis_helpers_classify_blocking_and_warning_issues_directly():
	blocking_validation = {
		"test_analysis": {
			"syntax_ok": True,
			"undefined_local_names": ["result"],
		}
	}
	warning_validation = {
		"test_analysis": {
			"syntax_ok": True,
			"constructor_arity_mismatches": ["MyClass (line 5)"],
		}
	}

	assert validation_has_static_issues(blocking_validation) is True
	assert validation_has_blocking_issues(blocking_validation) is True
	assert validation_has_blocking_issues(warning_validation) is False
	assert validation_has_only_warnings(warning_validation) is True


def test_collect_code_validation_issues_classifies_all_current_failure_paths_directly():
	issues = collect_code_validation_issues(
		{
			"syntax_ok": False,
			"syntax_error": "invalid syntax",
			"line_count": 12,
			"main_guard_required": True,
			"has_main_guard": False,
			"invalid_dataclass_field_usages": ["field(name='x')"],
		},
		10,
		{"issues": ["must expose run()"]},
		{"ran": True, "returncode": 1, "summary": "ImportError: nope"},
		{"likely_truncated": True},
		lambda diagnostics: "output likely truncated",
	)

	assert issues == [
		"syntax error invalid syntax",
		"line count 12 exceeds maximum 10",
		"missing required CLI entrypoint",
		"module import failed: ImportError: nope",
		"task public contract mismatch: must expose run()",
		"non-dataclass field(...) usage: field(name='x')",
		"output likely truncated",
	]


def test_collect_test_validation_issues_classifies_blocking_warning_and_pytest_paths_directly():
	test_analysis = {
		"syntax_ok": True,
		"line_count": 12,
		"line_budget": 10,
		"tests_without_assertions": ["test_empty (line 2)"],
		"constructor_arity_mismatches": ["Workflow expects 2 args but test uses 1 at line 4"],
		"undefined_local_names": ["result (line 5)"],
	}
	test_execution = {"ran": True, "returncode": 1, "summary": "1 failed"}
	completion_diagnostics = {"likely_truncated": True}

	validation_issues, warning_issues, pytest_passed = collect_test_validation_issues(
		test_analysis,
		test_execution,
		completion_diagnostics,
		lambda diagnostics: "completion likely truncated",
	)

	assert pytest_passed is False
	assert validation_issues == [
		"line count 12 exceeds maximum 10",
		"undefined local names: result (line 5)",
		"completion likely truncated",
		"pytest failed: 1 failed",
	]
	assert warning_issues == [
		"tests without assertion-like checks: test_empty (line 2)",
		"constructor arity mismatches: Workflow expects 2 args but test uses 1 at line 4",
	]


def test_test_validation_error_message_handles_blocking_and_warning_only_paths_directly():
	assert validation_error_message_for_test_result(["pytest failed: 1 failed"], ["warning detail"], False) == (
		"Generated test validation failed: pytest failed: 1 failed; (warning) warning detail"
	)
	assert validation_error_message_for_test_result([], ["warning detail"], False) == (
		"Generated test validation failed: warning detail (pytest did not confirm correctness)"
	)
	assert validation_error_message_for_test_result([], ["warning detail"], True) is None


def test_validation_analysis_helpers_detect_contract_overreach_directly():
	test_execution = {
		"stdout": "FAILED tests_tests.py::test_example - AssertionError: assert 'approved' == 'rejected'\n",
		"stderr": "",
	}

	signals = pytest_contract_overreach_signals(test_execution)

	assert signals == [
		"exact status/action label mismatch ('approved' vs 'rejected') suggests an unsupported threshold assumption"
	]