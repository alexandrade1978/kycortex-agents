from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import traceback
from typing import Any, cast

from kycortex_agents import ProjectState, Task
from kycortex_agents.provider_matrix import (
    DEFAULT_PROVIDER_MODELS,
    build_full_workflow_config,
    execute_empirical_validation_workflow,
    get_provider_availability,
    resolve_model,
    summarize_workflow_run,
    write_summary_json,
)


@dataclass(frozen=True)
class ScenarioSpec:
    slug: str
    project_name: str
    team_name: str
    service_name: str
    request_name: str
    domain_summary: str
    goal: str
    behavior_bullets: tuple[str, ...]
    docs_focus: tuple[str, ...]
    legal_focus: tuple[str, ...]


SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        slug="kyc_compliance_intake",
        project_name="KYCComplianceIntake",
        team_name="KYC operations team",
        service_name="ComplianceIntakeService",
        request_name="ComplianceRequest",
        domain_summary="KYC and AML intake screening for regulated customer onboarding",
        goal=(
            "Build a substantial single-module Python service for a KYC operations team. "
            "The service must triage onboarding submissions, validate required evidence, score customer risk, "
            "track audit history, support batch processing, and expose a small CLI demo for analyst review."
        ),
        behavior_bullets=(
            "Validate required identity evidence and reject malformed onboarding submissions early.",
            "Score risk using jurisdiction, customer type, adverse indicators, and missing-document severity.",
            "Track auditable review outcomes such as approved, escalated, or blocked.",
            "Support batch intake while preserving per-request audit records and summaries.",
        ),
        docs_focus=(
            "analyst workflow",
            "risk scoring inputs",
            "batch review behavior",
        ),
        legal_focus=(
            "regulated onboarding records",
            "privacy and retention of customer evidence",
            "auditability of compliance decisions",
        ),
    ),
    ScenarioSpec(
        slug="insurance_claim_triage",
        project_name="InsuranceClaimTriage",
        team_name="insurance claims triage desk",
        service_name="ClaimTriageService",
        request_name="ClaimRequest",
        domain_summary="insurance claim intake, fraud triage, and audit-ready review routing",
        goal=(
            "Build a substantial single-module Python service for an insurance claim triage desk. "
            "The service must validate claim submissions, score operational and fraud risk, track review actions, "
            "support batch claim handling, and expose a small CLI demo for claim analysts."
        ),
        behavior_bullets=(
            "Validate policy identifiers, claim categories, and required claim payload fields.",
            "Increase risk for duplicate claims, high-value losses, suspicious timing, and missing evidence.",
            "Track triage outcomes such as straight-through review, manual investigation, or fraud escalation.",
            "Support batch claim review with stable per-claim results and audit logging.",
        ),
        docs_focus=(
            "claim intake rules",
            "fraud-triage logic",
            "manual investigation thresholds",
        ),
        legal_focus=(
            "claims privacy",
            "fraud investigation records",
            "distribution and audit considerations",
        ),
    ),
    ScenarioSpec(
        slug="vendor_onboarding_risk",
        project_name="VendorOnboardingRisk",
        team_name="procurement risk and vendor onboarding team",
        service_name="VendorRiskReviewService",
        request_name="VendorSubmission",
        domain_summary="vendor onboarding review with compliance, resilience, and critical-supplier risk checks",
        goal=(
            "Build a substantial single-module Python service for a procurement risk and vendor onboarding team. "
            "The service must validate vendor submissions, score onboarding risk, track review actions, support batch intake, "
            "and expose a small CLI demo for procurement analysts."
        ),
        behavior_bullets=(
            "Validate vendor profile completeness, service category, and required due-diligence evidence.",
            "Increase risk for sanctioned regions, expired certifications, critical-service flags, and unresolved incidents.",
            "Track outcomes such as approved, conditional approval, or enhanced due diligence.",
            "Support batch onboarding review while preserving per-vendor audit history.",
        ),
        docs_focus=(
            "vendor due-diligence workflow",
            "risk escalation signals",
            "conditional approval handling",
        ),
        legal_focus=(
            "supplier due-diligence records",
            "cross-border vendor data",
            "contract and compliance review traceability",
        ),
    ),
    ScenarioSpec(
        slug="returns_abuse_screening",
        project_name="ReturnsAbuseScreening",
        team_name="e-commerce returns abuse prevention team",
        service_name="ReturnScreeningService",
        request_name="ReturnCase",
        domain_summary="e-commerce return intake with abuse scoring and operations-ready review logs",
        goal=(
            "Build a substantial single-module Python service for an e-commerce returns abuse prevention team. "
            "The service must validate return cases, score abuse risk, record operational review actions, support batch handling, "
            "and expose a small CLI demo for returns investigators."
        ),
        behavior_bullets=(
            "Validate order reference, return reason, item payload, and timing details.",
            "Increase risk for serial returns, no-receipt cases, high-value electronics, and damaged-item inconsistencies.",
            "Track outcomes such as auto-approve, manual inspection, or abuse escalation.",
            "Support batch return screening with stable per-case summaries and audit records.",
        ),
        docs_focus=(
            "returns screening flow",
            "abuse indicators",
            "manual inspection routing",
        ),
        legal_focus=(
            "customer purchase data",
            "abuse investigation logs",
            "consumer-rights and operational review boundaries",
        ),
    ),
    ScenarioSpec(
        slug="access_review_audit",
        project_name="AccessReviewAudit",
        team_name="identity governance and access review board",
        service_name="AccessReviewService",
        request_name="AccessReviewRequest",
        domain_summary="privileged access review with segregation-of-duties and audit enforcement",
        goal=(
            "Build a substantial single-module Python service for an identity governance and access review board. "
            "The service must validate access-review requests, score privilege risk, record review actions, support batch review, "
            "and expose a small CLI demo for governance analysts."
        ),
        behavior_bullets=(
            "Validate requester identity, requested roles, approval metadata, and review timestamps.",
            "Increase risk for privileged roles, stale approvals, segregation-of-duties conflicts, and emergency access extensions.",
            "Track outcomes such as approved, time-boxed approval, or security escalation.",
            "Support batch access review while preserving per-request audit history and review outcomes.",
        ),
        docs_focus=(
            "access governance workflow",
            "privilege risk inputs",
            "time-boxed approval behavior",
        ),
        legal_focus=(
            "access audit records",
            "least-privilege review traceability",
            "security and privacy handling of identity data",
        ),
    ),
)


