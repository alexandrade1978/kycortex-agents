# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally lightweight for the stabilized 1.0 line. Entries group changes by milestone so release history stays visible directly in the repository.

## Unreleased

## 1.0.8 - 2026-03-25

### Added

- A new internal provider-matrix validation helper module plus `examples/example_provider_matrix_validation.py` for reproducible empirical full-workflow reruns across OpenAI, Anthropic, and Ollama.
- Structured JSON workflow summaries for empirical provider runs, including `repair_cycle_count`, `repair_history`, `repair_task_ids`, and compact task-level failure metadata.
- Focused regression coverage for provider availability probing, empirical rerun control flow, workflow-summary persistence, and the new example entrypoints.

### Changed

- `examples/example_full_provider_workflow.py` now defaults to the bounded-repair validation mode (`workflow_failure_policy="continue"`, `workflow_resume_policy="resume_failed"`, `workflow_max_repair_cycles=1`) and automatically consumes the configured repair budget.
- Real provider-matrix validation now confirms the same bounded corrective-lineage semantics across all supported providers instead of relying on Ollama-only full-workflow evidence.

### Release Readiness Notes

- Version `1.0.8` is now the released package baseline.

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