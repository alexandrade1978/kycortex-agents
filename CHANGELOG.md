# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally lightweight for the active 1.0 line. Entries group changes by milestone so release history stays visible directly in the repository.

## Unreleased

### Added

- Documented the four-view boundary model for the active runtime/public split: internal persisted workflow state, `ProjectSnapshot`, `AgentView`, and internal runtime telemetry.
- Added a dedicated `ProjectState.internal_runtime_telemetry()` read path for exact operator-facing runtime telemetry after moving exact workflow and per-task runtime telemetry off the public snapshot path.

### Changed

- Tagged and manual GitHub release automation now runs the repository-owned `scripts/release_check.py` gate before building distribution artifacts, keeping workflow promotion aligned with the documented release metadata, coverage, packaging, and full-suite policy.
- Tagged GitHub release automation now smoke-validates the exact staged wheel and source distribution before generating release promotion metadata or publishing artifacts.
- Tagged GitHub release automation now generates and verifies `release-artifact-manifest.json` before publication, attaching the verified manifest alongside the promoted wheel and source distribution.
- Tagged GitHub release automation now writes `release-promotion-summary.json`, binding the verified manifest, pushed tag, commit SHA, and promoted artifact set into a repository-owned provenance packet before publication.
- Tagged GitHub release automation now runs `scripts/release_published_assets_check.py` after publication, downloading the GitHub release assets to verify the exact attached asset set and prove the published wheel and source distribution still match the attached manifest checksums.
- Tagged GitHub release automation now forces JavaScript-based GitHub Actions steps onto Node 24 through `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`, preventing runner deprecation warnings for artifact upload, artifact download, and GitHub release publication.
- Repository docs now describe prompt-facing context as filtered `AgentView` data instead of raw `ProjectSnapshot` serialization.
- Repository docs now point operator-facing observability to `ProjectState.internal_runtime_telemetry()` and describe the public snapshot, public execution-event, and provider-matrix telemetry removals as completed local behavior.
- Prompt-facing completed-task outputs, semantic aliases, and planned-module hints are now scoped to the active task dependency closure instead of leaking unrelated finished-task context.
- Public snapshots now expose `has_updated_at` instead of the exact top-level `updated_at` timestamp while preserving the internal exact update timestamp.
- Public snapshots now expose `has_started_at` and `has_finished_at` instead of the exact top-level workflow `started_at` and `finished_at` timestamps while preserving the exact public workflow event timestamps.
- Public snapshots no longer duplicate top-level `repair_cycle_count`, relying on the retained public `repair_history` contract for repair-lineage visibility instead.
- Public `workflow_finished` snapshot events now expose `has_workflow_duration` instead of the exact public `workflow_duration_ms` value while preserving the internal exact event duration and the rest of the minimized public event contract.
- Public `workflow_telemetry.provider_health_summary` now exposes `has_models` instead of exact provider model-name lists while preserving the exact internal provider-health telemetry.
- Public `workflow_telemetry` aggregate `usage` maps now expose presence-by-key instead of exact numeric values while preserving exact task-level provider usage and the internal exact workflow telemetry.
- Public `TaskResourceTelemetry.usage` now exposes presence-by-key instead of exact numeric values while preserving exact provider-call metadata and the internal exact task runtime telemetry.
- Public `TaskResult.details` now exposes `has_error_category` instead of the exact `last_error_category` string while preserving canonical failure categories through `FailureRecord.category`.
- Public `repair_history` entries and public `workflow_repair_cycle_started` snapshot-event details now expose `has_failure_category` instead of exact per-cycle `failure_category` values while preserving exact internal repair telemetry.
- Public `workflow_finished` snapshot events no longer duplicate top-level `acceptance_policy`, `terminal_outcome`, `failure_category`, or `acceptance_criteria_met`, relying on the canonical nested public `acceptance_evaluation` summary instead.
- Public snapshots no longer duplicate top-level `acceptance_criteria_met`, and `AgentView` now derives that prompt-facing boolean from the canonical public `acceptance_evaluation.accepted` field instead.
- Public snapshots no longer duplicate top-level `acceptance_policy`, `terminal_outcome`, or `failure_category` fields, and `AgentView` now derives those prompt-facing values from the canonical public `acceptance_evaluation` summary.
- Public snapshots now expose `has_last_resumed_at` instead of the exact top-level `last_resumed_at` timestamp while preserving `started_at`, `finished_at`, and the internal exact resume state.
- Public workflow resume summaries now expose `has_last_resumed_at` instead of the exact public `last_resumed_at` timestamp while preserving the existing resume event, reason, and task multiplicity signals.
- Public workflow acceptance summaries and public `workflow_finished` acceptance-evaluation details now expose `has_reason` instead of exact public `reason` strings while preserving policy, accepted, terminal outcome, failure category, and the existing task-presence flags.
- Public `repair_history` entries and public `workflow_repair_cycle_started` execution-event details now expose `has_reason` instead of exact public `reason` strings while preserving `cycle`, `failure_category`, and the existing failed-task/budget presence signals.
- Public operator/control execution events now expose `has_reason` instead of exact public `reason` strings for `workflow_paused`, `workflow_resumed`, `workflow_cancelled`, `workflow_replayed`, `task_cancelled`, and `task_overridden`.
- Public `task_repair_planned` execution-event details now align with the minimized public `TaskResult.details.repair_context` contract, replacing exact repair-planning instruction, owner, helper-surface, failed-artifact, failed-output, validation-summary, and existing-test payloads with coarse presence flags.
- Public `task_repair_planned` execution-event details now expose `has_failure_message` and `has_failure_error_type` instead of the exact failure message and failure error type.
- Breaking change note: the active boundary split has removed public `ProjectSnapshot.workflow_telemetry`, public `TaskResult.resource_telemetry`, and the remaining public telemetry echoes with no deprecation bridge.
- Public `repair_history` entries now expose `has_started_at` instead of the exact `started_at` timestamp while public `workflow_repair_cycle_started` event details continue to rely on the event's top-level `timestamp`.