DEFAULT_OUTPUT_ROOT = "./output/real_world_complex_usage_2026_04_07"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contract_anchor(spec: ScenarioSpec) -> str:
    return (
        f"- Public facade: {spec.service_name}\n"
        f"- Primary request model: {spec.request_name}(request_id, request_type, details, timestamp)\n"
        f"- Required request workflow: {spec.service_name}.handle_request(request)\n"
        f"- Supporting validation surface: {spec.service_name}.validate_request(request)\n"
        "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases.\n"
        f"- Keep these names exact. Do not rename the facade to a generic alias or replace {spec.request_name} with guessed placeholder models.\n"
        "- Keep constructor field names exact. Do not replace request_id, request_type, details, or timestamp with guessed fields such as id, type, data, metadata, or status."
    )


def _behavior_block(spec: ScenarioSpec) -> str:
    return "\n".join(f"- {item}" for item in spec.behavior_bullets)


def _docs_focus_block(spec: ScenarioSpec) -> str:
    return "\n".join(f"- {item}" for item in spec.docs_focus)


def _legal_focus_block(spec: ScenarioSpec) -> str:
    return "\n".join(f"- {item}" for item in spec.legal_focus)


def build_project(spec: ScenarioSpec, output_dir: str) -> ProjectState:
    project = ProjectState(
        project_name=spec.project_name,
        goal=spec.goal,
        state_file=str(Path(output_dir) / "project_state.json"),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description=(
                f"Design a concrete single-module architecture for {spec.domain_summary}. "
                f"Keep the design under 350 words and focus on the needs of a {spec.team_name}. "
                "Identify the domain entities, review workflow, risk inputs, audit boundaries, and operational failure modes. "
                "Prefer one cohesive public service surface plus typed domain models over a large helper hierarchy.\n\n"
                "Required domain behavior:\n"
                f"{_behavior_block(spec)}\n\n"
                "Public contract anchor:\n"
                f"{_contract_anchor(spec)}"
            ),
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description=(
                f"Write one Python module that implements {spec.domain_summary} for a {spec.team_name}. "
                "Use only the standard library. Include typed models, request validation, risk scoring, audit logging, "
                "batch processing, and a small CLI demo entrypoint. Prefer a small but complete design with one primary service facade. "
                "Avoid speculative helper layers, unnecessary abstractions, and third-party imports. "
                "If you define dataclasses with defaults, place required non-default fields before defaulted ones. "
                "If you use field(default_factory=...), import field explicitly from dataclasses. "
                "Keep imports consistent with how you reference datetime symbols.\n\n"
                "Required domain behavior:\n"
                f"{_behavior_block(spec)}\n\n"
                "Public contract anchor:\n"
                f"{_contract_anchor(spec)}\n\n"
                "Return raw Python only."
            ),
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="deps",
            title="Dependencies",
            description=(
                f"Infer the minimal runtime requirements.txt for the generated {spec.domain_summary} module. "
                "List only third-party runtime packages that are actually required, and prefer an empty manifest when the module uses only the standard library."
            ),
            assigned_to="dependency_manager",
            dependencies=["code"],
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description=(
                f"Write one compact raw pytest module for the generated {spec.domain_summary} module. "
                "Keep the suite concise and stable: target 4 to 6 top-level tests, at most 3 fixtures, and clear headroom below 180 lines. "
                "Include at least one happy path, one validation failure, one risk-scoring assertion, one batch-processing scenario, and one audit-trail assertion. "
                "Prefer directly observable outcomes over guessed internal implementation details. "
                "Do not import or test CLI entrypoints. Do not invent helper classes, renamed APIs, or missing fields. "
                "If you use the pytest namespace, import pytest explicitly.\n\n"
                "Required domain behavior:\n"
                f"{_behavior_block(spec)}\n\n"
                "Public contract anchor:\n"
                f"{_contract_anchor(spec)}\n\n"
                "Return raw Python only."
            ),
            assigned_to="qa_tester",
            dependencies=["code", "deps"],
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description=(
                f"Review the generated implementation, dependency manifest, and tests for correctness, maintainability, "
                f"and operational realism for {spec.domain_summary}. Keep the review concise and actionable."
            ),
            assigned_to="code_reviewer",
            dependencies=["tests"],
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description=(
                f"Write an engineer-facing README for the generated {spec.domain_summary} module. "
                "Cover setup, usage, core workflow, assumptions, extension points, and operational notes.\n\n"
                "Focus areas:\n"
                f"{_docs_focus_block(spec)}"
            ),
            assigned_to="docs_writer",
            dependencies=["review"],
        )
    )
    project.add_task(
        Task(
            id="legal",
            title="Legal",
            description=(
                f"Provide a concise legal and compliance note for the generated {spec.domain_summary} module. "
                "Cover data handling, privacy, audit, licensing assumptions, and distribution considerations.\n\n"
                "Focus areas:\n"
                f"{_legal_focus_block(spec)}"
            ),
            assigned_to="legal_advisor",
            dependencies=["docs"],
        )
    )
    return project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run five real-world complex end-to-end workflow scenarios across supported providers.",
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
        "--scenarios",
        nargs="*",
        default=None,
        metavar="scenario",
        help="Optional subset of scenario slugs to run.",
    )
    parser.add_argument(
        "--output-root",
        default=DEFAULT_OUTPUT_ROOT,
        help="Root directory for scenario/provider outputs and aggregated summaries.",
    )
    parser.add_argument(
        "--failure-policy",
        choices=["fail_fast", "continue"],
        default="continue",
        help="Workflow failure policy for each scenario run.",
    )
    parser.add_argument(
        "--resume-policy",
        choices=["interrupted_only", "resume_failed"],
        default="resume_failed",
        help="Workflow resume policy for each scenario run.",
    )
    parser.add_argument(
        "--max-repair-cycles",
        type=int,
        default=1,
        help="Maximum repair cycles allowed during each scenario run.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default="http://127.0.0.1:11435",
        help="Ollama base URL used for availability checks, model resolution, and workflow execution.",
    )
    parser.add_argument(
        "--ollama-num-ctx",
        type=int,
        default=16384,
        help="Explicit Ollama num_ctx to request during Ollama runs.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=3200,
        help="Completion-token budget to request for each provider call.",
    )
    parser.add_argument(
        "--summary-json",
        default=None,
        help="Optional custom path for the aggregated JSON summary.",
    )
    parser.add_argument(
        "--summary-md",
        default=None,
        help="Optional custom path for the aggregated Markdown summary.",
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


def resolve_requested_scenarios(scenarios: list[str] | None) -> list[ScenarioSpec]:
    if not scenarios:
        return list(SCENARIOS)
    by_slug = {scenario.slug: scenario for scenario in SCENARIOS}
    requested = [scenario.strip().lower() for scenario in scenarios]
    unknown = sorted({slug for slug in requested if slug not in by_slug})
    if unknown:
        supported = ", ".join(sorted(by_slug))
        unknown_list = ", ".join(unknown)
        raise SystemExit(f"Unsupported scenarios: {unknown_list}. Supported scenarios: {supported}.")
    return [by_slug[slug] for slug in requested]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_scenario_provider(
    spec: ScenarioSpec,
    provider: str,
    *,
    output_root: Path,
    failure_policy: str,
    resume_policy: str,
    max_repair_cycles: int,
    ollama_base_url: str | None,
    ollama_num_ctx: int | None,
    max_tokens: int,
    run_index: int,
    total_runs: int,
) -> dict[str, object]:
    if provider == "ollama":
        availability = get_provider_availability(provider, ollama_base_url=ollama_base_url)
        model = resolve_model(provider, None, ollama_base_url=ollama_base_url)
    else:
        availability = get_provider_availability(provider)
        model = resolve_model(provider, None)
    run_root = output_root / spec.slug / provider
    run_root.mkdir(parents=True, exist_ok=True)

    result: dict[str, object] = {
        "scenario": spec.slug,
        "scenario_title": spec.project_name,
        "provider": provider,
        "available": availability["available"],
        "availability_reason": availability["reason"],
        "model": model,
        "output_dir": str(run_root),
        "started_at": _utc_now_iso(),
    }

    print(
        f"[{run_index}/{total_runs}] scenario={spec.slug} provider={provider} model={model} available={availability['available']}",
        flush=True,
    )

    if not availability["available"]:
        result["status"] = "skipped"
        result["completed_at"] = _utc_now_iso()
        result["duration_seconds"] = 0.0
        _write_json(run_root / "run_result.json", result)
        print(
            f"[{run_index}/{total_runs}] scenario={spec.slug} provider={provider} status=skipped reason={availability['reason']}",
            flush=True,
        )
        return result

    if provider == "ollama":
        config = build_full_workflow_config(
            provider,
            model,
            str(run_root),
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
            str(run_root),
            max_tokens=max_tokens,
            workflow_failure_policy=failure_policy,
            workflow_resume_policy=resume_policy,
            workflow_max_repair_cycles=max_repair_cycles,
        )
    project = build_project(spec, str(run_root))

    started = time.perf_counter()
    try:
        execute_empirical_validation_workflow(config, project)
    except Exception as exc:  # pragma: no cover - exercised in real provider runs
        result["status"] = "execution_error"
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)
        result["traceback"] = traceback.format_exc()
    else:
        result["status"] = "completed"

    result["duration_seconds"] = round(time.perf_counter() - started, 3)
    result["completed_at"] = _utc_now_iso()
    result["summary"] = summarize_workflow_run(
        project,
        provider=provider,
        model=model,
        output_dir=str(run_root),
    )
    _write_json(run_root / "run_result.json", result)
    print(
        f"[{run_index}/{total_runs}] scenario={spec.slug} provider={provider} status={result['status']} phase={result['summary']['phase']} terminal={result['summary']['terminal_outcome']}",
        flush=True,
    )
    return result


