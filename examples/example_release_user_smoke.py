import argparse
import importlib.util
from pathlib import Path
import py_compile

from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task


DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "ollama": "qwen2.5-coder:7b",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a realistic user-style project creation smoke workflow.",
    )
    parser.add_argument(
        "provider",
        nargs="?",
        default="ollama",
        choices=sorted(DEFAULT_MODELS),
        help="Provider to validate. Defaults to ollama.",
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
    parser.add_argument(
        "--base-url",
        default=None,
        help="Optional provider base URL override. Useful for Ollama on a custom port.",
    )
    parser.add_argument(
        "--ollama-num-ctx",
        type=int,
        default=16384,
        help="Explicit Ollama num_ctx to request during local smoke runs.",
    )
    parser.add_argument(
        "--failure-policy",
        choices=["fail_fast", "continue"],
        default="continue",
        help="Workflow failure policy for the smoke run.",
    )
    parser.add_argument(
        "--max-repair-cycles",
        type=int,
        default=1,
        help="Maximum repair cycles allowed during the smoke run.",
    )
    return parser


def build_config(args: argparse.Namespace, output_dir: str) -> KYCortexConfig:
    provider = args.provider
    model = args.model or DEFAULT_MODELS[provider]
    config_kwargs = {
        "llm_provider": provider,
        "llm_model": model,
        "temperature": 0.0,
        "max_tokens": 700,
        "timeout_seconds": 180.0,
        "workflow_failure_policy": args.failure_policy,
        "workflow_max_repair_cycles": args.max_repair_cycles,
        "project_name": f"release-user-smoke-{provider}",
        "output_dir": output_dir,
    }
    if args.base_url:
        config_kwargs["base_url"] = args.base_url
    if provider == "ollama":
        config_kwargs["ollama_num_ctx"] = args.ollama_num_ctx

    config = KYCortexConfig(**config_kwargs)
    config.validate_runtime()
    return config


def build_project(output_dir: str, provider: str) -> ProjectState:
    project = ProjectState(
        project_name=f"ReleaseUserSmoke{provider.title()}",
        goal=(
            "Create a single-file Python budget planner that exposes a function named "
            "`calculate_budget_balance(income: float, expenses: list[float]) -> float` and a minimal CLI entrypoint."
        ),
        state_file=str(Path(output_dir) / "project_state.json"),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description=(
                "Design a concise single-module architecture for a Python budget planner that exposes "
                "`calculate_budget_balance(income: float, expenses: list[float]) -> float`, one formatting helper, and a minimal CLI entrypoint. "
                "Keep the architecture practical and compact."
            ),
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description=(
                "Implement the planned single-file Python budget planner using only the standard library. "
                "The module must expose `calculate_budget_balance(income: float, expenses: list[float]) -> float` and a working `main()` CLI entrypoint."
            ),
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description=(
                "Review the generated budget planner for correctness, API clarity, and obvious edge cases."
            ),
            assigned_to="code_reviewer",
            dependencies=["code"],
        )
    )
    return project


def _artifact_paths(task: Task) -> list[str]:
    payload = task.output_payload if isinstance(task.output_payload, dict) else {}
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return []
    paths: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("path")
        if isinstance(path, str) and path.strip():
            paths.append(path)
    return paths


def _preview_text(text: str, limit: int = 500) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n..."


def _code_artifact_path(task: Task, output_dir: str) -> Path | None:
    for relative_path in _artifact_paths(task):
        if relative_path.endswith(".py"):
            return Path(output_dir) / relative_path
    return None


def _validate_generated_code(task: Task, output_dir: str) -> tuple[float, str]:
    artifact_path = _code_artifact_path(task, output_dir)
    if artifact_path is None or not artifact_path.exists():
        raise RuntimeError("Generated code artifact was not found.")

    py_compile.compile(str(artifact_path), doraise=True)

    spec = importlib.util.spec_from_file_location("release_user_smoke_generated", artifact_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load generated code artifact: {artifact_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    calculate_budget_balance = getattr(module, "calculate_budget_balance", None)
    if not callable(calculate_budget_balance):
        raise RuntimeError("Generated code did not expose calculate_budget_balance().")

    main = getattr(module, "main", None)
    if not callable(main):
        raise RuntimeError("Generated code did not expose main().")

    sample_balance = calculate_budget_balance(5000.0, [1200.0, 700.0, 450.0])
    if not isinstance(sample_balance, (int, float)):
        raise RuntimeError("calculate_budget_balance() did not return a numeric balance.")

    return float(sample_balance), str(artifact_path)


def main() -> None:
    args = build_parser().parse_args()
    output_dir = args.output_dir or f"./output/release_user_smoke_{args.provider}"

    config = build_config(args, output_dir)
    project = build_project(output_dir, args.provider)

    Orchestrator(config).execute_workflow(project)

    print(f"provider={args.provider}")
    print(f"model={config.llm_model}")
    print(f"phase={project.phase}")
    print(f"terminal_outcome={project.terminal_outcome}")
    print(f"repair_cycle_count={project.repair_cycle_count}")
    print(f"output_dir={output_dir}")
    print()

    for task in project.tasks:
        print(f"task={task.id}")
        print(f"status={task.status}")
        artifact_paths = _artifact_paths(task)
        if artifact_paths:
            print("artifacts=")
            for path in artifact_paths:
                print(path)
        preview = _preview_text(task.output or "")
        if preview:
            print("preview=")
            print(preview)
        print("---")

    code_task = next((task for task in project.tasks if task.id == "code"), None)
    if code_task is None:
        raise SystemExit("Smoke workflow did not create a code task.")

    sample_balance, artifact_path = _validate_generated_code(code_task, output_dir)
    print("artifact_validation=passed")
    print(f"validated_artifact={artifact_path}")
    print(f"sample_balance={sample_balance:.2f}")


if __name__ == "__main__":
    main()