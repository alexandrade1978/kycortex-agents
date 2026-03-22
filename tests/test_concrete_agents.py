import pytest

from kycortex_agents.agents.architect import ArchitectAgent
from kycortex_agents.agents.code_engineer import CodeEngineerAgent
from kycortex_agents.agents.code_reviewer import CodeReviewerAgent
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
    assert "Apache 2.0, Python 3.10+, no GPL deps" in agent.last_user_message
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


def test_qa_tester_agent_execute_uses_default_module_name_and_test_artifact(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="tests",
        task_title="Tests",
        task_description="Write tests",
        project_name="Demo",
        project_goal="Build demo",
        context={"code": "def add(a, b): return a + b"},
    )

    result = agent.execute(agent_input)

    assert "Module name: module" in agent.last_user_message
    assert result.artifacts[0].artifact_type == ArtifactType.TEST
    assert result.artifacts[0].name == "tests_tests"


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
        },
    )

    result = agent.execute(agent_input)

    assert "Code summary: Core API and worker layer" in agent.last_user_message
    assert "def fallback(): pass" not in agent.last_user_message
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

    assert "Project License: Apache-2.0" in agent.last_user_message
    assert "Not specified" in agent.last_user_message
    assert result.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert result.artifacts[0].name == "legal_legal_analysis"