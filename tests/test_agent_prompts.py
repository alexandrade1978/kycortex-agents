import pytest

from kycortex_agents.agents.architect import ArchitectAgent
from kycortex_agents.agents.code_engineer import CodeEngineerAgent
from kycortex_agents.agents.code_reviewer import CodeReviewerAgent
from kycortex_agents.agents.docs_writer import DocsWriterAgent
from kycortex_agents.agents.legal_advisor import LegalAdvisorAgent
from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.types import AgentInput


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


def test_architect_agent_uses_typed_input_fields(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="arch",
        task_title="Architecture",
        task_description="Design the system",
        project_name="Demo",
        project_goal="Build demo",
        constraints=["Python 3.12", "No GPL dependencies"],
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Project Name: Demo" in agent.last_user_message
    assert "Project Goal: Build demo" in agent.last_user_message
    assert "Python 3.12, No GPL dependencies" in agent.last_user_message


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
        context={"code": "print('hello')"},
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Project: Demo" in agent.last_user_message
    assert "print('hello')" in agent.last_user_message


def test_qa_tester_uses_module_name_when_provided(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="test",
        task_title="Tests",
        task_description="Write tests",
        project_name="Demo",
        project_goal="Build demo",
        context={"code": "def add(a, b): return a + b", "module_name": "math_utils"},
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Module name: math_utils" in agent.last_user_message


def test_docs_writer_falls_back_to_code_for_summary(tmp_path):
    agent = CaptureDocsWriterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="docs",
        task_title="Docs",
        task_description="Write documentation",
        project_name="Demo",
        project_goal="Build demo",
        context={"architecture": "Layered design", "code": "def main(): pass"},
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Goal: Build demo" in agent.last_user_message
    assert "Code summary: def main(): pass" in agent.last_user_message


def test_legal_advisor_formats_dependencies_from_typed_context(tmp_path):
    agent = CaptureLegalAdvisorAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="legal",
        task_title="Legal",
        task_description="Review licensing",
        project_name="Demo",
        project_goal="Build demo",
        context={"license": "Apache-2.0", "dependencies": ["openai", "anthropic"]},
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "- openai" in agent.last_user_message
    assert "- anthropic" in agent.last_user_message