### Fixed

- Repository docs no longer advertise full normalized snapshots, public snapshot telemetry, or provider-matrix telemetry as stable prompt-facing or public observability behavior.
- Completed a repository documentation consistency sweep so `README.md` and `docs/README.md` now anchor the same four-view boundary model and direct exact observability readers to `ProjectState.internal_runtime_telemetry()` instead of stale compatibility-telemetry wording.

### Release Readiness Notes

- Current package version is now `1.0.13a2` ahead of the next alpha release.
- Latest released alpha remains `1.0.13a1` until `v1.0.13a2` is tagged.
- The unreleased boundary split now contains an explicit breaking public-telemetry removal in the local workspace.
- The unreleased release-hardening stream now includes repository-owned post-publish GitHub release asset checksum verification.

## 1.0.13a1 - 2026-03-30

### Added

- Added `examples/example_release_user_smoke.py`, a user-style live smoke example that generates a small project through the public API and validates the generated Python artifact with a real sample call.

### Changed

- Package metadata, release docs, and GitHub release automation now treat the public line as an alpha pre-release stream using PEP 440 package versions and GitHub prereleases for alpha, beta, and release-candidate tags.
- Provider-matrix code-generation guidance now requires visible line-budget headroom during compact module generation and repair instead of merely aiming near the hard ceiling.
- Provider-matrix QA guidance, repair priorities, and task descriptions now require leaving explicit test-budget headroom, counting top-level tests and total lines before finalizing, and cutting helper-only coverage before required workflow scenarios.
- Compact high-level workflow suites now explicitly avoid spending scarce top-level tests on validator, scorer, dataclass-serialization, and audit-logger helper coverage unless those helpers are requested directly.
- README and docs navigation now point directly to the new live smoke example for repository visitors who want a realistic local validation path.

### Fixed

