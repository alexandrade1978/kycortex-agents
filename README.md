# KYCortex AI Software House

**Multi-agent orchestration framework for building AI products**

KYCortex is an open-source framework that simulates an entire AI software house with specialized agents (Architect, Code Engineer, Code Reviewer, QA Tester, Docs Writer, Legal Advisor) coordinated by an Orchestrator to build complete software products.

## Features

- **Orchestrator**: Coordinates all agents, manages workflow state, and ensures tasks are completed in order
- **Multi-provider runtime**: Supports OpenAI, Anthropic, and Ollama through a shared provider interface
- **Specialized Agents**:
  - **Architect**: Designs software architecture and module structure
  - **Code Engineer**: Writes production-quality Python code
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
config = KYCortexConfig(llm_model="gpt-4o", api_key="your-key")

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

See `examples/` for complete examples.

## Configuration

Set `OPENAI_API_KEY` environment variable or pass to `KYCortexConfig`:

```python
config = KYCortexConfig(
    llm_provider="openai",
    llm_model="gpt-4o",
    temperature=0.2,
    project_name="my-project",
    output_dir="./output"
)
```

## Architecture

```
kycortex_agents/
├── agents/         # Specialized agents and registry
│   ├── architect.py
│   ├── code_engineer.py
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

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

Apache License 2.0 - see [LICENSE](LICENSE)

## Links

- **Homepage**: [kycortex.com](https://kycortex.com)
- **Documentation**: [kycortex.com/docs](https://kycortex.com/docs)
- **GitHub**: [github.com/alexandrade1978/kycortex-agents](https://github.com/alexandrade1978/kycortex-agents)

---

**Built with ❤️ by Alexandre Andrade | Powered by KYCortex AI**
