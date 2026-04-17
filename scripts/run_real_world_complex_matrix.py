from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import inspect
import json
from pathlib import Path
import py_compile
import sys
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
from kycortex_agents.types import FailureCategory, TaskStatus, WorkflowOutcome


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
    detail_contract_bullets: tuple[str, ...]
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
        detail_contract_bullets=(
            "Keep canonical details keys exact for this scenario: identity_evidence, jurisdiction, customer_type, adverse_indicators, and missing_documents.",
            "Keep identity_evidence as the evidence collection inside details. Do not replace it with guessed aliases such as identity_proof, address_proof, documents, or document_list.",
            "Keep jurisdiction and customer_type as strings. Keep identity_evidence, adverse_indicators, and missing_documents as list-like collections inside details, not numeric severity placeholders or plain strings.",
            "When details is not a dict, reject it immediately in validate_request (return False) and raise ValueError in handle_request. Never fall back to default values for non-dict details.",
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
        detail_contract_bullets=(
            "Keep canonical details keys exact for this scenario: policy_id, claim_category, claim_amount, evidence, duplicate_claim, and suspicious_timing.",
            "Keep evidence as the supporting-evidence field inside details. Do not replace it with guessed aliases such as documents, attachments, or proofs.",
            "Keep policy_id and claim_category as strings, claim_amount as a numeric amount, evidence as a list-like collection, and duplicate_claim plus suspicious_timing as boolean flags.",
            'The request_type value in test payloads is "claim". Accept it as-is — do not restrict request_type to an invented whitelist such as ("submit", "review", "escalate").',
            'The claim_category field accepts free-form string labels such as "water_damage" or "theft". Do not restrict it to an invented whitelist of categories.',
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
        detail_contract_bullets=(
            "Keep canonical details keys exact for this scenario: vendor_name, service_category, due_diligence_evidence, sanctioned_region, expired_certifications, critical_service, and unresolved_incidents.",
            "Keep due_diligence_evidence as the evidence collection inside details. Do not replace it with guessed aliases such as certifications, documents, or compliance_docs.",
            "Keep sanctioned_region and critical_service as boolean flags. Keep expired_certifications and unresolved_incidents as list-like collections, using [] when absent and explicit list entries when risk is present.",
            'The request_type value in test payloads is "vendor_submission". Accept it as-is — do not restrict request_type to an invented whitelist such as ("initial_onboarding", "renewal", "incident_review").',
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
        detail_contract_bullets=(
            "Keep canonical details keys exact for this scenario: order_reference, return_reason, items, receipt_present, prior_returns, and timing_days.",
            "Keep items as the item payload collection inside details. Do not replace it with guessed aliases such as products, order_items, or return_lines.",
            "Keep order_reference and return_reason as strings, receipt_present as a boolean flag, and prior_returns plus timing_days as integers. Keep items as a list-like collection of item payload records, not a plain string placeholder.",
            "Each record inside items is a dict with exactly the keys sku (str), category (str), and value (numeric). Do not rename value to price, amount, or cost.",
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
        detail_contract_bullets=(
            "Keep canonical details keys exact for this scenario: requester_identity, requested_roles, approval_metadata, sod_conflicts, emergency_access, and stale_approval.",
            "Keep requested_roles and approval_metadata exact inside details. Do not replace them with guessed aliases such as roles, approvals, or approver_metadata.",
            "Keep requester_identity as a string, requested_roles and sod_conflicts as list-like collections, approval_metadata as a mapping object, and emergency_access plus stale_approval as boolean flags.",
            "The approval_metadata mapping contains exactly the keys approved_by (str) and age_days (int). Do not invent additional required sub-keys such as approval_date, approved_at, or approval_timestamp.",
            "When details is not a dict, reject it immediately in validate_request (return False) and raise ValueError in handle_request. Never fall back to default values for non-dict details.",
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
_SCENARIO_REQUEST_FIELDS = ("request_id", "request_type", "details", "timestamp")
_ZERO_BUDGET_FAILURE_CATEGORIES = frozenset({FailureCategory.SANDBOX_SECURITY_VIOLATION.value})
_SCENARIO_PRODUCTIVITY_CHECKS = frozenset(
    {
        "syntax_valid",
        "service_constructor_supported",
        "request_signature_supported",
        "validation_surface_supported",
        "batch_processing_supported",
    }
)
_SCENARIO_REAL_WORKFLOW_CHECKS = frozenset(
    {
        "valid_request_accepted",
        "invalid_request_rejected",
        "risk_signal_observable",
        "audit_signal_present",
    }
)
_SCENARIO_SAFETY_CHECKS = frozenset({"stdlib_only"})
_RESULT_STATUSES = ("completed", "validation_error", "execution_error", "skipped")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contract_anchor(spec: ScenarioSpec) -> str:
    return (
        f"- Public facade: {spec.service_name}\n"
        f"- Primary request model: {spec.request_name}(request_id, request_type, details, timestamp)\n"
        f"- Required request workflow: {spec.service_name}.handle_request(request)\n"
        f"- Supporting validation surface: {spec.service_name}.validate_request(request)\n"
        "- validate_request(request) must return a plain bool (True for valid, False for invalid). Do not return a tuple, a dataclass, or a validation-result object — return exactly True or False.\n"
        "- The details field of every request is always a plain dict (Dict[str, Any]). Access detail values through dict indexing (details['key']) or details.get('key'), never through attribute access (details.key). Do not define a custom dataclass or NamedTuple for the details payload.\n"
        "- validate_request must return False immediately when details is not a dict. Do not gracefully handle non-dict details (e.g. a plain string); treat any non-dict value as an invalid request.\n"
        "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases.\n"
        f"- Keep these names exact. Do not rename the facade to a generic alias or replace {spec.request_name} with guessed placeholder models.\n"
        "- Keep constructor field names exact. Do not replace request_id, request_type, details, or timestamp with guessed fields such as id, type, data, metadata, or status.\n"
        f"- Keep {spec.service_name} instantiable with zero required constructor arguments. Initialize internal audit or review state inside __init__ instead of requiring callers to pass audit_history, collaborators, repositories, or other mutable state containers.\n"
        "- The timestamp field of every request is a datetime object (from the datetime module), not a float, int, or string. Validate it with isinstance(request.timestamp, datetime).\n"
        "- The request_type field is a free-form string label. Accept any non-empty string — do not restrict it to an invented whitelist of allowed values."
    )


def _details_contract_block(spec: ScenarioSpec) -> str:
    return "\n".join(f"- {item}" for item in spec.detail_contract_bullets)


def _test_fixture_contract_block(spec: ScenarioSpec) -> str:
    return "\n".join(
        (
            f"- Every {spec.request_name} fixture in the test suite must construct details as a literal dict with populated field values.",
            "- Never pass details as a plain string, a space-separated list of field names, or a placeholder. The implementation expects a dict and will fail on string input.",
            "- Example of CORRECT fixture: details={'field_one': ['value'], 'field_two': 'value', 'field_three': []}",
            "- Example of WRONG fixture: details='field_one field_two field_three'",
        )
    )


def _observable_outcome_contract_block() -> str:
    return "\n".join(
        (
            "- handle_request(request) must return a per-request outcome object or dict, not None.",
            "- The returned outcome must make the review decision and risk signal observable to callers, for example through outcome and risk_score style fields or equivalent structured keys.",
            "- Preserve audit evidence either in the returned outcome or on a service audit history surface that accumulates one auditable entry per processed request.",
            "- Do not treat a logging side effect alone or a None return as sufficient happy-path or batch behavior.",
        )
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
                f"{_contract_anchor(spec)}\n\n"
                "Canonical details contract:\n"
                f"{_details_contract_block(spec)}\n\n"
                "Observable outcome contract:\n"
                f"{_observable_outcome_contract_block()}"
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
                "Canonical details contract:\n"
                f"{_details_contract_block(spec)}\n\n"
                "Observable outcome contract:\n"
                f"{_observable_outcome_contract_block()}\n\n"
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
                "Canonical details contract:\n"
                f"{_details_contract_block(spec)}\n\n"
                "Test fixture contract:\n"
                f"{_test_fixture_contract_block(spec)}\n\n"
                "Observable outcome contract:\n"
                f"{_observable_outcome_contract_block()}\n\n"
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
        default="http://127.0.0.1:11434",
        help="Ollama base URL used for availability checks, model resolution, and workflow execution.",
    )
    parser.add_argument(
        "--ollama-num-ctx",
        type=int,
        default=16384,
        help="Explicit Ollama num_ctx to request during Ollama runs.",
    )
    parser.add_argument(
        "--ollama-think",
        type=str,
        choices=["true", "false"],
        default=None,
        help="Control Ollama thinking mode. 'false' disables thinking tokens for faster inference.",
    )
    parser.add_argument(
        "--ollama-model",
        default=None,
        help="Override the Ollama model to use instead of the auto-resolved default.",
    )
    parser.add_argument(
        "--ollama-timeout-seconds",
        type=float,
        default=300.0,
        help="Per-call timeout budget to request for Ollama provider calls during Ollama runs.",
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


def _code_artifact_path(task: Task, output_dir: str) -> Path | None:
    for relative_path in _artifact_paths(task):
        if relative_path.endswith(".py"):
            return Path(output_dir) / relative_path
    return None


def _unsupported_non_stdlib_imports(artifact_path: Path) -> list[str]:
    code_content = artifact_path.read_text(encoding="utf-8")
    module_ast = ast.parse(code_content, filename=str(artifact_path))
    stdlib_modules = frozenset(getattr(sys, "stdlib_module_names", ()))
    unsupported_imports: set[str] = set()

    for node in ast.walk(module_ast):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".", 1)[0]
                if top_level != "__future__" and top_level not in stdlib_modules:
                    unsupported_imports.add(top_level)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                unsupported_imports.add("relative import")
                continue
            top_level = (node.module or "").split(".", 1)[0]
            if top_level and top_level != "__future__" and top_level not in stdlib_modules:
                unsupported_imports.add(top_level)

    return sorted(unsupported_imports)


def _public_artifact_label(artifact_path: Path | None) -> str | None:
    if artifact_path is None:
        return None
    return artifact_path.name


def _public_validation_error_message(error: Exception, artifact_path: Path | None) -> str:
    message = str(error)
    if artifact_path is not None:
        message = message.replace(str(artifact_path), artifact_path.name)
    return message


def _callable_supports_leading_parameters(
    callable_obj: object,
    expected_parameter_names: tuple[str, ...],
) -> bool:
    if not callable(callable_obj):
        return False
    signature = inspect.signature(callable_obj)
    parameters = list(signature.parameters.values())
    if len(parameters) < len(expected_parameter_names):
        return False
    for parameter, expected_name in zip(parameters, expected_parameter_names, strict=True):
        if parameter.name != expected_name:
            return False
        if parameter.kind not in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            return False
    for parameter in parameters[len(expected_parameter_names) :]:
        if parameter.default is inspect.Parameter.empty:
            return False
    return True


def _instantiate_service(service_cls: type[Any], service_name: str) -> Any:
    signature = inspect.signature(service_cls)
    for parameter in signature.parameters.values():
        if parameter.kind not in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            raise RuntimeError(
                f"Generated code exposed {service_name} with unsupported constructor parameters."
            )
        if parameter.default is inspect.Parameter.empty:
            raise RuntimeError(
                f"Generated code exposed {service_name} with required constructor parameters."
            )
    return service_cls()


def _scenario_request_payloads(spec: ScenarioSpec) -> dict[str, dict[str, Any]]:
    timestamp = datetime(2026, 4, 13, 0, 0, tzinfo=timezone.utc)
    if spec.slug == "kyc_compliance_intake":
        request_type = "individual"
        low_details = {
            "identity_evidence": ["passport", "proof_of_address"],
            "jurisdiction": "pt",
            "customer_type": "individual",
            "adverse_indicators": [],
            "missing_documents": [],
        }
        high_details = {
            "identity_evidence": ["passport"],
            "jurisdiction": "sanctioned",
            "customer_type": "corporate",
            "adverse_indicators": ["pep", "watchlist_hit"],
            "missing_documents": ["beneficial_owner_register"],
        }
    elif spec.slug == "insurance_claim_triage":
        request_type = "claim"
        low_details = {
            "policy_id": "POL-1001",
            "claim_category": "water_damage",
            "claim_amount": 1200,
            "evidence": ["invoice", "photos"],
            "duplicate_claim": False,
            "suspicious_timing": False,
        }
        high_details = {
            "policy_id": "POL-2009",
            "claim_category": "theft",
            "claim_amount": 95000,
            "evidence": ["statement"],
            "duplicate_claim": True,
            "suspicious_timing": True,
        }
    elif spec.slug == "vendor_onboarding_risk":
        request_type = "vendor_submission"
        low_details = {
            "vendor_name": "Acme Logistics",
            "service_category": "courier",
            "due_diligence_evidence": ["iso27001", "soc2"],
            "sanctioned_region": False,
            "expired_certifications": [],
            "critical_service": False,
            "unresolved_incidents": [],
        }
        high_details = {
            "vendor_name": "Frontier Ops",
            "service_category": "critical_infrastructure",
            "due_diligence_evidence": ["insurance_certificate"],
            "sanctioned_region": True,
            "expired_certifications": ["iso27001"],
            "critical_service": True,
            "unresolved_incidents": ["sev1", "sev2", "sev3"],
        }
    elif spec.slug == "returns_abuse_screening":
        request_type = "return_case"
        low_details = {
            "order_reference": "ORD-1001",
            "return_reason": "damaged_item",
            "items": [{"sku": "SKU-1", "category": "home", "value": 45}],
            "receipt_present": True,
            "prior_returns": 0,
            "timing_days": 5,
        }
        high_details = {
            "order_reference": "ORD-9001",
            "return_reason": "changed_mind",
            "items": [{"sku": "SKU-9", "category": "electronics", "value": 1800}],
            "receipt_present": False,
            "prior_returns": 8,
            "timing_days": 89,
        }
    else:
        request_type = "access_review"
        low_details = {
            "requester_identity": "alice",
            "requested_roles": ["reader"],
            "approval_metadata": {"approved_by": "manager", "age_days": 2},
            "sod_conflicts": [],
            "emergency_access": False,
            "stale_approval": False,
        }
        high_details = {
            "requester_identity": "bob",
            "requested_roles": ["admin", "payments_release"],
            "approval_metadata": {"approved_by": "manager", "age_days": 45},
            "sod_conflicts": ["approver_and_requester"],
            "emergency_access": True,
            "stale_approval": True,
        }
    return {
        "low": {
            "request_id": f"{spec.slug}-low",
            "request_type": request_type,
            "details": low_details,
            "timestamp": timestamp,
        },
        "high": {
            "request_id": f"{spec.slug}-high",
            "request_type": request_type,
            "details": high_details,
            "timestamp": timestamp,
        },
        "invalid": {
            "request_id": f"{spec.slug}-invalid",
            "request_type": request_type,
            "details": "invalid-details",
            "timestamp": timestamp,
        },
    }


def _build_request(request_cls: type[Any], payload: dict[str, Any]) -> Any:
    return request_cls(
        request_id=payload["request_id"],
        request_type=payload["request_type"],
        details=payload["details"],
        timestamp=payload["timestamp"],
    )


def _build_request_or_capture_error(
    request_cls: type[Any],
    payload: dict[str, Any],
) -> tuple[Any | None, Exception | None]:
    try:
        return _build_request(request_cls, payload), None
    except Exception as exc:
        return None, exc


def _observable_value(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return repr(value)


def _observable_service_state(service: Any) -> dict[str, str]:
    if not hasattr(service, "__dict__"):
        return {}
    observable: dict[str, str] = {}
    for name, value in vars(service).items():
        if name.startswith("_"):
            continue
        observable[name] = _observable_value(value)
    return observable


def _audit_attribute_names(service: Any) -> list[str]:
    if not hasattr(service, "__dict__"):
        return []
    names: list[str] = []
    for name, value in vars(service).items():
        lowered = name.lower()
        if name.startswith("_"):
            continue
        if any(token in lowered for token in ("audit", "history", "log")) and bool(value):
            names.append(name)
    return sorted(names)


def _outcomes_expose_audit_signal(*outcomes: Any) -> bool:
    joined = " ".join(_observable_value(outcome).lower() for outcome in outcomes)
    return any(token in joined for token in ("audit", "review", "approved", "blocked", "escalat"))


_PROGRAMMING_ERROR_TYPES: tuple[type[BaseException], ...] = (
    UnboundLocalError,
    NameError,
    AttributeError,
    TypeError,
)


def _coerce_validation_bool(result: Any) -> bool:
    """Extract a boolean from a ``validate_request`` return value.

    Generated services may return a plain ``bool``, a ``(bool, errors)``
    tuple, a ``{"valid": bool, ...}`` dict, or any other truthy/falsy
    value.  This helper normalises all of those shapes into a single
    boolean so that the downstream validation checks work regardless of
    the chosen return convention.
    """
    if isinstance(result, tuple) and len(result) >= 1:
        return bool(result[0])
    if isinstance(result, dict) and "valid" in result:
        return bool(result["valid"])
    return bool(result)


def _invalid_request_is_rejected(validate_request: Any, handle_request: Any, invalid_request: Any) -> bool:
    try:
        validation_result = validate_request(invalid_request)
    except Exception:
        return True
    if not _coerce_validation_bool(validation_result):
        return True
    try:
        handle_request(invalid_request)
    except Exception:
        return True
    return False


def _handle_request_survives_invalid(
    service_cls: type[Any],
    service_name: str,
    request_cls: type[Any],
    invalid_payload: dict[str, Any],
    *,
    tolerate_type_confusion: bool = False,
) -> tuple[bool, str | None]:
    """Return *(ok, error_detail)*.

    Instantiates a fresh service and calls ``handle_request`` with an
    invalid request built from *invalid_payload*.  The implementation
    may raise a deliberate ``ValueError``/``KeyError`` or return a
    degraded outcome — both are acceptable.  What is *not* acceptable
    is a programming-level crash such as ``UnboundLocalError`` or
    ``NameError``, which reveals a code-generation defect that the LLM
    bounded-repair cycle often fails to fix.

    When *tolerate_type_confusion* is ``True``, ``AttributeError`` is
    also treated as an acceptable implicit rejection.  This is used for
    payloads that deliberately violate the type contract (e.g. passing a
    string where a dict is expected), where ``details.get(...)`` raising
    ``AttributeError`` is a reasonable type-boundary response rather
    than a code-generation defect.
    """
    try:
        invalid_request = request_cls(
            request_id=invalid_payload["request_id"],
            request_type=invalid_payload["request_type"],
            details=invalid_payload["details"],
            timestamp=invalid_payload["timestamp"],
        )
    except Exception:
        # Constructor itself rejects the request — acceptable.
        return True, None
    svc = _instantiate_service(service_cls, service_name)
    try:
        svc.handle_request(invalid_request)
    except _PROGRAMMING_ERROR_TYPES as exc:
        if tolerate_type_confusion and isinstance(exc, AttributeError):
            return True, None
        return False, f"{type(exc).__name__}: {exc}"
    except Exception:
        # Deliberate rejection (ValueError, KeyError, etc.) — acceptable.
        return True, None
    return True, None


def _observed_failure_categories(project: ProjectState) -> set[str]:
    categories: set[str] = set()
    if isinstance(project.failure_category, str) and project.failure_category:
        categories.add(project.failure_category)
    for task in project.tasks:
        if isinstance(task.last_error_category, str) and task.last_error_category:
            categories.add(task.last_error_category)
    return categories


def _task_acceptance_lists(project: ProjectState, acceptance_policy: str) -> dict[str, list[str]]:
    if acceptance_policy == "required_tasks":
        evaluated_tasks = [task for task in project.tasks if task.required_for_acceptance]
    else:
        evaluated_tasks = list(project.tasks)
    return {
        "evaluated_task_ids": [task.id for task in evaluated_tasks],
        "required_task_ids": [task.id for task in project.tasks if task.required_for_acceptance],
        "completed_task_ids": [task.id for task in evaluated_tasks if task.status == TaskStatus.DONE.value],
        "failed_task_ids": [task.id for task in evaluated_tasks if task.status == TaskStatus.FAILED.value],
        "skipped_task_ids": [task.id for task in evaluated_tasks if task.status == TaskStatus.SKIPPED.value],
        "pending_task_ids": [
            task.id
            for task in evaluated_tasks
            if task.status not in {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.SKIPPED.value}
        ],
    }


def _checks_pass(checks: dict[str, bool], required_checks: frozenset[str]) -> bool:
    return all(bool(checks.get(check_name)) for check_name in required_checks)


def _composite_acceptance_evaluation(
    project: ProjectState,
    *,
    acceptance_policy: str,
    scenario_validation: dict[str, Any],
) -> dict[str, Any]:
    base_evaluation = dict(project.acceptance_evaluation) if isinstance(project.acceptance_evaluation, dict) else {}
    base_evaluation.setdefault("policy", acceptance_policy)
    for key, values in _task_acceptance_lists(project, acceptance_policy).items():
        base_evaluation.setdefault(key, values)

    checks = scenario_validation.get("checks") if isinstance(scenario_validation, dict) else {}
    checks = checks if isinstance(checks, dict) else {}
    base_productivity_accepted = bool(base_evaluation.get("accepted", project.acceptance_criteria_met))
    productivity_accepted = base_productivity_accepted and _checks_pass(checks, _SCENARIO_PRODUCTIVITY_CHECKS)
    real_workflow_accepted = _checks_pass(checks, _SCENARIO_REAL_WORKFLOW_CHECKS)
    observed_failure_categories = _observed_failure_categories(project)
    safety_accepted = _checks_pass(checks, _SCENARIO_SAFETY_CHECKS) and not (
        observed_failure_categories & _ZERO_BUDGET_FAILURE_CATEGORIES
    )

    productivity_reason = str(base_evaluation.get("reason") or "evaluated_tasks_incomplete")
    if base_productivity_accepted and not productivity_accepted:
        productivity_reason = "productivity_validation_failed"
    real_workflow_reason = (
        "scenario_contract_validated" if real_workflow_accepted else "scenario_validation_failed"
    )
    safety_reason = "no_zero_budget_incident_detected"
    if not safety_accepted:
        safety_reason = "safety_validation_failed"

    lanes = {
        "productivity": {"accepted": productivity_accepted, "reason": productivity_reason},
        "real_workflow": {"accepted": real_workflow_accepted, "reason": real_workflow_reason},
        "safety": {"accepted": safety_accepted, "reason": safety_reason},
    }
    failed_lane_ids = [lane_id for lane_id, lane in lanes.items() if not lane["accepted"]]
    accepted = not failed_lane_ids
    reason = productivity_reason if not productivity_accepted else (
        "scenario_validation_failed" if not real_workflow_accepted else (
            "safety_validation_failed" if not safety_accepted else productivity_reason
        )
    )

    base_evaluation["accepted"] = accepted
    base_evaluation["reason"] = reason
    base_evaluation["acceptance_lanes"] = lanes
    base_evaluation["failed_lane_ids"] = failed_lane_ids
    base_evaluation["scenario_validation"] = scenario_validation
    return base_evaluation


def _validate_generated_scenario(spec: ScenarioSpec, task: Task, output_dir: str) -> dict[str, Any]:
    artifact_path = _code_artifact_path(task, output_dir)
    checks = {
        "syntax_valid": False,
        "stdlib_only": False,
        "service_constructor_supported": False,
        "request_signature_supported": False,
        "validation_surface_supported": False,
        "valid_request_accepted": False,
        "invalid_request_rejected": False,
        "invalid_request_handled": False,
        "risk_signal_observable": False,
        "audit_signal_present": False,
        "batch_processing_supported": False,
    }
    result: dict[str, Any] = {
        "validated": False,
        "artifact_path": _public_artifact_label(artifact_path),
        "service_name": spec.service_name,
        "request_name": spec.request_name,
        "checks": checks,
        "error": None,
        "observations": {},
    }

    try:
        if artifact_path is None or not artifact_path.exists():
            raise RuntimeError("Generated code artifact was not found.")

        py_compile.compile(str(artifact_path), doraise=True)
        checks["syntax_valid"] = True

        unsupported_imports = _unsupported_non_stdlib_imports(artifact_path)
        if unsupported_imports:
            raise RuntimeError(
                "Generated code used unsupported non-standard-library imports: "
                f"{', '.join(unsupported_imports)}."
            )
        checks["stdlib_only"] = True

        module_name = f"{spec.slug}_scenario_validation_generated"
        module_spec = importlib.util.spec_from_file_location(module_name, artifact_path)
        if module_spec is None or module_spec.loader is None:
            raise RuntimeError(f"Could not load generated code artifact: {artifact_path.name}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)

        service_cls = getattr(module, spec.service_name, None)
        if not inspect.isclass(service_cls):
            raise RuntimeError(f"Generated code did not expose {spec.service_name}.")
        request_cls = getattr(module, spec.request_name, None)
        if not inspect.isclass(request_cls):
            raise RuntimeError(f"Generated code did not expose {spec.request_name}.")

        _instantiate_service(service_cls, spec.service_name)
        checks["service_constructor_supported"] = True

        if not _callable_supports_leading_parameters(request_cls, _SCENARIO_REQUEST_FIELDS):
            raise RuntimeError(
                f"Generated code exposed {spec.request_name} with an incompatible constructor signature."
            )
        checks["request_signature_supported"] = True

        request_payloads = _scenario_request_payloads(spec)
        low_request = _build_request(request_cls, request_payloads["low"])
        high_request = _build_request(request_cls, request_payloads["high"])
        invalid_request, invalid_request_error = _build_request_or_capture_error(
            request_cls,
            request_payloads["invalid"],
        )

        validation_service = _instantiate_service(service_cls, spec.service_name)
        validate_request = getattr(validation_service, "validate_request", None)
        handle_request = getattr(validation_service, "handle_request", None)
        if not _callable_supports_leading_parameters(validate_request, ("request",)):
            raise RuntimeError(f"Generated code exposed {spec.service_name}.validate_request(...) with an incompatible signature.")
        if not _callable_supports_leading_parameters(handle_request, ("request",)):
            raise RuntimeError(f"Generated code exposed {spec.service_name}.handle_request(...) with an incompatible signature.")
        validate_request = cast(Any, validate_request)
        handle_request = cast(Any, handle_request)
        checks["validation_surface_supported"] = True

        valid_validation_result = validate_request(low_request)
        if not _coerce_validation_bool(valid_validation_result):
            raise RuntimeError("Generated code did not accept a valid scenario request through validate_request(...).")
        checks["valid_request_accepted"] = True

        invalid_request_rejected = invalid_request_error is not None
        if invalid_request_error is None:
            invalid_request_rejected = _invalid_request_is_rejected(
                validate_request,
                handle_request,
                invalid_request,
            )
        if not invalid_request_rejected:
            raise RuntimeError("Generated code did not reject a malformed scenario request.")
        checks["invalid_request_rejected"] = True

        # Verify that handle_request does not crash with programming errors
        # when given a request whose details are incomplete (the most common
        # invalid-path shape produced by generated tests).
        partial_details = dict(list(request_payloads["low"]["details"].items())[:2])
        partial_invalid_payload = {
            "request_id": f"{spec.slug}-partial-invalid",
            "request_type": request_payloads["low"]["request_type"],
            "details": partial_details,
            "timestamp": request_payloads["low"]["timestamp"],
        }
        survived, prog_error = _handle_request_survives_invalid(
            service_cls, spec.service_name, request_cls, partial_invalid_payload,
        )
        if not survived:
            raise RuntimeError(
                f"Generated code crashed with a programming error when handling an "
                f"invalid request: {prog_error}"
            )
        # Also verify the fully-invalid payload (details as a string).
        if invalid_request_error is None:
            survived_full, prog_error_full = _handle_request_survives_invalid(
                service_cls, spec.service_name, request_cls, request_payloads["invalid"],
                tolerate_type_confusion=True,
            )
            if not survived_full:
                raise RuntimeError(
                    f"Generated code crashed with a programming error when handling a "
                    f"malformed request: {prog_error_full}"
                )
        checks["invalid_request_handled"] = True

        low_service = _instantiate_service(service_cls, spec.service_name)
        low_outcome = low_service.handle_request(low_request)
        high_service = _instantiate_service(service_cls, spec.service_name)
        high_outcome = high_service.handle_request(high_request)
        low_state = _observable_service_state(low_service)
        high_state = _observable_service_state(high_service)
        observations: dict[str, Any] = {
            "low_outcome": _observable_value(low_outcome),
            "high_outcome": _observable_value(high_outcome),
        }
        result["observations"] = observations
        if _observable_value(low_outcome) == _observable_value(high_outcome) and low_state == high_state:
            raise RuntimeError(
                "Generated code did not expose an observable difference between low-risk and high-risk requests."
            )
        checks["risk_signal_observable"] = True

        batch_service = _instantiate_service(service_cls, spec.service_name)
        batch_service.handle_request(low_request)
        batch_service.handle_request(high_request)
        checks["batch_processing_supported"] = True

        audit_attributes = _audit_attribute_names(batch_service)
        observations["audit_attributes"] = list(audit_attributes)
        if not audit_attributes and not _outcomes_expose_audit_signal(low_outcome, high_outcome):
            raise RuntimeError(
                "Generated code did not expose audit history or review records after handling scenario requests."
            )
        checks["audit_signal_present"] = True

        result["validated"] = True
        return result
    except Exception as exc:
        result["error"] = _public_validation_error_message(exc, artifact_path)
        return result


def _scenario_validation_not_run(reason: str) -> dict[str, Any]:
    return {
        "validated": False,
        "not_run_reason": reason,
        "checks": {},
        "error": None,
    }


def _apply_scenario_validation(
    spec: ScenarioSpec,
    *,
    project: ProjectState,
    output_dir: str,
    acceptance_policy: str,
) -> dict[str, Any]:
    code_task = project.get_task("code")
    if code_task is None:
        return _scenario_validation_not_run("missing_code_task")

    scenario_validation = _validate_generated_scenario(spec, code_task, output_dir)
    acceptance_evaluation = _composite_acceptance_evaluation(
        project,
        acceptance_policy=acceptance_policy,
        scenario_validation=scenario_validation,
    )
    accepted = bool(acceptance_evaluation.get("accepted"))

    if accepted:
        project.acceptance_evaluation = acceptance_evaluation
        project.acceptance_criteria_met = True
        project.save()
        return scenario_validation

    project.mark_workflow_finished(
        "completed",
        acceptance_policy=acceptance_policy,
        terminal_outcome=WorkflowOutcome.DEGRADED.value,
        failure_category=FailureCategory.SCENARIO_VALIDATION.value,
        acceptance_criteria_met=False,
        acceptance_evaluation=acceptance_evaluation,
    )
    project.save()
    return scenario_validation


def run_scenario_provider(
    spec: ScenarioSpec,
    provider: str,
    *,
    output_root: Path,
    failure_policy: str,
    resume_policy: str,
    max_repair_cycles: int,
    ollama_base_url: str | None,
    ollama_model: str | None = None,
    ollama_num_ctx: int | None,
    ollama_think: bool | None = None,
    ollama_timeout_seconds: float = 300.0,
    max_tokens: int,
    run_index: int,
    total_runs: int,
) -> dict[str, object]:
    if provider == "ollama":
        availability = get_provider_availability(provider, ollama_base_url=ollama_base_url)
        model = resolve_model(provider, ollama_model, ollama_base_url=ollama_base_url)
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
        result["scenario_validation"] = _scenario_validation_not_run("provider_unavailable")
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
            ollama_think=ollama_think,
            ollama_timeout_seconds=ollama_timeout_seconds,
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
        result["scenario_validation"] = _scenario_validation_not_run("workflow_execution_failed")
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)
        result["traceback"] = traceback.format_exc()
    else:
        result["status"] = "completed"
        if project.phase == "completed" and project.acceptance_criteria_met:
            scenario_validation = _apply_scenario_validation(
                spec,
                project=project,
                output_dir=str(run_root),
                acceptance_policy=config.workflow_acceptance_policy,
            )
            result["scenario_validation"] = scenario_validation
            if not project.acceptance_criteria_met:
                result["status"] = "validation_error"
        else:
            result["scenario_validation"] = _scenario_validation_not_run("workflow_not_accepted")

    result["duration_seconds"] = round(time.perf_counter() - started, 3)
    result["completed_at"] = _utc_now_iso()
    result["summary"] = summarize_workflow_run(
        project,
        provider=provider,
        model=model,
        output_dir=str(run_root),
    )
    result["acceptance_criteria_met"] = project.acceptance_criteria_met
    result["failure_category"] = project.failure_category
    if isinstance(project.acceptance_evaluation, dict):
        result["acceptance_reason"] = project.acceptance_evaluation.get("reason")
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
        bucket = counts.setdefault(label, {name: 0 for name in _RESULT_STATUSES})
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
        "| Scenario | Provider | Status | Phase | Terminal Outcome | Accepted | Scenario Validation | Duration (s) | Repair History Entries |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for run in report_runs:
        summary = cast(dict[str, Any], run.get("summary") or {})
        repair_history = cast(list[object], summary.get("repair_history") or [])
        scenario_validation = cast(dict[str, Any], run.get("scenario_validation") or {})
        validation_status = "not_run"
        if scenario_validation.get("validated") is True:
            validation_status = "passed"
        elif scenario_validation.get("error"):
            validation_status = "failed"
        lines.append(
            "| {scenario} | {provider} | {status} | {phase} | {terminal} | {accepted} | {validation} | {duration} | {repair_count} |".format(
                scenario=run["scenario"],
                provider=run["provider"],
                status=run["status"],
                phase=summary.get("phase", "n/a"),
                terminal=summary.get("terminal_outcome", "n/a"),
                accepted="yes" if run.get("acceptance_criteria_met") is True else "no",
                validation=validation_status,
                duration=run.get("duration_seconds", 0.0),
                repair_count=len(repair_history),
            )
        )
    lines.extend(
        [
            "",
            "## Provider Totals",
            "",
            "| Provider | Completed | Validation Error | Execution Error | Skipped |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for provider, counts in report_provider_totals.items():
        lines.append(
            f"| {provider} | {counts.get('completed', 0)} | {counts.get('validation_error', 0)} | {counts.get('execution_error', 0)} | {counts.get('skipped', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Scenario Totals",
            "",
            "| Scenario | Completed | Validation Error | Execution Error | Skipped |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for scenario, counts in report_scenario_totals.items():
        lines.append(
            f"| {scenario} | {counts.get('completed', 0)} | {counts.get('validation_error', 0)} | {counts.get('execution_error', 0)} | {counts.get('skipped', 0)} |"
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
                    ollama_model=args.ollama_model,
                    ollama_num_ctx=args.ollama_num_ctx,
                    ollama_think={"true": True, "false": False}.get(args.ollama_think) if args.ollama_think else None,
                    ollama_timeout_seconds=args.ollama_timeout_seconds,
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