- The post-`1.0.12` Anthropic provider-matrix checkpoint no longer fails the workflow on over-budget code and test outputs after compactness repair guidance was tightened for both generation and repair paths.
- Verified that the released `v1.0.12` package can still be installed into a clean virtual environment and execute a real Ollama-backed project-creation workflow successfully.

### Validation Notes

- Focused prompt/provider-matrix/orchestrator regressions passed with `366` tests, `mypy` passed, and the dedicated empirical rerun `output/provider_matrix_validation_step3u_anthropic` completed with `repair_cycle_count=1` after the earlier `step3t` Anthropic workflow failure.
- The live local smoke run `output/release_user_smoke_ollama_live` completed on `qwen2.5-coder:7b` via `http://127.0.0.1:11435` with `repair_cycle_count=0`, and the generated artifact validated successfully with a sample balance of `2650.00`.
- A clean-install smoke of the released `v1.0.12` package also completed against the same Ollama runtime from a temporary virtual environment and produced a valid generated artifact exposing `calculate_budget_balance()` plus `main()`.

### Release Readiness Notes

- Version `1.0.13a1` is now the released alpha package baseline.

## 1.0.12 - 2026-03-30

### Changed

- Provider-matrix code-generation guidance now explicitly rejects constant-success validators, placeholder constant scores, and hidden score caps unless the behavior contract requires them.
- Provider-matrix QA guidance and task descriptions now require staying comfortably under fixture budgets and avoiding exact categorical score assertions at threshold boundaries unless the contract defines those cutoffs.
- Provider-matrix code-generation guidance now also requires boolean and toggle-like fields to influence behavior by their truth value rather than by mere key presence unless the contract explicitly defines presence-only semantics.

### Fixed

- The provider-matrix budget regression test no longer depends on an ambient `OPENAI_API_KEY` in the developer shell and now injects its own fake credential explicitly, keeping clean-environment GitHub runners aligned with local validation.
- GitHub Actions `Coverage Gate` and tagged release validation are green again on a clean runner after removing the hidden credential dependency from the regression suite.

### Validation Notes

- Focused prompt and provider-matrix regressions passed with `44` tests after the guidance hardening.
- The focused empirical rerun `output/provider_matrix_validation_step3q` completed for OpenAI and Ollama, improving Ollama from `repair_cycle_count=1` in `step3o` to `repair_cycle_count=0` while leaving a single residual OpenAI repair tied to code-side boolean-flag truthiness during batch scoring.
- The focused empirical rerun `output/provider_matrix_validation_step3r_openai` completed with `repair_cycle_count=0`, closing the remaining residual OpenAI repair from `step3q`.
- The exact clean-environment coverage-gate command passed locally with `849 passed` and `97.96%` coverage before the `v1.0.12` release tag was created.

### Release Readiness Notes

- Version `1.0.12` is now the released package baseline.

## 1.0.11 - 2026-03-30

### Added

