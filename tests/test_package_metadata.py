from pathlib import Path
import re
import subprocess
import sys
import tomllib

import kycortex_agents


def _refresh_generated_egg_info() -> Path:
    project_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps", "--quiet"],
        cwd=project_root,
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
    assert project["license"]["text"] == "AGPL-3.0-only"
    assert "Typing :: Typed" in project["classifiers"]
    assert "License :: OSI Approved :: GNU Affero General Public License v3" in project["classifiers"]
    assert "anthropic>=0.34.0,<1.0.0" in project["dependencies"]
    assert "openai>=1.0.0,<2.0.0" in project["dependencies"]
    assert data["project"]["urls"]["Homepage"] == "https://github.com/alexandrade1978/kycortex-agents"
    assert data["project"]["urls"]["Documentation"].endswith("/docs/README.md")


def test_pyproject_version_matches_package_version_constant():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert data["project"]["version"] == kycortex_agents.__version__


def test_pyproject_declares_test_extra():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    optional_dependencies = data["project"]["optional-dependencies"]
    assert optional_dependencies["test"] == ["pytest>=7.0.0"]


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


def test_manifest_in_exists_and_covers_core_distribution_assets():
    project_root = Path(__file__).resolve().parents[1]
    manifest_path = project_root / "MANIFEST.in"

    assert manifest_path.is_file()

    manifest = manifest_path.read_text(encoding="utf-8")
    assert "include LICENSE" in manifest
    assert "include README.md" in manifest
    assert "include CONTRIBUTING.md" in manifest
    assert "recursive-include docs *.md" in manifest
    assert "recursive-include examples *.py" in manifest
    assert "recursive-include kycortex_agents py.typed" in manifest


def test_generated_egg_info_metadata_matches_current_package_contract():
    egg_info_dir = _refresh_generated_egg_info()
    metadata = (egg_info_dir / "PKG-INFO").read_text(encoding="utf-8")
    requirements = (egg_info_dir / "requires.txt").read_text(encoding="utf-8")

    assert "Project-URL: Documentation, https://github.com/alexandrade1978/kycortex-agents/blob/main/docs/README.md" in metadata
    assert "Requires-Dist: anthropic<1.0.0,>=0.34.0" in metadata
    assert "Requires-Dist: openai<2.0.0,>=1.0.0" in metadata
    assert "Requires-Dist: pytest>=7.0.0; extra == \"test\"" in metadata
    assert "https://kycortex.com" not in metadata
    assert "from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task" in metadata
    assert "OPENAI_API_KEY" in metadata
    assert "ANTHROPIC_API_KEY" in metadata
    assert "anthropic<1.0.0,>=0.34.0" in requirements
    assert "openai<2.0.0,>=1.0.0" in requirements


def test_generated_egg_info_sources_include_current_distribution_assets():
    egg_info_dir = _refresh_generated_egg_info()
    members = set((egg_info_dir / "SOURCES.txt").read_text(encoding="utf-8").splitlines())

    expected_members = {
        "CONTRIBUTING.md",
        "docs/README.md",
        "examples/example_custom_agent.py",
        "examples/example_multi_provider.py",
        "examples/example_resume_workflow.py",
        "examples/example_simple_project.py",
        "examples/example_test_mode.py",
        "kycortex_agents/exceptions.py",
        "kycortex_agents/py.typed",
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
    assert (project_root / "docs" / "README.md").is_file()


def test_contributing_guide_documents_test_command_tiers():
    contributing_path = Path(__file__).resolve().parents[1] / "CONTRIBUTING.md"
    contributing = contributing_path.read_text(encoding="utf-8")

    assert "Suggested Test Commands" in contributing
    assert "tests/test_public_api.py tests/test_public_smoke.py -q" in contributing
    assert "tests/test_package_metadata.py -q" in contributing
    assert "python -m pytest -q" in contributing


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
    assert "Built by Alexandre Andrade with KYCortex AI." in readme


def test_docs_readme_covers_current_public_navigation_surfaces():
    docs_readme_path = Path(__file__).resolve().parents[1] / "docs" / "README.md"
    docs_readme = docs_readme_path.read_text(encoding="utf-8")

    assert "architecture.md" in docs_readme
    assert "providers.md" in docs_readme
    assert "workflows.md" in docs_readme
    assert "persistence.md" in docs_readme
    assert "extensions.md" in docs_readme
    assert "troubleshooting.md" in docs_readme
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
    assert "examples/example_test_mode.py" in docs_readme
    assert "OpenAI, Anthropic, and Ollama runtime setup" in docs_readme
    assert "task dependencies, failure policies, and resume policies" in docs_readme
    assert "JSON and SQLite state files or when debugging resume behavior" in docs_readme
    assert "custom agents, registries, providers, or persistence backends" in docs_readme
    assert "debugging configuration failures, blocked workflows, retries, or persisted-state recovery" in docs_readme
    assert "persisted reload and resume behavior" in docs_readme
    assert "custom agents plug into the public runtime" in docs_readme
    assert "supported provider configurations against the same workflow definition" in docs_readme
    assert "validating workflow behavior locally without calling a live provider" in docs_readme
    assert "focused public-API, packaging/docs, and full-suite test commands" in docs_readme


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