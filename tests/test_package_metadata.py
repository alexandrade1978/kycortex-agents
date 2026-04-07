from pathlib import Path
import importlib
import json
import os
import re
import subprocess
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 in CI
    tomllib = importlib.import_module("tomli")

import kycortex_agents


def _refresh_generated_egg_info() -> Path:
    project_root = Path(__file__).resolve().parents[1]
    env = {
        key: value
        for key, value in os.environ.items()
        if not (key.startswith("COV_CORE_") or key.startswith("COVERAGE"))
    }
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps", "--quiet"],
        cwd=project_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return project_root / "kycortex_agents.egg-info"


def test_pyproject_contains_expected_package_metadata():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    project = data["project"]
    assert project["name"] == "kycortex-agents"
    assert project["version"] == kycortex_agents.__version__
    assert project["authors"] == [{"name": "Alexandre Andrade", "email": "alex@kycortex.com"}]
    assert project["license"] == "AGPL-3.0-only"
    assert project["license-files"] == ["LICENSE"]
    assert "Development Status :: 3 - Alpha" in project["classifiers"]
    assert "Typing :: Typed" in project["classifiers"]
    assert "License :: OSI Approved :: GNU Affero General Public License v3" not in project["classifiers"]
    assert "anthropic>=0.34.0,<1.0.0" in project["dependencies"]
    assert "openai>=1.0.0,<2.0.0" in project["dependencies"]
    assert data["project"]["urls"]["Homepage"] == "https://github.com/alexandrade1978/kycortex-agents"
    assert data["project"]["urls"]["Documentation"].endswith("/docs/README.md")


def test_pyproject_build_backend_supports_spdx_license_metadata():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert data["build-system"]["requires"] == ["setuptools>=77.0.0", "wheel"]


def test_pyproject_version_matches_package_version_constant():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert data["project"]["version"] == kycortex_agents.__version__


def test_pyproject_declares_test_extra():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    optional_dependencies = data["project"]["optional-dependencies"]
    assert optional_dependencies["test"] == [
        "build>=1.2,<2.0",
        "pytest>=7.0.0",
        "pytest-cov>=5,<7",
        "tomli>=2.0.1,<3.0; python_version < '3.11'",
        "mypy>=1.10,<2.0",
        "pre-commit>=3.7,<5.0",
        "ruff>=0.6,<1.0",
    ]


def test_pyproject_declares_local_lint_and_typecheck_tooling():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    ruff_config = data["tool"]["ruff"]
    mypy_config = data["tool"]["mypy"]

    assert ruff_config["target-version"] == "py310"
    assert mypy_config["python_version"] == "3.10"
    assert mypy_config["files"] == ["kycortex_agents", "examples"]
    assert data["tool"]["mypy"]["overrides"][0]["module"] == ["anthropic"]
    assert data["tool"]["mypy"]["overrides"][0]["ignore_missing_imports"] is True


def test_pyproject_declares_repository_coverage_gate_configuration():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert data["tool"]["coverage"]["run"] == {"source": ["kycortex_agents"], "branch": True}
    assert data["tool"]["coverage"]["report"]["fail_under"] == 90
    assert data["tool"]["coverage"]["report"]["show_missing"] is True
    assert data["tool"]["coverage"]["report"]["skip_covered"] is False


def test_pyproject_declares_explicit_setuptools_package_discovery():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    setuptools_config = data["tool"]["setuptools"]
    assert setuptools_config["include-package-data"] is True
    assert setuptools_config["packages"]["find"]["include"] == [
        "kycortex_agents",
        "kycortex_agents.*",
    ]


def test_typed_package_marker_exists_and_is_declared_in_package_data():
    project_root = Path(__file__).resolve().parents[1]
    pyproject_path = project_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert (project_root / "kycortex_agents" / "py.typed").is_file()
    assert data["tool"]["setuptools"]["package-data"]["kycortex_agents"] == ["py.typed"]


def test_pyproject_metadata_file_pointers_exist():
    project_root = Path(__file__).resolve().parents[1]
    pyproject_path = project_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    project = data["project"]
    assert (project_root / project["readme"]).is_file()
    assert (project_root / "LICENSE").is_file()
    assert (project_root / "COMMERCIAL_LICENSE.md").is_file()
    assert (project_root / "CONTRIBUTOR_RIGHTS.md").is_file()


def test_manifest_in_exists_and_covers_core_distribution_assets():
    project_root = Path(__file__).resolve().parents[1]
    manifest_path = project_root / "MANIFEST.in"

    assert manifest_path.is_file()

    manifest = manifest_path.read_text(encoding="utf-8")
    assert "include LICENSE" in manifest
    assert "include COMMERCIAL_LICENSE.md" in manifest
    assert "include CONTRIBUTOR_RIGHTS.md" in manifest
    assert "include README.md" in manifest
    assert "include CONTRIBUTING.md" in manifest
    assert "include RELEASE.md" in manifest
    assert "include RELEASE_STATUS.md" in manifest
    assert "include Makefile" in manifest
    assert "include .editorconfig" in manifest
    assert "include .pre-commit-config.yaml" in manifest
    assert "recursive-include scripts *.py" in manifest
    assert "recursive-include docs *.md" in manifest
    assert "recursive-include examples *.py" in manifest
    assert "recursive-include kycortex_agents py.typed" in manifest


