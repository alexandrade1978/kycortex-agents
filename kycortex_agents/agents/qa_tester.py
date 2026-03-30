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
Never reference a symbol, enum member, class attribute, or constructor shape that is not listed in that contract.
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
Count fixtures before finalizing. If the task sets a maximum fixture budget, stay comfortably under it and inline one-off setup instead of adding a borderline extra fixture.
If the task sets a fixture maximum, target one fewer than that limit by default unless the documented contract clearly requires the extra fixture.
For compact scenario-driven tasks, merge overlapping checks into the smallest set of tests that covers the requested happy path, validation failure, and batch flow. Do not spend separate top-level tests on logging helpers, audit wrappers, or helper-level variants unless the contract explicitly requires those behaviors to be tested independently.
Do not hand-count prose strings to justify exact numeric assertions. If an exact numeric result is contractually required, use trivially countable inputs such as repeated characters or small literals; otherwise prefer stable invariants, ranges, or state transitions over guessed exact scores.
If an exact numeric assertion depends on string length, modulo, counts, or collection size, never use natural-language prose samples for that assertion. Use repeated-character literals, small digit strings, or similarly obvious inputs whose size can be verified at a glance.
Do not assert exact categorical score bands or labels at boundary values unless the contract explicitly defines those cutoffs. For derived levels such as low, medium, or high, use values comfortably inside a band or assert relative ordering when the exact boundary is not part of the contract.
When a constructor or callable signature is listed in the API contract, use exactly that signature in every test.
Do not instantiate helper validators, scorers, loggers, dataclasses, or batch processors merely to wire a higher-level service fixture unless the public API contract explicitly requires that direct setup.
When repairing a previously generated suite that already passed static validation, preserve the existing imported symbols, constructor shapes, fixture payload structure, and scenario skeleton unless the validation summary explicitly identifies one of those pieces as invalid.
When the previous validation summary reports constructor arity mismatches, treat those constructor calls as invalid and remove or rewrite them instead of preserving them from the earlier suite.
If the previous validation summary reports undefined local names or undefined fixtures, remove or rewrite every offending test unless you explicitly import or define those names in the rewritten file. In a compact suite, delete helper-only tests before adding new fixtures, caplog assertions, or extra helper imports.
Treat the current implementation artifact and API contract as fixed ground truth during repair. Do not invent replacement response classes, alternate validators, renamed helpers, or new return-wrapper types.
Do not invent alternate field names, sample payload shapes, return structures, or exception messages.
Do not reference pytest fixtures unless you define them in the same file or they are standard built-in pytest fixtures.
Every test function argument must be a built-in pytest fixture, a fixture defined in the same file, or a name introduced by a matching `pytest.mark.parametrize` decorator.
Do not reference helper names or expected-value variables inside test bodies unless they are imported, defined in the same file, or introduced by the matching parametrization.
Do not call `main()`, CLI/demo entrypoints, or `argparse`-driven functions directly unless the task explicitly requires CLI testing and you fully control `sys.argv` or monkeypatch the parser inputs.
If the module exposes a CLI wrapper class or `run()` method for command-line flow, leave it out of the suite unless the task explicitly requires CLI testing and you fully control argv or input.
For happy-path tests, derive input payloads from the implementation summary so they satisfy the module's own validation rules.
When the task names only high-level workflow scenarios, keep the suite on the main service or batch surface and do not add direct unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly asks for them.
In compact high-level workflow suites, do not spend top-level tests on validator units, scorer units, dataclass serialization, audit logger wrappers, or other helper-only coverage unless the task explicitly names those helpers.
When the task requires both a validation-failure scenario and a batch-processing scenario, keep the validation-failure coverage on the direct intake or validation surface unless the behavior contract explicitly requires batch-level failure coverage.
If the validation-failure scenario is a missing-required-field case, omit only the field under test and keep the rest of that payload valid for the same surface so the test isolates one clear contract violation.
If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid instead of raising, assert that state on the same object you passed into the call.
Keep batch-processing scenarios structurally valid unless the behavior contract explicitly says partially invalid batch items are expected and defines the expected outcome.
If the provided test targets list batch-capable functions, use one of those functions for the batch scenario instead of inventing batch behavior for unrelated helpers.
If the public API exposes no dedicated batch helper, express the batch scenario as a short list of individually valid items processed one by one. Do not pass a list into scalar-only validators or scorers.
Example: if the module exposes only process_request(request) and no process_batch(...), write a short loop over two valid requests and assert the documented result of each process_request call instead of switching to logger, repository, scorer, or audit helpers.
If a batch helper returns None or constructs its own domain objects from raw items, do not instantiate fresh objects after the batch call and assume they inherited internal mutations. Assert only directly observable outcomes, caller-owned object mutations, or behavior you explicitly patch in that test.
Prefer the highest-level public service or top-level workflow functions for the requested scenarios. Do not import repository, logger, scorer, validator, or similar helper services directly unless the API contract makes them the primary surface under test.
Do not add caplog assertions or raw logging-text expectations unless the behavior contract explicitly states that emitted log output is part of the observable contract. If audit behavior must be checked, prefer deterministic assertions on returned state or audit records exposed by the service.
If you assert audit records, assert only the actions exercised in that same scenario. Do not expect document-upload, status-change, or similar audit events unless the test performs that action directly.
Never define a custom fixture named `request`; pytest reserves that name. Use inline setup or a specific fixture name such as `sample_request` instead.
Do not use mock-style bookkeeping assertions such as `.call_count` or `.assert_called_once()` on logging objects, production callables, or other real objects unless the same test first installs a real `Mock`, `MagicMock`, or `patch` target for that exact object.
If repair context suggests truncation or incomplete output, remove non-essential comments, blank lines, extra fixtures, and optional helper scaffolding before dropping any required scenario.
If you are repairing a previously invalid or truncated test file, rewrite the complete pytest module from the top instead of continuing from a partial tail."""

class QATesterAgent(BaseAgent):
    required_context_keys = ("code",)
    output_artifact_type = ArtifactType.TEST
    output_artifact_name = "tests"

    def __init__(self, config: KYCortexConfig):
        super().__init__("QATester", "Quality Assurance & Testing", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        implementation_code = self.require_context_value(agent_input, "code")
        existing_tests = agent_input.context.get("existing_tests", "")
        module_name = agent_input.context.get("module_name", "module")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        code_summary = agent_input.context.get("code_summary", "")
        code_outline = agent_input.context.get("code_outline", "")
        code_public_api = agent_input.context.get("code_public_api", "")
        code_test_targets = agent_input.context.get("code_test_targets", "")
        code_behavior_contract = agent_input.context.get("code_behavior_contract", "")
        repair_validation_summary = agent_input.context.get("repair_validation_summary", "")
        user_msg = f"""Project: {agent_input.project_name}
    Project goal: {agent_input.project_goal}
    Implementation summary: {code_summary}
    Implementation code:
    {implementation_code}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}
    {code_test_targets}
    Behavior contract:
    {code_behavior_contract}

