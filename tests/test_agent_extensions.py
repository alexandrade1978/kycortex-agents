import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.types import AgentInput, AgentOutput


def build_input(**overrides):
    payload = {
        "task_id": "task-1",
        "task_title": "Task",
        "task_description": "Run extension hook test",
        "project_name": "Demo",
        "project_goal": "Validate hooks",
        "context": {"architecture": "Layered design"},
    }
    payload.update(overrides)
    return AgentInput(**payload)


class RecordingExtensionAgent(BaseAgent):
    required_context_keys = ("architecture",)

    def __init__(self):
        super().__init__("Recorder", "Testing", KYCortexConfig(output_dir="./output_test", api_key="token"))
        self.events = []

    def validate_input(self, agent_input: AgentInput) -> None:
        self.events.append("validate_input")
        super().validate_input(agent_input)

    def before_execute(self, agent_input: AgentInput) -> None:
        self.events.append("before_execute")
        agent_input.context["before_hook"] = True

    def run(self, task_description: str, context: dict) -> AgentOutput:
        self.events.append("run")
        return AgentOutput(
            summary="Hook summary",
            raw_content=f"before_hook={context['before_hook']}",
            metadata={"from_run": True},
        )

    def after_execute(self, agent_input: AgentInput, output: AgentOutput) -> AgentOutput:
        self.events.append("after_execute")
        output = super().after_execute(agent_input, output)
        output.summary = f"post-processed: {output.summary}"
        output.metadata["after_hook"] = True
        return output

    def validate_output(self, output: AgentOutput) -> None:
        self.events.append("validate_output")
        super().validate_output(output)


class RejectingInputAgent(BaseAgent):
    def __init__(self):
        super().__init__("RejectInput", "Testing", KYCortexConfig(output_dir="./output_test", api_key="token"))

    def validate_input(self, agent_input: AgentInput) -> None:
        super().validate_input(agent_input)
        raise AgentExecutionError("RejectInput: custom input validation failed")

    def run(self, task_description: str, context: dict) -> str:
        raise AssertionError("run should not execute when validate_input fails")


class RejectingOutputAgent(BaseAgent):
    def __init__(self):
        super().__init__("RejectOutput", "Testing", KYCortexConfig(output_dir="./output_test", api_key="token"))

    def run(self, task_description: str, context: dict) -> str:
        return "raw output"

    def validate_output(self, output: AgentOutput) -> None:
        super().validate_output(output)
        raise AgentExecutionError("RejectOutput: custom output validation failed")


class ErrorHandlingAgent(BaseAgent):
    def __init__(self):
        super().__init__("ErrorHandler", "Testing", KYCortexConfig(output_dir="./output_test", api_key="token"))
        self.handled_errors = []

    def run(self, task_description: str, context: dict) -> str:
        raise RuntimeError("boom")

    def on_execution_error(self, agent_input: AgentInput, exc: Exception) -> None:
        self.handled_errors.append((agent_input.task_id, type(exc).__name__))
        raise AgentExecutionError(f"{self.name}: handled {type(exc).__name__}") from exc


def test_extension_hooks_run_in_supported_order_and_can_mutate_output():
    agent = RecordingExtensionAgent()

    result = agent.execute(build_input())

    assert result.summary == "post-processed: Hook summary"
    assert result.raw_content == "before_hook=True"
    assert result.metadata["from_run"] is True
    assert result.metadata["after_hook"] is True
    assert result.metadata["agent_name"] == "Recorder"
    assert agent.events == [
        "validate_input",
        "before_execute",
        "run",
        "after_execute",
        "validate_output",
    ]


def test_custom_validate_input_can_abort_execution_before_run():
    agent = RejectingInputAgent()

    with pytest.raises(AgentExecutionError, match="custom input validation failed"):
        agent.execute(build_input())


def test_custom_validate_output_can_reject_normalized_output():
    agent = RejectingOutputAgent()

    with pytest.raises(AgentExecutionError, match="custom output validation failed"):
        agent.execute(build_input(context={}))


def test_on_execution_error_can_replace_default_runtime_error():
    agent = ErrorHandlingAgent()

    with pytest.raises(AgentExecutionError, match="ErrorHandler: handled RuntimeError"):
        agent.execute(build_input(context={}))

    assert agent.handled_errors == [("task-1", "RuntimeError")]


def test_required_context_keys_remain_enforced_for_extension_agents():
    agent = RecordingExtensionAgent()

    with pytest.raises(AgentExecutionError, match="required context key 'architecture'"):
        agent.execute(build_input(context={}))