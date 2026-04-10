import ast
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
Before finalizing, verify that every non-local name used anywhere in the suite is either imported from the target module, imported from the standard library or pytest, or defined in the file. If the implementation defines a production collaborator such as AuditLogger or RiskScorer and the suite uses it, import it explicitly at the top of the file instead of leaving it as an undefined local.
If behavior is exposed as a class method, instantiate the class and call the method on the instance instead of importing the method name as a top-level function.
Never use `assert True`, `assert False`, or placeholder comments such as `Assuming ...` to stand in for a real expectation. Every retained test must assert a concrete contract-backed outcome.
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
Do not hard-code exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests unless the behavior contract or current implementation explicitly defines those triggers.
Do not assume internal action or review dictionaries such as review_actions are keyed by request_id, vendor_id, or another request-identity field unless the contract explicitly says so. If stored values expose their own action_id or record_id, assert collection size or inspect stored values instead of membership by request identity.
When an API accepts a request, filter, or payload dict with documented required fields, either supply every required field or omit that optional dict entirely. Do not assume partial filter payloads are accepted unless the contract explicitly marks those keys optional.
If a service stores the full raw request payload in a field such as request.data, do not assume that field was normalized to only an inner sub-dict. Example: if request_data = {"id": "req1", "data": {"field1": "value1"}} and intake_request stores ComplianceRequest.data = request_data, assert compliance_request.data == request_data or compliance_request.data["data"] == {"field1": "value1"} instead of asserting compliance_request.data == {"field1": "value1"}.
When a constructor or callable signature is listed in the API contract, use exactly that signature in every test.
When the API contract lists constructor fields for a typed request or result model, pass every listed field explicitly in test instantiations, including fields that have defaults, unless the contract explicitly shows omission as valid.
Do not rely on Python dataclass defaults just because omission would run. If the contract lists defaulted fields such as timestamp or status, pass them explicitly in every constructor call in the suite.
Example: if the contract lists ComplianceRequest(id, data, timestamp, status), write ComplianceRequest(id="1", data={"name": "John Doe", "amount": 1000}, timestamp=1.0, status="pending") instead of omitting timestamp and status.
Mirror the listed constructor exactly in every test call. If the public API says ComplianceRequest(id, user_id, data, timestamp, status), every constructor call in the suite must pass all five named arguments; do not omit status and rely on the dataclass default.
When you pass an explicit constructor field such as timestamp, use a self-contained literal or a local value defined before the constructor call. Do not read attributes from the object you are still constructing or any other undefined local. Example: define fixed_time = datetime(2023, 1, 1, 0, 0, 0) and pass timestamp=fixed_time instead of writing timestamp=request.timestamp inside request = ComplianceRequest(...).
Do not instantiate helper validators, scorers, loggers, dataclasses, or batch processors merely to wire a higher-level service fixture unless the public API contract explicitly requires that direct setup.
Record-shaped value models such as AuditLog, RiskScore, ResultRecord, or similar typed data holders are not service collaborators unless the public API contract explicitly says so. Do not instantiate them merely to satisfy service setup, and do not replace an undefined helper alias with a similarly named record type just because it imports cleanly.
When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models rather than auxiliary validators, scorers, loggers, repositories, processors, or engines.
If you use isinstance or another exact type assertion against a returned production class, import that class explicitly; otherwise assert on returned fields or behavior without naming the unimported type.
When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity from that contract. Do not invent generic placeholders such as id, data, timestamp, or status when the contract lists different fields.
Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger. Otherwise assert stable invariants such as success, request identity, audit growth, and non-negative or relative scores.
Do not hard-code exact response.status labels such as accepted, rejected, pending_review, or flagged, and do not hard-code exact risk-summary bucket totals for specific batch items, unless the behavior contract or current implementation explicitly defines those triggers.
Do not hard-code exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests unless the behavior contract or current implementation explicitly defines those triggers.
When repairing a previously generated suite that already passed static validation, preserve the existing imported symbols, constructor shapes, fixture payload structure, and scenario skeleton unless the validation summary explicitly identifies one of those pieces as invalid.
If the previous validation summary reports contract overreach signals, that prior suite guessed behavior beyond the documented contract. Discard brittle exact batch-count or status-threshold assertions and rebuild only the minimum contract-backed scenarios instead of patching the old file in place.
If the previous validation summary reports tests without assertion-like checks, that prior suite skeleton is invalid. Discard the hollow test bodies and rewrite only the minimum contract-backed scenarios with explicit assertions instead of patching the old file in place.
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
If the implementation validates a required document or evidence list before scoring, every happy-path or valid batch item must include the full required set named by that validator. Do not use a single placeholder document like ["ID"] when the implementation names additional required evidence items.
If the implementation validates required payload keys before processing, every happy-path or valid batch item must include that full required key set. Do not omit fields like claim_type, amount, timestamp, or similar required payload keys from supposedly valid scenarios.
If the implementation shows a named required_evidence or required_documents list, copy that full list verbatim into every valid happy-path or valid batch payload instead of shrinking it to a representative subset.
Do not require a strictly positive score, non-empty risk list, or similar nonzero scoring side effect from a generic happy-path input unless the chosen payload actually exercises a documented risk factor. For a plain valid request, prefer asserting that scoring completed, a score record exists, or the score is non-negative.
When the task names only high-level workflow scenarios, keep the suite on the main service or batch surface and do not add direct unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly asks for them.
In compact high-level workflow suites, do not spend top-level tests on validator units, scorer units, dataclass serialization, audit logger wrappers, or other helper-only coverage unless the task explicitly names those helpers.
When the task requires both a validation-failure scenario and a batch-processing scenario, keep the validation-failure coverage on the direct intake or validation surface unless the behavior contract explicitly requires batch-level failure coverage.
When the suite already contains a dedicated validation-failure test, do not reuse that invalid payload inside test_batch_processing or any other supposedly valid batch scenario. Keep every batch item fully valid unless the behavior contract explicitly documents partial batch failure handling.
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
Before finalizing, verify that every non-local name used anywhere in the suite is either imported from the target module, imported from the standard library or pytest, or defined in the file. If the implementation defines a production collaborator such as AuditLogger or RiskScorer and the suite uses it, import it explicitly at the top of the file instead of leaving it as an undefined local.
If batch behavior is documented as repeated single-request calls on the main facade, write the batch scenario that way instead of inventing renamed batch helpers.
Never use `assert True`, `assert False`, or placeholder comments such as `Assuming ...` to stand in for a real expectation. Every retained test must assert a concrete contract-backed outcome.
Do not copy placeholder example names or invent alternate helpers.
If the implementation validates a required document or evidence list before scoring, every happy-path or valid batch item must include the full required set named by that validator. Do not use a single placeholder document like ["ID"] when the implementation names additional required evidence items.
If the implementation validates required payload keys before processing, every happy-path or valid batch item must include that full required key set. Do not omit fields like claim_type, amount, timestamp, or similar required payload keys from supposedly valid scenarios.
If the implementation shows a named required_evidence or required_documents list, copy that full list verbatim into every valid happy-path or valid batch payload instead of shrinking it to a representative subset.
Do not require a strictly positive score, non-empty risk list, or similar nonzero scoring side effect from a generic happy-path input unless the chosen payload actually exercises a documented risk factor. For a plain valid request, prefer asserting that scoring completed, a score record exists, or the score is non-negative.
Stay under stated line, fixture, and top-level test limits.
Do not add duplicate-detection, risk-tier, audit-only, or helper-only tests unless the exact contract or behavior contract explicitly requires them.
Do not add helper-only imports or helper-only tests when a documented public service facade exists.
Record-shaped value models such as AuditLog, RiskScore, ResultRecord, or similar typed data holders are not service collaborators unless the exact contract explicitly says so. Do not replace an undefined helper alias with a similarly named record type just because it imports cleanly.
If repair feedback reports unknown symbols, invalid members, or constructor mismatches, rebuild from the exact contract and remove those invalid surfaces entirely.
If the previous validation summary reports contract overreach signals, that prior suite guessed behavior beyond the documented contract. Discard brittle exact batch-count or status-threshold assertions and rebuild only the minimum contract-backed scenarios instead of patching the old file in place.
If repair feedback reports contract overreach signals, discard the prior overreaching assertions and rebuild only contract-backed scenarios instead of preserving brittle exact batch-count or threshold guesses.
If repair feedback reports tests without assertion-like checks, discard the prior hollow test bodies and rebuild the minimum contract-backed suite with explicit assertions instead of patching the old file in place.
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
    def _repair_focus_block(
        repair_validation_summary: object,
        implementation_code: object = "",
        existing_tests: object = "",
    ) -> str:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return ""

        normalized = repair_validation_summary.lower()
        focus_lines: list[str] = []
        required_payload_keys = QATesterAgent._implementation_required_payload_keys(implementation_code) or []
        validation_omitted_payload_key = QATesterAgent._validation_failure_omitted_payload_key(implementation_code)
        required_evidence_items = QATesterAgent._implementation_required_evidence_items(implementation_code) or []
        required_request_fields = QATesterAgent._implementation_required_request_fields(implementation_code) or []
        non_validation_payload_keys = QATesterAgent._implementation_non_validation_payload_keys(implementation_code) or []
        validation_missing_request_field = QATesterAgent._validation_failure_missing_request_field(implementation_code)
        _, validation_request_like_line = QATesterAgent._validation_failure_request_like_object_scaffold_line(
            implementation_code,
        )
        requires_recent_request_timestamp = QATesterAgent._implementation_requires_recent_request_timestamp(
            implementation_code,
        )
        exact_numeric_score_issue = QATesterAgent._summary_has_exact_numeric_score_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        positive_numeric_score_issue = QATesterAgent._summary_has_positive_numeric_score_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        presence_only_validation_sample_issue = (
            QATesterAgent._summary_has_presence_only_validation_sample_issue(
                repair_validation_summary,
                existing_tests,
                implementation_code,
            )
        )
        required_evidence_runtime_issue = QATesterAgent._summary_has_required_evidence_runtime_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        required_payload_runtime_issue = QATesterAgent._summary_has_required_payload_runtime_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        exact_status_action_label_issue = QATesterAgent._summary_has_exact_status_action_label_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        exact_band_label_issue = QATesterAgent._summary_has_exact_band_label_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        exact_temporal_value_issue = QATesterAgent._summary_has_exact_temporal_value_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        undefined_local_entries = [
            item.split(" (line ", 1)[0].strip()
            for item in QATesterAgent._comma_separated_items(
                QATesterAgent._summary_issue_value(repair_validation_summary, "Undefined local names")
            )
            if item.strip()
        ]
        undefined_local_names = {
            name.lower()
            for name in re.findall(
                r"[A-Za-z_][A-Za-z0-9_]*",
                QATesterAgent._summary_issue_value(repair_validation_summary, "Undefined local names"),
            )
        }
        available_module_symbol_names = QATesterAgent._undefined_available_module_symbol_names(
            implementation_code,
            repair_validation_summary,
        )
        available_module_symbol_lowers = {name.lower() for name in available_module_symbol_names}
        helper_alias_names = [
            name
            for name in undefined_local_entries
            if name.lower() not in available_module_symbol_lowers
            if QATesterAgent._is_helper_alias_like_name(name)
        ]

        if "pytest" in undefined_local_names or "name 'pytest' is not defined" in normalized:
            focus_lines.append(
                "- The previous file used `pytest.` without importing `pytest`. Add `import pytest` at the top if the rewritten suite keeps any `pytest.` references."
            )

        if "datetime" in undefined_local_names or "name 'datetime' is not defined" in normalized:
            focus_lines.append(
                "- The previous file referenced `datetime` without importing it. If any rewritten test keeps `datetime.now()` or another bare `datetime` reference, add a matching import such as `from datetime import datetime` or `import datetime` at the top before finalizing. Otherwise remove every bare `datetime` reference and switch those timestamp values to a self-contained literal or previously defined local that still matches the implementation contract."
            )
            focus_lines.append(
                "- Do not copy the previous invalid file forward unchanged. The rewritten suite must resolve every bare `datetime` reference before returning, either by adding the matching import or by replacing those constructor arguments with a self-contained local value."
            )
            if QATesterAgent._implementation_prefers_direct_datetime_import(implementation_code):
                focus_lines.append(
                    "- The implementation already uses `from datetime import datetime`. Match that import style in the rewritten tests and prefer a local fixed timestamp such as `fixed_time = datetime(2024, 1, 1, 0, 0, 0)` for constructor arguments instead of repeating unresolved bare `datetime.now()` calls."
                )

        if "line count" in normalized and "exceeds maximum" in normalized:
            focus_lines.append(
                "- The previous file failed because it exceeded the hard line budget. Rewrite to only the minimum contract-required trio, delete any fourth-or-later top-level test, remove per-test docstrings, comments, and extra blank lines, and drop validator-only, audit-only, risk-tier, or other helper-only coverage before touching the required scenarios."
            )

        if available_module_symbol_names:
            rendered_names = ", ".join(available_module_symbol_names)
            focus_lines.append(
                "- The previous file referenced real production symbols that exist in the module but were never imported, such as "
                f"`{rendered_names}`. Add each one to the import list at the top of the file before use instead of deleting, renaming, or leaving it as an undefined local."
            )

        if helper_alias_names:
            rendered_names = ", ".join(helper_alias_names)
            focus_lines.append(
                "- The previous file referenced undefined helper or collaborator aliases such as "
                f"`{rendered_names}`. Do not repair those names by swapping to a similarly named record or dataclass like `AuditLog()`; delete that guessed collaborator wiring and rebuild around the documented service facade or directly exchanged request or result models only."
            )

        if required_request_fields and not required_payload_keys:
            rendered_fields = ", ".join(required_request_fields)
            focus_lines.append(
                "- The current validator checks top-level request field presence on the request object rather than nested payload keys. "
                f"The required top-level field set here is {rendered_fields}. A fully populated request-model constructor that still supplies all of those fields remains valid even when nested business values are `False`, empty, or low-risk."
            )
            if validation_missing_request_field:
                focus_lines.append(
                    "- In `test_validation_failure`, do not replace the scaffolded request-like object with a fully populated request-model constructor such as `ReturnCase(...)`. "
                    f"Keep the request-like object missing `{validation_missing_request_field}` exactly as shown so `validate_request(...)` actually returns `False` before the workflow raises `ValueError`."
                )
                if validation_request_like_line:
                    focus_lines.append(
                        "- Keep the constructor-free invalid object line exactly as scaffolded: "
                        f"`{validation_request_like_line}`. Reuse that same `invalid_request` object in both `validate_request(...)` and the workflow call, and do not replace it with a request-model constructor or a placeholder case such as `details={{}}`."
                    )
                focus_lines.append(
                    f"- Do not fake a missing top-level field with `{validation_missing_request_field}=None`, an empty string, or another placeholder value. For this validator the field must be absent from the object entirely, not merely present with a falsey value."
                )

        if requires_recent_request_timestamp:
            recent_fixed_time_expr = f"`fixed_time = {QATesterAgent._fixed_time_expression(implementation_code)}`"
            focus_lines.append(
                "- The implementation validates request timestamp recency before happy-path scoring or workflow execution. "
                f"Do not keep a stale historical calendar literal in supposedly valid or risk-scoring tests. Use a recent local value such as {recent_fixed_time_expr} so valid requests pass validation first, and only age secondary fields like approval-chain timestamps when the scenario explicitly needs that branch."
            )
            focus_lines.append(
                "- Delete stale constructor literals such as `datetime(2024, 1, 1, ...)` from valid workflow tests when the validator compares request time to `datetime.now(...)`. A stale fixed timestamp will force the request down the validation-failure path and zero out downstream scoring expectations."
            )

        if exact_numeric_score_issue:
            focus_lines.append(
                "- The previous runtime failure came from a brittle exact numeric score or total guess. Recompute that expectation from only the branches exercised by the chosen input if the formula is explicit; otherwise replace the equality with stable invariants such as non-negative score, relative ordering, or the documented workflow outcome."
            )

        if positive_numeric_score_issue:
            focus_lines.append(
                "- The previous runtime failure came from assuming a positive non-zero score where the current implementation returned 0.0. Do not assert `result.risk_score > 0.0`, `result.score > 0.0`, or a similar positive-threshold check unless the implementation or contract explicitly guarantees that increase for the chosen input."
            )
            focus_lines.append(
                "- Prefer stable score invariants such as `>= 0.0`, `<= 1.0`, type checks, relative ordering, or documented decision and audit evidence over speculative positive-score thresholds in risk-scoring or emergency-path tests."
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

        if "exact batch audit length" in normalized:
            focus_lines.append(
                "- The previous suite overreached by expecting more batch audit entries than the visible number of processed items. Remove that guessed extra-count assertion and prefer result count, request identity, or monotonic audit growth unless the contract explicitly defines extra summary entries."
            )

        if "exact status/action label mismatch" in normalized or exact_status_action_label_issue:
            focus_lines.append(
                "- The previous runtime failure came from a brittle exact status or action label guess. Unless the contract explicitly defines the trigger, replace blocked, escalated, approved, conditional approval, straight-through, straight-through review, manual investigation, fraud escalation, time-boxed approval, or similar label guesses with stable invariants or with clearly non-borderline inputs whose outcome is documented."
            )
            focus_lines.append(
                "- In happy-path or valid batch scenarios, do not assert exact outcome strings such as `straight-through` or `manual investigation` unless the contract explicitly defines that input-to-label mapping; prefer request identity, audit growth, or another documented invariant instead."
            )
            focus_lines.append(
                "- Delete exact equality checks on `.action_type`, `.outcome`, `.status`, `['action_type']`, `['outcome']`, or `['status']` in happy-path and valid batch tests unless the contract explicitly defines that label mapping. Replace them with type, identity, count, or other contract-backed invariants."
            )
            focus_lines.append(
                "- Apply the same rule to return-review labels such as `auto-approve`, `manual inspection`, and `abuse escalation`; do not hard-code them in happy-path or valid batch tests unless the contract explicitly defines that mapping."
            )
            focus_lines.append(
                "- Treat audit-log message text the same way: do not hard-code label substrings such as `Approved`, `Escalated`, `Blocked`, or `Rejected` inside audit-log assertions unless the contract explicitly defines that text. Prefer request identity, entry count, or another contract-backed invariant."
            )

        if exact_band_label_issue:
            focus_lines.append(
                "- The previous runtime failure came from a brittle exact risk-tier or severity-band threshold guess. Unless the contract explicitly defines that score-to-band mapping, do not assert exact `risk_level`, `severity`, `priority`, `classification`, or similar tier labels such as `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` in happy-path, risk-scoring, audit-trail, or batch tests."
            )
            focus_lines.append(
                "- Delete exact equality checks like `== 'HIGH'` and narrow subset checks like `in ['HIGH', 'CRITICAL']` on `.risk_level`, `.severity`, `.priority`, `['risk_level']`, or similar band fields. Replace them with score bounds, audit evidence, request identity, or a simple string-type assertion unless the contract explicitly documents the threshold map."
            )

        if exact_temporal_value_issue:
            focus_lines.append(
                "- The previous runtime failure came from a brittle exact timestamp or generated-time equality guess. Do not assert that emitted `timestamp`, `created_at`, `updated_at`, or similar generated values exactly equal `fixed_time`, `request.timestamp`, `str(fixed_time)`, or another local time surrogate unless the contract explicitly documents that echo."
            )
            focus_lines.append(
                "- Prefer stable checks such as timestamp presence, request identity, collection growth, or type/format assertions over exact equality to a locally fixed time when the implementation may create its own action record time or identifier."
            )

        if "exact internal action-map key assumption" in normalized:
            focus_lines.append(
                "- The previous runtime failure came from assuming an internal action or review map used request identity as its key. Do not assert membership like `request.request_id in service.review_actions` unless the contract explicitly defines that storage key."
            )
            focus_lines.append(
                "- If the implementation stores `ReviewAction(action_id, ...)` or another action record with its own generated identifier, assert the action-map size or inspect stored action values instead of assuming the map key equals request_id, vendor_id, or another request-identity field."
            )

        if presence_only_validation_sample_issue:
            focus_lines.append(
                "- The previous validation-failure test still kept every required payload field that the current validator only checks for presence. Do not keep all required keys with same-type placeholder values like `\"value\"`; omit at least one required field or choose another input that the validator actually rejects."
            )
            if required_payload_keys:
                focus_lines.append(
                    "- The current validator only requires the presence of "
                    f"{', '.join(required_payload_keys)} inside the payload. Keep the rest of the rejection case valid and omit one of those required fields instead of keeping all of them with placeholder values."
                )
            if validation_omitted_payload_key:
                focus_lines.append(
                    "- In `test_validation_failure`, keep the scaffolded omission on the validator-required key "
                    f"`{validation_omitted_payload_key}` exactly as shown. Do not replace that omission with a different downstream business key."
                )
            if non_validation_payload_keys:
                rendered_keys = ", ".join(non_validation_payload_keys[:3])
                focus_lines.append(
                    "- Do not swap that missing-field case to optional downstream business keys such as "
                    f"{rendered_keys}. Those keys are only read after validation in scoring or review logic here, so omitting them may change risk but should not be used as the `validate_request(...)` rejection case."
                )
                if required_payload_keys:
                    focus_lines.append(
                        "- A payload that still includes every validator-required field "
                        f"{', '.join(required_payload_keys)} but only omits downstream keys such as {rendered_keys} remains validation-valid here. Delete that shape from `test_validation_failure` and omit a real validator-required key instead."
                    )

        if required_payload_runtime_issue:
            focus_lines.append(
                "- The previous happy-path or batch test still omitted required payload fields that the current validator checks before processing. Do not keep partial payloads in supposedly valid scenarios."
            )
            if required_payload_keys and len(required_payload_keys) > 0:
                focus_lines.append(
                    "- Every valid happy-path or batch payload must include all required payload keys named by the current validator: "
                    f"{', '.join(required_payload_keys)}. Keep missing-field coverage isolated to the explicit validation-failure test."
                )

        if required_evidence_runtime_issue:
            focus_lines.append(
                "- The previous non-validation suite still used incomplete required-evidence payloads inside processing assertions. Keep risk-scoring, audit-trail, happy-path, and batch scenarios fully valid, and isolate missing-document coverage to the explicit validation-failure test."
            )
            if required_evidence_items:
                focus_lines.append(
                    "- The current validator requires the full evidence set "
                    f"{required_evidence_items!r} before processing. Copy that full list into every non-validation scenario that calls the workflow or scoring path."
                )

        if "exact validation-failure score-state emptiness assertion" in normalized:
            focus_lines.append(
                "- The previous runtime failure came from assuming a rejected or invalid request leaves internal score state empty. Do not assert len(service.get_risk_scores()) == 0 or a similar exact zero-length check on internal score maps, caches, or derived-state collections unless the contract explicitly guarantees that post-validation state; prefer the rejected outcome, documented audit or action evidence, or another observable contract-backed effect."
            )
            focus_lines.append(
                "- In a validation-failure test, remove direct reads of `service.get_risk_scores()` or similar internal score state unless that post-failure state is itself the documented contract. Assert the rejected return value, blocked audit entry, or another documented effect instead."
            )

        if "exact return-shape attribute assumption" in normalized:
            focus_lines.append(
                "- The previous runtime failure came from assuming a wrapped object return shape that the current runtime did not provide. Do not assert attributes such as `.request_id` or `.outcome` on the return value unless the contract or implementation explicitly exposes that wrapper type; prefer direct value checks or documented mapping keys instead."
            )
            focus_lines.append(
                "- Delete every `.request_id`, `.outcome`, or similar attribute read on the workflow return value in happy-path and batch tests. If the workflow currently returns a direct string or other primitive, compare that direct value or assert a documented side effect instead of inventing a wrapper object."
            )
            focus_lines.append(
                "- Remove guessed wrapper-result imports such as `AccessReviewOutcome`, `ReviewOutcome`, or similar result classes when they are only used for those invalid return-shape assertions. Import only the documented facade and request model unless the implementation explicitly returns that wrapper type."
            )

        if "did not raise" in normalized:
            focus_lines.append(
                "- A previous validation-failure test expected an exception that the current input did not trigger. Do not keep `pytest.raises(...)` around a same-type business variation; choose an input that actually violates the current validator, such as a missing required field, unsupported request type, or wrong top-level type, or assert the documented non-exception outcome instead."
            )

        if "assert false" in normalized:
            focus_lines.append(
                "- The previous suite used a placeholder boolean failure such as `assert False` instead of a real contract-backed expectation. Delete that placeholder and replace it with an explicit validation result, raised exception, or observable side effect."
            )

        if "exact return-shape attribute assumption" in normalized and "did not raise" in normalized:
            focus_lines.append(
                "- The failed suite mixed a guessed return wrapper with a guessed exception path. Rebuild from scratch: keep happy-path and batch checks on the direct value or documented side effects of the workflow call, and make the validation-failure test use an input that the current validator actually rejects instead of a same-type business variation."
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
    def _summary_has_placeholder_boolean_assertion_issue(
        repair_validation_summary: object,
        content: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False

        summary_lower = repair_validation_summary.lower()
        if "pytest failure details" not in summary_lower:
            return False
        if "assert false" not in summary_lower and "assert true" not in summary_lower:
            return False

        if isinstance(content, str) and content.strip():
            if re.search(r"(?m)^\s*assert\s+(?:True|False)\s*(?:#.*)?$", content):
                return True
            if re.search(r"(?im)#\s*assuming\b", content):
                return True
            return False

        return True

    @staticmethod
    def _test_function_block(content: object, test_name: str) -> str:
        if not isinstance(content, str) or not content.strip() or not test_name.strip():
            return ""
        match = re.search(
            rf"(?ms)^def\s+{re.escape(test_name)}\s*\([^)]*\):\n.*?(?=^def\s+|\Z)",
            content,
        )
        if not match:
            return ""
        return match.group(0)

    @staticmethod
    def _pytest_failed_test_names(repair_validation_summary: object) -> list[str]:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return []

        names: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"FAILED\s+\S+::([A-Za-z_][A-Za-z0-9_]*)", repair_validation_summary):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    @staticmethod
    def _is_validation_failure_test_name(test_name: str) -> bool:
        lowered = test_name.strip().lower()
        if not lowered:
            return False
        return any(token in lowered for token in ("validation", "invalid", "reject", "error", "failure"))

    @classmethod
    def _failed_test_function_nodes(
        cls,
        repair_validation_summary: object,
        content: object,
    ) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
        tree = cls._parse_implementation_tree(content)
        if tree is None:
            return []

        nodes = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        failed_names = cls._pytest_failed_test_names(repair_validation_summary)
        if not failed_names:
            return nodes

        failed_name_set = set(failed_names)
        return [node for node in nodes if node.name in failed_name_set]

    @classmethod
    def _test_function_targets_valid_processing(
        cls,
        function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        function_name = function_node.name.lower()
        if any(token in function_name for token in ("validation", "invalid", "reject", "error", "failure")):
            return False
        if any(token in function_name for token in ("happy", "batch", "risk", "score", "audit")):
            return True

        workflow_call_names = {
            "batch_process",
            "calculate_risk_score",
            "handle_request",
            "intake_request",
            "process_request",
            "score_request",
            "score_risk",
            "submit_intake",
            "submit_request",
        }
        return any(
            isinstance(child, ast.Call)
            and cls._call_expression_name(child) in workflow_call_names
            for child in ast.walk(function_node)
        )

    @staticmethod
    def _canonical_status_like_label(value: str) -> str | None:
        normalized = re.sub(r"[\s\-]+", "_", value.strip().lower())
        if not normalized:
            return None

        aliases = {
            "accepted": "accepted",
            "abuse_escalation": "abuse_escalation",
            "approve": "approve",
            "approved": "approved",
            "auto_approve": "auto_approve",
            "blocked": "blocked",
            "conditional_approval": "conditional_approval",
            "conditional_approve": "conditional_approve",
            "enhanced_due_diligence": "enhanced_due_diligence",
            "escalated": "escalated",
            "flagged": "flagged",
            "fraud": "fraud",
            "fraud_escalation": "fraud_escalation",
            "invalid": "invalid",
            "manual_inspection": "manual_inspection",
            "manual_investigation": "manual_investigation",
            "manual_review": "manual_review",
            "pending": "pending",
            "pending_review": "pending_review",
            "rejected": "rejected",
            "security_escalation": "security_escalation",
            "straight_through": "straight_through_review",
            "straight_through_review": "straight_through_review",
            "time_boxed_approval": "time_boxed_approval",
        }
        return aliases.get(normalized)

    @classmethod
    def _status_like_literal_values(cls, expression: ast.AST) -> list[str]:
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            canonical = cls._canonical_status_like_label(expression.value)
            return [canonical] if canonical else []

        values = cls._string_literal_sequence(expression)
        if not values:
            return []

        canonical_values = [cls._canonical_status_like_label(value) for value in values]
        if any(value is None for value in canonical_values):
            return []
        return [value for value in canonical_values if value is not None]

    @staticmethod
    def _canonical_band_like_label(value: str) -> str | None:
        normalized = re.sub(r"[\s\-]+", "_", value.strip().lower())
        if not normalized:
            return None

        aliases = {
            "critical": "critical",
            "high": "high",
            "low": "low",
            "medium": "medium",
        }
        return aliases.get(normalized)

    @classmethod
    def _band_like_literal_values(cls, expression: ast.AST) -> list[str]:
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            canonical = cls._canonical_band_like_label(expression.value)
            return [canonical] if canonical else []

        values = cls._string_literal_sequence(expression)
        if not values:
            return []

        canonical_values = [cls._canonical_band_like_label(value) for value in values]
        if any(value is None for value in canonical_values):
            return []
        return [value for value in canonical_values if value is not None]

    @classmethod
    def _numeric_literal_value(cls, expression: ast.AST) -> int | float | None:
        if isinstance(expression, ast.Constant) and isinstance(expression.value, (int, float)):
            return expression.value
        if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.USub):
            operand = cls._numeric_literal_value(expression.operand)
            if operand is not None:
                return -operand
        return None

    @staticmethod
    def _expression_text(expression: ast.AST) -> str:
        try:
            return ast.unparse(expression).lower()
        except Exception:
            return ""

    @classmethod
    def _summary_has_exact_status_action_label_assertion_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False

        summary_lower = repair_validation_summary.lower()
        if "pytest execution: fail" not in summary_lower and "pytest failure details:" not in summary_lower:
            return False

        for node in cls._failed_test_function_nodes(repair_validation_summary, content):
            if cls._is_validation_failure_test_name(node.name):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Assert):
                    continue
                if not isinstance(child.test, ast.Compare) or len(child.test.ops) != 1 or len(child.test.comparators) != 1:
                    continue
                if not isinstance(child.test.ops[0], (ast.Eq, ast.In)):
                    continue

                if isinstance(child.test.ops[0], ast.In):
                    comparator_text = cls._expression_text(child.test.comparators[0])
                    if (
                        isinstance(child.test.left, ast.Constant)
                        and isinstance(child.test.left.value, str)
                        and ("audit_log" in comparator_text or "audit_logs" in comparator_text)
                    ):
                        left_text = child.test.left.value.lower()
                        if any(
                            token in left_text
                            for token in (
                                "approved",
                                "blocked",
                                "escalated",
                                "rejected",
                                "manual review",
                                "manual investigation",
                                "fraud escalation",
                                "straight-through",
                            )
                        ):
                            return True
                        if re.search(r"score:\s*\d+(?:\.\d+)?", left_text):
                            return True

                left_labels = cls._status_like_literal_values(child.test.left)
                right_labels = cls._status_like_literal_values(child.test.comparators[0])
                if left_labels and not right_labels:
                    return True
                if right_labels and not left_labels:
                    return True
        return False

    @classmethod
    def _summary_has_exact_band_label_assertion_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False

        summary_lower = repair_validation_summary.lower()
        if "pytest execution: fail" not in summary_lower and "pytest failure details:" not in summary_lower:
            return False

        full_band_set = {"low", "medium", "high", "critical"}

        def band_values_from_summary_list(raw_values: str) -> list[str]:
            values = re.findall(r"['\"]([^'\"]+)['\"]", raw_values)
            if not values:
                return []
            canonical_values = [cls._canonical_band_like_label(value) for value in values]
            if any(value is None for value in canonical_values):
                return []
            return [value for value in canonical_values if value is not None]

        for actual_value, expected_values in re.findall(
            r"assert\s+['\"]([^'\"]+)['\"]\s+in\s+\[([^\]]+)\]",
            repair_validation_summary,
            flags=re.IGNORECASE,
        ):
            actual_band = cls._canonical_band_like_label(actual_value)
            expected_bands = band_values_from_summary_list(expected_values)
            if actual_band and expected_bands and actual_band not in expected_bands and set(expected_bands) != full_band_set:
                return True

        for left_value, right_value in re.findall(
            r"assert\s+['\"]([^'\"]+)['\"]\s*==\s*['\"]([^'\"]+)['\"]",
            repair_validation_summary,
            flags=re.IGNORECASE,
        ):
            left_band = cls._canonical_band_like_label(left_value)
            right_band = cls._canonical_band_like_label(right_value)
            if left_band and right_band and left_band != right_band:
                return True

        field_tokens = ("risk_level", "severity", "priority", "classification", "tier", "band")
        for node in cls._failed_test_function_nodes(repair_validation_summary, content):
            if cls._is_validation_failure_test_name(node.name):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Assert):
                    continue
                if not isinstance(child.test, ast.Compare) or len(child.test.ops) != 1 or len(child.test.comparators) != 1:
                    continue

                left_text = cls._expression_text(child.test.left)
                right_text = cls._expression_text(child.test.comparators[0])
                if not any(token in left_text or token in right_text for token in field_tokens):
                    continue

                comparator = child.test.comparators[0]
                if isinstance(child.test.ops[0], ast.In):
                    expected_bands = cls._band_like_literal_values(comparator)
                    if expected_bands and set(expected_bands) != full_band_set:
                        return True
                    continue

                if not isinstance(child.test.ops[0], ast.Eq):
                    continue

                left_bands = cls._band_like_literal_values(child.test.left)
                right_bands = cls._band_like_literal_values(comparator)
                if left_bands and not right_bands:
                    return True
                if right_bands and not left_bands:
                    return True
                if left_bands and right_bands and set(left_bands) != set(right_bands):
                    return True
        return False

    @classmethod
    def _summary_has_exact_temporal_value_assertion_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False

        summary_lower = repair_validation_summary.lower()
        if not re.search(r"assert\s+['\"]?20\d{2}-\d{2}-\d{2}", summary_lower):
            return False

        temporal_tokens = (
            "timestamp",
            "created_at",
            "updated_at",
            "fixed_time",
            "fixed_timestamp",
            "request.timestamp",
            "isoformat(",
            "str(fixed_time)",
            "str(fixed_timestamp)",
        )
        for node in cls._failed_test_function_nodes(repair_validation_summary, content):
            if cls._is_validation_failure_test_name(node.name):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Assert):
                    continue
                if not isinstance(child.test, ast.Compare) or len(child.test.ops) != 1 or len(child.test.comparators) != 1:
                    continue
                if not isinstance(child.test.ops[0], ast.Eq):
                    continue

                left_text = cls._expression_text(child.test.left)
                right_text = cls._expression_text(child.test.comparators[0])
                if any(token in left_text for token in temporal_tokens) or any(token in right_text for token in temporal_tokens):
                    return True
        return False

    @classmethod
    def _summary_has_exact_numeric_score_assertion_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False

        if re.search(r"assert\s+-?\d+(?:\.\d+)?\s*==\s*-?\d+(?:\.\d+)?", repair_validation_summary) is None:
            return False

        for node in cls._failed_test_function_nodes(repair_validation_summary, content):
            if cls._is_validation_failure_test_name(node.name):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Assert):
                    continue
                if not isinstance(child.test, ast.Compare) or len(child.test.ops) != 1 or len(child.test.comparators) != 1:
                    continue
                if not isinstance(child.test.ops[0], ast.Eq):
                    continue

                left_text = cls._expression_text(child.test.left)
                right_text = cls._expression_text(child.test.comparators[0])
                if not any(token in left_text or token in right_text for token in ("risk_score", "score")):
                    continue
                if (
                    cls._numeric_literal_value(child.test.left) is not None
                    or cls._numeric_literal_value(child.test.comparators[0]) is not None
                ):
                    return True
        return False

    @classmethod
    def _summary_has_positive_numeric_score_assertion_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False

        summary_lower = repair_validation_summary.lower()
        if "pytest execution: fail" not in summary_lower and "pytest failure details:" not in summary_lower:
            return False

        score_tokens = ("risk_score", "score")
        for node in cls._failed_test_function_nodes(repair_validation_summary, content):
            if cls._is_validation_failure_test_name(node.name):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Assert):
                    continue
                if not isinstance(child.test, ast.Compare) or len(child.test.ops) != 1 or len(child.test.comparators) != 1:
                    continue

                left_text = cls._expression_text(child.test.left)
                right_text = cls._expression_text(child.test.comparators[0])
                if not any(token in left_text or token in right_text for token in score_tokens):
                    continue

                left_numeric = cls._numeric_literal_value(child.test.left)
                right_numeric = cls._numeric_literal_value(child.test.comparators[0])
                op = child.test.ops[0]

                if isinstance(op, ast.Gt):
                    if right_numeric is not None and right_numeric >= 0.0 and any(token in left_text for token in score_tokens):
                        return True
                    if left_numeric is not None and left_numeric >= 0.0 and any(token in right_text for token in score_tokens):
                        return True

                if isinstance(op, ast.Lt):
                    if left_numeric is not None and left_numeric >= 0.0 and any(token in right_text for token in score_tokens):
                        return True
                    if right_numeric is not None and right_numeric >= 0.0 and any(token in left_text for token in score_tokens):
                        return True

        return False

    @staticmethod
    def _implementation_prefers_timezone_aware_now(implementation_code: object) -> bool:
        return isinstance(implementation_code, str) and "timezone.utc" in implementation_code

    @classmethod
    def _implementation_requires_recent_request_timestamp(cls, implementation_code: object) -> bool:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return False

        lowered = implementation_code.lower()
        if "request timestamp is stale" in lowered or "timestamp cannot be in the future" in lowered:
            return True
        if re.search(r"request\.(?:timestamp|created_at|updated_at)\s*<\s*int\(", implementation_code):
            return True
        if (
            "datetime.now" in implementation_code
            and "timestamp" in lowered
            and (
                "return policy" in lowered
                or re.search(r"\.days\s*[<>]=?\s*(?:30|60|90|120|180|365)", implementation_code)
                or re.search(
                    r"datetime(?:\.datetime)?\.now\s*\([^\n]*\)\s*-\s*(?:request\.)?timestamp",
                    implementation_code,
                )
            )
        ):
            return True
        if (
            "datetime.now" in implementation_code
            and re.search(r"request(?:_ts|_timestamp|\.timestamp)", implementation_code)
            and (
                "86400" in implementation_code
                or re.search(
                    r"timedelta\s*\(\s*(?:days\s*=\s*1|hours\s*=\s*24|minutes\s*=\s*1440)\s*\)",
                    lowered,
                )
                or re.search(
                    r"total_seconds\s*\(\)\s*[<>]=?\s*(?:86400|24\s*\*\s*60\s*\*\s*60)",
                    implementation_code,
                )
            )
        ):
            return True
        return bool(
            re.search(r"request(?:_ts|_timestamp|\.timestamp)", implementation_code)
            and re.search(r"timedelta\s*\(\s*days\s*=\s*(?:30|60|90|120|180|365)\s*\)", implementation_code)
        )

    @classmethod
    def _summary_has_validation_side_effect_without_workflow_call_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
    ) -> bool:
        block = cls._test_function_block(content, "test_validation_failure")
        if not block:
            return False

        block_lower = block.lower()
        if "validate_request(" not in block_lower:
            return False
        if any(
            workflow_call in block_lower
            for workflow_call in (
                "handle_request(",
                "process_request(",
                "intake_request(",
                "submit_request(",
                "submit_intake(",
            )
        ):
            return False
        if not any(
            token in block_lower
            for token in (
                "get_audit_log(",
                "audit_log",
                "get_risk_scores(",
                "risk_scores",
                "blocked",
                "rejected",
                "approved",
            )
        ):
            return False

        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return True
        summary_lower = repair_validation_summary.lower()
        return "pytest execution: fail" in summary_lower or "assert 0 == 1" in summary_lower

    @staticmethod
    def _is_helper_alias_like_name(name: str) -> bool:
        normalized = name.strip().lower()
        if not normalized:
            return False
        return normalized.endswith((
            "logger",
            "scorer",
            "processor",
            "manager",
            "repository",
            "validator",
            "engine",
            "service",
        ))

    @classmethod
    def _undefined_local_names(cls, repair_validation_summary: object) -> list[str]:
        value = cls._summary_issue_value(repair_validation_summary, "Undefined local names")
        if not value:
            return []
        names: list[str] = []
        seen: set[str] = set()
        for item in cls._comma_separated_items(value):
            name = item.split(" (line ", 1)[0].strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    @classmethod
    def _undefined_helper_alias_names_outside_exact_contract(
        cls,
        code_exact_test_contract: object,
        repair_validation_summary: object,
        implementation_code: object = "",
    ) -> list[str]:
        allowed_imports = {
            item.lower()
            for item in cls._comma_separated_items(
                cls._contract_line_value(code_exact_test_contract, "Allowed production imports")
            )
        }
        module_defined_symbols = {
            name.lower() for name in cls._module_defined_symbol_names(implementation_code)
        }
        return [
            name
            for name in cls._undefined_local_names(repair_validation_summary)
            if name.lower() not in {"pytest", "datetime"}
            and name.lower() not in allowed_imports
            and name.lower() not in module_defined_symbols
            and cls._is_helper_alias_like_name(name)
        ]

    @classmethod
    def _undefined_available_module_symbol_names(
        cls,
        implementation_code: object,
        repair_validation_summary: object,
    ) -> list[str]:
        module_symbols = {
            name.lower(): name for name in cls._module_defined_symbol_names(implementation_code)
        }
        available_names: list[str] = []
        seen: set[str] = set()
        for name in cls._undefined_local_names(repair_validation_summary):
            normalized = name.lower()
            if normalized in {"pytest", "datetime"}:
                continue
            actual_name = module_symbols.get(normalized)
            if not actual_name or actual_name in seen:
                continue
            seen.add(actual_name)
            available_names.append(actual_name)
        return available_names

    @staticmethod
    def _content_has_matching_datetime_import(content: object) -> bool:
        if not isinstance(content, str) or not content.strip():
            return False
        return bool(
            re.search(
                r"^\s*(?:from\s+datetime\s+import\s+[^\n]*\bdatetime\b|import\s+datetime\b)",
                content,
                flags=re.MULTILINE,
            )
        )

    @staticmethod
    def _content_has_bare_datetime_reference(content: object) -> bool:
        if not isinstance(content, str) or not content.strip():
            return False
        return bool(
            re.search(
                r"(?<![A-Za-z0-9_\.])datetime(?:\.[A-Za-z_][A-Za-z0-9_]*)?\s*\(",
                content,
            )
        )

    @classmethod
    def _summary_has_missing_datetime_import_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False
        summary_lower = repair_validation_summary.lower()
        if (
            "undefined local names: datetime" not in summary_lower
            and "name 'datetime' is not defined" not in summary_lower
        ):
            return False
        if isinstance(content, str) and content.strip():
            return (
                cls._content_has_bare_datetime_reference(content)
                and not cls._content_has_matching_datetime_import(content)
            )
        return True

    @staticmethod
    def _implementation_prefers_direct_datetime_import(implementation_code: object) -> bool:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return False
        return bool(
            re.search(
                r"^\s*from\s+datetime\s+import\s+[^\n]*\bdatetime\b",
                implementation_code,
                flags=re.MULTILINE,
            )
        )

    @classmethod
    def _implementation_prefers_datetime_module_import(cls, implementation_code: object) -> bool:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return False
        if cls._implementation_prefers_direct_datetime_import(implementation_code):
            return False
        return bool(
            re.search(r"^\s*import\s+datetime\b", implementation_code, flags=re.MULTILINE)
            or "datetime.datetime" in implementation_code
            or "datetime.timezone" in implementation_code
        )

    @classmethod
    def _datetime_like_parameter_names(cls, signature: str) -> list[str]:
        _, parameters = cls._signature_name_and_params(signature)
        names: list[str] = []
        for parameter in parameters:
            parameter_name = cls._parameter_name(parameter)
            if not parameter_name:
                continue
            lowered = parameter_name.lower()
            if lowered in {"timestamp", "date", "time"} or lowered.endswith(
                ("_timestamp", "_time", "_date", "_at")
            ):
                names.append(parameter_name)
        return names

    @staticmethod
    def _string_literal_sequence(node: ast.AST | None) -> list[str]:
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return []

        values: list[str] = []
        for element in node.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                return []
            values.append(element.value)
        return values

    @classmethod
    def _all_membership_required_names(
        cls,
        node: ast.AST,
        required_field_names: dict[str, list[str]],
    ) -> tuple[list[str], ast.AST | None]:
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "all"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.GeneratorExp)
        ):
            return [], None

        generator = node.args[0]
        if len(generator.generators) != 1:
            return [], None

        comprehension = generator.generators[0]
        if not isinstance(comprehension.target, ast.Name) or not isinstance(comprehension.iter, ast.Name):
            return [], None

        field_names = required_field_names.get(comprehension.iter.id, [])
        if not field_names:
            return [], None

        if not (
            isinstance(generator.elt, ast.Compare)
            and len(generator.elt.ops) == 1
            and isinstance(generator.elt.ops[0], ast.In)
            and len(generator.elt.comparators) == 1
            and isinstance(generator.elt.left, ast.Name)
            and generator.elt.left.id == comprehension.target.id
        ):
            return [], None

        return field_names, generator.elt.comparators[0]

    @staticmethod
    def _is_required_field_collection_name(name: str) -> bool:
        normalized = name.strip().lower()
        if not normalized:
            return False
        if normalized in {"required_fields", "required_keys"}:
            return True
        if not normalized.startswith("required_"):
            return False
        return any(
            token in normalized
            for token in (
                "field",
                "fields",
                "key",
                "keys",
                "payload",
                "detail",
                "details",
                "request",
            )
        )

    @staticmethod
    def _is_required_evidence_collection_name(name: str) -> bool:
        normalized = name.strip().lower()
        return normalized in {"required_documents", "required_evidence"}

    @staticmethod
    def _ast_parent_map(root: ast.AST) -> dict[ast.AST, ast.AST]:
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(root):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        return parents

    @staticmethod
    def _validation_result_call_is_invalid(node: ast.Call) -> bool:
        for keyword in node.keywords:
            if keyword.arg != "is_valid":
                continue
            return isinstance(keyword.value, ast.Constant) and keyword.value.value is False
        return False

    @staticmethod
    def _body_affects_validation_result(body: list[ast.stmt]) -> bool:
        for statement in body:
            for child in ast.walk(statement):
                if isinstance(child, ast.Raise):
                    return True
                if isinstance(child, ast.Return):
                    value = child.value
                    if isinstance(value, ast.Constant) and value.value is False:
                        return True
                    if isinstance(value, ast.Call) and QATesterAgent._validation_result_call_is_invalid(value):
                        return True
                if isinstance(child, ast.Assign):
                    if len(child.targets) != 1 or not isinstance(child.targets[0], ast.Name):
                        continue
                    if "valid" not in child.targets[0].id.lower():
                        continue
                    if isinstance(child.value, ast.Constant) and child.value.value is False:
                        return True
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    if child.func.attr not in {"append", "extend"}:
                        continue
                    if not isinstance(child.func.value, ast.Name):
                        continue
                    collection_name = child.func.value.id.lower()
                    if "error" in collection_name and "warning" not in collection_name:
                        return True
        return False

    @classmethod
    def _is_payload_key_set_expression(
        cls,
        node: ast.AST | None,
        payload_alias_names: set[str],
    ) -> bool:
        if node is None:
            return False
        if cls._is_payload_container_expression(node, payload_alias_names):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "set" and len(node.args) == 1:
            return cls._is_payload_key_set_expression(node.args[0], payload_alias_names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "keys":
            return cls._is_payload_container_expression(node.func.value, payload_alias_names)
        return False

    @classmethod
    def _is_direct_payload_container_expression(
        cls,
        node: ast.AST | None,
        payload_alias_names: set[str],
    ) -> bool:
        if node is None:
            return False
        if isinstance(node, ast.Name) and node.id.lower() in payload_alias_names:
            return True
        return isinstance(node, ast.Attribute) and cls._is_payload_container_expression(node, payload_alias_names)

    @classmethod
    def _expression_references_payload_value(
        cls,
        node: ast.AST | None,
        payload_alias_names: set[str],
    ) -> bool:
        if node is None:
            return False

        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                if child.func.attr == "get" and cls._is_payload_container_expression(
                    child.func.value,
                    payload_alias_names,
                ):
                    return True
            if isinstance(child, ast.Subscript) and cls._is_payload_container_expression(
                child.value,
                payload_alias_names,
            ):
                return True
            if (
                isinstance(child, ast.Compare)
                and len(child.ops) == 1
                and len(child.comparators) == 1
                and isinstance(child.left, ast.Constant)
                and isinstance(child.left.value, str)
                and isinstance(child.ops[0], (ast.In, ast.NotIn))
                and cls._is_payload_container_expression(child.comparators[0], payload_alias_names)
            ):
                return True
        return False

    @classmethod
    def _node_is_conditionally_guarded_by_payload_value(
        cls,
        node: ast.AST,
        parent_map: dict[ast.AST, ast.AST],
        payload_alias_names: set[str],
    ) -> bool:
        current = node
        skip_first_if = not isinstance(node, ast.If)
        while current in parent_map:
            current = parent_map[current]
            if not isinstance(current, ast.If):
                continue
            if skip_first_if:
                skip_first_if = False
                continue
            if cls._expression_references_payload_value(current.test, payload_alias_names):
                return True
        return False

    @classmethod
    def _loop_iterated_required_names(
        cls,
        node: ast.AST,
        parent_map: dict[ast.AST, ast.AST],
        required_field_names: dict[str, list[str]],
    ) -> list[str]:
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name):
            return []

        current: ast.AST = node
        while current in parent_map:
            current = parent_map[current]
            if isinstance(current, ast.For):
                if (
                    isinstance(current.target, ast.Name)
                    and current.target.id == node.left.id
                    and isinstance(current.iter, ast.Name)
                ):
                    return required_field_names.get(current.iter.id, [])
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                break
        return []

    @classmethod
    def _presence_check_branch_affects_validation(
        cls,
        node: ast.AST,
        parent_map: dict[ast.AST, ast.AST],
    ) -> bool:
        current = node
        while current in parent_map:
            current = parent_map[current]
            if isinstance(current, ast.If):
                return cls._body_affects_validation_result(current.body)
        return False

    @classmethod
    def _implementation_required_evidence_items(cls, implementation_code: object) -> list[str]:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return []

        try:
            tree = ast.parse(implementation_code)
        except SyntaxError:
            return []

        for node in ast.walk(tree):
            target_names: list[str] = []
            value_node: ast.AST | None = None
            if isinstance(node, ast.Assign):
                target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target_names = [node.target.id]
                value_node = node.value
            if not any(name in {"required_evidence", "required_documents"} for name in target_names):
                continue
            items = cls._string_literal_sequence(value_node)
            if items:
                return cls._merge_preserving_order(items)
        return []

    @classmethod
    def _implementation_required_payload_keys(cls, implementation_code: object) -> list[str]:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return []

        tree = cls._parse_implementation_tree(implementation_code)
        if tree is None:
            return []

        keys: list[str] = []
        seen: set[str] = set()
        payload_alias_names = cls._implementation_validate_payload_alias_names(implementation_code)
        validate_nodes: list[ast.AST] = []

        for module_node in tree.body:
            if isinstance(module_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and module_node.name.startswith("validate"):
                validate_nodes.append(module_node)
            elif isinstance(module_node, ast.ClassDef):
                for class_child in module_node.body:
                    if isinstance(class_child, (ast.FunctionDef, ast.AsyncFunctionDef)) and class_child.name.startswith("validate"):
                        validate_nodes.append(class_child)

        def append_key(value: str) -> None:
            normalized = value.strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            keys.append(normalized)

        for validate_node in validate_nodes:
            parent_map = cls._ast_parent_map(validate_node)
            required_field_names: dict[str, list[str]] = {}
            required_evidence_field_names: dict[str, list[str]] = {}
            missing_field_names: dict[str, list[str]] = {}
            for node in ast.walk(validate_node):
                target_names: list[str] = []
                value_node: ast.AST | None = None
                if isinstance(node, ast.Assign):
                    target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                    value_node = node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    target_names = [node.target.id]
                    value_node = node.value
                string_items = cls._string_literal_sequence(value_node)
                if string_items:
                    for name in target_names:
                        if cls._is_required_field_collection_name(name):
                            required_field_names[name] = string_items
                        if cls._is_required_evidence_collection_name(name):
                            required_evidence_field_names[name] = string_items

                if (
                    len(target_names) == 1
                    and isinstance(value_node, ast.BinOp)
                    and isinstance(value_node.op, ast.Sub)
                    and isinstance(value_node.left, ast.Name)
                ):
                    field_names = required_field_names.get(value_node.left.id, [])
                    if field_names and cls._is_payload_key_set_expression(
                        value_node.right,
                        payload_alias_names,
                    ):
                        missing_field_names[target_names[0]] = field_names

                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if (
                        node.func.attr == "issubset"
                        and isinstance(node.func.value, ast.Name)
                        and len(node.args) == 1
                    ):
                        field_names = required_field_names.get(node.func.value.id, [])
                        if field_names and cls._is_payload_container_expression(
                            node.args[0],
                            payload_alias_names,
                        ) and not cls._node_is_conditionally_guarded_by_payload_value(
                            node,
                            parent_map,
                            payload_alias_names,
                        ):
                            for item in field_names:
                                append_key(item)

                field_names, container_node = cls._all_membership_required_names(node, required_field_names)
                if field_names and cls._is_payload_container_expression(
                    container_node,
                    payload_alias_names,
                ) and not cls._node_is_conditionally_guarded_by_payload_value(
                    node,
                    parent_map,
                    payload_alias_names,
                ):
                    for item in field_names:
                        append_key(item)

                if isinstance(node, ast.If) and isinstance(node.test, ast.Name):
                    field_names = missing_field_names.get(node.test.id, [])
                    if field_names and cls._body_affects_validation_result(
                        node.body,
                    ) and not cls._node_is_conditionally_guarded_by_payload_value(
                        node,
                        parent_map,
                        payload_alias_names,
                    ):
                        for item in field_names:
                            append_key(item)

                if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
                    continue
                if not isinstance(node.ops[0], ast.NotIn):
                    continue
                comparator = node.comparators[0]
                loop_field_names = cls._loop_iterated_required_names(
                    node,
                    parent_map,
                    required_field_names | required_evidence_field_names,
                )
                if loop_field_names and cls._is_direct_payload_container_expression(
                    comparator,
                    payload_alias_names,
                ) and cls._presence_check_branch_affects_validation(
                    node,
                    parent_map,
                ) and not cls._node_is_conditionally_guarded_by_payload_value(
                    node,
                    parent_map,
                    payload_alias_names,
                ):
                    for item in loop_field_names:
                        append_key(item)
                    continue
                if not isinstance(node.left, ast.Constant) or not isinstance(node.left.value, str):
                    continue
                if cls._is_payload_container_expression(
                    comparator,
                    payload_alias_names,
                ) and cls._presence_check_branch_affects_validation(
                    node,
                    parent_map,
                ) and not cls._node_is_conditionally_guarded_by_payload_value(
                    node,
                    parent_map,
                    payload_alias_names,
                ):
                    append_key(node.left.value)

        return keys

    @staticmethod
    def _is_payload_container_expression(node: ast.AST | None, payload_alias_names: set[str]) -> bool:
        if node is None:
            return False
        if isinstance(node, ast.Name) and node.id.lower() in payload_alias_names:
            return True
        comparator_text = ast.unparse(node).lower()
        return any(
            token in comparator_text
            for token in (
                ".details",
                ".data",
                ".metadata",
                ".payload",
                ".request_data",
                ".document_data",
                ".attributes",
                ".context",
                "['details']",
                "['data']",
                "['metadata']",
                "['payload']",
                "['request_data']",
                "['document_data']",
                "['attributes']",
                "['context']",
            )
        )

    @staticmethod
    def _is_request_field_container_expression(node: ast.AST | None) -> bool:
        if node is None:
            return False
        if isinstance(node, ast.Attribute) and node.attr == "__dict__":
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "vars":
            return len(node.args) == 1
        comparator_text = ast.unparse(node).lower()
        return "__dict__" in comparator_text or comparator_text.startswith("vars(")

    @classmethod
    def _implementation_required_request_fields(cls, implementation_code: object) -> list[str]:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return []

        tree = cls._parse_implementation_tree(implementation_code)
        if tree is None:
            return []

        fields: list[str] = []
        seen: set[str] = set()
        validate_nodes: list[ast.AST] = []

        for module_node in tree.body:
            if isinstance(module_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and module_node.name.startswith("validate"):
                validate_nodes.append(module_node)
            elif isinstance(module_node, ast.ClassDef):
                for class_child in module_node.body:
                    if isinstance(class_child, (ast.FunctionDef, ast.AsyncFunctionDef)) and class_child.name.startswith("validate"):
                        validate_nodes.append(class_child)

        def append_field(value: str) -> None:
            normalized = value.strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            fields.append(normalized)

        for validate_node in validate_nodes:
            parent_map = cls._ast_parent_map(validate_node)
            required_field_names: dict[str, list[str]] = {}
            for node in ast.walk(validate_node):
                target_names: list[str] = []
                value_node: ast.AST | None = None
                if isinstance(node, ast.Assign):
                    target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                    value_node = node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    target_names = [node.target.id]
                    value_node = node.value

                string_items = cls._string_literal_sequence(value_node)
                if string_items:
                    for name in target_names:
                        if cls._is_required_field_collection_name(name):
                            required_field_names[name] = string_items

                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if (
                        node.func.attr == "issubset"
                        and isinstance(node.func.value, ast.Name)
                        and len(node.args) == 1
                    ):
                        field_names = required_field_names.get(node.func.value.id, [])
                        if field_names and cls._is_request_field_container_expression(node.args[0]):
                            for item in field_names:
                                append_field(item)

                field_names, container_node = cls._all_membership_required_names(node, required_field_names)
                if field_names and cls._is_request_field_container_expression(container_node):
                    for item in field_names:
                        append_field(item)

                if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
                    continue
                if not isinstance(node.ops[0], ast.NotIn):
                    continue
                if not isinstance(node.left, ast.Constant) or not isinstance(node.left.value, str):
                    continue
                if cls._is_request_field_container_expression(
                    node.comparators[0],
                ) and cls._presence_check_branch_affects_validation(node, parent_map):
                    append_field(node.left.value)

        return fields

    @staticmethod
    def _parse_implementation_tree(implementation_code: object) -> ast.Module | None:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return None
        try:
            return ast.parse(implementation_code)
        except SyntaxError:
            return None

    @classmethod
    def _implementation_validate_payload_alias_names(cls, implementation_code: object) -> set[str]:
        tree = cls._parse_implementation_tree(implementation_code)
        if tree is None:
            return set()

        payload_aliases: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "validate" not in node.name.lower():
                continue
            payload_aliases.update(cls._function_payload_alias_names(node))
        return payload_aliases

    @staticmethod
    def _function_payload_alias_names(function_node: ast.AST) -> set[str]:
        if not isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return set()

        payload_aliases: set[str] = set()
        payload_attrs = {
            "details",
            "data",
            "metadata",
            "request_data",
            "document_data",
            "attributes",
            "context",
            "payload",
        }
        parameter_names = [
            arg.arg
            for arg in [
                *function_node.args.posonlyargs,
                *function_node.args.args,
                *function_node.args.kwonlyargs,
            ]
        ]
        if function_node.args.vararg is not None:
            parameter_names.append(function_node.args.vararg.arg)
        if function_node.args.kwarg is not None:
            parameter_names.append(function_node.args.kwarg.arg)

        for parameter_name in parameter_names:
            if parameter_name.lower() in payload_attrs:
                payload_aliases.add(parameter_name.lower())

        for child in ast.walk(function_node):
            target_names: list[str] = []
            value_node: ast.AST | None = None
            if isinstance(child, ast.Assign):
                target_names = [target.id for target in child.targets if isinstance(target, ast.Name)]
                value_node = child.value
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                target_names = [child.target.id]
                value_node = child.value

            if not target_names:
                continue
            if isinstance(value_node, ast.Attribute):
                if isinstance(value_node.value, ast.Name) and value_node.attr in payload_attrs:
                    payload_aliases.update(name.lower() for name in target_names if name)
                continue

            if not isinstance(value_node, ast.Subscript):
                continue
            if not isinstance(value_node.value, ast.Name):
                continue
            slice_value = value_node.slice
            if not isinstance(slice_value, ast.Constant) or not isinstance(slice_value.value, str):
                continue
            if slice_value.value not in payload_attrs:
                continue
            payload_aliases.update(name.lower() for name in target_names if name)

        return payload_aliases

    @classmethod
    def _implementation_non_validation_payload_keys(cls, implementation_code: object) -> list[str]:
        tree = cls._parse_implementation_tree(implementation_code)
        if tree is None:
            return []

        required_payload_keys = {key.lower() for key in cls._implementation_required_payload_keys(implementation_code)}
        required_evidence_items = {item.lower() for item in cls._implementation_required_evidence_items(implementation_code)}
        keys: list[str] = []
        seen: set[str] = set()

        def append_key(value: str) -> None:
            normalized = value.strip()
            lowered = normalized.lower()
            if not normalized or lowered in seen:
                return
            if lowered in required_payload_keys or lowered in required_evidence_items:
                return
            seen.add(lowered)
            keys.append(normalized)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            payload_alias_names = cls._function_payload_alias_names(node)
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    if (
                        child.func.attr == "get"
                        and child.args
                        and isinstance(child.args[0], ast.Constant)
                        and isinstance(child.args[0].value, str)
                        and cls._is_payload_container_expression(child.func.value, payload_alias_names)
                    ):
                        append_key(child.args[0].value)
                    continue

                if not isinstance(child, ast.Compare) or len(child.ops) != 1 or len(child.comparators) != 1:
                    continue
                if not isinstance(child.left, ast.Constant) or not isinstance(child.left.value, str):
                    continue
                if not isinstance(child.ops[0], (ast.In, ast.NotIn)):
                    continue
                if cls._is_payload_container_expression(child.comparators[0], payload_alias_names):
                    append_key(child.left.value)

        return keys

    @staticmethod
    def _annotation_name(node: ast.AST | None) -> str:
        if node is None:
            return ""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):
            slice_name = QATesterAgent._annotation_name(node.slice)
            if slice_name:
                return slice_name
            return QATesterAgent._annotation_name(node.value)
        if isinstance(node, ast.Tuple):
            for element in node.elts:
                name = QATesterAgent._annotation_name(element)
                if name:
                    return name
        return ""

    @staticmethod
    def _call_expression_name(node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""

    @classmethod
    def _normalized_callable_ref(cls, callable_ref: str) -> str:
        normalized_ref, _ = cls._signature_name_and_params(callable_ref)
        return normalized_ref or callable_ref.strip()

    @classmethod
    def _nested_callable_ref(cls, current_callable_ref: str, call_name: str) -> str:
        normalized_ref = cls._normalized_callable_ref(current_callable_ref)
        if not normalized_ref or not call_name:
            return ""
        if "." not in normalized_ref:
            return call_name
        class_name, _ = normalized_ref.split(".", 1)
        if not class_name:
            return call_name
        return f"{class_name}.{call_name}"

    @classmethod
    def _implementation_callable_node(
        cls,
        implementation_code: object,
        callable_ref: str,
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        tree = cls._parse_implementation_tree(implementation_code)
        if tree is None or not callable_ref:
            return None

        normalized_ref, _ = cls._signature_name_and_params(callable_ref)
        normalized_ref = normalized_ref or callable_ref.strip()
        if not normalized_ref:
            return None

        target_class = ""
        target_name = normalized_ref
        if "." in normalized_ref:
            target_class, target_name = normalized_ref.split(".", 1)

        if target_class:
            for node in tree.body:
                if not isinstance(node, ast.ClassDef) or node.name != target_class:
                    continue
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == target_name:
                        return child
            return None

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_name:
                return node
        return None

    @staticmethod
    def _callable_local_assignment_values(
        function_node: ast.AST,
        target_name: str,
    ) -> list[ast.AST]:
        values: list[ast.AST] = []
        for child in ast.walk(function_node):
            if isinstance(child, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == target_name for target in child.targets):
                    values.append(child.value)
                continue
            if (
                isinstance(child, ast.AnnAssign)
                and isinstance(child.target, ast.Name)
                and child.target.id == target_name
                and child.value is not None
            ):
                values.append(child.value)
        return values

    @classmethod
    def _resolve_return_expression_shape(
        cls,
        implementation_code: object,
        current_callable_ref: str,
        function_node: ast.AST,
        expression: ast.AST | None,
        *,
        seen_callable_refs: set[str],
        seen_names: set[str] | None = None,
    ) -> tuple[str, str]:
        primitive_kind = cls._expression_primitive_kind(expression)
        if primitive_kind:
            return primitive_kind, ""
        if expression is None:
            return "", ""

        if isinstance(expression, ast.Name):
            current_seen_names = set(seen_names or set())
            if expression.id in current_seen_names:
                return "", ""
            current_seen_names.add(expression.id)
            resolved_shapes = [
                cls._resolve_return_expression_shape(
                    implementation_code,
                    current_callable_ref,
                    function_node,
                    value,
                    seen_callable_refs=seen_callable_refs,
                    seen_names=current_seen_names,
                )
                for value in cls._callable_local_assignment_values(function_node, expression.id)
            ]
            primitive_kinds = list(dict.fromkeys(kind for kind, _ in resolved_shapes if kind))
            class_names = list(dict.fromkeys(name for _, name in resolved_shapes if name))
            if len(primitive_kinds) == 1 and not class_names:
                return primitive_kinds[0], ""
            if len(class_names) == 1 and not primitive_kinds:
                return "", class_names[0]
            return "", ""

        if isinstance(expression, ast.Call):
            call_name = cls._call_expression_name(expression)
            if not call_name:
                return "", ""
            if call_name in {"bool", "dict", "list", "str", "tuple"}:
                return call_name, ""

            nested_ref = cls._nested_callable_ref(current_callable_ref, call_name)
            primitive_kinds, class_names = cls._resolved_callable_return_shapes(
                implementation_code,
                nested_ref,
                seen_callable_refs=seen_callable_refs,
            )
            if len(primitive_kinds) == 1 and not class_names:
                return primitive_kinds[0], ""
            if len(class_names) == 1 and not primitive_kinds:
                return "", class_names[0]

            if cls._implementation_class_field_names(implementation_code, call_name):
                return "", call_name

        return "", ""

    @classmethod
    def _resolved_callable_return_shapes(
        cls,
        implementation_code: object,
        callable_ref: str,
        *,
        seen_callable_refs: set[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        normalized_ref = cls._normalized_callable_ref(callable_ref)
        if not normalized_ref:
            return [], []

        current_seen_refs = set(seen_callable_refs or set())
        if normalized_ref in current_seen_refs:
            return [], []
        current_seen_refs.add(normalized_ref)

        callable_node = cls._implementation_callable_node(implementation_code, normalized_ref)
        if callable_node is None:
            return [], []

        resolved_shapes = [
            cls._resolve_return_expression_shape(
                implementation_code,
                normalized_ref,
                callable_node,
                child.value,
                seen_callable_refs=current_seen_refs,
            )
            for child in ast.walk(callable_node)
            if isinstance(child, ast.Return) and child.value is not None
        ]
        primitive_kinds = list(dict.fromkeys(kind for kind, _ in resolved_shapes if kind))
        class_names = list(dict.fromkeys(name for _, name in resolved_shapes if name))
        return primitive_kinds, class_names

    @classmethod
    def _implementation_class_field_names(cls, implementation_code: object, class_name: str) -> list[str]:
        tree = cls._parse_implementation_tree(implementation_code)
        if tree is None or not class_name:
            return []

        class_node: ast.ClassDef | None = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                class_node = node
                break
        if class_node is None:
            return []

        field_names: list[str] = []
        seen: set[str] = set()

        def append_field(name: str) -> None:
            normalized = name.strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            field_names.append(normalized)

        for child in class_node.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                append_field(child.target.id)
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        append_field(target.id)

        if field_names:
            return field_names

        for child in class_node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) or child.name != "__init__":
                continue
            for statement in ast.walk(child):
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        append_field(target.attr)
        return field_names

    @classmethod
    def _implementation_validation_result_shape(
        cls,
        implementation_code: object,
        validation_method: str,
    ) -> tuple[str, list[str]]:
        callable_node = cls._implementation_callable_node(implementation_code, validation_method)
        if callable_node is None:
            return "bool", []

        candidate_names: list[str] = []
        annotation_name = cls._annotation_name(callable_node.returns)
        if annotation_name:
            candidate_names.append(annotation_name)
        for child in ast.walk(callable_node):
            if not isinstance(child, ast.Return) or not isinstance(child.value, ast.Call):
                continue
            call_name = cls._call_expression_name(child.value)
            if call_name:
                candidate_names.append(call_name)

        seen: set[str] = set()
        for candidate_name in candidate_names:
            if candidate_name in seen:
                continue
            seen.add(candidate_name)
            if candidate_name == "bool":
                return "bool", []
            field_names = cls._implementation_class_field_names(implementation_code, candidate_name)
            if "is_valid" in field_names:
                return "object_is_valid", field_names
        return "bool", []

    @classmethod
    def _implementation_call_return_class_name(
        cls,
        implementation_code: object,
        callable_ref: str,
    ) -> str:
        callable_node = cls._implementation_callable_node(implementation_code, callable_ref)
        if callable_node is None:
            return ""

        primitive_kinds, class_names = cls._resolved_callable_return_shapes(
            implementation_code,
            callable_ref,
        )
        if len(class_names) == 1 and not primitive_kinds:
            return class_names[0]
        if primitive_kinds:
            return ""

        annotation_name = cls._annotation_name(callable_node.returns)
        if annotation_name and cls._implementation_class_field_names(implementation_code, annotation_name):
            return annotation_name

        for child in ast.walk(callable_node):
            if not isinstance(child, ast.Return) or not isinstance(child.value, ast.Call):
                continue
            call_name = cls._call_expression_name(child.value)
            if call_name and cls._implementation_class_field_names(implementation_code, call_name):
                return call_name
        return ""

    @staticmethod
    def _expression_primitive_kind(node: ast.AST | None) -> str:
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool):
                return "bool"
            if isinstance(value, int) and not isinstance(value, bool):
                return "int"
            if isinstance(value, float):
                return "float"
            if isinstance(value, str):
                return "str"
            if isinstance(value, dict):
                return "dict"
            if isinstance(value, list):
                return "list"
            if isinstance(value, tuple):
                return "tuple"
        if isinstance(node, ast.Dict):
            return "dict"
        if isinstance(node, ast.List):
            return "list"
        if isinstance(node, ast.Tuple):
            return "tuple"
        if isinstance(node, ast.IfExp):
            body_kind = QATesterAgent._expression_primitive_kind(node.body)
            orelse_kind = QATesterAgent._expression_primitive_kind(node.orelse)
            if body_kind and body_kind == orelse_kind:
                return body_kind
        return ""

    @classmethod
    def _implementation_call_return_primitive_kind(
        cls,
        implementation_code: object,
        callable_ref: str,
    ) -> str:
        callable_node = cls._implementation_callable_node(implementation_code, callable_ref)
        if callable_node is None:
            return ""

        primitive_kinds, class_names = cls._resolved_callable_return_shapes(
            implementation_code,
            callable_ref,
        )
        if len(primitive_kinds) == 1 and not class_names:
            return primitive_kinds[0]

        annotation_name = cls._annotation_name(callable_node.returns)
        if annotation_name in {"bool", "dict", "float", "int", "list", "str", "tuple"}:
            return annotation_name

        inferred_kinds: list[str] = []
        for child in ast.walk(callable_node):
            if not isinstance(child, ast.Return) or child.value is None:
                continue
            kind = cls._expression_primitive_kind(child.value)
            if kind:
                inferred_kinds.append(kind)

        unique_kinds = list(dict.fromkeys(inferred_kinds))
        if len(unique_kinds) == 1:
            return unique_kinds[0]
        return ""

    @classmethod
    def _service_audit_collection_info(
        cls,
        implementation_code: object,
        callable_ref: str,
    ) -> tuple[str, str]:
        tree = cls._parse_implementation_tree(implementation_code)
        if tree is None or not callable_ref:
            return "", ""

        normalized_ref, _ = cls._signature_name_and_params(callable_ref)
        normalized_ref = normalized_ref or callable_ref.strip()
        if "." not in normalized_ref:
            return "", ""
        class_name, _ = normalized_ref.split(".", 1)

        class_node: ast.ClassDef | None = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                class_node = node
                break
        if class_node is None:
            return "", ""

        for child in class_node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) or child.name != "__init__":
                continue
            for statement in child.body:
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if (
                        not isinstance(target, ast.Attribute)
                        or not isinstance(target.value, ast.Name)
                        or target.value.id != "self"
                        or "audit" not in target.attr.lower()
                    ):
                        continue
                    if isinstance(statement.value, ast.List):
                        return target.attr, "list"
                    if isinstance(statement.value, ast.Dict):
                        return target.attr, "dict"
        return "", ""

    @classmethod
    def _implementation_has_audit_record_request_id(cls, implementation_code: object) -> bool:
        for class_name in cls._module_defined_symbol_names(implementation_code):
            if "audit" not in class_name.lower():
                continue
            if "request_id" in cls._implementation_class_field_names(implementation_code, class_name):
                return True
        return False

    @classmethod
    def _implementation_result_mapping_field_keys(
        cls,
        implementation_code: object,
        class_name: str,
        field_name: str,
    ) -> list[str]:
        tree = cls._parse_implementation_tree(implementation_code)
        if tree is None or not class_name or not field_name:
            return []

        keys: list[str] = []
        seen: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = cls._call_expression_name(node)
            if call_name != class_name:
                continue
            for keyword in node.keywords:
                if keyword.arg != field_name or not isinstance(keyword.value, ast.Dict):
                    continue
                for key_node in keyword.value.keys:
                    if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                        continue
                    normalized = key_node.value.strip()
                    if not normalized or normalized in seen:
                        continue
                    seen.add(normalized)
                    keys.append(normalized)
        return keys

    @classmethod
    def _implementation_direct_mapping_return_keys(
        cls,
        implementation_code: object,
        callable_ref: str,
    ) -> list[str]:
        callable_node = cls._implementation_callable_node(implementation_code, callable_ref)
        if callable_node is None:
            return []

        common_key_set: set[str] | None = None
        ordered_keys: list[str] = []
        for child in ast.walk(callable_node):
            if not isinstance(child, ast.Return) or not isinstance(child.value, ast.Dict):
                continue

            current_keys: list[str] = []
            for key_node in child.value.keys:
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    continue
                normalized = key_node.value.strip()
                if normalized:
                    current_keys.append(normalized)
            if not current_keys:
                continue

            current_key_set = set(current_keys)
            if common_key_set is None:
                common_key_set = current_key_set
                ordered_keys = current_keys
            else:
                common_key_set &= current_key_set

        if not common_key_set:
            return []
        return [key for key in ordered_keys if key in common_key_set]

    @classmethod
    def _stable_direct_mapping_assertion_lines(
        cls,
        implementation_code: object,
        callable_ref: str,
        *,
        result_name: str,
        request_name: str,
    ) -> list[str]:
        if cls._implementation_call_return_primitive_kind(implementation_code, callable_ref) != "dict":
            return []

        mapping_keys = cls._implementation_direct_mapping_return_keys(implementation_code, callable_ref)
        lines = [f"assert isinstance({result_name}, dict)"]
        if "request_id" in mapping_keys and request_name:
            lines.append(f"assert {result_name}['request_id'] == {request_name}.request_id")
        for score_key in ("risk_score", "score"):
            if score_key in mapping_keys:
                lines.append(f"assert '{score_key}' in {result_name}")
                lines.append(f"assert {result_name}['{score_key}'] >= 0.0")
        for text_key in (
            "action",
            "action_type",
            "classification",
            "decision",
            "outcome",
            "priority",
            "result",
            "risk_level",
            "severity",
            "status",
        ):
            if text_key in mapping_keys:
                lines.append(f"assert '{text_key}' in {result_name}")
                lines.append(f"assert isinstance({result_name}['{text_key}'], str)")
        return list(dict.fromkeys(lines))

    @classmethod
    def _stable_direct_mapping_batch_assertion_lines(
        cls,
        implementation_code: object,
        callable_ref: str,
    ) -> list[str]:
        if cls._implementation_call_return_primitive_kind(implementation_code, callable_ref) != "dict":
            return []

        mapping_keys = cls._implementation_direct_mapping_return_keys(implementation_code, callable_ref)
        lines = [
            "assert len(results) == len(requests)",
            "assert all(isinstance(item, dict) for item in results)",
        ]
        if "request_id" in mapping_keys:
            lines.append("assert results[0]['request_id'] == requests[0].request_id")
            lines.append("assert results[-1]['request_id'] == requests[-1].request_id")
        for score_key in ("risk_score", "score"):
            if score_key in mapping_keys:
                lines.append(f"assert all('{score_key}' in item for item in results)")
                lines.append(f"assert all(item['{score_key}'] >= 0.0 for item in results)")
        for text_key in (
            "action",
            "action_type",
            "classification",
            "decision",
            "outcome",
            "priority",
            "result",
            "risk_level",
            "severity",
            "status",
        ):
            if text_key in mapping_keys:
                lines.append(
                    f"assert all('{text_key}' in item and isinstance(item['{text_key}'], str) for item in results)"
                )
        return list(dict.fromkeys(lines))

    @classmethod
    def _stable_result_assertion_lines(
        cls,
        implementation_code: object,
        callable_ref: str,
        *,
        result_name: str,
        request_name: str,
    ) -> list[str]:
        return_class_name = cls._implementation_call_return_class_name(implementation_code, callable_ref)
        if not return_class_name:
            return []

        field_names = cls._implementation_class_field_names(implementation_code, return_class_name)
        lines: list[str] = []
        if "request_id" in field_names and request_name:
            lines.append(f"assert {result_name}.request_id == {request_name}.request_id")
        if "risk_score" in field_names:
            lines.append(f"assert {result_name}.risk_score >= 0.0")
        elif "score" in field_names:
            lines.append(f"assert {result_name}.score >= 0.0")
        for text_field in ("action", "status", "result", "outcome", "decision"):
            if text_field in field_names:
                lines.append(f"assert isinstance({result_name}.{text_field}, str)")
        for mapping_field in ("details", "data", "metadata", "payload"):
            if mapping_field not in field_names:
                continue
            lines.append(f"assert isinstance({result_name}.{mapping_field}, dict)")
            mapping_keys = cls._implementation_result_mapping_field_keys(
                implementation_code,
                return_class_name,
                mapping_field,
            )
            if "risk_score" in mapping_keys:
                lines.append(f"assert 'risk_score' in {result_name}.{mapping_field}")
                lines.append(f"assert {result_name}.{mapping_field}['risk_score'] >= 0.0")
        if "audit_log" in field_names:
            lines.append(f"assert len({result_name}.audit_log) > 0")
        elif "audit_logs" in field_names:
            lines.append(f"assert len({result_name}.audit_logs) > 0")
        if "remediation_notes" in field_names:
            lines.append(f"assert {result_name}.remediation_notes is not None")
        return lines

    @classmethod
    def _stable_audit_assertion_lines(
        cls,
        implementation_code: object,
        callable_ref: str,
        *,
        service_name: str,
        request_name: str,
        batch: bool = False,
    ) -> list[str]:
        collection_name, collection_kind = cls._service_audit_collection_info(implementation_code, callable_ref)
        if not collection_name or not service_name:
            return []

        if batch:
            if collection_kind == "dict":
                return [f"assert all(request.request_id in {service_name}.{collection_name} for request in requests)"]

            lines = [f"assert len({service_name}.{collection_name}) >= len(requests)"]
            if cls._implementation_has_audit_record_request_id(implementation_code):
                lines.append(f"assert {service_name}.{collection_name}[0].request_id == requests[0].request_id")
                lines.append(f"assert {service_name}.{collection_name}[-1].request_id == requests[-1].request_id")
            return lines

        if collection_kind == "dict":
            return [f"assert {request_name}.request_id in {service_name}.{collection_name}"]

        lines = [f"assert len({service_name}.{collection_name}) == 1"]
        if cls._implementation_has_audit_record_request_id(implementation_code):
            lines.append(f"assert {service_name}.{collection_name}[-1].request_id == {request_name}.request_id")
        return lines

    @classmethod
    def _stable_call_assertion_lines(
        cls,
        implementation_code: object,
        callable_ref: str,
        *,
        result_name: str,
        request_name: str,
        service_name: str,
    ) -> list[str]:
        result_lines = cls._stable_result_assertion_lines(
            implementation_code,
            callable_ref,
            result_name=result_name,
            request_name=request_name,
        )
        if result_lines:
            return result_lines

        direct_mapping_lines = cls._stable_direct_mapping_assertion_lines(
            implementation_code,
            callable_ref,
            result_name=result_name,
            request_name=request_name,
        )
        if direct_mapping_lines:
            return direct_mapping_lines

        audit_lines = cls._stable_audit_assertion_lines(
            implementation_code,
            callable_ref,
            service_name=service_name,
            request_name=request_name,
        )

        primitive_return_kind = cls._implementation_call_return_primitive_kind(
            implementation_code,
            callable_ref,
        )
        if primitive_return_kind:
            return [f"assert isinstance({result_name}, {primitive_return_kind})", *audit_lines]

        if cls._implementation_call_returns_none(implementation_code, callable_ref):
            return ["assert result is None", *audit_lines]
        return audit_lines

    @classmethod
    def _stable_batch_result_assertion_lines(
        cls,
        implementation_code: object,
        callable_ref: str,
        *,
        runtime_return_kind: str = "",
    ) -> list[str]:
        if runtime_return_kind:
            return [
                "assert len(results) == len(requests)",
                f"assert all(isinstance(item, {runtime_return_kind}) for item in results)",
            ]

        direct_mapping_lines = cls._stable_direct_mapping_batch_assertion_lines(
            implementation_code,
            callable_ref,
        )
        if direct_mapping_lines:
            return direct_mapping_lines

        primitive_return_kind = cls._implementation_call_return_primitive_kind(
            implementation_code,
            callable_ref,
        )
        if primitive_return_kind:
            return [
                "assert len(results) == len(requests)",
                f"assert all(isinstance(item, {primitive_return_kind}) for item in results)",
            ]

        return_class_name = cls._implementation_call_return_class_name(implementation_code, callable_ref)
        if not return_class_name:
            return []

        field_names = cls._implementation_class_field_names(implementation_code, return_class_name)
        lines = ["assert len(results) == len(requests)"]
        if "request_id" in field_names:
            lines.append("assert results[0].request_id == requests[0].request_id")
            lines.append("assert results[-1].request_id == requests[-1].request_id")
        if "risk_score" in field_names:
            lines.append("assert all(item.risk_score >= 0.0 for item in results)")
        elif "score" in field_names:
            lines.append("assert all(item.score >= 0.0 for item in results)")
        for text_field in ("action", "status", "result", "outcome", "decision"):
            if text_field in field_names:
                lines.append(f"assert all(isinstance(item.{text_field}, str) for item in results)")
        for mapping_field in ("details", "data", "metadata", "payload"):
            if mapping_field not in field_names:
                continue
            lines.append(f"assert all(isinstance(item.{mapping_field}, dict) for item in results)")
            mapping_keys = cls._implementation_result_mapping_field_keys(
                implementation_code,
                return_class_name,
                mapping_field,
            )
            if "risk_score" in mapping_keys:
                lines.append(f"assert all('risk_score' in item.{mapping_field} for item in results)")
                lines.append(f"assert all(item.{mapping_field}['risk_score'] >= 0.0 for item in results)")
        if "audit_log" in field_names:
            lines.append("assert all(len(item.audit_log) > 0 for item in results)")
        return lines

    @staticmethod
    def _sample_literal_for_required_key(key: str) -> str:
        mapping = {
            "adverse_indicators": "1",
            "policy_id": '"policy123"',
            "claim_type": '"collision"',
            "amount": "5000",
            "customer_type": '"individual"',
            "evidence": '"photo"',
            "identity_evidence": "True",
            "jurisdiction": '"high-risk"',
            "loss_amount": "5000",
            "missing_documents": "0",
            "value": "500",
            "quantity": "1",
            "name": '"John Doe"',
            "documents": '["ID", "Passport"]',
            "request_id": '"request_id-1"',
            "details": '{"value": 1}',
            "data": '{"value": 1}',
            "metadata": '{"value": 1}',
            "payload": '{"value": 1}',
            "region": '"us_east"',
            "role": '"admin"',
            "request_type": '"screening"',
            "requester": '"analyst"',
            "service_category": '"IT Services"',
            "timestamp": "fixed_time",
            "vendor_id": '"V-001"',
        }
        return mapping.get(key.lower(), '"value"')

    @classmethod
    def _required_payload_argument_overrides(
        cls,
        signature: str,
        implementation_code: object,
    ) -> dict[str, str]:
        required_payload_keys = cls._implementation_required_payload_keys(implementation_code)
        if not required_payload_keys:
            return {}

        payload_parameter_names = cls._payload_like_parameter_names(signature)
        if not payload_parameter_names:
            return {}

        payload_literal = "{" + ", ".join(
            f'"{key}": {cls._sample_literal_for_required_key(key)}'
            for key in required_payload_keys
        ) + "}"
        return {payload_parameter_names[0]: payload_literal}

    @classmethod
    def _validation_failure_argument_overrides(
        cls,
        signature: str,
        implementation_code: object,
    ) -> dict[str, str]:
        overrides: dict[str, str] = {}
        payload_parameter_names = cls._payload_like_parameter_names(signature)
        required_payload_keys = cls._implementation_required_payload_keys(implementation_code)
        non_validation_payload_keys = cls._implementation_non_validation_payload_keys(implementation_code)
        omitted_key = cls._validation_failure_omitted_payload_key(implementation_code)

        if payload_parameter_names and required_payload_keys:
            retained_keys = [key for key in required_payload_keys if key != omitted_key]
            retained_keys.extend(
                key
                for key in non_validation_payload_keys
                if key not in retained_keys and key != omitted_key
            )
            if retained_keys:
                rendered_items = ", ".join(
                    f'"{key}": {cls._sample_literal_for_required_key(key)}'
                    for key in retained_keys
                )
                payload_literal = "{" + rendered_items + "}"
            else:
                payload_literal = "{}"
            overrides[payload_parameter_names[0]] = payload_literal

        if cls._implementation_prefers_direct_datetime_import(implementation_code):
            for name in cls._datetime_like_parameter_names(signature):
                overrides.setdefault(name, "fixed_time")

        return overrides

    @classmethod
    def _validation_failure_omitted_payload_key(cls, implementation_code: object) -> str:
        required_payload_keys = cls._implementation_required_payload_keys(implementation_code)
        if not required_payload_keys:
            return ""
        if "documents" in required_payload_keys:
            return "documents"
        return required_payload_keys[-1]

    @classmethod
    def _validation_failure_missing_request_field(cls, implementation_code: object) -> str:
        required_request_fields = cls._implementation_required_request_fields(implementation_code)
        if not required_request_fields:
            return ""
        if "timestamp" in required_request_fields:
            return "timestamp"
        return required_request_fields[-1]

    @classmethod
    def _validation_failure_request_like_object_scaffold_line(
        cls,
        implementation_code: object,
    ) -> tuple[str, str]:
        required_request_fields = cls._implementation_required_request_fields(implementation_code)
        missing_field = cls._validation_failure_missing_request_field(implementation_code)
        if not required_request_fields or not missing_field:
            return "", ""

        rendered_items = ", ".join(
            f'"{field}": {cls._sample_literal_for_required_key(field)}'
            for field in required_request_fields
            if field != missing_field
        )
        if not rendered_items:
            return "", ""
        return (
            "invalid_request",
            f'invalid_request = type("InvalidRequest", (), {{{rendered_items}}})()',
        )

    @staticmethod
    def _implementation_raises_value_error(implementation_code: object) -> bool:
        return isinstance(implementation_code, str) and bool(re.search(r"raise\s+ValueError\b", implementation_code))

    @classmethod
    def _implementation_call_returns_none(cls, implementation_code: object, callable_ref: str) -> bool:
        if not isinstance(implementation_code, str) or not implementation_code.strip() or not callable_ref:
            return False

        try:
            tree = ast.parse(implementation_code)
        except SyntaxError:
            return False

        normalized_ref, _ = cls._signature_name_and_params(callable_ref)
        normalized_ref = normalized_ref or callable_ref.strip()

        target_class = ""
        target_name = normalized_ref
        if "." in normalized_ref:
            target_class, target_name = normalized_ref.split(".", 1)

        if target_class:
            for node in tree.body:
                if not isinstance(node, ast.ClassDef) or node.name != target_class:
                    continue
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == target_name:
                        return cls._function_returns_only_none(child)
            return False

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_name:
                return cls._function_returns_only_none(node)
        return False

    @classmethod
    def _function_returns_only_none(cls, function_node: ast.AST) -> bool:
        if not isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False

        def iter_returns(node: ast.AST) -> list[ast.Return]:
            returns: list[ast.Return] = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Return):
                    returns.append(child)
                    continue
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                returns.extend(iter_returns(child))
            return returns

        return_nodes = iter_returns(function_node)
        if not return_nodes:
            return True
        return all(
            return_node.value is None
            or (
                isinstance(return_node.value, ast.Constant)
                and return_node.value.value is None
            )
            for return_node in return_nodes
        )

    @staticmethod
    def _call_expression_without_assignment(call_line: str) -> str:
        if call_line.startswith("result = "):
            return call_line.split(" = ", 1)[1]
        if call_line.startswith("is_valid = "):
            return call_line.split(" = ", 1)[1]
        return call_line

    @staticmethod
    def _runtime_return_kind_from_summary(repair_validation_summary: object) -> str:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return ""
        match = re.search(
            r"exact return-shape attribute assumption \('\.[^']+' on '([^']+)'\)",
            repair_validation_summary,
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        runtime_type = match.group(1)
        runtime_assertion_map = {
            "bool": "bool",
            "dict": "dict",
            "float": "float",
            "int": "int",
            "list": "list",
            "NoneType": "type(None)",
            "str": "str",
            "tuple": "tuple",
        }
        assertion_type = runtime_assertion_map.get(runtime_type)
        if not assertion_type:
            return ""
        return assertion_type

    @classmethod
    def _return_shape_assertion_line(cls, repair_validation_summary: object) -> str:
        runtime_return_kind = cls._runtime_return_kind_from_summary(repair_validation_summary)
        if not runtime_return_kind:
            return ""
        return f"assert isinstance(result, {runtime_return_kind})"

    @staticmethod
    def _validation_support_method(exact_methods: list[str], preferred_facades: list[str]) -> str:
        for facade in preferred_facades:
            for method in exact_methods:
                if method.startswith(f"{facade}.") and ".validate" in method:
                    return method
        return next((method for method in exact_methods if ".validate" in method), "")

    @classmethod
    def _payload_like_parameter_names(cls, signature: str) -> list[str]:
        _, parameters = cls._signature_name_and_params(signature)
        names: list[str] = []
        for parameter in parameters:
            parameter_name = cls._parameter_name(parameter)
            if not parameter_name:
                continue
            lowered = parameter_name.lower()
            if lowered in {
                "details",
                "detail",
                "data",
                "payload",
                "metadata",
                "meta",
                "attributes",
                "context",
                "request_data",
                "document_data",
            } or lowered.endswith(("_details", "_data", "_payload", "_metadata")):
                names.append(parameter_name)
        return names

    @classmethod
    def _required_evidence_argument_overrides(
        cls,
        signature: str,
        implementation_code: object,
    ) -> dict[str, str]:
        required_evidence_items = cls._implementation_required_evidence_items(implementation_code)
        if not required_evidence_items:
            return {}

        required_payload_keys = cls._implementation_required_payload_keys(implementation_code)
        if set(required_evidence_items).issubset(set(required_payload_keys)):
            return {}

        payload_literal = "{'documents': " + repr(required_evidence_items) + "}"
        return {
            parameter_name: payload_literal
            for parameter_name in cls._payload_like_parameter_names(signature)
        }

    @classmethod
    def _content_has_incomplete_required_evidence_payload(
        cls,
        content: object,
        implementation_code: object,
    ) -> bool:
        required_evidence_items = cls._implementation_required_evidence_items(implementation_code)
        if len(required_evidence_items) <= 1:
            return False
        if not isinstance(content, str) or not content.strip():
            return False

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return False

        required_evidence_set = set(required_evidence_items)
        required_payload_keys = set(cls._implementation_required_payload_keys(implementation_code))
        top_level_required_evidence = required_evidence_set & required_payload_keys
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not cls._test_function_targets_valid_processing(node):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Dict):
                    continue
                dict_keys = {
                    key.value
                    for key in child.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
                if top_level_required_evidence and dict_keys & top_level_required_evidence:
                    if not top_level_required_evidence.issubset(dict_keys):
                        return True
                document_items: list[str] | None = None
                for key, value in zip(child.keys, child.values):
                    if isinstance(key, ast.Constant) and key.value == "documents":
                        document_items = cls._string_literal_sequence(value)
                        break
                if document_items is None:
                    continue
                if not required_evidence_set.issubset(set(document_items)):
                    return True
        return False

    @classmethod
    def _summary_has_required_evidence_runtime_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
        implementation_code: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False

        summary_lower = repair_validation_summary.lower()
        if "pytest execution: fail" not in summary_lower and "pytest failure details:" not in summary_lower:
            return False
        has_numeric_audit_mismatch = any(
            int(actual_count) < int(expected_count)
            for actual_count, expected_count in re.findall(r"assert\s+(\d+)\s*==\s*(\d+)", summary_lower)
        )
        has_required_evidence_failure = any(
            marker in summary_lower
            for marker in (
                "missing required documents",
                "missing required evidence",
            )
        )
        if not has_numeric_audit_mismatch and not has_required_evidence_failure:
            return False
        return cls._content_has_incomplete_required_evidence_payload(content, implementation_code)

    @classmethod
    def _content_has_incomplete_required_payload_for_valid_paths(
        cls,
        content: object,
        implementation_code: object,
    ) -> bool:
        required_payload_keys = cls._implementation_required_payload_keys(implementation_code)
        if not required_payload_keys:
            return False
        if not isinstance(content, str) or not content.strip():
            return False

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return False

        required_payload_set = set(required_payload_keys)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not cls._test_function_targets_valid_processing(node):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Dict):
                    continue
                dict_keys = {
                    key.value
                    for key in child.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
                if not dict_keys or not (dict_keys & required_payload_set):
                    continue
                if not required_payload_set.issubset(dict_keys):
                    return True
        return False

    @classmethod
    def _summary_has_required_payload_runtime_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
        implementation_code: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False

        summary_lower = repair_validation_summary.lower()
        if "pytest execution: fail" not in summary_lower and "pytest failure details:" not in summary_lower:
            return False
        if not any(
            marker in summary_lower
            for marker in (
                "missing required",
                "validationerror",
                "valueerror",
            )
        ):
            return False
        return cls._content_has_incomplete_required_payload_for_valid_paths(content, implementation_code)

    @classmethod
    def _implementation_has_presence_only_required_field_validation(
        cls,
        implementation_code: object,
    ) -> bool:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return False

        try:
            tree = ast.parse(implementation_code)
        except SyntaxError:
            return False

        validate_nodes: list[ast.AST] = []
        for module_node in tree.body:
            if isinstance(module_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and module_node.name.startswith("validate"):
                validate_nodes.append(module_node)
            elif isinstance(module_node, ast.ClassDef):
                for class_child in module_node.body:
                    if isinstance(class_child, (ast.FunctionDef, ast.AsyncFunctionDef)) and class_child.name.startswith("validate"):
                        validate_nodes.append(class_child)

        for validate_node in validate_nodes:
            required_field_names: dict[str, list[str]] = {}
            has_required_field_names = False
            presence_checks = False
            type_checks = False
            payload_alias_names = cls._function_payload_alias_names(validate_node)
            for child in ast.walk(validate_node):
                target_names: list[str] = []
                value_node: ast.AST | None = None
                if isinstance(child, ast.Assign):
                    target_names = [target.id for target in child.targets if isinstance(target, ast.Name)]
                    value_node = child.value
                elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    target_names = [child.target.id]
                    value_node = child.value

                if any(cls._is_required_field_collection_name(name) for name in target_names):
                    string_items = cls._string_literal_sequence(value_node)
                    if string_items:
                        has_required_field_names = True
                        for name in target_names:
                            if cls._is_required_field_collection_name(name):
                                required_field_names[name] = string_items

                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "issubset":
                    if cls._is_request_field_container_expression(child.args[0]) or cls._is_payload_container_expression(
                        child.args[0],
                        payload_alias_names,
                    ):
                        presence_checks = True

                field_names, container_node = cls._all_membership_required_names(child, required_field_names)
                if field_names and (
                    cls._is_request_field_container_expression(container_node)
                    or cls._is_payload_container_expression(container_node, payload_alias_names)
                ):
                    presence_checks = True

                if isinstance(child, ast.Compare) and len(child.comparators) == 1:
                    if any(isinstance(op, ast.NotIn) for op in child.ops):
                        if cls._is_request_field_container_expression(child.comparators[0]) or cls._is_payload_container_expression(
                            child.comparators[0],
                            payload_alias_names,
                        ):
                            presence_checks = True

                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "isinstance":
                    type_checks = True

            if has_required_field_names and presence_checks and not type_checks:
                return True

        return False

    @staticmethod
    def _block_mentions_all_required_payload_keys(block: str, required_payload_keys: list[str]) -> bool:
        if not block.strip() or not required_payload_keys:
            return False
        return all(
            re.search(rf"['\"]{re.escape(key)}['\"]\s*:", block) is not None
            for key in required_payload_keys
        )

    @classmethod
    def _summary_has_presence_only_validation_sample_issue(
        cls,
        repair_validation_summary: object,
        content: object = "",
        implementation_code: object = "",
    ) -> bool:
        if not isinstance(repair_validation_summary, str) or not repair_validation_summary.strip():
            return False

        summary_lower = repair_validation_summary.lower()
        has_validation_false_signal = (
            "assert true is false" in summary_lower
            or "assert not true" in summary_lower
            or "did not raise" in summary_lower
        )
        if not has_validation_false_signal:
            return False

        required_payload_keys = cls._implementation_required_payload_keys(implementation_code)
        if not required_payload_keys:
            return False

        block = cls._test_function_block(content, "test_validation_failure")
        if not block:
            return False

        block_lower = block.lower()
        if "validate_request(" not in block_lower and "pytest.raises" not in block_lower:
            return False

        return cls._block_mentions_all_required_payload_keys(block, required_payload_keys)

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
    def _merge_preserving_order(*groups: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for item in group:
                if not isinstance(item, str):
                    continue
                normalized = item.strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                merged.append(normalized)
        return merged

    @staticmethod
    def _module_defined_symbol_names(implementation_code: object) -> list[str]:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return []
        try:
            tree = ast.parse(implementation_code)
        except SyntaxError:
            return []

        names: list[str] = []
        seen: set[str] = set()
        for node in tree.body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in seen:
                continue
            seen.add(node.name)
            names.append(node.name)
        return names

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
If the module already imports `from datetime import datetime` and the suite needs a typed timestamp, match that style and prefer a local fixed value such as `fixed_time = datetime(2024, 1, 1, 0, 0, 0)` over repeating `datetime.now()` directly inside constructor arguments.
Pass every documented constructor field explicitly, including timestamp when it is listed.
If no dedicated batch helper is documented, keep batch coverage on the documented single-request surface by looping over valid inputs instead of inventing renamed helpers.
Stay on the main service facade; do not add helper-only imports or helper-only tests.
Record-shaped value models such as AuditLog, RiskScore, ResultRecord, or similar typed data holders are not service collaborators unless the exact contract explicitly says so. Do not replace an undefined helper alias with a similarly named record type just because it imports cleanly.
When the suite already contains a dedicated validation-failure test, do not reuse that invalid payload inside test_batch_processing or any other supposedly valid batch scenario. Keep every batch item fully valid unless the behavior contract explicitly documents partial batch failure handling.
Do not add duplicate-detection, risk-tier, audit-only, or helper-only tests unless the exact contract or behavior contract explicitly requires them.
Keep the suite under the stated line, fixture, and top-level-test caps.
Avoid guessed exact score totals, guessed derived labels, and guessed exact audit lengths unless the behavior contract explicitly defines them.
Avoid guessed exact response.status labels and guessed exact risk-summary bucket totals for batch items unless the behavior contract or current implementation explicitly defines those triggers.
Avoid guessed exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests unless the behavior contract or current implementation explicitly defines those triggers.
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
    def _constructor_scaffold_line_with_overrides(
        cls,
        signature: str,
        *,
        argument_overrides: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        class_name, constructor_expr = cls._constructor_call_expression(
            signature,
            argument_overrides=argument_overrides,
        )
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
        argument_overrides: dict[str, str] | None = None,
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
            override_value = (argument_overrides or {}).get(parameter_name)
            if override_value is not None:
                arguments.append(f"{parameter_name}={override_value}")
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
        argument_overrides: dict[str, str] | None = None,
        collect_results: bool = False,
    ) -> list[str]:
        if "." not in primary_method or not preferred_constructor:
            return []

        class_name, method_name = primary_method.split(".", 1)
        service_name = cls._instance_name_for_class(class_name)
        _, first_request_expr = cls._constructor_call_expression(
            preferred_constructor,
            index_offset=0,
            argument_overrides=argument_overrides,
        )
        _, second_request_expr = cls._constructor_call_expression(
            preferred_constructor,
            index_offset=1,
            argument_overrides=argument_overrides,
        )
        if not first_request_expr or not second_request_expr:
            return []

        lines = [
            f"{service_name} = {class_name}()",
            "requests = [",
            f"    {first_request_expr},",
            f"    {second_request_expr},",
            "]",
        ]
        if collect_results:
            lines.append("results = []")
        lines.extend([
            "for request in requests:",
            f"    result = {service_name}.{method_name}(request)",
        ])
        if collect_results:
            lines.append("    results.append(result)")
        return lines

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

        class_name, raw_method_name = method_ref.split(".", 1)
        method_name, _ = cls._signature_name_and_params(raw_method_name)
        method_name = method_name or raw_method_name.strip()
        service_name = cls._instance_name_for_class(class_name)
        service_line = f"{service_name} = {class_name}()"

        if constructor_variable:
            argument = f"[{constructor_variable}]" if "batch" in method_name.lower() else constructor_variable
            return service_line, f"result = {service_name}.{method_name}({argument})"
        if "batch" in method_name.lower():
            return service_line, f"result = {service_name}.{method_name}(...)"
        return service_line, f"result = {service_name}.{method_name}()"

    @classmethod
    def _fixed_time_expression(cls, implementation_code: object) -> str:
        module_style = cls._implementation_prefers_datetime_module_import(implementation_code)
        if cls._implementation_requires_recent_request_timestamp(implementation_code):
            if cls._implementation_prefers_timezone_aware_now(implementation_code):
                if module_style:
                    return "datetime.datetime.now(datetime.timezone.utc)"
                return "datetime.now(timezone.utc)"
            if module_style:
                return "datetime.datetime.now()"
            return "datetime.now()"
        if module_style:
            return "datetime.datetime(2024, 1, 1, 0, 0, 0)"
        return "datetime(2024, 1, 1, 0, 0, 0)"

    @classmethod
    def _fixed_time_import_line(cls, implementation_code: object) -> str:
        if cls._implementation_prefers_datetime_module_import(implementation_code):
            return "import datetime"
        if cls._implementation_requires_recent_request_timestamp(implementation_code) and cls._implementation_prefers_timezone_aware_now(implementation_code):
            return "from datetime import datetime, timezone"
        return "from datetime import datetime"

    @classmethod
    def _fixed_time_assignment_line(cls, implementation_code: object) -> str:
        return f"fixed_time = {cls._fixed_time_expression(implementation_code)}"

    @classmethod
    def _prepend_fixed_time_line(cls, lines: list[str], *, implementation_code: object = "") -> list[str]:
        if not any("fixed_time" in line for line in lines):
            return lines
        if any(
            line.startswith("fixed_time = datetime(") or line.startswith("fixed_time = datetime.now(")
            for line in lines
        ):
            return lines
        insert_at = 1 if lines and lines[0].startswith("service =") else 0
        return [
            *lines[:insert_at],
            cls._fixed_time_assignment_line(implementation_code),
            *lines[insert_at:],
        ]

    @classmethod
    def _deterministic_surface_scaffold_block(
        cls,
        *,
        module_name: str,
        task_description: str,
        code_exact_test_contract: object,
        code_test_targets: object,
        task_public_contract_anchor: object,
        implementation_code: object = "",
        repair_validation_summary: object = "",
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
            allowed_imports = cls._merge_preserving_order(
                cls._string_list(anchor_overrides.get("allowed_imports")),
                allowed_imports,
            ) or allowed_imports
            preferred_facades = cls._string_list(anchor_overrides.get("preferred_facades")) or preferred_facades
            exact_callables = []
            exact_methods = cls._string_list(anchor_overrides.get("exact_methods")) or exact_methods
            exact_constructors = cls._merge_preserving_order(
                cls._string_list(anchor_overrides.get("exact_constructors")),
                exact_constructors,
            ) or exact_constructors

        preferred_constructor = cls._preferred_constructor_signature(exact_constructors, preferred_facades)
        preferred_constructor_name, _ = cls._signature_name_and_params(preferred_constructor)
        argument_overrides = cls._required_payload_argument_overrides(
            preferred_constructor,
            implementation_code,
        )
        argument_overrides.update(cls._required_evidence_argument_overrides(
            preferred_constructor,
            implementation_code,
        ))
        if cls._implementation_prefers_direct_datetime_import(implementation_code):
            argument_overrides.update({
                name: "fixed_time" for name in cls._datetime_like_parameter_names(preferred_constructor)
            })
        constructor_variable, constructor_line = cls._constructor_scaffold_line_with_overrides(
            preferred_constructor,
            argument_overrides=argument_overrides,
        )

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
        primary_surface_ref = primary_method or primary_callable
        primary_returns_none = cls._implementation_call_returns_none(
            implementation_code,
            primary_surface_ref,
        )
        return_shape_assertion_line = cls._return_shape_assertion_line(repair_validation_summary)
        runtime_return_kind = cls._runtime_return_kind_from_summary(repair_validation_summary)
        primary_service_name = ""
        if primary_method and "." in primary_method:
            primary_service_name = cls._instance_name_for_class(primary_method.split(".", 1)[0])
        primary_stable_assertion_lines: list[str] = []
        if call_line.startswith("result = "):
            primary_stable_assertion_lines = cls._stable_call_assertion_lines(
                implementation_code,
                primary_surface_ref,
                result_name="result",
                request_name=constructor_variable,
                service_name=primary_service_name,
            )

        validation_body_lines: list[str] = []
        validation_omitted_payload_key = cls._validation_failure_omitted_payload_key(implementation_code)
        validation_missing_request_field = cls._validation_failure_missing_request_field(implementation_code)
        non_validation_payload_keys = cls._implementation_non_validation_payload_keys(implementation_code)
        validation_method = cls._validation_support_method(exact_methods, preferred_facades)
        validation_result_kind = "bool"
        validation_result_fields: list[str] = []
        if validation_method:
            validation_result_kind, validation_result_fields = cls._implementation_validation_result_shape(
                implementation_code,
                validation_method,
            )
        primary_body_lines = [line for line in (service_line, constructor_line) if line]
        if call_line:
            primary_body_lines.append(call_line)
        if return_shape_assertion_line and call_line.startswith("result = "):
            primary_body_lines.append(return_shape_assertion_line)
        elif call_line.startswith("result = "):
            primary_body_lines.extend(primary_stable_assertion_lines)

        validation_constructor_variable = ""
        validation_constructor_line = ""
        if preferred_constructor and (primary_method or primary_callable):
            if not validation_omitted_payload_key:
                validation_constructor_variable, validation_constructor_line = cls._validation_failure_request_like_object_scaffold_line(
                    implementation_code,
                )
            if not validation_constructor_variable or not validation_constructor_line:
                validation_overrides = cls._validation_failure_argument_overrides(
                    preferred_constructor,
                    implementation_code,
                )
                validation_constructor_variable, validation_constructor_line = cls._constructor_scaffold_line_with_overrides(
                    preferred_constructor,
                    argument_overrides=validation_overrides,
                )
            validation_service_line = service_line
            validation_call_line = ""
            if primary_method:
                validation_service_line, validation_call_line = cls._method_scaffold_lines(
                    primary_method,
                    validation_constructor_variable,
                )
            elif primary_callable:
                validation_call_line = cls._callable_scaffold_line(
                    primary_callable,
                    validation_constructor_variable,
                )

            validation_body_lines = [line for line in (validation_service_line, validation_constructor_line) if line]
            if validation_method and "." in validation_method:
                validation_owner, raw_validation_method_name = validation_method.split(".", 1)
                validation_method_name, _ = cls._signature_name_and_params(raw_validation_method_name)
                validation_method_name = validation_method_name or raw_validation_method_name.strip()
                validation_service_name = cls._instance_name_for_class(validation_owner)
                validation_service_assignment = f"{validation_service_name} = {validation_owner}()"
                if validation_body_lines and validation_body_lines[0] != validation_service_assignment:
                    validation_body_lines.insert(0, validation_service_assignment)
                elif not validation_body_lines:
                    validation_body_lines.append(validation_service_assignment)
                if validation_result_kind == "object_is_valid":
                    validation_body_lines.append(
                        f"validation = {validation_service_name}.{validation_method_name}({validation_constructor_variable})"
                    )
                    validation_body_lines.append("assert validation.is_valid is False")
                    if "errors" in validation_result_fields:
                        validation_body_lines.append("assert len(validation.errors) > 0")
                else:
                    validation_body_lines.append(
                        f"is_valid = {validation_service_name}.{validation_method_name}({validation_constructor_variable})"
                    )
                    validation_body_lines.append("assert is_valid is False")

            validation_call_expression = cls._call_expression_without_assignment(validation_call_line)
            validation_stable_assertion_lines: list[str] = []
            if validation_call_line.startswith("result = "):
                validation_stable_assertion_lines = cls._stable_call_assertion_lines(
                    implementation_code,
                    primary_surface_ref,
                    result_name="result",
                    request_name=validation_constructor_variable,
                    service_name=primary_service_name,
                )
            if validation_call_expression:
                if cls._implementation_raises_value_error(implementation_code):
                    validation_body_lines.append("with pytest.raises(ValueError):")
                    validation_body_lines.append(f"    {validation_call_expression}")
                elif validation_call_line.startswith("result = ") and validation_stable_assertion_lines:
                    validation_body_lines.append(validation_call_line)
                    validation_body_lines.extend(validation_stable_assertion_lines)
                else:
                    validation_body_lines.append(validation_call_expression)

        batch_body_lines = [line for line in (service_line, constructor_line, batch_call_line) if line]
        batch_surface_ref = batch_method or batch_callable
        batch_returns_none = cls._implementation_call_returns_none(
            implementation_code,
            batch_surface_ref,
        )
        if batch_returns_none and batch_call_line.startswith("result = "):
            batch_body_lines.append("assert result is None")
        batch_collects_results = False
        if batch_requested and not batch_call_line and primary_method and preferred_constructor:
            batch_audit_assertion_lines = cls._stable_audit_assertion_lines(
                implementation_code,
                primary_surface_ref,
                service_name=primary_service_name,
                request_name="request",
                batch=True,
            )
            batch_collects_results = bool(
                cls._implementation_call_return_class_name(
                    implementation_code,
                    primary_surface_ref,
                )
                or cls._implementation_call_return_primitive_kind(
                    implementation_code,
                    primary_surface_ref,
                )
            )
            if not batch_collects_results and primary_returns_none and not batch_audit_assertion_lines:
                batch_collects_results = True
            batch_body_lines = cls._batch_loop_scaffold_lines(
                primary_method=primary_method,
                preferred_constructor=preferred_constructor,
                argument_overrides=argument_overrides,
                collect_results=batch_collects_results,
            )
            if batch_collects_results:
                if primary_returns_none:
                    batch_body_lines.extend([
                        "assert len(results) == len(requests)",
                        "assert all(item is None for item in results)",
                    ])
                else:
                    batch_body_lines.extend(
                        cls._stable_batch_result_assertion_lines(
                            implementation_code,
                            primary_surface_ref,
                            runtime_return_kind=runtime_return_kind,
                        )
                    )
            else:
                batch_body_lines.extend(batch_audit_assertion_lines)
        primary_body_lines = cls._prepend_fixed_time_line(
            primary_body_lines,
            implementation_code=implementation_code,
        )
        validation_body_lines = cls._prepend_fixed_time_line(
            validation_body_lines,
            implementation_code=implementation_code,
        )
        batch_body_lines = cls._prepend_fixed_time_line(
            batch_body_lines,
            implementation_code=implementation_code,
        )
        body_lines = [*primary_body_lines, *validation_body_lines, *batch_body_lines]
        if not allowed_imports and not body_lines:
            return ""

        lines = [
            "",
            "Deterministic pytest scaffold anchor:",
            "Copy this exact import and test-safe surface shape. Change only literal values when the task requires it.",
            "```python",
            "import pytest",
        ]
        if any("fixed_time" in line for line in body_lines):
            lines.append(cls._fixed_time_import_line(implementation_code))
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
            if validation_body_lines:
                lines.append("")
                lines.append("def test_validation_failure():")
                seen_validation_lines: set[str] = set()
                for line in validation_body_lines:
                    if line in seen_validation_lines:
                        continue
                    seen_validation_lines.add(line)
                    if line.startswith("    "):
                        lines.append(f"    {line}")
                    else:
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
            "- Treat the scaffold body above as authoritative. Keep its payload shape and assertion style unless the exact contract explicitly requires a different literal or an extra check."
        )
        lines.append(
            "- Keep mutable services and request objects local to each test or a local helper. Do not lift them to module scope."
        )
        if cls._implementation_requires_recent_request_timestamp(implementation_code):
            recent_fixed_time_expr = f"`{cls._fixed_time_expression(implementation_code)}`"
            lines.append(
                "- The implementation validates request timestamp recency. In happy-path, batch, and risk-scoring scenarios, keep `fixed_time` recent enough to pass validation; "
                f"prefer {recent_fixed_time_expr} over a stale historical calendar literal."
            )
        lines.append(
            "- In compact contract-first mode, default to only the required trio: happy path, validation failure, and batch processing. Do not add duplicate-detection, risk-tier, audit-only, or other speculative extras unless the exact contract explicitly requires them."
        )
        if validation_body_lines:
            lines.append(
                "- If `test_validation_failure` later asserts audit records, risk-score state, or another workflow side effect, keep the documented workflow call in that test. `validate_request(...)` alone only checks validity; it does not emit workflow side effects by itself."
            )
            lines.append(
                "- Do not replace the scaffolded validation-failure payload with an empty dict, an omitted optional scoring field, or another guessed business-rule variation when the scaffold already shows an exact rejection case."
            )
            if validation_omitted_payload_key:
                lines.append(
                    "- In `test_validation_failure`, keep the scaffolded omission of the required payload key "
                    f"`{validation_omitted_payload_key}` exactly as shown. Do not swap that missing key to a different field."
                )
                if validation_constructor_line:
                    lines.append(
                        "- In `test_validation_failure`, keep the scaffolded invalid constructor line exactly as shown: "
                        f"`{validation_constructor_line}`. Do not reintroduce `{validation_omitted_payload_key}` with a placeholder literal."
                    )
                if non_validation_payload_keys:
                    rendered_keys = ", ".join(f"`{key}`" for key in non_validation_payload_keys[:3])
                    lines.append(
                        "- Do not swap that missing-field case to optional downstream business keys such as "
                        f"{rendered_keys}. Those keys are only read after validation in scoring or review logic here, so omitting them may change risk but should not be used as the `validate_request(...)` rejection case."
                    )
            elif validation_missing_request_field:
                request_model_constructor_hint = (
                    f"`{preferred_constructor_name}(...)`"
                    if preferred_constructor_name
                    else "`the request-model constructor`"
                )
                lines.append(
                    "- The current validator checks top-level request fields on the request object rather than nested payload keys. "
                    f"In `test_validation_failure`, keep the scaffolded request-like object missing the top-level field `{validation_missing_request_field}` exactly as shown. "
                    f"Do not instantiate {request_model_constructor_hint} anywhere in that test, including placeholder cases such as `details={{}}` or other fully populated constructor calls, and do not move request wrapper fields such as request_id, request_type, details, or timestamp into the nested payload dict to fabricate that rejection case. A request-model instance that still supplies all top-level fields remains valid here."
                )
                if validation_constructor_line:
                    lines.append(
                        "- In `test_validation_failure`, keep the scaffolded invalid-object line exactly as shown: "
                        f"`{validation_constructor_line}`. Reuse that same `invalid_request` object for both `validate_request(...)` and the workflow call."
                    )
                lines.append(
                    f"- Do not rewrite that missing-field case as `{validation_missing_request_field}=None`, an empty string, or another placeholder value. For this validator the field must be absent from the object entirely, not merely present with a falsey value."
                )
        if preferred_facades:
            lines.append(
                f"- Keep the suite centered on {', '.join(preferred_facades)} instead of auxiliary helpers."
            )
        if any("audit_" in line or ".audit_" in line or "audit_history" in line for line in body_lines):
            lines.append(
                "- Keep the scaffold's request-identity and audit-growth checks. Do not swap them for exact blocked, escalated, rejected, approved, or similar label guesses unless the behavior contract explicitly defines that mapping."
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
        existing_tests: object = "",
        implementation_code: object = "",
    ) -> bool:
        if not isinstance(code_exact_test_contract, str) or not code_exact_test_contract.strip():
            return False
        available_module_symbol_names = cls._undefined_available_module_symbol_names(
            implementation_code,
            repair_validation_summary,
        )
        required_evidence_runtime_issue = cls._summary_has_required_evidence_runtime_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        required_payload_runtime_issue = cls._summary_has_required_payload_runtime_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        required_request_fields = cls._implementation_required_request_fields(implementation_code)
        exact_status_action_label_issue = cls._summary_has_exact_status_action_label_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        exact_band_label_issue = cls._summary_has_exact_band_label_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        exact_temporal_value_issue = cls._summary_has_exact_temporal_value_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        exact_numeric_score_issue = cls._summary_has_exact_numeric_score_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        positive_numeric_score_issue = cls._summary_has_positive_numeric_score_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        presence_only_validation_sample_issue = cls._summary_has_presence_only_validation_sample_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        if cls._undefined_helper_alias_names_outside_exact_contract(
            code_exact_test_contract,
            repair_validation_summary,
            implementation_code,
        ):
            return True
        if cls._summary_has_missing_datetime_import_issue(repair_validation_summary) and not available_module_symbol_names:
            return True
        if required_evidence_runtime_issue and not available_module_symbol_names:
            return True
        if required_payload_runtime_issue and not available_module_symbol_names:
            return True
        if required_request_fields and not cls._implementation_required_payload_keys(implementation_code) and not available_module_symbol_names:
            return True
        if presence_only_validation_sample_issue:
            return True
        if cls._summary_has_placeholder_boolean_assertion_issue(
            repair_validation_summary,
            existing_tests,
        ):
            return True
        if cls._summary_has_validation_side_effect_without_workflow_call_issue(
            repair_validation_summary,
            existing_tests,
        ):
            return True
        if exact_status_action_label_issue:
            return True
        if exact_band_label_issue:
            return True
        if exact_temporal_value_issue:
            return True
        if exact_numeric_score_issue:
            return True
        if positive_numeric_score_issue:
            return True
        if cls._summary_has_active_issue(
            repair_validation_summary,
            "contract overreach signals",
        ):
            return True
        return any(
            cls._summary_has_active_issue(repair_validation_summary, label)
            for label in (
                "unknown module symbols",
                "invalid member references",
                "constructor arity mismatches",
            )
        )

    @staticmethod
    def _python_import_roots(raw_content: object) -> set[str]:
        if not isinstance(raw_content, str) or not raw_content.strip():
            return set()

        try:
            tree = ast.parse(raw_content)
        except SyntaxError:
            return set()

        import_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name:
                        import_roots.add(root_name)
                continue
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                module_name = (node.module or "").split(".", 1)[0]
                if module_name:
                    import_roots.add(module_name)
        return import_roots

    @classmethod
    def _stale_generated_module_import_roots(
        cls,
        existing_tests: object,
        module_name: object,
        module_filename: object,
    ) -> list[str]:
        expected_root = ""
        if isinstance(module_filename, str) and module_filename.strip():
            expected_root = module_filename.strip().rsplit("/", 1)[-1]
            if expected_root.endswith(".py"):
                expected_root = expected_root[:-3]
        if not expected_root and isinstance(module_name, str) and module_name.strip():
            expected_root = module_name.strip()
        if not expected_root:
            return []

        import_roots = cls._python_import_roots(existing_tests)
        relevant_roots = sorted(
            root
            for root in import_roots
            if root == expected_root or root.endswith("_implementation")
        )
        if not relevant_roots:
            return []
        return [root for root in relevant_roots if root != expected_root]

    @classmethod
    def _existing_tests_context_and_instruction(
        cls,
        *,
        existing_tests: object,
        module_name: object,
        module_filename: object,
        code_exact_test_contract: object,
        repair_validation_summary: object,
        implementation_code: object = "",
    ) -> tuple[str, str]:
        has_missing_datetime_import_issue = cls._summary_has_missing_datetime_import_issue(
            repair_validation_summary,
            existing_tests,
        )
        has_required_evidence_runtime_issue = cls._summary_has_required_evidence_runtime_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        has_required_payload_runtime_issue = cls._summary_has_required_payload_runtime_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        has_exact_status_action_label_issue = cls._summary_has_exact_status_action_label_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        has_exact_band_label_issue = cls._summary_has_exact_band_label_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        has_exact_temporal_value_issue = cls._summary_has_exact_temporal_value_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        has_exact_numeric_score_issue = cls._summary_has_exact_numeric_score_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        has_positive_numeric_score_issue = cls._summary_has_positive_numeric_score_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        has_presence_only_validation_sample_issue = cls._summary_has_presence_only_validation_sample_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        has_placeholder_boolean_assertion_issue = cls._summary_has_placeholder_boolean_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        has_validation_side_effect_without_workflow_call_issue = cls._summary_has_validation_side_effect_without_workflow_call_issue(
            repair_validation_summary,
            existing_tests,
        )
        available_module_symbol_names = cls._undefined_available_module_symbol_names(
            implementation_code,
            repair_validation_summary,
        )
        required_payload_keys = cls._implementation_required_payload_keys(implementation_code)
        non_validation_payload_keys = cls._implementation_non_validation_payload_keys(implementation_code)
        validation_omitted_payload_key = cls._validation_failure_omitted_payload_key(implementation_code)
        required_request_fields = cls._implementation_required_request_fields(implementation_code)
        validation_missing_request_field = cls._validation_failure_missing_request_field(implementation_code)
        _, validation_request_like_line = cls._validation_failure_request_like_object_scaffold_line(
            implementation_code,
        )
        required_payload_suffix = ""
        if required_payload_keys:
            required_payload_suffix = (
                f" The current validator only checks for the presence of {required_payload_keys!r}."
            )
        required_request_suffix = ""
        if required_request_fields:
            required_request_suffix = (
                f" The current validator instead checks the top-level request field set {required_request_fields!r} on the request object."
            )
        required_evidence_items = cls._implementation_required_evidence_items(implementation_code)
        required_evidence_suffix = ""
        if required_evidence_items:
            required_evidence_suffix = (
                f" The implementation names that required evidence list as {required_evidence_items!r}."
            )
        helper_alias_names = cls._undefined_helper_alias_names_outside_exact_contract(
            code_exact_test_contract,
            repair_validation_summary,
            implementation_code,
        )
        if helper_alias_names:
            rendered_names = ", ".join(helper_alias_names)
            return (
                "Previous invalid pytest file omitted because the validation summary reported undefined helper or collaborator aliases outside the Exact test contract: "
                f"{rendered_names}. Rebuild the suite from the Exact test contract and current implementation instead of patching guessed helper wiring in place.",
                "The previous validation summary reported undefined helper or collaborator aliases outside the Exact test contract: "
                f"{rendered_names}. Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation, and do not replace those guessed helpers with near-match record or dataclass imports.",
            )

        all_undefined_local_names = cls._undefined_local_names(repair_validation_summary)
        available_module_symbol_lowers = {name.lower() for name in available_module_symbol_names}
        safe_builtins = {"pytest", "datetime"}
        residual_undefined_names = [
            name
            for name in all_undefined_local_names
            if name.lower() not in available_module_symbol_lowers
            and name.lower() not in safe_builtins
        ]
        if residual_undefined_names:
            rendered_names = ", ".join(residual_undefined_names)
            return (
                "Previous invalid pytest file omitted because the validation summary reported undefined local names that are not available module symbols: "
                f"{rendered_names}. Rebuild the suite from the Exact test contract and current implementation instead of patching hallucinated references in place.",
                "The previous validation summary reported undefined local names that are not importable from the module or available as builtins: "
                f"{rendered_names}. Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation, and do not invent helper variables, callback captures, or intermediate locals that are not defined in the test or imported from the production module.",
            )

        stale_generated_module_roots = cls._stale_generated_module_import_roots(
            existing_tests,
            module_name,
            module_filename,
        )
        if stale_generated_module_roots:
            rendered_roots = ", ".join(stale_generated_module_roots)
            current_module_name = module_name if isinstance(module_name, str) and module_name.strip() else "the current target module"
            current_module_file = module_filename if isinstance(module_filename, str) and module_filename.strip() else f"{current_module_name}.py"
            return (
                "Previous invalid pytest file omitted because it imports stale generated module targets such as "
                f"{rendered_roots} instead of the current module file {current_module_file}. Rebuild the suite from the current implementation and import only from {current_module_name}.",
                "The previous invalid pytest file imports stale generated module targets such as "
                f"{rendered_roots} instead of the current module file {current_module_file}. Do not preserve or patch that file in place. Rebuild the suite from the current implementation, and import only from {current_module_name} instead of any older generated repair module alias.",
            )

        if has_missing_datetime_import_issue and not available_module_symbol_names:
            return (
                "Previous invalid pytest file omitted because the validation summary already reported bare `datetime` references without a matching import. Rebuild the suite from the Exact test contract and current implementation instead of copying the previous file forward unchanged.",
                "The previous validation summary already reported bare `datetime` references without a matching import. Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation, and resolve every bare `datetime` reference before returning the rewritten file.",
            )

        if has_required_evidence_runtime_issue and not available_module_symbol_names:
            return (
                "Previous invalid pytest file omitted because the current runtime failure shows that supposed happy-path or batch payloads still omit required evidence named by the implementation validator. Rebuild the suite from the Exact test contract and current implementation instead of copying the stale placeholder-document payload forward."
                f"{required_evidence_suffix}",
                "The current runtime failure shows that supposed happy-path or batch payloads still omit required evidence named by the implementation validator. Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation, copy the full required evidence list into every valid happy-path or batch payload, and isolate missing-document coverage to the explicit validation-failure test."
                f"{required_evidence_suffix}",
            )

        if has_required_payload_runtime_issue and not available_module_symbol_names:
            return (
                "Previous invalid pytest file omitted because the current runtime failure shows that supposed happy-path or batch payloads still omit required payload fields named by the implementation validator. Rebuild the suite from the Exact test contract and current implementation instead of copying the stale partial payload forward."
                f"{required_payload_suffix}",
                "The current runtime failure shows that supposed happy-path or batch payloads still omit required payload fields named by the implementation validator. Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation, copy the full required payload key set into every valid happy-path or batch payload, and isolate missing-field coverage to the explicit validation-failure test."
                f"{required_payload_suffix}"
                + (
                    f" Keep the scaffolded validation-failure omission on `{validation_omitted_payload_key}` exactly as shown."
                    if validation_omitted_payload_key
                    else ""
                ),
            )

        if required_request_fields and not required_payload_keys and not available_module_symbol_names:
            return (
                "Previous invalid pytest file omitted because the current validator checks top-level request field presence on the request object rather than nested payload keys. Rebuild the suite from the Exact test contract and current implementation instead of preserving a fully populated request-model rejection case."
                f"{required_request_suffix}",
                "The current validator checks top-level request field presence on the request object rather than nested payload keys. Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation, keep valid happy-path and batch coverage on the exact request model, and make `test_validation_failure` use a request-like object missing one of those top-level fields instead of a fully populated request-model constructor."
                f"{required_request_suffix}"
                + (
                    f" Keep the constructor-free invalid object line `{validation_request_like_line}` exactly as shown, reuse that same `invalid_request` object in both `validate_request(...)` and the workflow call, and do not replace it with a request-model constructor or a placeholder case such as `details={{}}`."
                    if validation_request_like_line
                    else ""
                )
                + (
                    f" Keep the scaffolded missing-field case on `{validation_missing_request_field}` exactly as shown, and do not turn that into `{validation_missing_request_field}=None` or another placeholder value because the field must be absent entirely."
                    if validation_missing_request_field
                    else ""
                ),
            )

        if has_presence_only_validation_sample_issue:
            return (
                "Previous invalid pytest file omitted because the validation-failure payload still keeps every required field that the current validator only checks for presence. Rebuild the suite from the Exact test contract and current implementation instead of preserving same-shape placeholder values that still satisfy validation."
                f"{required_payload_suffix}",
                "The current validation-failure payload still keeps every required field that the current validator only checks for presence. Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation, and make the rejection case omit one required field or use a clearly wrong top-level type instead of keeping all required fields with placeholder values."
                f"{required_payload_suffix}"
                + (
                    f" Keep the scaffolded missing-field case on `{validation_omitted_payload_key}` exactly as shown."
                    if validation_omitted_payload_key
                    else ""
                )
                + (
                    " Do not swap that rejection case to optional downstream business keys such as "
                    + ", ".join(f"`{key}`" for key in non_validation_payload_keys[:3])
                    + ". Those keys are only read after validation and do not make `validate_request(...)` return `False` here."
                    if non_validation_payload_keys
                    else ""
                ),
            )

        if has_positive_numeric_score_issue and not available_module_symbol_names:
            return (
                "Previous overreaching pytest file omitted because the current runtime failure still includes a speculative positive score threshold beyond the documented contract. Rebuild the suite from the Exact test contract and current implementation instead of preserving that guessed non-zero expectation.",
                "The current runtime failure still includes a speculative positive score threshold beyond the documented contract. Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch around contract-backed scenarios, and replace `risk_score > 0.0`, `score > 0.0`, or similar positive-threshold checks with stable invariants such as non-negative score bounds, type checks, relative ordering, or documented decision and audit evidence.",
            )

        if has_exact_numeric_score_issue and not available_module_symbol_names:
            return (
                "Previous overreaching pytest file omitted because the current runtime failure still includes a brittle exact numeric score or total assertion beyond the documented contract. Rebuild the suite from the Exact test contract and current implementation instead of preserving that guessed exact value.",
                "The current runtime failure still includes a brittle exact numeric score or total assertion beyond the documented contract. Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch around contract-backed scenarios, recompute any remaining exact numeric expectation from only the branches exercised by the chosen input when the formula is explicit, and otherwise prefer stable invariants such as non-negative scores, relative ordering, or documented outcomes.",
            )

        exact_value_issue_parts: list[str] = []
        if has_exact_status_action_label_issue:
            exact_value_issue_parts.append("exact outcome/action label assertions")
        if has_exact_band_label_issue:
            exact_value_issue_parts.append("exact risk-level or severity-band threshold assertions")
        if has_exact_temporal_value_issue:
            exact_value_issue_parts.append("exact timestamp or generated-time equality assertions")
        if (
            exact_value_issue_parts
            and not available_module_symbol_names
            and not cls._summary_has_active_issue(
                repair_validation_summary,
                "contract overreach signals",
            )
        ):
            rendered_issue_parts = " and ".join(exact_value_issue_parts)
            return (
                "Previous overreaching pytest file omitted because the current runtime failure still includes brittle "
                f"{rendered_issue_parts} beyond the documented contract. Rebuild the suite from the Exact test contract and current implementation instead of preserving those guessed exact values.",
                "The current runtime failure still includes brittle "
                f"{rendered_issue_parts} beyond the documented contract. Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch around contract-backed scenarios, replace guessed exact labels with stable invariants unless the mapping is explicit, and avoid exact timestamp or generated-time equality unless the contract explicitly documents that echo.",
            )

        if cls._summary_has_active_issue(
            repair_validation_summary,
            "contract overreach signals",
        ):
            return (
                "Previous overreaching pytest file omitted because the validation summary already reported contract-overreach assertions. Rebuild the suite from the current implementation and documented contract instead of preserving brittle exact batch-count, derived-state, or threshold guesses.",
                "The previous validation summary already reported contract-overreach assertions. Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch around only contract-backed scenarios, and replace brittle exact batch-count, derived-state, or status-threshold guesses with stable invariants unless the contract explicitly defines them.",
            )

        if has_placeholder_boolean_assertion_issue:
            return (
                "Previous hollow pytest file omitted because the validation summary already reported placeholder boolean assertions instead of real expectations. Rebuild the suite from the current implementation and documented contract instead of preserving `assert True`, `assert False`, or `Assuming ...` placeholders.",
                "The previous validation summary already reported placeholder boolean assertions instead of real expectations. Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch around only the minimum contract-backed scenarios, and replace every placeholder boolean or `Assuming ...` comment with a concrete assertion on a validation result, raised exception, or observable side effect.",
            )

        if has_validation_side_effect_without_workflow_call_issue:
            return (
                "Previous invalid pytest file omitted because the validation-failure test asserted audit or service side effects after calling only `validate_request(...)` without executing the workflow. Rebuild the suite from the current implementation and documented contract instead of preserving that incomplete side-effect pattern.",
                "The previous validation-failure test asserted audit or service side effects after calling only `validate_request(...)` without executing the workflow. Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch, and if the validation-failure test asserts audit records, risk-score state, or another workflow side effect, keep the documented workflow call in that test instead of checking those side effects after only `validate_request(...)`.",
            )

        if cls._should_rebuild_from_exact_contract(
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
            existing_tests=existing_tests,
            implementation_code=implementation_code,
        ):
            return (
                "Previous invalid pytest file omitted because the validation summary already reported invalid import, member, or constructor surface errors. Rebuild the suite from the Exact test contract and current implementation instead of preserving or patching the prior file.",
                "The previous validation summary already reported invalid import, member, or constructor surfaces. Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation instead.",
            )

        if cls._summary_has_active_issue(
            repair_validation_summary,
            "tests without assertion-like checks",
        ):
            return (
                "Previous hollow pytest file omitted because the validation summary already reported top-level tests without assertion-like checks. Rebuild the suite from the current implementation and documented contract instead of preserving call-only tests or the previous suite skeleton.",
                "The previous validation summary already reported hollow top-level tests without assertion-like checks. Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch around only the minimum contract-backed scenarios, and ensure every retained top-level test contains at least one explicit assertion-like check. If the documented workflow is side-effect-only, assign the call to `result` and assert `result is None` or another externally observable side effect instead of leaving a bare call. For repeated batch loops without a dedicated batch return value, collect per-request results and assert batch-visible facts such as `len(results) == len(requests)` and `all(item is None for item in results)` when no stronger observable state exists.",
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
        existing_tests: object = "",
        implementation_code: object = "",
    ) -> str:
        if not cls._should_rebuild_from_exact_contract(
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
            existing_tests=existing_tests,
            implementation_code=implementation_code,
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
            allowed_imports = cls._merge_preserving_order(
                cls._string_list(anchor_overrides.get("allowed_imports")),
                allowed_imports,
            ) or allowed_imports
            preferred_facades = ", ".join(cls._string_list(anchor_overrides.get("preferred_facades"))) or preferred_facades
            exact_callables = []
            exact_methods = cls._string_list(anchor_overrides.get("exact_methods")) or exact_methods
            exact_constructors = ", ".join(
                cls._merge_preserving_order(
                    cls._string_list(anchor_overrides.get("exact_constructors")),
                    cls._comma_separated_items(exact_constructors),
                )
            ) or exact_constructors
        unknown_symbols = cls._summary_issue_value(
            repair_validation_summary,
            "Unknown module symbols",
        )
        invalid_members = cls._summary_issue_value(
            repair_validation_summary,
            "Invalid member references",
        )
        required_evidence_runtime_issue = cls._summary_has_required_evidence_runtime_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        required_payload_runtime_issue = cls._summary_has_required_payload_runtime_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        presence_only_validation_sample_issue = cls._summary_has_presence_only_validation_sample_issue(
            repair_validation_summary,
            existing_tests,
            implementation_code,
        )
        positive_numeric_score_issue = cls._summary_has_positive_numeric_score_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        exact_status_action_label_issue = cls._summary_has_exact_status_action_label_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        exact_band_label_issue = cls._summary_has_exact_band_label_assertion_issue(
            repair_validation_summary,
            existing_tests,
        )
        required_payload_keys = cls._implementation_required_payload_keys(implementation_code)
        validation_omitted_payload_key = cls._validation_failure_omitted_payload_key(implementation_code)
        non_validation_payload_keys = cls._implementation_non_validation_payload_keys(implementation_code)
        required_evidence_items = cls._implementation_required_evidence_items(implementation_code)
        return_shape_assertion_line = cls._return_shape_assertion_line(repair_validation_summary)

        exact_surfaces = [*exact_callables, *exact_methods]
        documented_batch_surface = any("batch" in item.lower() for item in exact_surfaces)
        documented_single_surface = next(
            (item for item in exact_surfaces if "batch" not in item.lower()),
            "",
        )
        primary_exact_method = exact_methods[0] if exact_methods else ""
        primary_runtime_return_kind = cls._implementation_call_return_primitive_kind(
            implementation_code,
            documented_single_surface,
        )
        primary_stable_assertion_lines = cls._stable_call_assertion_lines(
            implementation_code,
            documented_single_surface,
            result_name="result",
            request_name="request",
            service_name="service",
        ) if documented_single_surface else []

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
        if return_shape_assertion_line:
            lines.append(
                f"- The previous runtime failure already showed the workflow return shape here. Keep the happy-path assertion on that runtime type instead: `{return_shape_assertion_line}`."
            )
            lines.append(
                "- Remove guessed wrapper-result imports or attribute reads from the rewritten file unless the implementation explicitly returns that wrapper type."
            )
        elif primary_runtime_return_kind and primary_stable_assertion_lines:
            lines.append(
                f"- The current workflow returns a direct `{primary_runtime_return_kind}` at runtime here. Keep happy-path and batch assertions on that direct value instead of inventing a wrapper result object."
            )
            lines.append(
                f"- Use a stable happy-path assertion such as `{primary_stable_assertion_lines[0]}` and do not add `.request_id`, `.outcome`, or guessed wrapper-result imports unless a later runtime failure proves that wrapper type exists."
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
        if cls._summary_has_missing_datetime_import_issue(repair_validation_summary):
            lines.append(
                "- The previous failed suite used bare `datetime` references without a matching import. Do not copy that file forward unchanged. Resolve every bare `datetime` reference in the rewritten file before returning it."
            )
            if cls._implementation_prefers_direct_datetime_import(implementation_code):
                lines.append(
                    "- Match the implementation's datetime style: add `from datetime import datetime` at the top and prefer a local fixed timestamp such as `fixed_time = datetime(2024, 1, 1, 0, 0, 0)` for constructor arguments instead of repeating bare `datetime.now()` calls."
                )
        if required_evidence_runtime_issue:
            lines.append(
                "- The previous failed suite kept an incomplete document payload inside a supposed happy-path or batch scenario. Do not copy that stale subset forward unchanged."
            )
            if required_evidence_items:
                lines.append(
                    f"- The implementation validator names the full required evidence list as {required_evidence_items!r}. Copy that exact list into every valid happy-path or batch payload."
                )
            else:
                lines.append(
                    "- Copy the full required evidence list named by the implementation validator into every valid happy-path or batch payload instead of shrinking it to a placeholder subset."
                )
            lines.append(
                "- Keep missing-document coverage isolated to `test_validation_failure` or another explicit validation-rejection case. Do not reuse reduced or empty document subsets like ['ID'] or [] inside happy-path or batch tests."
            )
            lines.append(
                "- Apply the same rule to risk-scoring, audit-trail, and other non-validation tests: if they call the workflow or scoring path, keep their request payload fully valid and move missing-document coverage back to the explicit validation-failure test."
            )
        if required_payload_runtime_issue:
            lines.append(
                "- The previous failed suite omitted required payload fields inside a supposed happy-path or batch scenario. Do not copy that stale partial payload forward unchanged."
            )
            if required_payload_keys:
                lines.append(
                    f"- The implementation validator requires the full payload key set {required_payload_keys!r} for valid processing. Copy that exact key set into every valid happy-path or batch payload."
                )
                if validation_omitted_payload_key:
                    lines.append(
                        "- In `test_validation_failure`, keep the scaffolded missing-field case on the required payload key "
                        f"`{validation_omitted_payload_key}`. Do not replace it with a different missing field."
                    )
            else:
                lines.append(
                    "- Copy the full required payload key set named by the implementation validator into every valid happy-path or batch payload instead of omitting part of that required set."
                )
            lines.append(
                "- Keep missing-field coverage isolated to `test_validation_failure` or another explicit validation-rejection case. Do not reuse partial payloads that omit required keys inside happy-path or batch tests."
            )
            lines.append(
                "- Apply the same rule to risk-scoring, audit-trail, and other non-validation tests: if they call the workflow or scoring path, keep their payload fully valid and move missing-field coverage back to the explicit validation-failure test."
            )
        if presence_only_validation_sample_issue:
            lines.append(
                "- The previous validation-failure payload still kept every required field that this validator only checks for presence. Rebuild that rejection case around an actually missing validator-required field or a clearly wrong top-level type instead of leaving all required keys present with placeholder values."
            )
            if validation_omitted_payload_key:
                lines.append(
                    "- In `test_validation_failure`, keep the scaffolded missing-field case on the validator-required key "
                    f"`{validation_omitted_payload_key}` exactly as shown."
                )
            if non_validation_payload_keys:
                rendered_keys = ", ".join(f"`{key}`" for key in non_validation_payload_keys[:3])
                lines.append(
                    "- Do not swap that rejection case to downstream scoring-only keys such as "
                    f"{rendered_keys}. Those keys are only read after validation and should not drive `validate_request(...)` failure here."
                )
        if positive_numeric_score_issue:
            lines.append(
                "- The previous failed suite assumed a positive non-zero score for the chosen input. Replace `risk_score > 0.0`, `score > 0.0`, or similar positive-threshold checks with stable invariants such as non-negative bounds, type checks, relative ordering, or documented decision and audit evidence unless the implementation explicitly guarantees a positive increase."
            )
        if exact_status_action_label_issue:
            lines.append(
                "- The previous failed suite guessed exact status/action labels or audit-log label text. Keep happy-path and batch assertions on request identity, returned type, collection growth, or other contract-backed invariants instead of exact `Approved`, `Escalated`, `Blocked`, or similar label text unless the contract explicitly defines that mapping."
            )
            lines.append(
                "- Treat audit-log message text the same way: do not assert label substrings such as `Approved`, `Escalated`, `Blocked`, or `Rejected` inside audit-log entries unless the contract explicitly defines that text."
            )
        if exact_band_label_issue:
            lines.append(
                "- The previous failed suite overreached with exact risk-tier or severity-band thresholds. Do not keep narrow subset checks like `in ['HIGH', 'CRITICAL']` unless the contract explicitly defines that mapping."
            )
            lines.append(
                "- Prefer numeric score bounds, audit evidence, request identity, or a simple string-type assertion over exact `risk_level` or `severity` labels in non-validation tests."
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
        repair_focus_block = self._repair_focus_block(
            repair_validation_summary,
            implementation_code,
            existing_tests,
        )
        existing_tests_context, repair_instruction = self._existing_tests_context_and_instruction(
            existing_tests=existing_tests,
            module_name=module_name,
            module_filename=module_filename,
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
            implementation_code=implementation_code,
        )
        exact_rebuild_surface_block = self._exact_rebuild_surface_block(
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
            task_public_contract_anchor=task_public_contract_anchor,
            existing_tests=existing_tests,
            implementation_code=implementation_code,
        )
        deterministic_surface_scaffold_block = self._deterministic_surface_scaffold_block(
            module_name=module_name,
            task_description=agent_input.task_description,
            code_exact_test_contract=code_exact_test_contract,
            code_test_targets=code_test_targets,
            task_public_contract_anchor=task_public_contract_anchor,
            implementation_code=implementation_code,
            repair_validation_summary=repair_validation_summary,
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
    Record-shaped value models such as AuditLog, RiskScore, ResultRecord, or similar typed data holders are not service collaborators unless the public API contract explicitly says so. Do not replace an undefined helper alias with a similarly named record type just because it imports cleanly.
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
    Do not hard-code exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests unless the behavior contract or current implementation explicitly defines those triggers.
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
    Do not hard-code exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests unless the behavior contract or current implementation explicitly defines those triggers.
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
        repair_focus_block = self._repair_focus_block(
            repair_validation_summary,
            implementation_code,
            existing_tests,
        )
        existing_tests_context, repair_instruction = self._existing_tests_context_and_instruction(
            existing_tests=existing_tests,
            module_name=module_name,
            module_filename=module_filename,
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
            implementation_code=implementation_code,
        )
        exact_rebuild_surface_block = self._exact_rebuild_surface_block(
            code_exact_test_contract=code_exact_test_contract,
            repair_validation_summary=repair_validation_summary,
            task_public_contract_anchor=task_public_contract_anchor,
            existing_tests=existing_tests,
            implementation_code=implementation_code,
        )
        deterministic_surface_scaffold_block = self._deterministic_surface_scaffold_block(
            module_name=module_name,
            task_description=task_description,
            code_exact_test_contract=code_exact_test_contract,
            code_test_targets=code_test_targets,
            task_public_contract_anchor=task_public_contract_anchor,
            implementation_code=implementation_code,
            repair_validation_summary=repair_validation_summary,
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
    Do not hard-code exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests unless the behavior contract or current implementation explicitly defines those triggers.
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
    Do not hard-code exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests unless the behavior contract or current implementation explicitly defines those triggers.
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
