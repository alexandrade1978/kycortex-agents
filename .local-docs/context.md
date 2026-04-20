# Local Operational Context

Date: 2026-04-19

## Refactor mode override

- published baseline remains `v1.0.13a6`
- development head is now `1.0.13a10.dev0`
- active release, canary, and production-readiness claims are suspended on the development branch
- paid canonical full-matrix reruns are frozen until deterministic gates and targeted provider/model smokes are green
- first low-risk internal refactor slices completed: acceptance typed contracts, private artifact permission hardening, and artifact persistence support extracted under `kycortex_agents/orchestration/`
- second low-risk internal slice completed: sandbox bootstrap templates and AST name-replacement helper extracted under `kycortex_agents/orchestration/`, with `Orchestrator` now rendering sandbox files through internal support modules instead of embedding those templates inline
- third low-risk internal slice completed: generated-test sandbox runtime bootstrap extracted under `kycortex_agents/orchestration/`, including secret-env detection, generated filename sanitization, environment sanitization, and sandbox `preexec_fn` construction
- fourth low-risk internal slice completed: validation-runtime helpers extracted under `kycortex_agents/orchestration/validation_runtime.py`, moving pytest-output summarization, validation-result redaction, and provider-call metadata sanitization/retrieval out of `Orchestrator`
- fifth low-risk internal slice completed: task constraint parsing and architecture-context compaction extracted under `kycortex_agents/orchestration/task_constraints.py`, moving line budgets, CLI-entrypoint detection, top-level test and fixture budgets, and compact anchored-architecture prompt shaping out of `Orchestrator`
- sixth low-risk internal slice completed: workflow-control and safe-log helpers extracted under `kycortex_agents/orchestration/workflow_control.py`, moving workflow pause/resume/cancel/skip/override/replay operations plus task-id count minimization and safe event logging out of `Orchestrator`
- seventh low-risk internal slice completed: validation-analysis helpers extracted under `kycortex_agents/orchestration/validation_analysis.py`, moving pytest-failure parsing, contract-overreach detection, failure-origin inspection, and warning-vs-blocking test-validation classification out of `Orchestrator`
- eighth low-risk internal slice completed: sandbox execution helpers extracted under `kycortex_agents/orchestration/sandbox_execution.py`, moving generated-module import execution, generated pytest execution, runner-file writing, and sandbox-security-violation detection out of `Orchestrator`
- ninth low-risk internal slice completed: validation reporting helpers extracted under `kycortex_agents/orchestration/validation_reporting.py`, moving completion-diagnostics derivation, truncation heuristics, and code/test validation summary rendering out of `Orchestrator`
- tenth low-risk internal slice completed: repair-instruction helpers extracted under `kycortex_agents/orchestration/repair_instructions.py`, moving deterministic repair-instruction composition for validation and test-failure paths out of `Orchestrator`
- eleventh low-risk internal slice completed: repair-analysis helpers extracted under `kycortex_agents/orchestration/repair_analysis.py`, moving deterministic regex/AST repair detectors and rewrite-hint derivation out of `Orchestrator`
- twelfth low-risk internal slice completed: repair-signal helpers extracted under `kycortex_agents/orchestration/repair_signals.py`, moving deterministic datetime-import and required-evidence reuse heuristics out of `Orchestrator`
- thirteenth low-risk internal slice completed: test-surface analysis helpers extracted under `kycortex_agents/orchestration/repair_test_analysis.py`, moving validation-summary symbol parsing, helper-alias drift detection, reusable missing-import analysis, and previous-valid-test-surface AST recovery out of `Orchestrator`
- fourteenth low-risk internal slice completed: runtime-only test-repair priorities extracted under `kycortex_agents/orchestration/repair_test_runtime.py`, moving deterministic runtime assertion-overreach guidance and failure-shape repair heuristics out of `Orchestrator`
- fifteenth low-risk internal slice completed: structural test-repair priorities extracted under `kycortex_agents/orchestration/repair_test_structure.py`, moving deterministic helper-surface cleanup, budget guidance, assertionless-test repair, import hygiene, truncation, constructor-arity, payload-contract, and fixture-shape priorities out of `Orchestrator`
- sixteenth low-risk internal slice completed: code-validation repair priorities extracted under `kycortex_agents/orchestration/repair_code_validation.py`, moving deterministic public-contract, pytest-failure, duplicate-constructor, attribute-alignment, dataclass-order, import-hygiene, truncation, object-semantics, and timezone-comparison repair guidance out of `Orchestrator`
- seventeenth low-risk internal slice completed: test-validation repair composition extracted under `kycortex_agents/orchestration/repair_test_validation.py`, moving type-mismatch priority injection, repair-surface analysis, helper-surface fallback normalization, assertionless-test parsing, and structural/runtime repair-priority composition out of `Orchestrator`
- eighteenth low-risk internal slice completed: repair-focus dispatch extracted under `kycortex_agents/orchestration/repair_focus.py`, moving shared signal/detail collection and category dispatch for `_repair_focus_lines(...)` out of `Orchestrator`
- nineteenth low-risk internal slice completed: the remaining `_repair_focus_lines(...)` compatibility wrapper was retired from `Orchestrator`, with production call sites and direct regressions now targeting `build_repair_focus_lines(...)` from internal orchestration support
- twentieth low-risk internal slice completed: the remaining `_build_test_validation_summary(...)` compatibility wrapper was retired from `Orchestrator`, with production call sites and direct regressions now targeting `build_test_validation_summary(...)` from internal orchestration support
- twenty-first low-risk internal slice completed: the remaining `_build_code_validation_summary(...)` compatibility wrapper was retired from `Orchestrator`, with production call sites and direct regressions now targeting `build_code_validation_summary(...)` from internal orchestration support
- twenty-second low-risk internal slice completed: dependency validation summary rendering was extracted into `kycortex_agents/orchestration/validation_reporting.py`, retiring `_build_dependency_validation_summary(...)` from `Orchestrator`
- twenty-third low-risk internal slice completed: output summarization and semantic output-key helpers were extracted into `kycortex_agents/orchestration/output_helpers.py`, retiring `_summarize_output(...)` and `_semantic_output_key(...)` from `Orchestrator`
- twenty-fourth low-risk internal slice completed: agent-result normalization and unredacted-output recovery were extracted into `kycortex_agents/orchestration/output_helpers.py`, retiring `_normalize_agent_result(...)` and `_unredacted_agent_result(...)` from `Orchestrator`
- twenty-fifth low-risk internal slice completed: agent-resolution validation was extracted into `kycortex_agents/orchestration/workflow_control.py`, retiring `_validate_agent_resolution(...)` from `Orchestrator`
- twenty-sixth low-risk internal slice completed: workflow acceptance evaluation was extracted into `kycortex_agents/orchestration/workflow_acceptance.py`, retiring `_task_acceptance_lists(...)`, `_observed_failure_categories(...)`, and `_evaluate_workflow_acceptance(...)` from `Orchestrator`
- twenty-seventh low-risk internal slice completed: AST name rendering and pytest-fixture detection were extracted into `kycortex_agents/orchestration/ast_tools.py`, retiring `_ast_name(...)` and `_is_pytest_fixture(...)` from `Orchestrator`
- twenty-eighth low-risk internal slice completed: agent execution dispatch was extracted into `kycortex_agents/orchestration/agent_runtime.py`, retiring `_execute_agent(...)` from `Orchestrator`
- twenty-ninth low-risk internal slice completed: agent-input assembly was extracted into `kycortex_agents/orchestration/agent_runtime.py`, leaving `_build_agent_input(...)` as a thin compatibility wrapper while direct regression anchors still target the façade method
- thirtieth low-risk internal slice completed: small AST-expression helpers were extracted into `kycortex_agents/orchestration/ast_tools.py`, retiring `_callable_name(...)`, `_attribute_chain(...)`, `_expression_root_name(...)`, `_render_expression(...)`, and `_first_call_argument(...)` from `Orchestrator`
- thirty-first low-risk internal slice completed: test-module AST analysis helpers were extracted into `kycortex_agents/orchestration/test_ast_analysis.py`, moving local-name binding collection, parametrized-argument discovery, mock/patch support detection, unsupported mock-assertion detection, and test local-type collection out of `Orchestrator` while keeping private wrapper methods stable
- thirty-second low-risk internal slice completed: pytest assertion-context and assertion-like counting helpers were co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_with_uses_pytest_raises(...)`, `_with_uses_pytest_assertion_context(...)`, and `_count_test_assertion_like_checks(...)` logic out of `Orchestrator` while preserving thin wrappers
- thirty-third low-risk internal slice completed: adjacent AST test-analysis helpers were co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_ast_contains_node(...)`, `_collect_local_bindings(...)`, and `_collect_module_defined_names(...)` logic out of `Orchestrator` while preserving thin wrappers
- thirty-fourth low-risk internal slice completed: module AST signature helpers were extracted into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_annotation_accepts_sequence_input(...)`, `_call_signature_details(...)`, `_method_binding_kind(...)`, and `_self_assigned_attributes(...)` logic out of `Orchestrator` while preserving thin wrappers
- thirty-fifth low-risk internal slice completed: adjacent dataclass and call-basename helpers were co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_has_dataclass_decorator(...)`, `_call_expression_basename(...)`, `_dataclass_field_has_default(...)`, and `_dataclass_field_is_init_enabled(...)` logic out of `Orchestrator` while preserving thin wrappers
- thirty-sixth low-risk internal slice completed: sequence-input and required-field analysis helpers were co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_first_user_parameter(...)`, `_parameter_is_iterated(...)`, `_comparison_required_field(...)`, `_extract_required_fields(...)`, `_extract_indirect_required_fields(...)`, `_field_selector_name(...)`, and `_extract_lookup_field_rules(...)` logic out of `Orchestrator` while preserving thin wrappers
- thirty-seventh low-risk internal slice completed: adjacent sequence-input rule helpers were co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_direct_return_expression(...)`, `_callable_parameter_names(...)`, and `_extract_sequence_input_rule(...)` logic out of `Orchestrator` while preserving thin wrappers
- thirty-eighth low-risk internal slice completed: static dict-example and dict-key analysis helpers were co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_example_from_default(...)`, `_infer_dict_key_value_examples(...)`, and `_dict_accessed_keys_from_tree(...)` logic out of `Orchestrator` while preserving compatibility shims
- thirty-ninth low-risk internal slice completed: `isinstance`-based type-constraint helpers were co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_extract_type_constraints(...)`, `_collect_isinstance_calls(...)`, `_isinstance_subject_name(...)`, and `_isinstance_type_names(...)` logic out of `Orchestrator` while preserving thin wrappers
- fortieth low-risk internal slice completed: literal-example and batch-rule helpers were co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_extract_valid_literal_examples(...)` and `_extract_batch_rule(...)` logic out of `Orchestrator` while preserving thin wrappers
- forty-first low-risk internal slice completed: class-style, return-annotation, and constructor-storage helpers were co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_extract_class_definition_style(...)`, `_extract_return_type_annotation(...)`, and `_extract_constructor_storage_rule(...)` logic out of `Orchestrator` while preserving thin wrappers
- forty-second low-risk internal slice completed: score-derivation helpers were co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_extract_score_derivation_rule(...)`, `_function_returns_score_value(...)`, `_render_score_expression(...)`, `_inline_score_helper_expression(...)`, and `_expand_local_name_aliases(...)` logic out of `Orchestrator` while preserving thin wrappers
- forty-third low-risk internal slice completed: literal payload-inspection and argument-type inference helpers were co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_resolve_bound_value(...)`, `_call_argument_value(...)`, `_extract_literal_dict_keys(...)`, `_extract_literal_field_values(...)`, `_extract_string_literals(...)`, `_extract_literal_list_items(...)`, and `_infer_argument_type(...)` logic out of `Orchestrator` while preserving thin wrappers
- forty-fourth low-risk internal slice completed: typed member-usage inference helpers were co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_call_argument_count(...)`, `_infer_expression_type(...)`, `_infer_call_result_type(...)`, and `_analyze_typed_test_member_usage(...)` logic out of `Orchestrator` while preserving thin wrappers
- forty-fifth low-risk internal slice completed: payload-selection and batch-call validation helpers were co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_payload_argument_for_validation(...)` and `_validate_batch_call(...)` logic out of `Orchestrator` while preserving thin wrappers
- forty-sixth low-risk internal slice completed: negative-expectation and invalid-outcome helpers were co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_assert_expects_false(...)`, `_call_has_negative_expectation(...)`, `_assigned_name_for_call(...)`, `_assert_expects_invalid_outcome(...)`, `_invalid_outcome_subject_matches(...)`, `_invalid_outcome_marker_matches(...)`, and `_call_expects_invalid_outcome(...)` logic out of `Orchestrator` while preserving thin wrappers
- forty-seventh low-risk internal slice completed: partial-batch-result helpers were co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_batch_call_allows_partial_invalid_items(...)`, `_assert_limits_batch_result(...)`, `_len_call_matches_batch_result(...)`, `_int_constant_value(...)`, and `_comparison_implies_partial_batch_result(...)` logic out of `Orchestrator` while preserving thin wrappers
- forty-eighth low-risk internal slice completed: the shared AST parent-map utility was co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_parent_map(...)` logic out of `Orchestrator` while preserving the thin wrapper
- forty-ninth low-risk internal slice completed: contract-overreach score-state and visible-batch heuristics were co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_test_name_suggests_validation_failure(...)`, `_is_internal_score_state_target(...)`, `_behavior_contract_explicitly_limits_score_state_to_valid_requests(...)`, `_find_contract_overreach_signals(...)`, `_visible_repeated_single_call_batch_sizes(...)`, `_loop_contains_non_batch_call(...)`, `_exact_len_assertion(...)`, and `_is_len_call(...)` logic out of `Orchestrator` while preserving thin wrappers
- fiftieth low-risk internal slice completed: invalid-path and missing-audit-trail helpers were promoted for reuse from `kycortex_agents/orchestration/repair_analysis.py`, moving `_compare_mentions_invalid_literal(...)`, `_test_function_targets_invalid_path(...)`, `_attribute_is_field_reference(...)`, `_is_len_of_field_reference(...)`, `_test_requires_non_empty_result_field(...)`, `_ast_is_empty_literal(...)`, `_class_field_uses_empty_default(...)`, and `_invalid_outcome_audit_return_details(...)` logic behind shared repair-analysis helpers while preserving thin wrappers in `Orchestrator`
- fifty-first low-risk internal slice completed: QA repair-suite reuse evaluation was co-located into `kycortex_agents/orchestration/repair_test_analysis.py`, moving `_qa_repair_should_reuse_failed_test_artifact(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- fifty-second low-risk internal slice completed: failing pytest test-name parsing was promoted for reuse from `kycortex_agents/orchestration/repair_analysis.py`, moving `_failing_pytest_test_names(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- fifty-third low-risk internal slice completed: the dead `_append_unique_mapping_value(...)` façade wrapper was retired from `Orchestrator` now that the only live implementation remains internal to `kycortex_agents/orchestration/repair_test_analysis.py`
- fifty-fourth low-risk internal slice completed: the dead `_string_literal_sequence(...)` façade wrapper was retired from `Orchestrator` now that only support modules and `qa_tester` retain live implementations
- fifty-fifth low-risk internal slice completed: task public-contract surface parsing was co-located into `kycortex_agents/orchestration/task_constraints.py`, moving `_parse_task_public_contract_surface(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- fifty-sixth low-risk internal slice completed: task public-contract anchor extraction was co-located into `kycortex_agents/orchestration/task_constraints.py`, moving `_task_public_contract_anchor(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- fifty-seventh low-risk internal slice completed: task public-contract preflight evaluation was co-located into `kycortex_agents/orchestration/task_constraints.py`, moving `_task_public_contract_preflight(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- fifty-eighth low-risk internal slice completed: Python import-root discovery was co-located into `kycortex_agents/orchestration/ast_tools.py`, moving `_python_import_roots(...)` logic out of `Orchestrator` while preserving the thin façade wrapper there
- fifty-ninth low-risk internal slice completed: dependency-manifest normalization and validation helpers were co-located into `kycortex_agents/orchestration/dependency_analysis.py`, moving `_normalize_package_name(...)`, `_normalize_import_name(...)`, and `_analyze_dependency_manifest(...)` logic out of `Orchestrator` while preserving thin façade wrappers
- sixtieth low-risk internal slice completed: code-outline extraction was co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_build_code_outline(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- sixty-first low-risk internal slice completed: validation-summary limit parsing was co-located into `kycortex_agents/orchestration/task_constraints.py`, moving `_summary_limit_exceeded(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- sixty-second low-risk internal slice completed: budget-decomposition planner detection was co-located into `kycortex_agents/orchestration/task_constraints.py`, moving `_is_budget_decomposition_planner(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- sixty-third low-risk internal slice completed: budget-decomposition instruction and task-context builders were co-located into `kycortex_agents/orchestration/task_constraints.py`, moving `_build_budget_decomposition_instruction(...)` and `_build_budget_decomposition_task_context(...)` logic out of `Orchestrator` while preserving thin façade wrappers
- sixty-fourth low-risk internal slice completed: budget-decomposition gate evaluation was co-located into `kycortex_agents/orchestration/task_constraints.py`, moving `_repair_requires_budget_decomposition(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- Pylance remediation completed: tightened `AcceptanceLane` required fields in `kycortex_agents/orchestration/contracts.py` and added explicit AST/optional-value narrowing in tests so workspace diagnostics re-cleared without changing runtime behavior
- sixty-fifth low-risk internal slice completed: repair-owner routing was co-located into `kycortex_agents/orchestration/repair_instructions.py`, moving `_repair_owner_for_category(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- sixty-sixth low-risk internal slice completed: failure-category artifact-type mapping was co-located into `kycortex_agents/orchestration/repair_analysis.py`, moving the category-to-`ArtifactType` decision out of `_failed_artifact_content_for_category(...)` while preserving the thin façade wrapper
- sixty-seventh low-risk internal slice completed: budget-decomposition task creation/reuse was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_ensure_budget_decomposition_task(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- sixty-eighth low-risk internal slice completed: active repair-cycle lookup was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_active_repair_cycle(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- sixty-ninth low-risk internal slice completed: failed-artifact content lookup was co-located into `kycortex_agents/orchestration/artifacts.py`, moving `_failed_artifact_content(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- seventieth low-risk internal slice completed: failed-artifact lookup by failure category was co-located into `kycortex_agents/orchestration/repair_analysis.py`, moving `_failed_artifact_content_for_category(...)` composition out of `Orchestrator` while preserving the thin façade wrapper
- seventy-first low-risk internal slice completed: test-repair helper-surface usage parsing was co-located into `kycortex_agents/orchestration/repair_test_analysis.py`, moving `_test_repair_helper_surface_usages(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- seventy-second low-risk internal slice completed: prior repair-context merging was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_merge_prior_repair_context(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- seventy-third low-risk internal slice completed: repair-context assembly was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_build_repair_context(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- seventy-fourth low-risk internal slice completed: code-repair context assembly from failed tests was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_build_code_repair_context_from_test_failure(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- seventy-fifth low-risk internal slice completed: failed-test code-repair routing was co-located into `kycortex_agents/orchestration/repair_test_analysis.py`, moving `_test_failure_requires_code_repair(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- seventy-sixth low-risk internal slice completed: imported and upstream code-task lookup for failed tests were co-located into `kycortex_agents/orchestration/repair_test_analysis.py`, moving `_imported_code_task_for_failed_test(...)` and `_upstream_code_task_for_test_failure(...)` logic out of `Orchestrator` while preserving thin façade wrappers
- seventy-seventh low-risk internal slice completed: failed-task selection for repair planning was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_failed_task_ids_for_repair(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- seventy-eighth low-risk internal slice completed: repair-task id planning for a cycle was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_repair_task_ids_for_cycle(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- seventy-ninth low-risk internal slice completed: repair-attempt configuration was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_configure_repair_attempts(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- eightieth low-risk internal slice completed: active-cycle repair queueing was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_queue_active_cycle_repair(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- eighty-first low-risk internal slice completed: cycle-local repair-task presence lookup was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `_has_repair_task_for_cycle(...)` logic out of `Orchestrator` while preserving the thin façade wrapper
- eighty-second low-risk internal slice completed: failed-task repair-cycle resumption was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the `start_repair_cycle(...)` plus `resume_failed_tasks(...)` subflow out of `execute_workflow(...)`
- eighty-third low-risk internal slice completed: failed-workflow resume dispatch was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the non-repairable-vs-resume decision branch out of `execute_workflow(...)`
- eighty-fourth low-risk internal slice completed: workflow resume preparation was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving interrupted-task resumption, failed-task discovery, resume dispatch, and `workflow_resumed` logging/save out of the top of `execute_workflow(...)`
- eighty-fifth low-risk internal slice completed: workflow start guarding was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the `mark_workflow_running(...)` plus `workflow_started` logging guard out of `execute_workflow(...)`
- eighty-sixth low-risk internal slice completed: no-pending workflow completion was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the `completed` versus `degraded` terminal branch out of the main execution loop
- eighty-seventh low-risk internal slice completed: workflow-definition failure handling was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the `WorkflowDefinitionError` terminal branch out of the main execution loop
- eighty-eighth low-risk internal slice completed: workflow-blocked failure handling was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the `workflow_blocked` terminal branch out of the main execution loop
- eighty-ninth low-risk internal slice completed: workflow-continue task-failure handling was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the duplicate dependent-skip plus progress/save/log branch out of the task-execution failure path in `execute_workflow(...)`
- ninetieth low-risk internal slice completed: workflow fail-fast task-failure handling was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the duplicate terminal failed-state transition plus save/log branch out of the task-execution failure path in `execute_workflow(...)`
- ninety-first low-risk internal slice completed: workflow progress-plus-save handling was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the repeated progress emission plus persistence sequence out of the retry, repair-chain, continue-policy, and success paths in `execute_workflow(...)`
- ninety-second low-risk internal slice completed: task-failure dispatch was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the remaining retry versus repairable versus policy-routing decision tree out of the task-execution failure path in `execute_workflow(...)`
- ninety-third low-risk internal slice completed: per-task workflow execution was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the cancel/pause guards, `run_task(...)` invocation, exception handoff, and success progress/save path out of the inner task loop in `execute_workflow(...)`
- ninety-fourth low-risk internal slice completed: runnable-task iteration was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the `for task in runnable` traversal and early-return handoff out of the main workflow loop in `execute_workflow(...)`
- ninety-fifth low-risk internal slice completed: runnable-frontier execution was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving `project.runnable_tasks()` resolution, `WorkflowDefinitionError` handling, blocked-workflow handling, and frontier execution handoff out of the main workflow loop in `execute_workflow(...)`
- ninety-sixth low-risk internal slice completed: outer workflow-loop control was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the remaining `while True` cancel/pause checks, pending-task lookup, completion check, and runnable-frontier dispatch out of `execute_workflow(...)`
- ninety-seventh low-risk internal slice completed: the active-workflow shell was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the post-resume cancel/pause guards, start guard, outer-loop handoff, and terminal `workflow_finished` logging out of `execute_workflow(...)`
- ninety-eighth low-risk internal slice completed: the workflow bootstrap shell was co-located into `kycortex_agents/orchestration/workflow_control.py`, moving the initial cancel gate, execution-plan bootstrap, agent-resolution validation, repair-budget initialization, resume handoff, and active-workflow handoff out of `execute_workflow(...)`
- ninety-ninth low-risk internal slice completed: the final workflow-runtime façade was co-located into `kycortex_agents/orchestration/workflow_control.py`, leaving `Orchestrator.execute_workflow(...)` as a very thin delegation shell over the extracted runtime pipeline
- one-hundredth low-risk internal slice completed: repair-context application inside `_build_context(...)` was co-located into `kycortex_agents/orchestration/context_building.py`, moving the final repair-context field-population branch out of the large context-assembly method
- one-hundred-first low-risk internal slice completed: completed-task output application inside `_build_context(...)` was co-located into `kycortex_agents/orchestration/context_building.py`, moving completed-task registration, budget-brief carry-forward, planner short-circuiting, and semantic alias population out of the context-assembly loop body
- one-hundred-second low-risk internal slice completed: completed-task artifact-context dispatch inside `_build_context(...)` was co-located into `kycortex_agents/orchestration/context_building.py`, moving the role-based code/test/dependency artifact-context branch out of the loop body
- one-hundred-third low-risk internal slice completed: task public-contract anchor and architecture-compaction application inside `_build_context(...)` was co-located into `kycortex_agents/orchestration/context_building.py`, moving the anchor/compaction branch out of the context-assembly prelude
- one-hundred-fourth low-risk internal slice completed: Python module analysis was co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_analyze_python_module(...)` and third-party import detection out of `Orchestrator`
- one-hundred-fifth low-risk internal slice completed: code public-API summary rendering was co-located into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_build_code_public_api(...)` out of `Orchestrator`
- one-hundred-sixth low-risk internal slice completed: test type-mismatch enforcement analysis was co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_analyze_test_type_mismatches(...)` out of `Orchestrator` while preserving the thin façade wrapper
- one-hundred-seventh low-risk internal slice completed: test type-mismatch auto-fix logic was co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_auto_fix_test_type_mismatches(...)` out of `Orchestrator` while preserving the thin façade wrapper and passing dict-key discovery as a callback to avoid a support-module cycle
- one-hundred-eighth low-risk internal slice completed: full generated-test module analysis was co-located into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_analyze_test_module(...)` out of `Orchestrator` while preserving the thin façade wrapper and passing precomputed boundary inputs to avoid cycles back into `module_ast_analysis.py`
- one-hundred-ninth low-risk internal slice completed: generated-test validation issue aggregation was co-located into `kycortex_agents/orchestration/validation_analysis.py`, moving the deterministic `validation_issues`/`warning_issues` assembly out of `_validate_test_output(...)`
- one-hundred-tenth low-risk internal slice completed: generated-test validation error-message composition was co-located into `kycortex_agents/orchestration/validation_analysis.py`, moving the final `validation_issues`/`warning_issues` outcome formatting out of `_validate_test_output(...)`
- one-hundred-eleventh low-risk internal slice completed: repeated generated-test output content replacement was co-located into `kycortex_agents/orchestration/validation_runtime.py`, moving the shared `AgentOutput` test-content mutation path out of `_validate_test_output(...)`
- one-hundred-twelfth low-risk internal slice completed: generated-test validation metadata persistence was co-located into `kycortex_agents/orchestration/validation_runtime.py`, moving the repeated `_record_output_validation(...)` test-validation field writes out of `_validate_test_output(...)`
- one-hundred-thirteenth low-risk internal slice completed: generated-test validation runtime-state preparation was co-located into `kycortex_agents/orchestration/validation_runtime.py`, moving the broader finalize/analyze/autofix/budget/execute/diagnostics flow out of `_validate_test_output(...)`
- one-hundred-fourteenth low-risk internal slice completed: the final `_validate_test_output(...)` orchestration shell was co-located into `kycortex_agents/orchestration/validation_runtime.py`, leaving `Orchestrator` with a thin façade delegation over the extracted generated-test validation runtime helpers
- one-hundred-fifteenth low-risk internal slice completed: generated-code validation issue aggregation was co-located into `kycortex_agents/orchestration/validation_analysis.py`, moving the deterministic `validation_issues` assembly out of `_validate_code_output(...)`
- one-hundred-sixteenth low-risk internal slice completed: generated-code validation metadata persistence was co-located into `kycortex_agents/orchestration/validation_runtime.py`, moving the repeated `_record_output_validation(...)` writes out of `_validate_code_output(...)`
- one-hundred-seventeenth low-risk internal slice completed: the final `_validate_code_output(...)` orchestration shell was co-located into `kycortex_agents/orchestration/validation_runtime.py`, leaving `Orchestrator` with a thin façade delegation over the extracted generated-code validation runtime helpers
- one-hundred-eighteenth low-risk internal slice completed: dependency-manifest validation inside `_validate_task_output(...)` was co-located into `kycortex_agents/orchestration/validation_runtime.py`, leaving `_validate_task_output(...)` as a thin role-dispatch façade over extracted code, test, and dependency validation helpers
- one-hundred-nineteenth low-risk internal slice completed: the base context bootstrap inside `_build_context(...)` was co-located into `kycortex_agents/orchestration/context_building.py`, moving the initial `ctx` assembly and planned-module alias synchronization behind `build_task_context_base(...)`
- one-hundred-twentieth low-risk internal slice completed: the completed-task context loop inside `_build_context(...)` was co-located into `kycortex_agents/orchestration/context_building.py`, moving visible-output traversal, semantic aliasing, and artifact-context dispatch behind `apply_completed_tasks_to_context(...)`
- one-hundred-twenty-first low-risk internal slice completed: the final `_build_context(...)` orchestration shell was co-located into `kycortex_agents/orchestration/context_building.py`, leaving `Orchestrator` with a thin façade delegation over the extracted context-building runtime helpers
- one-hundred-twenty-second low-risk internal slice completed: `_build_agent_view(...)` and its adjacent result/decision/artifact filters were co-located into `kycortex_agents/orchestration/context_building.py`, leaving `Orchestrator` with a thin façade delegation over the extracted agent-view runtime helpers
- one-hundred-twenty-third low-risk internal slice completed: the adjacent task-visibility helpers `_task_dependency_closure_ids(...)` and `_direct_dependency_ids(...)` were co-located into `kycortex_agents/orchestration/context_building.py`, further consolidating the context/view assembly corridor outside `Orchestrator`
- one-hundred-twenty-fourth low-risk internal slice completed: `_build_repair_validation_summary(...)` was co-located into `kycortex_agents/orchestration/validation_reporting.py`, leaving `Orchestrator` with a thin façade delegation over the extracted repair-validation summary dispatcher
- one-hundred-twenty-fifth low-risk internal slice completed: the adjacent payload/context-output helpers `_validation_payload(...)` and `_task_context_output(...)` were co-located into `kycortex_agents/orchestration/output_helpers.py`, further reducing the remaining repair/output corridor in `Orchestrator`
- one-hundred-twenty-sixth low-risk internal slice completed: `_build_code_repair_instruction_from_test_failure(...)` was co-located into `kycortex_agents/orchestration/repair_instructions.py`, leaving `Orchestrator` with a thin façade delegation over the extracted code-repair instruction runtime helper
- GitHub Actions remediation after `2129ce7`: `mypy` now excludes generated `build/`, `dist/`, and `.eggs/` artifacts, and the remaining stale `callable_name` local references in `Orchestrator` were aligned to the extracted helper naming so the full CI typecheck path re-clears
- GitHub Actions remediation after `cc960de`: the coverage gate now re-clears locally at `1620 passed` and `90.02%` after fixing the last stale `callable_name`-to-`called_name` formatting paths in `Orchestrator` and adding direct coverage for deterministic orchestration helpers instead of weakening `fail_under = 90`
- GitHub Actions remediation completed on the refactor branch: `ProjectState.mark_workflow_finished()` now accepts generic acceptance-evaluation mappings, which clears the `mypy` failure that was breaking the first CI job across the latest six pushes
- `Orchestrator` still exposes private helper wrappers for the extracted persistence path as temporary compatibility shims while direct tests still target those methods
- the rest of this file is retained as historical context and architectural reference unless explicitly superseded by this override

## Quick snapshot

- repository: `kycortex-agents`
- expected branch: `main`
- observed canary candidate: historical published baseline `f99a38d Prepare v1.0.13a6 release candidate`
- local package version: `1.0.13a10.dev0`
- latest published version: `1.0.13a6`
- public state: alpha, not production-ready
- internal Beta 1 interpretation: production-ready and defensible, not a packaging milestone
- local-plan phase: 16 of 17
- newer-head empirical state is frozen as historical evidence until the refactor branch requalifies itself through deterministic gates and targeted smokes
- active engineering focus: `_build_context(...)` has reached a near-endpoint thin façade, and the static code-analysis boundary is expanding in `module_ast_analysis.py` with both module analysis and public-API summary rendering now moved out of `Orchestrator`
- active engineering focus: the repair/output corridor is continuing to shrink, with the code-repair instruction runtime shell now also moved to shared support modules beside the repair-validation summary dispatcher and local payload/context-output helpers
- latest local checkpoint: `_validate_test_output(...)`, `_validate_code_output(...)`, `_validate_task_output(...)`, `_build_context(...)`, `_build_agent_view(...)`, `_task_dependency_closure_ids(...)`, `_direct_dependency_ids(...)`, `_build_repair_validation_summary(...)`, `_validation_payload(...)`, `_task_context_output(...)`, and `_build_code_repair_instruction_from_test_failure(...)` are now thin façades or extracted support helpers
- repository sync state at checkpoint: local `main` is clean and aligned with `origin/main`

## Current host environment

- current system: native Linux, without Windows + WSL in the main work path
- detected RAM: approximately 32 GB
- detected CPU: Intel Core i7-14700KF
- detected GPU: NVIDIA GeForce RTX 4060 Ti 8 GB
- detected disks: 2 WD_BLACK SN850X NVMe drives of approximately 1 TB each

Practical reading:

- more usable memory for the full host
- less filesystem and loopback friction than the old WSL setup
- more usable space for models, outputs, caches, and empirical campaigns

## What this product is

KYCortex Agents is an LLM agent-orchestration framework.

The product is not just a bundle of prompts. It is a runtime with:

- dependency-aware orchestration
- specialized agents
- execution sandbox for validating generated artifacts
- JSON and SQLite persistence
- retry, fallback, circuit breaker, and repair loops
- a strong boundary between public and internal surfaces

## Key architectural decisions

### 1. Four-view boundary model

The four active views are:

- internal persisted state as the source of truth for resume
- `ProjectSnapshot` as the public read model
- `AgentView` as filtered prompt context
- `ProjectState.internal_runtime_telemetry()` as the exact internal surface for operator and UI use

### 2. Isolated execution of generated artifacts

The framework executes tests and imports for generated code in sandboxed subprocesses, with:

- filesystem restrictions
- environment restrictions
- resource limits
- path and symlink escape blocking

### 3. Very strict public/internal boundary

The repository went through an intense public-surface minimization phase between 2026-04-02 and 2026-04-07.

Practical conclusion:

- exact telemetry must be read internally
- public snapshots are deliberately reduced

## Current known operational state

- v30 is the latest canonical 5×3 rerun: 11/15 GREEN (OpenAI 5/5, Ollama 5/5, Anthropic 1/5+4 DEGRADED)
- v35b/v39 confirmed qwen2.5-coder:14b CPU as gold standard local model (5/5 GREEN)
- v41 confirmed model sensitivity: gpt-4.1-mini drops to 1/5 GREEN (only insurance passes)
- root cause of model sensitivity identified: the behavior contract extracts field names but not type constraints from generated code
- models other than gpt-4o-mini generate wrong fixture types (e.g., `details='details'` string instead of dict), which passes lenient code but fails strict code
- remediation plan approved: 3-phase structural fix targeting orchestrator.py (type-aware behavior contract, type-mismatch detection, repair diagnostics) and qa_tester.py (prompt adjustment)
- validation target: 3 models × 5 scenarios = 15 runs (gpt-4o-mini regression, gpt-4.1-mini fix verification, qwen2.5-coder:14b cross-model)
- uncommitted changes: `ollama_think` parameter support in config.py, provider_matrix.py, ollama_provider.py, and matrix runner
- HEAD is `829adc4` (Fix infinite loop: add PROVIDER_TRANSIENT to orchestrator repairable set)
- 8 commits ahead of the canary base on `f99a38d` (v30 fixes, validator improvements, contract expansions)
- published canary `v1.0.13a6` window is still open on `f99a38d` — daily reviews continue independently
- canary target close date was `2026-04-20` (7-day minimum from `2026-04-13`) — overdue for daily review follow-up

Practical reading:

- the problem is no longer lack of visibility into historical local failures
- there is now both a historical failure baseline and a clean canonical rerun for the prompt-hardened candidate line
- the blocker for Phase 15 is now gone: the canonical matrix, local validation stack, and GitHub CI all stayed green on the same candidate line
- the active next problem is no longer cutting a fresh candidate; `v1.0.13a6` is already published with verified release assets
- the active next problem is now progressing the published `v1.0.13a6` canary from the clean 50-eligible-workflow checkpoint toward the 100-workflow threshold while keeping the daily review trail current and rollback pinned to `v1.0.13a2`
- the immediate Phase 16 baseline is no longer empty: there is now a repository-controlled guide covering runbook, rollback, escalation, incident templates, and canary evidence expectations
- the exact canary evidence path is no longer implicit: the guide now states which claims come from `snapshot()`, which come from `internal_runtime_telemetry()`, and how the evidence packet should be assembled
- the current owner model is no longer implicit either: the repository now documents a single-maintainer Phase 16 binding and a tracked root for evidence bundles
- the remaining Phase 16 gap is no longer bundle structure or release publication; it is collecting enough live evidence on the published `v1.0.13a6` line to close the canary window credibly
- there is now an active open canary window for the published `v1.0.13a6` candidate at `docs/canary-evidence/f99a38d/`; `docs/canary-evidence/c74e957/` remains the prior published abort record alongside the earlier published `v1.0.13a4` abort bundle on `8bfdc29`
- Beta 1 is being treated as a production claim for enterprise and developer users, so bounded completion alone is not enough to exit Phase 15

## Current provider runtime

### Cloud credentials

Current state:

- `OPENAI_API_KEY` validated with a health check and minimal generation
- `ANTHROPIC_API_KEY` validated with a health check and minimal generation
- `ANTHROPIC_BASE_URL` active and working for the Anthropic API via the intermediate endpoint

Applied local configuration:

- credentials moved from `~/.bashrc` to `~/.config/kycortex/provider.env`
- session mirror created at `~/.config/environment.d/kycortex-providers.conf`
- `~/.bashrc` and `~/.profile` now source the private file

Important note:

- no sudo-based change was made to global system files
- the configuration was kept at the user and session level

### Local Ollama

Confirmed current state:

- active endpoint: `http://127.0.0.1:11434`
- old `11435` is not active
- observed models in the runtime: `gemma4:26b`, `llama3.2:latest`, `qwen2.5-coder:7b`, `qwen2.5-coder:14b`

Recommended baseline for this project:

- use `qwen2.5-coder:14b` as the main local baseline for integrated matrix runs
- keep `qwen2.5-coder:7b` installed for comparison
- keep `gemma4:26b` installed only for experimentation

Motivation:

- `qwen2.5-coder:14b` (9 GB) provides substantially more reliable code generation than `qwen2.5-coder:7b` (4.7 GB) while remaining within practical timeout budgets
- `gemma4:26b` (18 GB) proved too slow for practical matrix runs
- the `--ollama-model` CLI argument in the matrix runner makes the model choice a per-run decision

Current empirical campaign result:

- v28: 10/10 GREEN on OpenAI+Ollama 5×2 (first clean integrated matrix on newer head)
- v30: 11/15 GREEN on 5×3 (OpenAI 5/5, Ollama 5/5, Anthropic 1/5+4 DEGRADED)
- v35b/v39: qwen2.5-coder:14b CPU = 5/5 GREEN (gold standard, confirmed across Ollama versions)
- v37c: qwen3.5:9b GPU = 3/5 GREEN (fast but inconsistent)
- v38: qwen2.5-coder:14b GPU partial offload = 2/5 GREEN (offload degrades quality)
- v40: qwen3-coder:30b MoE CPU = 0/3 GREEN (too weak)
- v41: gpt-4.1-mini = 1/5 GREEN (model sensitivity confirmed)
- model sensitivity root cause identified: behavior contract is type-blind

## Resolved contradiction on the newer head

The newer head originally produced contradictory evidence on the partial `5 x 2` rerun at `/home/tupira/Dados/experiments/kycortex_agents/full_matrix_validation_2026_04_13_v8_openai_ollama`, which motivated a full chain of fixes from v9 through v28.

The contradiction chain has been fully resolved through v30:

- v28: 10/10 GREEN on OpenAI+Ollama 5×2 (first clean integrated matrix)
- v29: 9/15 on 5×3 (OpenAI regression + Anthropic gaps exposed)
- v30: 11/15 on 5×3 (OpenAI 5/5 recovered, Anthropic 1/5+4 DEGRADED with validator bug fixed)

Beyond the provider-level resolution, v35b-v41 revealed a deeper structural issue:

- the framework is model-sensitive: changing models drops results significantly (gpt-4.1-mini 1/5, qwen3-coder:30b 0/3)
- the root cause is a type-blind behavior contract in the code-to-test bridge
- a structural remediation plan has been approved and is ready for implementation

## Recommended next priority

1. commit the `ollama_think` infrastructure changes and documentation updates
2. implement Phase 1 of the model-agnostic fix: type-aware behavior contract in orchestrator.py
3. implement Phase 2: QA tester prompt adjustment in qa_tester.py
4. implement Phase 3: type-aware repair diagnostics in orchestrator.py
5. validate with 3 models × 5 scenarios = 15 runs
6. resume canary daily reviews for the published v1.0.13a6 window

## Relevant local files

- `.local-docs/plan.md`
- `.local-docs/roadmap.md`
- `.local-docs/release-checklist.md`
- `.local-docs/history.md`
- `.local-docs/campaign.md`
- `.local-docs/evolution-log.md`

## What is known vs. what is still unconfirmed

Known:

- the 17-phase structure is coherent with the repository
- Phase 15 is the real-world campaign
- Phases 16 and 17 are defined in `docs/go-live-policy.md`
- the post-Beta 1 internal UI is aligned with `InternalRuntimeTelemetry`

Not confirmed from Git:

- the exact content of the old lost `.local-docs/`

Confirmed by the Linux rerun:

- the scenarios that currently fail in Ollama are `kyc_compliance_intake`, `insurance_claim_triage`, `vendor_onboarding_risk`, and `access_review_audit`
- `returns_abuse_screening` completes in Ollama after 1 repair cycle

Operational rule:

- whenever something cannot be demonstrated from the repository, keep it marked as reconstructed or unconfirmed

## Current state (2026-04-17)

Git HEAD: `179bb1f` (Fix 10) on `main`, pushed to `origin/main`.

### Fixes since v1.0.13a6

- Fix 3–3c: behavior contract dict key hints and concrete examples
- Fix 4–5: programmatic auto-fix for str→dict mismatches, line-specific
- Fix 6: skip auto-fix in validation-failure tests, detect `.get()` dict access
- Fix 7: auto-fix reuses local dict variable
- Fix 8 (`aa76db9`): dict-variable alias resolution, word-boundary guards
- Fix 9 (`9d88d81`): reasoning model 4× token multiplier for gpt-5-mini/o-series
- Fix 10 (`179bb1f`): sys.modules registration for dynamic module validation (Python 3.12 dataclass fix)

### Test suite

- 1334 tests passing, ruff clean, mypy clean

### Validated models (latest runs)

| Model | Best Score | Config | Stochastic Range |
|-------|-----------|--------|-----------------|
| gpt-5-mini | 5/5 (v55, v58) | Fix 9 + Fix 10 | Consistent so far |
| gpt-4o-mini | 5/5 (v50) | max-repair=3 | 1/5 to 5/5 (avg ~2.7/5) |
| gpt-4.1-mini | 4/5 (v52) | Fix 8, max-repair=3 | 1/5 to 4/5 |
| qwen2.5-coder:14b | 5/5 (v35b, v39) | CPU Ollama | Consistent |

### Open concerns

1. Stochastic variance across LLM runs is large; repair cycles mask but do not solve the root issue
2. Empirical test coverage biased toward OpenAI; Anthropic and Ollama need revalidation
3. Architecture is multi-provider by design, but registry and testing are OpenAI-heavy
4. Branch strategy: all work on main; should consider feature branches for production
5. Documentation was behind; now updated (CHANGELOG, evolution-log, context)
