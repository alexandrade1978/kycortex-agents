# Local Plan - Beta 1

## 2026-04-19 Restart checkpoint

- Safe restart point: `abdc44d refactor: extract repair context assembly`
- Local git state at checkpoint: clean `main`, aligned with `origin/main`
- Most recent completed slices in order: category-based failed-artifact lookup, test-repair helper-surface usage parsing, prior repair-context merge, and repair-context assembly
- Most recent completed slices after restart: code-repair context assembly from failed tests extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include failed-test code-repair routing extracted into `kycortex_agents/orchestration/repair_test_analysis.py`
- Most recent completed slices after restart also include imported and upstream code-task lookup for failed tests extracted into `kycortex_agents/orchestration/repair_test_analysis.py`
- Most recent completed slices after restart also include failed-task selection for repair planning extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include repair-task id planning for a cycle extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include repair-attempt configuration extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include active-cycle repair queueing extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include cycle-local repair-task presence lookup extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include failed-task repair-cycle resumption extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include failed-workflow resume dispatch extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include workflow resume preparation extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include workflow start guarding extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include no-pending workflow completion extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include workflow-definition failure handling extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include workflow-blocked failure handling extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include workflow-continue task-failure handling extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include workflow fail-fast task-failure handling extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include workflow progress-plus-save handling extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include task-failure dispatch extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include per-task workflow execution extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include runnable-task iteration extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include runnable-frontier execution extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include outer workflow-loop control extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include the active-workflow shell extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include the workflow bootstrap shell extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include the final workflow-runtime façade extracted into `kycortex_agents/orchestration/workflow_control.py`
- Most recent completed slices after restart also include repair-context application extracted into `kycortex_agents/orchestration/context_building.py`
- Most recent completed slices after restart also include completed-task output application extracted into `kycortex_agents/orchestration/context_building.py`
- Most recent completed slices after restart also include completed-task artifact-context dispatch extracted into `kycortex_agents/orchestration/context_building.py`
- Most recent completed slices after restart also include task public-contract context application extracted into `kycortex_agents/orchestration/context_building.py`
- Most recent completed slices after restart also include Python module analysis extracted into `kycortex_agents/orchestration/module_ast_analysis.py`
- Most recent completed slices after restart also include code public-API summary rendering extracted into `kycortex_agents/orchestration/module_ast_analysis.py`
- Most recent completed slices after restart also include code behavior-contract rendering extracted into `kycortex_agents/orchestration/module_ast_analysis.py`
- Most recent completed slices after restart also include test-target classification helpers extracted into `kycortex_agents/orchestration/module_ast_analysis.py`
- Most recent completed slices after restart also include exact test-contract formatting extracted into `kycortex_agents/orchestration/module_ast_analysis.py`
- Most recent completed slices after restart also include test-target formatting extracted into `kycortex_agents/orchestration/module_ast_analysis.py`
- Most recent completed slices after restart also include module-run-command rendering extracted into `kycortex_agents/orchestration/module_ast_analysis.py`
- Most recent completed slices after restart also include retirement of dead test-target classification wrappers from `Orchestrator`
- Most recent completed slices after restart also include behavior-contract parsing extracted into `kycortex_agents/orchestration/module_ast_analysis.py`
- Most recent completed slices after restart also include test behavior-contract enforcement analysis extracted into `kycortex_agents/orchestration/test_ast_analysis.py`
- Most recent completed slices after restart also include test type-mismatch enforcement analysis extracted into `kycortex_agents/orchestration/test_ast_analysis.py`
- Most recent completed slices after restart also include test type-mismatch auto-fix extraction into `kycortex_agents/orchestration/test_ast_analysis.py`
- Most recent completed slices after restart also include full test-module analysis extraction into `kycortex_agents/orchestration/test_ast_analysis.py`
- Most recent completed slices after restart also include test validation-issue aggregation extraction into `kycortex_agents/orchestration/validation_analysis.py`
- Most recent completed slices after restart also include test validation error-message extraction into `kycortex_agents/orchestration/validation_analysis.py`
- Most recent completed slices after restart also include test output-content replacement extraction into `kycortex_agents/orchestration/validation_runtime.py`
- Most recent completed slices after restart also include test validation-metadata persistence extraction into `kycortex_agents/orchestration/validation_runtime.py`
- Most recent completed slices after restart also include test validation runtime-state extraction into `kycortex_agents/orchestration/validation_runtime.py`
- Most recent completed slices after restart also include final test-validation runtime façade extraction into `kycortex_agents/orchestration/validation_runtime.py`
- Most recent completed slices after restart also include code validation-issue aggregation extraction into `kycortex_agents/orchestration/validation_analysis.py`
- Most recent completed slices after restart also include code validation-metadata persistence extraction into `kycortex_agents/orchestration/validation_runtime.py`
- Most recent completed slices after restart also include final code-validation runtime façade extraction into `kycortex_agents/orchestration/validation_runtime.py`
- Most recent completed slices after restart also include dependency validation runtime extraction into `kycortex_agents/orchestration/validation_runtime.py`, leaving `_validate_task_output(...)` as a thin role-dispatch façade
- Most recent completed slices after restart also include context base-bootstrap extraction into `kycortex_agents/orchestration/context_building.py`, moving the initial `ctx` assembly and planned-module alias synchronization out of `_build_context(...)`
- Most recent completed slices after restart also include completed-task context-loop extraction into `kycortex_agents/orchestration/context_building.py`, moving the visible completed-task traversal and artifact-context dispatch out of `_build_context(...)`
- Most recent completed slices after restart also include final context runtime façade extraction into `kycortex_agents/orchestration/context_building.py`, leaving `_build_context(...)` as a thin delegating façade
- Most recent completed slices after restart also include agent-view runtime extraction into `kycortex_agents/orchestration/context_building.py`, moving `_build_agent_view(...)` and its filtering helpers out of `Orchestrator`
- Most recent completed slices after restart also include task-visibility helper extraction into `kycortex_agents/orchestration/context_building.py`, moving `_task_dependency_closure_ids(...)` and `_direct_dependency_ids(...)` out of `Orchestrator`
- Most recent completed slices after restart also include repair-validation summary dispatch extraction into `kycortex_agents/orchestration/validation_reporting.py`, moving `_build_repair_validation_summary(...)` out of `Orchestrator`
- Most recent completed slices after restart also include payload/context-output helper extraction into `kycortex_agents/orchestration/output_helpers.py`, moving `_validation_payload(...)` and `_task_context_output(...)` out of `Orchestrator`
- Most recent completed slices after restart also include code-repair instruction runtime extraction into `kycortex_agents/orchestration/repair_instructions.py`, moving `_build_code_repair_instruction_from_test_failure(...)` out of `Orchestrator`
- Most recent completed slices after restart also include repair-instruction runtime extraction into `kycortex_agents/orchestration/repair_instructions.py`, moving `_build_repair_instruction(...)` out of `Orchestrator`
- Most recent completed slices after restart also include test-repair helper-surface runtime extraction into `kycortex_agents/orchestration/repair_test_analysis.py`, moving `_test_repair_helper_surface_usages(...)` out of `Orchestrator`
- Validation status at checkpoint: `pytest tests/test_orchestration_support.py tests/test_orchestrator.py tests/test_orchestrator_coverage.py -q` (`767 passed`), `python -m ruff check .`, and `python -m mypy` all green after the latest slice
- Next intended remap after restart: continue from the next deterministic repair/output boundary now that the helper-surface lookup shell is also out of `Orchestrator`