- Explicit `ollama_num_ctx` runtime configuration together with provider-matrix CLI overrides for dedicated Ollama base URLs and context windows during empirical validation runs.
- Generated-test validation now flags reserved fixture names, unsupported mock-style assertion bookkeeping on real objects, and CLI-wrapper imports as deterministic QA failures.
- Code-repair flows now receive the failing pytest module as concrete `existing_tests` context so repairs can target the exact fixtures, inputs, and assertions that exposed the regression.
- Completion-aware output diagnostics that combine provider token-limit metadata with structural EOF heuristics and feed those signals into persisted repair summaries for generated code and tests.
- Task-derived validation budgets for generated outputs, including optional line limits, required CLI entrypoints, exact or maximum top-level test counts, fixture budgets, undefined local-name checks, and richer call-arity validation.
- Model-readiness health snapshots for OpenAI, Anthropic, and Ollama providers, exposing `backend_reachable` and `model_ready` alongside the existing provider-health states.
- Explicit wall-clock limits in the execution sandbox policy so generated pytest runs can enforce a timeout independent from CPU budgeting.
- Artifact-persistence guards that reject writes resolving outside `output_dir`, including symlink-based output-path escapes.
- Active preflight health checks for OpenAI and Anthropic providers, including transient-vs-deterministic classification aligned with generation-time provider failures.
- Provider-health cooldown caching so repeated unhealthy readiness probes can reuse a recent degraded/failing snapshot instead of repeatedly probing the same backend.
- Persisted provider-budget summaries in task failures, task details, provider-matrix summaries, and workflow inspection paths.
- Workflow-level aggregate `workflow_telemetry` summaries in `ProjectSnapshot`, terminal `workflow_finished` execution events, and final structured orchestrator logs.
- Operational workflow telemetry rollups for acceptance outcomes, workflow resume activity, and repair-cycle usage inside the aggregate `workflow_telemetry` summary.
- Provider-matrix structured workflow summaries now embed the same aggregate `workflow_telemetry` payload exposed by `ProjectSnapshot`.
- Explicit public telemetry typed contracts in `kycortex_agents.types`, including `WorkflowTelemetry` and its nested workflow acceptance, resume, repair, fallback, error, provider, and metric summary shapes.
- Workflow repair telemetry summaries now expose aggregated repair trigger reasons and the last observed repair trigger through `workflow_telemetry["repair_summary"]`.
- `TaskResult` snapshots now expose typed per-task `resource_telemetry` summaries covering normalized task timing plus provider duration and usage metadata.
- Active workflows now emit incremental `workflow_progress` execution events and structured logs carrying the current aggregate `workflow_telemetry` payload during execution, not only at terminal workflow completion.
- Aggregate `workflow_telemetry` now includes a typed `progress_summary` with explicit pending, runnable, blocked, terminal, and completion-percentage progress signals.
- Aggregate `workflow_telemetry` now includes `provider_health_summary`, rolling up persisted provider health snapshots such as healthy, degraded, failing, and open-circuit states across workflow execution.

### Changed

- The validated local Ollama baseline across docs, examples, provider-matrix defaults, and empirical validation now uses `qwen2.5-coder:7b` with `ollama_num_ctx=16384`.
- QA repair prompts now repair the existing pytest file in place, preserve only contract-valid structure, and explicitly drop guessed helper-constructor wiring when constructor mismatches are reported.
- Code-repair prompts now treat cited pytest assertions as exact behavior contracts and keep explicit repair headroom under line-constrained task budgets.
- `BaseAgent` now performs provider preflight health checks before generation attempts, routes unhealthy providers into fail-fast or fallback behavior, and exposes the latest structured health snapshot per provider in provider metadata.
- `BaseAgent` now preserves compatibility with injected legacy providers that do not implement `health_check()` by recording a passive ready snapshot instead of failing before generation.
- Provider and workflow runtime documentation plus snapshot-inspection examples now describe the current resilience and observability behavior, including cooldown caching, fallback metadata, workflow-level aggregate telemetry, and the new acceptance/resume/repair rollups.
- `examples/example_snapshot_inspection.py` now prints the explicit workflow `progress_summary` and `provider_health_summary` views so the Phase 10 observability surface is demonstrated directly instead of only through the raw aggregate telemetry dictionary.
- `KYCortexConfig` no longer creates `output_dir` during initialization; artifact and validation writes now create the directory lazily at first use.
- Provider metadata now preserves requested completion budgets and backend-specific stop signals such as OpenAI `finish_reason`, Anthropic `stop_reason`, and Ollama `done_reason`.
- Provider-matrix validation now uses larger generation budgets together with tighter code and test task constraints so repair cycles target truncation and scope drift more deterministically.
- QA repair guidance now keeps validation failures on direct intake surfaces by default, keeps batch scenarios structurally valid unless the contract requires mixed-validity behavior, and avoids speculative logging assertions unless log output is explicitly observable.

### Fixed

