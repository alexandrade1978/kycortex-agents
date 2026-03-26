# KYCortex AI Software House

**Multi-agent orchestration framework for building AI products**

KYCortex is an open-source framework that simulates an entire AI software house with specialized agents (Architect, Code Engineer, Dependency Manager, Code Reviewer, QA Tester, Docs Writer, Legal Advisor) coordinated by an Orchestrator to build complete software products.

## Features

- **Orchestrator**: Coordinates all agents, manages workflow state, and ensures tasks are completed in order
- **Multi-provider runtime**: Supports OpenAI, Anthropic, and Ollama through a shared provider interface
- **Workflow resilience**: Supports task dependencies, topological ordering, configurable failure policies, and resumable execution after interruptions or failed runs
- **Deterministic validation context**: Derives API, test, and dependency-manifest checks from generated artifacts so downstream agents can review against concrete signals instead of prompt text alone
- **Specialized Agents**:
  - **Architect**: Designs software architecture and module structure
  - **Code Engineer**: Writes production-quality Python code
    - **Dependency Manager**: Produces runtime dependency manifests such as requirements.txt for generated projects
  - **Code Reviewer**: Reviews code for quality, security, and best practices
  - **QA Tester**: Generates pytest test suites
  - **Docs Writer**: Creates README, API docs, tutorials
  - **Legal Advisor**: Handles licensing, compliance, NOTICE files
- **Project Memory**: Persistent JSON and SQLite state management tracks tasks, decisions, artifacts, and execution history
- **Extensible**: Easy to add new agents or customize workflows

## Installation

```bash
# Clone repository
git clone https://github.com/alexandrade1978/kycortex-agents.git
cd kycortex-agents

# Install the package
pip install .

# Or install the editable test environment for local development
pip install -e ".[test]"
```

## Quick Start

```python
from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task

# Configure
config = KYCortexConfig(llm_model="gpt-4o-mini", api_key="your-key")

# Define project
project = ProjectState(
    project_name="MyApp",
    goal="Build a FastAPI app with user authentication"
)

# Add tasks
project.add_task(Task(
    id="arch", title="Architecture",
    description="Design system architecture",
    assigned_to="architect"
))

# Run
orch = Orchestrator(config)
orch.execute_workflow(project)
```

See `examples/` for complete examples, including `example_provider_matrix_validation.py` for resume-enabled empirical provider validation across the supported runtimes.

## Configuration

Choose a provider and either pass credentials directly or rely on the provider-specific environment variable:

- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`
- Ollama: no API key required; defaults to `http://localhost:11434`

OpenAI example:

```python
config = KYCortexConfig(
    llm_provider="openai",
    llm_model="gpt-4o-mini",
    temperature=0.2,
    project_name="my-project",
    output_dir="./output"
)
```

Anthropic example:

```python
config = KYCortexConfig(
    llm_provider="anthropic",
    llm_model="claude-haiku-4-5-20251001",
    temperature=0.2,
    project_name="my-project",
    output_dir="./output"
)
```

Ollama example:

```python
config = KYCortexConfig(
    llm_provider="ollama",
    llm_model="llama3",
    base_url="http://localhost:11434",
    project_name="my-project",
    output_dir="./output"
)
```

Workflow control example:

```python
config = KYCortexConfig(
    llm_provider="openai",
    llm_model="gpt-4o-mini",
    workflow_failure_policy="continue",
    workflow_resume_policy="resume_failed",
    project_name="my-project",
    output_dir="./output"
)
```

- `workflow_failure_policy="fail_fast"`: stop the workflow on the first terminal task failure.
- `workflow_failure_policy="continue"`: allow independent work to continue while dependency-blocked descendants are skipped.
- `workflow_resume_policy="interrupted_only"`: resume only tasks that were in flight when execution stopped.
- `workflow_resume_policy="resume_failed"`: re-queue failed tasks and dependency-skipped descendants for another run.

Tasks can also declare `dependencies=[...]` to build a dependency-aware workflow graph, as shown in `examples/example_simple_project.py`.

