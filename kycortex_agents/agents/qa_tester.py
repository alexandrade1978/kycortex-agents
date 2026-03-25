from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType

SYSTEM_PROMPT = """You are a QA Engineer at KYCortex AI Software House.
You write comprehensive pytest test suites.
For each module/function, write: unit tests, edge case tests, integration test stubs.
Use fixtures, parametrize where appropriate. Aim for 80%+ coverage.
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
Do not call `main()`, CLI/demo entrypoints, or `argparse`-driven functions directly unless the task explicitly requires CLI testing and you fully control `sys.argv` or monkeypatch the parser inputs.
For happy-path tests, derive input payloads from the implementation summary so they satisfy the module's own validation rules."""

class QATesterAgent(BaseAgent):
    required_context_keys = ("code",)
    output_artifact_type = ArtifactType.TEST
    output_artifact_name = "tests"

    def __init__(self, config: KYCortexConfig):
        super().__init__("QATester", "Quality Assurance & Testing", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        self.require_context_value(agent_input, "code")
        module_name = agent_input.context.get("module_name", "module")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        code_summary = agent_input.context.get("code_summary", "")
        code_outline = agent_input.context.get("code_outline", "")
        code_public_api = agent_input.context.get("code_public_api", "")
        code_test_targets = agent_input.context.get("code_test_targets", "")
        code_behavior_contract = agent_input.context.get("code_behavior_contract", "")
        user_msg = f"""Project: {agent_input.project_name}
    Project goal: {agent_input.project_goal}
    Implementation summary: {code_summary}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}
    {code_test_targets}
    Behavior contract:
    {code_behavior_contract}

Module name: {module_name}
Module file: {module_filename}
Task: {agent_input.task_description}

Write a complete raw pytest file.
Import from `{module_name}` and test the actual public functions and classes from that module.
    Import every called production function explicitly from `{module_name}`.
    Import only top-level functions and classes from `{module_name}`.
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    If the API contract does not list a symbol or enum member, do not use it.
    Before you finalize, verify this checklist against your own output:
    - every imported production symbol exists in the API contract
    - every imported production symbol also appears in the listed test targets unless it is only used as a type container
    - every class instantiation uses only documented constructor arguments
    - every assertion matches behavior reachable from the provided implementation summary
    - every happy-path payload satisfies the listed behavior contract and validation rules
    - every non-built-in fixture used by a test is defined in the same file
    - no test imports entrypoints listed under "Entry points to avoid in tests"
    - no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test
    - the file is syntactically complete with no truncated fixture, string, or parametrization block"""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        code_summary = context.get("code_summary", "")
        code_outline = context.get("code_outline", "")
        code_public_api = context.get("code_public_api", "")
        code_test_targets = context.get("code_test_targets", "")
        code_behavior_contract = context.get("code_behavior_contract", "")
        user_msg = f"""Implementation summary: {code_summary}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}
    {code_test_targets}
    Behavior contract:
    {code_behavior_contract}

Module name: {module_name}
Module file: {module_filename}
Task: {task_description}

Write a complete raw pytest file.
Import from `{module_name}` and test the actual public functions and classes from that module.
    Import every called production function explicitly from `{module_name}`.
    Import only top-level functions and classes from `{module_name}`.
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    If the API contract does not list a symbol or enum member, do not use it.
    Before you finalize, verify this checklist against your own output:
    - every imported production symbol exists in the API contract
    - every imported production symbol also appears in the listed test targets unless it is only used as a type container
    - every class instantiation uses only documented constructor arguments
    - every assertion matches behavior reachable from the provided implementation summary
    - every happy-path payload satisfies the listed behavior contract and validation rules
    - every non-built-in fixture used by a test is defined in the same file
    - no test imports entrypoints listed under "Entry points to avoid in tests"
    - no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test
    - the file is syntactically complete with no truncated fixture, string, or parametrization block"""
        return self.chat(SYSTEM_PROMPT, user_msg)
