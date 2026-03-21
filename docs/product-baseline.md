# Product Baseline for KYCortex 1.0

## Objective

Deliver KYCortex 1.0 as a production-grade Python framework for multi-agent software delivery workflows. The first release must be robust as a library product, support multiple LLM providers, and expose a stable public API with durable state and observable execution.

## Product scope

### Included in 1.0

- Stable Python package for local and CI usage.
- Multi-provider support for OpenAI, Anthropic, and one supported local backend.
- Typed workflow execution model with explicit task dependencies.
- Durable persistence with resumable execution.
- Structured logging and runtime observability.
- Public extension points for custom agents and workflow composition.
- Automated test suite, packaging validation, and release automation.
- Accurate documentation and curated examples.

### Excluded from 1.0

- Hosted SaaS control plane.
- Web dashboard as a release blocker.
- Multi-tenant cloud backend.
- Large domain-specific agent packs beyond the current core set.

## Supported platform baseline

- Python: 3.10, 3.11, 3.12.
- Package distribution: source distribution and wheel.
- Execution model: library-first, CLI-ready architecture.
- Local persistence default: SQLite.

## Provider baseline

### Required providers

- OpenAI
- Anthropic
- One local backend selected during implementation

### Required provider capabilities

- Text generation
- Structured output support or equivalent schema validation path
- Timeout handling
- Retry handling with backoff
- Token usage and latency reporting
- Clear provider-specific error mapping

## Workflow baseline

### Required 1.0 capabilities

- Explicit task dependencies
- Deterministic execution ordering
- Retry policies
- Failure policies
- Resume after interruption
- Linear mode built on top of the workflow engine

### Non-blocking capabilities

- Parallel execution of independent tasks
- Advanced branching and conditional workflows beyond the initial engine

## Public API baseline

The package must support top-level imports for the primary public types and services without requiring deep internal imports.

### Minimum public surface

- Orchestrator
- Configuration types
- Workflow and task types
- State store interfaces
- Base agent and registry
- Core result and artifact types

## Migration constraints

- The current prototype API is not stable and can change during the redesign.
- Migration notes are required before the 1.0 release candidate.
- The public API must be frozen before packaging, documentation, and example suites are finalized.

## Release criteria

### Functional criteria

- All required providers satisfy the common provider contract.
- Workflow execution supports dependency ordering, failure handling, and resume behavior.
- State persistence preserves task transitions, outputs, artifacts, decisions, and failures.
- The public API supports the documented example workflows.

### Quality criteria

- Automated tests cover the core runtime, providers, workflow engine, persistence, and public API.
- CI passes linting, typing, tests, coverage gate, and packaging validation.
- Clean install and example execution succeed from source and built artifacts.
- Documentation matches shipped behavior and repository contents.

## Current baseline findings

- The current orchestrator is sequential and context passing is implicit.
- Agent outputs are untyped and not validated before reuse.
- The base agent is coupled to OpenAI.
- State persistence is JSON-only and not durable enough for 1.0.
- The public API surface is not yet defined.
- Tests, CI, and release automation are missing.

## Phase 0 completion conditions

- Product scope documented and approved.
- Platform and provider baseline documented.
- Release criteria documented.
- Migration constraints documented.
- Repository plan mirror created at [docs/plan.md](/home/user/bootcamp/projects/kycortex-agents/docs/plan.md).

## Phase 0 status

Phase 0 is complete. The remaining implementation work starts in Phase 1 with the typed domain model, inter-agent contracts, and architecture redesign.
