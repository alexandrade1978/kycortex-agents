import argparse
import inspect

from kycortex_agents.provider_matrix import (
    DEFAULT_PROVIDER_MODELS,
    _public_path_label,
    build_full_workflow_config,
    build_full_workflow_project_with_budgets,
    execute_empirical_validation_workflow,
    resolve_model,
    summarize_workflow_run,
    write_summary_json,
)


def _presence_label(value: object) -> str:
    return "present" if value else "none"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a full multi-agent workflow against one provider.")
    parser.add_argument("provider", choices=sorted(DEFAULT_PROVIDER_MODELS))
    parser.add_argument("--model", default=None, help="Override the default model for the provider.")
    parser.add_argument("--output-dir", default=None, help="Optional custom output directory.")
    parser.add_argument(
        "--failure-policy",
        choices=["fail_fast", "continue"],
        default="continue",
        help="Workflow failure policy for the run.",
    )
    parser.add_argument(
        "--resume-policy",
        choices=["interrupted_only", "resume_failed"],
        default="resume_failed",
        help="Workflow resume policy for the run.",
    )
    parser.add_argument(
        "--max-repair-cycles",
        type=int,
        default=1,
        help="Maximum repair cycles allowed during the run.",
    )
    parser.add_argument(
        "--summary-json",
        default=None,
        help="Optional path for a structured JSON summary of the run.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=3200,
        help="Completion-token budget to request for each provider call during the run.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=180.0,
        help="Provider request timeout in seconds used for non-Ollama providers.",
    )
    parser.add_argument(
        "--ollama-timeout-seconds",
        type=float,
        default=300.0,
        help="Ollama provider request timeout in seconds.",
    )
    parser.add_argument(
        "--code-line-budget",
        type=int,
        default=300,
        help="Maximum implementation-module line budget encoded into the code task prompt.",
    )
    parser.add_argument(
        "--test-line-budget",
        type=int,
        default=150,
        help="Maximum pytest-module line budget encoded into the tests task prompt.",
    )
    parser.add_argument(
        "--test-max-top-level-tests",
        type=int,
        default=7,
        help="Maximum top-level pytest test functions encoded into the tests task prompt.",
    )
    return parser


def build_config(
    provider: str,
    model: str,
    output_dir: str,
    *,
    workflow_failure_policy: str = "continue",
    workflow_resume_policy: str = "resume_failed",
    workflow_max_repair_cycles: int = 1,
    max_tokens: int = 3200,
    request_timeout_seconds: float = 180.0,
    ollama_timeout_seconds: float = 300.0,
):
    return build_full_workflow_config(
        provider,
        model,
        output_dir,
        max_tokens=max_tokens,
        request_timeout_seconds=request_timeout_seconds,
        ollama_timeout_seconds=ollama_timeout_seconds,
        workflow_failure_policy=workflow_failure_policy,
        workflow_resume_policy=workflow_resume_policy,
        workflow_max_repair_cycles=workflow_max_repair_cycles,
    )


def build_project(
    output_dir: str,
    provider: str,
    *,
    code_line_budget: int = 300,
    test_line_budget: int = 150,
    test_max_top_level_tests: int = 7,
):
    return build_full_workflow_project_with_budgets(
        output_dir,
        provider,
        code_line_budget=code_line_budget,
        test_line_budget=test_line_budget,
        test_max_top_level_tests=test_max_top_level_tests,
    )


def main() -> None:
    args = build_parser().parse_args()
    provider = args.provider
    model = resolve_model(provider, args.model)
    output_dir = args.output_dir or f"./output/full_project_{provider}"
    max_tokens = getattr(args, "max_tokens", 3200)
    request_timeout_seconds = getattr(args, "request_timeout_seconds", 180.0)
    ollama_timeout_seconds = getattr(args, "ollama_timeout_seconds", 300.0)
    code_line_budget = getattr(args, "code_line_budget", 300)
    test_line_budget = getattr(args, "test_line_budget", 150)
    test_max_top_level_tests = getattr(args, "test_max_top_level_tests", 7)

    config = build_config(
        provider,
        model,
        output_dir,
        workflow_failure_policy=args.failure_policy,
        workflow_resume_policy=args.resume_policy,
        workflow_max_repair_cycles=args.max_repair_cycles,
        max_tokens=max_tokens,
        request_timeout_seconds=request_timeout_seconds,
        ollama_timeout_seconds=ollama_timeout_seconds,
    )
    build_project_signature = inspect.signature(build_project)
    build_project_params = build_project_signature.parameters
    supports_budget_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in build_project_params.values()
    ) or {
        "code_line_budget",
        "test_line_budget",
        "test_max_top_level_tests",
    }.issubset(build_project_params)

    if supports_budget_kwargs:
        project = build_project(
            output_dir,
            provider,
            code_line_budget=code_line_budget,
            test_line_budget=test_line_budget,
            test_max_top_level_tests=test_max_top_level_tests,
        )
    else:
        project = build_project(output_dir, provider)

    execute_empirical_validation_workflow(config, project)

    summary = summarize_workflow_run(
        project,
        provider=provider,
        model=model,
        output_dir=output_dir,
    )
    if args.summary_json:
        write_summary_json(summary, args.summary_json)

    print(f"provider={_presence_label(provider)}")
    print(f"model={_presence_label(model)}")
    print(f"phase={project.phase}")
    print(f"terminal_outcome={project.terminal_outcome}")
    print(f"repair_cycles_present={_presence_label(project.repair_cycle_count)}")
    print(f"output_dir={_public_path_label(output_dir)}")
    for task in project.tasks:
        print(f"task.{task.id}.status={task.status}")


if __name__ == "__main__":
    main()