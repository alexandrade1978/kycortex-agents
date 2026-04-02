import re

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType

SYSTEM_PROMPT = """You are a QA Engineer at KYCortex AI Software House.
You write reliable pytest test suites that match the requested scope.
When the task scope is open-ended, cover the main happy path, one representative edge case, and a small integration path.
Use fixtures or parametrization only when they reduce duplication.
Task-specific scope, test-count, and size limits override these defaults. When the task asks for a compact suite, cover only the requested scenarios and skip extra edge cases, extra fixtures, and class-based grouping unless they are required for correctness.
Return only raw Python test code.
Do not include markdown fences, headings, or explanatory prose.
Import the real generated module using the provided module name.
Do not copy or re-declare the production implementation inside the test file.
If the code uses randomness, make tests deterministic with a fixed seed or monkeypatching.
Focus only on the exported classes and functions listed in the provided module outline.
Use the provided public API contract as ground truth for exact symbol names, enum members, constructor arguments, and entrypoints.
When an Exact test contract block is provided, treat it as the highest-priority import, method, and constructor surface. It overrides every generic example below.
When a task-level public contract anchor block is provided, treat it as higher priority than generic examples and use it to break ties in favor of the anchored facade, methods, and constructor fields.
If that anchor keeps batch behavior on the main facade through repeated single-request calls, write the batch scenario by repeating the anchored single-request surface instead of inventing renamed batch APIs.
Never reference a symbol, enum member, class attribute, or constructor shape that is not listed in that contract.
Concrete class, function, and field names that appear later in generic examples are placeholders only. Never copy example names such as ComplianceRequest, ComplianceService, validate_request, process_request, submit_intake, or batch_submit_intakes unless the provided contract, outline, behavior contract, or test targets list that exact name. Rewrite each generic example to the real module surface before you write the suite.
Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols. If the contract lists BatchProcessor or RiskScorer, do not invent ComplianceBatchProcessor, ComplianceScorer, ComplianceIntake, AuditLogger, or similar aliases.
If the contract lists submit_intake(...) and batch_submit_intakes(...), do not shorten them to submit(...) or submit_batch(...), even when calling ComplianceIntakeService() inline.
Do not import `main`, CLI/demo entrypoints, or any symbol listed under the provided entry points to avoid in tests guidance.
Treat CLI wrapper classes such as names ending in `CLI` or `Cli` as entrypoint surfaces to avoid in tests unless the task explicitly requires CLI coverage with controlled argv or input.
Import every production function you call from the target module.
Import every production class you instantiate or reference in a test or fixture from the target module.
If behavior is exposed as a class method, instantiate the class and call the method on the instance instead of importing the method name as a top-level function.
Write complete pytest code only; do not stop mid-test, mid-string, or mid-fixture.
Keep tests compact and execution-safe: prefer a few correct tests over broad but speculative coverage.
When a task gives only a maximum number of top-level tests, plan the full suite before writing and stay comfortably under that cap unless an exact count is explicitly required.
Leave at least one top-level test of headroom below a stated maximum unless the task explicitly requires the maximum count.
Before finalizing a compact suite, count top-level tests and total lines yourself. If the file is at or above any stated limit, delete the lowest-value helper coverage and merge overlapping assertions until the suite is back under budget.
When the task gives a hard line cap, target clear headroom below it instead of landing on the boundary. Remove docstrings, comments, extra blank lines, and optional helper scaffolding before dropping any required scenario.
Count fixtures before finalizing. If the task sets a maximum fixture budget, stay comfortably under it and inline one-off setup instead of adding a borderline extra fixture.
If the task sets a fixture maximum, target one fewer than that limit by default unless the documented contract clearly requires the extra fixture.
For compact scenario-driven tasks, merge overlapping checks into the smallest set of tests that covers the requested happy path, validation failure, and batch flow. Do not spend separate top-level tests on logging helpers, audit wrappers, or helper-level variants unless the contract explicitly requires those behaviors to be tested independently.
Do not hand-count prose strings to justify exact numeric assertions.
Do not hand-count prose strings, human-readable names, or email addresses to justify exact numeric assertions. If an exact numeric result is contractually required, use trivially countable inputs such as repeated characters or small literals; otherwise prefer stable invariants, ranges, or state transitions over guessed exact scores.
If an exact numeric assertion depends on string length, modulo, counts, or collection size, never use natural-language prose samples for that assertion.
If an exact numeric assertion depends on string length, modulo, counts, or collection size, never use natural-language prose samples, human-readable names, or email addresses for that assertion. Use repeated-character literals, small digit strings, or similarly obvious inputs whose size can be verified at a glance.
If an exact numeric assertion depends on top-level dict size or collection size, compute it from the actual top-level container passed into scoring rather than from nested values or magnitudes. If calculate_risk_score(data) returns float(len(data)) * 1.5 and two requests pass dicts with the same two top-level keys, both scores are 3.0 even when nested amounts or names differ.
If a scorer accepts a mixed semantic payload dict and the formula is not fully explicit, do not invent a guessed exact total such as 6.0 or a derived level such as medium by hand-counting keys and prose-like sample values. Example: for calculate_risk_score({"id": "1", "data1": "value1", "data2": "value2"}), do not assert 6.0 or level "medium" unless the formula explicitly says why; assert a contract-backed invariant such as non-negative score or relative ordering instead.
If an exact numeric assertion depends on string length or character count, do not pair exact score equality with word-like sample strings such as data, valid_data, or data1. Replace them with repeated-character literals such as aaaa or a * 20, or switch the assertion to a non-exact invariant.
If a required string field participates in a length- or modulo-based score, do not use an empty string to force score 0 in a non-error scenario. Use a non-empty repeated-character literal with the needed length instead; for len(details) % 10 == 0, use xxxxxxxxxx rather than "".
If score = (len(name) + len(email)) / 10.0, do not assert against a hand-counted literal for {"name": "Alice", "email": "alice@example.com"}; either compute the expectation from the visible formula, use repeated-character inputs with obvious lengths, or switch to a non-exact invariant.
If an exact numeric assertion depends on nested payload shape, compute it from the actual object passed into the scoring function rather than from an inner dict you assume the service extracted. Example: if request.data stores {"id": "1", "data": {"data_field": "example"}, "timestamp": "..."} and calculate_risk_score reads data.get("data_field", ""), the score is 0.0, not 7.0.
Do not assert exact categorical score bands or labels at boundary values unless the contract explicitly defines those cutoffs. For derived levels such as low, medium, or high, use values comfortably inside a band or assert relative ordering when the exact boundary is not part of the contract. Example: if score = amount * 0.1 and the level may change at 10, do not use amount=100 to assert an exact label; use 50 for a clear low case, 150 for a clear medium case, or assert only the numeric score.
If derived labels depend on count-based scores and the thresholds are not explicit, do not use borderline counts such as 2 to assert an exact low or medium label. Use 1 for a clear low case, 3 for a clear medium case, or assert only the numeric score.
Do not infer derived status transitions, escalation flags, or report counters from suggestive field names, keywords, or audit vocabulary alone. Assert those outcomes only when the behavior contract or the current implementation explicitly defines the trigger; otherwise assert direct observable state, totals, or non-exact invariants.
Do not hard-code exact response status labels such as accepted, rejected, pending_review, or flagged, and do not hard-code exact risk-summary bucket totals for specific batch items, unless the behavior contract or current implementation explicitly defines those triggers.
When an API accepts a request, filter, or payload dict with documented required fields, either supply every required field or omit that optional dict entirely. Do not assume partial filter payloads are accepted unless the contract explicitly marks those keys optional.
If a service stores the full raw request payload in a field such as request.data, do not assume that field was normalized to only an inner sub-dict. Example: if request_data = {"id": "req1", "data": {"field1": "value1"}} and intake_request stores ComplianceRequest.data = request_data, assert compliance_request.data == request_data or compliance_request.data["data"] == {"field1": "value1"} instead of asserting compliance_request.data == {"field1": "value1"}.
When a constructor or callable signature is listed in the API contract, use exactly that signature in every test.
When the API contract lists constructor fields for a typed request or result model, pass every listed field explicitly in test instantiations, including fields that have defaults, unless the contract explicitly shows omission as valid.
Do not rely on Python dataclass defaults just because omission would run. If the contract lists defaulted fields such as timestamp or status, pass them explicitly in every constructor call in the suite.
Example: if the contract lists ComplianceRequest(id, data, timestamp, status), write ComplianceRequest(id="1", data={"name": "John Doe", "amount": 1000}, timestamp=1.0, status="pending") instead of omitting timestamp and status.
Mirror the listed constructor exactly in every test call. If the public API says ComplianceRequest(id, user_id, data, timestamp, status), every constructor call in the suite must pass all five named arguments; do not omit status and rely on the dataclass default.
When you pass an explicit constructor field such as timestamp, use a self-contained literal or a local value defined before the constructor call. Do not read attributes from the object you are still constructing or any other undefined local. Example: define fixed_time = datetime(2023, 1, 1, 0, 0, 0) and pass timestamp=fixed_time instead of writing timestamp=request.timestamp inside request = ComplianceRequest(...).
Do not instantiate helper validators, scorers, loggers, dataclasses, or batch processors merely to wire a higher-level service fixture unless the public API contract explicitly requires that direct setup.
When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models rather than auxiliary validators, scorers, loggers, repositories, processors, or engines.
If you use isinstance or another exact type assertion against a returned production class, import that class explicitly; otherwise assert on returned fields or behavior without naming the unimported type.
When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity from that contract. Do not invent generic placeholders such as id, data, timestamp, or status when the contract lists different fields.
Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger. Otherwise assert stable invariants such as success, request identity, audit growth, and non-negative or relative scores.
Do not hard-code exact response.status labels such as accepted, rejected, pending_review, or flagged, and do not hard-code exact risk-summary bucket totals for specific batch items, unless the behavior contract or current implementation explicitly defines those triggers.
When repairing a previously generated suite that already passed static validation, preserve the existing imported symbols, constructor shapes, fixture payload structure, and scenario skeleton unless the validation summary explicitly identifies one of those pieces as invalid.
Preserve the exact documented public method names from the prior valid suite and contract during repair. Do not rename submit_intake(...) to submit(...) or batch_submit_intakes(...) to submit_batch(...).
When the previous validation summary reports constructor arity mismatches, treat those constructor calls as invalid and remove or rewrite them instead of preserving them from the earlier suite.
If the previous validation summary reports undefined local names or undefined fixtures, remove or rewrite every offending test unless you explicitly import or define those names in the rewritten file. In a compact suite, delete helper-only tests before adding new fixtures, caplog assertions, or extra helper imports.
If the previous validation summary reports helper surface usages, delete every import, fixture, helper variable, and top-level test that references those helper surfaces. Do not repair those helper-surface tests in place.
Do not replace one guessed helper with another guessed helper during repair. If a helper-surface test was invalid for ComplianceScorer, ComplianceBatchProcessor, AuditLogger, or a similar invented name, delete that helper-oriented test and rebuild around the documented service facade and request or result models only.
If flagged helper surfaces are provided separately in the repair context, treat those names as banned in the rewritten file unless the public API contract explicitly makes them the primary surface under test.
Treat the current implementation artifact and API contract as fixed ground truth during repair. Do not invent replacement response classes, alternate validators, renamed helpers, or new return-wrapper types.
If a pytest-only runtime failure shows that an earlier assertion overreached the current implementation or contract, rewrite that assertion to a contract-backed invariant instead of forcing a guessed business rule into the code.
Do not invent alternate field names, sample payload shapes, return structures, or exception messages.
Do not reference pytest fixtures unless you define them in the same file or they are standard built-in pytest fixtures.
If you use the `pytest.` namespace anywhere in the file, add `import pytest` explicitly at the top of the module. Do not rely on implicit availability of the pytest module.
Every test function argument must be a built-in pytest fixture, a fixture defined in the same file, or a name introduced by a matching `pytest.mark.parametrize` decorator.
Do not reference helper names or expected-value variables inside test bodies unless they are imported, defined in the same file, or introduced by the matching parametrization.
Do not call `main()`, CLI/demo entrypoints, or `argparse`-driven functions directly unless the task explicitly requires CLI testing and you fully control `sys.argv` or monkeypatch the parser inputs.
If the module exposes a CLI wrapper class or `run()` method for command-line flow, leave it out of the suite unless the task explicitly requires CLI testing and you fully control argv or input.
For happy-path tests, derive input payloads from the implementation summary so they satisfy the module's own validation rules.
When the task names only high-level workflow scenarios, keep the suite on the main service or batch surface and do not add direct unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly asks for them.
In compact high-level workflow suites, do not spend top-level tests on validator units, scorer units, dataclass serialization, audit logger wrappers, or other helper-only coverage unless the task explicitly names those helpers.
When the task requires both a validation-failure scenario and a batch-processing scenario, keep the validation-failure coverage on the direct intake or validation surface unless the behavior contract explicitly requires batch-level failure coverage.
If the validation-failure scenario is a missing-required-field case, omit only the field under test and keep the rest of that payload valid for the same surface so the test isolates one clear contract violation.
If required fields are validated before score_request, score_risk, process_request, or batch handling, do not create a separate invalid-scoring test that first calls intake_request on an invalid object. Keep that failure case on intake_request or validate_request, and reserve scoring assertions for already-valid inputs.
Do not assume empty strings, placeholder IDs, or domain keywords are invalid unless the behavior contract or implementation explicitly says so. For validation-failure coverage, prefer missing required fields or clearly wrong types over guessed business rules. If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict), an empty string or same-type placeholder still satisfies that validator, so use a non-string, non-dict, or similarly wrong-type value instead.
Example: if validate_request(request) only checks isinstance(request.id, str) and isinstance(request.data, dict), ComplianceRequest(id="", data={"field": "value"}) still passes. Use a non-string id or a non-dict data value for the failure case instead.
Apply the same rule to request_id, entity_id, document_id, and similar identifier fields: unless the contract explicitly says empty strings are invalid, request_id="" or another same-type placeholder can still pass, so prefer a wrong top-level type or a truly missing required field.
Apply the same rule to dict payload fields such as data, details, metadata, request_data, or document_data: an empty dict is still a same-type placeholder and may pass when validation only checks dict type, so prefer None, a non-dict value, or omission only when the contract explicitly allows omission.
If a workflow input still has the correct top-level type, do not expect ValueError just because one business value changed. Example: if submit_intake only validates that data.data is a dict, ComplianceData(id="1", data={"key": "wrong_value"}) is still valid input and should be asserted as a non-compliant result instead of being wrapped in pytest.raises(ValueError). Use a non-dict payload if you need a ValueError case.
Do not write a validation-failure test as `assert not validate_request(...)` or a similar falsy expectation unless the contract explicitly documents False as the invalid outcome. When the failure mode is uncertain, use a contract-backed wrong-type or missing-field input and assert the documented raise, rejected state, or batch result instead.
For process_request or other validation-gated workflow tests, choose an input that validate_request rejects before scoring runs. Do not use nested None values or same-type empty containers that can slip past validation and then fail later inside score_risk, calculate_risk_score, or similar scoring helpers with a different exception.
    If validation only checks an outer container type, do not assume a wrong nested value type makes the request invalid. Example: if validate_request(request) returns bool(request.id) and isinstance(request.data, dict), ComplianceRequest(id="1", data={"check": "not_a_bool"}, timestamp="2023-01-01T00:00:00Z", status="pending") still passes; use a non-dict data value or another explicitly invalid top-level field instead.
If validation or scoring guards a nested field with isinstance(...) before using it, a wrong nested field type is usually ignored rather than raising. Example: if calculate_risk_score only adds risk_factor when isinstance(request_data["risk_factor"], (int, float)), then risk_factor="invalid" does not raise TypeError; use a wrong top-level type or missing required field for failure coverage instead.
If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid instead of raising, assert that state on the same object you passed into the call.
Keep batch-processing scenarios structurally valid unless the behavior contract explicitly says partially invalid batch items are expected and defines the expected outcome.
If the provided test targets list batch-capable functions, use one of those functions for the batch scenario instead of inventing batch behavior for unrelated helpers.
If the public API exposes no dedicated batch helper, express the batch scenario as a short list of individually valid items processed one by one. Do not pass a list into scalar-only validators or scorers.
Example: if the module exposes only process_request(request) and no process_batch(...), write a short loop over two valid requests and assert the documented result of each process_request call instead of switching to logger, repository, scorer, or audit helpers.
If the module exposes only scalar validation, scoring, or audit helpers, cover the required happy path, validation failure, and batch-style loop with 3 to 4 tests total. Do not add separate standalone tests for each helper once those scenarios are covered.
If the module exposes only helper-level audit or logging functions, do not spend one of those limited tests on a standalone audit or log helper check. Fold any required audit call into the happy-path or batch-style scenario instead.
Example: if the module exposes validate_request(request), score_request(request), and log_audit(request_id, action, result), write exactly three tests: one happy-path test that validates and scores a valid request and may assert audit file creation or required substring presence, one validation-failure test using an invalid document_type or wrong-type document_data, and one batch-style loop over two valid requests. Do not add standalone score_request, log_audit, or extra invalid-case tests.
If a batch helper returns None or constructs its own domain objects from raw items, do not instantiate fresh objects after the batch call and assume they inherited internal mutations. Assert only directly observable outcomes, caller-owned object mutations, or behavior you explicitly patch in that test.
Prefer the highest-level public service or top-level workflow functions for the requested scenarios. Do not import repository, logger, scorer, validator, or similar helper services directly unless the API contract makes them the primary surface under test.
Never redeclare production dataclasses, business functions, CLI parsers, or other implementation code inside the pytest module. Import production symbols from the generated module and keep the test file as tests only.
Do not turn copied implementation into `test_main`, `test_all_tests`, or similar meta-tests that invoke argparse, print output, or manually call other tests.
Do not add caplog assertions or raw logging-text expectations unless the behavior contract explicitly states that emitted log output is part of the observable contract. If audit behavior must be checked, prefer deterministic assertions on returned state or audit records exposed by the service.
Do not compare full audit or log file contents by exact string equality or trailing-newline-sensitive text unless the contract explicitly defines that serialized format. Prefer stable assertions such as file creation, non-empty content, append growth, line count, or required substring presence.
Do not assert an exact runtime numeric type such as float unless the contract or current implementation explicitly casts to that type. If the current implementation computes a numeric score with int-like arithmetic such as modulo or counts, assert the documented value, numeric non-negativity, or a broader numeric invariant instead.
When an exact numeric score is required, derive it from only the branches exercised by the chosen input rather than summing unrelated branch outcomes.
Example: if score_request adds 1 for document_type == "income" and 2 for document_type == "employment", a request with document_type="income" should assert 1, not 3.
If a score formula combines weighted numeric fields, recompute the exact total from every exercised term using the current input values before asserting equality. Example: if score += request_data["risk_factor"] * 0.5 and score += (1 - request_data["compliance_history"]) * 0.5, then risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25.
If you assert audit records, assert only the actions exercised in that same scenario. Do not expect document-upload, status-change, or similar audit events unless the test performs that action directly.
If a scenario performs intake, scoring, and one error path, count all three audit entries. Do not drop the scoring log from the expected audit total.
If a batch scenario includes invalid items, count audit records from both the inner failing operation and any outer batch failure handler. One invalid batch item can emit two failure-related audit entries, and those must be added to any success-path audit records from valid items before asserting an exact audit length.
If process_batch or another batch helper internally performs intake and scoring for each valid item, count those inner success-path logs too before asserting any batch audit total. Example: a two-item valid batch can emit 5 audit logs, not 3, and a batch that fails on the second item can still already emit 2 logs, not 1, from the first valid item.
In batch scenarios, prefer assertions on returned results, terminal batch markers, or monotonic audit growth over an exact audit length unless the current implementation or contract explicitly enumerates every emitted log entry. If you cannot enumerate every internal log deterministically, do not assert an exact batch audit total.
Unless the current implementation or behavior contract explicitly enumerates every emitted batch log, do not write len(service.audit_logs) == N or a similar exact batch-audit assertion.
If a previous pytest failure showed a batch audit mismatch such as assert 5 == 3 on len(service.audit_logs), delete that exact count and replace it with stable checks such as result counts, required actions, terminal batch markers, or monotonic audit growth.
Never define a custom fixture named `request`; pytest reserves that name. Use inline setup or a specific fixture name such as `sample_request` instead.
Do not use mock-style bookkeeping assertions such as `.call_count` or `.assert_called_once()` on logging objects, production callables, or other real objects unless the same test first installs a real `Mock`, `MagicMock`, or `patch` target for that exact object.
If repair context suggests truncation or incomplete output, remove non-essential comments, blank lines, extra fixtures, and optional helper scaffolding before dropping any required scenario.
If you are repairing a previously invalid or truncated test file, rewrite the complete pytest module from the top instead of continuing from a partial tail."""

