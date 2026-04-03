from kycortex_agents import KYCortexConfig, ProjectState, Task
from kycortex_agents.provider_matrix import _public_path_label
from urllib.parse import urlsplit


def build_demo_project() -> ProjectState:
    project = ProjectState(
        project_name="MultiProviderDemo",
        goal="Demonstrate switching the same workflow between supported providers",
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the system architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )
    return project


def build_provider_configs() -> dict[str, KYCortexConfig]:
    return {
        "openai": KYCortexConfig(
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            api_key="your-openai-key",
            project_name="multi-provider-openai",
            output_dir="./output_multi_provider/openai",
        ),
        "anthropic": KYCortexConfig(
            llm_provider="anthropic",
            llm_model="claude-haiku-4-5-20251001",
            api_key="your-anthropic-key",
            project_name="multi-provider-anthropic",
            output_dir="./output_multi_provider/anthropic",
        ),
        "ollama": KYCortexConfig(
            llm_provider="ollama",
            llm_model="qwen2.5-coder:7b",
            base_url="http://localhost:11434",
            ollama_num_ctx=16384,
            project_name="multi-provider-ollama",
            output_dir="./output_multi_provider/ollama",
        ),
    }


def _public_base_url_label(base_url: str | None) -> str | None:
    if base_url is None:
        return None

    parsed = urlsplit(base_url)
    hostname = parsed.hostname
    if not hostname:
        return _public_path_label(base_url)

    host_label = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is None:
        return host_label
    return f"{host_label}:{parsed.port}"


def main() -> None:
    project = build_demo_project()
    configs = build_provider_configs()

    print("Same workflow, three provider configurations:\n")
    for provider_name, config in configs.items():
        print(f"Provider: {provider_name}")
        print(f"  model: {config.llm_model}")
        print(f"  output_dir: {_public_path_label(config.output_dir or '')}")
        print(f"  task_count: {len(project.tasks)}")
        if provider_name == "ollama":
            print(f"  base_url: {_public_base_url_label(config.base_url)}")
        else:
            print("  api_key: provided explicitly for demo purposes")
        print()

    print("Use one of these configurations with Orchestrator(config).execute_workflow(project).")


if __name__ == "__main__":
    main()