Existing tests context:
    {existing_tests}

Repair the existing pytest file above when it is provided. Preserve every valid import, fixture, and scenario that already matches the contract, and change only the parts needed to fix the reported blockers.
If the previous validation summary lists constructor arity mismatches, remove or rewrite those constructor calls instead of preserving guessed helper wiring from the old suite.

Previous validation summary:
    {repair_validation_summary}

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.

Module name: {module_name}
Module file: {module_filename}
Task: {agent_input.task_description}

Write a complete raw pytest file.
Import from `{module_name}` and test the actual public functions and classes from that module.
    Import every called production function explicitly from `{module_name}`.
    Import only top-level functions and classes from `{module_name}`.
    Do not import `main`, CLI/demo entrypoints, or any symbol listed under the provided Entry points to avoid in tests guidance.
    Do not import or instantiate CLI wrapper classes such as names ending in `CLI` or `Cli` unless the task explicitly requires CLI testing and you fully control argv or input.
    Import every production class you instantiate or reference in a fixture or test body.
    Do not hand-wire validator, scorer, logger, batch-processor, dataclass, or similar helper objects into a service fixture unless the public API contract explicitly requires those constructor arguments.
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    Respect the task's line budget and requested scenario count exactly. Prefer top-level test functions and inline setup over class-based suites or extra helper fixtures when the task asks for compact coverage.
    If the task sets only a maximum number of top-level tests, stay comfortably under that ceiling unless the documented contract explicitly requires more coverage.
    Leave at least one top-level test of headroom below a stated maximum unless the task explicitly requires the maximum count.
    Before you finalize, count top-level tests and total lines explicitly. If the suite is at or above any stated limit, merge or delete the lowest-value helper coverage until the file is back under budget.
    If the task sets a fixture maximum, count fixtures before you finalize and inline one-off setup instead of adding a borderline extra fixture.
    If the task sets a fixture maximum, target one fewer than that limit by default unless the documented contract clearly requires the extra fixture.
    If the task only names high-level workflow scenarios, stay on the main service or batch API and do not add separate unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly requests them.
    In compact high-level workflow suites, do not spend top-level tests on validator units, scorer units, dataclass serialization, audit logger wrappers, or other helper-only coverage unless the task explicitly names those helpers.
    For compact scenario-driven suites, merge overlapping checks instead of creating helper-specific extra tests. Do not spend standalone tests on simple logging or audit helpers unless the contract makes them independently observable.
    If the task requires both a validation-failure scenario and a batch-processing scenario, use the direct intake or validation surface for the failure case unless the behavior contract explicitly requires a batch-level failure scenario.
    If the validation-failure scenario is a missing-required-field case, omit only the field under test and keep the rest of that payload valid for the same surface.
    If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid instead of raising, assert that state on the same object you passed into the call.
    Keep the batch-processing scenario structurally valid unless the behavior contract explicitly says partially invalid batch items are expected.
    If the provided test targets list batch-capable functions, use one of those functions for the batch scenario instead of inventing batch behavior for unrelated helpers.
    If the public API exposes no dedicated batch helper, express the batch scenario by iterating over a short list of valid items one by one instead of passing a list into scalar-only validators or scorers.
    Example: if the module exposes only process_request(request) and no process_batch(...), write a short loop over two valid requests and assert the documented result of each process_request call instead of switching to logger, repository, scorer, or audit helpers.
    If a batch helper returns None or constructs its own domain objects from raw items, do not instantiate fresh objects after the batch call and assume they inherited internal mutations. Assert only directly observable outcomes, caller-owned object mutations, or behavior you explicitly patch in that test.
    Prefer the highest-level public service or top-level workflow functions for the requested scenarios. Do not import repository, logger, scorer, validator, or similar helper services directly unless the API contract makes them the primary surface under test.
    Do not add standalone caplog or raw logging-output assertions unless the behavior contract explicitly makes log output observable. If audit behavior matters, prefer deterministic assertions on service state or audit records exposed by the service.
    If you assert audit records, assert only actions exercised in that same scenario. Do not expect document-upload, status-change, or similar audit events unless the test performs that action directly.
    Never define a custom fixture named `request`; pytest reserves that name. Use inline setup or a specific fixture name such as `sample_request` instead.
    Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test creates the exact mock or patch target first.
    If you assert an exact numeric value, use trivially countable inputs and do so only when the behavior contract or implementation clearly defines the exact formula; otherwise prefer stable non-exact assertions.
    If an exact numeric assertion depends on string length, modulo, counts, or collection size, never use prose sample text for that assertion. Use repeated-character literals or similarly obvious inputs.
    Do not assert exact categorical score bands or labels at boundary values unless the contract explicitly defines those cutoffs. Use comfortably in-band inputs or non-boundary assertions for derived levels.
    If the API contract does not list a symbol or enum member, do not use it.
    If the previous suite already passed static validation and only failed at pytest runtime, keep the same public module surface and make the smallest behavioral correction needed. Do not replace valid imports with guessed APIs or change documented constructor signatures.
    If the previous validation summary reports undefined local names or undefined fixtures, remove or rewrite every offending test unless you explicitly import or define those names in this rewritten file. In a compact workflow suite, delete helper-only tests before adding new fixtures, caplog assertions, or extra helper imports.
    Treat the current implementation artifact and API contract as fixed ground truth during repair. Do not invent replacement response classes, alternate validators, renamed helpers, or new return-wrapper types.
    Before you finalize, verify this checklist against your own output:
    - every imported production symbol exists in the API contract
    - every imported production symbol also appears in the listed test targets unless it is only used as a type container
    - every production class referenced in a fixture or test body is explicitly imported from the target module
    - every class instantiation uses only documented constructor arguments
    - if the previous validation summary lists constructor arity mismatches, you removed guessed helper wiring and rebuilt the scenario around the smallest documented public API surface
    - every assertion matches behavior reachable from the provided implementation summary
    - every happy-path payload satisfies the listed behavior contract and validation rules
    - if the task sets a fixture maximum, you stayed at or under it and inlined one-off setup instead of adding a borderline extra fixture
    - if the task sets only a maximum number of top-level tests, you stayed comfortably under that ceiling unless the documented contract explicitly required more coverage
    - if the task sets only a maximum number of top-level tests, you left at least one top-level test of headroom below that maximum unless an exact count was explicitly required
    - before you finalized, you counted top-level tests and total lines and removed lowest-value helper coverage until the file sat safely under every stated cap
    - if the task requires both a validation-failure scenario and a batch scenario, the validation failure stays on the direct intake or validation surface unless the behavior contract explicitly requires a batch-level failure case
    - if the validation-failure scenario omits a required field, it omits only the field under test and keeps the rest of that payload valid for the same surface
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
    - you did not define a custom fixture named `request`
    - every non-built-in fixture used by a test is defined in the same file
    - every test function argument is either a built-in fixture, a locally defined fixture, or a name introduced by the matching parametrization
    - every helper or expected-value name referenced inside a test body is imported, defined in the file, or introduced by the matching parametrization
    - you did not add caplog or raw logging-text assertions unless the behavior contract explicitly makes emitted log output observable
    - if you asserted audit records, every asserted action is exercised in that same scenario rather than guessed from unrelated workflow steps
    - you did not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test creates the exact mock or patch target first
    - every exact numeric assertion is supported by an explicit contract or formula and uses trivially countable input; otherwise you used stable non-exact assertions
    - if you asserted derived categorical levels or score bands, you used comfortably in-band inputs or non-boundary assertions unless the contract explicitly defined the thresholds
    - if an exact numeric assertion depends on string length, modulo, counts, or collection size, you used repeated-character or similarly obvious inputs rather than prose sample text
    - you did not invent replacement API names, response-wrapper classes, alternate validators, or alternate constructor signatures during repair
    - if the previous test file was syntax-invalid or truncated, you rewrote the full pytest file from the top instead of appending a partial continuation
    - if the previous validation mentions truncation or completion diagnostics, you reduced non-essential comments, blank lines, optional fixtures, and helper scaffolding so the whole pytest file fits cleanly in one response
    - no test imports entrypoints listed under "Entry points to avoid in tests"
    - no test imports or instantiates CLI wrapper classes such as names ending in `CLI` or `Cli` unless CLI coverage is explicitly required and argv/input is fully controlled
    - no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test
    - the file is syntactically complete with no truncated fixture, string, or parametrization block"""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        implementation_code = context.get("code", "")
        existing_tests = context.get("existing_tests", "")
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        code_summary = context.get("code_summary", "")
        code_outline = context.get("code_outline", "")
        code_public_api = context.get("code_public_api", "")
        code_test_targets = context.get("code_test_targets", "")
        code_behavior_contract = context.get("code_behavior_contract", "")
        repair_validation_summary = context.get("repair_validation_summary", "")
        user_msg = f"""Implementation summary: {code_summary}
    Implementation code:
    {implementation_code}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}
    {code_test_targets}
    Behavior contract:
    {code_behavior_contract}

