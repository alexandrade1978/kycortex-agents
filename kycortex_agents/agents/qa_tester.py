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
If behavior is exposed as a class method, instantiate the class and call the method on the instance instead of importing the method name as a top-level function."""

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
        user_msg = f"""Project: {agent_input.project_name}
    Project goal: {agent_input.project_goal}
    Implementation summary: {code_summary}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}

Module name: {module_name}
Module file: {module_filename}
Task: {agent_input.task_description}

Write a complete raw pytest file.
Import from `{module_name}` and test the actual public functions and classes from that module.
    Import every called production function explicitly from `{module_name}`.
    Import only top-level functions and classes from `{module_name}`.
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    If the API contract does not list a symbol or enum member, do not use it."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        code_summary = context.get("code_summary", "")
        code_outline = context.get("code_outline", "")
        code_public_api = context.get("code_public_api", "")
        user_msg = f"""Implementation summary: {code_summary}
    Public API outline:
    {code_outline}
    Public API contract:
    {code_public_api}

Module name: {module_name}
Module file: {module_filename}
Task: {task_description}

Write a complete raw pytest file.
Import from `{module_name}` and test the actual public functions and classes from that module.
    Import every called production function explicitly from `{module_name}`.
    Import only top-level functions and classes from `{module_name}`.
    Do not duplicate the implementation code in the tests.
    Assume the module code already exists in `{module_filename}` and keep the tests compact and deterministic.
    If the API contract does not list a symbol or enum member, do not use it."""
        return self.chat(SYSTEM_PROMPT, user_msg)
