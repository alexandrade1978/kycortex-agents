import argparse
from pathlib import Path

from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.provider_matrix import _public_path_label


DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "ollama": "qwen2.5-coder:7b",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a minimal low-cost provider smoke workflow.",
    )
    parser.add_argument(
        "provider",
        choices=sorted(DEFAULT_MODELS),
        help="Provider to validate.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the default model for the selected provider.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional custom output directory.",
    )
    return parser


def build_config(provider: str, model: str, output_dir: str) -> KYCortexConfig:
    config = KYCortexConfig(
        llm_provider=provider,
        llm_model=model,
        ollama_num_ctx=16384 if provider == "ollama" else None,
        temperature=0.0,
        max_tokens=250,
        timeout_seconds=90.0,
        workflow_failure_policy="fail_fast",
        project_name=f"provider-smoke-{provider}",
        output_dir=output_dir,
    )
    config.validate_runtime()
    return config


def build_project(output_dir: str, provider: str) -> ProjectState:
    project = ProjectState(
        project_name=f"ProviderSmoke{provider.title()}",
        goal="Validate provider connectivity with a single minimal architecture task.",
        state_file=str(Path(output_dir) / "project_state.json"),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Produce a concise architecture note under 80 words for a single Python module that exposes one pure function.",
            assigned_to="architect",
        )
    )
    return project


def main() -> None:
    args = build_parser().parse_args()
    provider = args.provider
    model = args.model or DEFAULT_MODELS[provider]
    output_dir = args.output_dir or f"./output/provider_smoke_{provider}"

    config = build_config(provider, model, output_dir)
    project = build_project(output_dir, provider)

    Orchestrator(config).execute_workflow(project)

    task = project.tasks[0]
    print(f"provider={provider}")
    print(f"model={model}")
    print(f"phase={project.phase}")
    print(f"output_dir={_public_path_label(output_dir)}")
    print(f"task_status={task.status}")
    print("preview=")
    print((task.output or "")[:400])


if __name__ == "__main__":
    main()