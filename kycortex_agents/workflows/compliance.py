"""Public compliance workflow pack with prevalidated regulated-intake project builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from kycortex_agents.exceptions import WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task


@dataclass(frozen=True)
class ComplianceScenario:
    """Declarative specification for a packaged compliance workflow scenario."""

    slug: str
    project_name: str
    team_name: str
    service_name: str
    request_name: str
    domain_summary: str
    goal: str
    behavior_bullets: tuple[str, ...]
    detail_contract_bullets: tuple[str, ...]
    detail_fixture_example: Mapping[str, object]
    docs_focus: tuple[str, ...]
    legal_focus: tuple[str, ...]


KYC_COMPLIANCE_INTAKE = ComplianceScenario(
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
        "Score risk as an additive numeric value (int or float, minimum 0). Increase the score when adverse indicators or missing documents are present. Use addition and weighted sums only — never divide by the count of any detail field because empty lists would cause ZeroDivisionError.",
        "Track auditable review outcomes such as approved, escalated, or blocked.",
        "Support batch intake while preserving per-request audit records and summaries.",
    ),
    detail_contract_bullets=(
        "Keep canonical details keys exact for this scenario: identity_evidence, jurisdiction, customer_type, adverse_indicators, and missing_documents.",
        "Keep identity_evidence as the evidence collection inside details. Do not replace it with guessed aliases such as identity_proof, address_proof, documents, or document_list.",
        "Keep jurisdiction and customer_type as strings. Keep identity_evidence, adverse_indicators, and missing_documents as list-like collections inside details, not numeric severity placeholders or plain strings.",
        "When details is not a dict, reject it immediately in validate_request (return False) and raise ValueError in handle_request. Never fall back to default values for non-dict details.",
        "Risk scoring must use additive accumulation (start at 0, add points for each risk factor). Never divide by len(adverse_indicators), len(missing_documents), or any other detail count — those collections can be empty, making the divisor zero.",
    ),
    detail_fixture_example={
        "identity_evidence": ["passport_scan"],
        "jurisdiction": "US",
        "customer_type": "individual",
        "adverse_indicators": [],
        "missing_documents": [],
    },
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
)


AML_SANCTIONS_SCREENING = ComplianceScenario(
    slug="aml_sanctions_screening",
    project_name="AMLSanctionsScreening",
    team_name="AML compliance team",
    service_name="AMLSanctionsScreeningService",
    request_name="SanctionsScreeningRequest",
    domain_summary="AML sanctions and PEP screening for high-risk customer transactions",
    goal=(
        "Build a single-module Python service for an AML compliance team. "
        "The service must screen transaction subjects against sanctions lists and PEP registries, "
        "calculate match confidence scores, handle false positive designations, track audit records, "
        "and support batch screening with clear escalation markers."
    ),
    behavior_bullets=(
        "Validate screening subjects and reject malformed requests early.",
        "Score match confidence as an additive value (0 to 100). Add score points for exact name matches, country overlap, and watchlist flags. Never divide by empty list counts.",
        "Track audit outcomes such as clear, flagged, or false_positive.",
        "Support batch screening while recording detailed per-subject audit entries.",
    ),
    detail_contract_bullets=(
        "Keep canonical details keys exact for this scenario: subject_name, country, watchlist_hits, and pep_status.",
        "Keep subject_name and country as strings. Keep watchlist_hits as a list-like collection inside details and pep_status as a boolean or string.",
        "When details is not a dict, reject it immediately in validate_request (return False) and raise ValueError in handle_request. Never fall back to default values for non-dict details.",
        "Match scoring must use additive calculations (minimum 0, max 100). Do not divide by len(watchlist_hits) or empty collections.",
    ),
    detail_fixture_example={
        "subject_name": "John Doe",
        "country": "US",
        "watchlist_hits": [],
        "pep_status": "none",
    },
    docs_focus=(
        "sanctions screening workflow",
        "watchlist match confidence scoring",
        "false positive management",
    ),
    legal_focus=(
        "sanctions compliance obligations",
        "PEP screening data privacy",
        "audit trail for regulatory reporting",
    ),
)


VENDOR_DUE_DILIGENCE = ComplianceScenario(
    slug="vendor_due_diligence",
    project_name="VendorDueDiligence",
    team_name="Vendor risk and compliance team",
    service_name="VendorDueDiligenceService",
    request_name="VendorAssessmentRequest",
    domain_summary="Third-party vendor compliance assessment and risk tiering",
    goal=(
        "Build a single-module Python service for a vendor risk and compliance team. "
        "The service must evaluate vendor compliance questionnaires, score security and privacy risks, "
        "assign risk tiers (low, medium, high, critical), track review history, "
        "and support batch evaluation with auditable outcomes."
    ),
    behavior_bullets=(
        "Validate vendor assessment submissions and reject malformed requests early.",
        "Score vendor risk as an additive numeric score based on missing security certifications, data access levels, and location risk.",
        "Track review outcomes such as approved, conditional, or rejected.",
        "Support batch vendor assessments with per-vendor audit records.",
    ),
    detail_contract_bullets=(
        "Keep canonical details keys exact for this scenario: vendor_name, certifications, data_access_level, and audit_findings.",
        "Keep vendor_name and data_access_level as strings. Keep certifications and audit_findings as list-like collections inside details.",
        "When details is not a dict, reject it immediately in validate_request (return False) and raise ValueError in handle_request.",
        "Vendor risk scoring must use additive accumulation. Never divide by empty findings collections.",
    ),
    detail_fixture_example={
        "vendor_name": "Acme Cloud",
        "certifications": ["ISO27001", "SOC2"],
        "data_access_level": "confidential",
        "audit_findings": [],
    },
    docs_focus=(
        "vendor onboarding review workflow",
        "security and compliance risk tiering",
        "periodic review tracking",
    ),
    legal_focus=(
        "third-party data processing agreements",
        "regulatory vendor oversight mandates",
        "vendor audit trail retention",
    ),
)


AUDIT_RISK_SCORING = ComplianceScenario(
    slug="audit_risk_scoring",
    project_name="AuditRiskScoring",
    team_name="Internal audit and risk management team",
    service_name="AuditRiskScoringService",
    request_name="AuditRiskAssessmentRequest",
    domain_summary="Continuous audit risk assessment and transaction anomaly scoring",
    goal=(
        "Build a single-module Python service for an internal audit and risk management team. "
        "The service must analyze operational transactions, score risk anomalies, "
        "flag threshold breaches, support legal-hold markers, "
        "and generate structured audit summary logs."
    ),
    behavior_bullets=(
        "Validate audit requests and reject malformed inputs early.",
        "Score audit risk using additive rules based on transaction value, anomaly indicators, and historical findings.",
        "Track audit decisions such as compliant, flagged_for_audit, or legal_hold.",
        "Support batch processing and audit log accumulation.",
    ),
    detail_contract_bullets=(
        "Keep canonical details keys exact for this scenario: transaction_id, amount, anomaly_indicators, and legal_hold_flag.",
        "Keep transaction_id as a string and amount as a numeric value. Keep anomaly_indicators as a list-like collection and legal_hold_flag as a boolean.",
        "When details is not a dict, reject it immediately in validate_request (return False) and raise ValueError in handle_request.",
        "Risk scoring must be additive. Do not divide by anomaly_indicators count.",
    ),
    detail_fixture_example={
        "transaction_id": "tx_1001",
        "amount": 15000.0,
        "anomaly_indicators": [],
        "legal_hold_flag": False,
    },
    docs_focus=(
        "continuous audit monitoring workflow",
        "anomaly risk scoring rules",
        "legal hold and audit log management",
    ),
    legal_focus=(
        "regulatory compliance audit trail",
        "legal hold record preservation",
        "internal control reporting requirements",
    ),
)


BUILTIN_COMPLIANCE_SCENARIOS: tuple[ComplianceScenario, ...] = (
    KYC_COMPLIANCE_INTAKE,
    AML_SANCTIONS_SCREENING,
    VENDOR_DUE_DILIGENCE,
    AUDIT_RISK_SCORING,
)


def list_compliance_scenarios() -> tuple[ComplianceScenario, ...]:
    """Return the built-in compliance scenarios shipped with the workflow pack."""
    return BUILTIN_COMPLIANCE_SCENARIOS


def get_compliance_scenario(slug: str) -> ComplianceScenario:
    """Return the built-in compliance scenario registered under the supplied slug."""
    normalized = slug.strip().lower()
    for scenario in BUILTIN_COMPLIANCE_SCENARIOS:
        if scenario.slug == normalized:
            return scenario
    supported = ", ".join(scenario.slug for scenario in BUILTIN_COMPLIANCE_SCENARIOS)
    raise WorkflowDefinitionError(f"Unknown compliance scenario '{slug}'. Supported scenarios: {supported}.")


def _contract_anchor(scenario: ComplianceScenario) -> str:
    return (
        f"- Public facade: {scenario.service_name}\n"
        f"- Primary request model: {scenario.request_name}(request_id, request_type, details, timestamp)\n"
        f"- Required request workflow: {scenario.service_name}.handle_request(request)\n"
        f"- Supporting validation surface: {scenario.service_name}.validate_request(request)\n"
        "- validate_request(request) must return a plain bool (True for valid, False for invalid). Do not return a tuple, a dataclass, or a validation-result object — return exactly True or False.\n"
        "- The details field of every request is always a plain dict (Dict[str, Any]). Access detail values through dict indexing (details['key']) or details.get('key'), never through attribute access (details.key). Do not define a custom dataclass or NamedTuple for the details payload.\n"
        "- validate_request must return False immediately when details is not a dict. Do not gracefully handle non-dict details (e.g. a plain string); treat any non-dict value as an invalid request.\n"
        "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases.\n"
        f"- Keep these names exact. Do not rename the facade to a generic alias or replace {scenario.request_name} with guessed placeholder models.\n"
        "- Keep constructor field names exact. Do not replace request_id, request_type, details, or timestamp with guessed fields such as id, type, data, metadata, or status.\n"
        f"- Keep {scenario.service_name} instantiable with zero required constructor arguments. Initialize internal audit or review state inside __init__ instead of requiring callers to pass audit_history, collaborators, repositories, or other mutable state containers.\n"
        "- The timestamp field of every request is a datetime object (from the datetime module), not a float, int, or string. Validate it with isinstance(request.timestamp, datetime).\n"
        "- The request_type field is a free-form string label. Accept any non-empty string — do not restrict it to an invented whitelist of allowed values."
    )


def _details_contract_block(scenario: ComplianceScenario) -> str:
    return "\n".join(f"- {item}" for item in scenario.detail_contract_bullets)


def _test_fixture_contract_block(scenario: ComplianceScenario) -> str:
    example_repr = repr(dict(scenario.detail_fixture_example))
    wrong_keys = " ".join(scenario.detail_fixture_example)
    return "\n".join(
        (
            f"- Every {scenario.request_name} fixture in the test suite must construct details as a literal dict with populated field values.",
            "- Never pass details as a plain string, a space-separated list of field names, or a placeholder. The implementation expects a dict and will fail on string input.",
            f"- Example of CORRECT fixture: details={example_repr}",
            f"- Example of WRONG fixture: details='{wrong_keys}'",
        )
    )


def _observable_outcome_contract_block() -> str:
    return "\n".join(
        (
            "- handle_request(request) must return a per-request outcome object or dict, not None.",
            "- For malformed requests where details is not a dict, handle_request(request) must raise ValueError explicitly. Never return a normal outcome dict, fallback result, or 'invalid' response payload for that malformed input.",
            "- The returned outcome must make the review decision and risk signal observable to callers, for example through outcome and risk_score style fields or equivalent structured keys.",
            "- Preserve audit evidence either in the returned outcome or on a service audit history surface that accumulates one auditable entry per processed request.",
            "- Do not treat a logging side effect alone or a None return as sufficient happy-path or batch behavior.",
        )
    )


def _behavior_block(scenario: ComplianceScenario) -> str:
    return "\n".join(f"- {item}" for item in scenario.behavior_bullets)


def _docs_focus_block(scenario: ComplianceScenario) -> str:
    return "\n".join(f"- {item}" for item in scenario.docs_focus)


def _legal_focus_block(scenario: ComplianceScenario) -> str:
    return "\n".join(f"- {item}" for item in scenario.legal_focus)


def build_compliance_project(scenario: ComplianceScenario, *, state_file: Optional[str] = None) -> ProjectState:
    """Build a dependency-aware ProjectState implementing the supplied compliance scenario."""
    project = ProjectState(
        project_name=scenario.project_name,
        goal=scenario.goal,
        state_file=state_file if state_file is not None else "project_state.json",
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description=(
                f"Design a concrete single-module architecture for {scenario.domain_summary}. "
                f"Keep the design under 350 words and focus on the needs of a {scenario.team_name}. "
                "Identify the domain entities, review workflow, risk inputs, audit boundaries, and operational failure modes. "
                "Prefer one cohesive public service surface plus typed domain models over a large helper hierarchy.\n\n"
                "Required domain behavior:\n"
                f"{_behavior_block(scenario)}\n\n"
                "Public contract anchor:\n"
                f"{_contract_anchor(scenario)}\n\n"
                "Canonical details contract:\n"
                f"{_details_contract_block(scenario)}\n\n"
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
                f"Write one Python module that implements {scenario.domain_summary} for a {scenario.team_name}. "
                "Use only the standard library. Include typed models, request validation, risk scoring, audit logging, "
                "batch processing, and a small CLI demo entrypoint. Prefer a small but complete design with one primary service facade. "
                "Avoid speculative helper layers, unnecessary abstractions, and third-party imports. "
                "If you use @dataclass anywhere in the module, import dataclass explicitly from dataclasses so the module imports cleanly. "
                "If you define dataclasses with defaults, place required non-default fields before defaulted ones. "
                "If you use field(default_factory=...), import field explicitly from dataclasses. "
                "Keep imports consistent with how you reference datetime symbols.\n\n"
                "Required domain behavior:\n"
                f"{_behavior_block(scenario)}\n\n"
                "Public contract anchor:\n"
                f"{_contract_anchor(scenario)}\n\n"
                "Canonical details contract:\n"
                f"{_details_contract_block(scenario)}\n\n"
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
                f"Infer the minimal runtime requirements.txt for the generated {scenario.domain_summary} module. "
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
                f"Write one compact raw pytest module for the generated {scenario.domain_summary} module. "
                "Keep the suite concise and stable: target 4 to 6 top-level tests, at most 3 fixtures, and clear headroom below 180 lines. "
                "Include at least one happy path, one validation failure, one risk-scoring assertion, one batch-processing scenario, and one audit-trail assertion. "
                "The validation-failure test must use a malformed request whose details is not a dict, assert validate_request(...) is False, and assert handle_request(...) raises ValueError. "
                "Prefer directly observable outcomes over guessed internal implementation details. "
                "Do not import or test CLI entrypoints. Do not invent helper classes, renamed APIs, or missing fields. "
                "If you use the pytest namespace, import pytest explicitly.\n\n"
                "Required domain behavior:\n"
                f"{_behavior_block(scenario)}\n\n"
                "Public contract anchor:\n"
                f"{_contract_anchor(scenario)}\n\n"
                "Canonical details contract:\n"
                f"{_details_contract_block(scenario)}\n\n"
                "Test fixture contract:\n"
                f"{_test_fixture_contract_block(scenario)}\n\n"
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
                f"and operational realism for {scenario.domain_summary}. Keep the review concise and actionable."
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
                f"Write an engineer-facing README for the generated {scenario.domain_summary} module. "
                "Cover setup, usage, core workflow, assumptions, extension points, and operational notes.\n\n"
                "Focus areas:\n"
                f"{_docs_focus_block(scenario)}"
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
                f"Provide a concise legal and compliance note for the generated {scenario.domain_summary} module. "
                "Cover data handling, privacy, audit, licensing assumptions, and distribution considerations.\n\n"
                "Focus areas:\n"
                f"{_legal_focus_block(scenario)}"
            ),
            assigned_to="legal_advisor",
            dependencies=["docs"],
        )
    )
    return project


def build_kyc_intake_project(*, state_file: Optional[str] = None) -> ProjectState:
    """Build a ProjectState implementing the KYC compliance intake scenario."""
    return build_compliance_project(KYC_COMPLIANCE_INTAKE, state_file=state_file)


def build_aml_screening_project(*, state_file: Optional[str] = None) -> ProjectState:
    """Build a ProjectState implementing the AML sanctions screening scenario."""
    return build_compliance_project(AML_SANCTIONS_SCREENING, state_file=state_file)


def build_vendor_due_diligence_project(*, state_file: Optional[str] = None) -> ProjectState:
    """Build a ProjectState implementing the vendor due diligence scenario."""
    return build_compliance_project(VENDOR_DUE_DILIGENCE, state_file=state_file)


def build_audit_risk_scoring_project(*, state_file: Optional[str] = None) -> ProjectState:
    """Build a ProjectState implementing the audit risk scoring scenario."""
    return build_compliance_project(AUDIT_RISK_SCORING, state_file=state_file)


__all__ = [
    "AML_SANCTIONS_SCREENING",
    "AUDIT_RISK_SCORING",
    "BUILTIN_COMPLIANCE_SCENARIOS",
    "ComplianceScenario",
    "KYC_COMPLIANCE_INTAKE",
    "VENDOR_DUE_DILIGENCE",
    "build_aml_screening_project",
    "build_audit_risk_scoring_project",
    "build_compliance_project",
    "build_kyc_intake_project",
    "build_vendor_due_diligence_project",
    "get_compliance_scenario",
    "list_compliance_scenarios",
]