def _aggregate_counts(runs: list[dict[str, object]], key: str) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for run in runs:
        label = str(run[key])
        status = str(run["status"])
        bucket = counts.setdefault(label, {"completed": 0, "execution_error": 0, "skipped": 0})
        bucket[status] = bucket.get(status, 0) + 1
    return counts


def build_markdown_summary(report: dict[str, object]) -> str:
    report_providers = cast(list[str], report["providers"])
    report_scenarios = cast(list[str], report["scenario_order"])
    report_runs = cast(list[dict[str, Any]], report["runs"])
    report_provider_totals = cast(dict[str, dict[str, int]], report["provider_totals"])
    report_scenario_totals = cast(dict[str, dict[str, int]], report["scenario_totals"])
    lines = [
        "# Real-World Complex Usage Campaign",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Output root: {report['output_root']}",
        f"- Providers: {', '.join(report_providers)}",
        f"- Scenarios: {', '.join(report_scenarios)}",
        f"- Total runs: {report['total_runs']}",
        "",
        "## Run Matrix",
        "",
        "| Scenario | Provider | Status | Phase | Terminal Outcome | Duration (s) | Repair History Entries |",
        "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for run in report_runs:
        summary = cast(dict[str, Any], run.get("summary") or {})
        repair_history = cast(list[object], summary.get("repair_history") or [])
        lines.append(
            "| {scenario} | {provider} | {status} | {phase} | {terminal} | {duration} | {repair_count} |".format(
                scenario=run["scenario"],
                provider=run["provider"],
                status=run["status"],
                phase=summary.get("phase", "n/a"),
                terminal=summary.get("terminal_outcome", "n/a"),
                duration=run.get("duration_seconds", 0.0),
                repair_count=len(repair_history),
            )
        )
    lines.extend(
        [
            "",
            "## Provider Totals",
            "",
            "| Provider | Completed | Execution Error | Skipped |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for provider, counts in report_provider_totals.items():
        lines.append(
            f"| {provider} | {counts.get('completed', 0)} | {counts.get('execution_error', 0)} | {counts.get('skipped', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Scenario Totals",
            "",
            "| Scenario | Completed | Execution Error | Skipped |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for scenario, counts in report_scenario_totals.items():
        lines.append(
            f"| {scenario} | {counts.get('completed', 0)} | {counts.get('execution_error', 0)} | {counts.get('skipped', 0)} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = build_parser().parse_args()
    providers = resolve_requested_providers(args.providers)
    scenarios = resolve_requested_scenarios(args.scenarios)
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    total_runs = len(providers) * len(scenarios)
    runs: list[dict[str, object]] = []
    run_index = 0

    for scenario in scenarios:
        for provider in providers:
            run_index += 1
            runs.append(
                run_scenario_provider(
                    scenario,
                    provider,
                    output_root=output_root,
                    failure_policy=args.failure_policy,
                    resume_policy=args.resume_policy,
                    max_repair_cycles=args.max_repair_cycles,
                    ollama_base_url=args.ollama_base_url,
                    ollama_num_ctx=args.ollama_num_ctx,
                    max_tokens=args.max_tokens,
                    run_index=run_index,
                    total_runs=total_runs,
                )
            )

    report = {
        "generated_at": _utc_now_iso(),
        "output_root": str(output_root),
        "providers": providers,
        "scenario_order": [scenario.slug for scenario in scenarios],
        "total_runs": total_runs,
        "provider_totals": _aggregate_counts(runs, "provider"),
        "scenario_totals": _aggregate_counts(runs, "scenario"),
        "runs": runs,
    }

    summary_json_path = Path(args.summary_json).resolve() if args.summary_json else output_root / "campaign_summary.json"
    summary_md_path = Path(args.summary_md).resolve() if args.summary_md else output_root / "campaign_summary.md"
    write_summary_json(report, str(summary_json_path))
    _write_markdown(summary_md_path, build_markdown_summary(report))

    print(f"campaign_summary_json={summary_json_path.name}", flush=True)
    print(f"campaign_summary_md={summary_md_path.name}", flush=True)


if __name__ == "__main__":
    main()