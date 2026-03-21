## Plan: Finalize KYCortex 1.0

Canonical workspace copy of the project plan. Keep this file synchronized with the repository memory plan after each completed phase or major milestone.

**Status**
- Current state: Phase 1 complete, Phase 2 ready to start.
- Completed phases: Phase 0, Phase 1.
- Next milestone: expand the provider layer beyond the initial OpenAI implementation.
- Progress: 2/14 phases complete.
- Update rule: after each completed phase or major milestone, update this file and the repository memory plan together.

The goal is to turn the current prototype into a production-grade multi-agent framework by first stabilizing the execution core, then introducing typed inter-agent contracts and provider abstraction, then expanding into workflow orchestration, persistence, observability, packaging, and release operations. The recommended path is to avoid shipping roadmap items as isolated fixes and instead evolve the package into a layered library with explicit schemas, a registry, a workflow engine, and a verified public API.

**Phases**
1. Phase 0: Product definition and baseline freeze. Capture 1.0 scope, supported Python versions, provider matrix, supported workflow features, and release criteria. Freeze the current public behavior as the migration baseline. Output: product requirements note, release checklist, and migration constraints.
2. Phase 1: Core architecture redesign. Replace the current implicit context passing model with explicit typed contracts between tasks, orchestrator, and agents. Define core domain types for Task, TaskResult, AgentInput, AgentOutput, ProjectSnapshot, DecisionRecord, ArtifactRecord, FailureRecord, and WorkflowStatus.
3. Phase 2: Provider abstraction. Introduce a provider layer that decouples agents from OpenAI-specific calls and supports OpenAI, Anthropic, and local models behind a common interface.
4. Phase 3: Agent runtime refactor. Rework the base agent into a runtime-aware abstraction with input validation, output schema validation, lifecycle hooks, and standardized error handling.
5. Phase 4: Workflow engine redesign. Replace the current sequential pending-task loop with an execution model that supports explicit dependencies, topological ordering, retries, failure policies, resumability, and optional parallel execution.
6. Phase 5: State and persistence overhaul. Replace the current JSON-only state handling with a state store abstraction and add a durable transactional backend for 1.0.
7. Phase 6: Observability and operational safeguards. Add structured logging, traces, provider call metadata, latency and token accounting, and clear exception classes.
8. Phase 7: Public API definition. Turn the package into a stable library surface with documented extension points and clear separation between public contracts and internal modules.
9. Phase 8: Tests and quality gates. Build unit, integration, smoke, and regression tests to cover the runtime, providers, workflow engine, and persistence model.
10. Phase 9: Packaging and repository hygiene. Clean up packaging metadata, extras, build configuration, package exports, and distribution artifacts.
11. Phase 10: Documentation rewrite. Rewrite the README and add architecture, extension, provider, workflow, persistence, troubleshooting, and contribution documentation.
12. Phase 11: Examples and developer experience. Replace the current single example with a curated example suite and add local development tooling.
13. Phase 12: CI/CD and release automation. Add automated linting, type checking, testing, packaging validation, and release workflows.
14. Phase 13: Final hardening and 1.0 release readiness. Run the release candidate cycle and publish changelog and migration notes.

**Current deliverables**
- [docs/product-baseline.md](/home/user/bootcamp/projects/kycortex-agents/docs/product-baseline.md)
- [docs/release-checklist.md](/home/user/bootcamp/projects/kycortex-agents/docs/release-checklist.md)
- [pyproject.toml](/home/user/bootcamp/projects/kycortex-agents/pyproject.toml)
- [kycortex_agents/types.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/types.py)
- [kycortex_agents/exceptions.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/exceptions.py)
- [kycortex_agents/__init__.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/__init__.py)
- [kycortex_agents/config.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/config.py)
- [kycortex_agents/agents/registry.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/agents/registry.py)
- [kycortex_agents/memory/project_state.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/memory/project_state.py)
- [kycortex_agents/memory/__init__.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/memory/__init__.py)
- [kycortex_agents/providers/base.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/providers/base.py)
- [kycortex_agents/providers/openai_provider.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/providers/openai_provider.py)
- [kycortex_agents/providers/factory.py](/home/user/bootcamp/projects/kycortex-agents/kycortex_agents/providers/factory.py)
- [tests/test_orchestrator.py](/home/user/bootcamp/projects/kycortex-agents/tests/test_orchestrator.py)
- [tests/test_base_agent.py](/home/user/bootcamp/projects/kycortex-agents/tests/test_base_agent.py)
- [tests/test_config.py](/home/user/bootcamp/projects/kycortex-agents/tests/test_config.py)
- [tests/test_package_metadata.py](/home/user/bootcamp/projects/kycortex-agents/tests/test_package_metadata.py)
- [tests/test_public_api.py](/home/user/bootcamp/projects/kycortex-agents/tests/test_public_api.py)
- [tests/test_project_state.py](/home/user/bootcamp/projects/kycortex-agents/tests/test_project_state.py)
- [tests/test_registry.py](/home/user/bootcamp/projects/kycortex-agents/tests/test_registry.py)
- [tests/test_providers.py](/home/user/bootcamp/projects/kycortex-agents/tests/test_providers.py)

**Synchronization**
- Memory source: `/memories/repo/plan.md`
- Visible repository mirror: [docs/plan.md](/home/user/bootcamp/projects/kycortex-agents/docs/plan.md)

**Last completed milestone**
- Phase 1 completed by replacing implicit task/runtime contracts with typed inputs, typed outputs, typed snapshots, explicit agent lookup, and a stable public API surface.

**Current phase notes**
- Phase 1 started with the initial typed domain model and first public API exports.
- The orchestrator now builds semantic context from project snapshots, marks task failures explicitly, and is covered by the first automated tests.
- The base agent now raises explicit runtime errors for provider failures and invalid responses, and that behavior is covered by unit tests.
- The provider layer now exists behind a factory and OpenAI implementation, and the full suite passes with provider-level coverage.
- Configuration now normalizes provider settings, validates static runtime values, and enforces provider credentials when a provider instance is created.
- The orchestrator now resolves agents through an explicit registry, removing the hardcoded agent map and improving extension points.
- Project state persistence now saves atomically, creates missing state directories, and raises explicit persistence errors for missing or invalid state files.
- The package now exposes a clearer public API, including version, agent classes, and memory exports, and that surface is covered by import smoke tests.
- Project snapshots now expose structured task outputs with summaries, artifact typing, and output metadata instead of carrying only raw task strings.
- Package metadata now declares classifiers, typed-package support, pytest configuration, and dependency bounds, and this configuration is covered by pyproject metadata tests.
- The runtime now invokes agents through a typed AgentInput entrypoint while preserving compatibility with legacy run(description, context) implementations.
