import argparse

from kycortex_agents.provider_matrix import (
    DEFAULT_PROVIDER_MODELS,
    _public_path_label,
    build_full_workflow_config,
    build_full_workflow_project,
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
    return parser


def build_config(
    provider: str,
    model: str,
    output_dir: str,
    *,
    workflow_failure_policy: str = "continue",
    workflow_resume_policy: str = "resume_failed",
    workflow_max_repair_cycles: int = 1,
):
    return build_full_workflow_config(
        provider,
        model,
        output_dir,
        workflow_failure_policy=workflow_failure_policy,
        workflow_resume_policy=workflow_resume_policy,
        workflow_max_repair_cycles=workflow_max_repair_cycles,
    )


def build_project(output_dir: str, provider: str):
    return build_full_workflow_project(output_dir, provider)


def main() -> None:
    args = build_parser().parse_args()
    provider = args.provider
    model = resolve_model(provider, args.model)
    output_dir = args.output_dir or f"./output/full_project_{provider}"

    config = build_config(
        provider,
        model,
        output_dir,
        workflow_failure_policy=args.failure_policy,
        workflow_resume_policy=args.resume_policy,
        workflow_max_repair_cycles=args.max_repair_cycles,
    )
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

    print(f"provider={provider}")
    print(f"model={model}")
    print(f"phase={project.phase}")
    print(f"terminal_outcome={project.terminal_outcome}")
    print(f"repair_cycles_present={_presence_label(project.repair_cycle_count)}")
    print(f"output_dir={_public_path_label(output_dir)}")
    for task in project.tasks:
        print(f"task.{task.id}.status={task.status}")


if __name__ == "__main__":
    main()