## 2026-04-18 Refactor reset

- The current branch is no longer on a near-term publication path.
- The trusted published baseline remains `v1.0.13a6`; the current head is `1.0.13a10.dev0` in refactor-engineering mode.
- Phase 16 canary advancement is suspended on the development branch; historical canary material remains reference evidence only.
- The immediate goal is to slim the orchestrator, separate deterministic responsibilities, and rebuild the validation ladder before any new empirical claim is made.
- Completed low-risk slices: acceptance typed contracts, artifact permission hardening, and artifact persistence support extracted into `kycortex_agents/orchestration/`.
- Completed low-risk slices also include sandbox bootstrap template rendering and the AST name-replacement helper extracted into `kycortex_agents/orchestration/`.
- Completed low-risk slices also include generated-test sandbox runtime bootstrap extracted into `kycortex_agents/orchestration/sandbox_runtime.py`.
- Completed low-risk slices now also include validation-runtime helper extraction into `kycortex_agents/orchestration/validation_runtime.py`.
- Completed low-risk slices now also include task constraint parsing and architecture-context compaction extracted into `kycortex_agents/orchestration/task_constraints.py`.
- Completed low-risk slices now also include workflow-control and safe-log helpers extracted into `kycortex_agents/orchestration/workflow_control.py`.
- Completed low-risk slices now also include validation-analysis helpers extracted into `kycortex_agents/orchestration/validation_analysis.py`.
- Completed low-risk slices now also include sandbox execution helpers extracted into `kycortex_agents/orchestration/sandbox_execution.py`.
- Completed low-risk slices now also include validation reporting helpers extracted into `kycortex_agents/orchestration/validation_reporting.py`.
- Completed low-risk slices now also include repair-instruction helpers extracted into `kycortex_agents/orchestration/repair_instructions.py`.
- Completed low-risk slices now also include repair-analysis helpers extracted into `kycortex_agents/orchestration/repair_analysis.py`.
- Completed low-risk slices now also include repair-signal helpers extracted into `kycortex_agents/orchestration/repair_signals.py`.
- Completed low-risk slices now also include test-surface analysis helpers extracted into `kycortex_agents/orchestration/repair_test_analysis.py`.
- Completed low-risk slices now also include runtime-only test-repair priorities extracted into `kycortex_agents/orchestration/repair_test_runtime.py`.
- Completed low-risk slices now also include structural test-repair priorities extracted into `kycortex_agents/orchestration/repair_test_structure.py`.
- Completed low-risk slices now also include code-validation repair priorities extracted into `kycortex_agents/orchestration/repair_code_validation.py`.
- Completed low-risk slices now also include test-validation repair composition extracted into `kycortex_agents/orchestration/repair_test_validation.py`.
- Completed low-risk slices now also include repair-focus dispatch extracted into `kycortex_agents/orchestration/repair_focus.py`.
- Completed low-risk slices now also include retirement of the `_repair_focus_lines(...)` compatibility wrapper, with production and regression anchors now calling `build_repair_focus_lines(...)` directly.
- Completed low-risk slices now also include retirement of the `_build_test_validation_summary(...)` compatibility wrapper, with production and regression anchors now calling `build_test_validation_summary(...)` directly.
- Completed low-risk slices now also include retirement of the `_build_code_validation_summary(...)` compatibility wrapper, with production and regression anchors now calling `build_code_validation_summary(...)` directly.
- Completed low-risk slices now also include extraction of dependency validation summary rendering into `kycortex_agents/orchestration/validation_reporting.py`, retiring `_build_dependency_validation_summary(...)` from `Orchestrator`.
- Completed low-risk slices now also include extraction of output summarization and semantic output-key helpers into `kycortex_agents/orchestration/output_helpers.py`, retiring `_summarize_output(...)` and `_semantic_output_key(...)` from `Orchestrator`.
- Completed low-risk slices now also include extraction of agent-result normalization and unredacted-output recovery into `kycortex_agents/orchestration/output_helpers.py`, retiring `_normalize_agent_result(...)` and `_unredacted_agent_result(...)` from `Orchestrator`.
- Completed low-risk slices now also include extraction of agent-resolution validation into `kycortex_agents/orchestration/workflow_control.py`, retiring `_validate_agent_resolution(...)` from `Orchestrator`.
- Completed low-risk slices now also include extraction of workflow acceptance evaluation into `kycortex_agents/orchestration/workflow_acceptance.py`, retiring `_task_acceptance_lists(...)`, `_observed_failure_categories(...)`, and `_evaluate_workflow_acceptance(...)` from `Orchestrator`.
- Completed low-risk slices now also include extraction of AST name rendering and pytest-fixture detection into `kycortex_agents/orchestration/ast_tools.py`, retiring `_ast_name(...)` and `_is_pytest_fixture(...)` from `Orchestrator`.
- Completed low-risk slices now also include extraction of agent execution dispatch into `kycortex_agents/orchestration/agent_runtime.py`, retiring `_execute_agent(...)` from `Orchestrator`.
- Completed low-risk slices now also include extraction of agent-input assembly into `kycortex_agents/orchestration/agent_runtime.py`, with `_build_agent_input(...)` reduced to a thin compatibility wrapper.
- Completed low-risk slices now also include extraction of small AST-expression helpers into `kycortex_agents/orchestration/ast_tools.py`, retiring `_callable_name(...)`, `_attribute_chain(...)`, `_expression_root_name(...)`, `_render_expression(...)`, and `_first_call_argument(...)` from `Orchestrator`.
- Completed low-risk slices now also include extraction of test-module AST analysis helpers into `kycortex_agents/orchestration/test_ast_analysis.py`, moving local-name binding collection, parametrized-argument discovery, mock/patch support detection, unsupported mock-assertion detection, and test local-type collection out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating pytest assertion-context detection and assertion-like counting into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_with_uses_pytest_raises(...)`, `_with_uses_pytest_assertion_context(...)`, and `_count_test_assertion_like_checks(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating adjacent AST test-analysis helpers into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_ast_contains_node(...)`, `_collect_local_bindings(...)`, and `_collect_module_defined_names(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include extracting module AST signature helpers into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_annotation_accepts_sequence_input(...)`, `_call_signature_details(...)`, `_method_binding_kind(...)`, and `_self_assigned_attributes(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating adjacent dataclass and call-basename helpers into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_has_dataclass_decorator(...)`, `_call_expression_basename(...)`, `_dataclass_field_has_default(...)`, and `_dataclass_field_is_init_enabled(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating sequence-input and required-field analysis helpers into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_first_user_parameter(...)`, `_parameter_is_iterated(...)`, `_comparison_required_field(...)`, `_extract_required_fields(...)`, `_extract_indirect_required_fields(...)`, `_field_selector_name(...)`, and `_extract_lookup_field_rules(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating adjacent sequence-input rule helpers into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_direct_return_expression(...)`, `_callable_parameter_names(...)`, and `_extract_sequence_input_rule(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating static dict-example and dict-key analysis helpers into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_example_from_default(...)`, `_infer_dict_key_value_examples(...)`, and `_dict_accessed_keys_from_tree(...)` logic out of `Orchestrator` while keeping compatibility shims stable.
- Completed low-risk slices now also include co-locating `isinstance`-based type-constraint helpers into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_extract_type_constraints(...)`, `_collect_isinstance_calls(...)`, `_isinstance_subject_name(...)`, and `_isinstance_type_names(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating literal-example and batch-rule helpers into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_extract_valid_literal_examples(...)` and `_extract_batch_rule(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating class-style, return-annotation, and constructor-storage helpers into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_extract_class_definition_style(...)`, `_extract_return_type_annotation(...)`, and `_extract_constructor_storage_rule(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating score-derivation helpers into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_extract_score_derivation_rule(...)`, `_function_returns_score_value(...)`, `_render_score_expression(...)`, `_inline_score_helper_expression(...)`, and `_expand_local_name_aliases(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating literal payload-inspection and argument-type inference helpers into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_resolve_bound_value(...)`, `_call_argument_value(...)`, `_extract_literal_dict_keys(...)`, `_extract_literal_field_values(...)`, `_extract_string_literals(...)`, `_extract_literal_list_items(...)`, and `_infer_argument_type(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating typed member-usage inference helpers into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_call_argument_count(...)`, `_infer_expression_type(...)`, `_infer_call_result_type(...)`, and `_analyze_typed_test_member_usage(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating payload-selection and batch-call validation helpers into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_payload_argument_for_validation(...)` and `_validate_batch_call(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating negative-expectation and invalid-outcome helpers into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_assert_expects_false(...)`, `_call_has_negative_expectation(...)`, `_assigned_name_for_call(...)`, `_assert_expects_invalid_outcome(...)`, `_invalid_outcome_subject_matches(...)`, `_invalid_outcome_marker_matches(...)`, and `_call_expects_invalid_outcome(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating partial-batch-result helpers into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_batch_call_allows_partial_invalid_items(...)`, `_assert_limits_batch_result(...)`, `_len_call_matches_batch_result(...)`, `_int_constant_value(...)`, and `_comparison_implies_partial_batch_result(...)` logic out of `Orchestrator` while keeping private wrapper methods stable.
- Completed low-risk slices now also include co-locating the shared AST parent-map utility into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_parent_map(...)` logic out of `Orchestrator` while keeping the thin wrapper stable.
- Completed low-risk slices now also include co-locating contract-overreach score-state and visible-batch heuristics into `kycortex_agents/orchestration/test_ast_analysis.py`, moving `_test_name_suggests_validation_failure(...)`, `_is_internal_score_state_target(...)`, `_behavior_contract_explicitly_limits_score_state_to_valid_requests(...)`, `_find_contract_overreach_signals(...)`, `_visible_repeated_single_call_batch_sizes(...)`, `_loop_contains_non_batch_call(...)`, `_exact_len_assertion(...)`, and `_is_len_call(...)` logic out of `Orchestrator` while keeping thin wrappers stable.
- Completed low-risk slices now also include promoting invalid-path and missing-audit-trail helpers for shared reuse from `kycortex_agents/orchestration/repair_analysis.py`, moving `_compare_mentions_invalid_literal(...)`, `_test_function_targets_invalid_path(...)`, `_attribute_is_field_reference(...)`, `_is_len_of_field_reference(...)`, `_test_requires_non_empty_result_field(...)`, `_ast_is_empty_literal(...)`, `_class_field_uses_empty_default(...)`, and `_invalid_outcome_audit_return_details(...)` logic behind shared repair-analysis helpers while keeping thin wrappers stable.
- Completed low-risk slices now also include co-locating QA repair-suite reuse evaluation into `kycortex_agents/orchestration/repair_test_analysis.py`, moving `_qa_repair_should_reuse_failed_test_artifact(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include promoting failing pytest test-name parsing for shared reuse from `kycortex_agents/orchestration/repair_analysis.py`, moving `_failing_pytest_test_names(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include retiring the dead `_append_unique_mapping_value(...)` façade wrapper from `Orchestrator`, leaving the only live implementation internal to `kycortex_agents/orchestration/repair_test_analysis.py`.
- Completed low-risk slices now also include retiring the dead `_string_literal_sequence(...)` façade wrapper from `Orchestrator`, leaving live implementations only in support modules and `qa_tester`.
- Completed low-risk slices now also include co-locating task public-contract surface parsing into `kycortex_agents/orchestration/task_constraints.py`, moving `_parse_task_public_contract_surface(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating task public-contract anchor extraction into `kycortex_agents/orchestration/task_constraints.py`, moving `_task_public_contract_anchor(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating task public-contract preflight evaluation into `kycortex_agents/orchestration/task_constraints.py`, moving `_task_public_contract_preflight(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating Python import-root discovery into `kycortex_agents/orchestration/ast_tools.py`, moving `_python_import_roots(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating dependency-manifest normalization and validation into `kycortex_agents/orchestration/dependency_analysis.py`, moving `_normalize_package_name(...)`, `_normalize_import_name(...)`, and `_analyze_dependency_manifest(...)` logic out of `Orchestrator` while keeping thin façade wrappers stable.
- Completed low-risk slices now also include co-locating code-outline extraction into `kycortex_agents/orchestration/module_ast_analysis.py`, moving `_build_code_outline(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating validation-summary limit parsing into `kycortex_agents/orchestration/task_constraints.py`, moving `_summary_limit_exceeded(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating budget-decomposition planner detection into `kycortex_agents/orchestration/task_constraints.py`, moving `_is_budget_decomposition_planner(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating budget-decomposition instruction and task-context builders into `kycortex_agents/orchestration/task_constraints.py`, moving `_build_budget_decomposition_instruction(...)` and `_build_budget_decomposition_task_context(...)` logic out of `Orchestrator` while keeping thin façade wrappers stable.
- Completed low-risk slices now also include co-locating budget-decomposition gate evaluation into `kycortex_agents/orchestration/task_constraints.py`, moving `_repair_requires_budget_decomposition(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed remediation now also includes clearing the real workspace Pylance errors by making `AcceptanceLane` require `accepted` and `reason`, and by adding explicit AST/optional-value narrowing in affected tests.
- Completed low-risk slices now also include co-locating repair-owner routing into `kycortex_agents/orchestration/repair_instructions.py`, moving `_repair_owner_for_category(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating failure-category artifact-type mapping into `kycortex_agents/orchestration/repair_analysis.py`, moving the category-to-`ArtifactType` decision out of `_failed_artifact_content_for_category(...)` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating budget-decomposition task creation/reuse into `kycortex_agents/orchestration/workflow_control.py`, moving `_ensure_budget_decomposition_task(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating active repair-cycle lookup into `kycortex_agents/orchestration/workflow_control.py`, moving `_active_repair_cycle(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating failed-artifact content lookup into `kycortex_agents/orchestration/artifacts.py`, moving `_failed_artifact_content(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating failed-artifact lookup by failure category into `kycortex_agents/orchestration/repair_analysis.py`, moving `_failed_artifact_content_for_category(...)` composition out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating test-repair helper-surface usage parsing into `kycortex_agents/orchestration/repair_test_analysis.py`, moving `_test_repair_helper_surface_usages(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating prior repair-context merging into `kycortex_agents/orchestration/workflow_control.py`, moving `_merge_prior_repair_context(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed low-risk slices now also include co-locating repair-context assembly into `kycortex_agents/orchestration/workflow_control.py`, moving `_build_repair_context(...)` logic out of `Orchestrator` while keeping the thin façade wrapper stable.
- Completed CI remediation now also includes excluding generated build artifacts from `mypy` and fixing the remaining stale `callable_name` references exposed only by the full CI typecheck path after the AST-expression slice.
- Completed CI remediation now also includes restoring the coverage gate to a truthful green state by fixing the remaining stale `callable_name` formatting paths in behavior-analysis branches and adding direct helper-coverage tests until the full gate re-cleared at `1620 passed` and `90.02%`.
- Current deterministic next slice: remap the next live façade-wrapper adjacent to the latest artifact and workflow-control extractions, with `_failed_artifact_content_for_category(...)` retirement or nearby repair-context assembly helpers now the smallest fresh candidates.
- The remaining sections in this file are preserved as historical analysis and root-cause context unless explicitly superseded by this reset.

## Current newer-head requalification checkpoint on 2026-04-17

### Campaign progression from v29 to v41

- v29: 9/15 GREEN on 5×3 (Ollama 5/5, OpenAI 3/5, Anthropic 1/5+3 DEGRADED+1 RED)
- v30: 11/15 GREEN on 5×3 — fixture contract block fixed OpenAI to 5/5; Anthropic still 1/5+4 DEGRADED
- v31/v31b: expanded contract bullets partially improved Anthropic; validator tuple-return bug fixed; infinite resume loop fixed
- v35b: qwen2.5-coder:14b CPU = 5/5 GREEN (gold standard confirmed after infinite-loop fix)
- v36: qwen3.5:9b GPU = 1/5 GREEN
- v37c: qwen3.5:9b GPU = 3/5 GREEN (inconsistent)
- v38: qwen2.5-coder:14b GPU partial offload = 2/5 GREEN (offload degrades quality)
- v39: qwen2.5-coder:14b CPU Ollama 0.20.7 = 5/5 GREEN (confirmed across Ollama versions)
- v40: qwen3-coder:30b MoE CPU = 0/3 GREEN (too weak)
- v41: gpt-4.1-mini = 1/5 GREEN (only insurance passed — model sensitivity confirmed)

### Current engineering focus: model-agnostic test generation

The framework has been confirmed as model-sensitive: changing from gpt-4o-mini to gpt-4.1-mini drops 5/5 → 1/5. Root cause: the behavior contract extracted from generated code is blind to type constraints. Tests pass field names correctly but use wrong types (e.g., `details='details'` string instead of dict).

Remediation plan (approved for structural changes):

- Phase 1 (orchestrator.py): Add `_extract_type_constraints()` and `_extract_valid_literal_examples()` methods; integrate into `_build_code_behavior_contract()`; add type-mismatch detection to `_test_validation_has_static_issues()`
- Phase 2 (qa_tester.py): Add type-constraint instruction block to SYSTEM_PROMPT; add fixture example hints; audit conflicting NEVER/MUST rules
- Phase 3 (orchestrator.py): Add type-mismatch category to `_build_test_validation_summary()` and repair instruction to `_build_test_repair_instruction()`
- Phase 4: Validation with 3 models × 5 scenarios (gpt-4o-mini regression, gpt-4.1-mini fix verification, qwen2.5-coder:14b cross-model)

### Infrastructure additions (uncommitted)

- `ollama_think` parameter support across config, provider_matrix, ollama_provider, and matrix runner
- multi-port Ollama setup documented: 11434 (old v0.20.5), 11435 (v0.20.7 GPU), 11436 (v0.20.7 CPU-only)

### Commits since v29 (on origin/main)

- `2c27316` Harden QA tester prompt: add test fixture contract to prevent string-valued details
- `46ba257` Record v1.0.13a6 canary day-3 daily review with 103 accepted workflows
- `d338c93` Fix validator tuple/dict-return gap for validate_request
- `3a3c754` Fix infinite resume loop when only repair-origin tasks are failed
- `235d58b` Expand contract bullets to close v31b DEGRADED cells
- `197f4b8` Fix unused WorkflowStatus import (ruff F401)
- `1fbeafa` Reject non-dict details in contract anchor and scenario bullets
- `829adc4` Fix infinite loop: add PROVIDER_TRANSIENT to orchestrator repairable set

### Provider baseline (current validated)

- OpenAI gpt-4o-mini: 5/5 GREEN (v28, v30)
- Ollama qwen2.5-coder:14b CPU: 5/5 GREEN (v28, v35b, v39)
- Anthropic claude-haiku: 1/5 GREEN + 4 DEGRADED (v30) — partial; validator bugs fixed but code generation issues remain
- OpenAI gpt-4.1-mini: 1/5 GREEN (v41) — model sensitivity confirmed
- Ollama qwen3-coder:30b: 0/3 GREEN (v40) — too weak

### Immediate next steps

1. commit `ollama_think` infrastructure and documentation updates
2. begin Phase 1 implementation of the type-aware behavior contract in orchestrator.py
3. continue with Phase 2 (qa_tester.py prompt adjustment) and Phase 3 (repair diagnostics)
4. validate with 3×5 matrix (15 runs) after all phases complete
5. canary daily reviews continue independently on published v1.0.13a6

Reconstruction date: 2026-04-12

Current summary:

- Public package line: alpha
- Local version: 1.0.13a6
- Latest published release: 1.0.13a6
- Current phase: 16 of 17
- Goal of this plan: reconstruct the path to Beta 1 from repository evidence, public docs, and Git history

## Reconstruction method

This plan was reconstructed from:

- `CHANGELOG.md`
- `docs/go-live-policy.md`
- `RELEASE.md`
- `RELEASE_STATUS.md`
- `git log` history
- source code in `kycortex_agents/`
- empirical validation scripts in `scripts/`

Reading rule:

- Phases 1, 8, 9, 10, 13, 14, 16, and 17 have direct evidence in the repository.
- Phases 2 through 7, 11, 12, and 15 were reconstructed from a coherent grouping of commits, docs, and release milestones.

## The 17 phases

### Phase 1 - Runtime typing foundation

Status: completed

Scope:

- base domain typing
- initial public contracts
- package structure

Primary evidence:

- `da0cce0 Add project baseline and typed domain model`
- `da5f8d0 Complete phase 1 runtime typing`

### Phase 2 - Provider abstraction and runtime config

Status: completed

Scope:

- provider layer
- validated runtime configuration
- cloud and local support

Primary evidence:

- `ea73c55 Add provider abstraction layer`
- `fb04053 Validate runtime configuration`
- `f8c642f Add Anthropic provider support`
- `cfbe61d Add Ollama local provider`

### Phase 3 - Typed agent runtime

Status: completed

Scope:

- runtime-aware `BaseAgent`
- typed inputs for agents
- typed and normalized outputs
- agent registry

Primary evidence:

- `a294efc Add agent registry abstraction`
- `0a4548e Add runtime-aware agent execution`
- `d2b35f2 Migrate agents to typed runtime inputs`
- `006907d Standardize agent runtime outputs`

### Phase 4 - Dependency-aware workflow scheduling

Status: completed

Scope:

- dependency graph
- topological ordering
- failure and retry policies

Primary evidence:

- `00fba4f Add dependency-aware workflow scheduling`
- `09227a4 Add workflow retries and failure policies`
- `5a3a661 Validate workflow graphs and failure policies`

### Phase 5 - Persistence and resumability

Status: completed

Scope:

- abstract state store
- JSON backend
- SQLite backend
- resume for interrupted and failed workflows

Primary evidence:

- `630363d Harden project state persistence`
- `f3d5d39 Add state store abstraction`
- `f030153 Add resumable workflow execution`
- `508e0de Support failed workflow resume`

### Phase 6 - Audit trail and structured state

Status: completed

Scope:

- structured artifacts
- persisted outputs
- execution metadata
- events and durations
- provider usage metadata

Primary evidence:

- `57d1101 Persist rich artifact records`
- `4159f8f Persist structured task outputs`
- `19be0a2 Persist execution metadata`
- `94ca2ae Persist workflow metadata`
- `d5a7ed4 Persist execution events`
- `ebc5e9e Capture provider usage metadata`

### Phase 7 - Corrective workflow controls

Status: completed

Scope:

- acceptance policies
- repair budgets
- repair routing by failure category
- corrective task lineage

Primary evidence:

- `7b53928 Add explicit workflow acceptance policy`
- `a1156f1 Add bounded workflow repair budgets`
- `5e77d3a Route repair attempts by failure category`
- `0144ee1 Add corrective task lineage`

### Phase 8 - Sandbox isolation

Status: completed

Scope:

- file and path confinement
- symlink escape blocking
- resource limits
- environment cleanup
- strong host isolation

Primary evidence:

- `17e690c hardening: complete phase 8 sandbox isolation`

### Phase 9 - Configuration and public docs baseline

Status: completed

Scope:

- configuration documentation
- stable public surface
- provider, workflow, persistence, and extension docs

Primary evidence:

- `57e32c7 Complete Phase 9 configuration docs`

### Phase 10 - Examples, tooling, and CI baseline

Status: completed

Scope:

- public examples
- local tooling
- pre-commit
- CI workflow
- repository documentation consolidation

Primary evidence:

- `bf52286 Complete Phase 10 docs`
- commits from 2026-03-23 through 2026-03-24 for examples, Makefile, pre-commit, CI, and release docs

### Phase 11 - Provider matrix and empirical validation

Status: completed

Scope:

- provider validation matrix
- OpenAI, Anthropic, and Ollama baseline
- structured run summaries
- real smoke examples

Primary evidence:

- `16f1712 feat: add provider matrix validation`
- `scripts/run_real_world_complex_matrix.py`
- releases 1.0.8 through 1.0.13a1 in `CHANGELOG.md`

### Phase 12 - Privacy and public-surface minimization

Status: completed

Scope:

- secret redaction
- public metadata minimization
- strict separation between public and internal views

Primary evidence:

- commit stream between 2026-04-02 and 2026-04-07 focused on `Redact`, `Limit`, `Minimize`, `Remove`, and `Bound`

### Phase 13 - Release-readiness baseline

Status: completed

Scope:

- publishable 1.0.0 package
- release workflow
- distribution metadata
- release and migration docs

Primary evidence:

- `CHANGELOG.md` for 1.0.0: `Phase 13 release-readiness work is complete`
- `127025e Finalize 1.0.0 release baseline`

### Phase 14 - Four-view runtime boundary

Status: completed

Scope:

- explicit separation between persisted state, `ProjectSnapshot`, `AgentView`, and `InternalRuntimeTelemetry`
- exact telemetry removed from the public surface
- formal go-live policy

Primary evidence:

- `4f476a4 Split public snapshot from internal runtime telemetry`
- the `Unreleased` section of `CHANGELOG.md`
- `docs/go-live-policy.md`

### Phase 15 - Real-world campaign

Status: closed on `cd82118` after GitHub Actions run `#450` finished green (`8/8`)

Scope:

- 5 real scenarios
- 3 providers
- 15 total runs
- goal: close the pre-Beta 1 baseline with strong empirical evidence

Current known state:

- the original Linux-baseline run captured the pre-fix failure profile and is now historical evidence rather than the current decision anchor
- the fresh clean rerun `full_matrix_validation_2026_04_12_v6` remains the pre-hardening degraded baseline: 15 bounded completions, 11 clean outcomes, and 4 degraded outcomes
- prompt hardening plus targeted reruns cleared the 4 degraded scenario/provider pairs on the same candidate line
- the fresh canonical rerun `full_matrix_validation_2026_04_12_v7` then closed with 15 of 15 runs at `status=completed` and 15 of 15 at `terminal_outcome=completed`
- GitHub Actions run `#450` on commit `cd82118` finished green with 8 of 8 jobs successful, so the full Phase 15 exit gate is now satisfied
- Beta 1 is being treated internally as a production claim for a defensible open-source product, not as a packaging milestone or a minimal beta label
- the current focus is no longer Phase 15 repair; it is Phase 16 canary-readiness material

Primary evidence:

- `scripts/run_real_world_complex_matrix.py`
- `/home/tupira/Dados/experiments/kycortex_agents/full_matrix_validation_2026_04_12_v6/campaign_summary.json`
- `/home/tupira/Dados/experiments/kycortex_agents/real_world_complex_usage_2026_04_12_linux_baseline/campaign_summary.json`
- local continuity docs in `.local-docs/`

Phase 15 exit gate:

- the candidate commit must keep `ruff`, `mypy`, focused regressions, release checks, and CI green
- the four currently degraded cells must first be rerun on the same scenario and provider pairs and finish with `status=completed` and `terminal_outcome=completed`
- after the targeted reruns are clean, a fresh canonical 5x3 rerun must finish 15 of 15 with `status=completed` and 15 of 15 with `terminal_outcome=completed`
- zero degraded or false-success outcomes are allowed in the candidate evidence set; a single degraded cell keeps Phase 15 open because the go-live policy defines success by accepted end-to-end criteria rather than by partial artifacts
- no provider-specific carve-out is allowed for the canonical providers; OpenAI, Anthropic, and Ollama must each clear 5 of 5 clean outcomes on the canonical scenarios
- for this local plan, defensible superiority means repository-owned evidence that materially exceeds the current alpha line by replacing the current 11 clean / 4 degraded split with a clean 15 / 15 canonical matrix

Current prioritized Phase 16 backlog:

1. continue daily reviews while the active canary remains open and preserve each follow-up repository-owned evidence packet now that the 100-workflow checkpoint is satisfied
2. continue the active canary until the remaining 7-day observation window is complete
3. keep the rollback target pinned to `v1.0.13a2` and close the active canary with incident, rollback, and completion review material under `docs/canary-evidence/f99a38d/`

Immediate engineering priority opened on 2026-04-13:

1. treat the clean canonical `v7` rerun on `cd82118` as historical proof for the accepted Phase 15 line only, not as portable proof for newer heads
2. use the contradictory partial `5 x 2` rerun at `/home/tupira/Dados/experiments/kycortex_agents/full_matrix_validation_2026_04_13_v8_openai_ollama` as the active engineering truth for the current head until clean reruns are re-established
3. enforce a composite acceptance model that requires productivity, real-workflow correctness, and safety together instead of allowing bounded completion alone to stand in for success
4. propagate that model first in the real-world runner, then into the orchestrator acceptance and failure-classification seams
5. repair the failing current-head cells, rerun the failing `5 x 2` pairs, then rerun the full `5 x 2` and canonical `5 x 3` before reusing any `15 of 15` claim on the newer head

Latest execution status through 2026-04-13:

- prompt hardening landed in `kycortex_agents/agents/qa_tester.py` and `kycortex_agents/provider_matrix.py` to reduce threshold-label drift, invalid validator/workflow expectation drift, and incompatible optional-config stubs
- focused prompt regressions passed in `tests/test_concrete_agents.py` and `tests/test_provider_matrix.py`
- all 4 previously degraded scenario/provider pairs now have targeted reruns with `status=completed` and `terminal_outcome=completed`
- targeted rerun details:
	- `kyc_compliance_intake/openai`: clean completion without repair
	- `vendor_onboarding_risk/anthropic`: clean completion without repair
	- `returns_abuse_screening/ollama`: clean completion after 1 repair cycle
	- `returns_abuse_screening/anthropic`: clean completion after 1 repair cycle
- the fresh canonical full rerun at `/home/tupira/Dados/experiments/kycortex_agents/full_matrix_validation_2026_04_12_v7` finished with 15 of 15 runs at `status=completed`
- the same `v7` rerun finished with 15 of 15 runs at `terminal_outcome=completed`
- clean-output provider totals on `v7`: OpenAI 5 of 5, Anthropic 5 of 5, Ollama 5 of 5
- the empirical portion of the Phase 15 exit gate is now satisfied on the current candidate line
- the remaining local validation stack also passed on the same candidate line: `ruff`, `mypy`, focused prompt regressions, `scripts/release_metadata_check.py`, and `scripts/release_check.py`
- local acceptance decision: the current candidate line is strong enough to promote to CI because the empirical gate and the local validation stack are both green
- the accepted candidate line was committed as `cd82118` (`Harden Phase 15 validation flow`) and pushed to `origin/main`, which triggered GitHub Actions run `#450`
- GitHub Actions run `#450` then finished with `status=completed`, `conclusion=success`, and 8 of 8 jobs green: `Lint and Typecheck (3.12)`, `Lint and Typecheck (3.10)`, `Focused Regressions (3.10)`, `Focused Regressions (3.12)`, `Package Validation`, `Coverage Gate`, `Full Test Suite (3.12)`, and `Full Test Suite (3.10)`
- the repository-controlled Phase 16 guide then expanded in three clean CI-backed steps: `c56abe7` added `docs/canary-operations.md`, `be748fa` refined the evidence path, and the GPG-signed `355b9fb` bound the current operator roles and evidence root
- commit `355b9fb` is now GitHub-verified and GitHub Actions run `#453` finished green with the same full 8-job matrix as `#450`
- the first candidate-shaped Phase 16 bundle now exists at `docs/canary-evidence/355b9fb/`, explicitly marked as a pre-canary bootstrap rather than a completed canary record
- the bundle bootstrap first landed on GPG-signed commit `ef0b4fd`, but that commit carried an accidental patch-text echo in `docs/canary-evidence/README.md`; the clean final repository state was restored immediately on GPG-signed commit `fac7530`
- GitHub Actions run `#454` for `ef0b4fd` was automatically cancelled as superseded, and GitHub Actions run `#455` for `fac7530` finished green with the full CI workflow closed clean again
- commit `2563383` (`Prepare 1.0.13a3 alpha`) then closed GitHub Actions run `#456` green, was promoted through signed tag `v1.0.13a3`, and Release workflow `#18` published the six-asset GitHub pre-release successfully
- `main` is now reopened on GPG-signed commit `83ec228` with package version `1.0.13a4` so future maintenance work does not reuse a published version identifier
- the historical abort bundle remains tracked at `docs/canary-evidence/2563383/` for the disqualified `v1.0.13a3` canary base
- the `release-user-smoke` false-success path has now been fixed locally on the `1.0.13a4` line so deterministic artifact-validation failures rewrite persisted workflow state to `failed` with `failure_category=code_validation`
- local remediation validation is now green on that fix line: `tests/test_provider_matrix.py` passed 54 of 54 tests and `python scripts/release_check.py` completed successfully with the full 1211-test suite and coverage gate green
- commit `e23c1f7` then pushed the remediation to `origin/main`, and the corresponding GitHub Actions CI workflow completed successfully
- the rollback baseline `v1.0.13a2` has now been re-smoke-validated on the live host via controlled Ollama `release-user-smoke`, finishing `completed` with `repair_cycle_count=0` and artifact validation passing at sample balance `2650.00`
- commit `8bfdc29` (`Record rollback baseline smoke evidence`) then closed GitHub Actions run `#460` green, was promoted through signed tag `v1.0.13a4`, and Release workflow `#19` published the six-asset GitHub pre-release successfully
- the most recent candidate-shaped Phase 16 bundle is now tracked at `docs/canary-evidence/8bfdc29/` for the published `v1.0.13a4` canary base
- the restarted live canary preflight on host `alex-kycortex` confirmed OpenAI, Anthropic, and Ollama healthy before traffic at `2026-04-13T00:56:52.840533Z`, and refreshed expansion health stayed healthy at `2026-04-13T01:28:52.992574Z`
- the first 3 controlled `release-user-smoke` workflows in the restarted window were externally validated and accepted across OpenAI, Anthropic, and Ollama by `2026-04-13T01:33:54.386905+00:00`
- `run_04_openai` then failed external validation because the generated artifact imported missing dependency `click`; Phase 16 is now an aborted `v1.0.13a4` canary with rollback still pinned to `v1.0.13a2` and a fresh candidate required before restart
- the smoke runner now rejects unsupported non-standard-library imports deterministically and reinforces the standard-library-only contract across architecture, implementation, and review tasks
- `main` is now reopened on `1.0.13a6` so the next maintenance candidate can carry the `release_user_smoke_ollama` remediation without reusing the published `1.0.13a5` version identifier
- commit `c74e957` (`Prepare v1.0.13a5 release candidate`) then pushed the reopened line to `origin/main`, signed tag `v1.0.13a5` published the next alpha candidate, and Release workflow `#20` completed successfully with staged artifact validation, manifest verification, promotion-summary generation, and published-asset verification green
- the most recent candidate-shaped Phase 16 bundle is now tracked at `docs/canary-evidence/c74e957/` for the published `v1.0.13a5` canary base, but that bundle is now an abort record rather than an active window
- the fresh live canary preflight on host `alex-kycortex` confirmed OpenAI, Anthropic, and Ollama healthy before traffic at `2026-04-13T02:34:45.948542+00:00`, and refreshed expansion health stayed healthy at `2026-04-13T02:47:53.463682+00:00`
- the first 2 controlled workflows `release_user_smoke_openai` and `release_user_smoke_anthropic` were externally validated and accepted, but `release_user_smoke_ollama` then triggered a `code_validation` abort at `2026-04-13T02:49:28.144777+00:00` because the generated artifact did not expose `main()`
- the repaired line now injects a task-level public contract anchor into the `release-user-smoke` tasks and normalizes annotated anchor surfaces semantically during task public contract preflight, which removed the false-negative mismatch seen during the first local Ollama rerun after the abort
- the focused `release-user-smoke` regressions and the focused orchestrator anchor regression re-cleared on the repaired line, and a live local Ollama rerun of `examples/example_release_user_smoke.py` then completed successfully with artifact validation passing
- the full local release gate for `1.0.13a6` then re-cleared: `python scripts/release_check.py` completed successfully with package validation green, release metadata green, coverage at `90.21%`, and `1216` passing tests
- signed commit `f99a38d` (`Prepare v1.0.13a6 release candidate`) then pushed the release-ready line to `origin/main`, signed tag `v1.0.13a6` published the next alpha candidate, and Release workflow `#21` completed successfully with release validation, distribution build, and GitHub release publication all green
- GitHub release `v1.0.13a6` published the wheel, sdist, `release-artifact-manifest.json`, and `release-promotion-summary.json`, and the public release object confirms the expected asset digests
- the fresh live canary preflight on host `alex-kycortex` confirmed OpenAI, Anthropic, and Ollama healthy at `2026-04-13T03:25:21Z`
- the first controlled workflow `release_user_smoke_openai` in the restarted window was externally validated and accepted at `2026-04-13T03:26:22.839835+00:00` with sample balance `2650.00`
- refreshed expansion provider health then kept OpenAI, Anthropic, and Ollama healthy at `2026-04-13T03:51:37.043973+00:00`
- the clean checkpoint through run 10 completed at `2026-04-13T03:55:23.377066+00:00` with 10 eligible workflows seen, 10 accepted workflows, 0 incidents, 0 rollback actions, and provider breakdown OpenAI 4, Anthropic 3, Ollama 3
- a second expansion provider-health refresh then kept OpenAI, Anthropic, and Ollama healthy at `2026-04-13T04:03:29.889609+00:00`
- the clean checkpoint through run 25 completed at `2026-04-13T04:08:17.863018+00:00` with 25 eligible workflows seen, 25 accepted workflows, 0 incidents, 0 rollback actions, and provider breakdown OpenAI 9, Anthropic 8, Ollama 8
- a third expansion provider-health refresh then kept OpenAI, Anthropic, and Ollama healthy at `2026-04-13T04:15:41.775710+00:00`
- the clean checkpoint through run 50 completed at `2026-04-13T04:22:59.352947+00:00` with 50 eligible workflows seen, 50 accepted workflows, 0 incidents, 0 rollback actions, and provider breakdown OpenAI 17, Anthropic 17, Ollama 16
- the first same-day daily review was recorded at `2026-04-13T04:30:01.447970+00:00` and kept the active window open without rollback
- refreshed expansion provider health then kept OpenAI, Anthropic, and Ollama healthy again at `2026-04-13T09:22:33.389958+00:00` and `2026-04-13T09:41:39.329840+00:00`
- the clean checkpoint through run 100 completed at `2026-04-13T10:39:05.274887+00:00` with 100 eligible workflows seen, 100 accepted workflows, 0 incidents, 0 rollback actions, and provider breakdown OpenAI 34, Anthropic 33, Ollama 33
- the active published canary bundle is now tracked at `docs/canary-evidence/f99a38d/`, while `docs/canary-evidence/c74e957/` remains the prior published abort record for `v1.0.13a5`
- a fresh practical rerun without Anthropic was then started at `/home/tupira/Dados/experiments/kycortex_agents/full_matrix_validation_2026_04_13_v8_openai_ollama` to verify whether the newer head still behaved like the retained clean `v7` baseline
- `kyc_compliance_intake/openai` only completed after `repair_cycle_count=1`, which is usable evidence of bounded recovery but not of the same practical cleanliness as the retained `v7` line
- `kyc_compliance_intake/ollama` failed in `code` with a `ProviderTransientError` timeout at the `180 s` execution limit
- `insurance_claim_triage/openai` failed in `tests`, then failed again in `tests__repair_1` with `pytest: 1 failed, 2 passed`
- `insurance_claim_triage/ollama` failed in `code` with the same `180 s` timeout profile
- `vendor_onboarding_risk/openai` only started when the campaign was intentionally stopped because the accumulated contradiction was already sufficient
- local reading: the newer head no longer inherits the practical clean `15 of 15` interpretation of the retained `v7` rerun
- the strategic response is now a composite acceptance model with three simultaneous lanes: productivity, real-workflow correctness, and safety
- the first implementation slice of that response is already landed in the empirical runner: `FailureCategory.SCENARIO_VALIDATION`, deterministic post-workflow scenario validation, and automatic downgrade to `validation_error` / `degraded` when a generated workflow violates the retained scenario contract
- focused regression coverage for that slice now exists in `tests/test_real_world_complex_matrix.py` and last re-cleared with `3 passed`
- the next implementation slice is now landed in `kycortex_agents/orchestrator.py`: workflow acceptance now evaluates productivity, real-workflow, and safety lanes together, `required_tasks` no longer masks failed workflow tasks, and zero-budget sandbox incidents explicitly fail the safety lane
- focused validation for the orchestrator slice re-cleared with `4 passed` in the targeted orchestrator subset alongside the existing `3 passed` runner regression file
- the newer-head contradiction set from the partial OpenAI plus Ollama `5 x 2` rerun has now been requalified in isolated reruns across all four previously contradicted cells:
	- `insurance_claim_triage/openai`: `completed`
	- `kyc_compliance_intake/openai`: `completed`
	- `kyc_compliance_intake/ollama`: `completed` after timeout, repair-guidance, and contract hardening
	- `insurance_claim_triage/ollama`: `completed` on the same hardened line
- the real-world task contract now explicitly requires the public facade to remain instantiable with zero required constructor arguments, and focused regression coverage for that rule passed in `tests/test_real_world_complex_matrix.py`
- the next empirical obligation on the newer head is no longer another isolated contradiction rerun; it is a fresh integrated OpenAI plus Ollama `5 x 2` campaign, followed by the canonical `5 x 3` rerun if the integrated `5 x 2` clears

### Phase 16 - Canary readiness

Status: published `v1.0.13a6` active; canary window open on `f99a38d`

Scope:

- operator runbooks
- rollback steps
- support escalation rules
- incident templates
- minimum SLO window for canary

Primary evidence:

- the `Canary Gate` section in `docs/go-live-policy.md`
- repository-controlled canary operations guide drafted at `docs/canary-operations.md`
- the exact canary evidence collection path is now documented in `docs/canary-operations.md` through the repository-owned evidence-source map, packet layout, and collection cadence
- the current Phase 16 operating model and tracked evidence-bundle root are now documented in `docs/canary-operations.md` and `docs/canary-evidence/README.md`
- the active candidate bundle is now tracked at `docs/canary-evidence/f99a38d/`, and it currently records a live open canary window with healthy preflight, repeated healthy expansion refreshes, a clean checkpoint through run 100, and the first same-day daily review
- the historical abort evidence for `v1.0.13a3` remains tracked in `docs/canary-evidence/2563383/`, including the provider-health preflight and the aggregated checkpoint through `run_06_ollama`
- the published `v1.0.13a4` abort record remains tracked in `docs/canary-evidence/8bfdc29/`
- the published `v1.0.13a5` abort record remains tracked in `docs/canary-evidence/c74e957/`
- the restarted `v1.0.13a6` live preflight, repeated expansion health refreshes, clean checkpoints through run 10, run 25, run 50, and run 100, plus the first same-day daily review are now tracked in `docs/canary-evidence/f99a38d/`

### Phase 17 - Production qualification / Beta 1

Status: pending

Scope:

- production qualification sign-off
- formalized operational support
- rollback drill results
- documented release ownership path

Primary evidence:

- the `General-Availability Gate` section in `docs/go-live-policy.md`

## Operational reading of the current moment

Practical conclusion:

- Phases 1 through 15 are closed.
- Phase 15 closed on commit `cd82118` because the targeted reruns, the clean canonical `v7` rerun, the local validation stack, and GitHub Actions run `#450` all stayed green on the same candidate line.
- The active next phase is now Phase 16, which is operational canary-readiness work rather than core framework repair.
- The first repository-controlled Phase 16 artifact now exists: `docs/canary-operations.md` covers the operator runbook, rollback triggers and steps, support escalation rules, incident templates, and the minimum canary evidence window.
- The next repository-controlled refinement is also in place: the same guide now defines the exact evidence path for canary reviews using `snapshot()`, `internal_runtime_telemetry()`, validation artifacts, and structured summary files.
- The current single-maintainer role binding and the tracked evidence-bundle root are now explicit, and the first candidate bundle for `355b9fb` has been opened in a truthful pre-canary state.
- The published `v1.0.13a5` line on `c74e957` remains an aborted canary candidate, and the tracked evidence packet under `docs/canary-evidence/c74e957/` records the Ollama `main()` omission incident.
- The current active canary candidate is the published `v1.0.13a6` line on `f99a38d`, and the tracked evidence packet under `docs/canary-evidence/f99a38d/` now records the healthy preflight, repeated healthy expansion refreshes, clean checkpoints through run 10, run 25, run 50, and run 100, and the first same-day daily review.
- The next Phase 16 gap is now no longer reaching the `100`-workflow threshold; it is carrying the still-open `v1.0.13a6` window through daily reviews until the remaining 7-day minimum is satisfied.
- The last clean canonical `5 x 3` proof remains the retained `v7` rerun on `cd82118`, and it is still valid evidence for that accepted line.
- The newer partial `5 x 2` rerun at `/home/tupira/Dados/experiments/kycortex_agents/full_matrix_validation_2026_04_13_v8_openai_ollama` is contradictory evidence for the newer head, so the retained `v7` cleanliness must not be reused as if it already covered later changes.
- The immediate engineering problem is now dual-track: keep the published canary truthful on `f99a38d` while tightening the acceptance model and re-qualifying the newer head empirically.
- The tighter model now spans both the empirical runner and the orchestrator acceptance path, which means later reruns will no longer treat `required_tasks` productivity as enough when the real workflow or safety lanes fail.
- The next engineering step is no longer repair of isolated contradiction cells; it is a fresh integrated OpenAI plus Ollama `5 x 2` rerun on the newer head so the isolated requalification can be turned back into campaign-level evidence.
- Phase 17 remains the qualification and ownership phase after the Phase 16 canary material is complete.

## Definition of done for Beta 1

For this local plan, Beta 1 means:

- Phase 15 resolved with a clear acceptance decision backed by empirical evidence, targeted clean reruns for each currently degraded cell, and a fresh canonical 5x3 matrix result with 15 of 15 clean outcomes and no provider carve-outs
- Phase 15 evidence strong enough to support a materially stronger product claim than the current alpha baseline, because the current 11 clean / 4 degraded split has been converted into a clean 15 / 15 and the repeated degraded root-cause classes have been removed from the candidate evidence
- any newer head used for the same claim re-establishes that bar on its own evidence, with simultaneous productivity, real-workflow correctness, and safety rather than historical inheritance from an older clean rerun
- the same candidate commit still passes release checks, CI, and focused regressions when the empirical evidence is collected
- Phase 16 documented and reviewed
- Phase 17 signed off and supported by the gates in `docs/go-live-policy.md`
