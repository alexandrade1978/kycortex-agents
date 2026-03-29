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
Import every production function you call from the target module.
If behavior is exposed as a class method, instantiate the class and call the method on the instance instead of importing the method name as a top-level function.
Write complete pytest code only; do not stop mid-test, mid-string, or mid-fixture.
Keep tests compact and execution-safe: prefer a few correct tests over broad but speculative coverage.
When a constructor or callable signature is listed in the API contract, use exactly that signature in every test.
Do not invent alternate field names, sample payload shapes, return structures, or exception messages.
Do not reference pytest fixtures unless you define them in the same file or they are standard built-in pytest fixtures.
Every test function argument must be a built-in pytest fixture, a fixture defined in the same file, or a name introduced by a matching `pytest.mark.parametrize` decorator.
Do not reference helper names or expected-value variables inside test bodies unless they are imported, defined in the same file, or introduced by the matching parametrization.
Do not call `main()`, CLI/demo entrypoints, or `argparse`-driven functions directly unless the task explicitly requires CLI testing and you fully control `sys.argv` or monkeypatch the parser inputs.
For happy-path tests, derive input payloads from the implementation summary so they satisfy the module's own validation rules.
When the task names only high-level workflow scenarios, keep the suite on the main service or batch surface and do not add direct unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly asks for them.
When the task requires both a validation-failure scenario and a batch-processing scenario, keep the validation-failure coverage on the direct intake or validation surface unless the behavior contract explicitly requires batch-level failure coverage.
Keep batch-processing scenarios structurally valid unless the behavior contract explicitly says partially invalid batch items are expected and defines the expected outcome.
Do not add caplog assertions or raw logging-text expectations unless the behavior contract explicitly states that emitted log output is part of the observable contract. If audit behavior must be checked, prefer deterministic assertions on returned state or audit records exposed by the service.
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
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    Respect the task's line budget and requested scenario count exactly. Prefer top-level test functions and inline setup over class-based suites or extra helper fixtures when the task asks for compact coverage.
    If the task only names high-level workflow scenarios, stay on the main service or batch API and do not add separate unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly requests them.
    If the task requires both a validation-failure scenario and a batch-processing scenario, use the direct intake or validation surface for the failure case unless the behavior contract explicitly requires a batch-level failure scenario.
    Keep the batch-processing scenario structurally valid unless the behavior contract explicitly says partially invalid batch items are expected.
    Do not add standalone caplog or raw logging-output assertions unless the behavior contract explicitly makes log output observable. If audit behavior matters, prefer deterministic assertions on service state or audit records exposed by the service.
    If the API contract does not list a symbol or enum member, do not use it.
    Before you finalize, verify this checklist against your own output:
    - every imported production symbol exists in the API contract
    - every imported production symbol also appears in the listed test targets unless it is only used as a type container
    - every class instantiation uses only documented constructor arguments
    - every assertion matches behavior reachable from the provided implementation summary
    - every happy-path payload satisfies the listed behavior contract and validation rules
    - if the task requires both a validation-failure scenario and a batch scenario, the validation failure stays on the direct intake or validation surface unless the behavior contract explicitly requires a batch-level failure case
    - every happy-path batch item satisfies the same required fields as the single-request happy path unless the behavior contract explicitly documents a different batch shape
    - if the task asks for a fixed number of scenarios or tests, you did not add extra cases beyond that request
    - every non-built-in fixture used by a test is defined in the same file
    - every test function argument is either a built-in fixture, a locally defined fixture, or a name introduced by the matching parametrization
    - every helper or expected-value name referenced inside a test body is imported, defined in the file, or introduced by the matching parametrization
    - you did not add caplog or raw logging-text assertions unless the behavior contract explicitly makes emitted log output observable
    - if the previous test file was syntax-invalid or truncated, you rewrote the full pytest file from the top instead of appending a partial continuation
    - if the previous validation mentions truncation or completion diagnostics, you reduced non-essential comments, blank lines, optional fixtures, and helper scaffolding so the whole pytest file fits cleanly in one response
    - no test imports entrypoints listed under "Entry points to avoid in tests"
    - no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test
    - the file is syntactically complete with no truncated fixture, string, or parametrization block"""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        implementation_code = context.get("code", "")
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
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    Respect the task's line budget and requested scenario count exactly. Prefer top-level test functions and inline setup over class-based suites or extra helper fixtures when the task asks for compact coverage.
    If the task only names high-level workflow scenarios, stay on the main service or batch API and do not add separate unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities unless the task explicitly requests them.
    If the task requires both a validation-failure scenario and a batch-processing scenario, use the direct intake or validation surface for the failure case unless the behavior contract explicitly requires a batch-level failure scenario.
    Keep the batch-processing scenario structurally valid unless the behavior contract explicitly says partially invalid batch items are expected.
    Do not add standalone caplog or raw logging-output assertions unless the behavior contract explicitly makes log output observable. If audit behavior matters, prefer deterministic assertions on service state or audit records exposed by the service.
    If the API contract does not list a symbol or enum member, do not use it.
    Before you finalize, verify this checklist against your own output:
    - every imported production symbol exists in the API contract
    - every imported production symbol also appears in the listed test targets unless it is only used as a type container
    - every class instantiation uses only documented constructor arguments
    - every assertion matches behavior reachable from the provided implementation summary
    - every happy-path payload satisfies the listed behavior contract and validation rules
    - if the task requires both a validation-failure scenario and a batch scenario, the validation failure stays on the direct intake or validation surface unless the behavior contract explicitly requires a batch-level failure case
    - every happy-path batch item satisfies the same required fields as the single-request happy path unless the behavior contract explicitly documents a different batch shape
    - if the task asks for a fixed number of scenarios or tests, you did not add extra cases beyond that request
    - every non-built-in fixture used by a test is defined in the same file
    - every test function argument is either a built-in fixture, a locally defined fixture, or a name introduced by the matching parametrization
    - every helper or expected-value name referenced inside a test body is imported, defined in the file, or introduced by the matching parametrization
    - you did not add caplog or raw logging-text assertions unless the behavior contract explicitly makes emitted log output observable
    - if the previous test file was syntax-invalid or truncated, you rewrote the full pytest file from the top instead of appending a partial continuation
    - if the previous validation mentions truncation or completion diagnostics, you reduced non-essential comments, blank lines, optional fixtures, and helper scaffolding so the whole pytest file fits cleanly in one response
    - no test imports entrypoints listed under "Entry points to avoid in tests"
    - no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test
    - the file is syntactically complete with no truncated fixture, string, or parametrization block"""
        return self.chat(SYSTEM_PROMPT, user_msg)