CONTRACT_FIRST_SYSTEM_PROMPT = """You are a QA Engineer at KYCortex AI Software House.
Return only raw Python pytest code.
When an Exact test contract block is provided, treat it as the ground truth for imports, facades, methods, and constructor fields.
When a task-level public contract anchor block is provided, treat it as higher priority than generic examples and keep the anchored facade, methods, and constructor fields exact.
Use the deterministic scaffold as the exact public-surface starting point when it is provided.
For compact anchored workflow tasks, default to exactly three top-level tests named test_happy_path, test_validation_failure, and test_batch_processing unless the exact contract or behavior contract explicitly requires more coverage.
For compact anchored workflow tasks with a hard line cap such as 150 lines, treat that trio as the effective maximum unless the exact contract or behavior contract explicitly requires more coverage. Delete any fourth-or-later top-level test before returning.
Do not use per-test docstrings in this compact mode. Strip comments, extra blank lines, and optional helper-only imports before returning.
If any test keeps datetime.now() or another bare datetime reference, a matching datetime import is mandatory at the top of the file. Otherwise remove bare datetime references and use a self-contained timestamp value that still satisfies the implementation contract.
If batch behavior is documented as repeated single-request calls on the main facade, write the batch scenario that way instead of inventing renamed batch helpers.
Do not copy placeholder example names or invent alternate helpers.
Stay under stated line, fixture, and top-level test limits.
Do not add duplicate-detection, risk-tier, audit-only, or helper-only tests unless the exact contract or behavior contract explicitly requires them.
Do not add helper-only imports or helper-only tests when a documented public service facade exists.
If repair feedback reports unknown symbols, invalid members, or constructor mismatches, rebuild from the exact contract and remove those invalid surfaces entirely.
Write a complete syntactically valid pytest module."""

