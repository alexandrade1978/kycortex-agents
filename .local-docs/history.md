# Local Project History

Reconstruction date: 2026-04-13

This file summarizes the evolution of the project in operational language, based on `git log`, `CHANGELOG.md`, and repository docs.

## Top-of-branch state

- Observed HEAD: `bc2f8c6 Record v1.0.13a6 canary checkpoint through run 100` (pre-commit; accumulated changes include composite acceptance model, prompt hardenings, typed contract freezes, and matrix runner improvements)
- HEAD date: 2026-04-13
- Immediate context: the newer-head engineering requalification has achieved 10/10 GREEN on the OpenAI plus Ollama `5 x 2` matrix at v28, resolving the contradictory partial rerun from v8; uncommitted changes totalling 2349+ insertions across 8 modified files plus 1 new test file are ready for commit

## Local operational milestone on 2026-04-20 - Test validation runtime-state slice recorded

- the next deterministic refactor slice co-located the broader generated-test validation runtime-state preparation flow into `kycortex_agents/orchestration/validation_runtime.py`
- the extracted support now owns suite finalization, optional type-mismatch auto-fix, repeated test-content replacement, line and budget annotation, generated pytest execution, completion diagnostics, and pytest failure-origin derivation for `_validate_test_output(...)`
- `Orchestrator` now delegates that broader finalize/analyze/execute preparation flow through `build_test_validation_runtime_state(...)` while focused regressions re-cleared locally at `747 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Dependency validation runtime slice recorded

- the next deterministic refactor slice co-located the remaining `dependency_manager` validation branch from `_validate_task_output(...)` into `kycortex_agents/orchestration/validation_runtime.py`
- the extracted support now owns dependency-manifest analysis dispatch, validation metadata persistence, deterministic failure-summary assembly, and final error raising for generated dependency manifests
- `_validate_task_output(...)` now delegates the dependency validation path through `validate_dependency_output_runtime(...)` and is reduced to a thin role-dispatch façade, while focused regressions re-cleared locally at `753 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Context base-bootstrap slice recorded

- the next deterministic refactor slice co-located the initial base-context assembly from `_build_context(...)` into `kycortex_agents/orchestration/context_building.py`
- the extracted support now owns root context creation, provider token budget exposure, task metadata packaging, agent-view snapshot carry-forward, completed-task container setup, and planned-module alias synchronization through `build_task_context_base(...)`
- `_build_context(...)` now delegates that bootstrap through shared context-building support while focused regressions re-cleared locally at `754 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Context completed-task loop slice recorded

- the next deterministic refactor slice co-located the visible completed-task traversal from `_build_context(...)` into `kycortex_agents/orchestration/context_building.py`
- the extracted support now owns visible completed-task filtering, output recovery, semantic alias application, budget-brief propagation, and role-based artifact-context dispatch through `apply_completed_tasks_to_context(...)`
- `_build_context(...)` now delegates that loop through shared context-building support while focused regressions re-cleared locally at `755 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Context runtime façade slice recorded

- the next deterministic refactor slice co-located the remaining `_build_context(...)` orchestration shell into `kycortex_agents/orchestration/context_building.py`
- the extracted support now owns snapshot and agent-view bootstrap, visible-task closure resolution, repair-context budget planning lookup, task public-contract anchor dispatch, completed-task loop dispatch, repair-context application, and final redaction through `build_task_context_runtime(...)`
- `_build_context(...)` now delegates the full context-building path through `build_task_context_runtime(...)`, while focused regressions re-cleared locally at `756 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Agent-view runtime slice recorded

- the next deterministic refactor slice co-located `_build_agent_view(...)` and its adjacent task-result, decision, and artifact filters into `kycortex_agents/orchestration/context_building.py`
- the extracted support now owns acceptance-evaluation normalization plus filtered `AgentView` assembly through `build_agent_view_runtime(...)`, `build_agent_view_task_results(...)`, `build_agent_view_decisions(...)`, and `build_agent_view_artifacts(...)`
- `Orchestrator` now delegates the full agent-view path through shared context-building support, while focused regressions re-cleared locally at `760 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Task-visibility helper slice recorded

- the next deterministic refactor slice co-located the adjacent task-visibility helpers `_task_dependency_closure_ids(...)` and `_direct_dependency_ids(...)` into `kycortex_agents/orchestration/context_building.py`
- the extracted support now owns dependency-closure expansion and direct-dependency collection for the context/view assembly corridor through `task_dependency_closure_ids(...)` and `direct_dependency_ids(...)`
- `Orchestrator` now delegates those helpers through shared context-building support, while focused regressions re-cleared locally at `762 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Repair-validation summary slice recorded

- the next deterministic refactor slice co-located `_build_repair_validation_summary(...)` into `kycortex_agents/orchestration/validation_reporting.py`
- the extracted support now owns failure-category-based dispatch across code, test, and dependency validation summary rendering through `build_repair_validation_summary(...)`
- `Orchestrator` now delegates that repair-summary dispatcher through shared reporting support, while focused regressions re-cleared locally at `763 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Payload/output helper slice recorded

- the next deterministic refactor slice co-located `_validation_payload(...)` and `_task_context_output(...)` into `kycortex_agents/orchestration/output_helpers.py`
- the extracted support now owns nested validation metadata recovery plus task-context output fallback selection through `validation_payload(...)` and `task_context_output(...)`
- `Orchestrator` now delegates those two local helpers through shared output support, while focused regressions re-cleared locally at `765 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Code-repair instruction runtime slice recorded

- the next deterministic refactor slice co-located `_build_code_repair_instruction_from_test_failure(...)` into `kycortex_agents/orchestration/repair_instructions.py`
- the extracted support now owns failed-artifact lookup plus the final code-repair instruction dispatch through `build_code_repair_instruction_from_test_failure_runtime(...)`
- `Orchestrator` now delegates that code-repair instruction shell through shared repair-instruction support, while focused regressions re-cleared locally at `766 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Repair-instruction runtime slice recorded

- the next deterministic refactor slice co-located `_build_repair_instruction(...)` into `kycortex_agents/orchestration/repair_instructions.py`
- the extracted support now owns failed-artifact lookup plus the final repair-instruction runtime dispatch through `build_repair_instruction_runtime(...)`
- `Orchestrator` now delegates that repair-instruction shell through shared repair-instruction support, while focused regressions re-cleared locally at `767 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Test-repair helper-surface runtime slice recorded

- the next deterministic refactor slice co-located `_test_repair_helper_surface_usages(...)` into `kycortex_agents/orchestration/repair_test_analysis.py`
- the extracted support now owns validation-payload lookup plus helper-surface usage dispatch through `helper_surface_usages_for_test_repair_runtime(...)`
- `Orchestrator` now delegates that helper-surface shell through shared repair-test analysis support, while focused regressions re-cleared locally at `767 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Failed-test code-repair runtime slice recorded

- the next deterministic refactor slice co-located `_test_failure_requires_code_repair(...)` into `kycortex_agents/orchestration/repair_test_analysis.py`
- the extracted support now owns validation-payload lookup plus failed-test code-repair dispatch through `failed_test_requires_code_repair_runtime(...)`
- `Orchestrator` now delegates that failed-test routing shell through shared repair-test analysis support, while focused regressions re-cleared locally at `767 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Test validation runtime façade slice recorded

- the next deterministic refactor slice co-located the remaining `_validate_test_output(...)` orchestration shell into `kycortex_agents/orchestration/validation_runtime.py`
- the extracted support now owns syntax gating, context/artifact bootstrap, runtime-state preparation dispatch, validation metadata persistence, issue collection, and final error-message raising for generated-test validation
- `Orchestrator` now delegates the full generated-test validation path through `validate_test_output_runtime(...)` while focused regressions re-cleared locally at `749 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Code validation-issue aggregation slice recorded

- the next deterministic refactor slice co-located the deterministic generated-code validation-issue assembly into `kycortex_agents/orchestration/validation_analysis.py`
- the extracted support now owns syntax, line-budget, CLI-entrypoint, import-failure, task-contract, dataclass-field, and truncation issue aggregation for `_validate_code_output(...)`
- `Orchestrator` now delegates that issue assembly through `collect_code_validation_issues(...)` while focused regressions re-cleared locally at `750 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Code validation-metadata persistence slice recorded

- the next deterministic refactor slice co-located repeated generated-code validation metadata persistence into `kycortex_agents/orchestration/validation_runtime.py`
- the extracted support now owns synchronized writes of code analysis, task-public-contract preflight, import validation, and completion diagnostics onto `output.metadata["validation"]`
- `Orchestrator` now delegates that repeated `_record_output_validation(...)` sequence through `record_code_validation_metadata(...)` while focused regressions re-cleared locally at `751 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Code validation runtime façade slice recorded

