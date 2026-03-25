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


class NoisyDependencyManagerAgent(DependencyManagerAgent):
    def chat(self, system_prompt: str, user_message: str) -> str:
        return (
            "After analyzing the module, the requirements.txt should be:\n\n"
            "```text\n"
            "requests>=2.31.0\n"
            "numpy==2.1.1\n"
            "```\n"
        )


class EmptyDependencyManagerAgent(DependencyManagerAgent):
    def chat(self, system_prompt: str, user_message: str) -> str:
        return "The module only uses the standard library.\n\n# No external runtime dependencies"


class CaptureQATesterAgent(ChatCaptureMixin, QATesterAgent):
    pass


class CaptureDocsWriterAgent(ChatCaptureMixin, DocsWriterAgent):
    pass


class CaptureLegalAdvisorAgent(ChatCaptureMixin, LegalAdvisorAgent):
    pass


def build_config(tmp_path):
    return KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="token")


def test_architect_agent_execute_uses_default_constraints_and_document_artifact(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="arch",
        task_title="Architecture",
        task_description="Design the system",
        project_name="Demo",
        project_goal="Build demo",
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "ok"
    assert "Python 3.10+, production-ready dependencies, licensing suitable for open-source or commercial distribution" in agent.last_user_message
    assert "Respect the task scope exactly" in agent.last_user_message
    assert result.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert result.artifacts[0].name == "arch_architecture"


def test_code_engineer_agent_execute_requires_architecture_context(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="code",
        task_title="Implementation",
        task_description="Implement the service",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    with pytest.raises(AgentExecutionError, match="required context key 'architecture'"):
        agent.execute(agent_input)


def test_code_reviewer_agent_execute_adds_review_artifact_and_uses_code_context(tmp_path):
    agent = CaptureCodeReviewerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="review",
        task_title="Review",
        task_description="Review the implementation",
        project_name="Demo",
        project_goal="Build demo",
        context={"code": "print('hello')"},
    )

    result = agent.execute(agent_input)

    assert "print('hello')" in agent.last_user_message
    assert result.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert result.artifacts[0].name == "review_review"


def test_dependency_manager_agent_execute_writes_requirements_artifact(tmp_path):
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

    result = agent.execute(agent_input)

    assert "Infer the minimal runtime requirements.txt" in agent.last_user_message
    assert result.artifacts[0].artifact_type == ArtifactType.CONFIG
    assert result.artifacts[0].path == "artifacts/requirements.txt"
    assert result.artifacts[0].name == "deps_requirements"


def test_dependency_manager_agent_normalizes_noisy_requirements_output(tmp_path):
    agent = NoisyDependencyManagerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="deps",
        task_title="Dependencies",
        task_description="Infer runtime dependencies",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "import requests\nimport numpy as np\n",
            "module_name": "demo_mod",
            "module_filename": "demo_mod.py",
        },
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "requests>=2.31.0\nnumpy==2.1.1"
    assert result.artifacts[0].content == "requests>=2.31.0\nnumpy==2.1.1"


def test_dependency_manager_agent_falls_back_to_no_external_dependencies(tmp_path):
    agent = EmptyDependencyManagerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="deps",
        task_title="Dependencies",
        task_description="Infer runtime dependencies",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "import random\nimport logging\n",
            "module_name": "demo_mod",
            "module_filename": "demo_mod.py",
        },
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "# No external runtime dependencies"
    assert result.artifacts[0].content == "# No external runtime dependencies"


def test_dependency_manager_agent_normalizes_bulleted_requirements_and_deduplicates(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    normalized = agent._normalize_requirements(
        "- `requests>=2.31.0`\n* requests>=2.31.0\n* numpy==2.1.1\n"
    )

    assert normalized == "requests>=2.31.0\nnumpy==2.1.1"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("requests>=2.31.0", True),
        ("package[extra]>=1.0", True),
        ("import requests", False),
        ("after analyzing the code", False),
        ("plain prose line", False),
    ],
)
def test_dependency_manager_requirement_detection_filters_non_requirements(tmp_path, line, expected):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    assert agent._looks_like_requirement(line) is expected


def test_qa_tester_agent_execute_uses_default_module_name_and_test_artifact(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="tests",
        task_title="Tests",
        task_description="Write tests",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "def add(a, b): return a + b",
            "code_summary": "def add(a, b): return a + b",
            "code_outline": "def add(a, b):",
            "code_public_api": "Functions:\n- add(a, b)\nClasses:\n- none",
        },
    )

    result = agent.execute(agent_input)

    assert "Module name: module" in agent.last_user_message
    assert "Public API outline:" in agent.last_user_message
    assert "Public API contract:" in agent.last_user_message
    assert "Do not duplicate the implementation code in the tests." in agent.last_user_message
    assert "Import every called production function explicitly" in agent.last_user_message
    assert "Return only raw Python test code." in agent.last_system_prompt
    assert result.artifacts[0].artifact_type == ArtifactType.TEST
    assert result.artifacts[0].name == "tests_tests"


