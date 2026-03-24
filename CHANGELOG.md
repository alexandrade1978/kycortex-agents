# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally lightweight for the stabilized 1.0 line. Entries group changes by milestone so release history stays visible directly in the repository.

## Unreleased

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

### Changed

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