def test_generated_egg_info_metadata_matches_current_package_contract():
    egg_info_dir = _refresh_generated_egg_info()
    metadata = (egg_info_dir / "PKG-INFO").read_text(encoding="utf-8")
    requirements = (egg_info_dir / "requires.txt").read_text(encoding="utf-8")

    assert "Author-email: Alexandre Andrade <alex@kycortex.com>" in metadata
    assert "Project-URL: Documentation, https://github.com/alexandrade1978/kycortex-agents/blob/main/docs/README.md" in metadata
    assert "Requires-Dist: anthropic<1.0.0,>=0.34.0" in metadata
    assert "Requires-Dist: openai<2.0.0,>=1.0.0" in metadata
    assert "Requires-Dist: pytest>=7.0.0; extra == \"test\"" in metadata
    assert "Requires-Dist: build<2.0,>=1.2; extra == \"test\"" in metadata
    assert "Requires-Dist: pytest-cov<7,>=5; extra == \"test\"" in metadata
    assert "Requires-Dist: tomli<3.0,>=2.0.1; python_version < \"3.11\" and extra == \"test\"" in metadata
    assert "Requires-Dist: mypy<2.0,>=1.10; extra == \"test\"" in metadata
    assert "Requires-Dist: pre-commit<5.0,>=3.7; extra == \"test\"" in metadata
    assert "Requires-Dist: ruff<1.0,>=0.6; extra == \"test\"" in metadata
    assert "https://kycortex.com" not in metadata
    assert "from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task" in metadata
    assert "OPENAI_API_KEY" in metadata
    assert "ANTHROPIC_API_KEY" in metadata
    assert "anthropic<1.0.0,>=0.34.0" in requirements
    assert "build<2.0,>=1.2" in requirements
    assert "pytest-cov<7,>=5" in requirements
    assert '[test:python_version < "3.11"]' in requirements
    assert "tomli<3.0,>=2.0.1" in requirements
    assert "openai<2.0.0,>=1.0.0" in requirements
    assert "mypy<2.0,>=1.10" in requirements
    assert "pre-commit<5.0,>=3.7" in requirements
    assert "ruff<1.0,>=0.6" in requirements


def test_generated_egg_info_sources_include_current_distribution_assets():
    egg_info_dir = _refresh_generated_egg_info()
    members = set((egg_info_dir / "SOURCES.txt").read_text(encoding="utf-8").splitlines())

    expected_members = {
        ".editorconfig",
        ".pre-commit-config.yaml",
        "COMMERCIAL_LICENSE.md",
        "CONTRIBUTOR_RIGHTS.md",
        "CONTRIBUTING.md",
        "Makefile",
        "RELEASE.md",
        "RELEASE_STATUS.md",
        "docs/README.md",
        "examples/example_complex_workflow.py",
        "examples/example_custom_agent.py",
        "examples/example_failure_recovery.py",
        "examples/example_multi_provider.py",
        "examples/example_provider_matrix_validation.py",
        "examples/example_resume_workflow.py",
        "examples/example_simple_project.py",
        "examples/example_snapshot_inspection.py",
        "examples/example_test_mode.py",
        "kycortex_agents/exceptions.py",
        "kycortex_agents/py.typed",
        "scripts/package_check.py",
        "scripts/release_artifact_manifest.py",
        "scripts/release_metadata_check.py",
        "scripts/release_check.py",
        "scripts/release_promotion_summary.py",
        "kycortex_agents/agents/registry.py",
        "kycortex_agents/memory/state_store.py",
        "kycortex_agents/providers/__init__.py",
        "kycortex_agents/providers/anthropic_provider.py",
        "kycortex_agents/providers/base.py",
        "kycortex_agents/providers/factory.py",
        "kycortex_agents/providers/ollama_provider.py",
        "kycortex_agents/providers/openai_provider.py",
    }

    missing_members = sorted(expected_members - members)
    assert not missing_members, f"generated egg-info is missing: {missing_members}"


def test_top_level_contributing_guide_exists_for_readme_reference():
    project_root = Path(__file__).resolve().parents[1]

    assert (project_root / "CONTRIBUTING.md").is_file()
    assert (project_root / "COMMERCIAL_LICENSE.md").is_file()
    assert (project_root / "CONTRIBUTOR_RIGHTS.md").is_file()
    assert (project_root / "RELEASE.md").is_file()
    assert (project_root / "RELEASE_STATUS.md").is_file()
    assert (project_root / "CHANGELOG.md").is_file()
    assert (project_root / "MIGRATION.md").is_file()
    assert (project_root / "docs" / "README.md").is_file()
    assert (project_root / ".github" / "workflows" / "ci.yml").is_file()
    assert (project_root / ".github" / "workflows" / "release.yml").is_file()


def test_contributing_guide_documents_test_command_tiers():
    contributing_path = Path(__file__).resolve().parents[1] / "CONTRIBUTING.md"
    contributing = contributing_path.read_text(encoding="utf-8")

    assert "make setup" in contributing
    assert "make install-hooks" in contributing
    assert "Suggested Test Commands" in contributing
    assert "python -m pre_commit install --install-hooks --hook-type pre-commit --hook-type pre-push" in contributing
    assert "python -m pre_commit run --all-files" in contributing
    assert "python -m pre_commit run --all-files --hook-stage pre-push" in contributing
    assert "python scripts/package_check.py" in contributing
    assert "make package-check" in contributing
    assert "python scripts/release_artifact_manifest.py --dist-dir dist --output dist/release-artifact-manifest.json" in contributing
    assert "python scripts/release_artifact_manifest.py --dist-dir dist --manifest dist/release-artifact-manifest.json --verify" in contributing
    assert "python scripts/release_promotion_summary.py --dist-dir dist --manifest dist/release-artifact-manifest.json --tag v<version> --output dist/release-promotion-summary.json" in contributing
    assert "python scripts/release_metadata_check.py" in contributing
    assert "make release-metadata-check" in contributing
    assert "git tag v<version>" in contributing
    assert "git push origin v<version>" in contributing
    assert "RELEASE.md" in contributing
    assert "RELEASE_STATUS.md" in contributing
    assert ".github/workflows/release.yml" in contributing
    assert "scripts/release_promotion_summary.py" in contributing
    assert "make precommit" in contributing
    assert "make prepush" in contributing
    assert "python -m ruff check ." in contributing
    assert "python -m mypy" in contributing
    assert "make lint" in contributing
    assert "make typecheck" in contributing
    assert "python -m pytest --cov=kycortex_agents --cov-report=term-missing --cov-report=xml -q" in contributing
    assert "make coverage" in contributing
    assert "python scripts/release_check.py" in contributing
    assert "make release-check" in contributing
    assert "## Contribution Licensing" in contributing
    assert "COMMERCIAL_LICENSE.md" in contributing
    assert "CONTRIBUTOR_RIGHTS.md" in contributing
    assert "case-by-case basis" in contributing
    assert "explicit written rights grant" in contributing
    assert "tests/test_public_api.py tests/test_public_smoke.py -q" in contributing
    assert "tests/test_package_metadata.py -q" in contributing
    assert "python -m pytest -q" in contributing
    assert "make test-public" in contributing
    assert "make test-metadata" in contributing
    assert "make test" in contributing


