import pytest

from kycortex_agents.agents.architect import ArchitectAgent
from kycortex_agents.agents.code_engineer import CodeEngineerAgent
from kycortex_agents.agents.code_reviewer import CodeReviewerAgent
from kycortex_agents.agents.dependency_manager import DependencyManagerAgent
from kycortex_agents.agents.docs_writer import DocsWriterAgent
from kycortex_agents.agents.legal_advisor import LegalAdvisorAgent
from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.types import AgentInput, ArtifactType


class ChatCaptureMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_system_prompt = None
        self.last_user_message = None

    def chat(self, system_prompt: str, user_message: str) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        return "ok"


class CaptureArchitectAgent(ChatCaptureMixin, ArchitectAgent):
    pass


class CaptureCodeEngineerAgent(ChatCaptureMixin, CodeEngineerAgent):
    pass


class CaptureCodeReviewerAgent(ChatCaptureMixin, CodeReviewerAgent):
    pass


class CaptureDependencyManagerAgent(ChatCaptureMixin, DependencyManagerAgent):
    pass


class CaptureQATesterAgent(ChatCaptureMixin, QATesterAgent):
    pass


class CaptureDocsWriterAgent(ChatCaptureMixin, DocsWriterAgent):
    pass


class CaptureLegalAdvisorAgent(ChatCaptureMixin, LegalAdvisorAgent):
    pass


def build_config(tmp_path):
    return KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="token")


def test_architect_agent_uses_typed_input_fields(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="arch",
        task_title="Architecture",
        task_description="Design the system",
        project_name="Demo",
        project_goal="Build demo",
        context={"planned_module_filename": "code_implementation.py"},
        constraints=["Python 3.12", "No GPL dependencies"],
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Project Name: Demo" in agent.last_user_message
    assert "Project Goal: Build demo" in agent.last_user_message
    assert "Python 3.12, No GPL dependencies" in agent.last_user_message
    assert "Target module: code_implementation.py" in agent.last_user_message
    assert "Respect the task scope exactly" in agent.last_user_message


def test_architect_agent_run_uses_context_goal_and_target_module(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))

    result = agent.run(
        "Design a single module",
        {
            "goal": "Build demo",
            "constraints": "Python 3.12",
            "planned_module_filename": "single_module.py",
        },
    )

    assert result == "ok"
    assert "Project Goal: Build demo" in agent.last_user_message
    assert "Constraints: Python 3.12" in agent.last_user_message
    assert "Target module: single_module.py" in agent.last_user_message


