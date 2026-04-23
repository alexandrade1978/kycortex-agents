# KYCortex

**Open-source agent orchestration runtime and developer framework for regulated workflows**

KYCortex is an open-source agent orchestration runtime and control plane for regulated workflows. It coordinates specialized agents, provider and model routing, validation, repair cycles, and persisted workflow state so teams can build and run auditable AI-assisted delivery flows.

The package still exposes a framework and SDK layer for developers who want to compose custom agents, providers, and workflows on top of the runtime. In practice, KYCortex should be read as a runtime/platform with framework ergonomics rather than as a prompt-only helper library.

## Features

- **Orchestration core**: Coordinates agents, manages workflow state, and exposes the public control surface for task and workflow execution.
- **Provider and model routing**: Supports OpenAI, Anthropic, and Ollama through a shared provider interface with model-readiness checks, primary-provider model candidates, and fallback-provider routing.
- **Workflow resilience**: Supports task dependencies, topological ordering, configurable failure policies, and resumable execution, plus bounded repair cycles after interruptions or failed runs.
- **Validation and repair runtime**: Detects likely truncated code or test outputs, enforces task-level size and shape constraints, and feeds structured repair evidence into follow-up attempts.
- **Deterministic validation context**: Derives API, test, and dependency-manifest checks from generated artifacts so downstream agents can review against concrete runtime signals instead of prompt text alone.
- **Specialized agents**:
    - **Architect**: Designs software architecture and module structure.
    - **Code Engineer**: Writes production-quality Python code.
    - **Dependency Manager**: Produces runtime dependency manifests such as `requirements.txt` for generated projects.
    - **Code Reviewer**: Reviews code for quality, security, and best practices.
    - **QA Tester**: Generates pytest test suites.
    - **Docs Writer**: Creates README files, API docs, and tutorials.
    - **Legal Advisor**: Handles licensing, compliance, and NOTICE files.
- **Persistent project memory**: JSON and SQLite state management tracks tasks, decisions, artifacts, execution history, and provider-call metadata.
- **Extensible framework layer**: Exposes public configuration, agent, provider, workflow, and persistence seams for custom runtime integrations.

## Product Layers

KYCortex currently spans three complementary layers:

1. **Runtime / control plane**: executes agent workflows, enforces policies, persists state, and captures operator-facing telemetry.
2. **Developer framework / SDK**: provides the public Python interfaces for configuring agents, providers, workflows, and persistence backends.
3. **Reference workflow layer**: includes repository workflows such as provider-matrix validation and release-user-smoke that demonstrate how the runtime behaves on regulated-style delivery tasks.

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

For a real user-style local creation smoke against a live provider, run `examples/example_release_user_smoke.py`. It exercises the public package API, generates a small project, and validates the generated Python artifact with a sample call before reporting success.

Provider preflight validation now distinguishes backend reachability from model readiness. In practice, this means cloud providers must expose the configured model through their model-listing API before generation starts, and Ollama must expose both a reachable `/api/tags` endpoint and the configured local model.

## Configuration

Choose a provider and either pass credentials directly or rely on the provider-specific environment variable:

- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`
- Ollama: no API key required; defaults to `http://localhost:11434`

The built-in runtime now performs a provider health probe before generation. A provider can be reachable but still fail fast if the configured model is not ready for that backend.

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
    llm_model="qwen2.5-coder:7b",
    base_url="http://localhost:11434",
    ollama_num_ctx=16384,
    project_name="my-project",
    output_dir="./output"
)
```

For local Ollama runs, the repository's validated baseline is `qwen2.5-coder:7b` with `ollama_num_ctx=16384`.
The framework talks to Ollama over HTTP, so local use only requires a running Ollama server plus that model installed on the machine that serves the endpoint.
If your Ollama server is not exposed at the default `http://localhost:11434`, set `base_url` to the correct host and port.

Workflow control example:

```python
config = KYCortexConfig(
    llm_provider="openai",
    llm_model="gpt-4o-mini",
    workflow_failure_policy="continue",
    workflow_resume_policy="resume_failed",
    workflow_max_repair_cycles=1,
    project_name="my-project",
    output_dir="./output"
)
```

- `workflow_failure_policy="fail_fast"`: stop the workflow on the first terminal task failure.
- `workflow_failure_policy="continue"`: allow independent work to continue while dependency-blocked descendants are skipped.
- `workflow_resume_policy="interrupted_only"`: resume only tasks that were in flight when execution stopped.
- `workflow_resume_policy="resume_failed"`: re-queue failed tasks and dependency-skipped descendants for another run.
- `workflow_max_repair_cycles=1`: bound corrective reruns when `resume_failed` is active.

Tasks can also declare `dependencies=[...]` to build a dependency-aware workflow graph, as shown in `examples/example_simple_project.py`.

### Configuration Parameters

