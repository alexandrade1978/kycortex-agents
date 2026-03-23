from kycortex_agents import KYCortexConfig, ProjectState, Task


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
            llm_model="claude-3-5-sonnet-latest",
            api_key="your-anthropic-key",
            project_name="multi-provider-anthropic",
            output_dir="./output_multi_provider/anthropic",
        ),
        "ollama": KYCortexConfig(
            llm_provider="ollama",
            llm_model="llama3",
            base_url="http://localhost:11434",
            project_name="multi-provider-ollama",
            output_dir="./output_multi_provider/ollama",
        ),
    }


if __name__ == "__main__":
    project = build_demo_project()
    configs = build_provider_configs()

    print("Same workflow, three provider configurations:\n")
    for provider_name, config in configs.items():
        print(f"Provider: {provider_name}")
        print(f"  model: {config.llm_model}")
        print(f"  output_dir: {config.output_dir}")
        print(f"  task_count: {len(project.tasks)}")
        if provider_name == "ollama":
            print(f"  base_url: {config.base_url}")
        else:
            print("  api_key: provided explicitly for demo purposes")
        print()

    print("Use one of these configurations with Orchestrator(config).execute_workflow(project).")