def test_code_engineer_requires_architecture_context(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="code",
        task_title="Code",
        task_description="Implement feature",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    with pytest.raises(AgentExecutionError, match="required context key 'architecture'"):
        agent.execute(agent_input)


def test_code_reviewer_uses_typed_code_context(tmp_path):
    agent = CaptureCodeReviewerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="review",
        task_title="Review",
        task_description="Review implementation",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "print('hello')",
            "tests": "def test_it():\n    assert True",
            "module_name": "demo_mod",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Project: Demo" in agent.last_user_message
    assert "print('hello')" in agent.last_user_message
    assert "Module name: demo_mod" in agent.last_user_message
    assert "Generated tests:" in agent.last_user_message
    assert "Test validation summary:" in agent.last_user_message
    assert "Dependency validation summary:" in agent.last_user_message


def test_code_engineer_run_uses_context_module_details(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))

    result = agent.run(
        "Implement feature",
        {
            "architecture": "Layered design",
            "existing_code": "def old():\n    return 1",
            "existing_tests": "def test_old():\n    assert old() == 2",
            "repair_validation_summary": "Generated code validation:\n- Syntax OK: no\n- Completion diagnostics: likely truncated at completion limit",
            "module_name": "service_module",
            "module_filename": "service_module.py",
        },
    )

    assert result == "ok"
    assert "Architecture:\nLayered design" in agent.last_user_message
    assert "Target module: service_module.py" in agent.last_user_message
    assert "The file will be saved as `service_module.py` and imported as `service_module`." in agent.last_user_message
    assert "def old():" in agent.last_user_message
    assert "Existing tests context:" in agent.last_user_message
    assert "def test_old():" in agent.last_user_message
    assert "Previous validation summary:" in agent.last_user_message
    assert "Completion diagnostics: likely truncated at completion limit" in agent.last_user_message
    assert "hard blocker" in agent.last_user_message
    assert "Use the existing tests context, when provided" in agent.last_user_message
    assert "Respect the task's requested size budget exactly." in agent.last_user_message
    assert "If the task does not specify one, keep the module under 260 lines." in agent.last_user_message
    assert "stay comfortably under that ceiling instead of aiming for the exact limit" in agent.last_user_message
    assert "treat each listed failing assertion as an exact behavior contract for this module" in agent.last_user_message
    assert "Do not stop at a nearby constant tweak, renamed helper, or signature change" in agent.last_user_message
    assert "if the task requires a CLI or demo entrypoint" in agent.last_user_message
    assert "if __name__ == \"__main__\":" in agent.last_user_message
    assert "you stayed comfortably under the ceiling rather than using the full budget" in agent.last_user_message
    assert "you implemented only the required behavior from the architecture" in agent.last_user_message
    assert "rewrote the full module from the top instead of appending a partial continuation" in agent.last_user_message
    assert "every constructor call matches the constructor you defined" in agent.last_user_message
    assert "every opened string, bracket, parenthesis, and docstring is closed" in agent.last_user_message
    assert "you reduced non-essential docstrings, comments, blank lines, and optional helpers" in agent.last_user_message
    assert "If you are repairing a previously invalid or truncated file" in agent.last_system_prompt
    assert "Do not stop mid-function, mid-string, or mid-docstring." in agent.last_system_prompt
    assert "stay comfortably under that ceiling so imports, the main guard, and any required repairs still fit" in agent.last_system_prompt
    assert "remove non-essential docstrings, comments, blank lines, and optional helper layers" in agent.last_system_prompt
    assert "Treat the architecture as guidance for required behavior" in agent.last_system_prompt
    assert "Task-specific scope and size limits override generic polish" in agent.last_system_prompt
    assert "treat those assertions as exact behavioral requirements for the module" in agent.last_system_prompt
    assert "do not stop at a nearby constant tweak or branch edit" in agent.last_system_prompt


def test_code_reviewer_run_uses_context_module_validation_fields(tmp_path):
    agent = CaptureCodeReviewerAgent(build_config(tmp_path))

    result = agent.run(
        "Review implementation",
        {
            "code": "def run():\n    return 1",
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
            "tests": "from service_module import run",
            "test_validation_summary": "Generated test validation:\n- Missing function imports: none",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
        },
    )

    assert result == "ok"
    assert "Module name: service_module" in agent.last_user_message
    assert "Module file: service_module.py" in agent.last_user_message
    assert "Functions:\n- run()" in agent.last_user_message
    assert "Generated tests:" in agent.last_user_message