- Test-failure repair routing now chains code repair whenever pytest tracebacks point into generated code, even if the same suite also reports static QA issues, instead of spending the repair budget only on test regeneration.
- Provider-matrix stabilization now completes on the strongest current checkpoint for all supported providers, with dedicated Anthropic and Ollama reruns also converging without repair cycles after the latest repair-routing hardening.
- Transient-provider classification now treats timeout and connection failures as retryable without incorrectly classifying arbitrary unknown exception objects as transient.
- Provider-health cooldown caching is now keyed by credential identity so unhealthy snapshots are not reused across different API keys for the same provider/model tuple.
- OpenAI and Anthropic health probes now fail deterministically when the configured model is not present in the provider model listing instead of treating backend reachability alone as success.
- Ollama health probes now validate both `/api/tags` reachability and model availability, surfacing a deterministic failure when the configured local model is not installed.
- Empirical cloud-provider full-workflow validation recovered the current strongest baseline: OpenAI completed at the latest checkpoint with zero repair cycles, Anthropic completed after one repair cycle, and Ollama remains contingent on local runtime reachability.

### Release Readiness Notes

- Version `1.0.11` is now the released package baseline.
- The latest empirical matrix checkpoint `output/provider_matrix_validation_step3o` completed for Anthropic, Ollama, and OpenAI, and the dedicated reruns `output/provider_matrix_validation_step3n_anthropic` plus `output/provider_matrix_validation_step3n_ollama` both completed with `repair_cycle_count=0`.

## 1.0.10 - 2026-03-25

### Fixed

- Fixed Python 3.10 compatibility for `examples/example_provider_matrix_validation.py` by removing the positional `argparse` `choices` dependency that rejected an empty provider list during `parse_args([])`.
- Added explicit post-parse provider normalization and validation through `resolve_requested_providers()` so the CLI still defaults to all supported providers and reports unsupported providers with a clear error.
- Added regression coverage for the default-provider path and unsupported-provider rejection in the provider-matrix example CLI.

### Release Readiness Notes

- Version `1.0.10` is now the released package baseline.

## 1.0.9 - 2026-03-25

### Fixed

- Hardened Ollama model-resolution fallback so raw socket and connection failures now fall back to the default model just like `URLError`-wrapped probe failures.
- Fixed provider-availability environment selection so an explicitly supplied empty environment mapping is respected instead of silently falling back to the process environment.
- Added regression coverage for raw `OSError` probe failures and explicit empty-environment availability checks.

### Release Readiness Notes

- Version `1.0.9` is now the previous package baseline.
- `Release #11` for `v1.0.9` succeeded, but `CI #23` still failed in `Full Test Suite (3.10)` before the Python 3.10 parser compatibility fix shipped.

## 1.0.8 - 2026-03-25

### Added

- A new internal provider-matrix validation helper module plus `examples/example_provider_matrix_validation.py` for reproducible empirical full-workflow reruns across OpenAI, Anthropic, and Ollama.
- Structured JSON workflow summaries for empirical provider runs, including `repair_cycle_count`, `repair_history`, `repair_task_ids`, and compact task-level failure metadata.
- Focused regression coverage for provider availability probing, empirical rerun control flow, workflow-summary persistence, and the new example entrypoints.

### Changed

- `examples/example_full_provider_workflow.py` now defaults to the bounded-repair validation mode (`workflow_failure_policy="continue"`, `workflow_resume_policy="resume_failed"`, `workflow_max_repair_cycles=1`) and automatically consumes the configured repair budget.
- Real provider-matrix validation now confirms the same bounded corrective-lineage semantics across all supported providers instead of relying on Ollama-only full-workflow evidence.

### Release Readiness Notes

- Version `1.0.8` is now the previous package baseline.

## 1.0.7 - 2026-03-25

### Added