def test_code_engineer_agent_prompt_demands_raw_python_output(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="code",
        task_title="Implementation",
        task_description="Implement the service",
        project_name="Demo",
        project_goal="Build demo",
        context={"architecture": "Layered design"},
    )

    agent.execute(agent_input)

    assert "Return only raw Python source code." in agent.last_system_prompt
    assert "Do not include markdown fences" in agent.last_system_prompt
    assert "Target module: code_implementation.py" in agent.last_user_message


def test_code_reviewer_agent_prompt_includes_tests_and_module_name(tmp_path):
    agent = CaptureCodeReviewerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="review",
        task_title="Review",
        task_description="Review the implementation",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "print('hello')",
            "tests": "def test_it():\n    assert True",
            "module_name": "code_implementation",
            "module_filename": "code_implementation.py",
            "code_public_api": "Functions:\n- none\nClasses:\n- none",
            "test_validation_summary": "Generated test validation:\n- Missing function imports: none",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
        },
    )

    agent.execute(agent_input)

    assert "Module name: code_implementation" in agent.last_user_message
    assert "Module file: code_implementation.py" in agent.last_user_message
    assert "Generated tests:" in agent.last_user_message
    assert "Test validation summary:" in agent.last_user_message
    assert "Dependency validation summary:" in agent.last_user_message


def test_docs_writer_agent_prompt_anchors_to_actual_module(tmp_path):
    agent = CaptureDocsWriterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="docs",
        task_title="Docs",
        task_description="Write docs",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "architecture": "Layered design",
            "code": "def main(): pass",
            "code_summary": "Core API and worker layer",
            "module_name": "code_implementation",
            "module_run_command": "python code_implementation.py",
            "dependency_manifest_path": "artifacts/requirements.txt",
            "dependency_manifest": "requests>=2.0",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
            "code_public_api": "Functions:\n- main()\nClasses:\n- none",
        },
    )

    agent.execute(agent_input)

    assert "Actual module: code_implementation.py" in agent.last_user_message
    assert "Exact run command: python code_implementation.py" in agent.last_user_message
    assert "Dependency manifest: artifacts/requirements.txt" in agent.last_user_message
    assert "Dependency validation summary:" in agent.last_user_message
    assert "Do not invent extra files, package layouts, CLIs, API endpoints, or components" in agent.last_system_prompt


def test_docs_writer_agent_execute_prefers_code_summary_over_code(tmp_path):
    agent = CaptureDocsWriterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="docs",
        task_title="Docs",
        task_description="Write docs",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "architecture": "Layered design",
            "code": "def fallback(): pass",
            "code_summary": "Core API and worker layer",
            "module_run_command": "",
        },
    )

    result = agent.execute(agent_input)

    assert "Code summary: Core API and worker layer" in agent.last_user_message
    assert "Generated code:" in agent.last_user_message
    assert "def fallback(): pass" in agent.last_user_message
    assert "Exact run command: No CLI entrypoint detected" in agent.last_user_message
    assert result.artifacts[0].name == "docs_documentation"


def test_legal_advisor_agent_execute_uses_default_license_and_dependency_placeholder(tmp_path):
    agent = CaptureLegalAdvisorAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="legal",
        task_title="Legal",
        task_description="Review legal posture",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    result = agent.execute(agent_input)

    assert "Project License: Dual-licensed: AGPL-3.0 open-source distribution or separate commercial terms" in agent.last_user_message
    assert "Not specified" in agent.last_user_message
    assert result.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert result.artifacts[0].name == "legal_legal_analysis"


def test_legal_advisor_agent_execute_includes_custom_license_and_dependencies(tmp_path):
    agent = CaptureLegalAdvisorAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="legal",
        task_title="Legal",
        task_description="Review dependencies and licensing",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "license": "MIT",
            "dependencies": ["fastapi==0.115.0", "uvicorn==0.30.0"],
        },
    )

    agent.execute(agent_input)

    assert "Project License: MIT" in agent.last_user_message
    assert "- fastapi==0.115.0" in agent.last_user_message
    assert "- uvicorn==0.30.0" in agent.last_user_message
    assert "Goal: Build demo" in agent.last_user_message


def test_legal_advisor_agent_run_uses_custom_license_and_dependency_list(tmp_path):
    agent = CaptureLegalAdvisorAgent(build_config(tmp_path))

    result = agent.run(
        "Assess compliance posture",
        {
            "license": "Apache-2.0",
            "dependencies": ["requests>=2.31.0", "pydantic>=2.0"],
        },
    )

    assert result == "ok"
    assert "Project License: Apache-2.0" in agent.last_user_message
    assert "- requests>=2.31.0" in agent.last_user_message
    assert "- pydantic>=2.0" in agent.last_user_message
    assert "Task: Assess compliance posture" in agent.last_user_message