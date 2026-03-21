# Release Checklist for KYCortex 1.0

## Scope and product readiness

- Product scope is documented and approved.
- Included and excluded 1.0 features are frozen.
- Supported Python versions are frozen.
- Supported provider matrix is frozen.
- Public API freeze criteria are documented.

## Architecture and runtime readiness

- Provider abstraction is implemented and validated.
- Typed workflow contracts are implemented.
- Agent runtime lifecycle and error handling are implemented.
- Workflow dependency execution, retry handling, and resume behavior are validated.
- State persistence backend is durable and validated.

## Quality and verification

- Unit tests pass.
- Integration tests pass.
- Provider smoke tests pass.
- Coverage threshold passes in CI.
- Lint and type checks pass in CI.
- Packaging validation passes in CI.

## Documentation and examples

- README matches shipped functionality.
- Architecture documentation matches implementation.
- Contribution guidance exists and is accurate.
- Example workflows run against the public API.
- Migration notes are ready for the release candidate.

## Distribution and operations

- Source distribution builds successfully.
- Wheel builds successfully.
- Clean environment install succeeds from built artifacts.
- Version number, changelog, and release notes are prepared.
- Release workflow is green for the tagged version.

## Final release gate

- No open release-blocking defects remain.
- Plan status and repository plan mirror are current.
- The release candidate checklist has been reviewed before tagging 1.0.