- the next deterministic refactor slice co-located the remaining `_validate_code_output(...)` orchestration shell into `kycortex_agents/orchestration/validation_runtime.py`
- the extracted support now owns content selection, static analysis, line-budget and CLI-entrypoint requirements, task-contract preflight, completion diagnostics, optional import validation, validation metadata persistence, deterministic issue aggregation dispatch, and final error raising for generated code validation
- `Orchestrator` now delegates the full generated-code validation path through `validate_code_output_runtime(...)` while focused regressions re-cleared locally at `752 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-20 - Test validation-metadata persistence slice recorded

- the next deterministic refactor slice co-located repeated generated-test validation metadata persistence into `kycortex_agents/orchestration/validation_runtime.py`
- the extracted support now owns the deterministic writes of test analysis, pytest execution, completion diagnostics, filenames, and pytest failure origin onto `output.metadata["validation"]`
- `Orchestrator` now delegates that repeated `_record_output_validation(...)` sequence through `record_test_validation_metadata(...)` while focused regressions re-cleared locally at `746 passed`, with `ruff` and `mypy` also green across 69 source files

## Local operational milestone on 2026-04-19 - Coverage gate remediated after AST-expression slice

- the post-`cc960de` GitHub Actions failure moved from `mypy` to the `Coverage Gate`, where the full local gate initially stopped at `1607 passed` and `89.64%`
- the first remediation fixed the remaining stale `callable_name` formatting path in `Orchestrator` that was still breaking two behavior-analysis regressions under the coverage command
- the second remediation added direct support coverage for deterministic orchestration helpers and instruction builders instead of weakening `fail_under = 90`
- the final local CI-equivalent coverage command now re-clears at `1620 passed` and `90.02%`, restoring a truthful green baseline for the refactor branch

## Local operational milestone on 2026-04-19 - Failed-artifact-by-category slice recorded

- the next deterministic refactor slice co-located category-based failed-artifact lookup into `kycortex_agents/orchestration/repair_analysis.py`
- the extracted support now owns the composition of failure-category to artifact-type routing with shared failed-artifact-content lookup
- `Orchestrator` kept the thin `_failed_artifact_content_for_category(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-19 - Test-repair helper-surface usage slice recorded

- the next deterministic refactor slice co-located test-repair helper-surface usage parsing into `kycortex_agents/orchestration/repair_test_analysis.py`
- the extracted support now owns validation-payload parsing for helper surface usages used during test-repair context assembly
- `Orchestrator` kept the thin `_test_repair_helper_surface_usages(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-19 - Prior repair-context merge slice recorded

- the next deterministic refactor slice co-located prior repair-context merging into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns instruction and validation-summary augmentation when repair tasks must preserve unresolved objectives from an earlier failure
- `Orchestrator` kept the thin `_merge_prior_repair_context(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-19 - Repair-context assembly slice recorded

- the next deterministic refactor slice co-located repair-context assembly into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns deterministic assembly of failure metadata, repair ownership, instruction text, validation summary, failed-artifact lookup, helper-surface metadata, and prior-context merge dispatch
- `Orchestrator` kept the thin `_build_repair_context(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-19 - Code-repair-context-from-test-failure slice recorded

- the next deterministic refactor slice co-located code-repair context assembly from failed tests into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns deterministic assembly of code-repair context derived from failed-test validation, including existing-tests lookup, validation-summary reuse, failed-artifact lookup, and prior-context merge dispatch
- `Orchestrator` kept the thin `_build_code_repair_context_from_test_failure(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-19 - Failed-test code-repair routing slice recorded

- the next deterministic refactor slice co-located failed-test code-repair routing into `kycortex_agents/orchestration/repair_test_analysis.py`
- the extracted support now owns the deterministic decision over whether a failed test should trigger code repair, including failure-origin fallback, contract-overreach suppression, blocking-validation short-circuiting, and semantic-assertion mismatch routing
- `Orchestrator` kept the thin `_test_failure_requires_code_repair(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Failed-test code-task lookup slice recorded

- the next deterministic refactor slice co-located imported and upstream code-task lookup for failed tests into `kycortex_agents/orchestration/repair_test_analysis.py`
- the extracted support now owns import-root-based code-task matching plus dependency-aware upstream resolution used by the repair-launch path for failed tests
- `Orchestrator` kept the thin `_imported_code_task_for_failed_test(...)` and `_upstream_code_task_for_test_failure(...)` façade wrappers while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Failed-task selection slice recorded

- the next deterministic refactor slice co-located failed-task selection for repair planning into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the filtering of failed origin tasks that are eligible for a new repair cycle while excluding already-active repair origins
- `Orchestrator` kept the thin `_failed_task_ids_for_repair(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Repair-task-id planning slice recorded

- the next deterministic refactor slice co-located repair-task id planning for a cycle into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns repair-task creation ordering, optional code-repair chaining, decomposition-task dependency wiring, and returned repair-task-id accumulation for one repair cycle
- `Orchestrator` kept the thin `_repair_task_ids_for_cycle(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Repair-attempt configuration slice recorded

- the next deterministic refactor slice co-located repair-attempt configuration into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns failed-task iteration, optional upstream code-repair planning, decomposition-task attachment, and final repair-context dispatch for one repair cycle
- `Orchestrator` kept the thin `_configure_repair_attempts(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Active-cycle repair queueing slice recorded

- the next deterministic refactor slice co-located active-cycle repair queueing into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns active-cycle gating, repair-attempt configuration dispatch, repair-task resumption, and `task_repair_chained` event/log emission for one failed origin task
- `Orchestrator` kept the thin `_queue_active_cycle_repair(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Cycle-local repair-task presence slice recorded

- the next deterministic refactor slice co-located cycle-local repair-task presence lookup into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the small deterministic scan for whether a failed origin task already has a repair child for a given cycle number
- `Orchestrator` kept the thin `_has_repair_task_for_cycle(...)` façade wrapper while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Failed-task repair-cycle resumption slice recorded

- the next deterministic refactor slice co-located failed-task repair-cycle resumption into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns repair-budget exhaustion handling, repair-cycle start metadata, repair-attempt configuration dispatch, repair-task-id accumulation, and failed-task resumption for one resume-failed branch
- `execute_workflow(...)` now delegates that subflow to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Failed-workflow resume dispatch slice recorded

- the next deterministic refactor slice co-located failed-workflow resume dispatch into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the decision between hard-stopping on non-repairable failure categories and delegating to the shared repair-cycle resumption flow for repairable failures
- `execute_workflow(...)` now delegates that decision branch to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow resume preparation slice recorded

- the next deterministic refactor slice co-located workflow resume preparation into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns interrupted-task resumption, failed-task discovery, failed-workflow resume dispatch, and the resulting `workflow_resumed` log/save side effects before entering the main execution loop
- `execute_workflow(...)` now delegates that top-of-method preparation to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow start guarding slice recorded

- the next deterministic refactor slice co-located workflow start guarding into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the idempotent `workflow_started` transition check, `mark_workflow_running(...)` call, and paired log emission before entering the main execution loop
- `execute_workflow(...)` now delegates that top-level start guard to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - No-pending workflow completion slice recorded

- the next deterministic refactor slice co-located no-pending workflow completion into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns acceptance evaluation, `completed` versus `degraded` terminal-outcome selection, final workflow persistence, and `workflow_completed` logging when the main loop has no pending tasks left
- `execute_workflow(...)` now delegates that terminal branch to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow-definition failure slice recorded

- the next deterministic refactor slice co-located workflow-definition failure handling into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the terminal state transition, acceptance-evaluation persistence, save, and `workflow_failed` logging when `project.runnable_tasks()` raises `WorkflowDefinitionError`
- `execute_workflow(...)` now delegates that terminal branch to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow-blocked failure slice recorded

- the next deterministic refactor slice co-located workflow-blocked failure handling into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns blocked-task id rendering, the terminal blocked-workflow state transition, acceptance-evaluation persistence, save, and `workflow_blocked` logging when pending tasks have no runnable frontier
- `execute_workflow(...)` now delegates that terminal branch to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow-continue failure branch slice recorded

- the next deterministic refactor slice co-located workflow-continue task-failure handling into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns dependent-task skipping, workflow-progress emission, persistence, and `dependent_tasks_skipped` logging for the shared `workflow_failure_policy == "continue"` branch inside task-execution failure handling
- `execute_workflow(...)` now delegates both duplicate continue-policy branches to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow fail-fast task-failure slice recorded

- the next deterministic refactor slice co-located workflow fail-fast task-failure handling into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the terminal failed-state transition, acceptance-evaluation persistence, save, and `workflow_failed` logging for the shared non-continue branch inside task-execution failure handling
- `execute_workflow(...)` now delegates both duplicate fail-fast branches to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow progress save helper slice recorded

- the next deterministic refactor slice co-located repeated workflow progress emission plus persistence into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the shared `emit progress + save` sequence reused by retry handling, repair-chain continuation, continue-policy failure handling, and normal task completion
- `execute_workflow(...)` now delegates those repeated progress/save paths to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Task failure dispatch slice recorded

- the next deterministic refactor slice co-located task-failure dispatch into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the remaining retry-versus-repairable-versus-policy routing decision tree built on top of the already-extracted progress/save, continue-policy, fail-fast, and repair-chain helpers
- `execute_workflow(...)` now delegates the full failure dispatcher to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow task execution slice recorded

- the next deterministic refactor slice co-located per-task workflow execution into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the inner cancel/pause guards, `run_task(...)` call, task-failure classification handoff, dispatcher invocation, original-exception propagation, and success progress/save path for one runnable task
- `execute_workflow(...)` now delegates one full runnable-task execution step to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Runnable-task iteration slice recorded

- the next deterministic refactor slice co-located runnable-task iteration into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns traversal of the current runnable frontier and the early-return handoff when one task execution requests a workflow exit
- `execute_workflow(...)` now delegates runnable-frontier iteration to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Runnable-frontier execution slice recorded

- the next deterministic refactor slice co-located runnable-frontier execution into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns runnable-frontier resolution, workflow-definition failure handling, blocked-workflow handling, and the handoff into runnable-task iteration
- `execute_workflow(...)` now delegates the full runnable-frontier boundary to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow loop control slice recorded

- the next deterministic refactor slice co-located outer workflow-loop control into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the remaining `while True` control flow: cancellation checks, pending-task lookup, completion dispatch, pause checks, and runnable-frontier execution handoff
- `execute_workflow(...)` now delegates the outer loop to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Active-workflow shell slice recorded

- the next deterministic refactor slice co-located the active-workflow shell into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the post-resume cancel/pause guards, start guard handoff, outer-loop execution, and final `workflow_finished` logging
- `execute_workflow(...)` now delegates the whole active-workflow shell to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow bootstrap shell slice recorded

- the next deterministic refactor slice co-located the workflow bootstrap shell into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the initial cancellation gate, execution-plan bootstrap, agent-resolution validation, repair-budget initialization, resume preparation handoff, and active-workflow handoff
- `execute_workflow(...)` now delegates the workflow bootstrap to shared support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Workflow runtime façade slice recorded

- the next deterministic refactor slice co-located the final workflow-runtime façade into `kycortex_agents/orchestration/workflow_control.py`
- the extracted support now owns the final top-level runtime handoff built on the previously-extracted bootstrap and active-workflow helpers
- `execute_workflow(...)` is now effectively a thin façade over shared workflow-control support while focused regressions (`579 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Context repair-application slice recorded

- the next deterministic refactor slice co-located repair-context application inside `_build_context(...)` into `kycortex_agents/orchestration/context_building.py`
- the extracted support now owns the deterministic population of repair-context-visible fields, reused existing-code/tests injection, helper-surface metadata, and QA/dependency repair carry-forward context
- `_build_context(...)` now delegates that final repair-context branch to shared support while focused regressions (`581 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Context completed-task application slice recorded

- the next deterministic refactor slice co-located completed-task output application inside `_build_context(...)` into `kycortex_agents/orchestration/context_building.py`
- the extracted support now owns completed-task registration, budget-decomposition brief carry-forward, budget-planner short-circuiting, and semantic alias population including compact architecture substitution
- `_build_context(...)` now delegates that loop-body branch to shared support while focused regressions (`583 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Context artifact-dispatch slice recorded

- the next deterministic refactor slice co-located completed-task artifact-context dispatch inside `_build_context(...)` into `kycortex_agents/orchestration/context_building.py`
- the extracted support now owns the role-based dispatch that applies code, dependency, and test artifact-context helpers for completed visible tasks
- `_build_context(...)` now delegates that loop-body branch to shared support while focused regressions (`586 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Context contract-application slice recorded

- the next deterministic refactor slice co-located task public-contract anchor and architecture-compaction application inside `_build_context(...)` into `kycortex_agents/orchestration/context_building.py`
- the extracted support now owns anchor injection and optional compact-architecture selection for low-budget or repair-sensitive context assembly
- `_build_context(...)` now delegates that pre-loop branch to shared support while focused regressions (`588 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Module analysis slice recorded

- the next deterministic refactor slice co-located Python module analysis into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now owns syntax parsing, public symbol discovery, import-root classification, dataclass/constructor inspection, and third-party import detection for generated code analysis
- `Orchestrator` now delegates `_analyze_python_module(...)` and `_is_probable_third_party_import(...)` to shared support while focused regressions (`590 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Code public-API slice recorded

- the next deterministic refactor slice co-located code public-API summary rendering into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now owns formatting of public function signatures, class constructor fields, method lists, enum members, and entrypoint visibility for prompt context assembly
- `Orchestrator` now delegates `_build_code_public_api(...)` to shared support while focused regressions (`591 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Code behavior-contract slice recorded

- the next deterministic refactor slice co-located code behavior-contract rendering into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now owns validation-rule aggregation, field-value and type-constraint rendering, batch and sequence rule rendering, constructor-storage and score-derivation hints, and literal fixture example formatting for prompt context assembly
- `Orchestrator` now delegates `_build_code_behavior_contract(...)` to shared support while focused regressions (`733 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Test-target classification helper slice recorded

- the next deterministic refactor slice co-located entrypoint, preferred-class, helper-class, and exposed-test-class classification into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now owns the reusable heuristics that filter CLI/demo entrypoints, preserve required constructor helpers, and identify compact workflow-test surfaces for adjacent prompt formatters
- `Orchestrator` now delegates `_entrypoint_*`, `_preferred_test_class_names(...)`, `_constructor_param_matches_class(...)`, `_helper_classes_to_avoid(...)`, and `_exposed_test_class_names(...)` to shared support while focused regressions (`734 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Exact test-contract slice recorded

- the next deterministic refactor slice co-located exact test-contract formatting into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now owns allowed-import rendering, preferred facade reporting, exact callable and method listing, constructor-field formatting, and the final anti-aliasing guidance used in prompt context assembly
- `Orchestrator` now delegates `_build_code_exact_test_contract(...)` to shared support while focused regressions (`735 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Test-target formatter slice recorded

- the next deterministic refactor slice co-located test-target formatting into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now owns testable-function bucketing, batch-versus-scalar grouping, preferred workflow reporting, helper-class avoidance rendering, and entrypoint exclusion formatting used in prompt context assembly
- `Orchestrator` now delegates `_build_code_test_targets(...)` to shared support while focused regressions (`736 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Module run-command slice recorded

- the next deterministic refactor slice co-located module run-command rendering into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now owns the tiny `__main__`-guard-to-`python MODULE_FILE` formatter used in generated-code context assembly
- `Orchestrator` now delegates `_build_module_run_command(...)` to shared support while focused regressions (`737 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Dead test-target wrapper retirement slice recorded

- the next deterministic refactor slice retired dead compatibility wrappers for entrypoint and helper-class classification from `Orchestrator`
- the remaining internal caller in test-module analysis now uses the shared `module_ast_analysis.py` helpers directly instead of routing through façade-only methods with no external consumers
- focused regressions (`737 passed`), `ruff`, and `mypy` all re-cleared locally after the wrapper retirement and import cleanup

## Local operational milestone on 2026-04-20 - Behavior-contract parsing slice recorded

- the next deterministic refactor slice co-located behavior-contract parsing into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now owns parsing of validation rules, field-value constraints, type constraints, sequence-input markers, and batch-shape rules from the prompt-facing behavior-contract text
- `Orchestrator` now delegates `_parse_behavior_contract(...)` to shared support while focused regressions (`738 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Test behavior-contract analysis slice recorded

- the next deterministic refactor slice co-located test behavior-contract enforcement analysis into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now owns payload-field validation, invalid-value detection, batch-rule enforcement, and non-batch list-input detection over generated test ASTs
- `Orchestrator` now delegates `_analyze_test_behavior_contracts(...)` to shared support while focused regressions (`739 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Test type-mismatch analysis slice recorded

- the next deterministic refactor slice co-located test type-mismatch enforcement analysis into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now owns the deterministic scan over generated test calls that skips negative-expectation paths, resolves payload bindings, infers observed field types, and reports mismatches against parsed behavior-contract type rules
- `Orchestrator` now delegates `_analyze_test_type_mismatches(...)` to shared support while focused regressions (`740 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Test type-mismatch auto-fix slice recorded

- the next deterministic refactor slice co-located test type-mismatch auto-fix logic into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now owns implementation parsing, dict-key discovery callback usage, negative-test skipping, local dict-variable reuse, and string-to-dict argument replacement for generated tests
- `Orchestrator` now delegates `_auto_fix_test_type_mismatches(...)` to shared support while focused regressions (`741 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Test module analysis slice recorded

- the next deterministic refactor slice co-located full generated-test module analysis into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now owns blank/syntax handling, import and fixture tracking, invalid member and arity detection, helper-surface detection, contract-overreach aggregation, payload/type validation integration, and final analysis-shape assembly
- `Orchestrator` now delegates `_analyze_test_module(...)` to shared support while focused regressions (`742 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Test validation issue aggregation slice recorded

- the next deterministic refactor slice co-located generated-test validation issue aggregation into `kycortex_agents/orchestration/validation_analysis.py`
- the extracted support now owns deterministic assembly of blocking issues, warning issues, truncation handling, and pytest-pass/fail arbitration inputs from `test_analysis`, `test_execution`, and completion diagnostics
- `_validate_test_output(...)` now delegates that issue aggregation to shared support while focused regressions (`743 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Test validation error-message slice recorded

- the next deterministic refactor slice co-located the final generated-test validation error-message decision into `kycortex_agents/orchestration/validation_analysis.py`
- the extracted support now owns the final message composition for blocking issues and warning-only-without-pytest-confirmation outcomes, leaving `_validate_test_output(...)` with only the final raise-if-message shell
- `_validate_test_output(...)` now delegates that final message composition to shared support while focused regressions (`744 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-20 - Test output content replacement slice recorded

- the next deterministic refactor slice co-located repeated generated-test output mutation into `kycortex_agents/orchestration/validation_runtime.py`
- the extracted support now owns synchronized `AgentOutput` raw-content, summary, and test-artifact content replacement for both finalized and auto-fixed test content paths
- `_validate_test_output(...)` now delegates that repeated mutation to shared support while focused regressions (`745 passed`), `ruff`, and `mypy` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-19 - Safe restart checkpoint recorded

- latest published remote checkpoint: `abdc44d refactor: extract repair context assembly`
- local branch state at checkpoint: clean `main`, aligned with `origin/main`
- latest validated gate at checkpoint: focused orchestration regressions (`579 passed`), `ruff`, and `mypy`
- next restart target: scan the now-thinner repair-launch and repair-integration path in `Orchestrator` for the next smallest deterministic extraction

## Local operational milestone on 2026-04-19 - Test-analysis AST helper slice recorded

- the next deterministic refactor slice extracted the mock-support typed-analysis cluster into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now owns local-name binding collection, parametrized-argument discovery, mock/patch support detection, unsupported mock-assertion detection, and test local-type collection
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions, `mypy`, and `ruff` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-19 - Adjacent AST helper slice recorded

- the next deterministic refactor slice co-located adjacent AST test-analysis helpers into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now also owns AST containment checks, local binding collection, and module-defined-name discovery used by the typed test-analysis path
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`709 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Module AST signature slice recorded

- the next deterministic refactor slice extracted module AST signature helpers into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now owns sequence-input annotation checks, function signature shaping, method binding-kind detection, and `self`-assigned attribute discovery used by `_analyze_python_module(...)`
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the new boundary

## Local operational milestone on 2026-04-19 - Module AST dataclass helper slice recorded

- the next deterministic refactor slice co-located adjacent dataclass and call-basename helpers into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now also owns dataclass decorator detection, call basename discovery, dataclass default detection, and dataclass `init=` handling used by `_analyze_python_module(...)`
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Module AST required-field slice recorded

- the next deterministic refactor slice co-located sequence-input and required-field analysis helpers into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now also owns first-user-parameter discovery, iterated-parameter detection, required-field extraction, indirect required-field propagation, selector-name parsing, and lookup-field rule derivation used by module behavior analysis
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Module AST sequence-input rule slice recorded

- the next deterministic refactor slice co-located adjacent sequence-input rule helpers into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now also owns direct-return detection, callable positional-parameter discovery, and sequence-input rule rendering used by module behavior analysis
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Module AST dict-analysis slice recorded

- the next deterministic refactor slice co-located static dict-example and dict-key analysis helpers into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now also owns default-example rendering, inferred dict key/value example derivation, and dict-accessed-key collection used by module behavior analysis
- `Orchestrator` kept compatibility shims stable while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Module AST type-constraint slice recorded

- the next deterministic refactor slice co-located `isinstance`-based type-constraint helpers into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now also owns `isinstance` call collection, subject-name parsing, type-name parsing, and type-constraint extraction used by module behavior analysis
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Module AST literal-example and batch-rule slice recorded

- the next deterministic refactor slice co-located literal-example extraction and batch-shape rule derivation into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now also owns top-level dict/list example discovery and batch intake-shape rendering used by module behavior analysis
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Module AST class-style and constructor-storage slice recorded

- the next deterministic refactor slice co-located class-definition style, return-type annotation, and constructor-storage rule derivation into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now also owns human-readable class style rendering, public return-type rendering, and constructor payload-storage detection used by the module behavior contract
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Module AST score-derivation slice recorded

- the next deterministic refactor slice co-located score-derivation helpers into `kycortex_agents/orchestration/module_ast_analysis.py`
- the extracted support now also owns score-return detection, local alias expansion, helper-call inlining, score-expression rendering, and score-derivation rule extraction used by the module behavior contract
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Test AST literal payload helper slice recorded

- the next deterministic refactor slice co-located literal payload inspection and argument-type inference helpers into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now also owns bound-value resolution, constructor-argument lookup, literal dict/list inspection, string-literal extraction, and payload field type inference used by typed test analysis and batch-call validation
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Test AST typed member-usage slice recorded

- the next deterministic refactor slice co-located typed member-usage inference helpers into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now also owns call-argument counting, expression-type inference, call-result type inference, and typed member-usage validation used by the typed test-analysis path
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Test AST batch-validation slice recorded

- the next deterministic refactor slice co-located payload-selection and batch-call validation helpers into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now also owns validation-payload selection and batch item field-shape validation used by the typed test-analysis path
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Test AST negative-expectation slice recorded

- the next deterministic refactor slice co-located negative-expectation and invalid-outcome helpers into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now also owns false-assert detection, invalid-outcome marker matching, result-name recovery, and follow-up invalid-outcome assertion detection used by the typed test-analysis path
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Test AST partial-batch slice recorded

- the next deterministic refactor slice co-located partial-batch-result helpers into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now also owns partial-batch assertion detection, batch-result length matching, integer-constant extraction, and partial-result comparison evaluation used by the typed test-analysis path
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Test AST parent-map slice recorded

- the next deterministic refactor slice co-located the shared AST parent-map utility into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now also owns parent-child lookup map construction used by the typed test-analysis path
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Test AST contract-overreach slice recorded

- the next deterministic refactor slice co-located contract-overreach score-state and visible-batch heuristics into `kycortex_agents/orchestration/test_ast_analysis.py`
- the extracted support now also owns validation-failure test-name detection, internal score-state target detection, exact length assertion parsing, visible batch-size detection, and overreach signal derivation used by the typed test-analysis path
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Repair-analysis invalid-path delegation slice recorded

- the next deterministic refactor slice promoted the existing invalid-path and missing-audit-trail helpers in `kycortex_agents/orchestration/repair_analysis.py` for shared reuse instead of keeping duplicate implementations in `Orchestrator`
- the shared repair-analysis support now owns invalid-literal comparison detection, invalid-path test targeting, non-empty result-field checks, empty-default detection, and invalid-outcome audit-return extraction used by the repair-analysis path
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`710 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - QA repair-suite reuse slice recorded

- the next deterministic refactor slice co-located failed-suite reuse evaluation into `kycortex_agents/orchestration/repair_test_analysis.py`
- the shared repair-test-analysis support now owns helper-alias drift, reusable-missing-import, missing-datetime-import, required-evidence-runtime, and contract-overreach gating used to decide whether the failed test artifact should be reused during QA repair
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`712 passed`), `mypy`, and `ruff` all re-cleared locally on the expanded boundary

## Local operational milestone on 2026-04-19 - Failing pytest test-name slice recorded

- the next deterministic refactor slice promoted failing pytest test-name parsing for shared reuse from `kycortex_agents/orchestration/repair_analysis.py`
- the shared repair-analysis support now owns normalized failing-test-name extraction used by the invalid-path and missing-audit-trail analysis path
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`713 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Dead append-unique wrapper retired

- the next deterministic refactor slice retired the dead `_append_unique_mapping_value(...)` façade wrapper from `Orchestrator`
- the only live append-unique mapping logic remains internal to `kycortex_agents/orchestration/repair_test_analysis.py`, so the façade no longer carries an unused duplicate helper
- focused regressions (`713 passed`), `mypy`, and `ruff` all re-cleared locally after the retirement

## Local operational milestone on 2026-04-19 - Dead string-literal wrapper retired

- the next deterministic refactor slice retired the dead `_string_literal_sequence(...)` façade wrapper from `Orchestrator`
- the live string-literal sequence helpers remain in `kycortex_agents/orchestration/repair_analysis.py`, `kycortex_agents/orchestration/repair_signals.py`, and `qa_tester`, so the façade no longer carries an unused duplicate helper
- focused regressions (`713 passed`), `mypy`, and `ruff` all re-cleared locally after the retirement

## Local operational milestone on 2026-04-19 - Task public-contract parser slice recorded

- the next deterministic refactor slice co-located task public-contract surface parsing into `kycortex_agents/orchestration/task_constraints.py`
- the shared task-constraint support now owns owner/name/parameter extraction for anchored callable surfaces used by the task public-contract preflight path
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`714 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Task public-contract anchor slice recorded

- the next deterministic refactor slice co-located task public-contract anchor extraction into `kycortex_agents/orchestration/task_constraints.py`
- the shared task-constraint support now owns extraction of anchored bullet lines and indented continuations from task descriptions used by context building and public-contract preflight
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`715 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Task public-contract preflight slice recorded

- the next deterministic refactor slice co-located task public-contract preflight evaluation into `kycortex_agents/orchestration/task_constraints.py`
- the shared task-constraint support now owns public facade, request-model, required-surface, and main-guard mismatch detection for anchored task contracts
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`716 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Python import-root slice recorded

- the next deterministic refactor slice co-located Python import-root discovery into `kycortex_agents/orchestration/ast_tools.py`
- the shared AST support now owns top-level import-root discovery used by the failed-test import analysis path in `Orchestrator`
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`717 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Dependency-analysis slice recorded

- the next deterministic refactor slice co-located dependency-manifest normalization and validation into `kycortex_agents/orchestration/dependency_analysis.py`
- the shared orchestration support now owns package/import normalization, manifest gap detection, and provenance-violation detection used by the dependency artifact analysis path
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`718 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Code-outline slice recorded

- the next deterministic refactor slice co-located code-outline extraction into `kycortex_agents/orchestration/module_ast_analysis.py`
- the shared module-analysis support now owns top-level class/function outline extraction used by the code-artifact context path
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`718 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Validation-summary limit slice recorded

- the next deterministic refactor slice co-located validation-summary limit parsing into `kycortex_agents/orchestration/task_constraints.py`
- the shared task-constraint support now owns summary budget-overrun detection used by the budget-decomposition repair gate
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`718 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Budget-decomposition planner slice recorded

- the next deterministic refactor slice co-located budget-decomposition planner detection into `kycortex_agents/orchestration/task_constraints.py`
- the shared task-constraint support now owns repair-context planner-mode detection used while assembling visible completed-task context
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`718 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Budget-decomposition instruction/context slice recorded

- the next deterministic refactor slice co-located budget-decomposition instruction and task-context builders into `kycortex_agents/orchestration/task_constraints.py`
- the shared task-constraint support now owns category-specific compact-brief instructions plus decomposition task-context assembly used when creating budget-compaction planner tasks
- `Orchestrator` kept thin private wrappers for compatibility while focused regressions (`718 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Budget-decomposition gate slice recorded

- the next deterministic refactor slice co-located budget-decomposition gate evaluation into `kycortex_agents/orchestration/task_constraints.py`
- the shared task-constraint support now owns validation-summary and failure-category gating used to decide when a compact planner task must be inserted before repair
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`718 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Pylance typing remediation recorded

- the next maintenance pass cleared the real workspace Pylance diagnostics without changing runtime behavior
- `AcceptanceLane` now requires `accepted` and `reason`, and the affected tests now narrow AST node shapes and optional helper returns explicitly instead of relying on implicit inference
- targeted regressions (`577 passed`), `mypy`, and `ruff` all re-cleared locally after the typing cleanup

## Local operational milestone on 2026-04-19 - Repair-owner slice recorded

- the next deterministic refactor slice co-located repair-owner routing into `kycortex_agents/orchestration/repair_instructions.py`
- the shared repair-instruction support now owns failure-category to execution-agent routing used when building repair context
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`578 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Failure-category artifact mapping slice recorded

- the next deterministic refactor slice co-located failure-category artifact-type mapping into `kycortex_agents/orchestration/repair_analysis.py`
- the shared repair-analysis support now owns category-to-`ArtifactType` selection used by the failed-artifact lookup path
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`578 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Budget-decomposition task creation slice recorded

- the next deterministic refactor slice co-located budget-decomposition task creation/reuse into `kycortex_agents/orchestration/workflow_control.py`
- the shared workflow-control support now owns reuse of existing plan tasks plus creation of new budget-compaction planner tasks when the repair gate is open
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`578 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Active repair-cycle slice recorded

- the next deterministic refactor slice co-located active repair-cycle lookup into `kycortex_agents/orchestration/workflow_control.py`
- the shared workflow-control support now owns recovery of the current repair-cycle mapping from `ProjectState.repair_history`
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`578 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Local operational milestone on 2026-04-19 - Failed-artifact lookup slice recorded

- the next deterministic refactor slice co-located failed-artifact content lookup into `kycortex_agents/orchestration/artifacts.py`
- the shared artifact support now owns artifact-list scanning and raw-content fallback used by the repair-context assembly path
- `Orchestrator` kept a thin private wrapper for compatibility while focused regressions (`579 passed`), `mypy`, and `ruff` all re-cleared locally on the delegated boundary

## Timeline by milestone

### 2026-03-20 - Repository foundation

- `322306a Initial commit`
- `a69447d feat: Initial KYCortex AI Software House framework with multi-agent orchestration`

Reading:

- the product starts as a multi-agent orchestration framework
- the focus is already on orchestrating specialized roles, not on calling a single isolated LLM

### 2026-03-21 - Typed contracts, providers, agents, and scheduling

Main milestones:

- typed domain model
- orchestrator context refactor
- `BaseAgent` hardening
- provider abstraction and runtime config
- agent registry
- typed runtime inputs and outputs
- dependency-aware workflow scheduling
- retries and resumability

Reading:

- this is where the product stops being a simple prototype and takes shape as a runtime framework

### 2026-03-22 - Rich persistence, public API, and heavy coverage

Main milestones:

- artifacts, outputs, metadata, events, durations, usage, and logging
- stable `workflows` public surface and exports
- major coverage growth in state, resume, provider, snapshot, context, and retry tests

Reading:

- the repository invests heavily in defensive engineering and auditability very early

### 2026-03-23 - Docs, examples, tooling, and CI

Main milestones:

- docs for architecture, providers, workflows, persistence, and extensions
- examples for resume, custom agents, multi-provider, and test mode
- local tooling, pre-commit, and CI baseline

Reading:

- this phase consolidates the repository as a usable and explainable open-source product

### 2026-03-24 - Packaging and the 1.0.0 release baseline

Main milestones:

- packaging validation
- release workflow automation
- release guide, release status, and migration guide
- repository coverage gate
- finalization of the 1.0.0 baseline

Reading:

- the project closes its first publishable line with distribution discipline

### 2026-03-25 - Post-1.0.0: acceptance, repair, provider matrix, and safety

Main milestones:

- terminal workflow outcome scaffold
- explicit workflow acceptance policy
- bounded repair budgets
- failure-category repair routing
- corrective lineage
- provider matrix validation
- initial sandbox hardening
- provider retries, jitter, circuit breaker, fallback, cancellation, and health state

Reading:

- the focus shifts from "it works" to "it works in a controlled and recoverable way"

### 2026-03-26 - Strong sandbox isolation and coverage cleanup

Direct milestone:

- `17e690c hardening: complete phase 8 sandbox isolation`

Complements:

- blocking host reads, directory enumeration, realpath leaks, env inheritance, and metadata probes
- closing orchestrator helper coverage gaps

Reading:

- this is a major turn: the framework starts treating generated-code execution as an untrusted workload

### 2026-03-28 - Workflow telemetry and provider health

Main milestones:

- provider health resilience
- workflow telemetry
- repair summaries
- progress summaries
- provider health summaries

Reading:

- a rich observable surface emerges here and is later split again between public and internal views

### 2026-03-30 - Releases 1.0.11, 1.0.12, and 1.0.13a1

Main milestones:

- explicit `ollama_num_ctx`
- completion-aware diagnostics
- task-derived validation budgets
- release user smoke example
- hardened guidance for compact code and test generation

Reading:

- the repository enters a phase of empirical maturation and fine-tuning against real providers

### 2026-04-02 through 2026-04-06 - Privacy hardening and public-surface minimization

Main milestones:

- secret redaction in prompts, metadata, outputs, state views, and matrix summaries
- path exposure limits
- minimization of provider, retry, fallback, repair, and acceptance details in the public surface
- hardened permissions for state store and artifacts

Reading:

- this phase prepares the serious boundary split between what is safe to expose and what must remain internal

### 2026-04-07 - Boundary split and 1.0.13a2 preparation

Main milestones:

- `4f476a4 Split public snapshot from internal runtime telemetry`
- release workflow gate alignment
- release artifact manifest
- release promotion summary
- published release asset verification
- prepare 1.0.13a2 alpha

Reading:

- the project closes the four-view architecture and strengthens the release trust chain

### 2026-04-09 through 2026-04-10 - Repair guidance and final prompt hardening

Main milestones:

- duplicate-call rewrite hints
- nested repair-module context alignment
- stale repaired-module import avoidance
- prompt v15 hardening
- `6bd6fed Fix CI prompt assertion drift`

Reading:

- the immediate focus becomes repair-loop stability and CI consistency

## Local operational milestone on 2026-04-12

- the fresh clean `v6` rerun tightened the local interpretation of Beta 1 from a packaging milestone to a production-grade claim that must clear the canonical 5x3 matrix with 15 of 15 clean outcomes
- prompt hardening and targeted reruns cleared the previously degraded cells on the same scenario and provider pairs
- the fresh canonical `v7` rerun then closed with 15 of 15 clean outcomes across OpenAI, Anthropic, and Ollama
- the remaining local validation stack then also re-cleared after isolating `OLLAMA_HOST` leakage in config and provider tests
- GitHub Actions run `#450` on commit `cd82118` then closed green with 8 of 8 jobs successful, fully satisfying the Phase 15 exit gate
- the active local plan phase moved from 15 to 16, shifting the next work from validation closure to canary-readiness material

## Local operational milestone on 2026-04-13

- the published `v1.0.13a6` canary on `f99a38d` progressed cleanly through the run-100 checkpoint, and the repository-owned evidence packet was refreshed and checkpointed on `bc2f8c6`
- the operational reading after run 100 became time-based rather than traffic-based: the remaining blocker for the canary window is the 7-day minimum observation period, not more same-day workflows
- a newer-head practical OpenAI plus Ollama rerun then exposed contradictions, motivating a full chain of fixes through v28 (10/10 GREEN)
- the composite acceptance model (productivity + real-workflow + safety) was implemented in both the empirical runner and the orchestrator acceptance path

## Local operational milestone on 2026-04-15

### v29 canonical 5×3 rerun

- first canonical 5×3 including Anthropic: 9/15 GREEN (Ollama 5/5, OpenAI 3/5+2 RED, Anthropic 1/5+3 DEGRADED+1 RED)
- discovered OpenAI regression: gpt-4o-mini generating `details='details'` (string) instead of dict in test fixtures
- discovered Anthropic DEGRADED pattern: `validate_request()` returns `(False, errors)` tuples; validator treated as truthy

### v30 fixture contract and validator fixes

- added `_test_fixture_contract_block()` to prevent string-valued details in test fixtures
- added `_coerce_validation_bool()` to handle tuple, dict, and bool returns from `validate_request()`
- v30 result: 11/15 GREEN (OpenAI 5/5 recovered, Ollama 5/5 stable, Anthropic 1/5+4 DEGRADED)

### v31-v31b infrastructure fixes

- expanded contract bullets for Anthropic-specific patterns
- fixed infinite resume loop (PROVIDER_TRANSIENT not in REPAIRABLE_FAILURE_CATEGORIES)
- rejected non-dict details in contract anchor and scenario bullets
- 4 commits pushed: `235d58b`, `197f4b8`, `1fbeafa`, `829adc4`

## Local operational milestone on 2026-04-16

## Local operational milestone on 2026-04-18

- the orchestrator refactor continued in disciplined slice mode with `validation_runtime`, `task_constraints`, `workflow_control`, `validation_analysis`, and now `sandbox_execution` extracted into `kycortex_agents/orchestration/`
- the sandbox execution slice moved generated import/test subprocess orchestration, generated runner-file writing, and sandbox-security classification out of `Orchestrator` while keeping wrapper methods stable
- focused direct support tests, focused orchestrator sandbox regressions, and `mypy` all re-cleared on the extracted slice
- the validation reporting slice then moved completion diagnostics, truncation heuristics, and code/test validation summary rendering into `kycortex_agents/orchestration/validation_reporting.py`
- focused direct support tests, focused orchestrator validation-summary regressions, `mypy`, and `ruff` all re-cleared on that slice
- the repair-instruction slice then moved deterministic repair-instruction composition for validation and test-failure paths into `kycortex_agents/orchestration/repair_instructions.py`
- focused direct support tests, focused orchestrator repair-instruction regressions, `mypy`, and `ruff` all re-cleared on that slice
- the repair-analysis slice then moved deterministic regex/AST repair detectors, missing-import detection, constructor strictness analysis, duplicate-constructor rewrite hints, nested-wrapper validation detection, and invalid-path audit-trail detection into `kycortex_agents/orchestration/repair_analysis.py`
- focused direct support tests, focused orchestrator repair-analysis regressions, `mypy`, and `ruff` all re-cleared on that slice
- the repair-signal slice then moved deterministic datetime-import and required-evidence reuse heuristics into `kycortex_agents/orchestration/repair_signals.py`
- focused direct support tests, focused orchestrator repair-signal regressions, `mypy`, and `ruff` all re-cleared on that slice
- the repair-test-analysis slice then moved validation-summary symbol parsing, helper-alias drift detection, reusable missing-import discovery, and previous-valid-test-surface AST analysis into `kycortex_agents/orchestration/repair_test_analysis.py`
- focused direct support tests, focused orchestrator repair-focus regressions, `mypy`, and `ruff` all re-cleared on that slice
- the runtime-only repair-priorities slice then moved deterministic pytest-runtime assertion-overreach guidance and failure-shape repair heuristics into `kycortex_agents/orchestration/repair_test_runtime.py`
- focused direct support tests, focused orchestrator runtime-repair regressions, `mypy`, and `ruff` all re-cleared on that slice
- the structural repair-priorities slice then moved deterministic helper-surface cleanup, budget guidance, assertionless-test repair, import hygiene, truncation, constructor-arity, payload-contract, and fixture-shape priorities into `kycortex_agents/orchestration/repair_test_structure.py`
- focused direct support tests, focused orchestrator structural-repair regressions, `mypy`, and `ruff` all re-cleared on that slice
- the code-validation repair-priorities slice then moved deterministic public-contract, pytest-failure, duplicate-constructor, attribute-alignment, dataclass-order, import-hygiene, truncation, object-semantics, and timezone-comparison guidance into `kycortex_agents/orchestration/repair_code_validation.py`
- focused direct support tests, focused orchestrator code-repair regressions, targeted `mypy`, and `ruff` all re-cleared on that slice
- the test-validation composition slice then moved type-mismatch priority injection, repair-surface analysis, helper-surface fallback normalization, assertionless-test parsing, and structural/runtime repair-priority composition into `kycortex_agents/orchestration/repair_test_validation.py`
- focused direct support tests, focused orchestrator repair-focus regressions, targeted `mypy`, and `ruff` all re-cleared on that slice
- the repair-focus dispatch slice then moved shared signal/detail collection and category dispatch for `_repair_focus_lines(...)` into `kycortex_agents/orchestration/repair_focus.py`
- focused direct support tests, focused orchestrator repair-focus regressions, targeted `mypy`, and `ruff` all re-cleared on that slice


## Local operational milestone on 2026-04-18 - Refactor mode reset and first low-risk slices
- focused validation re-cleared again after the validation-runtime slice, including direct support tests plus orchestrator regressions for pytest-summary handling and provider-call metadata redaction
- `kycortex_agents/orchestrator.py` now delegates the artifact persistence path to internal support code while preserving private wrapper methods so direct tests and external behaviour do not drift during the refactor
- the next low-risk slice then extracted the sandbox bootstrap templates and AST name-replacement helper into internal orchestration modules, removing the embedded sandbox template payloads from `kycortex_agents/orchestrator.py`
- the orchestrator now renders `sitecustomize.py`, the generated pytest runner, and the generated import runner through internal support functions, reducing one of the largest static infrastructure blocks left in the file
- a third low-risk slice then extracted the generated-test sandbox runtime bootstrap into internal orchestration support, moving environment scrubbing, sandbox home/XDG binding, generated filename sanitization, secret-env detection, and `preexec_fn` limit construction out of `kycortex_agents/orchestrator.py`
- a fourth low-risk slice then extracted validation-runtime helpers into internal orchestration support, moving pytest-output summarization, validation-result redaction, output metadata sanitization, and provider-call metadata lookup out of `kycortex_agents/orchestrator.py`
- focused validation re-cleared on the refactor branch for release metadata, package metadata, public API, orchestration support, and orchestrator artifact persistence helpers
- focused validation also re-cleared after the sandbox-template slice, including support-level tests plus representative orchestrator regressions for import-time validation and sandbox enforcement
- focused validation re-cleared again after the sandbox-runtime slice, including direct support tests plus orchestrator regressions for environment bootstrap, restrictive umask and resource limits, and generated filename handling
- focused validation re-cleared again after the validation-runtime slice, including direct support tests plus orchestrator regressions for pytest-summary handling and provider-call metadata redaction
- a fifth low-risk slice then extracted task constraint parsing and architecture-context compaction into internal orchestration support, moving line-budget parsing, CLI-entrypoint detection, top-level test and fixture limits, and low-budget or repair-focused architecture summarization out of `kycortex_agents/orchestrator.py`
- focused validation re-cleared again after the task-constraint slice, including direct support tests plus orchestrator regressions for line budgets, test-count and fixture budgets, and compact architecture context shaping

## Local operational milestone on 2026-04-19

- the orchestrator refactor continued in disciplined slice mode with the remaining façade wrappers and small helper clusters retired or extracted one at a time
- `_repair_focus_lines(...)`, `_build_test_validation_summary(...)`, and `_build_code_validation_summary(...)` were fully retired from `Orchestrator`, with production and regression anchors moved directly to internal orchestration helpers
- dependency validation summary rendering, output summarization, semantic output-key classification, agent-result normalization, agent-resolution validation, and workflow acceptance evaluation were extracted into dedicated internal orchestration modules
- the next micro-slice then extracted AST name rendering and pytest-fixture detection into `kycortex_agents/orchestration/ast_tools.py`, retiring `_ast_name(...)` and `_is_pytest_fixture(...)` from `Orchestrator`
- focused support tests, focused orchestrator regressions, targeted `mypy`, and targeted `ruff` all re-cleared on the AST-helper slice
- the next micro-slice then extracted agent execution dispatch into `kycortex_agents/orchestration/agent_runtime.py`, retiring `_execute_agent(...)` from `Orchestrator`
- the `execute_agent(...)` slice re-cleared with direct support coverage plus targeted `mypy` and `ruff`
- the next micro-slice then extracted agent-input assembly into `kycortex_agents/orchestration/agent_runtime.py`, reducing `_build_agent_input(...)` to a thin wrapper while preserving the large set of façade regression anchors
- focused support tests, focused wrapper regressions, targeted `mypy`, and targeted `ruff` all re-cleared on the `build_agent_input(...)` slice
- the next micro-slice then extracted small AST-expression helpers into `kycortex_agents/orchestration/ast_tools.py`, retiring `_callable_name(...)`, `_attribute_chain(...)`, `_expression_root_name(...)`, `_render_expression(...)`, and `_first_call_argument(...)` from `Orchestrator`
- focused support coverage, a focused orchestrator regression, targeted `mypy`, and targeted `ruff` all re-cleared on the AST-expression slice
- the follow-up CI remediation then fixed the failing GitHub Actions `mypy` job by excluding generated build artifacts from static analysis and correcting the remaining stale `callable_name` references that the full repository typecheck exposed
- the exact CI-equivalent checks re-cleared locally with `python -m mypy`, `python -m ruff check .`, and focused orchestrator regressions
- a sixth low-risk slice then extracted workflow-control and safe-log helpers into internal orchestration support, moving workflow pause, resume, cancel, skip, override, replay, progress emission, and task-id count minimization out of `kycortex_agents/orchestrator.py`
- focused validation re-cleared again after the workflow-control slice, including direct support tests plus orchestrator regressions for log minimization, operator control-surface redaction, resume flow, and workflow event audit behaviour
- a seventh low-risk slice then extracted validation-analysis helpers into internal orchestration support, moving pytest-failure parsing, failure-origin inspection, semantic assertion mismatch checks, contract-overreach signals, and warning-vs-blocking test-validation classification out of `kycortex_agents/orchestrator.py`
- focused validation re-cleared again after the validation-analysis slice, including direct support tests, focused orchestrator regressions for pytest-failure parsing and warning arbitration, and `mypy` to keep the CI type-check green

Recommended next steps:

- continue with the next low-risk sandbox/path-policy extraction before touching subprocess execution ownership
- continue with the next low-risk deterministic extraction now that the first validation-runtime helper cluster has been offloaded
- keep updating `.local-docs/` and creating a repository commit after each completed refactor slice so the operational trail stays truthful and reviewable
- continue with the next low-risk deterministic extraction now that task constraints and architecture-context compaction are also offloaded
- continue with the next low-risk deterministic extraction now that workflow-control and safe-log helpers are also offloaded
- continue with the next low-risk deterministic extraction now that validation-analysis helpers are also offloaded

### Ollama model exploration

- established multi-port Ollama setup: port 11434 (v0.20.5), port 11435 (v0.20.7 GPU), port 11436 (v0.20.7 CPU-only)
- added `ollama_think` parameter support across config, provider_matrix, ollama_provider, and matrix runner
- v35b: qwen2.5-coder:14b CPU = 5/5 GREEN (gold standard confirmed)
- v39: qwen2.5-coder:14b CPU on Ollama 0.20.7 = 5/5 GREEN (confirmed across versions)
- v36/v37c: qwen3.5:9b GPU = 1/5 and 3/5 GREEN (inconsistent)
- v38: qwen2.5-coder:14b GPU partial offload = 2/5 GREEN (offload degrades quality)
- v40: qwen3-coder:30b MoE = 0/3 GREEN (too weak despite 24.5 tok/s)
- RTX 4060 Ti 8GB VRAM insufficient for full qwen2.5-coder:14b offload

### gpt-4.1-mini test (v41)

- v41: gpt-4.1-mini = 1/5 GREEN (only insurance passed)
- critical finding: both KYC and insurance had identical `details='details'` bug; insurance passed because code is lenient, KYC failed because code is strict
- model sensitivity conclusively confirmed: gpt-4o-mini 5/5 → gpt-4.1-mini 1/5

## Local operational milestone on 2026-04-17

### Root-cause investigation and remediation plan

- deep investigation of orchestrator.py code-to-test pipeline: `_code_artifact_context()`, `_build_code_behavior_contract()`, `_build_code_exact_test_contract()`, `_build_code_test_targets()`, and repair mechanisms
- root cause identified: behavior contract extracts field NAMES but not TYPE CONSTRAINTS from generated code; models guess fixture types differently
- repair cycles proven unable to fix type mismatches: validation summary has no category for "test passes string where code expects dict"
- QA tester prompt over-specification: 1000+ lines with 50+ NEVER/MUST rules but concrete fixture types unspecified
- remediation plan approved: 3-phase structural fix (type-aware behavior contract, QA prompt adjustment, type-aware repair diagnostics)
- validation target: 3 models × 5 scenarios = 15 runs

Reading:

- the project shifted from provider-specific prompt hardening to a structural fix for the code-to-test information bridge
- this is the first time the framework's model sensitivity has been traced to a specific architectural gap rather than to prompt quality

## Local operational milestone on 2026-04-18

- the development branch stopped being treated as a publishable continuation of the `15/15` baseline and entered explicit refactor-engineering mode
- the trusted published baseline remained `v1.0.13a6`; the branch version moved forward as `1.0.13a10.dev0` to mark deep in-progress work rather than a releasable maintenance line
- the operational interpretation of the current work changed from canary continuation to architecture reset: the branch will no longer spend budget on repeated canonical reruns until deterministic validation gates are rebuilt
- the orchestrator was reclassified operationally as a God object that must be slimmed by extracting deterministic responsibilities such as private-file hardening, analysis services, validation logic, repair policy, and context building
- the new near-term plan became: truth-reset the docs, preserve the public runtime/workflows API where possible, extract low-risk deterministic infrastructure first, then requalify empirically only after the refactor stabilizes

Reading:

- the problem is no longer understood as isolated provider drift; it is understood as architectural over-coupling plus late validation feedback
- the repository's sandbox, persistence, and auditability line remains worth preserving, while the orchestration and validation layer requires deep internal restructuring

## Release line from the changelog

### 1.0.0 - 2026-03-25

- stabilized public baseline
- CI, release automation, docs, and examples ready
- direct changelog note: `Phase 13 release-readiness work is complete`

### 1.0.1 through 1.0.7 - 2026-03-25

- cross-provider hardening
- workflow outcomes and acceptance policy
- repair budgets
- repair routing
- corrective task lineage

### 1.0.8 through 1.0.10 - 2026-03-25

- provider matrix validation
- structured workflow summaries
- Python 3.10 compatibility and parser fixes
- Ollama fallback hardening

### 1.0.11 - 2026-03-30

- `ollama_num_ctx`
- richer validation budgets
- provider health snapshots
- workflow telemetry and resource telemetry
- larger empirical validation baseline

### 1.0.12 - 2026-03-30

- code and test guidance hardening against artificial behavior and incorrect score logic
- clean-environment CI repair

### 1.0.13a1 - 2026-03-30

- live release smoke example
- stronger compact-budget guidance
- published alpha release baseline

### 1.0.13a2 - in preparation

- four-view boundary model
- `ProjectState.internal_runtime_telemetry()`
- formal go-live policy
- release artifact manifest and promotion summary
- published release asset verification
- breaking removal of exact telemetry from the public surface

## Consolidated historical reading

The product evolved in three major movements:

1. build the orchestration and persistence framework
2. harden validation, repair, and isolated execution
3. separate public and internal surfaces rigorously and prepare the alpha line for Beta 1

## Important note about lost local history

The old `.local-docs/` files are not in Git.

Because of that:

- the history above recovers what is demonstrable from the repository
- the local planning and operational-state history is now being rebuilt in this folder

## 2026-04-19 - Repair-focus wrapper retirement

- after the `repair_focus.py` extraction cleared CI, the next minimal deterministic slice retired the `_repair_focus_lines(...)` compatibility wrapper from `Orchestrator`
- production assembly in `_build_agent_input(...)` now calls `build_repair_focus_lines(...)` directly
- the direct orchestrator regressions that previously anchored the wrapper were migrated to the extracted builder
- focused pytest coverage, `mypy`, and `ruff` stayed green on the slice
- the next natural target is `_build_test_validation_summary(...)`, which remains as the most obvious thin forwarding wrapper in `Orchestrator`

## 2026-04-19 - Test-validation summary wrapper retirement

- the next minimal deterministic slice retired the `_build_test_validation_summary(...)` compatibility wrapper from `Orchestrator`
- production validation-summary assembly now calls `build_test_validation_summary(...)` directly in the test-validation failure path and in test-artifact context assembly
- direct orchestrator regressions that previously anchored the wrapper were migrated to the extracted builder
- focused pytest coverage, `mypy`, and `ruff` stayed green on the slice
- the next natural target is the next smallest façade shim or helper cluster still forwarding into extracted orchestration support

## 2026-04-19 - Code-validation summary wrapper retirement

- the next minimal deterministic slice retired the `_build_code_validation_summary(...)` compatibility wrapper from `Orchestrator`
- production validation-summary assembly now calls `build_code_validation_summary(...)` directly in the code-validation failure path
- direct orchestrator regressions that previously anchored the wrapper were migrated to the extracted builder
- focused pytest coverage, `mypy`, and `ruff` stayed green on the slice
- the next natural target remains the next smallest façade shim or helper cluster still forwarding into extracted orchestration support

## 2026-04-19 - Dependency validation summary extraction

- the next minimal deterministic slice moved dependency validation summary rendering into `kycortex_agents/orchestration/validation_reporting.py`
- production dependency-validation summary assembly now calls `build_dependency_validation_summary(...)` directly in failure-summary assembly and dependency-artifact context assembly
- the former `_build_dependency_validation_summary(...)` method was removed from `Orchestrator`
- focused pytest coverage, `mypy`, and `ruff` stayed green on the slice
- the next natural target remains the next smallest façade shim or helper cluster still forwarding into extracted orchestration support

## 2026-04-19 - Output helper extraction

- the next minimal deterministic slice moved output summarization and semantic output-key classification into `kycortex_agents/orchestration/output_helpers.py`
- production call sites now use `summarize_output(...)` and `semantic_output_key(...)` directly for finalized test summaries, semantic context keys, normalized agent results, and code summaries
- the former `_summarize_output(...)` and `_semantic_output_key(...)` methods were removed from `Orchestrator`
- focused pytest coverage, `mypy`, and `ruff` stayed green on the slice
- the next natural target remains the next smallest façade shim or helper cluster still forwarding into extracted orchestration support

## 2026-04-19 - Agent-result normalization extraction

- the next minimal deterministic slice moved agent-result normalization and unredacted-output recovery into `kycortex_agents/orchestration/output_helpers.py`
- production task execution now uses `normalize_agent_result(...)` and `unredacted_agent_result(...)` directly before metadata sanitization and output validation
- the former `_normalize_agent_result(...)` and `_unredacted_agent_result(...)` methods were removed from `Orchestrator`
- focused pytest coverage, `mypy`, and `ruff` stayed green on the slice
- the next natural target remains the next smallest façade shim or helper cluster still forwarding into extracted orchestration support

## 2026-04-19 - Agent-resolution validation extraction

- the next minimal deterministic slice moved agent-resolution validation into `kycortex_agents/orchestration/workflow_control.py`
- workflow execution now calls `validate_agent_resolution(...)` directly before planning the run
- the former `_validate_agent_resolution(...)` method was removed from `Orchestrator`
- focused pytest coverage, `mypy`, and `ruff` stayed green on the slice
- the next natural target is the remaining acceptance-evaluation cluster, which may or may not still be small enough for another deterministic slice

## 2026-04-19 - Workflow acceptance extraction

- the next deterministic slice moved task acceptance lists, observed failure-category aggregation, and workflow acceptance evaluation into `kycortex_agents/orchestration/workflow_acceptance.py`
- workflow completion and failure paths now call `evaluate_workflow_acceptance(...)` directly
- the former `_task_acceptance_lists(...)`, `_observed_failure_categories(...)`, and `_evaluate_workflow_acceptance(...)` methods were removed from `Orchestrator`
- focused support tests, focused orchestrator regressions, `mypy`, and `ruff` stayed green on the slice
- the next natural target is to remap the reduced `Orchestrator` and pick the next smallest deterministic helper cluster