def test_qa_tester_uses_module_name_when_provided(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="test",
        task_title="Tests",
        task_description="Write tests",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "def add(a, b): return a + b",
            "module_name": "math_utils",
            "module_filename": "math_utils.py",
            "code_summary": "def add(a, b): return a + b",
            "code_outline": "def add(a, b):",
            "code_public_api": "Functions:\n- add(a, b)\nClasses:\n- none",
            "code_test_targets": "Test targets:\n- Functions to test: add(a, b)\n- Classes to test: none\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- add accepts numeric operands",
            "repair_validation_summary": "Generated test validation:\n- Completion diagnostics: likely truncated at completion limit",
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Module name: math_utils" in agent.last_user_message
    assert "Public API outline:" in agent.last_user_message
    assert "Public API contract:" in agent.last_user_message
    assert "Test targets:" in agent.last_user_message
    assert "Functions to test: add(a, b)" in agent.last_user_message
    assert "Behavior contract:" in agent.last_user_message
    assert "Implementation code:" in agent.last_user_message
    assert "def add(a, b): return a + b" in agent.last_user_message
    assert "add accepts numeric operands" in agent.last_user_message
    assert "Previous validation summary:" in agent.last_user_message
    assert "Completion diagnostics: likely truncated at completion limit" in agent.last_user_message
    assert "hard blocker" in agent.last_user_message
    assert "def add(a, b):" in agent.last_user_message
    assert "Import from `math_utils`" in agent.last_user_message
    assert "Import every called production function explicitly" in agent.last_user_message
    assert "Import every production class you instantiate or reference in a fixture or test body" in agent.last_user_message
    assert "Do not hand-wire validator, scorer, logger, batch-processor, dataclass, or similar helper objects into a service fixture" in agent.last_user_message
    assert "Respect the task's line budget and requested scenario count exactly." in agent.last_user_message
    assert "stay comfortably under that ceiling" in agent.last_user_message
    assert "if the task asks for a fixed number of scenarios or tests" in agent.last_user_message
    assert "merge overlapping checks instead of creating helper-specific extra tests" in agent.last_user_message
    assert "If you assert an exact numeric value, use trivially countable inputs" in agent.last_user_message
    assert "never use prose sample text for that assertion" in agent.last_user_message
    assert "every imported production symbol exists in the API contract" in agent.last_user_message
    assert "every imported production symbol also appears in the listed test targets" in agent.last_user_message
    assert "every class instantiation uses only documented constructor arguments" in agent.last_user_message
    assert "if the previous validation summary lists constructor arity mismatches" in agent.last_user_message
    assert "every happy-path payload satisfies the listed behavior contract and validation rules" in agent.last_user_message
    assert "you did not add standalone helper or logging tests" in agent.last_user_message
    assert "every exact numeric assertion is supported by an explicit contract or formula" in agent.last_user_message
    assert "you used repeated-character or similarly obvious inputs rather than prose sample text" in agent.last_user_message
    assert "use the direct intake or validation surface for the failure case" in agent.last_user_message
    assert "Keep the batch-processing scenario structurally valid" in agent.last_user_message
    assert "If the public API exposes no dedicated batch helper" in agent.last_user_message
    assert "Do not add standalone caplog or raw logging-output assertions" in agent.last_user_message
    assert "Never define a custom fixture named `request`" in agent.last_user_message
    assert "Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions" in agent.last_user_message
    assert "Do not import or instantiate CLI wrapper classes such as names ending in `CLI` or `Cli`" in agent.last_user_message
    assert "If the previous suite already passed static validation and only failed at pytest runtime" in agent.last_user_message
    assert "Treat the current implementation artifact and API contract as fixed ground truth during repair" in agent.last_user_message
    assert "Write complete pytest code only; do not stop mid-test, mid-string, or mid-fixture." in agent.last_system_prompt
    assert "Do not import `main`, CLI/demo entrypoints" in agent.last_system_prompt
    assert "Treat CLI wrapper classes such as names ending in `CLI` or `Cli` as entrypoint surfaces to avoid in tests" in agent.last_system_prompt
    assert "stay comfortably under that cap" in agent.last_system_prompt
    assert "Do not hand-count prose strings to justify exact numeric assertions" in agent.last_system_prompt
    assert "never use natural-language prose samples for that assertion" in agent.last_system_prompt
    assert "keep the validation-failure coverage on the direct intake or validation surface" in agent.last_system_prompt
    assert "Keep batch-processing scenarios structurally valid" in agent.last_system_prompt
    assert "If the public API exposes no dedicated batch helper" in agent.last_system_prompt
    assert "Do not add caplog assertions or raw logging-text expectations" in agent.last_system_prompt
    assert "Never define a custom fixture named `request`" in agent.last_system_prompt
    assert "Do not use mock-style bookkeeping assertions such as `.call_count` or `.assert_called_once()`" in agent.last_system_prompt
    assert "When repairing a previously generated suite that already passed static validation" in agent.last_system_prompt
    assert "Do not invent replacement response classes, alternate validators, renamed helpers, or new return-wrapper types" in agent.last_system_prompt
    assert "do not add direct unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities" in agent.last_system_prompt
    assert "every non-built-in fixture used by a test is defined in the same file" in agent.last_user_message
    assert "every test function argument is either a built-in fixture, a locally defined fixture, or a name introduced by the matching parametrization" in agent.last_user_message
    assert "every helper or expected-value name referenced inside a test body is imported, defined in the file, or introduced by the matching parametrization" in agent.last_user_message
    assert "every happy-path batch item satisfies the same required fields as the single-request happy path" in agent.last_user_message
    assert "you did not add caplog or raw logging-text assertions unless the behavior contract explicitly makes emitted log output observable" in agent.last_user_message
    assert "you did not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions" in agent.last_user_message
    assert "if the previous suite already passed static validation, you preserved valid imports, constructor signatures, fixture payload shapes, and scenario structure" in agent.last_user_message
    assert "you did not invent replacement API names, response-wrapper classes, alternate validators, or alternate constructor signatures during repair" in agent.last_user_message
    assert "rewrote the full pytest file from the top instead of appending a partial continuation" in agent.last_user_message
    assert "you reduced non-essential comments, blank lines, optional fixtures, and helper scaffolding" in agent.last_user_message
    assert "stay on the main service or batch API" in agent.last_user_message
    assert "no test imports entrypoints listed under \"Entry points to avoid in tests\"" in agent.last_user_message
    assert "no test imports or instantiates CLI wrapper classes such as names ending in `CLI` or `Cli`" in agent.last_user_message
    assert "no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test" in agent.last_user_message
    assert "Every test function argument must be a built-in pytest fixture" in agent.last_system_prompt
    assert "If you are repairing a previously invalid or truncated test file" in agent.last_system_prompt
    assert "Do not reference pytest fixtures unless you define them in the same file" in agent.last_system_prompt
    assert "remove non-essential comments, blank lines, extra fixtures, and optional helper scaffolding" in agent.last_system_prompt
    assert "Task-specific scope, test-count, and size limits override these defaults" in agent.last_system_prompt


def test_docs_writer_falls_back_to_code_for_summary(tmp_path):
    agent = CaptureDocsWriterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="docs",
        task_title="Docs",
        task_description="Write documentation",
        project_name="Demo",
        project_goal="Build demo",
        context={"architecture": "Layered design", "code": "def main(): pass", "module_name": "demo_mod"},
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Goal: Build demo" in agent.last_user_message
    assert "Code summary: def main(): pass" in agent.last_user_message
    assert "Actual module: demo_mod.py" in agent.last_user_message
    assert "Exact run command: No CLI entrypoint detected" in agent.last_user_message
    assert "Dependency manifest: Not provided" in agent.last_user_message
    assert "Dependency validation summary:" in agent.last_user_message


def test_docs_writer_run_uses_context_for_actual_module_and_run_command(tmp_path):
    agent = CaptureDocsWriterAgent(build_config(tmp_path))

    result = agent.run(
        "Write docs",
        {
            "project_name": "Demo",
            "architecture": "Layered design",
            "code_summary": "Core API",
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "dependency_manifest": "requests>=2.31.0",
            "dependency_manifest_path": "artifacts/requirements.txt",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
            "module_run_command": "python service_module.py",
            "test_validation_summary": "Generated test validation:\n- Missing function imports: none",
            "code": "def run():\n    return 1",
        },
    )

    assert result == "ok"
    assert "Actual module: service_module.py" in agent.last_user_message
    assert "Exact run command: python service_module.py" in agent.last_user_message
    assert "Dependency manifest: artifacts/requirements.txt" in agent.last_user_message
    assert "requests>=2.31.0" in agent.last_user_message


def test_dependency_manager_uses_code_context_and_requirements_prompt(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="deps",
        task_title="Dependencies",
        task_description="Infer runtime dependencies",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "import numpy as np\n\ndef run():\n    return np.array([1])",
            "module_name": "demo_mod",
            "module_filename": "demo_mod.py",
            "code_summary": "import numpy as np",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
        },
    )

    result = agent.run_with_input(agent_input)

    assert result.raw_content == "ok"
    assert "Module: demo_mod.py" in agent.last_user_message
    assert "requirements.txt" in agent.last_user_message
    assert "Do not include development-only tools such as pytest" in agent.last_user_message