`KYCortexConfig` exposes the following public runtime parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `llm_provider` | `"openai"` | Selects the built-in provider backend. Supported values are `openai`, `anthropic`, and `ollama`. |
| `llm_model` | `"gpt-4o"` | Provider-specific model name used for agent execution. |
| `llm_model_candidates` | `()` | Optional ordered additional models for the primary provider. The runtime attempts `llm_model` first, then each candidate. |
| `api_key` | `None` | Optional explicit API key. When omitted, OpenAI and Anthropic fall back to `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. |
| `base_url` | `None` or Ollama default | Optional provider base URL. Ollama defaults to `http://localhost:11434`. |
| `ollama_num_ctx` | `None` | Optional Ollama-specific context window override passed as `num_ctx` in generate requests. Useful for local repair-heavy workflows that need more than the runtime default context. |
| `ollama_think` | `None` | Optional Ollama reasoning/thinking mode override. When unset, reasoning-capable Ollama models default to `think=false` in runtime requests; set explicitly to force `true` or `false`. |
| `temperature` | `0.2` | Sampling temperature validated between `0` and `2`. |
| `max_tokens` | `4096` | Maximum number of output tokens requested from the provider. For Ollama, this is forwarded as `options.num_predict`. |
| `timeout_seconds` | `60.0` | Provider request timeout in seconds. |
| `provider_timeout_seconds` | `{}` | Optional per-provider timeout overrides keyed by provider name, used for primary and fallback provider runtime configs. |
| `provider_fallback_order` | `()` | Optional ordered list of fallback providers to use when the primary provider/model path fails or is unavailable. |
| `provider_fallback_models` | `{}` | Provider-to-model mapping for fallback routing. Each value may be a single model string or an ordered model sequence for multi-model fallback per provider. |
| `workflow_failure_policy` | `"fail_fast"` | Controls whether workflow execution stops immediately or continues while skipping blocked descendants. |
| `workflow_resume_policy` | `"interrupted_only"` | Controls whether resume only re-queues interrupted tasks or also re-queues failed and dependency-skipped tasks. |
| `workflow_max_repair_cycles` | `1` | Maximum bounded repair cycles allowed when failed tasks are resumed with corrective context. |
| `provider_health_check_cooldown_seconds` | `0.0` | Reuses a recent unhealthy health snapshot during the cooldown window instead of probing the same failing backend again immediately. |
| `execution_sandbox_max_cpu_seconds` | `30.0` | CPU-time budget for generated test execution inside the sandbox. |
| `execution_sandbox_max_wall_clock_seconds` | `60.0` | Wall-clock timeout for generated test execution, independent from the CPU-time budget. |
| `execution_sandbox_max_memory_mb` | `512` | Memory ceiling for generated test execution inside the sandbox. |
| `project_name` | `"kycortex-project"` | Human-readable project name persisted into workflow state and snapshots. |
| `output_dir` | `"./output"` | Output root used for persisted artifacts and validation files. The directory is created lazily when the runtime first writes to it. |
| `log_level` | `"INFO"` | Public log-level setting reserved for orchestrator and runtime logging configuration. |

### Runtime Hardening Notes

- Built-in providers now expose model-readiness health snapshots that distinguish `backend_reachable` from `model_ready`.
- Provider metadata now preserves requested token budgets plus backend-specific stop reasons such as OpenAI `finish_reason`, Anthropic `stop_reason`, and Ollama `done_reason` when available.
- Generated code and tests are validated against task-level budgets derived from task text, including optional line limits, CLI entrypoint requirements, test-count limits, fixture budgets, and completion diagnostics for likely truncated outputs.
- Artifact persistence rejects relative-path escapes, including writes that would leave `output_dir` through symlinked directories.

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

## Runtime Boundary Model

The current architecture treats four views explicitly:

- internal persisted workflow state as the exact resume source of truth
- `ProjectSnapshot` as the public normalized read model
- `AgentView` as the prompt-facing filtered projection
- `ProjectState.internal_runtime_telemetry()` as the exact operator-facing telemetry read path

Agent prompts consume `AgentView`, not the raw `ProjectSnapshot`. Public snapshots no longer expose `workflow_telemetry`, public task results no longer expose a separate `resource_telemetry` surface, and exact runtime telemetry is intentionally available only through `ProjectState.internal_runtime_telemetry()`.

See `docs/architecture.md`, `docs/workflows.md`, and `docs/persistence.md` for the detailed boundary rules.

## Operational Readiness

Tagged package releases and production go-live are separate decisions in this repository.

- The current public line remains Alpha.
- A workflow is only successful when its declared acceptance criteria pass end to end.
- Production go-live remains blocked until the repository-owned SLO, error-budget, and staged go-live gates in `docs/go-live-policy.md` are satisfied.

Use `RELEASE.md` for package publication and `docs/go-live-policy.md` for production-readiness policy.

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
Historical canary operations and evidence are retained separately from the primary public entry surface and are not summarized here.

## License

KYCortex Agents is available under a dual-license model.

- Open-source distribution: GNU Affero General Public License v3.0 - see [LICENSE](LICENSE)
- Commercial licensing: available directly from KYCortex for teams that need proprietary deployment or terms outside AGPL - see [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md)

The published package metadata currently reflects the open-source distribution license.

## Links

- **Repository**: [github.com/alexandrade1978/kycortex-agents](https://github.com/alexandrade1978/kycortex-agents)
- **Documentation**: [docs/README.md](docs/README.md)
- **Go-Live Policy**: [docs/go-live-policy.md](docs/go-live-policy.md)
- **Commercial Licensing**: [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md)
- **Contributor Rights**: [CONTRIBUTOR_RIGHTS.md](CONTRIBUTOR_RIGHTS.md)
- **Release Guide**: [RELEASE.md](RELEASE.md)
- **Release Status**: [RELEASE_STATUS.md](RELEASE_STATUS.md)
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)
- **Migration Notes**: [MIGRATION.md](MIGRATION.md)

---

Built by Alexandre Andrade with KYCortex AI.
