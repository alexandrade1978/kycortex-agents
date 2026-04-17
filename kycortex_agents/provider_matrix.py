"""Internal helpers for empirical provider validation and workflow summaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.config import resolve_provider_base_url
from kycortex_agents.providers.base import redact_sensitive_data
from kycortex_agents.types import FailureCategory, TaskStatus, WorkflowOutcome

DEFAULT_PROVIDER_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "ollama": "qwen2.5-coder:7b",
}

PROVIDER_CREDENTIAL_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

REPAIRABLE_FAILURE_CATEGORIES = {
    FailureCategory.UNKNOWN.value,
    FailureCategory.TASK_EXECUTION.value,
    FailureCategory.CODE_VALIDATION.value,
    FailureCategory.TEST_VALIDATION.value,
    FailureCategory.DEPENDENCY_VALIDATION.value,
    FailureCategory.WORKFLOW_BLOCKED.value,
    FailureCategory.PROVIDER_TRANSIENT.value,
}


def _public_path_label(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def _harden_private_file_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    path.chmod(0o600)


def _harden_private_directory_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    path.chmod(0o700)


def _ollama_base_url(base_url_override: str | None, *, environ: Mapping[str, str] | None = None) -> str:
    base_url = resolve_provider_base_url("ollama", base_url_override, environ=environ)
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("Ollama base_url could not be resolved")
    return base_url.rstrip("/")


def resolve_model(
    provider: str,
    model_override: str | None,
    *,
    ollama_base_url: str | None = None,
    urlopen_fn: Callable[..., Any] | None = None,
) -> str:
    """Resolve the concrete model to use for a provider validation run."""

    provider = provider.strip().lower()
    if model_override is not None or provider != "ollama":
        return model_override or DEFAULT_PROVIDER_MODELS[provider]

    default_model = DEFAULT_PROVIDER_MODELS[provider]
    urlopen_impl = urlopen if urlopen_fn is None else urlopen_fn
    request = Request(f"{_ollama_base_url(ollama_base_url)}/api/tags", method="GET")
    try:
        with urlopen_impl(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return default_model

    installed_models = [item.get("name", "") for item in payload.get("models", []) if item.get("name")]
    if default_model in installed_models:
        return default_model
    if installed_models:
        return installed_models[0]
    return default_model


def get_provider_availability(
    provider: str,
    *,
    environ: Mapping[str, str] | None = None,
    urlopen_fn: Callable[..., Any] | None = None,
    ollama_base_url: str | None = None,
) -> dict[str, Any]:
    """Return whether the provider is runnable in the current environment."""

    provider = provider.strip().lower()
    if provider not in DEFAULT_PROVIDER_MODELS:
        raise ValueError(f"Unsupported provider: {provider}")

    resolved_environ = environ if environ is not None else os.environ
    if provider in PROVIDER_CREDENTIAL_ENV_VARS:
        env_var = PROVIDER_CREDENTIAL_ENV_VARS[provider]
        available = bool(resolved_environ.get(env_var))
        return {
            "provider": provider,
            "available": available,
            "reason": None if available else f"missing {env_var}",
        }

    urlopen_impl = urlopen if urlopen_fn is None else urlopen_fn
    request = Request(f"{_ollama_base_url(ollama_base_url, environ=resolved_environ)}/api/tags", method="GET")
    try:
        with urlopen_impl(request, timeout=5) as response:
            available = getattr(response, "status", 200) == 200
    except (HTTPError, URLError, TimeoutError, OSError):
        available = False

    return {
        "provider": provider,
        "available": available,
        "reason": None if available else "ollama tags endpoint unreachable",
    }


def build_full_workflow_config(
    provider: str,
    model: str,
    output_dir: str,
    *,
    ollama_base_url: str | None = None,
    ollama_num_ctx: int | None = 16384,
    ollama_think: bool | None = None,
    ollama_timeout_seconds: float = 300.0,
    max_tokens: int = 3200,
    workflow_failure_policy: str = "continue",
    workflow_resume_policy: str = "resume_failed",
    workflow_max_repair_cycles: int = 1,
) -> KYCortexConfig:
    """Build the empirical full-workflow config used by provider-validation examples."""

    config = KYCortexConfig(
        llm_provider=provider,
        llm_model=model,
        base_url=_ollama_base_url(ollama_base_url) if provider == "ollama" else None,
        ollama_num_ctx=ollama_num_ctx if provider == "ollama" else None,
        ollama_think=ollama_think if provider == "ollama" else None,
        temperature=0.0,
        max_tokens=max_tokens,
        timeout_seconds=180.0,
        provider_timeout_seconds={"ollama": ollama_timeout_seconds} if provider == "ollama" else {},
        workflow_failure_policy=workflow_failure_policy,
        workflow_resume_policy=workflow_resume_policy,
        workflow_max_repair_cycles=workflow_max_repair_cycles,
        project_name="full-provider-workflow",
        output_dir=output_dir,
    )
    config.validate_runtime()
    return config


def build_full_workflow_project(output_dir: str, provider: str) -> ProjectState:
    """Build the canonical empirical full workflow used for provider comparison."""

    project = ProjectState(
        project_name="ComplianceIntake",
        goal=(
            "Build a substantial single-module Python service for a compliance intake team. "
            "The module must use only the standard library and implement typed domain models, "
            "request validation, risk scoring, audit logging, batch processing, and a small CLI demo."
        ),
        state_file=str(Path(output_dir) / "project_state.json"),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description=(
                "Design a concrete single-module architecture for a compliance intake service. "
                "Keep the design under 350 words and identify entities, workflows, audit boundaries, "
                "and operational risks. "
                "Prefer one cohesive public service surface plus domain models over separate helper-only collaborators or interface sections. "
                "Do not describe standalone RiskScorer, AuditLogger, BatchProcessor, Manager, or Processor types unless the task explicitly requires those public surfaces. "
                "If you describe typed entities or dataclasses, list required fields before defaulted fields and call out defaults explicitly so the design does not imply an invalid constructor order. "
                "\n\nPublic contract anchor:\n"
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases.\n"
                "- Keep these names exact. Do not rename the facade to ComplianceService or rename handle_request(...) to intake_request(...), validate_and_score(...), submit_intake(...), or similar aliases.\n"
                "- Keep constructor field names exact. Do not replace request_id, request_type, details, or timestamp with guessed fields such as id, type, data, metadata, or status."
            ),
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description=(
                "Write one Python module under 300 lines that implements only the planned compliance intake service. "
                "Use only the standard library. Include typed models, validation, risk scoring, batch processing, "
                "audit logging, and a CLI demo entrypoint. Prefer the smallest complete design that satisfies those requirements. "
                "Target roughly 240 to 280 lines when the requested behavior fits there so the hard 300-line cap keeps repair headroom. "
                "Leave at least 15 lines of headroom under the hard cap when the required behavior fits there. "
                "Implement only the minimal core flow rather than mirroring every optional architecture layer or future extension point. "
                "Avoid extra helper layers, exhaustive docstrings, and optional abstractions. "
                "Prefer one cohesive public service surface or a very small set of top-level functions for validation, scoring, audit logging, and batch handling. "
                "Do not split those behaviors into separate Logger, Scorer, Processor, Manager, or interface classes unless the task explicitly requires those public collaborators. "
                "If the architecture sketch mentions optional helper collaborators such as RiskScorer, AuditLogger, or BatchProcessor, collapse them into the smallest importable API instead of mirroring every helper layer. "
                "Prefer in-memory service state and audit records unless the architecture explicitly requires durable persistence; do not add sqlite or filesystem-backed storage just to simulate realism. "
                "Implement real validation and scoring behavior instead of constant-success validators or placeholder constant scores. "
                "If you derive a numeric risk score from request data, prefer a direct, easy-to-verify formula and avoid hidden caps, clamps, or arbitrary thresholds unless the architecture explicitly requires them. "
                "If a boolean or toggle-like request field influences behavior, use its truth value rather than mere field presence unless the architecture explicitly defines presence-only semantics. "
                "If you model requests or records as dataclasses or typed objects, keep object access consistent and do not mix in dict-style membership checks or subscripting unless the architecture explicitly requires mappings. "
                "If you define dataclasses or typed record models with defaults, place every required non-default field before any defaulted field so the module imports cleanly and avoids import-time field-order errors. "
                "If a dataclass such as AuditLog has required fields action and details plus a defaulted timestamp, declare action and details before timestamp = field(default_factory=...) so the module imports cleanly. "
                "If you use dataclasses.field(...) or field(default_factory=...) anywhere in the module, import field explicitly from dataclasses so the module imports cleanly. "
                "Keep imports consistent with the names you reference. If you call datetime.datetime.now() or datetime.date.today(), import datetime. If you import a symbol such as from datetime import datetime, call datetime.now() instead of datetime.datetime.now(). Do not leave module-qualified references pointing at names you never imported. "
                "\n\nPublic contract anchor:\n"
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases.\n"
                "- Keep these names exact. Do not rename the facade to ComplianceService or rename handle_request(...) to intake_request(...), validate_and_score(...), submit_intake(...), batch_intake_requests(...), or similar aliases.\n"
                "- Keep constructor field names exact. Do not replace request_id, request_type, details, or timestamp with guessed fields such as id, type, data, metadata, or status. "
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
                "Infer the minimal runtime requirements.txt for the generated module. "
                "List only third-party runtime packages that are actually required."
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
                "Write one compact raw pytest module under 150 lines for the generated compliance intake service. "
                "Use at most 3 fixtures and at most 7 top-level test functions. Include at least one happy path, one validation failure, and one batch-processing scenario. "
                "Prefer 3 to 5 top-level tests when those requested scenarios fit within that budget, and merge overlapping checks instead of adding helper-specific extras. "
                "Leave at least one full test of headroom below the stated maximum when those scenarios fit there, and delete helper-level coverage before dropping any required scenario. "
                "Count top-level tests before finalizing. If you draft more than 6 for this task, merge or delete the lowest-value extra case before returning because the validator rejects any suite above the hard cap even when pytest passes. "
                "Target clear headroom below the 150-line ceiling instead of landing on the boundary. Remove docstrings, comments, extra blank lines, and optional helper scaffolding before dropping any required scenario. "
                "Stay comfortably under the fixture limit; target 0 to 2 fixtures by default and inline one-off setup instead of adding a borderline extra fixture. "
                "Use the direct intake or validation surface for the validation-failure scenario and keep the batch-processing scenario fully valid unless the implementation contract explicitly requires partially invalid batch items. "
                "If the validation-failure scenario is a missing-required-field case, omit only the field under test and keep the rest of that payload valid for the same surface. "
                "If required fields are validated before score_request, score_risk, process_request, or batch handling, do not create a separate invalid-scoring test that first calls intake_request on an invalid object. Keep that failure case on intake_request or validate_request, and reserve scoring assertions for already-valid inputs. "
                "If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid instead of raising, assert that state on the same object you passed into the call. "
                "\n\nPublic contract anchor:\n"
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade through repeated handle_request(request) calls unless the exact contract later documents a different public batch callable.\n"
                "- Keep these names exact. Do not rename the facade to ComplianceService or invent process_batch(...), batch_process(...), batch_intake_requests(...), validate_and_score(...), or similar aliases.\n"
                "- Keep constructor field names exact and pass them all explicitly in tests. Do not omit timestamp from ComplianceRequest(...) calls and do not rename request_id, request_type, details, or timestamp.\n"
                "Concrete class, function, and field names used in the generic examples below are placeholders only. Never copy example names such as ComplianceRequest, ComplianceService, validate_request, process_request, submit_intake, or batch_submit_intakes unless the provided contract, behavior contract, or test targets list that exact name. Rewrite those examples to the real module surface before you write the suite. "
                "Prefer the highest-level public service or top-level workflow functions for the requested scenarios; do not import repository, logger, scorer, validator, or similar helper services directly unless the documented contract makes them the primary surface under test. "
                "When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models instead of auxiliary validators, scorers, loggers, repositories, processors, or engines. "
                "Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols. If the contract lists BatchProcessor or RiskScorer, do not invent ComplianceBatchProcessor, ComplianceScorer, ComplianceIntake, AuditLogger, or similar aliases. "
                "If the contract lists submit_intake(...) and batch_submit_intakes(...), do not shorten them to submit(...) or submit_batch(...), even when calling ComplianceIntakeService() inline. "
                "When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity from that contract; do not invent generic placeholders such as id, data, timestamp, or status when the contract lists different fields. "
                "When the API contract lists constructor fields for a typed request or result model, pass every listed field explicitly in test instantiations, including documented defaulted fields, unless omission is explicitly shown as valid. "
                "Do not rely on dataclass defaults just because omission would run; if the contract lists defaulted fields such as timestamp or status, pass them explicitly in every constructor call. If the contract lists ComplianceRequest(id, data, timestamp, status), write ComplianceRequest(id=\"1\", data={\"name\": \"John Doe\", \"amount\": 1000}, timestamp=1.0, status=\"pending\") instead of omitting timestamp and status. When you pass an explicit constructor field such as timestamp, use a self-contained literal or a local value defined before the constructor call. Do not read attributes from the object you are still constructing or any other undefined local; define fixed_time first and pass timestamp=fixed_time instead of writing timestamp=request.timestamp inside request = ComplianceRequest(...). "
                "If the public API contract lists ComplianceRequest(id, user_id, data, timestamp, status), every constructor call in the suite must pass all five named arguments; do not omit status and rely on the dataclass default. "
                "If the provided test targets list batch-capable functions, use one of those for the batch scenario instead of inventing batch behavior for unrelated helpers. "
                "If the implementation exposes no dedicated batch helper, express the batch scenario as a short list of individually valid items processed one by one instead of passing a list into scalar-only validators or scorers. "
                "If the implementation exposes only a single-request surface such as process_request(request) and no process_batch(...), keep the batch scenario on that main request-processing surface by looping over a short list of valid requests instead of switching to logger, repository, scorer, or audit helpers. "
                "If the implementation exposes only scalar validation, scoring, or audit helpers, compose the required scenarios from those helpers in 3 to 4 tests total and do not add separate standalone tests for each helper. "
                "If a batch helper returns None or constructs its own domain objects from raw items, do not instantiate fresh objects after the batch call and assume they inherited internal mutations; assert only directly observable outcomes. "
                "Do not import or test `main`, CLI/demo entrypoints, or other symbols explicitly listed as entry points to avoid in tests. "
                "Do not spend standalone tests on simple logging or audit helpers unless the public contract makes them independently observable. "
                "In this compact workflow suite, do not spend top-level tests on validator units, scorers, dataclass serialization, audit loggers, or other helper surfaces unless the contract explicitly requires them. "
                "Do not add standalone caplog or raw logging-output assertions unless externally observable logging behavior is explicitly required. "
                "If audit behavior matters, assert only records for actions actually exercised in the scenario and do not expect document-upload, status-change, or similar audit events unless the test performs that action. "
                "If a batch scenario includes invalid items, count audit records from both the inner failing operation and any outer batch failure handler. One invalid batch item can emit two failure-related audit entries, and those must be added to any success-path audit records from valid items before asserting an exact audit length. "
                "If process_batch or another batch helper internally performs intake and scoring for each valid item, count those inner success-path logs too before asserting any batch audit total. Example: a two-item valid batch can emit 5 audit logs, not 3, and a batch that fails on the second item can still already emit 2 logs, not 1, from the first valid item. "
                "In batch scenarios, prefer assertions on returned results, terminal batch markers, or monotonic audit growth over an exact audit length unless the current implementation or contract explicitly enumerates every emitted log entry. If you cannot enumerate every internal log deterministically, do not assert an exact batch audit total. "
                "Unless the current implementation or behavior contract explicitly enumerates every emitted batch log, do not write len(service.audit_logs) == N or a similar exact batch-audit assertion. "
                "If pytest or prior repair feedback showed a mismatch such as assert 5 == 3 on len(service.audit_logs), delete that exact batch-audit count and replace it with stable checks such as result counts, required actions, terminal batch markers, or monotonic audit growth. "
                "Never define a custom fixture named `request`; pytest reserves that name. Use inline setup or a specific fixture name instead. "
                "Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test installs the exact mock or patch target first. "
                "If repair feedback reports undefined local names or undefined fixtures, remove or rewrite those offending helper tests instead of preserving them. "
                "If repair feedback reports helper surface usages, delete those helper-surface imports, fixtures, helper variables, and top-level tests instead of preserving or repairing them in place. "
                "If the suite uses the `pytest.` namespace anywhere, add `import pytest` explicitly at the top of the file; built-in fixtures alone do not make the module name available. "
                "Do not assume empty strings, placeholder IDs, or domain keywords are invalid unless the contract or implementation explicitly says so; for validation-failure coverage, prefer missing required fields or clearly wrong types over guessed business rules. If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict), an empty string or same-type placeholder still satisfies that validator, so use a non-string, non-dict, or similarly wrong-type value instead. "
                "If validate_request(request) only checks isinstance(request.id, str) and isinstance(request.data, dict), ComplianceRequest(id=\"\", data={\"field\": \"value\"}) still passes; use a non-string id or a non-dict data value for the failure case instead. "
                "Apply the same rule to request_id, entity_id, document_id, and similar identifier fields: unless the contract explicitly says empty strings are invalid, request_id=\"\" or another same-type placeholder can still pass, so prefer a wrong top-level type or a truly missing required field. "
                "Apply the same rule to dict payload fields such as data, details, metadata, request_data, or document_data: an empty dict is still a same-type placeholder and may pass when validation only checks dict type, so prefer None, a non-dict value, or omission only when the contract explicitly allows omission. "
                "If a workflow input still has the correct top-level type, do not expect ValueError just because one business value changed. If submit_intake only validates that data.data is a dict, ComplianceData(id=\"1\", data={\"key\": \"wrong_value\"}) is still valid input and should be asserted as a non-compliant result instead of being wrapped in pytest.raises(ValueError). Use a non-dict payload if you need a ValueError case. "
                "Do not write a validation-failure test as assert not validate_request(...) or a similar falsy expectation unless the contract explicitly documents False as the invalid outcome; otherwise use a wrong top-level type or missing required field and assert the documented failure mode. "
                "For process_request or other validation-gated workflow tests, choose an input that validate_request rejects before scoring runs. Do not use nested None values or same-type empty containers that can slip past validation and then fail later inside score_risk, calculate_risk_score, or similar scoring helpers with a different exception. "
                "If validation only checks an outer container type, do not assume a wrong nested value type makes the request invalid. If validate_request(request) returns bool(request.id) and isinstance(request.data, dict), ComplianceRequest(id=\"1\", data={\"check\": \"not_a_bool\"}, timestamp=\"2023-01-01T00:00:00Z\", status=\"pending\") still passes; use a non-dict data value or another explicitly invalid top-level field instead. "
                "If validation or scoring guards a nested field with isinstance(...) before using it, a wrong nested field type is usually ignored rather than raising. If calculate_risk_score only adds risk_factor when isinstance(request_data[\"risk_factor\"], (int, float)), then risk_factor=\"invalid\" does not raise TypeError; use a wrong top-level type or missing required field for failure coverage instead. "
                "If the implementation exposes only helper-level audit or logging functions, do not spend one of the limited top-level tests on a standalone audit or log helper check; fold any required audit call into another required scenario instead. "
                "If the implementation exposes validate_request(request), score_request(request), and log_audit(request_id, action, result), write exactly three tests: one happy-path test that validates and scores a valid request and may assert audit file creation or required substring presence, one validation-failure test using an invalid document_type or wrong-type document_data, and one batch-style loop over two valid requests. Do not add standalone score_request, log_audit, or extra invalid-case tests. "
                "If you need an exact numeric assertion, use trivially countable inputs rather than prose strings; otherwise prefer stable non-exact assertions. "
                "Do not assert an exact runtime numeric type such as float unless the contract or current implementation explicitly casts to that type; if the implementation computes a numeric score with int-like arithmetic such as modulo or counts, assert the documented value, numeric non-negativity, or another broader numeric invariant instead. "
                "If an exact numeric assertion depends on nested payload shape, compute it from the actual object passed into the scoring function rather than from an inner dict you assume the service extracted. If request.data stores {\"id\": \"1\", \"data\": {\"data_field\": \"example\"}, \"timestamp\": \"...\"} and calculate_risk_score reads data.get(\"data_field\", \"\"), the score is 0.0, not 7.0. "
                "If an exact numeric assertion depends on top-level dict size or collection size, compute it from the actual top-level container passed into scoring rather than from nested values or magnitudes. If calculate_risk_score(data) returns float(len(data)) * 1.5 and two requests pass dicts with the same two top-level keys, both scores are 3.0 even when nested amounts or names differ. "
                "If a scorer accepts a mixed semantic payload dict and the formula is not fully explicit, do not invent a guessed exact total such as 6.0 or a derived level such as medium by hand-counting keys and prose-like sample values. If calculate_risk_score({\"id\": \"1\", \"data1\": \"value1\", \"data2\": \"value2\"}) does not come with a fully explicit formula, assert a contract-backed invariant such as non-negative score or relative ordering instead of 6.0 or medium. "
                "If an exact numeric assertion depends on string length or character count, do not pair exact score equality with word-like sample strings such as data, valid_data, or data1. Replace them with repeated-character literals such as aaaa or a * 20, or switch the assertion to a non-exact invariant. "
                "If a required string field participates in a length- or modulo-based score, do not use an empty string to force score 0 in a non-error scenario. Use a non-empty repeated-character literal with the needed length instead; for len(details) % 10 == 0, use xxxxxxxxxx rather than \"\". "
                "When an exact numeric score is required, compute it from only the branches exercised by the chosen input instead of summing unrelated categories. If score_request adds 1 for document_type == \"income\" and 2 for document_type == \"employment\", a request with document_type == \"income\" should assert 1, not 3. "
                "If a score formula combines weighted numeric fields, recompute the exact total from every exercised term using the current input values before asserting equality. If score += request_data[\"risk_factor\"] * 0.5 and score += (1 - request_data[\"compliance_history\"]) * 0.5, then risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25. "
                "If you assert derived categorical score bands or levels, avoid threshold boundary values unless the contract explicitly defines those cutoffs; use comfortably in-band inputs or non-boundary assertions instead. If score = amount * 0.1 and the level may change at 10, do not use amount=100 to assert an exact label; use 50 for a clear low case, 150 for a clear medium case, or assert only the numeric score. "
                "If derived labels depend on count-based scores and the thresholds are not explicit, do not use borderline counts such as 2 to assert an exact low or medium label; use 1 for a clear low case, 3 for a clear medium case, or assert only the numeric score. "
                "If an exact decision, outcome, or audit label depends on a visible numeric score formula or threshold table, recompute the total from every exercised factor before asserting that label. Do not guess labels such as blocked, escalated, rejected, or conditional_approval from a single suggestive factor such as sanctions, high-risk geography, or a partial point count. "
                "If you are not recomputing every exercised branch or the sample sits near a threshold, switch to a non-exact invariant or choose a comfortably in-band sample instead of asserting the exact label. "
                "Do not infer `FLAGGED` status, non-zero flagged/report counters, or other derived outcomes from suggestive keywords like sanction alone unless the contract explicitly defines that trigger or the scenario performs the required state transition. "
                "Prefer assertions on directly observable totals, persisted submissions, audit growth, or non-negative scores over guessed status/report thresholds. "
                "If a service constructor accepts optional configuration such as risk_weights, omit that argument unless the task explicitly requires collaborator coverage. When you must pass it, use the documented runtime shape, such as a real dict with the expected keys, and never a placeholder object that only answers attribute access when the implementation reads by subscription. "
                "If a service stores the full raw request payload in a field such as request.data, do not assume that field was normalized to only an inner sub-dict. If request_data = {\"id\": \"req1\", \"data\": {\"field1\": \"value1\"}} and intake_request stores ComplianceRequest.data = request_data, assert the full stored payload shape or direct nested keys instead of asserting request.data == {\"field1\": \"value1\"}. "
                "Never redeclare production dataclasses, business functions, CLI parsers, or other implementation code inside the pytest module; import production symbols from the generated module and keep the test file as tests only. "
                "Do not turn copied implementation into `test_main`, `test_all_tests`, or similar meta-tests that invoke argparse, print output, or manually call other tests. "
                "Do not compare full audit or log file contents by exact string equality or trailing-newline-sensitive text unless the contract explicitly defines that serialized format; prefer stable assertions such as file creation, non-empty content, append growth, line count, or required substring presence. "
                "Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger; otherwise assert stable invariants such as success, request identity, audit growth, and non-negative or relative scores. "
                "If a test uses the same invalid sample for validate_request(...) and a later workflow call, the validator expectation must agree with the workflow expectation. Do not assert validate_request(...) is True and then expect that same sample to fail immediately in handle_request(...), process_request(...), or a similar validation-gated workflow. "
                "When calling get_audit_log or any similar request/filter API, either omit the optional filter dict or provide every documented required filter key; do not assume a single-field partial filter is accepted unless the contract explicitly says so. "
                "If you use isinstance or another exact type assertion against a returned production class, import that class explicitly; otherwise assert on returned fields or behavior without naming the unimported type. "
                "If an exact numeric assertion depends on string length, modulo, or counts, use repeated-character or similarly obvious inputs rather than natural-language sample text. "
                "Prefer direct assertions over exhaustive permutations or class-based test suites. Return raw Python only."
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
                "Review the generated implementation, dependency manifest, and tests for correctness, maintainability, "
                "and operational realism. Keep it actionable and concise."
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
                "Write an engineer-facing README for the generated module, including setup, usage, dependency notes, "
                "design assumptions, and extension points."
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
                "Provide a concise legal and compliance note covering audit-data handling, privacy concerns, "
                "licensing assumptions, and distribution considerations for the generated compliance intake module."
            ),
            assigned_to="legal_advisor",
            dependencies=["docs"],
        )
    )
    return project


def summarize_workflow_run(
    project: ProjectState,
    *,
    provider: str,
    model: str,
    output_dir: str,
) -> dict[str, Any]:
    """Build a compact structured summary for a provider workflow run."""

    snapshot = project.snapshot()
    task_status_counts: dict[str, int] = {}
    task_summaries = []

    for task in project.tasks:
        task_status_counts[task.status] = task_status_counts.get(task.status, 0) + 1
        task_summaries.append(
            {
                "id": task.id,
                "status": task.status,
                "has_assigned_to": bool(task.assigned_to),
                "has_attempts": bool(task.attempts),
                "last_error_present": bool(
                    task.last_error or task.last_error_type or task.last_error_category
                ),
                "last_error_category": task.last_error_category,
                "has_provider_call": isinstance(task.last_provider_call, Mapping),
                "has_repair_origin": bool(task.repair_origin_task_id),
            }
        )

    return redact_sensitive_data(
        {
        "project_name": snapshot.project_name,
        "phase": project.phase,
        "terminal_outcome": project.terminal_outcome,
        "repair_history": list(snapshot.repair_history),
        "state_file": _public_path_label(project.state_file),
        "output_dir": _public_path_label(output_dir),
        "task_status_counts": task_status_counts,
        "task_summaries": task_summaries,
        }
    )


def _can_resume_failed_workflow(project: ProjectState) -> bool:
    if not any(
        task.status in {TaskStatus.FAILED.value, TaskStatus.SKIPPED.value}
        for task in project.tasks
        if not task.repair_origin_task_id
    ):
        return False
    if project.terminal_outcome == WorkflowOutcome.CANCELLED.value:
        return False
    if project.terminal_outcome != WorkflowOutcome.FAILED.value:
        return True
    failure_category = project.failure_category or FailureCategory.UNKNOWN.value
    return failure_category in REPAIRABLE_FAILURE_CATEGORIES


def execute_empirical_validation_workflow(config: KYCortexConfig, project: ProjectState) -> None:
    """Execute a full workflow and consume any configured bounded repair cycles."""

    orchestrator = Orchestrator(config)
    last_error: Exception | None = None

    while True:
        try:
            orchestrator.execute_workflow(project)
        except Exception as exc:  # pragma: no cover - exercised via monkeypatched test doubles
            last_error = exc
        else:
            last_error = None

        should_resume = (
            config.workflow_resume_policy == "resume_failed"
            and project.can_start_repair_cycle()
            and _can_resume_failed_workflow(project)
        )
        if not should_resume:
            break

    if last_error is not None:
        raise last_error


def write_summary_json(summary: dict[str, Any], path: str) -> None:
    """Persist a provider-validation summary as formatted JSON."""

    summary_path = Path(path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    _harden_private_directory_permissions(summary_path.parent)
    summary_path.write_text(json.dumps(redact_sensitive_data(summary), indent=2, sort_keys=True), encoding="utf-8")
    _harden_private_file_permissions(summary_path)