Existing tests context:
    {existing_tests}

Repair the existing pytest file above when it is provided. Preserve every valid import, fixture, and scenario that already matches the contract, and change only the parts needed to fix the reported blockers.
If the previous validation summary lists constructor arity mismatches, remove or rewrite those constructor calls instead of preserving guessed helper wiring from the old suite.

Previous validation summary:
    {repair_validation_summary}

If the previous validation summary lists any failures, treat every listed issue as a hard blocker and fix each one in this new file.

Module name: {module_name}
Module file: {module_filename}
Task: {task_description}

Write a complete raw pytest file.
Import from `{module_name}` and test the actual public functions and classes from that module.
    Import every called production function explicitly from `{module_name}`.
    Import only top-level functions and classes from `{module_name}`.
    Do not import `main`, CLI/demo entrypoints, or any symbol listed under the provided Entry points to avoid in tests guidance.
    Do not import or instantiate CLI wrapper classes such as names ending in `CLI` or `Cli` unless the task explicitly requires CLI testing and you fully control argv or input.
    Import every production class you instantiate or reference in a fixture or test body.
    Do not hand-wire validator, scorer, logger, batch-processor, dataclass, or similar helper objects into a service fixture unless the public API contract explicitly requires those constructor arguments.
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    Respect the task's line budget and requested scenario count exactly. Prefer top-level test functions and inline setup over class-based suites or extra helper fixtures when the task asks for compact coverage.
    If the task sets only a maximum number of top-level tests, stay comfortably under that ceiling unless the documented contract explicitly requires more coverage.
    Leave at least one top-level test of headroom below a stated maximum unless the task explicitly requires the maximum count.
    Before you finalize, count top-level tests and total lines explicitly. If the suite is at or above any stated limit, merge or delete the lowest-value helper coverage until the file is back under budget.
    If the task sets a fixture maximum, count fixtures before you finalize and inline one-off setup instead of adding a borderline extra fixture.
    If the task sets a fixture maximum, target one fewer than that limit by default unless the documented contract clearly requires the extra fixture.
    If the task only names high-level workflow scenarios, stay on the main service or batch API and do not add separate unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly requests them.
    In compact high-level workflow suites, do not spend top-level tests on validator units, scorer units, dataclass serialization, audit logger wrappers, or other helper-only coverage unless the task explicitly names those helpers.
    For compact scenario-driven suites, merge overlapping checks instead of creating helper-specific extra tests. Do not spend standalone tests on simple logging or audit helpers unless the contract makes them independently observable.
    If the task requires both a validation-failure scenario and a batch-processing scenario, use the direct intake or validation surface for the failure case unless the behavior contract explicitly requires a batch-level failure scenario.
    If the validation-failure scenario is a missing-required-field case, omit only the field under test and keep the rest of that payload valid for the same surface.
    If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid instead of raising, assert that state on the same object you passed into the call.
    Keep the batch-processing scenario structurally valid unless the behavior contract explicitly says partially invalid batch items are expected.
    If the provided test targets list batch-capable functions, use one of those functions for the batch scenario instead of inventing batch behavior for unrelated helpers.
    If the public API exposes no dedicated batch helper, express the batch scenario by iterating over a short list of valid items one by one instead of passing a list into scalar-only validators or scorers.
    Example: if the module exposes only process_request(request) and no process_batch(...), write a short loop over two valid requests and assert the documented result of each process_request call instead of switching to logger, repository, scorer, or audit helpers.
    If a batch helper returns None or constructs its own domain objects from raw items, do not instantiate fresh objects after the batch call and assume they inherited internal mutations. Assert only directly observable outcomes, caller-owned object mutations, or behavior you explicitly patch in that test.
    Prefer the highest-level public service or top-level workflow functions for the requested scenarios. Do not import repository, logger, scorer, validator, or similar helper services directly unless the API contract makes them the primary surface under test.
    Do not add standalone caplog or raw logging-output assertions unless the behavior contract explicitly makes log output observable. If audit behavior matters, prefer deterministic assertions on service state or audit records exposed by the service.
    If you assert audit records, assert only actions exercised in that same scenario. Do not expect document-upload, status-change, or similar audit events unless the test performs that action directly.
    Never define a custom fixture named `request`; pytest reserves that name. Use inline setup or a specific fixture name such as `sample_request` instead.
    Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test creates the exact mock or patch target first.
    If you assert an exact numeric value, use trivially countable inputs and do so only when the behavior contract or implementation clearly defines the exact formula; otherwise prefer stable non-exact assertions.
    If an exact numeric assertion depends on string length, modulo, counts, or collection size, never use prose sample text for that assertion. Use repeated-character literals or similarly obvious inputs.
    Do not assert exact categorical score bands or labels at boundary values unless the contract explicitly defines those cutoffs. Use comfortably in-band inputs or non-boundary assertions for derived levels.
    If the API contract does not list a symbol or enum member, do not use it.
    If the previous suite already passed static validation and only failed at pytest runtime, keep the same public module surface and make the smallest behavioral correction needed. Do not replace valid imports with guessed APIs or change documented constructor signatures.
    If the previous validation summary reports undefined local names or undefined fixtures, remove or rewrite every offending test unless you explicitly import or define those names in this rewritten file. In a compact workflow suite, delete helper-only tests before adding new fixtures, caplog assertions, or extra helper imports.
    Treat the current implementation artifact and API contract as fixed ground truth during repair. Do not invent replacement response classes, alternate validators, renamed helpers, or new return-wrapper types.
    Before you finalize, verify this checklist against your own output:
    - every imported production symbol exists in the API contract
    - every imported production symbol also appears in the listed test targets unless it is only used as a type container
    - every production class referenced in a fixture or test body is explicitly imported from the target module
    - every class instantiation uses only documented constructor arguments
    - if the previous validation summary lists constructor arity mismatches, you removed guessed helper wiring and rebuilt the scenario around the smallest documented public API surface
    - every assertion matches behavior reachable from the provided implementation summary
    - every happy-path payload satisfies the listed behavior contract and validation rules
    - if the task sets only a maximum number of top-level tests, you stayed comfortably under that ceiling unless the documented contract explicitly required more coverage
    - if the task sets only a maximum number of top-level tests, you left at least one top-level test of headroom below that maximum unless an exact count was explicitly required
    - before you finalized, you counted top-level tests and total lines and removed lowest-value helper coverage until the file sat safely under every stated cap
    - if the task requires both a validation-failure scenario and a batch scenario, the validation failure stays on the direct intake or validation surface unless the behavior contract explicitly requires a batch-level failure case
    - if the validation-failure scenario omits a required field, it omits only the field under test and keeps the rest of that payload valid for the same surface
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
    - you did not define a custom fixture named `request`
    - every non-built-in fixture used by a test is defined in the same file
    - every test function argument is either a built-in fixture, a locally defined fixture, or a name introduced by the matching parametrization
    - every helper or expected-value name referenced inside a test body is imported, defined in the file, or introduced by the matching parametrization
    - you did not add caplog or raw logging-text assertions unless the behavior contract explicitly makes emitted log output observable
    - if you asserted audit records, every asserted action is exercised in that same scenario rather than guessed from unrelated workflow steps
    - you did not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test creates the exact mock or patch target first
    - every exact numeric assertion is supported by an explicit contract or formula and uses trivially countable input; otherwise you used stable non-exact assertions
    - if an exact numeric assertion depends on string length, modulo, counts, or collection size, you used repeated-character or similarly obvious inputs rather than prose sample text
    - you did not invent replacement API names, response-wrapper classes, alternate validators, or alternate constructor signatures during repair
    - if the previous test file was syntax-invalid or truncated, you rewrote the full pytest file from the top instead of appending a partial continuation
    - if the previous validation mentions truncation or completion diagnostics, you reduced non-essential comments, blank lines, optional fixtures, and helper scaffolding so the whole pytest file fits cleanly in one response
    - no test imports entrypoints listed under "Entry points to avoid in tests"
    - no test imports or instantiates CLI wrapper classes such as names ending in `CLI` or `Cli` unless CLI coverage is explicitly required and argv/input is fully controlled
    - no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test
    - the file is syntactically complete with no truncated fixture, string, or parametrization block"""
        return self.chat(SYSTEM_PROMPT, user_msg)