- First-class persisted corrective child tasks for bounded repair cycles, including `repair_origin_task_id` and `repair_attempt` lineage.
- Mirroring of corrective-task execution back into the original logical workflow task so task history, attempts, and final outputs remain audit-friendly without breaking the stable task graph contract.
- Persistence and resume coverage proving corrective tasks survive save/load and continue correctly after workflow reload.

### Changed

- `resume_failed` now materializes corrective repair tasks instead of only reassigning the original failed task in place.
- Dependency-skipped descendants can be re-queued while the failed logical task remains the workflow truth record and waits for its corrective child to finish.

### Release Readiness Notes

- Version `1.0.7` is now the previous package baseline.

## 1.0.6 - 2026-03-25

### Added

- Persisted task-level `repair_context` metadata so bounded repair attempts preserve failure evidence across save/load and workflow resume.
- Failure-category-driven repair routing that can send resumed tasks to `code_engineer`, `qa_tester`, or `dependency_manager` based on the normalized validation failure.
- Structured repair attempt descriptions and repair validation summaries injected into agent input context for resumed tasks.

### Changed

- `resume_failed` workflow recovery no longer behaves like a blind requeue: failed tasks now restart with explicit repair instructions, preserved failing artifact content, and validation evidence.
- The orchestrator now distinguishes the original task owner from the effective repair owner, allowing corrective execution without rewriting the persisted workflow graph.

### Release Readiness Notes

- Version `1.0.6` is now the previous package baseline.

## 1.0.5 - 2026-03-25

### Added

- Explicit `workflow_max_repair_cycles` configuration with validation and a backward-compatible default repair budget for `resume_failed` workflows.
- Persisted repair-cycle accounting in workflow state and snapshots, including audit history and remaining repair budget metadata.
- Orchestrator regressions covering successful bounded repair resumption and deterministic failure when the workflow repair budget is exhausted.

### Changed

- `resume_failed` workflow recovery now consumes an explicit workflow-level repair budget instead of allowing unbounded rerun attempts.
- Exhausted repair budgets now terminate workflows with the normalized failure category `repair_budget_exhausted` and persisted acceptance evidence.

### Release Readiness Notes

- Version `1.0.5` is now the previous package baseline.

## 1.0.4 - 2026-03-25

### Added

- Targeted regression coverage for config validation edge cases, provider base-contract behavior, legal advisor prompt construction, and legacy project-state normalization paths.
- A project-state regression proving missing-task lookup, unresolved dependency readiness checks, retry-window evaluation, and lightweight decision recording stay deterministic.

### Changed

- Generated pytest subprocess execution now strips inherited coverage instrumentation environment variables before running model-generated test validation.
- The repository coverage gate now passes without mixing incompatible nested coverage data from orchestrator-managed subprocesses.
- Release validation and CI coverage execution now stabilize on the repository's enforced `90%` threshold with the new regression coverage.

### Release Readiness Notes

- Version `1.0.4` is now the previous package baseline.

## 1.0.3 - 2026-03-25

### Added

- Explicit workflow acceptance policy support with `all_tasks` and `required_tasks` modes.
- Persisted `acceptance_policy` and `acceptance_evaluation` metadata in workflow state, snapshots, and workflow execution events.
- Task-level `required_for_acceptance` markers so workflow templates can declare which tasks define terminal acceptance.

### Changed

- The orchestrator now evaluates workflow completion through explicit acceptance-policy logic instead of an implicit all-task-success heuristic.
- Workflows using `required_tasks` now degrade safely when no required tasks are declared, preventing false successful completion.
- Accepted workflows can now complete under the required-task policy even when optional tasks fail, while preserving explicit audit evidence in state.

### Release Readiness Notes

- Version `1.0.3` is now the released package baseline.

## 1.0.2 - 2026-03-25

### Added

- Explicit `WorkflowOutcome` and `FailureCategory` public types for terminal workflow semantics and normalized failure classification.
- Persisted workflow-level `terminal_outcome`, `failure_category`, and `acceptance_criteria_met` metadata in project snapshots and execution events.

### Changed