class QATesterAgent(BaseAgent):
    required_context_keys = ("code",)
    output_artifact_type = ArtifactType.TEST
    output_artifact_name = "tests"

    _GENERIC_PLACEHOLDER_REPLACEMENTS: tuple[tuple[str, str], ...] = (
        (
            'ComplianceRequest(id="1", data={"name": "John Doe", "amount": 1000}, timestamp=1.0, status="pending")',
            '<request model>(field_a="1", field_b={"name": "John Doe", "amount": 1000}, field_c=1.0, field_d="pending")',
        ),
        (
            "ComplianceRequest(id, user_id, data, timestamp, status)",
            "<request model>(field_a, field_b, field_c, field_d, field_e)",
        ),
        (
            "ComplianceRequest(id, data, timestamp, status)",
            "<request model>(field_a, field_b, field_c, field_d)",
        ),
        (
            'ComplianceRequest(id="", data={"field": "value"})',
            '<request model>(field_a="", field_b={"field": "value"})',
        ),
        (
            'ComplianceRequest(id="1", data={"check": "not_a_bool"}, timestamp="2023-01-01T00:00:00Z", status="pending")',
            '<request model>(field_a="1", field_b={"check": "not_a_bool"}, field_c="2023-01-01T00:00:00Z", field_d="pending")',
        ),
        (
            'ComplianceData(id="1", data={"key": "wrong_value"})',
            '<request model>(field_a="1", field_b={"key": "wrong_value"})',
        ),
        (
            "timestamp=request.timestamp inside request = ComplianceRequest(...)",
            "field_c=current_value inside item = <request model>(...)",
        ),
        (
            "request_id=\"\" or another same-type placeholder can still pass",
            "a same-type identifier placeholder can still pass",
        ),
        (
            "ComplianceRequest.data = request_data",
            "<request model>.field_b = request_data",
        ),
        (
            "ComplianceRequest.data",
            "<request model>.field_b",
        ),
        (
            "ComplianceBatchProcessor",
            "<batch helper alias>",
        ),
        (
            "ComplianceScorer",
            "<scoring helper alias>",
        ),
        (
            "ComplianceIntakeService",
            "<service facade>",
        ),
        (
            "ComplianceService",
            "<service facade>",
        ),
        (
            "ComplianceRequest",
            "<request model>",
        ),
        (
            "ComplianceData",
            "<request model>",
        ),
        (
            "ComplianceResult",
            "<result model>",
        ),
        (
            "AuditLogger",
            "<audit helper alias>",
        ),
        (
            "BatchProcessor",
            "<batch helper>",
        ),
        (
            "RiskScorer",
            "<scoring helper>",
        ),
        (
            "ComplianceIntake",
            "<workflow alias>",
        ),
        (
            "batch_submit_intakes",
            "<batch workflow>",
        ),
        (
            "submit_batch",
            "<batch workflow alias>",
        ),
        (
            "process_batch",
            "<batch workflow>",
        ),
        (
            "submit_intake",
            "<primary workflow>",
        ),
        (
            "process_request",
            "<primary workflow>",
        ),
        (
            "validate_request",
            "<validation function>",
        ),
        (
            "score_request",
            "<scoring function>",
        ),
        (
            "score_risk",
            "<scoring function>",
        ),
        (
            "calculate_risk_score",
            "<scoring function>",
        ),
        (
            "log_audit",
            "<audit function>",
        ),
        (
            "intake_request",
            "<intake function>",
        ),
    )

    def __init__(self, config: KYCortexConfig):
        super().__init__("QATester", "Quality Assurance & Testing", config)

    @staticmethod
    def _normalized_helper_surface_symbols(raw_values: object) -> list[str]:
        if not isinstance(raw_values, list):
            return []

        seen: set[str] = set()
        symbols: list[str] = []
        for value in raw_values:
            if not isinstance(value, str):
                continue
            symbol = value.split(" (line ", 1)[0].strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
        return symbols

    def _repair_helper_surface_block(self, context: dict) -> str:
        raw_usages = context.get("repair_helper_surface_usages")
        usages = [item.strip() for item in raw_usages if isinstance(item, str) and item.strip()] if isinstance(raw_usages, list) else []
        symbols = self._normalized_helper_surface_symbols(context.get("repair_helper_surface_symbols"))
        if not symbols:
            symbols = self._normalized_helper_surface_symbols(usages)
        if not usages and not symbols:
            return ""

        lines = ["", "Flagged helper surfaces to remove during repair:"]
        if symbols:
            lines.append(f"    {', '.join(symbols)}")
        if usages:
            lines.extend([
                "Flagged helper-surface references from validation:",
                f"    {', '.join(usages)}",
            ])
        return "\n".join(lines)

    @staticmethod
    def _repair_focus_block(repair_validation_summary: object) -> str:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return ""

        normalized = repair_validation_summary.lower()
        focus_lines: list[str] = []
        undefined_local_names = {
            name.lower()
            for name in re.findall(
                r"[A-Za-z_][A-Za-z0-9_]*",
                QATesterAgent._summary_issue_value(repair_validation_summary, "Undefined local names"),
            )
        }

        if "pytest" in undefined_local_names or "name 'pytest' is not defined" in normalized:
            focus_lines.append(
                "- The previous file used `pytest.` without importing `pytest`. Add `import pytest` at the top if the rewritten suite keeps any `pytest.` references."
            )

        if "datetime" in undefined_local_names or "name 'datetime' is not defined" in normalized:
            focus_lines.append(
                "- The previous file referenced `datetime` without importing it. If any rewritten test keeps `datetime.now()` or another bare `datetime` reference, add a matching import such as `from datetime import datetime` or `import datetime` at the top before finalizing. Otherwise remove every bare `datetime` reference and switch those timestamp values to a self-contained literal or previously defined local that still matches the implementation contract."
            )

        if "line count" in normalized and "exceeds maximum" in normalized:
            focus_lines.append(
                "- The previous file failed because it exceeded the hard line budget. Rewrite to only the minimum contract-required trio, delete any fourth-or-later top-level test, remove per-test docstrings, comments, and extra blank lines, and drop validator-only, audit-only, risk-tier, or other helper-only coverage before touching the required scenarios."
            )

        other_undefined_names = sorted(
            name for name in undefined_local_names if name not in {"pytest", "datetime", "line"}
        )
        if other_undefined_names:
            focus_lines.append(
                "- The previous file referenced undefined local names. Import or define each referenced name before use, or remove those references entirely in the rewritten suite."
            )

        if ("audit_log" in normalized or "audit_logs" in normalized) and "assertionerror: assert" in normalized:
            focus_lines.append(
                "- The previous runtime failure came from a fragile exact audit-length check. Recreate fresh service/request objects inside each test and replace exact batch audit totals with stable delta, monotonic growth, or identity checks unless the contract explicitly enumerates every emitted entry."
            )

        if "pytest timed out" in normalized:
            focus_lines.append(
                "- The previous suite hung at runtime. Rewrite to the minimal contract-required trio only: happy path, validation failure, and batch processing. Remove duplicate-detection, risk-tier, audit-only, and other speculative extras unless the exact contract or behavior contract explicitly requires them."
            )

        if not focus_lines:
            return ""

        return "\n".join(["", "Repair focus:", *focus_lines])

    @classmethod
    def _abstract_generic_placeholders(cls, text: str) -> str:
        result = text
        for source, replacement in cls._GENERIC_PLACEHOLDER_REPLACEMENTS:
            result = result.replace(source, replacement)
        return result

    @staticmethod
    def _restore_preserved_sections(prompt: str, preserved_sections: list[str]) -> str:
        restored_prompt = prompt
        for section in preserved_sections:
            if not section:
                continue
            abstracted_section = QATesterAgent._abstract_generic_placeholders(section)
            restored_prompt = restored_prompt.replace(abstracted_section, section)
        return restored_prompt

    @staticmethod
    def _summary_has_active_issue(summary: object, label: str) -> bool:
        if not isinstance(summary, str):
            return False
        summary_lower = summary.lower()
        marker = f"{label}:"
        return marker in summary_lower and f"{marker} none" not in summary_lower

    @staticmethod
    def _summary_issue_value(summary: object, label: str) -> str:
        if not isinstance(summary, str):
            return ""
        prefix = f"- {label}:"
        for line in summary.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith(prefix.lower()):
                value = stripped[len(prefix):].strip()
                if value.lower() == "none":
                    return ""
                return value
        return ""

    @staticmethod
    def _contract_line_value(contract: object, label: str) -> str:
        if not isinstance(contract, str):
            return ""
        prefix = f"- {label}:"
        for line in contract.splitlines():
            stripped = line.strip()
            if stripped.startswith(prefix):
                value = stripped[len(prefix):].strip()
                if value.lower() == "none":
                    return ""
                return value
        return ""

    @staticmethod
    def _task_anchor_line_value(anchor: object, label: str) -> str:
        if not isinstance(anchor, str):
            return ""
        prefix = f"- {label}:"
        for line in anchor.splitlines():
            stripped = line.strip()
            if stripped.startswith(prefix):
                return stripped[len(prefix):].strip()
        return ""

    @staticmethod
    def _comma_separated_items(raw_value: str) -> list[str]:
        if not isinstance(raw_value, str):
            return []

        items: list[str] = []
        current: list[str] = []
        depth = 0
        for char in raw_value:
            if char == "," and depth == 0:
                item = "".join(current).strip()
                if item and item.lower() != "none":
                    items.append(item)
                current = []
                continue
            if char in "([{":
                depth += 1
            elif char in ")]}" and depth > 0:
                depth -= 1
            current.append(char)

        item = "".join(current).strip()
        if item and item.lower() != "none":
            items.append(item)
        return items

    @staticmethod
    def _string_list(raw_value: object) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        return [item for item in raw_value if isinstance(item, str) and item]

    @staticmethod
    def _parameter_name(parameter: str) -> str:
        cleaned = parameter.strip()
        if not cleaned:
            return ""
        cleaned = cleaned.split(":", 1)[0]
        cleaned = cleaned.split("=", 1)[0]
        return cleaned.lstrip("*").strip()

    @classmethod
    def _signature_name_and_params(cls, signature: str) -> tuple[str, list[str]]:
        if not isinstance(signature, str):
            return "", []
        stripped = signature.strip()
        if not stripped or stripped.lower() == "none":
            return "", []
        if "(" not in stripped or not stripped.endswith(")"):
            return stripped, []
        name, raw_params = stripped.split("(", 1)
        return name.strip(), cls._comma_separated_items(raw_params[:-1])

    @classmethod
    def _task_anchor_overrides(cls, task_public_contract_anchor: object) -> dict[str, object]:
        if not isinstance(task_public_contract_anchor, str) or not task_public_contract_anchor.strip():
            return {}

        facade = cls._task_anchor_line_value(task_public_contract_anchor, "Public facade")
        request_model = cls._task_anchor_line_value(
            task_public_contract_anchor,
            "Primary request model",
        )
        request_workflow = cls._task_anchor_line_value(
            task_public_contract_anchor,
            "Required request workflow",
        )
        validation_surface = cls._task_anchor_line_value(
            task_public_contract_anchor,
            "Supporting validation surface",
        )
        request_model_name, _ = cls._signature_name_and_params(request_model)
        suppress_batch_aliases = "repeated handle_request(request) calls" in task_public_contract_anchor

        allowed_imports = [item for item in (facade, request_model_name) if item]
        exact_methods = [item for item in (request_workflow, validation_surface) if item]

        return {
            "allowed_imports": allowed_imports,
            "preferred_facades": [facade] if facade else [],
            "exact_methods": exact_methods,
            "exact_constructors": [request_model] if request_model else [],
            "request_model_signature": request_model,
            "request_workflow": request_workflow,
            "suppress_batch_aliases": suppress_batch_aliases,
        }

    @classmethod
    def _task_public_contract_anchor_block(cls, task_public_contract_anchor: object) -> str:
        if not isinstance(task_public_contract_anchor, str) or not task_public_contract_anchor.strip():
            return ""

        overrides = cls._task_anchor_overrides(task_public_contract_anchor)
        request_model_signature = overrides.get("request_model_signature", "")
        request_model_name, _ = cls._signature_name_and_params(str(request_model_signature))
        request_workflow = str(overrides.get("request_workflow", "") or "")

        lines = ["Task-level public contract anchor:", task_public_contract_anchor]
        if request_workflow and overrides.get("suppress_batch_aliases"):
            lines.append(
                f"Treat that anchor as exact. For batch coverage, loop over {request_workflow} with multiple valid items instead of inventing renamed batch helpers such as process_batch(...), batch_process(...), or batch_intake_requests(...)."
            )
        if request_model_name and isinstance(request_model_signature, str) and "timestamp" in request_model_signature:
            lines.append(
                f"Because the anchor lists timestamp in {request_model_signature}, every {request_model_name}(...) call in the suite must pass timestamp explicitly."
            )
        return "\n".join(lines)

    @staticmethod
    def _compact_task_constraints_block(task_description: str) -> str:
        if not isinstance(task_description, str) or not task_description.strip():
            return ""

        summary_source = task_description.split("Public contract anchor:", 1)[0]
        normalized = re.sub(r"\s+", " ", summary_source).strip()
        if not normalized:
            normalized = re.sub(r"\s+", " ", task_description).strip()
        if not normalized:
            return ""

        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", normalized)
            if sentence.strip()
        ]
        selected = sentences[:4] if sentences else [normalized]
        lines = ["Task constraints summary:"]
        lines.extend(f"- {sentence}" for sentence in selected)
        return "\n".join(lines)

    @staticmethod
    def _contract_first_user_guidance(module_name: str, module_filename: str) -> str:
        return f"""Write a complete raw pytest file.
Import only documented top-level symbols from `{module_name}`.
Use the deterministic scaffold above as the exact starting surface.
Keep the anchored facade, methods, and constructor fields exact.
Default to exactly 3 top-level tests named `test_happy_path`, `test_validation_failure`, and `test_batch_processing` when those cover the required scope.
If the task also says to prefer 3 to 5 tests, resolve that softer preference in favor of exactly those 3 tests when they already cover the required scope.
For hard caps like 150 lines, treat that trio as the effective maximum unless the exact contract or behavior contract explicitly requires more coverage. Delete any fourth-or-later test before finalizing.
Do not add per-test docstrings in this compact mode. Strip comments, extra blank lines, and optional helper-only imports before finalizing.
Use 0 fixtures by default in this compact mode and inline setup instead of spending budget on reusable fixtures unless the exact contract clearly requires one.
Keep mutable service instances and request objects local to each test or a local helper; do not share a module-level service or request object across tests.
If the suite uses `pytest.` anywhere, keep `import pytest` explicitly at the top of the module.
If the suite uses `datetime.now()` or any other bare `datetime` reference, you must add a matching datetime import at the top before finalizing. Do not leave bare `datetime.now()` calls without that import; if you choose not to import datetime, remove every bare datetime reference and use a self-contained timestamp value that still satisfies the implementation contract.
Pass every documented constructor field explicitly, including timestamp when it is listed.
If no dedicated batch helper is documented, keep batch coverage on the documented single-request surface by looping over valid inputs instead of inventing renamed helpers.
Stay on the main service facade; do not add helper-only imports or helper-only tests.
Do not add duplicate-detection, risk-tier, audit-only, or helper-only tests unless the exact contract or behavior contract explicitly requires them.
Keep the suite under the stated line, fixture, and top-level-test caps.
Avoid guessed exact score totals, guessed derived labels, and guessed exact audit lengths unless the behavior contract explicitly defines them.
Avoid guessed exact response.status labels and guessed exact risk-summary bucket totals for batch items unless the behavior contract or current implementation explicitly defines those triggers.
When batch behavior mutates audit state, prefer stable delta or monotonic-growth checks over a global exact total unless the contract explicitly enumerates every emitted entry.
If repair feedback lists unknown symbols, invalid members, or constructor mismatches, remove those invalid surfaces and rebuild from the exact contract instead of patching guessed helpers.
Assume the module code already exists in `{module_filename}`.
Return complete raw Python only."""

    @staticmethod
    def _snake_case_name(name: str) -> str:
        stripped = name.strip()
        if not stripped:
            return "value"

        result: list[str] = []
        for index, char in enumerate(stripped):
            if not char.isalnum():
                if result and result[-1] != "_":
                    result.append("_")
                continue
            if char.isupper() and result:
                previous = stripped[index - 1]
                next_char = stripped[index + 1] if index + 1 < len(stripped) else ""
                if previous.islower() or (previous.isupper() and next_char.islower()):
                    if result[-1] != "_":
                        result.append("_")
                result.append(char.lower())
                continue
            result.append(char.lower())
        return "".join(result).strip("_") or "value"

    @classmethod
    def _instance_name_for_class(cls, class_name: str) -> str:
        lowered = class_name.lower()
        if any(token in lowered for token in ("service", "workflow", "manager", "processor", "engine", "handler")):
            return "service"
        if "request" in lowered:
            return "request"
        if any(token in lowered for token in ("result", "response", "outcome")):
            return "result"
        if "record" in lowered:
            return "record"
        return cls._snake_case_name(class_name)

    @classmethod
    def _sample_literal_for_parameter(cls, parameter: str, *, index: int = 0) -> str:
        name = cls._parameter_name(parameter)
        lowered = name.lower()
        if lowered in {"a", "b", "x", "y", "left", "right"}:
            return str(index + 1)
        if lowered == "id" or lowered.endswith("_id"):
            return f'"{lowered}-1"'
        if lowered.endswith("_type") or lowered in {"type", "kind", "category"}:
            return '"screening"'
        if lowered in {"status", "state"} or lowered.endswith("_status"):
            return '"pending"'
        if lowered in {"action", "result", "outcome"}:
            return '"accepted"'
        if lowered.startswith("is_") or lowered.startswith("has_") or lowered.endswith("_enabled"):
            return "True"
        if any(token in lowered for token in ("timestamp", "created_at", "updated_at", "time", "date")):
            return "1.0"
        if any(token in lowered for token in ("details", "detail", "data", "payload", "metadata", "meta", "content", "attributes", "context")):
            return '{"source": "web"}'
        if any(token in lowered for token in ("count", "limit", "size", "score", "amount", "level", "priority", "age", "days", "number", "total")):
            return "1"
        return f'"sample_{index + 1}"'

    @classmethod
    def _preferred_constructor_signature(
        cls,
        constructor_refs: list[str],
        preferred_facades: list[str],
    ) -> str:
        if not constructor_refs:
            return ""

        for signature in constructor_refs:
            class_name, _ = cls._signature_name_and_params(signature)
            lowered = class_name.lower()
            if class_name in preferred_facades:
                continue
            if any(token in lowered for token in ("service", "workflow", "manager", "processor", "engine", "handler")):
                continue
            return signature
        return constructor_refs[0]

    @classmethod
    def _constructor_scaffold_line(cls, signature: str) -> tuple[str, str]:
        class_name, constructor_expr = cls._constructor_call_expression(signature)
        if not class_name:
            return "", ""

        variable_name = cls._instance_name_for_class(class_name)
        return variable_name, f"{variable_name} = {constructor_expr}"

    @classmethod
    def _constructor_call_expression(
        cls,
        signature: str,
        *,
        index_offset: int = 0,
    ) -> tuple[str, str]:
        class_name, parameters = cls._signature_name_and_params(signature)
        if not class_name:
            return "", ""

        if not parameters:
            return class_name, f"{class_name}()"

        arguments = []
        for index, parameter in enumerate(parameters):
            parameter_name = cls._parameter_name(parameter)
            if not parameter_name:
                continue
            arguments.append(
                f"{parameter_name}={cls._sample_literal_for_parameter(parameter_name, index=index + index_offset)}"
            )
        return class_name, f"{class_name}({', '.join(arguments)})"

    @classmethod
    def _batch_loop_scaffold_lines(
        cls,
        *,
        primary_method: str,
        preferred_constructor: str,
    ) -> list[str]:
        if "." not in primary_method or not preferred_constructor:
            return []

        class_name, method_name = primary_method.split(".", 1)
        service_name = cls._instance_name_for_class(class_name)
        _, first_request_expr = cls._constructor_call_expression(
            preferred_constructor,
            index_offset=0,
        )
        _, second_request_expr = cls._constructor_call_expression(
            preferred_constructor,
            index_offset=1,
        )
        if not first_request_expr or not second_request_expr:
            return []

        return [
            f"{service_name} = {class_name}()",
            "requests = [",
            f"    {first_request_expr},",
            f"    {second_request_expr},",
            "]",
            "for request in requests:",
            f"    result = {service_name}.{method_name}(request)",
        ]

    @classmethod
    def _callable_scaffold_line(cls, signature: str, constructor_variable: str) -> str:
        callable_name, parameters = cls._signature_name_and_params(signature)
        if not callable_name:
            return ""

        arguments = []
        for index, parameter in enumerate(parameters):
            parameter_name = cls._parameter_name(parameter)
            lowered = parameter_name.lower()
            if constructor_variable and any(
                token in lowered for token in ("request", "item", "record", "entry", "document", "model")
            ):
                if lowered.endswith("s") or "batch" in callable_name.lower():
                    arguments.append(f"[{constructor_variable}]")
                else:
                    arguments.append(constructor_variable)
                continue
            arguments.append(cls._sample_literal_for_parameter(parameter_name, index=index))

        if not arguments and "batch" in callable_name.lower():
            return f"result = {callable_name}(...)"
        return f"result = {callable_name}({', '.join(arguments)})"

    @classmethod
    def _method_scaffold_lines(cls, method_ref: str, constructor_variable: str) -> tuple[str, str]:
        if "." not in method_ref:
            return "", ""

        class_name, method_name = method_ref.split(".", 1)
        service_name = cls._instance_name_for_class(class_name)
        service_line = f"{service_name} = {class_name}()"

        if constructor_variable:
            argument = f"[{constructor_variable}]" if "batch" in method_name.lower() else constructor_variable
            return service_line, f"result = {service_name}.{method_name}({argument})"
        if "batch" in method_name.lower():
            return service_line, f"result = {service_name}.{method_name}(...)"
        return service_line, f"result = {service_name}.{method_name}()"

    @classmethod
    def _deterministic_surface_scaffold_block(
        cls,
        *,
        module_name: str,
        task_description: str,
        code_exact_test_contract: object,
        code_test_targets: object,
        task_public_contract_anchor: object,
    ) -> str:
        if not isinstance(code_exact_test_contract, str) or not code_exact_test_contract.strip():
            return ""

        allowed_imports = cls._comma_separated_items(
            cls._contract_line_value(code_exact_test_contract, "Allowed production imports")
        )
        preferred_facades = cls._comma_separated_items(
            cls._contract_line_value(code_exact_test_contract, "Preferred service or workflow facades")
        )
        exact_callables = cls._comma_separated_items(
            cls._contract_line_value(code_exact_test_contract, "Exact public callables")
        )
        exact_methods = cls._comma_separated_items(
            cls._contract_line_value(code_exact_test_contract, "Exact public class methods")
        )
        exact_constructors = cls._comma_separated_items(
            cls._contract_line_value(code_exact_test_contract, "Exact constructor fields")
        )

        anchor_overrides = cls._task_anchor_overrides(task_public_contract_anchor)
        if anchor_overrides:
            allowed_imports = cls._string_list(anchor_overrides.get("allowed_imports")) or allowed_imports
            preferred_facades = cls._string_list(anchor_overrides.get("preferred_facades")) or preferred_facades
            exact_callables = []
            exact_methods = cls._string_list(anchor_overrides.get("exact_methods")) or exact_methods
            exact_constructors = cls._string_list(anchor_overrides.get("exact_constructors")) or exact_constructors

        preferred_constructor = cls._preferred_constructor_signature(exact_constructors, preferred_facades)
        constructor_variable, constructor_line = cls._constructor_scaffold_line(preferred_constructor)

        primary_method = ""
        if preferred_facades:
            for facade in preferred_facades:
                primary_method = next(
                    (
                        item
                        for item in exact_methods
                        if item.startswith(f"{facade}.") and "batch" not in item.lower()
                    ),
                    "",
                )
                if primary_method:
                    break
        if not primary_method:
            primary_method = next(
                (item for item in exact_methods if "batch" not in item.lower()),
                exact_methods[0] if exact_methods else "",
            )

        primary_callable = next(
            (item for item in exact_callables if "batch" not in item.lower()),
            exact_callables[0] if exact_callables else "",
        )

        service_line = ""
        call_line = ""
        if primary_method and (preferred_facades or not primary_callable):
            service_line, call_line = cls._method_scaffold_lines(primary_method, constructor_variable)
        elif primary_callable:
            call_line = cls._callable_scaffold_line(primary_callable, constructor_variable)
        elif primary_method:
            service_line, call_line = cls._method_scaffold_lines(primary_method, constructor_variable)

        batch_method = ""
        if preferred_facades:
            for facade in preferred_facades:
                batch_method = next(
                    (
                        item
                        for item in exact_methods
                        if item.startswith(f"{facade}.") and "batch" in item.lower()
                    ),
                    "",
                )
                if batch_method:
                    break
        if anchor_overrides.get("suppress_batch_aliases"):
            batch_method = ""
        elif not batch_method:
            batch_method = next((item for item in exact_methods if "batch" in item.lower()), "")

        batch_callable = ""
        if not anchor_overrides.get("suppress_batch_aliases"):
            batch_callable = next((item for item in exact_callables if "batch" in item.lower()), "")
        batch_call_line = ""
        if batch_method:
            _, batch_call_line = cls._method_scaffold_lines(batch_method, constructor_variable)
        elif batch_callable:
            batch_call_line = cls._callable_scaffold_line(batch_callable, constructor_variable)

        batch_requested = any(
            isinstance(value, str) and "batch" in value.lower()
            for value in (task_description, code_test_targets)
        )
        documented_batch_surface = any(
            "batch" in item.lower() for item in [*exact_callables, *exact_methods]
        )
        primary_body_lines = [line for line in (service_line, constructor_line, call_line) if line]
        batch_body_lines = [line for line in (service_line, constructor_line, batch_call_line) if line]
        if batch_requested and not batch_call_line and primary_method and preferred_constructor:
            batch_body_lines = cls._batch_loop_scaffold_lines(
                primary_method=primary_method,
                preferred_constructor=preferred_constructor,
            )
        body_lines = [*primary_body_lines, *batch_body_lines]
        if not allowed_imports and not body_lines:
            return ""

        lines = [
            "",
            "Deterministic pytest scaffold anchor:",
            "Copy this exact import and test-safe surface shape. Change only literal values when the task requires it.",
            "```python",
            "import pytest",
        ]
        if allowed_imports:
            lines.append(f"from {module_name} import {', '.join(allowed_imports)}")
        if primary_body_lines or batch_body_lines:
            if allowed_imports:
                lines.append("")
            if primary_body_lines:
                lines.append("def test_happy_path():")
                seen_primary_lines: set[str] = set()
                for line in primary_body_lines:
                    if line in seen_primary_lines:
                        continue
                    seen_primary_lines.add(line)
                    lines.append(f"    {line}")
            if batch_body_lines:
                lines.append("")
                lines.append("def test_batch_processing():")
                seen_batch_lines: set[str] = set()
                for line in batch_body_lines:
                    if line in seen_batch_lines:
                        continue
                    seen_batch_lines.add(line)
                    lines.append(f"    {line}")
        lines.append("```")
        lines.append(
            "- Preserve every import, facade, method name, and constructor field from this scaffold exactly. Do not rename them."
        )
        lines.append(
            "- Keep mutable services and request objects local to each test or a local helper. Do not lift them to module scope."
        )
        lines.append(
            "- In compact contract-first mode, default to only the required trio: happy path, validation failure, and batch processing. Do not add duplicate-detection, risk-tier, audit-only, or other speculative extras unless the exact contract explicitly requires them."
        )
        if preferred_facades:
            lines.append(
                f"- Keep the suite centered on {', '.join(preferred_facades)} instead of auxiliary helpers."
            )

        if batch_requested and batch_body_lines and anchor_overrides.get("suppress_batch_aliases"):
            lines.append(
                "- The task-level contract keeps batch behavior on repeated single-request calls. For batch coverage, loop over the non-batch call above instead of inventing a renamed batch helper."
            )
            lines.append(
                "- For that batch loop, prefer assertions on response count, request identity, validation shape, or monotonic service state. Do not hard-code pending_review, accepted, rejected, or exact high-risk counters unless the contract explicitly defines those outcomes."
            )
        elif batch_requested and call_line and not documented_batch_surface:
            lines.append(
                "- No dedicated batch surface is documented here. For batch coverage, loop over the non-batch call above with multiple valid items instead of inventing a renamed batch helper."
            )
            lines.append(
                "- For that batch loop, prefer assertions on response count, request identity, validation shape, or monotonic service state. Do not hard-code pending_review, accepted, rejected, or exact high-risk counters unless the contract explicitly defines those outcomes."
            )
        return "\n".join(lines)

    @classmethod
    def _should_rebuild_from_exact_contract(
        cls,
        *,
        code_exact_test_contract: object,
        repair_validation_summary: object,
    ) -> bool:
        if not isinstance(code_exact_test_contract, str) or not code_exact_test_contract.strip():
            return False
        return any(
            cls._summary_has_active_issue(repair_validation_summary, label)
            for label in (
                "unknown module symbols",
                "invalid member references",
                "constructor arity mismatches",
            )
        )

    @classmethod
    def _existing_tests_context_and_instruction(
        cls,
        *,
        existing_tests: object,
        code_exact_test_contract: object,
        repair_validation_summary: object,
    ) -> tuple[str, str]:
        if cls._should_rebuild_from_exact_contract(
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
        ):
            return (
                "Previous invalid pytest file omitted because the validation summary already reported invalid import, member, or constructor surface errors. Rebuild the suite from the Exact test contract and current implementation instead of preserving or patching the prior file.",
                "The previous validation summary already reported invalid import, member, or constructor surfaces. Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation instead.",
            )

        if isinstance(existing_tests, str):
            existing_tests_context = existing_tests
        else:
            existing_tests_context = ""

        return (
            existing_tests_context,
            "Repair the existing pytest file above when it is provided. Preserve every valid import, fixture, and scenario that already matches the contract, and change only the parts needed to fix the reported blockers.",
        )

    @classmethod
    def _exact_rebuild_surface_block(
        cls,
        *,
        code_exact_test_contract: object,
        repair_validation_summary: object,
        task_public_contract_anchor: object,
    ) -> str:
        if not cls._should_rebuild_from_exact_contract(
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
        ):
            return ""

        allowed_imports = cls._comma_separated_items(
            cls._contract_line_value(code_exact_test_contract, "Allowed production imports")
        )
        preferred_facades = cls._contract_line_value(
            code_exact_test_contract,
            "Preferred service or workflow facades",
        )
        exact_callables = cls._comma_separated_items(
            cls._contract_line_value(code_exact_test_contract, "Exact public callables")
        )
        exact_methods = cls._comma_separated_items(
            cls._contract_line_value(code_exact_test_contract, "Exact public class methods")
        )
        exact_constructors = cls._contract_line_value(
            code_exact_test_contract,
            "Exact constructor fields",
        )

        anchor_overrides = cls._task_anchor_overrides(task_public_contract_anchor)
        if anchor_overrides:
            allowed_imports = cls._string_list(anchor_overrides.get("allowed_imports")) or allowed_imports
            preferred_facades = ", ".join(cls._string_list(anchor_overrides.get("preferred_facades"))) or preferred_facades
            exact_callables = []
            exact_methods = cls._string_list(anchor_overrides.get("exact_methods")) or exact_methods
            exact_constructors = ", ".join(cls._string_list(anchor_overrides.get("exact_constructors"))) or exact_constructors
        unknown_symbols = cls._summary_issue_value(
            repair_validation_summary,
            "Unknown module symbols",
        )
        invalid_members = cls._summary_issue_value(
            repair_validation_summary,
            "Invalid member references",
        )

        exact_surfaces = [*exact_callables, *exact_methods]
        documented_batch_surface = any("batch" in item.lower() for item in exact_surfaces)
        documented_single_surface = next(
            (item for item in exact_surfaces if "batch" not in item.lower()),
            "",
        )
        primary_exact_method = exact_methods[0] if exact_methods else ""

        lines = ["", "Exact rebuild surface:"]
        if allowed_imports:
            lines.append(f"- Allowed imports only: {', '.join(allowed_imports)}")
        if preferred_facades:
            lines.append(f"- Center the suite on this documented facade: {preferred_facades}")
        if exact_surfaces:
            lines.append(f"- Use only these documented callables or methods: {', '.join(exact_surfaces)}")
        if primary_exact_method:
            lines.append(
                f"- Keep documented method names exact. Do not shorten or rename {primary_exact_method}."
            )
        if exact_constructors:
            lines.append(f"- Mirror only these documented constructors: {exact_constructors}")
        if unknown_symbols:
            lines.append(
                f"- Unknown symbols from the previous validation are forbidden in the rewritten file: {unknown_symbols}"
            )
        if invalid_members:
            lines.append(
                f"- Invalid member references from the previous validation are forbidden in the rewritten file: {invalid_members}"
            )
        if anchor_overrides.get("suppress_batch_aliases") and documented_single_surface:
            lines.append(
                f"- The task-level anchor keeps batch coverage on {documented_single_surface}. Do not invent renamed batch helpers such as process_batch(...), batch_process(...), or batch_intake_requests(...)."
            )
        request_model_signature = str(anchor_overrides.get("request_model_signature") or "")
        request_model_name, _ = cls._signature_name_and_params(request_model_signature)
        if request_model_name and "timestamp" in request_model_signature:
            lines.append(
                f"- Because the task-level anchor lists {request_model_signature}, every {request_model_name}(...) call must pass timestamp explicitly."
            )
        if documented_single_surface and not documented_batch_surface:
            lines.append(
                "- No batch helper is documented in the exact contract. "
                f"For any batch scenario, loop over {documented_single_surface} for multiple valid inputs instead of inventing batch helpers or renamed methods."
            )
        lines.append(
            "- Any import, method, or constructor field not listed in the Exact test contract is forbidden in the rewritten file."
        )
        return "\n".join(lines)

    def _placeholder_safe_prompt_pair(
        self,
        *,
        system_prompt: str,
        user_message: str,
        code_exact_test_contract: str,
        preserved_sections: list[str],
    ) -> tuple[str, str]:
        if not isinstance(code_exact_test_contract, str) or not code_exact_test_contract.strip():
            return system_prompt, user_message

        abstracted_system_prompt = self._abstract_generic_placeholders(system_prompt)
        abstracted_user_message = self._abstract_generic_placeholders(user_message)
        restored_user_message = self._restore_preserved_sections(abstracted_user_message, preserved_sections)
        return abstracted_system_prompt, restored_user_message

    def run_with_input(self, agent_input: AgentInput) -> str:
        implementation_code = self.require_context_value(agent_input, "code")
        existing_tests = agent_input.context.get("existing_tests", "")
        module_name = agent_input.context.get("module_name", "module")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        code_summary = agent_input.context.get("code_summary", "")
        code_outline = agent_input.context.get("code_outline", "")
        code_public_api = agent_input.context.get("code_public_api", "")
        code_exact_test_contract = agent_input.context.get("code_exact_test_contract", "")
        code_test_targets = agent_input.context.get("code_test_targets", "")
        code_behavior_contract = agent_input.context.get("code_behavior_contract", "")
        task_public_contract_anchor = agent_input.context.get("task_public_contract_anchor", "")
        repair_validation_summary = agent_input.context.get("repair_validation_summary", "")
        budget_decomposition_brief = agent_input.context.get("budget_decomposition_brief", "")
        budget_decomposition_block = (
            f"Budget decomposition brief:\n    {budget_decomposition_brief}\n\n"
            if isinstance(budget_decomposition_brief, str) and budget_decomposition_brief.strip()
            else ""
        )
        repair_helper_surface_block = self._repair_helper_surface_block(agent_input.context)
        repair_focus_block = self._repair_focus_block(repair_validation_summary)
        existing_tests_context, repair_instruction = self._existing_tests_context_and_instruction(
            existing_tests=existing_tests,
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
        )
        exact_rebuild_surface_block = self._exact_rebuild_surface_block(
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
            task_public_contract_anchor=task_public_contract_anchor,
        )
        deterministic_surface_scaffold_block = self._deterministic_surface_scaffold_block(
            module_name=module_name,
            task_description=agent_input.task_description,
            code_exact_test_contract=code_exact_test_contract,
            code_test_targets=code_test_targets,
            task_public_contract_anchor=task_public_contract_anchor,
        )
        task_public_contract_anchor_block = self._task_public_contract_anchor_block(
            task_public_contract_anchor
        )
        contract_first_mode = bool(task_public_contract_anchor_block)
        task_constraints_block = self._compact_task_constraints_block(
            agent_input.task_description
        )
        user_msg = f"""Project: {agent_input.project_name}
    Project goal: {agent_input.project_goal}
    Implementation summary: {code_summary}
    Implementation code:
    {implementation_code}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}
    {code_exact_test_contract}
    {code_test_targets}
    {task_public_contract_anchor_block}
    {deterministic_surface_scaffold_block}
    Behavior contract:
    {code_behavior_contract}

Existing tests context:
    {existing_tests_context}

{repair_instruction}{exact_rebuild_surface_block}
If the previous validation summary lists constructor arity mismatches, remove or rewrite those constructor calls instead of preserving guessed helper wiring from the old suite.

Previous validation summary:
    {repair_validation_summary}{repair_helper_surface_block}{repair_focus_block}

{budget_decomposition_block}If a budget decomposition brief is provided, treat it as the compact rewrite plan for this suite. Keep the required scenarios it names, merge or delete the optional coverage it says to cut, and follow its write order so the rewritten file stays under budget.

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.

Module name: {module_name}
Module file: {module_filename}
Task: {agent_input.task_description}

Write a complete raw pytest file.
Import from `{module_name}` and test the actual public functions and classes from that module.
    Import every called production function explicitly from `{module_name}`.
    Import only top-level functions and classes from `{module_name}`.
    When an Exact test contract block is provided above, treat it as the highest-priority import, method, and constructor surface. It overrides every generic example below.
    When a Task-level public contract anchor block is provided above, treat it as higher priority than generic examples and break ties in favor of the anchored facade, methods, and constructor fields.
    If that anchor keeps batch behavior on the same facade through repeated single-request calls, do not invent renamed batch helpers such as process_batch(...), batch_process(...), or batch_intake_requests(...).
    Concrete class, function, and field names that appear later in generic examples are placeholders only. Never copy example names such as ComplianceRequest, ComplianceService, validate_request, process_request, submit_intake, or batch_submit_intakes unless the provided contract, outline, behavior contract, or test targets list that exact name. Rewrite each generic example to the real module surface before you write the suite.
    Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols. If the contract lists BatchProcessor or RiskScorer, do not invent ComplianceBatchProcessor, ComplianceScorer, ComplianceIntake, AuditLogger, or similar aliases.
    If the contract lists submit_intake(...) and batch_submit_intakes(...), do not shorten them to submit(...) or submit_batch(...), even when calling ComplianceIntakeService() inline.
    Do not import `main`, CLI/demo entrypoints, or any symbol listed under the provided Entry points to avoid in tests guidance.
    Do not import or instantiate CLI wrapper classes such as names ending in `CLI` or `Cli` unless the task explicitly requires CLI testing and you fully control argv or input.
    Import every production class you instantiate or reference in a fixture or test body.
    Do not hand-wire validator, scorer, logger, batch-processor, dataclass, or similar helper objects into a service fixture unless the public API contract explicitly requires those constructor arguments.
    When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models instead of auxiliary validators, scorers, loggers, repositories, processors, or engines.
    If you use isinstance or another exact type assertion against a returned production class, import that class explicitly; otherwise assert on returned fields or behavior without naming the unimported type.
    When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity from that contract. Do not invent generic placeholders such as id, data, timestamp, or status when the contract lists different fields.
    When the API contract lists constructor fields for a typed request or result model, pass every listed field explicitly in test instantiations, including fields that have defaults, unless the contract explicitly shows omission as valid.
    Do not rely on Python dataclass defaults just because omission would run. If the contract lists defaulted fields such as timestamp or status, pass them explicitly in every constructor call in the suite.
    Example: if the contract lists ComplianceRequest(id, data, timestamp, status), write ComplianceRequest(id="1", data={{"name": "John Doe", "amount": 1000}}, timestamp=1.0, status="pending") instead of omitting timestamp and status.
    Mirror the listed constructor exactly in every test call. If the public API says ComplianceRequest(id, user_id, data, timestamp, status), every constructor call in the suite must pass all five named arguments; do not omit status and rely on the dataclass default.
    When you pass an explicit constructor field such as timestamp, use a self-contained literal or a local value defined before the constructor call. Do not read attributes from the object you are still constructing or any other undefined local. Example: define fixed_time = datetime(2023, 1, 1, 0, 0, 0) and pass timestamp=fixed_time instead of writing timestamp=request.timestamp inside request = ComplianceRequest(...).
    Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger. Otherwise assert stable invariants such as success, request identity, audit growth, and non-negative or relative scores.
    Do not hard-code exact response.status labels such as accepted, rejected, pending_review, or flagged, and do not hard-code exact risk-summary bucket totals for specific batch items unless the behavior contract or current implementation explicitly defines those triggers.
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    Respect the task's line budget and requested scenario count exactly. Prefer top-level test functions and inline setup over class-based suites or extra helper fixtures when the task asks for compact coverage.
    If the task sets only a maximum number of top-level tests, stay comfortably under that ceiling unless the documented contract explicitly requires more coverage.
    Leave at least one top-level test of headroom below a stated maximum unless the task explicitly requires the maximum count.
    Before you finalize, count top-level tests and total lines explicitly. If the suite is at or above any stated limit, merge or delete the lowest-value helper coverage until the file is back under budget.
    When the task gives a hard line cap, target clear headroom below it instead of landing on the boundary. Remove docstrings, comments, extra blank lines, and optional helper scaffolding before dropping any required scenario.
    If the task sets a fixture maximum, count fixtures before you finalize and inline one-off setup instead of adding a borderline extra fixture.
    If the task sets a fixture maximum, target one fewer than that limit by default unless the documented contract clearly requires the extra fixture.
    If the task only names high-level workflow scenarios, stay on the main service or batch API and do not add separate unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly requests them.
    In compact high-level workflow suites, do not spend top-level tests on validator units, scorer units, dataclass serialization, audit logger wrappers, or other helper-only coverage unless the task explicitly names those helpers.
    For compact scenario-driven suites, merge overlapping checks instead of creating helper-specific extra tests. Do not spend standalone tests on simple logging or audit helpers unless the contract makes them independently observable.
    If the task requires both a validation-failure scenario and a batch-processing scenario, use the direct intake or validation surface for the failure case unless the behavior contract explicitly requires a batch-level failure scenario.
    If the validation-failure scenario is a missing-required-field case, omit only the field under test and keep the rest of that payload valid for the same surface.
    If required fields are validated before score_request, score_risk, process_request, or batch handling, do not create a separate invalid-scoring test that first calls intake_request on an invalid object. Keep that failure case on intake_request or validate_request, and reserve scoring assertions for already-valid inputs.
    Do not assume empty strings, placeholder IDs, or domain keywords are invalid unless the behavior contract or implementation explicitly says so. For validation-failure coverage, prefer missing required fields or clearly wrong types over guessed business rules. If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict), an empty string or same-type placeholder still satisfies that validator, so use a non-string, non-dict, or similarly wrong-type value instead.
    Example: if validate_request(request) only checks isinstance(request.id, str) and isinstance(request.data, dict), ComplianceRequest(id="", data={{"field": "value"}}) still passes. Use a non-string id or a non-dict data value for the failure case instead.
    Apply the same rule to request_id, entity_id, document_id, and similar identifier fields: unless the contract explicitly says empty strings are invalid, request_id="" or another same-type placeholder can still pass, so prefer a wrong top-level type or a truly missing required field.
    Apply the same rule to dict payload fields such as data, details, metadata, request_data, or document_data: an empty dict is still a same-type placeholder and may pass when validation only checks dict type, so prefer None, a non-dict value, or omission only when the contract explicitly allows omission.
    If a workflow input still has the correct top-level type, do not expect ValueError just because one business value changed. Example: if submit_intake only validates that data.data is a dict, ComplianceData(id="1", data={{"key": "wrong_value"}}) is still valid input and should be asserted as a non-compliant result instead of being wrapped in pytest.raises(ValueError). Use a non-dict payload if you need a ValueError case.
    Do not write a validation-failure test as `assert not validate_request(...)` or a similar falsy expectation unless the contract explicitly documents False as the invalid outcome. When the failure mode is uncertain, use a contract-backed wrong-type or missing-field input and assert the documented raise, rejected state, or batch result instead.
    For process_request or other validation-gated workflow tests, choose an input that validate_request rejects before scoring runs. Do not use nested None values or same-type empty containers that can slip past validation and then fail later inside score_risk, calculate_risk_score, or similar scoring helpers with a different exception.
    If validation only checks an outer container type, do not assume a wrong nested value type makes the request invalid. Example: if validate_request(request) returns bool(request.id) and isinstance(request.data, dict), ComplianceRequest(id="1", data={{"check": "not_a_bool"}}, timestamp="2023-01-01T00:00:00Z", status="pending") still passes; use a non-dict data value or another explicitly invalid top-level field instead.
    If validation or scoring guards a nested field with isinstance(...) before using it, a wrong nested field type is usually ignored rather than raising. Example: if calculate_risk_score only adds risk_factor when isinstance(request_data["risk_factor"], (int, float)), then risk_factor="invalid" does not raise TypeError; use a wrong top-level type or missing required field for failure coverage instead.
    If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid instead of raising, assert that state on the same object you passed into the call.
    Keep the batch-processing scenario structurally valid unless the behavior contract explicitly says partially invalid batch items are expected.
    If the provided test targets list batch-capable functions, use one of those functions for the batch scenario instead of inventing batch behavior for unrelated helpers.
    If the public API exposes no dedicated batch helper, express the batch scenario by iterating over a short list of valid items one by one instead of passing a list into scalar-only validators or scorers.
    Example: if the module exposes only process_request(request) and no process_batch(...), write a short loop over two valid requests and assert the documented result of each process_request call instead of switching to logger, repository, scorer, or audit helpers.
    If the module exposes only scalar validation, scoring, or audit helpers, cover the required happy path, validation failure, and batch-style loop with 3 to 4 tests total. Do not add separate standalone tests for each helper once those scenarios are covered.
    If the module exposes only helper-level audit or logging functions, do not spend one of those limited tests on a standalone audit or log helper check. Fold any required audit call into the happy-path or batch-style scenario instead.
    Example: if the module exposes validate_request(request), score_request(request), and log_audit(request_id, action, result), write exactly three tests: one happy-path test that validates and scores a valid request and may assert audit file creation or required substring presence, one validation-failure test using an invalid document_type or wrong-type document_data, and one batch-style loop over two valid requests. Do not add standalone score_request, log_audit, or extra invalid-case tests.
    If a batch helper returns None or constructs its own domain objects from raw items, do not instantiate fresh objects after the batch call and assume they inherited internal mutations. Assert only directly observable outcomes, caller-owned object mutations, or behavior you explicitly patch in that test.
    Prefer the highest-level public service or top-level workflow functions for the requested scenarios. Do not import repository, logger, scorer, validator, or similar helper services directly unless the API contract makes them the primary surface under test.
    Never redeclare production dataclasses, business functions, CLI parsers, or other implementation code inside the pytest module. Import production symbols from the generated module and keep the test file as tests only.
    Do not turn copied implementation into `test_main`, `test_all_tests`, or similar meta-tests that invoke argparse, print output, or manually call other tests.
    Do not add standalone caplog or raw logging-output assertions unless the behavior contract explicitly makes log output observable. If audit behavior matters, prefer deterministic assertions on service state or audit records exposed by the service.
    Do not compare full audit or log file contents by exact string equality or trailing-newline-sensitive text unless the behavior contract explicitly defines that serialized format. Prefer stable assertions such as file creation, non-empty content, append growth, line count, or required substring presence.
    Do not assert an exact runtime numeric type such as float unless the contract or current implementation explicitly casts to that type. If the current implementation computes a numeric score with int-like arithmetic such as modulo or counts, assert the documented value, numeric non-negativity, or a broader numeric invariant instead.
    When an exact numeric score is required, derive it from only the branches exercised by the chosen input rather than summing unrelated branch outcomes.
    Example: if score_request adds 1 for document_type == "income" and 2 for document_type == "employment", a request with document_type="income" should assert 1, not 3.
    If a score formula combines weighted numeric fields, recompute the exact total from every exercised term using the current input values before asserting equality. Example: if score += request_data["risk_factor"] * 0.5 and score += (1 - request_data["compliance_history"]) * 0.5, then risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25.
    If you assert audit records, assert only actions exercised in that same scenario. Do not expect document-upload, status-change, or similar audit events unless the test performs that action directly.
    If a scenario performs intake, scoring, and one error path, count all three audit entries. Do not drop the scoring log from the expected audit total.
    If a scenario performs intake, scoring, and one error path, count all three audit entries. Do not drop the scoring log from the expected audit total.
    If a batch scenario includes invalid items, count audit records from both the inner failing operation and any outer batch failure handler. One invalid batch item can emit two failure-related audit entries, and those must be added to any success-path audit records from valid items before asserting an exact audit length.
    If process_batch or another batch helper internally performs intake and scoring for each valid item, count those inner success-path logs too before asserting any batch audit total. Example: a two-item valid batch can emit 5 audit logs, not 3, and a batch that fails on the second item can still already emit 2 logs, not 1, from the first valid item.
    In batch scenarios, prefer assertions on returned results, terminal batch markers, or monotonic audit growth over an exact audit length unless the current implementation or contract explicitly enumerates every emitted log entry. If you cannot enumerate every internal log deterministically, do not assert an exact batch audit total.
    Unless the current implementation or behavior contract explicitly enumerates every emitted batch log, do not write len(service.audit_logs) == N or a similar exact batch-audit assertion.
    If a previous pytest failure showed a batch audit mismatch such as assert 5 == 3 on len(service.audit_logs), delete that exact count and replace it with stable checks such as result counts, required actions, terminal batch markers, or monotonic audit growth.
    Never define a custom fixture named `request`; pytest reserves that name. Use inline setup or a specific fixture name such as `sample_request` instead.
    If you use the `pytest.` namespace anywhere in the file, add `import pytest` explicitly at the top of the module. Built-in fixtures alone do not make the pytest module name available.
    Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test creates the exact mock or patch target first.
    If you assert an exact numeric value, use trivially countable inputs and do so only when the behavior contract or implementation clearly defines the exact formula; otherwise prefer stable non-exact assertions.
    Do not hand-count prose strings, human-readable names, or email addresses to justify exact numeric assertions.
    If an exact numeric assertion depends on string length, modulo, counts, or collection size, never use prose sample text for that assertion.
    If an exact numeric assertion depends on string length, modulo, counts, or collection size, never use prose sample text, human-readable names, or email addresses for that assertion. Use repeated-character literals or similarly obvious inputs.
    If an exact numeric assertion depends on top-level dict size or collection size, compute it from the actual top-level container passed into scoring rather than from nested values or magnitudes. If calculate_risk_score(data) returns float(len(data)) * 1.5 and two requests pass dicts with the same two top-level keys, both scores are 3.0 even when nested amounts or names differ.
    If a scorer accepts a mixed semantic payload dict and the formula is not fully explicit, do not invent a guessed exact total such as 6.0 or a derived level such as medium by hand-counting keys and prose-like sample values. Example: for calculate_risk_score({{"id": "1", "data1": "value1", "data2": "value2"}}), do not assert 6.0 or level "medium" unless the formula explicitly says why; assert a contract-backed invariant such as non-negative score or relative ordering instead.
    If an exact numeric assertion depends on string length or character count, do not pair exact score equality with word-like sample strings such as data, valid_data, or data1. Replace them with repeated-character literals such as aaaa or a * 20, or switch the assertion to a non-exact invariant.
    If a required string field participates in a length- or modulo-based score, do not use an empty string to force score 0 in a non-error scenario. Use a non-empty repeated-character literal with the needed length instead; for len(details) % 10 == 0, use xxxxxxxxxx rather than "".
    If score = (len(name) + len(email)) / 10.0, do not assert against a hand-counted literal for {{"name": "Alice", "email": "alice@example.com"}}; either compute the expectation from the visible formula, use repeated-character inputs with obvious lengths, or switch to a non-exact invariant.
    If an exact numeric assertion depends on nested payload shape, compute it from the actual object passed into the scoring function rather than from an inner dict you assume the service extracted. Example: if request.data stores {{"id": "1", "data": {{"data_field": "example"}}, "timestamp": "..."}} and calculate_risk_score reads data.get("data_field", ""), the score is 0.0, not 7.0.
    Do not assert exact categorical score bands or labels at boundary values unless the contract explicitly defines those cutoffs. Use comfortably in-band inputs or non-boundary assertions for derived levels. Example: if score = amount * 0.1 and the level may change at 10, do not use amount=100 to assert an exact label; use 50 for a clear low case, 150 for a clear medium case, or assert only the numeric score.
    If derived labels depend on count-based scores and the thresholds are not explicit, do not use borderline counts such as 2 to assert an exact low or medium label. Use 1 for a clear low case, 3 for a clear medium case, or assert only the numeric score.
    Do not infer derived status transitions, escalation flags, or report counters from suggestive field names, keywords, or audit vocabulary alone. Assert those outcomes only when the behavior contract or current implementation explicitly defines the trigger.
    Do not hard-code exact response.status labels such as accepted, rejected, pending_review, or flagged, and do not hard-code exact risk-summary bucket totals for specific batch items unless the behavior contract or current implementation explicitly defines those triggers.
    When an API accepts a request, filter, or payload dict with documented required fields, either supply every required field or omit that optional dict entirely. Do not assume partial filter payloads are accepted unless the contract explicitly marks those keys optional.
    If a service stores the full raw request payload in a field such as request.data, do not assume that field was normalized to only an inner sub-dict. Example: if request_data = {{"id": "req1", "data": {{"field1": "value1"}}}} and intake_request stores ComplianceRequest.data = request_data, assert compliance_request.data == request_data or compliance_request.data["data"] == {{"field1": "value1"}} instead of asserting compliance_request.data == {{"field1": "value1"}}.
    If the API contract does not list a symbol or enum member, do not use it.
    If the previous suite already passed static validation and only failed at pytest runtime, keep the same public module surface and make the smallest behavioral correction needed. Do not replace valid imports with guessed APIs or change documented constructor signatures.
    If a pytest-only runtime failure shows that an earlier assertion overreached the current implementation or contract, rewrite that assertion to a contract-backed invariant instead of forcing a guessed business rule into the code.
    If the previous validation summary reports undefined local names or undefined fixtures, remove or rewrite every offending test unless you explicitly import or define those names in this rewritten file. In a compact workflow suite, delete helper-only tests before adding new fixtures, caplog assertions, or extra helper imports.
    If the previous validation summary reports helper surface usages, delete every import, fixture, helper variable, and top-level test that references those helper surfaces. Do not repair those helper-surface tests in place.
    Do not replace one guessed helper with another guessed helper during repair. If a helper-surface test was invalid for ComplianceScorer, ComplianceBatchProcessor, AuditLogger, or a similar invented name, delete that helper-oriented test and rebuild around the documented service facade and request or result models only.
    If flagged helper surfaces are listed below, treat those names as banned in the rewritten file unless the public API contract explicitly makes them the primary surface under test.
    Treat the current implementation artifact and API contract as fixed ground truth during repair. Do not invent replacement response classes, alternate validators, renamed helpers, or new return-wrapper types.
    Before you finalize, verify this checklist against your own output:
    - every imported production symbol exists in the API contract
    - every imported production symbol also appears in the listed test targets unless it is only used as a type container
    - every production class referenced in a fixture or test body is explicitly imported from the target module
    - when a public service or workflow facade exists, you limited imports to that facade and directly exchanged domain models instead of auxiliary validators, scorers, loggers, repositories, processors, or engines
    - every class instantiation uses only documented constructor arguments
    - if you used isinstance or another exact type assertion against a production class, you explicitly imported that class; otherwise you asserted on returned fields or behavior without naming an unimported type
    - if the API contract exposed typed request or result models, you instantiated them with the exact field names and full constructor arity from that contract instead of inventing generic placeholders
    - if the API contract listed defaulted constructor fields, you passed them explicitly in every constructor call instead of relying on omitted defaults
    - if the API contract listed a constructor like ComplianceRequest(id, user_id, data, timestamp, status), every constructor call in the suite includes all listed fields instead of omitting a trailing default such as status
    - if you had to pass explicit constructor fields such as timestamp, you used a self-contained literal or previously defined local rather than reading from the object being constructed
    - if the implementation summary or behavior contract did not explicitly define a formula or trigger, you avoided exact score totals and threshold-triggered boolean flags and used stable invariants instead
    - if the previous validation summary lists constructor arity mismatches, you removed guessed helper wiring and rebuilt the scenario around the smallest documented public API surface
    - every assertion matches behavior reachable from the provided implementation summary
    - every happy-path payload satisfies the listed behavior contract and validation rules
    - if the task sets a fixture maximum, you stayed at or under it and inlined one-off setup instead of adding a borderline extra fixture
    - if the task sets only a maximum number of top-level tests, you stayed comfortably under that ceiling unless the documented contract explicitly required more coverage
    - if the task sets only a maximum number of top-level tests, you left at least one top-level test of headroom below that maximum unless an exact count was explicitly required
    - before you finalized, you counted top-level tests and total lines and removed lowest-value helper coverage until the file sat safely under every stated cap
    - if the task requires both a validation-failure scenario and a batch scenario, the validation failure stays on the direct intake or validation surface unless the behavior contract explicitly requires a batch-level failure case
    - if the validation-failure scenario omits a required field, it omits only the field under test and keeps the rest of that payload valid for the same surface
    - if validation checks only an outer container type, you did not assume a wrong nested value type would fail that validator unless the contract explicitly said so
    - if validation or scoring guarded a nested field with isinstance before using it, you did not expect a wrong nested field type to raise unless the implementation actually performs arithmetic on that value
    - if the validation-failure path keeps the same caller-owned object in a non-success state such as pending or invalid, you asserted that state on the same object you passed into the call
    - every happy-path batch item satisfies the same required fields as the single-request happy path unless the behavior contract explicitly documents a different batch shape
    - if the listed test targets name batch-capable functions, the batch scenario uses one of those functions instead of inventing batch behavior for unrelated helpers
    - if the public API exposes no dedicated batch helper, the batch scenario iterates over individual items rather than passing a list into a scalar-only function
    - if the public API exposes no dedicated batch helper, you kept the batch scenario on the main request-processing surface instead of switching to logger, repository, scorer, or audit helpers
    - if a batch helper returns None or constructs its own domain objects internally, you did not create fresh objects after the batch call and assume they inherited internal mutations
    - if the task asks for a fixed number of scenarios or tests, you did not add extra cases beyond that request
    - you did not add standalone helper or logging tests that duplicate behavior already covered by the requested scenarios
    - in a compact high-level workflow suite, you did not spend top-level tests on validator units, scorer units, dataclass serialization, audit logger wrappers, or other helper-only coverage unless the task explicitly named them
    - if the previous suite already passed static validation, you preserved valid imports, constructor signatures, fixture payload shapes, and scenario structure unless the validation summary explicitly marked them invalid
    - if the validation summary reported undefined local names or undefined fixtures, you removed or rewrote those tests unless you explicitly imported or defined the missing names
    - if the validation summary reported helper surface usages, you deleted every import, fixture, helper variable, and top-level test that referenced those helper surfaces instead of preserving them
    - if flagged helper surfaces were listed below, none of those names reappear in imports, fixtures, helper variables, or tests unless the API contract explicitly makes them the primary surface under test
    - you did not define a custom fixture named `request`
    - every non-built-in fixture used by a test is defined in the same file
    - every test function argument is either a built-in fixture, a locally defined fixture, or a name introduced by the matching parametrization
    - if you used the `pytest.` namespace anywhere in the file, you explicitly added `import pytest` at the top of the module instead of relying on implicit availability
    - every helper or expected-value name referenced inside a test body is imported, defined in the file, or introduced by the matching parametrization
    - you did not add caplog or raw logging-text assertions unless the behavior contract explicitly makes emitted log output observable
    - if you asserted audit records, every asserted action is exercised in that same scenario rather than guessed from unrelated workflow steps
    - if a batch scenario included invalid items, you counted audit records from both the inner failing operation and any outer batch failure handler before asserting any exact audit total
    - if a batch helper internally performed more than one logged success step per valid item, you counted each of those inner success-path logs before any batch-level or failure logs when asserting audit totals
    - unless the current implementation or behavior contract explicitly enumerated every emitted batch log, you did not write len(service.audit_logs) == N or another exact batch-audit assertion
    - if a previous pytest failure showed a batch audit-length mismatch, you replaced that exact count with stable checks such as result counts, required actions, terminal batch markers, or monotonic audit growth
    - you did not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test creates the exact mock or patch target first
    - every exact numeric assertion is supported by an explicit contract or formula and uses trivially countable input; otherwise you used stable non-exact assertions
    - if you asserted an exact numeric score for branch-based logic, the expected value matches only the branches exercised by that specific input rather than a guessed sum of unrelated branches
    - if a score formula combined weighted numeric fields, you recomputed the exact total from every exercised term using the current input values before asserting equality
    - you did not infer derived status transitions, escalation flags, or report counters from suggestive field names, keywords, or audit vocabulary alone
    - every request, filter, or payload dict in the suite either supplies all documented required fields or omits that optional dict entirely
    - if required fields are validated before scoring, you kept invalid required-field coverage on intake_request or validate_request instead of first calling intake_request and then expecting score_request or score_risk to fail on the same invalid object
    - if an exact numeric assertion depended on nested payload shape, you computed it from the actual object passed into the scoring function instead of an assumed inner dict
    - if you asserted derived categorical levels or score bands, you used comfortably in-band inputs or non-boundary assertions unless the contract explicitly defined the thresholds
    - if you asserted derived categorical levels from count-based scores, you used clearly in-band counts such as 1 or 3 instead of a borderline count such as 2 unless the thresholds were explicit
    - if you asserted a stored request payload field such as `.data`, you matched the implementation's stored shape instead of guessing a normalized inner sub-dict
    - if an exact numeric assertion depends on string length, modulo, counts, or collection size, you used repeated-character or similarly obvious inputs rather than prose sample text
    - if an exact numeric assertion depends on top-level dict size or collection size, you computed it from the actual top-level container passed into scoring rather than from nested values, magnitudes, or the assumption that later batch items must produce different scores
    - if an exact numeric assertion depends on string length or character count, you replaced word-like sample strings with repeated-character literals or dropped the exact equality instead of keeping a guessed score against values such as data or data1
    - if a required string field participates in a length- or modulo-based score, you did not use an empty string to force zero in a non-error scenario; you used a non-empty repeated-character literal with the needed length or dropped the exact equality
    - you did not invent replacement API names, response-wrapper classes, alternate validators, or alternate constructor signatures during repair
    - if a pytest-only runtime failure exposed a guessed business-rule assertion, you rewrote it to a contract-backed invariant instead of forcing a new unstated rule into the implementation
    - if the previous test file was syntax-invalid or truncated, you rewrote the full pytest file from the top instead of appending a partial continuation
    - if the previous validation mentions truncation or completion diagnostics, you reduced non-essential comments, blank lines, optional fixtures, and helper scaffolding so the whole pytest file fits cleanly in one response
    - no test imports entrypoints listed under "Entry points to avoid in tests"
    - no test imports or instantiates CLI wrapper classes such as names ending in `CLI` or `Cli` unless CLI coverage is explicitly required and argv/input is fully controlled
    - no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test
    - the file is syntactically complete with no truncated fixture, string, or parametrization block"""

        if contract_first_mode:
            user_msg = f"""Project: {agent_input.project_name}
    Project goal: {agent_input.project_goal}
    Implementation summary: {code_summary}
    Implementation code:
    {implementation_code}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}
    {code_exact_test_contract}
    {code_test_targets}
    {task_public_contract_anchor_block}
    {deterministic_surface_scaffold_block}
    Behavior contract:
    {code_behavior_contract}

Existing tests context:
    {existing_tests_context}

{repair_instruction}{exact_rebuild_surface_block}
If the previous validation summary lists constructor arity mismatches, remove or rewrite those constructor calls instead of preserving guessed helper wiring from the old suite.

Previous validation summary:
    {repair_validation_summary}{repair_helper_surface_block}{repair_focus_block}

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.

Module name: {module_name}
Module file: {module_filename}
{task_constraints_block}

{self._contract_first_user_guidance(module_name, module_filename)}"""

        system_prompt, user_msg = self._placeholder_safe_prompt_pair(
            system_prompt=CONTRACT_FIRST_SYSTEM_PROMPT if contract_first_mode else SYSTEM_PROMPT,
            user_message=user_msg,
            code_exact_test_contract=code_exact_test_contract,
            preserved_sections=[
                code_summary,
                implementation_code,
                code_outline,
                code_public_api,
                code_exact_test_contract,
                code_test_targets,
                task_constraints_block,
                task_public_contract_anchor_block,
                deterministic_surface_scaffold_block,
                code_behavior_contract,
                existing_tests_context,
                repair_validation_summary,
                repair_helper_surface_block,
                repair_focus_block,
                exact_rebuild_surface_block,
            ],
        )
        return self.chat(system_prompt, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        implementation_code = context.get("code", "")
        existing_tests = context.get("existing_tests", "")
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        code_summary = context.get("code_summary", "")
        code_outline = context.get("code_outline", "")
        code_public_api = context.get("code_public_api", "")
        code_exact_test_contract = context.get("code_exact_test_contract", "")
        code_test_targets = context.get("code_test_targets", "")
        code_behavior_contract = context.get("code_behavior_contract", "")
        task_public_contract_anchor = context.get("task_public_contract_anchor", "")
        repair_validation_summary = context.get("repair_validation_summary", "")
        budget_decomposition_brief = context.get("budget_decomposition_brief", "")
        budget_decomposition_block = (
            f"Budget decomposition brief:\n    {budget_decomposition_brief}\n\n"
            if isinstance(budget_decomposition_brief, str) and budget_decomposition_brief.strip()
            else ""
        )
        repair_helper_surface_block = self._repair_helper_surface_block(context)
        repair_focus_block = self._repair_focus_block(repair_validation_summary)
        existing_tests_context, repair_instruction = self._existing_tests_context_and_instruction(
            existing_tests=existing_tests,
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
        )
        exact_rebuild_surface_block = self._exact_rebuild_surface_block(
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
            task_public_contract_anchor=task_public_contract_anchor,
        )
        deterministic_surface_scaffold_block = self._deterministic_surface_scaffold_block(
            module_name=module_name,
            task_description=task_description,
            code_exact_test_contract=code_exact_test_contract,
            code_test_targets=code_test_targets,
            task_public_contract_anchor=task_public_contract_anchor,
        )
        task_public_contract_anchor_block = self._task_public_contract_anchor_block(
            task_public_contract_anchor
        )
        contract_first_mode = bool(task_public_contract_anchor_block)
        task_constraints_block = self._compact_task_constraints_block(task_description)
        user_msg = f"""Implementation summary: {code_summary}
    Implementation code:
    {implementation_code}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}
    {code_exact_test_contract}
    {code_test_targets}
    {task_public_contract_anchor_block}
    {deterministic_surface_scaffold_block}
    Behavior contract:
    {code_behavior_contract}

Existing tests context:
    {existing_tests_context}

{repair_instruction}{exact_rebuild_surface_block}
If the previous validation summary lists constructor arity mismatches, remove or rewrite those constructor calls instead of preserving guessed helper wiring from the old suite.

Previous validation summary:
    {repair_validation_summary}{repair_helper_surface_block}{repair_focus_block}

{budget_decomposition_block}If a budget decomposition brief is provided, treat it as the compact rewrite plan for this suite. Keep the required scenarios it names, merge or delete the optional coverage it says to cut, and follow its write order so the rewritten file stays under budget.

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.

Module name: {module_name}
Module file: {module_filename}
Task: {task_description}

Write a complete raw pytest file.
Import from `{module_name}` and test the actual public functions and classes from that module.
    Import every called production function explicitly from `{module_name}`.
    Import only top-level functions and classes from `{module_name}`.
    When an Exact test contract block is provided above, treat it as the highest-priority import, method, and constructor surface. It overrides every generic example below.
    When a Task-level public contract anchor block is provided above, treat it as higher priority than generic examples and break ties in favor of the anchored facade, methods, and constructor fields.
    If that anchor keeps batch behavior on the same facade through repeated single-request calls, do not invent renamed batch helpers such as process_batch(...), batch_process(...), or batch_intake_requests(...).
    Concrete class, function, and field names that appear later in generic examples are placeholders only. Never copy example names such as ComplianceRequest, ComplianceService, validate_request, process_request, submit_intake, or batch_submit_intakes unless the provided contract, outline, behavior contract, or test targets list that exact name. Rewrite each generic example to the real module surface before you write the suite.
    Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols. If the contract lists BatchProcessor or RiskScorer, do not invent ComplianceBatchProcessor, ComplianceScorer, ComplianceIntake, AuditLogger, or similar aliases.
    If the contract lists submit_intake(...) and batch_submit_intakes(...), do not shorten them to submit(...) or submit_batch(...), even when calling ComplianceIntakeService() inline.
    Do not import `main`, CLI/demo entrypoints, or any symbol listed under the provided Entry points to avoid in tests guidance.
    Do not import or instantiate CLI wrapper classes such as names ending in `CLI` or `Cli` unless the task explicitly requires CLI testing and you fully control argv or input.
    Import every production class you instantiate or reference in a fixture or test body.
    Do not hand-wire validator, scorer, logger, batch-processor, dataclass, or similar helper objects into a service fixture unless the public API contract explicitly requires those constructor arguments.
    When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models instead of auxiliary validators, scorers, loggers, repositories, processors, or engines.
    If you use isinstance or another exact type assertion against a returned production class, import that class explicitly; otherwise assert on returned fields or behavior without naming the unimported type.
    When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity from that contract. Do not invent generic placeholders such as id, data, timestamp, or status when the contract lists different fields.
    When the API contract lists constructor fields for a typed request or result model, pass every listed field explicitly in test instantiations, including fields that have defaults, unless the contract explicitly shows omission as valid.
    Do not rely on Python dataclass defaults just because omission would run. If the public API says ComplianceRequest(id, user_id, data, timestamp, status), every constructor call in the suite must pass all five named arguments; do not omit status and rely on the dataclass default.
    Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger. Otherwise assert stable invariants such as success, request identity, audit growth, and non-negative or relative scores.
    Do not hard-code exact response.status labels such as accepted, rejected, pending_review, or flagged, and do not hard-code exact risk-summary bucket totals for specific batch items unless the behavior contract or current implementation explicitly defines those triggers.
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    Respect the task's line budget and requested scenario count exactly. Prefer top-level test functions and inline setup over class-based suites or extra helper fixtures when the task asks for compact coverage.
    If the task sets only a maximum number of top-level tests, stay comfortably under that ceiling unless the documented contract explicitly requires more coverage.
    Leave at least one top-level test of headroom below a stated maximum unless the task explicitly requires the maximum count.
    Before you finalize, count top-level tests and total lines explicitly. If the suite is at or above any stated limit, merge or delete the lowest-value helper coverage until the file is back under budget.
    When the task gives a hard line cap, target clear headroom below it instead of landing on the boundary. Remove docstrings, comments, extra blank lines, and optional helper scaffolding before dropping any required scenario.
    If the task sets a fixture maximum, count fixtures before you finalize and inline one-off setup instead of adding a borderline extra fixture.
    If the task sets a fixture maximum, target one fewer than that limit by default unless the documented contract clearly requires the extra fixture.
    If the task only names high-level workflow scenarios, stay on the main service or batch API and do not add separate unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly requests them.
    In compact high-level workflow suites, do not spend top-level tests on validator units, scorer units, dataclass serialization, audit logger wrappers, or other helper-only coverage unless the task explicitly names those helpers.
    For compact scenario-driven suites, merge overlapping checks instead of creating helper-specific extra tests. Do not spend standalone tests on simple logging or audit helpers unless the contract makes them independently observable.
    If the task requires both a validation-failure scenario and a batch-processing scenario, use the direct intake or validation surface for the failure case unless the behavior contract explicitly requires a batch-level failure scenario.
    If the validation-failure scenario is a missing-required-field case, omit only the field under test and keep the rest of that payload valid for the same surface.
    If required fields are validated before score_request, score_risk, process_request, or batch handling, do not create a separate invalid-scoring test that first calls intake_request on an invalid object. Keep that failure case on intake_request or validate_request, and reserve scoring assertions for already-valid inputs.
    Do not assume empty strings, placeholder IDs, or domain keywords are invalid unless the behavior contract or implementation explicitly says so. For validation-failure coverage, prefer missing required fields or clearly wrong types over guessed business rules. If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict), an empty string or same-type placeholder still satisfies that validator, so use a non-string, non-dict, or similarly wrong-type value instead.
    Example: if validate_request(request) only checks isinstance(request.id, str) and isinstance(request.data, dict), ComplianceRequest(id="", data={{"field": "value"}}) still passes. Use a non-string id or a non-dict data value for the failure case instead.
    Apply the same rule to request_id, entity_id, document_id, and similar identifier fields: unless the contract explicitly says empty strings are invalid, request_id="" or another same-type placeholder can still pass, so prefer a wrong top-level type or a truly missing required field.
    Apply the same rule to dict payload fields such as data, details, metadata, request_data, or document_data: an empty dict is still a same-type placeholder and may pass when validation only checks dict type, so prefer None, a non-dict value, or omission only when the contract explicitly allows omission.
    If a workflow input still has the correct top-level type, do not expect ValueError just because one business value changed. Example: if submit_intake only validates that data.data is a dict, ComplianceData(id="1", data={{"key": "wrong_value"}}) is still valid input and should be asserted as a non-compliant result instead of being wrapped in pytest.raises(ValueError). Use a non-dict payload if you need a ValueError case.
    Do not write a validation-failure test as `assert not validate_request(...)` or a similar falsy expectation unless the contract explicitly documents False as the invalid outcome. When the failure mode is uncertain, use a contract-backed wrong-type or missing-field input and assert the documented raise, rejected state, or batch result instead.
    For process_request or other validation-gated workflow tests, choose an input that validate_request rejects before scoring runs. Do not use nested None values or same-type empty containers that can slip past validation and then fail later inside score_risk, calculate_risk_score, or similar scoring helpers with a different exception.
    If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid instead of raising, assert that state on the same object you passed into the call.
    Keep the batch-processing scenario structurally valid unless the behavior contract explicitly says partially invalid batch items are expected.
    If the provided test targets list batch-capable functions, use one of those functions for the batch scenario instead of inventing batch behavior for unrelated helpers.
    If the public API exposes no dedicated batch helper, express the batch scenario by iterating over a short list of valid items one by one instead of passing a list into scalar-only validators or scorers.
    Example: if the module exposes only process_request(request) and no process_batch(...), write a short loop over two valid requests and assert the documented result of each process_request call instead of switching to logger, repository, scorer, or audit helpers.
    If a batch helper returns None or constructs its own domain objects from raw items, do not instantiate fresh objects after the batch call and assume they inherited internal mutations. Assert only directly observable outcomes, caller-owned object mutations, or behavior you explicitly patch in that test.
    Prefer the highest-level public service or top-level workflow functions for the requested scenarios. Do not import repository, logger, scorer, validator, or similar helper services directly unless the API contract makes them the primary surface under test.
    Do not add standalone caplog or raw logging-output assertions unless the behavior contract explicitly makes log output observable. If audit behavior matters, prefer deterministic assertions on service state or audit records exposed by the service.
    If you assert audit records, assert only actions exercised in that same scenario. Do not expect document-upload, status-change, or similar audit events unless the test performs that action directly.
    If a batch scenario includes invalid items, count audit records from both the inner failing operation and any outer batch failure handler. One invalid batch item can emit two failure-related audit entries, and those must be added to any success-path audit records from valid items before asserting an exact audit length.
    If process_batch or another batch helper internally performs intake and scoring for each valid item, count those inner success-path logs too before asserting any batch audit total. Example: a two-item valid batch can emit 5 audit logs, not 3, and a batch that fails on the second item can still already emit 2 logs, not 1, from the first valid item.
    In batch scenarios, prefer assertions on returned results, terminal batch markers, or monotonic audit growth over an exact audit length unless the current implementation or contract explicitly enumerates every emitted log entry. If you cannot enumerate every internal log deterministically, do not assert an exact batch audit total.
    Unless the current implementation or behavior contract explicitly enumerates every emitted batch log, do not write len(service.audit_logs) == N or a similar exact batch-audit assertion.
    If a previous pytest failure showed a batch audit mismatch such as assert 5 == 3 on len(service.audit_logs), delete that exact count and replace it with stable checks such as result counts, required actions, terminal batch markers, or monotonic audit growth.
    Never define a custom fixture named `request`; pytest reserves that name. Use inline setup or a specific fixture name such as `sample_request` instead.
    If you use the `pytest.` namespace anywhere in the file, add `import pytest` explicitly at the top of the module. Built-in fixtures alone do not make the pytest module name available.
    Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test creates the exact mock or patch target first.
    If you assert an exact numeric value, use trivially countable inputs and do so only when the behavior contract or implementation clearly defines the exact formula; otherwise prefer stable non-exact assertions.
    Do not hand-count prose strings, human-readable names, or email addresses to justify exact numeric assertions.
    If an exact numeric assertion depends on string length, modulo, counts, or collection size, never use prose sample text for that assertion.
    If an exact numeric assertion depends on string length, modulo, counts, or collection size, never use prose sample text, human-readable names, or email addresses for that assertion. Use repeated-character literals or similarly obvious inputs.
    If an exact numeric assertion depends on top-level dict size or collection size, compute it from the actual top-level container passed into scoring rather than from nested values or magnitudes. If calculate_risk_score(data) returns float(len(data)) * 1.5 and two requests pass dicts with the same two top-level keys, both scores are 3.0 even when nested amounts or names differ.
    If a scorer accepts a mixed semantic payload dict and the formula is not fully explicit, do not invent a guessed exact total such as 6.0 or a derived level such as medium by hand-counting keys and prose-like sample values. Example: for calculate_risk_score({{"id": "1", "data1": "value1", "data2": "value2"}}), do not assert 6.0 or level "medium" unless the formula explicitly says why; assert a contract-backed invariant such as non-negative score or relative ordering instead.
    If an exact numeric assertion depends on string length or character count, do not pair exact score equality with word-like sample strings such as data, valid_data, or data1. Replace them with repeated-character literals such as aaaa or a * 20, or switch the assertion to a non-exact invariant.
    If a required string field participates in a length- or modulo-based score, do not use an empty string to force score 0 in a non-error scenario. Use a non-empty repeated-character literal with the needed length instead; for len(details) % 10 == 0, use xxxxxxxxxx rather than "".
    If score = (len(name) + len(email)) / 10.0, do not assert against a hand-counted literal for {{"name": "Alice", "email": "alice@example.com"}}; either compute the expectation from the visible formula, use repeated-character inputs with obvious lengths, or switch to a non-exact invariant.
    If a score formula combines weighted numeric fields, recompute the exact total from every exercised term using the current input values before asserting equality. Example: if score += request_data["risk_factor"] * 0.5 and score += (1 - request_data["compliance_history"]) * 0.5, then risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25.
    Do not assert exact categorical score bands or labels at boundary values unless the contract explicitly defines those cutoffs. Use comfortably in-band inputs or non-boundary assertions for derived levels. Example: if score = amount * 0.1 and the level may change at 10, do not use amount=100 to assert an exact label; use 50 for a clear low case, 150 for a clear medium case, or assert only the numeric score.
    If derived labels depend on count-based scores and the thresholds are not explicit, do not use borderline counts such as 2 to assert an exact low or medium label. Use 1 for a clear low case, 3 for a clear medium case, or assert only the numeric score.
    Do not infer derived status transitions, escalation flags, or report counters from suggestive field names, keywords, or audit vocabulary alone. Assert those outcomes only when the behavior contract or current implementation explicitly defines the trigger.
    Do not hard-code exact response.status labels such as accepted, rejected, pending_review, or flagged, and do not hard-code exact risk-summary bucket totals for specific batch items unless the behavior contract or current implementation explicitly defines those triggers.
    When an API accepts a request, filter, or payload dict with documented required fields, either supply every required field or omit that optional dict entirely. Do not assume partial filter payloads are accepted unless the contract explicitly marks those keys optional.
    If validation or scoring guards a nested field with isinstance(...) before using it, a wrong nested field type is usually ignored rather than raising. Example: if calculate_risk_score only adds risk_factor when isinstance(request_data["risk_factor"], (int, float)), then risk_factor="invalid" does not raise TypeError; use a wrong top-level type or missing required field for failure coverage instead.
    If a service stores the full raw request payload in a field such as request.data, do not assume that field was normalized to only an inner sub-dict. Example: if request_data = {{"id": "req1", "data": {{"field1": "value1"}}}} and intake_request stores ComplianceRequest.data = request_data, assert compliance_request.data == request_data or compliance_request.data["data"] == {{"field1": "value1"}} instead of asserting compliance_request.data == {{"field1": "value1"}}.
    If the API contract does not list a symbol or enum member, do not use it.
    If the previous suite already passed static validation and only failed at pytest runtime, keep the same public module surface and make the smallest behavioral correction needed. Do not replace valid imports with guessed APIs or change documented constructor signatures.
    If a pytest-only runtime failure shows that an earlier assertion overreached the current implementation or contract, rewrite that assertion to a contract-backed invariant instead of forcing a guessed business rule into the code.
    If the previous validation summary reports undefined local names or undefined fixtures, remove or rewrite every offending test unless you explicitly import or define those names in this rewritten file. In a compact workflow suite, delete helper-only tests before adding new fixtures, caplog assertions, or extra helper imports.
    If the previous validation summary reports helper surface usages, delete every import, fixture, helper variable, and top-level test that references those helper surfaces. Do not repair those helper-surface tests in place.
    Do not replace one guessed helper with another guessed helper during repair. If a helper-surface test was invalid for ComplianceScorer, ComplianceBatchProcessor, AuditLogger, or a similar invented name, delete that helper-oriented test and rebuild around the documented service facade and request or result models only.
    If flagged helper surfaces are listed below, treat those names as banned in the rewritten file unless the public API contract explicitly makes them the primary surface under test.
    Treat the current implementation artifact and API contract as fixed ground truth during repair. Do not invent replacement response classes, alternate validators, renamed helpers, or new return-wrapper types.
    Before you finalize, verify this checklist against your own output:
    - every imported production symbol exists in the API contract
    - every imported production symbol also appears in the listed test targets unless it is only used as a type container
    - every production class referenced in a fixture or test body is explicitly imported from the target module
    - when a public service or workflow facade exists, you limited imports to that facade and directly exchanged domain models instead of auxiliary validators, scorers, loggers, repositories, processors, or engines
    - every class instantiation uses only documented constructor arguments
    - if you used isinstance or another exact type assertion against a production class, you explicitly imported that class; otherwise you asserted on returned fields or behavior without naming an unimported type
    - if the API contract exposed typed request or result models, you instantiated them with the exact field names and full constructor arity from that contract instead of inventing generic placeholders
    - if the API contract listed defaulted constructor fields, you passed them explicitly in every constructor call instead of relying on omitted defaults
    - if the API contract listed a constructor like ComplianceRequest(id, user_id, data, timestamp, status), every constructor call in the suite includes all listed fields instead of omitting a trailing default such as status
    - if the implementation summary or behavior contract did not explicitly define a formula or trigger, you avoided exact score totals and threshold-triggered boolean flags and used stable invariants instead
    - if the previous validation summary lists constructor arity mismatches, you removed guessed helper wiring and rebuilt the scenario around the smallest documented public API surface
    - every assertion matches behavior reachable from the provided implementation summary
    - every happy-path payload satisfies the listed behavior contract and validation rules
    - if the task sets only a maximum number of top-level tests, you stayed comfortably under that ceiling unless the documented contract explicitly required more coverage
    - if the task sets only a maximum number of top-level tests, you left at least one top-level test of headroom below that maximum unless an exact count was explicitly required
    - before you finalized, you counted top-level tests and total lines and removed lowest-value helper coverage until the file sat safely under every stated cap
    - if the task requires both a validation-failure scenario and a batch scenario, the validation failure stays on the direct intake or validation surface unless the behavior contract explicitly requires a batch-level failure case
    - if the validation-failure scenario omits a required field, it omits only the field under test and keeps the rest of that payload valid for the same surface
    - if validation or scoring guarded a nested field with isinstance before using it, you did not expect a wrong nested field type to raise unless the implementation actually performs arithmetic on that value
    - if the validation-failure path keeps the same caller-owned object in a non-success state such as pending or invalid, you asserted that state on the same object you passed into the call
    - every happy-path batch item satisfies the same required fields as the single-request happy path unless the behavior contract explicitly documents a different batch shape
    - if the listed test targets name batch-capable functions, the batch scenario uses one of those functions instead of inventing batch behavior for unrelated helpers
    - if the public API exposes no dedicated batch helper, the batch scenario iterates over individual items rather than passing a list into a scalar-only function
    - if the public API exposes no dedicated batch helper, you kept the batch scenario on the main request-processing surface instead of switching to logger, repository, scorer, or audit helpers
    - if a batch helper returns None or constructs its own domain objects internally, you did not create fresh objects after the batch call and assume they inherited internal mutations
    - if the task asks for a fixed number of scenarios or tests, you did not add extra cases beyond that request
    - you did not add standalone helper or logging tests that duplicate behavior already covered by the requested scenarios
    - in a compact high-level workflow suite, you did not spend top-level tests on validator units, scorer units, dataclass serialization, audit logger wrappers, or other helper-only coverage unless the task explicitly named them
    - if the previous suite already passed static validation, you preserved valid imports, constructor signatures, fixture payload shapes, and scenario structure unless the validation summary explicitly marked them invalid
    - if the validation summary reported undefined local names or undefined fixtures, you removed or rewrote those tests unless you explicitly imported or defined the missing names
    - if the validation summary reported helper surface usages, you deleted every import, fixture, helper variable, and top-level test that referenced those helper surfaces instead of preserving them
    - if flagged helper surfaces were listed below, none of those names reappear in imports, fixtures, helper variables, or tests unless the API contract explicitly makes them the primary surface under test
    - you did not define a custom fixture named `request`
    - every non-built-in fixture used by a test is defined in the same file
    - every test function argument is either a built-in fixture, a locally defined fixture, or a name introduced by the matching parametrization
    - if you used the `pytest.` namespace anywhere in the file, you explicitly added `import pytest` at the top of the module instead of relying on implicit availability
    - every helper or expected-value name referenced inside a test body is imported, defined in the file, or introduced by the matching parametrization
    - you did not add caplog or raw logging-text assertions unless the behavior contract explicitly makes emitted log output observable
    - if you asserted audit records, every asserted action is exercised in that same scenario rather than guessed from unrelated workflow steps
    - if a batch scenario included invalid items, you counted audit records from both the inner failing operation and any outer batch failure handler before asserting any exact audit total
    - if a batch helper internally performed more than one logged success step per valid item, you counted each of those inner success-path logs before any batch-level or failure logs when asserting audit totals
    - unless the current implementation or behavior contract explicitly enumerated every emitted batch log, you did not write len(service.audit_logs) == N or another exact batch-audit assertion
    - if a previous pytest failure showed a batch audit-length mismatch, you replaced that exact count with stable checks such as result counts, required actions, terminal batch markers, or monotonic audit growth
    - you did not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test creates the exact mock or patch target first
    - every exact numeric assertion is supported by an explicit contract or formula and uses trivially countable input; otherwise you used stable non-exact assertions
    - if you asserted an exact numeric score for branch-based logic, the expected value matches only the branches exercised by that specific input rather than a guessed sum of unrelated branches
    - if a score formula combined weighted numeric fields, you recomputed the exact total from every exercised term using the current input values before asserting equality
    - you did not infer derived status transitions, escalation flags, or report counters from suggestive field names, keywords, or audit vocabulary alone
    - every request, filter, or payload dict in the suite either supplies all documented required fields or omits that optional dict entirely
    - if required fields are validated before scoring, you kept invalid required-field coverage on intake_request or validate_request instead of first calling intake_request and then expecting score_request or score_risk to fail on the same invalid object
    - if an exact numeric assertion depends on string length, modulo, counts, or collection size, you used repeated-character or similarly obvious inputs rather than prose sample text
    - if an exact numeric assertion depends on top-level dict size or collection size, you computed it from the actual top-level container passed into scoring rather than from nested values, magnitudes, or the assumption that later batch items must produce different scores
    - if an exact numeric assertion depends on string length or character count, you replaced word-like sample strings with repeated-character literals or dropped the exact equality instead of keeping a guessed score against values such as data or data1
    - if a required string field participates in a length- or modulo-based score, you did not use an empty string to force zero in a non-error scenario; you used a non-empty repeated-character literal with the needed length or dropped the exact equality
    - you did not invent replacement API names, response-wrapper classes, alternate validators, or alternate constructor signatures during repair
    - if a pytest-only runtime failure exposed a guessed business-rule assertion, you rewrote it to a contract-backed invariant instead of forcing a new unstated rule into the implementation
    - if the previous test file was syntax-invalid or truncated, you rewrote the full pytest file from the top instead of appending a partial continuation
    - if the previous validation mentions truncation or completion diagnostics, you reduced non-essential comments, blank lines, optional fixtures, and helper scaffolding so the whole pytest file fits cleanly in one response
    - no test imports entrypoints listed under "Entry points to avoid in tests"
    - no test imports or instantiates CLI wrapper classes such as names ending in `CLI` or `Cli` unless CLI coverage is explicitly required and argv/input is fully controlled
    - no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test
    - the file is syntactically complete with no truncated fixture, string, or parametrization block"""

        if contract_first_mode:
            user_msg = f"""Implementation summary: {code_summary}
    Implementation code:
    {implementation_code}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}
    {code_exact_test_contract}
    {code_test_targets}
    {task_public_contract_anchor_block}
    {deterministic_surface_scaffold_block}
    Behavior contract:
    {code_behavior_contract}

Existing tests context:
    {existing_tests_context}

{repair_instruction}{exact_rebuild_surface_block}
If the previous validation summary lists constructor arity mismatches, remove or rewrite those constructor calls instead of preserving guessed helper wiring from the old suite.

Previous validation summary:
    {repair_validation_summary}{repair_helper_surface_block}{repair_focus_block}

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.

Module name: {module_name}
Module file: {module_filename}
{task_constraints_block}

{self._contract_first_user_guidance(module_name, module_filename)}"""

        system_prompt, user_msg = self._placeholder_safe_prompt_pair(
            system_prompt=CONTRACT_FIRST_SYSTEM_PROMPT if contract_first_mode else SYSTEM_PROMPT,
            user_message=user_msg,
            code_exact_test_contract=code_exact_test_contract,
            preserved_sections=[
                code_summary,
                implementation_code,
                code_outline,
                code_public_api,
                code_exact_test_contract,
                code_test_targets,
                task_constraints_block,
                deterministic_surface_scaffold_block,
                code_behavior_contract,
                existing_tests_context,
                repair_validation_summary,
                repair_helper_surface_block,
                repair_focus_block,
                exact_rebuild_surface_block,
            ],
        )
        return self.chat(system_prompt, user_msg)