### Configuration Parameters

`KYCortexConfig` exposes the following public runtime parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `llm_provider` | `"openai"` | Selects the built-in provider backend. Supported values are `openai`, `anthropic`, and `ollama`. |
| `llm_model` | `"gpt-4o"` | Provider-specific model name used for agent execution. |
| `api_key` | `None` | Optional explicit API key. When omitted, OpenAI and Anthropic fall back to `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. |
| `base_url` | `None` or Ollama default | Optional provider base URL. Ollama defaults to `http://localhost:11434`. |
| `temperature` | `0.2` | Sampling temperature validated between `0` and `2`. |
| `max_tokens` | `4096` | Maximum number of output tokens requested from the provider. |
| `timeout_seconds` | `60.0` | Provider request timeout in seconds. |
| `provider_timeout_seconds` | `{}` | Optional per-provider timeout overrides keyed by provider name, used for primary and fallback provider runtime configs. |
| `workflow_failure_policy` | `"fail_fast"` | Controls whether workflow execution stops immediately or continues while skipping blocked descendants. |
| `workflow_resume_policy` | `"interrupted_only"` | Controls whether resume only re-queues interrupted tasks or also re-queues failed and dependency-skipped tasks. |
| `project_name` | `"kycortex-project"` | Human-readable project name persisted into workflow state and snapshots. |
| `output_dir` | `"./output"` | Output directory created during configuration initialization and used to persist artifact files emitted by agents. |
| `log_level` | `"INFO"` | Public log-level setting reserved for orchestrator and runtime logging configuration. |

## Architecture

```
kycortex_agents/
├── agents/         # Specialized agents and registry
│   ├── architect.py
│   ├── code_engineer.py
│   ├── dependency_manager.py
│   ├── code_reviewer.py
│   ├── qa_tester.py
│   ├── docs_writer.py
│   ├── legal_advisor.py
│   └── registry.py
├── memory/         # State management and persistence backends
│   ├── project_state.py
│   └── state_store.py
├── providers/      # Shared provider interface and implementations
│   ├── base.py
│   ├── factory.py
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   └── ollama_provider.py
├── workflows/      # Public workflow module surface
├── orchestrator.py # Main coordinator
├── config.py       # Global config
├── exceptions.py   # Public exception hierarchy
└── types.py        # Public typed contracts
```

## Roadmap

- [ ] Add vector store for long-term memory
- [ ] Web UI for project monitoring
- [ ] Agent templates for specific domains (MLOps, LLMOps)
- [ ] Integration with CI/CD pipelines

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow guidance and [CONTRIBUTOR_RIGHTS.md](CONTRIBUTOR_RIGHTS.md) for contributor-rights expectations under the dual-license model.

## Releases

Use [RELEASE.md](RELEASE.md) for the repository-owned release validation and tagging procedure.
Use [RELEASE_STATUS.md](RELEASE_STATUS.md) for the current repository release-state snapshot.

## License

KYCortex Agents is available under a dual-license model.

- Open-source distribution: GNU Affero General Public License v3.0 - see [LICENSE](LICENSE)
- Commercial licensing: available directly from KYCortex for teams that need proprietary deployment or terms outside AGPL - see [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md)

The published package metadata currently reflects the open-source distribution license.

## Links

- **Repository**: [github.com/alexandrade1978/kycortex-agents](https://github.com/alexandrade1978/kycortex-agents)
- **Documentation**: [docs/README.md](docs/README.md)
- **Commercial Licensing**: [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md)
- **Contributor Rights**: [CONTRIBUTOR_RIGHTS.md](CONTRIBUTOR_RIGHTS.md)
- **Release Guide**: [RELEASE.md](RELEASE.md)
- **Release Status**: [RELEASE_STATUS.md](RELEASE_STATUS.md)
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)
- **Migration Notes**: [MIGRATION.md](MIGRATION.md)

---

Built by Alexandre Andrade with KYCortex AI.
