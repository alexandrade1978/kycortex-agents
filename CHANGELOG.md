# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally lightweight while the project moves toward its 1.0 release candidate. Entries group changes by milestone so release readiness stays visible even before the final 1.0 tag exists.

## Unreleased

### Added

- GitHub Actions CI covering linting, type checking, focused regressions, package validation, and the full pytest suite.
- Tagged and manual GitHub release automation that rebuilds artifacts and publishes wheel and source-distribution assets.
- Built-artifact validation through `scripts/package_check.py`, including wheel and sdist install smoke checks.
- Python 3.10 CI hardening for TOML-reading tests through conditional `tomli` support and broader focused regression coverage.
- Repository-owned architecture, provider, workflow, persistence, extension, and troubleshooting guides.
- Curated public examples covering resume, failure recovery, custom agents, multi-provider usage, deterministic test mode, complex DAGs, and snapshot inspection.

### Changed

- Public package imports are now centered on the stable top-level `kycortex_agents` surface and the public `workflows` module.
- Workflow execution now supports explicit dependencies, retry policies, failure policies, resumable execution, and persisted audit history.
- Persistence now supports both JSON and SQLite backends while retaining compatibility with older state payloads.
- Provider execution now exposes structured metadata for latency, usage, and failure diagnostics across OpenAI, Anthropic, and Ollama.
- Packaging metadata now uses SPDX license metadata and modern setuptools configuration for cleaner automated builds.

### Release Readiness Notes

- Current package version remains `0.1.0` while the repository completes 1.0 release-candidate hardening.
- The remaining Phase 13 work is focused on final release-candidate verification, migration guidance, and closing the last release-gate items before tagging `1.0.0`.