def test_local_tooling_files_exist_and_cover_expected_commands():
    project_root = Path(__file__).resolve().parents[1]
    makefile = (project_root / "Makefile").read_text(encoding="utf-8")
    editorconfig = (project_root / ".editorconfig").read_text(encoding="utf-8")
    precommit_config = (project_root / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert ".PHONY: setup install-hooks precommit prepush lint typecheck coverage package-check release-metadata-check release-check test-public test-metadata test" in makefile
    assert 'python -m pip install -e ".[test]"' in makefile
    assert "python -m pre_commit install --install-hooks --hook-type pre-commit --hook-type pre-push" in makefile
    assert "python -m pre_commit run --all-files" in makefile
    assert "python -m pre_commit run --all-files --hook-stage pre-push" in makefile
    assert "python -m ruff check ." in makefile
    assert "python -m mypy" in makefile
    assert "python -m pytest --cov=kycortex_agents --cov-report=term-missing --cov-report=xml -q" in makefile
    assert "python scripts/package_check.py" in makefile
    assert "python scripts/release_metadata_check.py" in makefile
    assert "python scripts/release_check.py" in makefile
    assert "python -m pytest tests/test_public_api.py tests/test_public_smoke.py -q" in makefile
    assert "python -m pytest tests/test_package_metadata.py -q" in makefile
    assert "python -m pytest -q" in makefile
    assert "root = true" in editorconfig
    assert "[*.py]" in editorconfig
    assert "indent_size = 4" in editorconfig
    assert "[Makefile]" in editorconfig
    assert "indent_style = tab" in editorconfig
    assert 'minimum_pre_commit_version: "3.7.0"' in precommit_config
    assert "stages: [pre-commit, manual]" in precommit_config
    assert "stages: [pre-push, manual]" in precommit_config
    assert "entry: .venv/bin/python" in precommit_config
    assert 'args: ["-m", "ruff", "check", "."]' in precommit_config
    assert 'args: ["-m", "mypy"]' in precommit_config
    assert 'args: ["-m", "pytest", "tests/test_public_api.py", "tests/test_package_metadata.py", "-q"]' in precommit_config


def test_github_actions_ci_workflow_covers_repository_validation_baseline():
    project_root = Path(__file__).resolve().parents[1]
    ci_workflow = (project_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "name: CI" in ci_workflow
    assert "pull_request:" in ci_workflow
    assert "workflow_dispatch:" in ci_workflow
    assert "branches:" in ci_workflow
    assert "- main" in ci_workflow
    assert "actions/checkout@v5" in ci_workflow
    assert "actions/setup-python@v6" in ci_workflow
    assert 'python-version: ["3.10", "3.12"]' in ci_workflow
    assert 'python-version: "3.12"' in ci_workflow
    assert "name: Focused Regressions (${{ matrix.python-version }})" in ci_workflow
    assert 'python -m pip install -e ".[test]"' in ci_workflow
    assert "python -m ruff check ." in ci_workflow
    assert "python -m mypy" in ci_workflow
    assert "python -m pytest tests/test_public_api.py tests/test_public_smoke.py tests/test_package_metadata.py -q" in ci_workflow
    assert "package-validation:" in ci_workflow
    assert "coverage-gate:" in ci_workflow
    assert "python scripts/package_check.py" in ci_workflow
    assert "python -m pytest --cov=kycortex_agents --cov-report=term-missing --cov-report=xml -q" in ci_workflow
    assert "python -m pytest -q" in ci_workflow


def test_github_actions_release_workflow_covers_tagged_release_automation():
    project_root = Path(__file__).resolve().parents[1]
    release_workflow = (project_root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "name: Release" in release_workflow
    assert "workflow_dispatch:" in release_workflow
    assert "tags:" in release_workflow
    assert '- "v*"' in release_workflow
    assert "actions/checkout@v5" in release_workflow
    assert "actions/setup-python@v6" in release_workflow
    assert 'python -m pip install -e ".[test]"' in release_workflow
    assert "Run repository-owned release gate" in release_workflow
    assert "python scripts/release_check.py" in release_workflow
    assert "python -m build" in release_workflow
    assert "python scripts/release_artifact_manifest.py --dist-dir dist --output dist/release-artifact-manifest.json" in release_workflow
    assert "python scripts/release_artifact_manifest.py --dist-dir dist --manifest dist/release-artifact-manifest.json --verify" in release_workflow
    assert "python scripts/release_promotion_summary.py --dist-dir dist --manifest dist/release-artifact-manifest.json --tag ${{ github.ref_name }} --commit-sha ${{ github.sha }} --output dist/release-promotion-summary.json" in release_workflow
    assert "release-artifact-manifest.json" in release_workflow
    assert "release-promotion-summary.json" in release_workflow
    assert "actions/upload-artifact@v4" in release_workflow
    assert "actions/download-artifact@v4" in release_workflow
    assert "softprops/action-gh-release@v2" in release_workflow
    assert "generate_release_notes: true" in release_workflow


def test_readme_relative_markdown_links_resolve_to_existing_files():
    project_root = Path(__file__).resolve().parents[1]
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    relative_targets = re.findall(r"\[[^\]]+\]\(((?!https?://)[^)#]+)\)", readme)

    assert relative_targets
    for target in relative_targets:
        assert (project_root / target).is_file(), f"README link target does not exist: {target}"


def test_docs_readme_internal_links_resolve_to_existing_files():
    project_root = Path(__file__).resolve().parents[1]
    docs_readme = (project_root / "docs" / "README.md").read_text(encoding="utf-8")
    relative_targets = re.findall(r"\[[^\]]+\]\(((?!https?://)[^)#]+)\)", docs_readme)

    assert relative_targets
    docs_root = project_root / "docs"
    for target in relative_targets:
        assert (docs_root / target).exists(), f"docs/README.md link target does not exist: {target}"


def test_readme_uses_repository_owned_links_in_links_section():
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    assert "https://kycortex.com" not in readme
    assert "https://kycortex.com/docs" not in readme
    assert "- **Repository**: [github.com/alexandrade1978/kycortex-agents](https://github.com/alexandrade1978/kycortex-agents)" in readme
    assert "- **Documentation**: [docs/README.md](docs/README.md)" in readme
    assert "KYCortex Agents is available under a dual-license model." in readme
    assert "Commercial licensing: available directly from KYCortex" in readme
    assert "- **Commercial Licensing**: [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md)" in readme
    assert "- **Contributor Rights**: [CONTRIBUTOR_RIGHTS.md](CONTRIBUTOR_RIGHTS.md)" in readme
    assert "- **Release Guide**: [RELEASE.md](RELEASE.md)" in readme
    assert "- **Release Status**: [RELEASE_STATUS.md](RELEASE_STATUS.md)" in readme
    assert "- **Changelog**: [CHANGELOG.md](CHANGELOG.md)" in readme
    assert "- **Migration Notes**: [MIGRATION.md](MIGRATION.md)" in readme
    assert "Built by Alexandre Andrade with KYCortex AI." in readme


def test_docs_readme_covers_current_public_navigation_surfaces():
    docs_readme_path = Path(__file__).resolve().parents[1] / "docs" / "README.md"
    docs_readme = docs_readme_path.read_text(encoding="utf-8")

    assert "architecture.md" in docs_readme
    assert "COMMERCIAL_LICENSE.md" in docs_readme
    assert "CONTRIBUTOR_RIGHTS.md" in docs_readme
    assert "providers.md" in docs_readme
    assert "workflows.md" in docs_readme
    assert "persistence.md" in docs_readme
    assert "extensions.md" in docs_readme
    assert "troubleshooting.md" in docs_readme
    assert "CHANGELOG.md" in docs_readme
    assert "MIGRATION.md" in docs_readme
    assert "RELEASE.md" in docs_readme
    assert "RELEASE_STATUS.md" in docs_readme
    assert "## Public API Navigation" in docs_readme
    assert "## Module Guides" in docs_readme
    assert "## Examples And Usage" in docs_readme
    assert "kycortex_agents/config.py" in docs_readme
    assert "kycortex_agents/orchestrator.py" in docs_readme
    assert "kycortex_agents/types.py" in docs_readme
    assert "kycortex_agents/exceptions.py" in docs_readme
    assert "kycortex_agents/providers" in docs_readme
    assert "kycortex_agents/memory" in docs_readme
    assert "kycortex_agents/workflows" in docs_readme
    assert "examples/example_simple_project.py" in docs_readme
    assert "examples/example_resume_workflow.py" in docs_readme
    assert "examples/example_custom_agent.py" in docs_readme
    assert "examples/example_multi_provider.py" in docs_readme
    assert "examples/example_provider_matrix_validation.py" in docs_readme
    assert "examples/example_test_mode.py" in docs_readme
    assert "examples/example_complex_workflow.py" in docs_readme
    assert "examples/example_failure_recovery.py" in docs_readme
    assert "examples/example_snapshot_inspection.py" in docs_readme
    assert "OpenAI, Anthropic, and Ollama runtime setup" in docs_readme
    assert "task dependencies, failure policies, and resume policies" in docs_readme
    assert "JSON and SQLite state files or when debugging resume behavior" in docs_readme
    assert "custom agents, registries, providers, or persistence backends" in docs_readme
    assert "debugging configuration failures, blocked workflows, retries, or persisted-state recovery" in docs_readme
    assert "persisted reload and resume behavior" in docs_readme
    assert "custom agents plug into the public runtime" in docs_readme
    assert "supported provider configurations against the same workflow definition" in docs_readme
    assert "validating workflow behavior locally without calling a live provider" in docs_readme
    assert "converging DAGs expose merged upstream artifacts and decisions" in docs_readme
    assert "persisted failed workflows reload and continue" in docs_readme
    assert "snapshot()` exposes structured task results, artifacts, decisions, and execution events while exact operator-facing observability comes from `ProjectState.internal_runtime_telemetry()`" in docs_readme
    assert "repository `Makefile` targets and shared `.editorconfig` defaults" in docs_readme
    assert "dual-license overview" in docs_readme
    assert "contributor-rights policy" in docs_readme
    assert "repository `.pre-commit-config.yaml` workflow" in docs_readme
    assert ".github/workflows/ci.yml" in docs_readme
    assert ".github/workflows/release.yml" in docs_readme
    assert "repository CI baseline for pull requests, pushes to `main`, or GitHub-hosted lint/type/test verification" in docs_readme
    assert "scripts/package_check.py" in docs_readme
    assert "scripts/release_artifact_manifest.py" in docs_readme
    assert "scripts/release_promotion_summary.py" in docs_readme
    assert "validating built wheel and source-distribution artifacts before publishing releases or changing packaging metadata" in docs_readme
    assert "staged release artifact manifest attached to tagged releases" in docs_readme
    assert "promotion provenance packet that binds the verified manifest to the release tag and promoted artifacts" in docs_readme
    assert "manual release dry runs or publishing tagged GitHub releases with attached wheel and source-distribution artifacts" in docs_readme
    assert "release notes" in docs_readme
    assert "migrating from earlier prototype revisions" in docs_readme
    assert "local `ruff` and `mypy` validation commands" in docs_readme
    assert "focused public-API, packaging/docs, and full-suite test commands" in docs_readme
    assert "repository coverage gate command" in docs_readme
    assert "scripts/release_check.py" in docs_readme
    assert "scripts/release_metadata_check.py" in docs_readme
    assert "release validation pass" in docs_readme
    assert "post-tag GitHub release workflow results" in docs_readme
    assert "current release-readiness state" in docs_readme
    assert "coverage-gate enforcement" in docs_readme


def test_changelog_documents_current_release_scope():
    changelog_path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8")
    version = kycortex_agents.__version__

    assert "# Changelog" in changelog
    assert "## Unreleased" in changelog
    assert "### Added" in changelog
    assert "### Changed" in changelog
    assert "### Release Readiness Notes" in changelog
    assert "COMMERCIAL_LICENSE.md" in changelog
    assert "CONTRIBUTOR_RIGHTS.md" in changelog
    assert "GitHub Actions CI covering linting, type checking, focused regressions, package validation, and the full pytest suite" in changelog
    assert "scripts/release_check.py" in changelog
    assert "make release-check" in changelog
    assert "RELEASE.md" in changelog
    assert "RELEASE_STATUS.md" in changelog
    assert "release-artifact-manifest.json" in changelog
    assert "release-promotion-summary.json" in changelog
    assert "scripts/release_metadata_check.py" in changelog
    assert "make release-metadata-check" in changelog
    assert "GitHub release automation" in changelog
    assert "Python 3.10 CI hardening" in changelog
    assert (
        f"Version `{version}` is now the released alpha package baseline." in changelog
        or f"Version `{version}` is now the released package baseline." in changelog
    )
    assert "shipped `1.0.0` baseline" in changelog
    assert "commercial licensing path" in changelog


def test_release_check_script_runs_repository_release_readiness_sequence():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "release_check.py"
    script = script_path.read_text(encoding="utf-8")

    assert "COMMANDS" in script
    assert '"ruff"' in script
    assert '"mypy"' in script
    assert '"focused regressions"' in script
    assert '"package validation"' in script
    assert '"release metadata"' in script
    assert '"coverage gate"' in script
    assert '"full test suite"' in script
    assert '"tests/test_public_api.py"' in script
    assert '"tests/test_public_smoke.py"' in script
    assert '"tests/test_package_metadata.py"' in script
    assert '"scripts/package_check.py"' in script
    assert '"scripts/release_metadata_check.py"' in script
    assert '"--cov=kycortex_agents"' in script
    assert '"Release readiness validation completed successfully."' in script


def test_release_artifact_manifest_script_generates_and_verifies_manifest(tmp_path):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "release_artifact_manifest.py"
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    wheel = dist_dir / "kycortex_agents-1.0.13a1-py3-none-any.whl"
    sdist = dist_dir / "kycortex_agents-1.0.13a1.tar.gz"
    wheel.write_bytes(b"wheel-bytes")
    sdist.write_bytes(b"sdist-bytes")

    manifest_path = dist_dir / "release-artifact-manifest.json"
    subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dist-dir",
            str(dist_dir),
            "--output",
            str(manifest_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1
    assert manifest["artifact_count"] == 2
    assert {artifact["name"] for artifact in manifest["artifacts"]} == {wheel.name, sdist.name}
    assert all(len(artifact["sha256"]) == 64 for artifact in manifest["artifacts"])

    verify = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dist-dir",
            str(dist_dir),
            "--manifest",
            str(manifest_path),
            "--verify",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 0
    assert "Verified release artifact manifest" in verify.stdout

    wheel.write_bytes(b"tampered-wheel-bytes")
    verify = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dist-dir",
            str(dist_dir),
            "--manifest",
            str(manifest_path),
            "--verify",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 1
    assert "does not match the current distribution artifacts" in verify.stderr


def test_release_promotion_summary_script_generates_provenance_packet(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    manifest_script_path = project_root / "scripts" / "release_artifact_manifest.py"
    summary_script_path = project_root / "scripts" / "release_promotion_summary.py"
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    wheel = dist_dir / f"kycortex_agents-{kycortex_agents.__version__}-py3-none-any.whl"
    sdist = dist_dir / f"kycortex_agents-{kycortex_agents.__version__}.tar.gz"
    wheel.write_bytes(b"wheel-bytes")
    sdist.write_bytes(b"sdist-bytes")

    manifest_path = dist_dir / "release-artifact-manifest.json"
    subprocess.run(
        [
            sys.executable,
            str(manifest_script_path),
            "--dist-dir",
            str(dist_dir),
            "--output",
            str(manifest_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary_path = dist_dir / "release-promotion-summary.json"
    create_summary = subprocess.run(
        [
            sys.executable,
            str(summary_script_path),
            "--dist-dir",
            str(dist_dir),
            "--manifest",
            str(manifest_path),
            "--tag",
            f"v{kycortex_agents.__version__}",
            "--commit-sha",
            "deadbeef",
            "--output",
            str(summary_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert create_summary.returncode == 0
    assert "Wrote release promotion summary" in create_summary.stdout

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["summary_version"] == 1
    assert summary["release_tag"] == f"v{kycortex_agents.__version__}"
    assert summary["package_version"] == kycortex_agents.__version__
    assert summary["manifest_verified"] is True
    assert summary["commit_sha"] == "deadbeef"
    assert summary["artifact_manifest"]["name"] == manifest_path.name
    assert summary["artifact_manifest"]["artifact_count"] == 2
    assert len(summary["artifact_manifest"]["sha256"]) == 64
    assert {artifact["name"] for artifact in summary["promoted_artifacts"]} == {
        wheel.name,
        sdist.name,
    }
    assert all(len(artifact["sha256"]) == 64 for artifact in summary["promoted_artifacts"])

    wheel.write_bytes(b"tampered-wheel-bytes")
    create_summary = subprocess.run(
        [
            sys.executable,
            str(summary_script_path),
            "--dist-dir",
            str(dist_dir),
            "--manifest",
            str(manifest_path),
            "--tag",
            f"v{kycortex_agents.__version__}",
            "--output",
            str(summary_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert create_summary.returncode == 1
    assert "does not match the manifest entry" in create_summary.stderr


def test_release_metadata_check_script_validates_version_and_release_docs_alignment():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "release_metadata_check.py"
    script = script_path.read_text(encoding="utf-8")

    assert "def _parse_version" in script
    assert '"pyproject.toml"' in script
    assert '"kycortex_agents/__init__.py"' in script
    assert '"RELEASE.md"' in script
    assert '"RELEASE_STATUS.md"' in script
    assert '"CHANGELOG.md"' in script
    assert '"Release target under final Phase 13 review: `([^`]+)`"' in script
    assert '"Latest released version: `([^`]+)`"' in script
    assert '"git tag v<version>"' in script
    assert '"git push origin v<version>"' in script
    assert '"RELEASE_STATUS.md must declare either a future release target or the latest released version"' in script
    assert '"Release metadata validation passed: "' in script


def test_release_guide_documents_repository_release_gate_procedure():
    release_guide_path = Path(__file__).resolve().parents[1] / "RELEASE.md"
    release_guide = release_guide_path.read_text(encoding="utf-8")

    assert "# Release Guide" in release_guide
    assert "## Preconditions" in release_guide
    assert "COMMERCIAL_LICENSE.md" in release_guide
    assert "## Local Validation" in release_guide
    assert "python scripts/release_metadata_check.py" in release_guide
    assert "make release-metadata-check" in release_guide
    assert "python scripts/release_check.py" in release_guide
    assert "make release-check" in release_guide
    assert "scripts/package_check.py" in release_guide
    assert "scripts/release_artifact_manifest.py" in release_guide
    assert "release-artifact-manifest.json" in release_guide
    assert "scripts/release_promotion_summary.py" in release_guide
    assert "release-promotion-summary.json" in release_guide
    assert "scripts/release_metadata_check.py" in release_guide
    assert "coverage gate" in release_guide
    assert "## Tagging A Release" in release_guide
    assert "git tag v<version>" in release_guide
    assert "git push origin v<version>" in release_guide
    assert ".github/workflows/release.yml" in release_guide
    assert "## Post-Tag Verification" in release_guide
    assert "## Release Gate Summary" in release_guide


def test_release_status_documents_current_repository_release_readiness_state():
    release_status_path = Path(__file__).resolve().parents[1] / "RELEASE_STATUS.md"
    release_status = release_status_path.read_text(encoding="utf-8")
    version = kycortex_agents.__version__

    assert "# Release Status" in release_status
    assert "## Current State" in release_status
    assert f"Package version in `pyproject.toml`: `{version}`" in release_status
    assert f"Latest released version: `{version}`" in release_status
    assert f"Release tag for this version: `v{version}`" in release_status
    assert "## Repository Release Gates" in release_status
    assert "python scripts/release_check.py" in release_status
    assert "make release-check" in release_status
    assert "scripts/package_check.py" in release_status
    assert "scripts/release_artifact_manifest.py" in release_status
    assert "release-artifact-manifest.json" in release_status
    assert "scripts/release_promotion_summary.py" in release_status
    assert "release-promotion-summary.json" in release_status
    assert "python scripts/release_metadata_check.py" in release_status
    assert "make release-metadata-check" in release_status
    assert ".github/workflows/release.yml" in release_status
    assert "## Latest Validated Release-Readiness Pass" in release_status
    assert "release metadata check: passing" in release_status
    assert "## Release Outcome" in release_status
    assert "COMMERCIAL_LICENSE.md" in release_status
    assert "commercial licensing path" in release_status
    assert "RELEASE.md" in release_status
    assert "CHANGELOG.md" in release_status
    assert "MIGRATION.md" in release_status
    assert "## Next Maintenance Action" in release_status
    assert "create and push the matching `v<version>` tag" in release_status


def test_migration_notes_document_public_upgrade_path():
    migration_path = Path(__file__).resolve().parents[1] / "MIGRATION.md"
    migration = migration_path.read_text(encoding="utf-8")

    assert "# Migration Notes" in migration
    assert "## Who Should Read This" in migration
    assert "## Main Migration Themes" in migration
    assert "Use the public package surface" in migration
    assert "Migrate from sequential tasks to dependency-aware workflows" in migration
    assert "Expect structured runtime state" in migration
    assert "Expect provider abstraction instead of OpenAI-only behavior" in migration
    assert "Prefer runtime-aware agents and registries" in migration
    assert "## Practical Upgrade Checklist" in migration
    assert "## Compatibility Notes" in migration
    assert "## Recommended Validation After Migration" in migration
    assert "from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task" in migration
    assert "python scripts/package_check.py" in migration


def test_docs_architecture_guide_documents_current_runtime_shape():
    architecture_path = Path(__file__).resolve().parents[1] / "docs" / "architecture.md"
    architecture = architecture_path.read_text(encoding="utf-8")

    assert "# Architecture Guide" in architecture
    assert "## Runtime Layers" in architecture
    assert "## Core Domain Contracts" in architecture
    assert "## Workflow Execution Model" in architecture
    assert "## Context Assembly" in architecture
    assert "## Persistence Model" in architecture
    assert "## Provider Layer" in architecture
    assert "## Extension Points" in architecture
    assert "Orchestrator" in architecture
    assert "ProjectState" in architecture
    assert "ProjectSnapshot" in architecture
    assert "AgentInput" in architecture
    assert "AgentOutput" in architecture
    assert "JsonStateStore" in architecture
    assert "SqliteStateStore" in architecture
    assert "OpenAIProvider" in architecture
    assert "AnthropicProvider" in architecture
    assert "OllamaProvider" in architecture


def test_docs_provider_guide_documents_current_provider_runtime():
    provider_guide_path = Path(__file__).resolve().parents[1] / "docs" / "providers.md"
    provider_guide = provider_guide_path.read_text(encoding="utf-8")

    assert "# Provider Guide" in provider_guide
    assert "## Provider Architecture" in provider_guide
    assert "## Common Contract" in provider_guide
    assert "## Provider Selection" in provider_guide
    assert "## OpenAI Configuration" in provider_guide
    assert "## Anthropic Configuration" in provider_guide
    assert "## Ollama Configuration" in provider_guide
    assert "## Runtime Validation Rules" in provider_guide
    assert "## Metadata and Observability" in provider_guide
    assert "## Error Handling" in provider_guide
    assert "## Extension Path" in provider_guide
    assert "BaseLLMProvider" in provider_guide
    assert "create_provider" in provider_guide
    assert "OPENAI_API_KEY" in provider_guide
    assert "ANTHROPIC_API_KEY" in provider_guide
    assert "http://localhost:11434" in provider_guide
    assert "AgentExecutionError" in provider_guide


def test_docs_workflow_guide_documents_current_workflow_runtime():
    workflow_guide_path = Path(__file__).resolve().parents[1] / "docs" / "workflows.md"
    workflow_guide = workflow_guide_path.read_text(encoding="utf-8")

    assert "# Workflow Guide" in workflow_guide
    assert "## Workflow Model" in workflow_guide
    assert "## Defining Tasks" in workflow_guide
    assert "## Dependency Scheduling" in workflow_guide
    assert "## Agent Resolution" in workflow_guide
    assert "## Retry Behavior" in workflow_guide
    assert "## Failure Policies" in workflow_guide
    assert "## Resume Policies" in workflow_guide
    assert "## Persistence During Execution" in workflow_guide
    assert "## Context Flow Between Tasks" in workflow_guide
    assert "## Inspecting Workflow State" in workflow_guide
    assert "## Common Configuration Patterns" in workflow_guide
    assert "## Troubleshooting Workflow Failures" in workflow_guide
    assert "ProjectState" in workflow_guide
    assert "Task" in workflow_guide
    assert "Orchestrator" in workflow_guide
    assert "retry_limit" in workflow_guide
    assert "workflow_failure_policy" in workflow_guide
    assert "workflow_resume_policy" in workflow_guide
    assert "resume_failed_tasks()" in workflow_guide


def test_docs_persistence_guide_documents_current_state_runtime():
    persistence_guide_path = Path(__file__).resolve().parents[1] / "docs" / "persistence.md"
    persistence_guide = persistence_guide_path.read_text(encoding="utf-8")

    assert "# Persistence Guide" in persistence_guide
    assert "## Persistence Model" in persistence_guide
    assert "## Backend Selection" in persistence_guide
    assert "## JSON Backend" in persistence_guide
    assert "## SQLite Backend" in persistence_guide
    assert "## Save And Load Lifecycle" in persistence_guide
    assert "## Resume And Recovery" in persistence_guide
    assert "## Snapshot Inspection" in persistence_guide
    assert "## Legacy Compatibility" in persistence_guide
    assert "## Failure Modes" in persistence_guide
    assert "## Common Patterns" in persistence_guide
    assert "ProjectState" in persistence_guide
    assert "JsonStateStore" in persistence_guide
    assert "SqliteStateStore" in persistence_guide
    assert "resolve_state_store" in persistence_guide
    assert "StatePersistenceError" in persistence_guide
    assert "workflow_resume_policy=\"resume_failed\"" in persistence_guide
    assert "snapshot()" in persistence_guide


def test_docs_extension_guide_documents_current_extension_surface():
    extension_guide_path = Path(__file__).resolve().parents[1] / "docs" / "extensions.md"
    extension_guide = extension_guide_path.read_text(encoding="utf-8")

    assert "# Extension Guide" in extension_guide
    assert "## Supported Extension Surface" in extension_guide
    assert "## Custom Agents" in extension_guide
    assert "## Lifecycle Hooks" in extension_guide
    assert "## Registry Customization" in extension_guide
    assert "## Custom Providers" in extension_guide
    assert "## Custom Persistence Backends" in extension_guide
    assert "## Orchestrator Integration" in extension_guide
    assert "## Design Boundaries" in extension_guide
    assert "## Testing Extensions" in extension_guide
    assert "BaseAgent" in extension_guide
    assert "AgentRegistry" in extension_guide
    assert "BaseLLMProvider" in extension_guide
    assert "BaseStateStore" in extension_guide
    assert "Orchestrator" in extension_guide
    assert "validate_input()" in extension_guide
    assert "after_execute()" in extension_guide
    assert "get_last_call_metadata()" in extension_guide
    assert "StatePersistenceError" in extension_guide


def test_docs_troubleshooting_guide_documents_current_failure_surface():
    troubleshooting_path = Path(__file__).resolve().parents[1] / "docs" / "troubleshooting.md"
    troubleshooting = troubleshooting_path.read_text(encoding="utf-8")

    assert "# Troubleshooting Guide" in troubleshooting
    assert "## Failure Surface Overview" in troubleshooting
    assert "## Configuration Problems" in troubleshooting
    assert "## Provider And Agent Failures" in troubleshooting
    assert "## Unknown Agents And Invalid Workflows" in troubleshooting
    assert "## Blocked Workflows" in troubleshooting
    assert "## Retries And Resume Behavior" in troubleshooting
    assert "## Persistence Failures" in troubleshooting
    assert "## Inspecting Persisted State" in troubleshooting
    assert "## Recovery Patterns" in troubleshooting
    assert "## Audit Trail Signals" in troubleshooting
    assert "## Preventive Practices" in troubleshooting
    assert "ConfigValidationError" in troubleshooting
    assert "AgentExecutionError" in troubleshooting
    assert "StatePersistenceError" in troubleshooting
    assert "WorkflowDefinitionError" in troubleshooting
    assert "workflow_blocked" in troubleshooting
    assert "workflow_resume_policy=\"resume_failed\"" in troubleshooting
    assert "snapshot()" in troubleshooting


def test_docs_readme_documents_supported_environment_variables():
    docs_readme_path = Path(__file__).resolve().parents[1] / "docs" / "README.md"
    docs_readme = docs_readme_path.read_text(encoding="utf-8")

    assert "## Environment Variables" in docs_readme
    assert "OPENAI_API_KEY" in docs_readme
    assert "ANTHROPIC_API_KEY" in docs_readme
    assert 'base_url="http://localhost:11434"' in docs_readme
    assert "These values mirror the provider mappings and defaults exported by `kycortex_agents.config`." in docs_readme


def test_requirements_file_uses_package_test_extra_as_single_source_of_truth():
    requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    requirements_lines = [
        line.strip()
        for line in requirements_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert requirements_lines == ["-e .[test]"]


def test_readme_installation_flow_uses_package_installs():
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    assert "pip install ." in readme
    assert 'pip install -e ".[test]"' in readme
    assert "pip install -r requirements.txt" not in readme


def test_readme_documents_all_supported_provider_configuration_paths():
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    assert "OPENAI_API_KEY" in readme
    assert "ANTHROPIC_API_KEY" in readme
    assert "http://localhost:11434" in readme
    assert "qwen2.5-coder:7b" in readme
    assert "ollama_num_ctx=16384" in readme
    assert 'llm_provider="openai"' in readme
    assert 'llm_provider="anthropic"' in readme
    assert 'llm_provider="ollama"' in readme


def test_readme_documents_all_public_configuration_parameters():
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    assert "### Configuration Parameters" in readme
    assert "`KYCortexConfig` exposes the following public runtime parameters:" in readme
    assert "| `llm_provider` |" in readme
    assert "| `llm_model` |" in readme
    assert "| `api_key` |" in readme
    assert "| `base_url` |" in readme
    assert "| `temperature` |" in readme
    assert "| `max_tokens` |" in readme
    assert "| `timeout_seconds` |" in readme
    assert "| `provider_timeout_seconds` |" in readme
    assert "| `workflow_failure_policy` |" in readme
    assert "| `workflow_resume_policy` |" in readme
    assert "| `project_name` |" in readme
    assert "| `output_dir` |" in readme
    assert "| `log_level` |" in readme


def test_readme_documents_current_package_layout_and_provider_support():
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    assert "Supports OpenAI, Anthropic, and Ollama" in readme
    assert "├── providers/      # Shared provider interface and implementations" in readme
    assert "│   └── state_store.py" in readme
    assert "├── workflows/      # Public workflow module surface" in readme
    assert "└── types.py        # Public typed contracts" in readme
    assert "Support for multiple LLM providers (Anthropic, local models)" not in readme


def test_readme_documents_workflow_resilience_controls():
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    assert "Supports task dependencies, topological ordering, configurable failure policies, and resumable execution" in readme
    assert 'workflow_failure_policy="continue"' in readme
    assert 'workflow_resume_policy="resume_failed"' in readme
    assert 'workflow_failure_policy="fail_fast"' in readme
    assert 'workflow_resume_policy="interrupted_only"' in readme
    assert "dependencies=[...]" in readme


def test_readme_quick_start_model_matches_packaged_example():
    project_root = Path(__file__).resolve().parents[1]
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    example = (project_root / "examples" / "example_simple_project.py").read_text(encoding="utf-8")

    assert 'config = KYCortexConfig(llm_model="gpt-4o-mini", api_key="your-key")' in readme
    assert 'llm_model="gpt-4o-mini"' in example


def test_pyproject_configures_pytest_testpaths():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    pytest_config = data["tool"]["pytest"]["ini_options"]
    assert pytest_config["testpaths"] == ["tests"]
    assert pytest_config["python_files"] == ["test_*.py"]