def test_dependency_manager_run_uses_context_module_details(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    result = agent.run(
        "Infer runtime dependencies",
        {
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "import requests",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
            "code": "import requests\n\ndef run():\n    return requests.Session()",
        },
    )

    assert result == "ok"
    assert "Module: service_module.py" in agent.last_user_message
    assert "Code summary: import requests" in agent.last_user_message
    assert "Infer the minimal runtime requirements.txt" in agent.last_user_message


def test_legal_advisor_formats_dependencies_from_typed_context(tmp_path):
    agent = CaptureLegalAdvisorAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="legal",
        task_title="Legal",
        task_description="Review licensing",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "license": "Dual-licensed: AGPL-3.0 open-source distribution or separate commercial terms",
            "dependencies": ["openai", "anthropic"],
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Project License: Dual-licensed: AGPL-3.0 open-source distribution or separate commercial terms" in agent.last_user_message
    assert "- openai" in agent.last_user_message
    assert "- anthropic" in agent.last_user_message


def test_qa_tester_run_uses_context_module_contract(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Write tests",
        {
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Core API",
            "code_outline": "def run():",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
            "existing_tests": "def test_old():\n    assert True",
        },
    )

    assert result == "ok"
    assert "Module name: service_module" in agent.last_user_message
    assert "Module file: service_module.py" in agent.last_user_message
    assert "Public API contract:" in agent.last_user_message
    assert "Existing tests context:" in agent.last_user_message
    assert "def test_old():" in agent.last_user_message
    assert "Repair the existing pytest file above when it is provided." in agent.last_user_message
    assert "remove or rewrite those constructor calls instead of preserving guessed helper wiring" in agent.last_user_message
    assert "Import from `service_module`" in agent.last_user_message
    assert "If you assert an exact numeric value, use trivially countable inputs" in agent.last_user_message
    assert "never use prose sample text for that assertion" in agent.last_user_message
    assert "Never define a custom fixture named `request`" in agent.last_user_message
    assert "Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions" in agent.last_user_message


@pytest.mark.parametrize(
    ("agent_class", "context", "expected_type", "expected_name"),
    [
        (CaptureArchitectAgent, {}, ArtifactType.DOCUMENT, "arch_architecture"),
        (CaptureCodeEngineerAgent, {"architecture": "Layered design"}, ArtifactType.CODE, "code_implementation"),
        (CaptureCodeReviewerAgent, {"code": "print('hello')"}, ArtifactType.DOCUMENT, "review_review"),
        (CaptureDependencyManagerAgent, {"code": "print('hello')"}, ArtifactType.CONFIG, "deps_requirements"),
        (CaptureQATesterAgent, {"code": "def add(a, b): return a + b"}, ArtifactType.TEST, "test_tests"),
        (CaptureDocsWriterAgent, {}, ArtifactType.DOCUMENT, "docs_documentation"),
        (CaptureLegalAdvisorAgent, {}, ArtifactType.DOCUMENT, "legal_legal_analysis"),
    ],
)
def test_execute_adds_role_specific_default_artifact(tmp_path, agent_class, context, expected_type, expected_name):
    agent = agent_class(build_config(tmp_path))
    agent_input = AgentInput(
        task_id=expected_name.split("_", 1)[0],
        task_title="Task",
        task_description="Perform task",
        project_name="Demo",
        project_goal="Build demo",
        context=context,
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "ok"
    assert result.metadata["project_name"] == "Demo"
    assert len(result.artifacts) == 1
    assert result.artifacts[0].artifact_type == expected_type
    assert result.artifacts[0].name == expected_name