- The orchestrator now classifies task failures by validation domain and persists those categories into failed task records.
- Workflows that finish with skipped tasks under the `continue` failure policy now preserve the historical `completed` phase while exposing a `degraded` terminal outcome and `acceptance_criteria_met=False`.

### Release Readiness Notes

- Version `1.0.2` is now the released package baseline.

## 1.0.1 - 2026-03-25

### Added

- A first-class `DependencyManagerAgent` that emits normalized `requirements.txt` artifacts for generated projects.
- Deterministic orchestrator context derivation for generated module APIs, test validation, and dependency-manifest validation.
- A low-cost provider smoke example for OpenAI, Anthropic, and Ollama under `examples/example_provider_smoke.py`.
- Cross-provider orchestrator regressions proving dependency-manifest enforcement across OpenAI, Anthropic, and Ollama adapters.

### Changed

- Agent prompts now constrain architecture, code, tests, review, and documentation generation to the actual single-module artifact produced by the workflow.
- Code and test artifacts are now normalized to raw source output when providers return markdown fences or leading prose.
- Ollama failures now surface explicit health-check, timeout, HTTP, and invalid-JSON diagnostics instead of a generic provider-call error.
- Anthropic examples and documentation now use the live-valid low-cost model `claude-haiku-4-5-20251001`.

### Release Readiness Notes

- Version `1.0.1` is now the released package baseline.

## 1.0.0 - 2026-03-25

### Added

- A repository-owned `COMMERCIAL_LICENSE.md` guide describing the dual-license model and the commercial licensing contact path.
- A repository-owned `CONTRIBUTOR_RIGHTS.md` guide describing contributor-rights expectations for the dual-license model.
- GitHub Actions CI covering linting, type checking, focused regressions, package validation, and the full pytest suite.
- Tagged and manual GitHub release automation that rebuilds artifacts and publishes wheel and source-distribution assets.
- Built-artifact validation through `scripts/package_check.py`, including wheel and sdist install smoke checks.
- Python 3.10 CI hardening for TOML-reading tests through conditional `tomli` support and broader focused regression coverage.
- Repository-owned architecture, provider, workflow, persistence, extension, and troubleshooting guides.
- Curated public examples covering resume, failure recovery, custom agents, multi-provider usage, deterministic test mode, complex DAGs, and snapshot inspection.
- A repository-owned `scripts/release_check.py` validator and `make release-check` target for full local release verification.
- A repository-owned `RELEASE.md` guide describing the final release gate, version-tag flow, and post-tag verification steps.
- A repository-owned `RELEASE_STATUS.md` snapshot describing the current release-readiness state and the remaining manual release decision.
- A repository-owned `scripts/release_metadata_check.py` validator and `make release-metadata-check` target for version and release-document alignment checks before tagging.

- Public licensing guidance now documents the AGPL open-source distribution together with a separate commercial licensing path, while package metadata remains aligned to the open-source distribution.
- Public package imports are now centered on the stable top-level `kycortex_agents` surface and the public `workflows` module.
- Workflow execution now supports explicit dependencies, retry policies, failure policies, resumable execution, and persisted audit history.
- Persistence now supports both JSON and SQLite backends while retaining compatibility with older state payloads.
- Provider execution now exposes structured metadata for latency, usage, and failure diagnostics across OpenAI, Anthropic, and Ollama.
- Packaging metadata now uses SPDX license metadata and modern setuptools configuration for cleaner automated builds.
- Release-readiness validation is now codified in a single local command that runs linting, typing, focused regressions, package validation, the coverage gate, and the full pytest suite in sequence.
- Release-facing documentation now separates the stable operator procedure from the current release-readiness snapshot so the final tag decision is explicit.
- Release metadata validation now checks that package version declarations and release-facing documents remain aligned before a version tag is created.

### Release Readiness Notes

- Version `1.0.0` is now the released package baseline.
- Phase 13 release-readiness work is complete, and future changes should build from the shipped `1.0.0` baseline.