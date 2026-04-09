import argparse
from pathlib import Path
from urllib.parse import urlsplit

from kycortex_agents.provider_matrix import (
    DEFAULT_PROVIDER_MODELS,
    _public_path_label,
    build_full_workflow_config,
    build_full_workflow_project,
    execute_empirical_validation_workflow,
    get_provider_availability,
    resolve_model,
    summarize_workflow_run,
    write_summary_json,
)


def _public_ollama_base_url_label(base_url: str | None) -> str | None:
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


def _presence_label(value: object) -> str:
    return "present" if value else "none"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run empirical full-workflow validation across supported providers.",
    )
    parser.add_argument(
        "providers",
        nargs="*",
        default=None,
        metavar="provider",
        help=(
            "Providers to validate. Defaults to all supported providers: "
            + ", ".join(sorted(DEFAULT_PROVIDER_MODELS))
            + "."
        ),
    )
    parser.add_argument(
        "--output-root",
        default="./output/provider_matrix_validation",
        help="Root directory for per-provider workflow outputs and the matrix summary.",
    )
    parser.add_argument(
        "--failure-policy",
        choices=["fail_fast", "continue"],
        default="continue",
        help="Workflow failure policy for the full empirical run.",
    )
    parser.add_argument(
        "--resume-policy",
        choices=["interrupted_only", "resume_failed"],
        default="resume_failed",
        help="Workflow resume policy for the empirical run.",
    )
    parser.add_argument(
        "--max-repair-cycles",
        type=int,
        default=1,
        help="Maximum repair cycles allowed during the empirical run.",
    )
    parser.add_argument(
        "--summary-json",
        default=None,
        help="Optional custom path for the aggregated matrix summary JSON.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=None,
        help="Optional Ollama base URL override used for Ollama availability checks, model resolution, and workflow execution.",
    )
    parser.add_argument(
        "--ollama-num-ctx",
        type=int,
        default=16384,
        help="Explicit Ollama num_ctx to request during empirical Ollama runs.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=3200,
        help="Completion-token budget to request for each provider call during the empirical run.",
    )
    return parser


def resolve_requested_providers(providers: list[str] | None) -> list[str]:
    requested = providers or sorted(DEFAULT_PROVIDER_MODELS)
    normalized = [provider.strip().lower() for provider in requested]
    unsupported = sorted({provider for provider in normalized if provider not in DEFAULT_PROVIDER_MODELS})
    if unsupported:
        supported = ", ".join(sorted(DEFAULT_PROVIDER_MODELS))
        unsupported_list = ", ".join(unsupported)
        raise SystemExit(f"Unsupported providers: {unsupported_list}. Supported providers: {supported}.")
    return normalized


def run_provider(
    provider: str,
    *,
    output_root: str,
    failure_policy: str,
    resume_policy: str,
    max_repair_cycles: int,
    ollama_base_url: str | None = None,
    ollama_num_ctx: int | None = 16384,
    max_tokens: int = 3200,
) -> dict:
    if provider == "ollama":
        availability = get_provider_availability(provider, ollama_base_url=ollama_base_url)
    else:
        availability = get_provider_availability(provider)
    result = {
        "provider": provider,
        "available": availability["available"],
        "has_availability_reason": bool(availability["reason"]),
    }
    if not availability["available"]:
        result["status"] = "skipped"
        return result

    if provider == "ollama":
        model = resolve_model(provider, None, ollama_base_url=ollama_base_url)
    else:
        model = resolve_model(provider, None)
    output_dir = str(Path(output_root) / provider)
    if provider == "ollama":
        config = build_full_workflow_config(
            provider,
            model,
            output_dir,
            ollama_base_url=ollama_base_url,
            ollama_num_ctx=ollama_num_ctx,
            max_tokens=max_tokens,
            workflow_failure_policy=failure_policy,
            workflow_resume_policy=resume_policy,
            workflow_max_repair_cycles=max_repair_cycles,
        )
    else:
        config = build_full_workflow_config(
            provider,
            model,
            output_dir,
            max_tokens=max_tokens,
            workflow_failure_policy=failure_policy,
            workflow_resume_policy=resume_policy,
            workflow_max_repair_cycles=max_repair_cycles,
        )
    project = build_full_workflow_project(output_dir, provider)

    try:
        execute_empirical_validation_workflow(config, project)
    except Exception as exc:  # pragma: no cover - exercised in real provider runs when available
        result["status"] = "execution_error"
        result["error_type"] = type(exc).__name__
        result["has_error_message"] = bool(str(exc))
    else:
        result["status"] = "completed"

    result["summary"] = summarize_workflow_run(
        project,
        provider=provider,
        model=model,
        output_dir=output_dir,
    )
    return result


def main() -> None:
    args = build_parser().parse_args()
    output_root = args.output_root
    providers = resolve_requested_providers(args.providers)

    results = [
        run_provider(
            provider,
            output_root=output_root,
            failure_policy=args.failure_policy,
            resume_policy=args.resume_policy,
            max_repair_cycles=args.max_repair_cycles,
            ollama_base_url=args.ollama_base_url,
            ollama_num_ctx=args.ollama_num_ctx,
            max_tokens=args.max_tokens,
        )
        for provider in providers
    ]

    report = {
        "providers": results,
        "failure_policy": args.failure_policy,
        "resume_policy": args.resume_policy,
        "max_repair_cycles": args.max_repair_cycles,
        "ollama_base_url": _public_ollama_base_url_label(args.ollama_base_url),
        "ollama_num_ctx": args.ollama_num_ctx,
        "max_tokens": args.max_tokens,
        "output_root": _public_path_label(output_root),
    }
    summary_path = args.summary_json or str(Path(output_root) / "provider_matrix_summary.json")
    write_summary_json(report, summary_path)

    print(f"summary_json={_public_path_label(summary_path)}")
    for result in results:
        print(f"provider={_presence_label(result['provider'])}")
        print(f"available={result['available']}")
        print(f"status={result['status']}")
        if result.get("has_availability_reason"):
            print("availability_reason_present=present")
        if result.get("summary"):
            summary = result["summary"]
            print(f"phase={summary['phase']}")
            print(f"terminal_outcome={summary['terminal_outcome']}")
            print(f"repair_cycles_present={_presence_label(summary.get('repair_cycle_count'))}")


if __name__ == "__main__":
    main()