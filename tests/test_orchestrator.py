import ast
import os
import pathlib
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest
import kycortex_agents.orchestrator as orchestrator_module

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.dependency_manager import DependencyManagerAgent
from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider
from kycortex_agents.types import AgentOutput, ArtifactRecord, ArtifactType, DecisionRecord, FailureCategory, TaskStatus, WorkflowOutcome, WorkflowStatus


class RecordingAgent:
    def __init__(self, response: str):
        self.response = response
        self.last_description: str = ""
        self.last_context: dict[str, Any] = {}
        self.last_input: Any = None

    def run_with_input(self, agent_input: Any) -> str:
        self.last_input = agent_input
        return self.run(agent_input.task_description, agent_input.context)

    def run(self, task_description: str, context: dict[str, Any]) -> str:
        self.last_description = task_description
        self.last_context = context
        return self.response


class FailingAgent:
    def run(self, task_description: str, context: dict) -> str:
        raise RuntimeError("boom")


class FlakyAgent:
    def __init__(self, failures_before_success: int, success_response: str):
        self.failures_before_success = failures_before_success
        self.success_response = success_response
        self.calls = 0

    def run(self, task_description: str, context: dict) -> str:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError(f"boom-{self.calls}")
        return self.success_response


class AgentExecutionFlakyAgent:
    def __init__(self, failures_before_success: int, success_response: str, error_message: str):
        self.failures_before_success = failures_before_success
        self.success_response = success_response
        self.error_message = error_message
        self.calls = 0

    def run(self, task_description: str, context: dict) -> str:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise AgentExecutionError(self.error_message)
        return self.success_response


class StructuredAgent:
    def execute(self, agent_input) -> AgentOutput:
        return AgentOutput(
            summary="Decision summary",
            raw_content="STRUCTURED OUTPUT",
            artifacts=[
                ArtifactRecord(
                    name="architecture_doc",
                    artifact_type=ArtifactType.DOCUMENT,
                    path="artifacts/architecture.md",
                )
            ],
            decisions=[
                DecisionRecord("stack", "Use typed runtime", "Enables contract validation")
            ],
        )


class PausingAgent:
    def __init__(self, responses: list[str], project: ProjectState, pause_reason: str):
        self.responses = list(responses)
        self.project = project
        self.pause_reason = pause_reason
        self.calls = 0

    def run(self, task_description: str, context: dict[str, Any]) -> str:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if self.calls == 1:
            self.project.pause_workflow(reason=self.pause_reason)
        return response


class CancellingAgent:
    def __init__(self, responses: list[str], project: ProjectState, cancel_reason: str):
        self.responses = list(responses)
        self.project = project
        self.cancel_reason = cancel_reason
        self.calls = 0

    def run(self, task_description: str, context: dict[str, Any]) -> str:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if self.calls == 1:
            self.project.cancel_workflow(reason=self.cancel_reason)
        return response


class FakeHTTPResponse:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class CompletedProcessStub:
    def __init__(self, returncode: int = 0, stdout: str = "1 passed in 0.01s", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def supports_user_xattrs(target_path: pathlib.Path) -> bool:
    if not all(hasattr(os, name) for name in ("getxattr", "listxattr", "setxattr", "removexattr")):
        return False

    attribute_name = "user.kycortex_probe"
    attribute_value = b"probe"

    try:
        os.setxattr(target_path, attribute_name, attribute_value)
        listed_names = os.listxattr(target_path)
        loaded_value = os.getxattr(target_path, attribute_name)
    except OSError:
        return False
    finally:
        try:
            os.removexattr(target_path, attribute_name)
        except OSError:
            pass

    return attribute_name in listed_names and loaded_value == attribute_value


def build_openai_client(response=None, error=None, health_response=None, health_error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    def list_models(**kwargs):
        if health_error is not None:
            raise health_error
        return health_response if health_response is not None else []

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        models=SimpleNamespace(list=list_models),
    )


def build_anthropic_client(response=None, error=None, health_response=None, health_error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    def list_models(**kwargs):
        if health_error is not None:
            raise health_error
        return health_response if health_response is not None else []

    return SimpleNamespace(
        messages=SimpleNamespace(create=create),
        models=SimpleNamespace(list=list_models),
    )


def build_ollama_opener(
    payload=None,
    error=None,
    health_payload='{"models": [{"name": "llama3:latest"}]}',
    health_error=None,
):
    health_calls = 0
    generate_calls = 0

    def current_value(value, index):
        if isinstance(value, list):
            return value[min(index, len(value) - 1)]
        return value

    def open_request(request, timeout=None):
        nonlocal health_calls, generate_calls
        url = getattr(request, "full_url", None)
        if url is None and hasattr(request, "get_full_url"):
            url = request.get_full_url()
        if isinstance(url, str) and url.endswith("/api/tags"):
            current_payload = current_value(health_payload if health_payload is not None else payload, health_calls)
            current_error = current_value(health_error if health_error is not None else error, health_calls)
            health_calls += 1
        else:
            current_payload = current_value(payload, generate_calls)
            current_error = current_value(error, generate_calls)
            generate_calls += 1
        if current_error is not None:
            raise current_error
        assert isinstance(current_payload, str)
        return FakeHTTPResponse(current_payload)

    return open_request


def parse_function_node(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    node = ast.parse(source).body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return node


def parse_call_node(source: str) -> ast.Call:
    node = ast.parse(source, mode="eval").body
    assert isinstance(node, ast.Call)
    return node


def parse_expr_node(source: str) -> ast.expr:
    return ast.parse(source, mode="eval").body


def parse_assert_node(source: str) -> ast.Assert:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.Assert)
    return node


def parse_with_node(source: str) -> ast.With | ast.AsyncWith:
    node = ast.parse(source).body[0]
    assert isinstance(node, (ast.With, ast.AsyncWith))
    return node


def parse_ann_assign_node(source: str) -> ast.AnnAssign:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.AnnAssign)
    return node


def require_task(project: ProjectState, task_id: str) -> Task:
    task = project.get_task(task_id)
    assert task is not None
    return task


def require_output_payload(task: Task) -> dict[str, Any]:
    assert task.output_payload is not None
    return task.output_payload


def require_test_validation(task: Task) -> dict[str, Any]:
    return cast(dict[str, Any], require_output_payload(task)["metadata"]["validation"]["test_analysis"])


def require_artifact(project: ProjectState, index: int = 0) -> dict[str, Any]:
    artifact = project.artifacts[index]
    assert isinstance(artifact, dict)
    return artifact


def test_run_task_exposes_semantic_context(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
        )
    )

    agent = RecordingAgent("IMPLEMENTED CODE")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"code_engineer": agent}))

    result = orchestrator.run_task(project.tasks[1], project)

    assert result == "IMPLEMENTED CODE"
    assert project.tasks[1].status == TaskStatus.DONE.value
    assert agent.last_description == "Implement the application"
    assert agent.last_input.task_id == "code"
    assert agent.last_input.project_name == "Demo"
    assert agent.last_context["architecture"] == "ARCHITECTURE DOC"
    assert agent.last_context["completed_tasks"]["arch"] == "ARCHITECTURE DOC"
    assert agent.last_context["task"]["id"] == "code"
    assert agent.last_context["snapshot"]["project_name"] == "Demo"
    assert agent.last_context["module_name"] == "code_implementation"
    assert agent.last_context["module_filename"] == "code_implementation.py"


def test_run_task_redacts_sensitive_agent_input_and_context(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo api_key=sk-secret-123456")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design with Authorization: Bearer sk-ant-secret-987654",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="api_key=sk-secret-123456",
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests password=hunter2",
            description="Fix Authorization: Bearer sk-ant-secret-987654",
            assigned_to="qa_tester",
            repair_context={
                "repair_owner": "qa_tester",
                "failure_message": "api_key=sk-secret-123456",
                "validation_summary": "Authorization: Bearer sk-ant-secret-987654",
                "failed_output": "password=hunter2",
            },
        )
    )

    agent = RecordingAgent("TESTS FIXED")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    result = orchestrator.run_task(project.tasks[1], project)

    assert result == "TESTS FIXED"
    assert "sk-ant-secret-987654" not in agent.last_description
    assert "[REDACTED]" in agent.last_description
    assert agent.last_input.project_goal == "Build demo api_key=[REDACTED]"
    assert agent.last_context["goal"] == "Build demo api_key=[REDACTED]"
    assert agent.last_context["task"]["description"] == "Fix Authorization: Bearer [REDACTED]"
    assert agent.last_context["architecture"] == "api_key=[REDACTED]"
    assert agent.last_context["completed_tasks"]["arch"] == "api_key=[REDACTED]"
    assert agent.last_context["repair_context"] == {"repair_owner": "qa_tester"}
    assert agent.last_context["existing_tests"] == "password=[REDACTED]"
    assert agent.last_context["test_validation_summary"] == "Authorization: Bearer [REDACTED]"
    assert agent.last_context["snapshot"]["goal"] == "Build demo api_key=[REDACTED]"


def test_run_task_exposes_generated_code_module_context_to_downstream_agents(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def main():\n    return 1",
            output_payload={
                "summary": "def main():",
                "raw_content": "def main():\n    return 1",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def main():\n    return 1",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent("TESTS")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    orchestrator.run_task(project.tasks[1], project)

    assert agent.last_context["code"] == "def main():\n    return 1"
    assert agent.last_context["module_name"] == "code_implementation"
    assert agent.last_context["module_filename"] == "code_implementation.py"
    assert agent.last_context["code_artifact_path"] == "artifacts/code_implementation.py"
    assert agent.last_context["code_summary"] == "def main():"
    assert agent.last_context["code_outline"] == "def main():"
    assert "Functions:" in agent.last_context["code_public_api"]
    assert "main()" in agent.last_context["code_public_api"]
    assert agent.last_context["module_run_command"] == ""


def test_run_task_uses_repair_owner_and_failure_context_for_code_validation(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
        )
    )
    project.add_task(
        Task(
            id="repair",
            title="Repair implementation",
            description="Review the implementation",
            assigned_to="code_reviewer",
            status=TaskStatus.PENDING.value,
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.CODE_VALIDATION.value,
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module so it becomes syntactically valid and internally consistent.",
                "validation_summary": "Generated code validation:\n- Syntax OK: no\n- Syntax error: '[' was never closed",
                "failed_output": "def broken(:\n    pass",
                "failed_artifact_content": "def broken(:\n    pass",
            },
        )
    )

    engineer = RecordingAgent("def repaired() -> int:\n    return 1")
    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry({"code_engineer": engineer, "code_reviewer": FailingAgent()}),
    )

    result = orchestrator.run_task(project.tasks[1], project)
    repair_task = project.get_task("repair")

    assert repair_task is not None

    assert result == "def repaired() -> int:\n    return 1"
    assert repair_task.status == TaskStatus.DONE.value
    assert engineer.last_context["repair_context"] == {
        "cycle": 1,
        "failure_category": FailureCategory.CODE_VALIDATION.value,
        "repair_owner": "code_engineer",
    }
    assert engineer.last_context["existing_code"] == "def broken(:\n    pass"
    assert engineer.last_context["repair_validation_summary"].startswith("Generated code validation:")
    assert "Repair objective:" in engineer.last_description
    assert "Previous failure category: code_validation" in engineer.last_description


def test_classify_task_failure_returns_provider_transient_for_provider_errors(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="arch",
        title="Architecture",
        description="Design the architecture",
        assigned_to="architect",
    )

    category = orchestrator._classify_task_failure(task, ProviderTransientError("provider temporarily unavailable"))

    assert category == FailureCategory.PROVIDER_TRANSIENT.value


def test_classify_task_failure_returns_sandbox_violation_for_blocked_operations(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="tests",
        title="Tests",
        description="Write tests",
        assigned_to="qa_tester",
    )

    category = orchestrator._classify_task_failure(
        task,
        RuntimeError("sandbox policy blocked filesystem write outside sandbox root"),
    )

    assert category == FailureCategory.SANDBOX_SECURITY_VIOLATION.value


def test_classify_task_failure_falls_back_to_task_execution_for_unmapped_agent_errors(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="arch",
        title="Architecture",
        description="Design the architecture",
        assigned_to="architect",
    )

    category = orchestrator._classify_task_failure(task, AgentExecutionError("unexpected validation failure"))

    assert category == FailureCategory.TASK_EXECUTION.value


def test_is_sandbox_security_violation_returns_false_for_unrelated_errors(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._is_sandbox_security_violation(RuntimeError("provider temporarily unavailable")) is False


def test_parse_behavior_contract_supports_all_rule_shapes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    contract = "\n".join(
        [
            "- intake_request requires fields: request_id, compliance_data",
            "- intake_request expects field `status` to be one of: approved, denied",
            "- process_batch expects each batch item to include key `request_id` and nested `payload` fields: compliance_data, status",
            "- process_requests expects each batch item to include: request_id, compliance_data",
            "- process_nested expects nested `payload` fields: compliance_data, status",
            "This line should be ignored",
        ]
    )

    validation_rules, field_value_rules, batch_rules, sequence_input_functions = orchestrator._parse_behavior_contract(
        contract
    )

    assert validation_rules == {"intake_request": ["request_id", "compliance_data"]}
    assert field_value_rules == {"intake_request": {"status": ["approved", "denied"]}}
    assert batch_rules == {
        "process_batch": {
            "request_key": "request_id",
            "wrapper_key": "payload",
            "fields": ["compliance_data", "status"],
        },
        "process_requests": {
            "request_key": None,
            "wrapper_key": None,
            "fields": ["request_id", "compliance_data"],
        },
        "process_nested": {
            "request_key": None,
            "wrapper_key": "payload",
            "fields": ["compliance_data", "status"],
        },
    }
    assert sequence_input_functions == set()


def test_parse_behavior_contract_ignores_blank_and_non_matching_entries(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    contract = "\n".join(
        [
            "  ",
            "- intake_request requires fields: , , ",
            "- intake_request expects field `status` to be one of: , , ",
            "- process_batch expects each batch item to include: , , ",
            "not a rule",
        ]
    )

    validation_rules, field_value_rules, batch_rules, sequence_input_functions = orchestrator._parse_behavior_contract(
        contract
    )

    assert validation_rules == {}
    assert field_value_rules == {}
    assert batch_rules == {"process_batch": {"request_key": None, "wrapper_key": None, "fields": []}}
    assert sequence_input_functions == set()


def test_summarize_pytest_output_handles_empty_and_fallback_cases(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._summarize_pytest_output("", "", 5) == "pytest exited with code 5"
    assert orchestrator._summarize_pytest_output("line one", "line two", 1) == "line two"


def test_validate_test_output_rejects_syntax_invalid_code_under_test(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(summary="tests", raw_content="def test_ok():\n    assert True")

    with pytest.raises(AgentExecutionError, match="code under test has syntax error invalid syntax"):
        orchestrator._validate_test_output(
            {
                "code_analysis": {"syntax_ok": False, "syntax_error": "invalid syntax"},
                "module_name": "code_implementation",
                "code": "def broken(:\n    pass",
            },
            output,
        )


def test_validate_test_output_uses_default_module_filename_when_missing(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(summary="tests", raw_content="def test_ok():\n    assert True")
    captured: dict[str, str] = {}

    monkeypatch.setattr(orchestrator, "_analyze_test_module", lambda *args, **kwargs: {"syntax_ok": True})

    def fake_execute_generated_tests(module_filename, code_content, test_filename, test_content):
        captured["module_filename"] = module_filename
        captured["test_filename"] = test_filename
        return {"ran": False, "returncode": None, "summary": "skipped"}

    monkeypatch.setattr(orchestrator, "_execute_generated_tests", fake_execute_generated_tests)

    orchestrator._validate_test_output(
        {
            "module_name": "code_implementation",
            "module_filename": "   ",
            "code": "def ok():\n    return 1",
        },
        output,
    )

    assert captured == {"module_filename": "code_implementation.py", "test_filename": "tests_tests.py"}


def test_validate_test_output_returns_early_when_context_is_incomplete(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(summary="tests", raw_content="def test_ok():\n    assert True")

    monkeypatch.setattr(
        orchestrator,
        "_execute_generated_tests",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not execute generated tests")),
    )

    assert orchestrator._validate_test_output({"module_name": "", "code": "def ok():\n    return 1"}, output) is None
    assert orchestrator._validate_test_output({"module_name": "code_implementation", "code": "   "}, output) is None


def test_validate_test_output_surfaces_syntax_analysis_and_pytest_failures(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(summary="tests", raw_content="def test_ok():\n    assert True")

    monkeypatch.setattr(
        orchestrator,
        "_analyze_test_module",
        lambda *args, **kwargs: {
            "syntax_ok": False,
            "missing_function_imports": ["missing_helper"],
            "unsafe_entrypoint_calls": ["main()"],
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "_execute_generated_tests",
        lambda *args, **kwargs: {"ran": True, "returncode": 1, "summary": ""},
    )

    with pytest.raises(AgentExecutionError) as excinfo:
        orchestrator._validate_test_output(
            {
                "module_name": "code_implementation",
                "code": "def ok():\n    return 1",
            },
            output,
        )

    message = str(excinfo.value)
    assert "test syntax error unknown syntax error" in message
    assert "missing function imports: missing_helper" in message
    assert "unsafe entrypoint calls: main()" in message
    assert "pytest failed: generated tests failed" in message


def test_validate_code_output_rejects_missing_required_cli_entrypoint(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(summary="code", raw_content="def run() -> int:\n    return 1\n")
    task = Task(
        id="code",
        title="Implementation",
        description="Write one module with a CLI demo entrypoint.",
        assigned_to="code_engineer",
    )

    with pytest.raises(AgentExecutionError, match="missing required CLI entrypoint"):
        orchestrator._validate_code_output(output, task=task)


def test_validate_test_output_rejects_line_budget_overrun(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(
        summary="tests",
        raw_content="def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n",
    )
    task = Task(
        id="tests",
        title="Tests",
        description="Write tests under 3 lines.",
        assigned_to="qa_tester",
    )

    monkeypatch.setattr(orchestrator, "_analyze_test_module", lambda *args, **kwargs: {"syntax_ok": True})
    monkeypatch.setattr(
        orchestrator,
        "_execute_generated_tests",
        lambda *args, **kwargs: {"available": True, "ran": False, "returncode": None, "summary": "not-run"},
    )

    with pytest.raises(AgentExecutionError, match="line count 6 exceeds maximum 3"):
        orchestrator._validate_test_output(
            {
                "module_name": "code_implementation",
                "code": "def ok():\n    return 1",
            },
            output,
            task=task,
        )


def test_validate_task_output_uses_repair_owner_role_for_validation(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="repair",
        title="Repair",
        description="Write one module with a CLI demo entrypoint.",
        assigned_to="code_reviewer",
        repair_context={"repair_owner": "code_engineer"},
    )
    output = AgentOutput(summary="code", raw_content="def run() -> int:\n    return 1\n")

    with pytest.raises(AgentExecutionError, match="missing required CLI entrypoint"):
        orchestrator._validate_task_output(task, {}, output)


def test_validate_code_output_rejects_line_budget_overrun_and_truncation(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(summary="code", raw_content="def run():\n    return 1\n")
    task = Task(
        id="code",
        title="Implementation",
        description="Write one module under 1 line.",
        assigned_to="code_engineer",
    )

    monkeypatch.setattr(
        orchestrator,
        "_analyze_python_module",
        lambda *args, **kwargs: {"syntax_ok": True, "has_main_guard": True, "third_party_imports": []},
    )
    monkeypatch.setattr(
        orchestrator,
        "_completion_diagnostics_from_output",
        lambda *args, **kwargs: {"likely_truncated": True, "hit_token_limit": True},
    )

    with pytest.raises(
        AgentExecutionError,
        match="line count 2 exceeds maximum 1; output likely truncated at the completion token limit",
    ):
        orchestrator._validate_code_output(output, task=task)


def test_validate_code_output_rejects_import_time_errors(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(
        summary="code",
        raw_content=(
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class Broken:\n"
            "    label: str = ''\n"
            "    value: int\n"
        ),
    )
    task = Task(
        id="code",
        title="Implementation",
        description="Write one Python module.",
        assigned_to="code_engineer",
    )

    with pytest.raises(
        AgentExecutionError,
        match="module import failed: TypeError: non-default argument 'value' follows default argument",
    ):
        orchestrator._validate_code_output(output, task=task)


def test_validate_code_output_skips_import_validation_for_third_party_imports(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(summary="code", raw_content="import requests\n")
    task = Task(
        id="code",
        title="Implementation",
        description="Write one Python module.",
        assigned_to="code_engineer",
    )

    monkeypatch.setattr(
        orchestrator,
        "_analyze_python_module",
        lambda *args, **kwargs: {
            "syntax_ok": True,
            "has_main_guard": True,
            "third_party_imports": ["requests"],
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "_execute_generated_module_import",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run import validation")),
    )

    assert orchestrator._validate_code_output(output, task=task) is None


def test_classify_task_failure_returns_workflow_definition_for_definition_errors(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="arch",
        title="Architecture",
        description="Design the architecture",
        assigned_to="architect",
    )

    category = orchestrator._classify_task_failure(task, WorkflowDefinitionError("invalid workflow"))

    assert category == FailureCategory.WORKFLOW_DEFINITION.value


def test_artifact_helpers_return_matching_content_and_filename(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(
        summary="artifacts",
        raw_content="fallback",
        artifacts=[
            ArtifactRecord(name="note", artifact_type=ArtifactType.TEXT, content="ignored"),
            ArtifactRecord(name="code", artifact_type=ArtifactType.CODE, content="   "),
            ArtifactRecord(
                name="tests",
                artifact_type=ArtifactType.TEST,
                path="nested/generated_tests.py",
                content="def test_ok():\n    assert True",
            ),
            ArtifactRecord(
                name="module",
                artifact_type=ArtifactType.CODE,
                path="artifacts/generated_module.py",
                content="def ok():\n    return 1",
            ),
        ],
    )

    assert orchestrator._artifact_content(output, ArtifactType.CODE) == "def ok():\n    return 1"
    assert orchestrator._artifact_filename(output, ArtifactType.TEST, "default_test.py") == "generated_tests.py"
    assert orchestrator._artifact_filename(output, ArtifactType.DOCUMENT, "default_doc.md") == "default_doc.md"


def test_record_output_validation_ignores_non_mapping_validation_metadata(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(summary="tests", raw_content="ok", metadata={"validation": "invalid"})

    orchestrator._record_output_validation(output, "test_analysis", {"syntax_ok": True})

    assert output.metadata["validation"] == "invalid"


def test_should_validate_content_helpers_cover_typed_and_blank_cases(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._should_validate_code_content("anything", has_typed_artifact=True) is True
    assert orchestrator._should_validate_code_content("   ", has_typed_artifact=False) is False
    assert orchestrator._should_validate_code_content("plain prose only", has_typed_artifact=False) is False
    assert orchestrator._should_validate_test_content("anything", has_typed_artifact=True) is True
    assert orchestrator._should_validate_test_content("   ", has_typed_artifact=False) is False
    assert orchestrator._should_validate_test_content("plain prose only", has_typed_artifact=False) is False


def test_execute_generated_tests_returns_unavailable_when_pytest_missing(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    monkeypatch.setattr(orchestrator_module.importlib.util, "find_spec", lambda name: None)

    result = orchestrator._execute_generated_tests(
        "generated_module.py",
        "def ok():\n    return 1",
        "generated_tests.py",
        "def test_ok():\n    assert True",
    )

    assert result == {
        "available": False,
        "ran": False,
        "returncode": None,
        "summary": "pytest is not installed in the current environment",
    }


def test_execute_generated_tests_returns_early_for_blank_inputs(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "generated_module.py",
        "   ",
        "generated_tests.py",
        "def test_ok():\n    assert True",
    )

    assert result == {
        "available": True,
        "ran": False,
        "returncode": None,
        "summary": "generated code or tests were empty",
    }


def test_execute_generated_module_import_reports_import_time_errors(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_module_import(
        "generated_module.py",
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class Broken:\n"
        "    label: str = ''\n"
        "    value: int\n",
    )

    assert result["ran"] is True
    assert result["returncode"] != 0
    assert "TypeError: non-default argument 'value' follows default argument" in result["summary"]


def test_execute_generated_module_import_redacts_sensitive_subprocess_output(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setattr(
        orchestrator_module.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcessStub(
            returncode=1,
            stdout="api_key=sk-secret-123456",
            stderr="Authorization: Bearer sk-ant-secret-987654",
        ),
    )

    result = orchestrator._execute_generated_module_import(
        "generated_module.py",
        "def ok():\n    return 1\n",
    )

    assert result["ran"] is True
    assert result["returncode"] == 1
    assert "sk-secret-123456" not in result["stdout"]
    assert "sk-ant-secret-987654" not in result["stderr"]
    assert "sk-ant-secret-987654" not in result["summary"]
    assert "[REDACTED]" in result["stdout"]
    assert "[REDACTED]" in result["stderr"]
    assert "[REDACTED]" in result["summary"]


def test_execute_generated_tests_uses_explicit_wall_clock_budget(tmp_path, monkeypatch):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        timeout_seconds=2,
        execution_sandbox_max_wall_clock_seconds=7,
    )
    orchestrator = Orchestrator(config)
    captured_timeout: dict[str, float] = {}

    def raise_timeout(*args, **kwargs):
        captured_timeout["value"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(orchestrator_module.subprocess, "run", raise_timeout)

    result = orchestrator._execute_generated_tests(
        "generated_module.py",
        "def ok():\n    return 1",
        "generated_tests.py",
        "def test_ok():\n    assert True",
    )

    assert result == {
        "available": True,
        "ran": True,
        "returncode": -1,
        "summary": "pytest timed out after 7 seconds",
    }
    assert captured_timeout["value"] == 7


def test_sanitize_generated_filename_appends_default_suffix_when_missing(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._sanitize_generated_filename("generated tests", "generated_tests.py") == "generated_tests.py"
    assert orchestrator._sanitize_generated_filename("custom-name", "generated_tests.py") == "custom-name.py"


def test_provider_call_metadata_uses_agent_getter_when_output_has_no_metadata(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    class MetadataAgent:
        def get_last_provider_call_metadata(self):
            return {
                "provider": "openai",
                "model": "gpt-test",
                "base_url": "https://alice:secret-pass@example.com/v1",
                "error_type": "RuntimeError",
                "error_message": "api_key=sk-secret-123456",
                "provider_call_count": 2,
                "provider_max_calls_per_agent": 3,
                "provider_remaining_calls": 1,
            }

    metadata = orchestrator._provider_call_metadata(MetadataAgent(), AgentOutput(summary="ok", raw_content="ok"))

    assert metadata is not None
    assert metadata["provider"] == "openai"
    assert metadata["model"] == "gpt-test"
    assert "secret-pass" not in str(metadata)
    assert "sk-secret-123456" not in str(metadata)
    assert "[REDACTED]" in metadata["base_url"]
    assert metadata["has_error_type"] is True
    assert "error_type" not in metadata
    assert metadata["has_error_message"] is True
    assert "error_message" not in metadata
    assert metadata["provider_call_budget_limited"] is True
    assert metadata["provider_call_budget_exhausted"] is False
    assert metadata["provider_call_budget_limited_providers"] == []
    assert metadata["provider_call_budget_exhausted_providers"] == []
    assert "provider_call_count" not in metadata


def test_provider_call_metadata_redacts_sensitive_output_metadata(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    output = AgentOutput(
        summary="ok",
        raw_content="ok",
        metadata={
            "provider_call": {
                "provider": "anthropic",
                "model": "claude-test",
                "base_url": "https://bob:secret-pass@example.com/messages",
                "error_type": "ProviderTransientError",
                "error_message": "Authorization: Bearer sk-ant-secret-987654",
                "provider_cancellation_reason": "operator requested stop api_key=sk-ant-secret-987654",
                "provider_timeout_seconds_by_provider": {"anthropic": 22.0},
                "provider_call_counts_by_provider": {"anthropic": 1},
                "provider_max_calls_per_provider": {"anthropic": 1},
                "provider_remaining_calls_by_provider": {"anthropic": 0},
                "fallback_history": [
                    {
                        "provider": "anthropic",
                        "model": "claude-test",
                        "status": "failed_call_budget_exhausted",
                        "provider_call_count": 1,
                        "provider_max_calls": 1,
                        "error_message": "Authorization: Bearer sk-ant-secret-987654",
                    }
                ],
            }
        },
    )

    metadata = orchestrator._provider_call_metadata(object(), output)

    assert metadata is not None
    assert metadata["provider"] == "anthropic"
    assert metadata["model"] == "claude-test"
    assert "active_provider" not in metadata
    assert "active_model" not in metadata
    assert "secret-pass" not in str(metadata)
    assert "sk-ant-secret-987654" not in str(metadata)
    assert "[REDACTED]" in metadata["base_url"]
    assert metadata["has_error_type"] is True
    assert "error_type" not in metadata
    assert metadata["has_error_message"] is True
    assert "error_message" not in metadata
    assert metadata["provider_call_budget_limited"] is True
    assert metadata["provider_call_budget_exhausted"] is False
    assert metadata["provider_call_budget_limited_providers"] == ["anthropic"]
    assert metadata["provider_call_budget_exhausted_providers"] == ["anthropic"]
    assert metadata["has_provider_cancellation_reason"] is True
    assert "provider_cancellation_reason" not in metadata
    assert "provider_timeout_provider_count" not in metadata
    assert "provider_timeout_seconds_by_provider" not in metadata
    assert metadata["fallback_history"] == [
        {
            "provider": "anthropic",
            "status": "failed_call_budget_exhausted",
            "has_error_message": True,
        }
    ]
    assert "model" not in metadata["fallback_history"][0]
    assert "provider_call_counts_by_provider" not in metadata


def test_persist_artifacts_writes_content_and_updates_relative_path(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    artifacts = [
        ArtifactRecord(name="blank", artifact_type=ArtifactType.TEXT, content="   ", path="ignored.txt"),
        ArtifactRecord(name="Report Draft", artifact_type=ArtifactType.DOCUMENT, content="hello", path="reports/final draft.md"),
    ]

    orchestrator._persist_artifacts(artifacts)

    persisted_path = tmp_path / "output" / "reports" / "final_draft.md"
    assert artifacts[0].path == "ignored.txt"
    assert artifacts[1].path == "reports/final_draft.md"
    assert persisted_path.read_text(encoding="utf-8") == "hello"


def test_persist_artifacts_redacts_sensitive_content_before_disk_write(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    artifacts = [
        ArtifactRecord(
            name="credentials",
            artifact_type=ArtifactType.TEXT,
            content="api_key=sk-secret-123456\nAuthorization: Bearer sk-ant-secret-987654",
            path="artifacts/credentials.txt",
        )
    ]

    orchestrator._persist_artifacts(artifacts)

    persisted_path = tmp_path / "output" / "artifacts" / "credentials.txt"
    persisted_content = persisted_path.read_text(encoding="utf-8")

    assert "sk-secret-123456" not in persisted_content
    assert "sk-ant-secret-987654" not in persisted_content
    assert persisted_content == "api_key=[REDACTED]\nAuthorization: Bearer [REDACTED]"
    assert artifacts[0].content == persisted_content


def test_persist_artifacts_rejects_symlinked_output_path_escape(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_root = tmp_path / "escaped"
    escaped_root.mkdir()
    (tmp_path / "output").mkdir()
    linked_dir = tmp_path / "output" / "artifacts"
    linked_dir.symlink_to(escaped_root, target_is_directory=True)
    artifacts = [
        ArtifactRecord(
            name="Report Draft",
            artifact_type=ArtifactType.DOCUMENT,
            content="hello",
            path="artifacts/final.md",
        )
    ]

    with pytest.raises(AgentExecutionError, match="resolves outside the output directory"):
        orchestrator._persist_artifacts(artifacts)

    assert not (escaped_root / "final.md").exists()
    assert artifacts[0].path == "artifacts/final.md"


def test_sanitize_artifact_relative_path_rejects_invalid_segments_and_empty_paths(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._sanitize_artifact_relative_path("reports/./summary.md") == pathlib.Path("reports/summary.md")

    with pytest.raises(AgentExecutionError, match="artifact path must not be empty"):
        orchestrator._sanitize_artifact_relative_path(".")


def test_sanitize_artifact_relative_path_rejects_defensive_invalid_segment(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    real_sub = orchestrator_module.re.sub

    def fake_sub(pattern, replacement, value):
        if value == "unsafe":
            return "."
        return real_sub(pattern, replacement, value)

    monkeypatch.setattr(orchestrator_module.re, "sub", fake_sub)

    with pytest.raises(AgentExecutionError, match="artifact path contains an invalid segment"):
        orchestrator._sanitize_artifact_relative_path("reports/unsafe/summary.md")


def test_artifact_record_path_returns_absolute_path_outside_output_root(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    external_path = tmp_path / "external" / "report.txt"
    external_path.parent.mkdir()
    external_path.write_text("hello", encoding="utf-8")

    assert orchestrator._artifact_record_path(external_path) == str(external_path.resolve())


def test_default_artifact_path_sanitizes_blank_names_and_other_suffix(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    artifact = ArtifactRecord(name="...", artifact_type=ArtifactType.OTHER)

    assert orchestrator._default_artifact_path(artifact) == "artifacts/artifact.artifact"


def test_build_context_includes_test_repair_content_and_summary(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    task = Task(
        id="tests",
        title="Repair tests",
        description="Fix the tests",
        assigned_to="qa_tester",
        repair_context={
            "repair_owner": "qa_tester",
            "validation_summary": "Generated test validation: failed",
            "failed_output": "def test_old():\n    assert False",
        },
    )
    project.add_task(task)

    context = orchestrator._build_context(task, project)

    assert context["existing_tests"] == "def test_old():\n    assert False"
    assert context["test_validation_summary"] == "Generated test validation: failed"


def test_build_context_includes_dependency_repair_content_and_summary_without_existing_context(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    task = Task(
        id="deps",
        title="Repair dependencies",
        description="Fix the manifest",
        assigned_to="dependency_manager",
        repair_context={
            "repair_owner": "dependency_manager",
            "validation_summary": "Generated dependency validation: failed",
            "failed_artifact_content": "requests>=2.0",
        },
    )
    project.add_task(task)

    context = orchestrator._build_context(task, project)

    assert context["existing_dependency_manifest"] == "requests>=2.0"
    assert context["dependency_validation_summary"] == "Generated dependency validation: failed"


def test_build_context_skips_blank_repair_content_for_test_and_dependency_repairs(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    test_task = Task(
        id="tests",
        title="Repair tests",
        description="Fix the tests",
        assigned_to="qa_tester",
        repair_context={
            "repair_owner": "qa_tester",
            "validation_summary": "   ",
            "failed_output": "   ",
        },
    )
    dependency_task = Task(
        id="deps",
        title="Repair dependencies",
        description="Fix dependencies",
        assigned_to="dependency_manager",
        repair_context={
            "repair_owner": "dependency_manager",
            "validation_summary": "   ",
            "failed_artifact_content": "   ",
        },
    )
    project.add_task(test_task)
    project.add_task(dependency_task)

    test_context = orchestrator._build_context(test_task, project)
    dependency_context = orchestrator._build_context(dependency_task, project)

    assert "existing_tests" not in test_context
    assert "test_validation_summary" not in test_context
    assert "existing_dependency_manifest" not in dependency_context
    assert "dependency_validation_summary" not in dependency_context


def test_validation_payload_returns_empty_for_non_mapping_metadata(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="arch",
        title="Architecture",
        description="Design the architecture",
        assigned_to="architect",
        output_payload={"metadata": "invalid"},
    )

    assert orchestrator._validation_payload(task) == {}


def test_failed_artifact_content_skips_invalid_entries_and_falls_back_to_raw_content(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="code",
        title="Implementation",
        description="Implement the application",
        assigned_to="code_engineer",
        output="fallback output",
        output_payload={
            "raw_content": "def fallback() -> int:\n    return 1",
            "artifacts": [
                "invalid",
                {"artifact_type": ArtifactType.TEST.value, "content": "def test_ok():\n    assert True"},
                {"artifact_type": ArtifactType.CODE.value, "content": "   "},
            ],
        },
    )

    assert orchestrator._failed_artifact_content(task, ArtifactType.CODE) == "def fallback() -> int:\n    return 1"


def test_build_code_validation_summary_omits_optional_fields_when_missing(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_validation_summary({"syntax_ok": True, "third_party_imports": []}, "")

    assert summary == "Generated code validation:\n- Syntax OK: yes\n- Third-party imports: none"


def test_build_code_validation_summary_includes_line_count_and_cli_requirement(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_validation_summary(
        {
            "syntax_ok": True,
            "third_party_imports": [],
            "line_count": 176,
            "line_budget": 260,
            "has_main_guard": False,
            "main_guard_required": True,
        },
        "",
    )

    assert "Line count: 176/260" in summary
    assert "CLI entrypoint present: no (required by task)" in summary


def test_build_code_validation_summary_includes_line_count_without_budget(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_validation_summary(
        {"syntax_ok": True, "line_count": 12, "third_party_imports": []},
        "",
    )

    assert "Line count: 12" in summary


def test_build_code_validation_summary_includes_import_validation(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_validation_summary(
        {"syntax_ok": True, "third_party_imports": []},
        "",
        import_validation={
            "ran": True,
            "returncode": 1,
            "summary": "TypeError: non-default argument 'value' follows default argument",
        },
    )

    assert "Module import: FAIL" in summary
    assert "Import summary: TypeError: non-default argument 'value' follows default argument" in summary


def test_build_code_public_api_marks_constructor_fields_explicit_for_tests(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    code_analysis = orchestrator._analyze_python_module(
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    id: str\n"
        "    user_id: str\n"
        "    data: dict[str, str]\n"
        "    timestamp: str\n"
        "    status: str = 'pending'\n"
    )

    summary = orchestrator._build_code_public_api(code_analysis)

    assert "ComplianceRequest(id, user_id, data, timestamp, status)" in summary
    assert "tests must instantiate with all listed constructor fields explicitly: id, user_id, data, timestamp, status" in summary


def test_build_code_behavior_contract_includes_payload_storage_and_score_formula(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    contract = orchestrator._build_code_behavior_contract(
        "from dataclasses import dataclass\n"
        "from datetime import datetime\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    id: str\n"
        "    data: dict[str, str]\n"
        "    timestamp: datetime\n"
        "    status: str = 'pending'\n\n"
        "@dataclass\n"
        "class RiskScore:\n"
        "    score: int\n"
        "    level: str\n\n"
        "class ComplianceIntakeService:\n"
        "    def intake_request(self, request_data: dict[str, str]) -> ComplianceRequest:\n"
        "        request = ComplianceRequest(id=request_data['id'], data=request_data, timestamp=datetime.now())\n"
        "        return request\n\n"
        "    def score_risk(self, request: ComplianceRequest) -> RiskScore:\n"
        "        score = len(request.data) * 10\n"
        "        return RiskScore(score=score, level='low')\n"
    )

    assert "intake_request stores full request_data in returned ComplianceRequest.data" in contract
    assert "score_risk derives score from len(request.data) * 10" in contract


def test_build_code_behavior_contract_inlines_helper_score_formula_for_service_methods(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    contract = orchestrator._build_code_behavior_contract(
        "from dataclasses import dataclass\n"
        "from typing import Any, Dict\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    id: str\n"
        "    data: dict[str, str]\n"
        "    timestamp: str\n"
        "    status: str = 'pending'\n\n"
        "@dataclass\n"
        "class RiskScore:\n"
        "    score: float\n"
        "    level: str\n\n"
        "class ComplianceIntakeService:\n"
        "    def assess_risk(self, request: ComplianceRequest) -> RiskScore:\n"
        "        score = self.calculate_risk_score(request.data)\n"
        "        level = 'low'\n"
        "        return RiskScore(score, level)\n\n"
        "    def calculate_risk_score(self, data: Dict[str, Any]) -> float:\n"
        "        return float(len(data.get('compliance_data', ''))) * 0.1\n"
    )

    assert "calculate_risk_score derives score from float(len(data.get('compliance_data', ''))) * 0.1" in contract
    assert "assess_risk derives score from float(len(request.data.get('compliance_data', ''))) * 0.1" in contract


def test_build_code_behavior_contract_expands_local_score_aliases(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    contract = orchestrator._build_code_behavior_contract(
        "from dataclasses import dataclass\n"
        "from typing import Any, Dict\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    id: str\n"
        "    data: dict[str, str]\n"
        "    timestamp: str\n"
        "    status: str = 'pending'\n\n"
        "@dataclass\n"
        "class RiskScore:\n"
        "    score: float\n"
        "    level: str\n\n"
        "class ComplianceIntakeService:\n"
        "    def assess_risk(self, request: ComplianceRequest) -> RiskScore:\n"
        "        score = self.calculate_risk_score(request.data)\n"
        "        level = 'low'\n"
        "        return RiskScore(score, level)\n\n"
        "    def calculate_risk_score(self, data: Dict[str, Any]) -> float:\n"
        "        compliance_data_length = len(data.get('compliance_data', ''))\n"
        "        return compliance_data_length * 0.2\n"
    )

    assert "calculate_risk_score derives score from len(data.get('compliance_data', '')) * 0.2" in contract
    assert "assess_risk derives score from len(request.data.get('compliance_data', '')) * 0.2" in contract


def test_pytest_failure_details_include_assertion_context(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    details = orchestrator._pytest_failure_details(
        {
            "stdout": "FAILED tests_tests.py::test_example - AssertionError: assert 1 == 2\nE   AssertionError: assert 1 == 2\n",
            "stderr": "",
        }
    )

    assert details == [
        "FAILED tests_tests.py::test_example - AssertionError: assert 1 == 2 | AssertionError: assert 1 == 2"
    ]


def test_pytest_failure_details_prefer_full_assertion_lines_from_failure_sections(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    details = orchestrator._pytest_failure_details(
        {
            "stdout": (
                "..F                                                                    \n"
                "=================================== FAILURES ===================================\n"
                "_________________________ test_assess_risk_happy_path __________________________\n\n"
                ">   ???\n"
                "E   AssertionError: assert 0.4 == 0.1\n"
                "E    +  where 0.4 = RiskScore(score=0.4, level='low').score\n\n"
                "tests_tests.py:24: AssertionError\n"
                "=========================== short test summary info ============================\n"
                "FAILED tests_tests.py::test_assess_risk_happy_path - AssertionError: assert 0...\n"
            ),
            "stderr": "",
        }
    )

    assert details == [
        "FAILED tests_tests.py::test_assess_risk_happy_path - AssertionError: assert 0... | AssertionError: assert 0.4 == 0.1"
    ]


def test_build_repair_validation_summary_falls_back_when_validation_payload_shape_is_unusable(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="code",
        title="Implementation",
        description="Implement the application",
        assigned_to="code_engineer",
        output="fallback output",
        last_error="fallback error",
        output_payload={
            "metadata": {
                "validation": {
                    "code_analysis": "invalid",
                    "dependency_analysis": "invalid",
                }
            }
        },
    )

    assert (
        orchestrator._build_repair_validation_summary(task, FailureCategory.CODE_VALIDATION.value)
        == "fallback error"
    )
    assert (
        orchestrator._build_repair_validation_summary(task, FailureCategory.DEPENDENCY_VALIDATION.value)
        == "fallback error"
    )


def test_active_repair_cycle_returns_none_for_non_mapping_history_entries(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.repair_history.append(cast(Any, "invalid"))

    assert orchestrator._active_repair_cycle(project) is None


def test_has_repair_task_for_cycle_matches_origin_and_attempt(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch__repair_1",
            title="Repair architecture",
            description="Repair architecture",
            assigned_to="architect",
            repair_origin_task_id="arch",
            repair_attempt=1,
        )
    )

    assert orchestrator._has_repair_task_for_cycle(project, "arch", 1) is True


def test_has_repair_task_for_cycle_returns_false_for_mismatched_attempt(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch__repair_1",
            title="Repair architecture",
            description="Repair architecture",
            assigned_to="architect",
            repair_origin_task_id="arch",
            repair_attempt=2,
        )
    )

    assert orchestrator._has_repair_task_for_cycle(project, "arch", 1) is False


def test_queue_active_cycle_repair_returns_false_for_guard_conditions(tmp_path, monkeypatch):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_resume_policy="resume_failed",
    )
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    task = Task(id="arch", title="Architecture", description="Design", assigned_to="architect")
    project.add_task(task)

    project.repair_history.append({"cycle": 0})
    assert orchestrator._queue_active_cycle_repair(project, task) is False

    project.repair_history[-1] = {"cycle": 1}
    monkeypatch.setattr(orchestrator, "_has_repair_task_for_cycle", lambda *args, **kwargs: True)
    assert orchestrator._queue_active_cycle_repair(project, task) is False

    monkeypatch.setattr(orchestrator, "_has_repair_task_for_cycle", lambda *args, **kwargs: False)
    monkeypatch.setattr(project, "_plan_task_repair", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrator, "_repair_task_ids_for_cycle", lambda *args, **kwargs: [])
    assert orchestrator._queue_active_cycle_repair(project, task) is False


def test_failed_artifact_content_for_dependency_validation_uses_config_artifact(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="deps",
        title="Dependencies",
        description="Infer dependencies",
        assigned_to="dependency_manager",
        output_payload={
            "raw_content": "fallback",
            "artifacts": [
                {"artifact_type": ArtifactType.CONFIG.value, "content": "requests>=2.0"},
            ],
        },
    )

    assert (
        orchestrator._failed_artifact_content_for_category(task, FailureCategory.DEPENDENCY_VALIDATION.value)
        == "requests>=2.0"
    )


def test_repair_task_ids_for_cycle_skips_missing_tasks(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")

    assert orchestrator._repair_task_ids_for_cycle(project, ["missing-task"]) == []


def test_repair_task_ids_for_cycle_skips_none_repair_tasks(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement",
            assigned_to="code_engineer",
        )
    )

    monkeypatch.setattr(project, "_create_repair_task", lambda *args, **kwargs: None)

    assert orchestrator._repair_task_ids_for_cycle(project, ["code"]) == []


def test_planned_module_context_skips_code_tasks_without_module_name(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement",
            assigned_to="code_engineer",
        )
    )
    monkeypatch.setattr(orchestrator, "_default_module_name_for_task", lambda task: None)

    assert orchestrator._planned_module_context(project) == {}


def test_artifact_context_helpers_return_empty_for_invalid_payload_shapes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(id="task", title="Task", description="Task", assigned_to="architect")

    assert orchestrator._code_artifact_context(task) == {}
    assert orchestrator._test_artifact_context(task, {}) == {}
    assert orchestrator._dependency_artifact_context(task, {}) == {}

    task.output_payload = {"artifacts": "invalid"}
    assert orchestrator._code_artifact_context(task) == {}
    assert orchestrator._test_artifact_context(task, {}) == {}
    assert orchestrator._dependency_artifact_context(task, {}) == {}


def test_artifact_context_helpers_skip_non_matching_artifacts_and_missing_context(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    code_task = Task(
        id="code",
        title="Implementation",
        description="Implement",
        assigned_to="code_engineer",
        output="def ok():\n    return 1",
        output_payload={
            "artifacts": [
                "invalid",
                {"artifact_type": ArtifactType.TEST.value, "path": "tests_generated.py", "content": "def test_ok():\n    assert True"},
                {"artifact_type": ArtifactType.CODE.value, "path": "   ", "content": "def ok():\n    return 1"},
            ]
        },
    )
    test_task = Task(
        id="tests",
        title="Tests",
        description="Test",
        assigned_to="qa_tester",
        output="def test_ok():\n    assert True",
        output_payload={
            "artifacts": [
                "invalid",
                {"artifact_type": ArtifactType.CODE.value, "path": "code.py", "content": "def ok():\n    return 1"},
                {"artifact_type": ArtifactType.TEST.value, "path": "   ", "content": "def test_ok():\n    assert True"},
            ]
        },
    )
    dep_task = Task(
        id="deps",
        title="Dependencies",
        description="Deps",
        assigned_to="dependency_manager",
        output="requests>=2.0",
        output_payload={
            "artifacts": [
                "invalid",
                {"artifact_type": ArtifactType.CONFIG.value, "path": "   ", "content": "requests>=2.0"},
                {"artifact_type": ArtifactType.CONFIG.value, "path": "deps.txt", "content": "requests>=2.0"},
            ]
        },
    )

    assert orchestrator._code_artifact_context(code_task) == {}
    assert orchestrator._test_artifact_context(test_task, {}) == {}
    assert orchestrator._test_artifact_context(test_task, {"module_name": "code_implementation", "code_analysis": {}}) == {}
    assert orchestrator._dependency_artifact_context(dep_task, {}) == {}


def test_analyze_dependency_manifest_skips_blank_requirement_names(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    analysis = orchestrator._analyze_dependency_manifest(
        ">=1.0\nrequests>=2.0",
        {"third_party_imports": ["requests"]},
    )

    assert analysis["declared_packages"] == ["requests"]
    assert analysis["missing_manifest_entries"] == []
    assert analysis["provenance_violations"] == []


def test_analyze_dependency_manifest_flags_provenance_violations(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    analysis = orchestrator._analyze_dependency_manifest(
        "requests @ https://example.com/requests.whl\n--extra-index-url https://example.com/simple",
        {"third_party_imports": ["requests"]},
    )

    assert analysis["declared_packages"] == ["requests"]
    assert analysis["missing_manifest_entries"] == []
    assert analysis["provenance_violations"] == [
        "requests @ https://example.com/requests.whl",
        "--extra-index-url https://example.com/simple",
    ]
    assert analysis["is_valid"] is False


def test_build_generated_test_env_strips_additional_prefix_markers(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/cert.pem")
    monkeypatch.setenv("KUBECONFIG", "/tmp/kubeconfig")
    monkeypatch.setenv("PYTHONMALLOCSTATS", "1")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "SSL_CERT_FILE" not in env
    assert "KUBECONFIG" not in env
    assert "PYTHONMALLOCSTATS" not in env


def test_build_dependency_validation_summary_formats_failures_and_passes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_dependency_validation_summary(
        {
            "required_imports": ["requests"],
            "declared_packages": ["urllib3"],
            "missing_manifest_entries": ["requests"],
            "unused_manifest_entries": ["urllib3"],
            "is_valid": False,
        }
    )

    assert summary == (
        "Dependency manifest validation:\n"
        "- Required third-party imports: requests\n"
        "- Declared packages: urllib3\n"
        "- Missing manifest entries: requests\n"
        "- Unused manifest entries: urllib3\n"
        "- Provenance violations: none\n"
        "- Verdict: FAIL"
    )


def test_build_code_outline_returns_empty_for_blank_content(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._build_code_outline("   ") == ""


def test_analyze_python_module_covers_public_symbols_imports_and_class_metadata(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    raw_content = (
        "import requests\n"
        "from package.module import helper\n"
        "from .local import thing\n"
        "CONSTANT = 1\n\n"
        "def _private():\n"
        "    return 0\n\n"
        "async def public_async(value):\n"
        "    return value\n\n"
        "class Service:\n"
        "    status = 'ok'\n"
        "    def __init__(self, request_id):\n"
        "        self.request_id = request_id\n"
        "    def run(self, payload):\n"
        "        return payload\n"
    )

    analysis = orchestrator._analyze_python_module(raw_content)

    assert analysis["syntax_ok"] is True
    assert analysis["imports"] == ["package", "requests"]
    assert analysis["third_party_imports"] == ["package", "requests"]
    assert analysis["functions"] == [
        {
            "name": "public_async",
            "params": ["value"],
            "param_annotations": [None],
            "min_args": 1,
            "max_args": 1,
            "accepts_sequence_input": False,
            "return_annotation": None,
            "signature": "public_async(value)",
            "async": True,
        }
    ]
    assert analysis["classes"]["Service"] == {
        "name": "Service",
        "bases": [],
        "is_enum": False,
        "fields": [],
        "attributes": ["request_id", "status"],
        "constructor_params": ["request_id"],
        "constructor_min_args": 1,
        "constructor_max_args": 1,
        "methods": ["run(self, payload)"],
        "method_signatures": {
            "run": {
                "params": ["payload"],
                "param_annotations": [None],
                "min_args": 1,
                "max_args": 1,
                "accepts_sequence_input": False,
                "return_annotation": None,
            }
        },
    }
    assert analysis["symbols"] == ["Service", "public_async"]


def test_analyze_python_module_covers_enum_fields_and_public_async_methods(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    raw_content = (
        "import pkg.submodule, pkg.extra\n"
        "from service.api import Client\n\n"
        "class Payload:\n"
        "    request_id: str\n"
        "    left = right = 1\n"
        "    async def run(self, payload):\n"
        "        return payload\n\n"
        "class Status(Enum):\n"
        "    READY = 'ready'\n"
        "    def label(self):\n"
        "        return self.value\n"
    )

    analysis = orchestrator._analyze_python_module(raw_content)

    assert analysis["imports"] == ["pkg", "service"]
    assert analysis["classes"]["Payload"]["fields"] == ["request_id"]
    assert analysis["classes"]["Payload"]["attributes"] == ["left", "right"]
    assert analysis["classes"]["Payload"]["methods"] == ["run(self, payload)"]
    assert analysis["classes"]["Status"]["is_enum"] is True
    assert analysis["classes"]["Status"]["methods"] == ["label(self)"]


def test_analyze_python_module_includes_public_module_variables_in_symbols(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    raw_content = (
        "PUBLIC_COUNT = 1\n"
        "_internal_state = []\n"
        "audit_logs: list[str] = []\n\n"
        "def run():\n"
        "    return PUBLIC_COUNT\n"
    )

    analysis = orchestrator._analyze_python_module(raw_content)

    assert analysis["module_variables"] == ["PUBLIC_COUNT", "audit_logs"]
    assert analysis["symbols"] == ["run"]


def test_analyze_python_module_returns_default_shape_for_blank_content(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    analysis = orchestrator._analyze_python_module("   ")

    assert analysis == {
        "syntax_ok": True,
        "syntax_error": None,
        "functions": [],
        "classes": {},
        "imports": [],
        "third_party_imports": [],
        "module_variables": [],
        "symbols": [],
        "has_main_guard": False,
    }


def test_is_probable_third_party_import_rejects_blank_and_future(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._is_probable_third_party_import("") is False
    assert orchestrator._is_probable_third_party_import("__future__") is False


def test_build_code_public_api_reports_syntax_errors(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_public_api({"syntax_ok": False, "syntax_error": "invalid syntax"})

    assert summary == "Module syntax error: invalid syntax"


def test_build_module_run_command_returns_python_command_for_main_guard(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._build_module_run_command("app.py", {"has_main_guard": True}) == "python app.py"


def test_build_code_test_targets_reports_invalid_syntax(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_test_targets({"syntax_ok": False})

    assert summary == "Test targets unavailable because module syntax is invalid."


def test_build_code_test_targets_excludes_cli_wrapper_classes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_test_targets(
        {
            "syntax_ok": True,
            "functions": [
                {"name": "main", "signature": "main()", "accepts_sequence_input": False},
                {"name": "run_service", "signature": "run_service()", "accepts_sequence_input": False},
                {"name": "batch_run", "signature": "batch_run(items)", "accepts_sequence_input": True},
            ],
            "classes": {
                "ComplianceCLI": {},
                "ComplianceService": {},
            },
        }
    )

    assert "Functions to test: run_service(), batch_run(items)" in summary
    assert "Batch-capable functions: batch_run(items)" in summary
    assert "Scalar-only functions: run_service()" in summary
    assert "Classes to test: ComplianceService" in summary
    assert "Entry points to avoid in tests: ComplianceCLI, main" in summary


def test_build_code_test_targets_marks_preferred_and_helper_classes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_test_targets(
        {
            "syntax_ok": True,
            "functions": [],
            "classes": {
                "ComplianceService": {
                    "method_signatures": {
                        "validate_request": {},
                        "process_request": {},
                    }
                },
                "RiskScoringService": {"method_signatures": {"score_request": {}}},
                "ComplianceRepository": {"method_signatures": {"store_request": {}}},
                "ComplianceCLI": {"method_signatures": {"run": {}}},
            },
        }
    )

    assert "Classes to test: ComplianceService" in summary
    assert "Preferred workflow classes: ComplianceService" in summary
    assert "Helper classes to avoid in compact workflow tests: ComplianceRepository, RiskScoringService" in summary


def test_build_code_exact_test_contract_excludes_helper_classes_when_facade_exists(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_exact_test_contract(
        {
            "syntax_ok": True,
            "functions": [],
            "classes": {
                "ComplianceIntakeService": {
                    "constructor_params": [],
                    "methods": ["intake_request", "validate_request"],
                    "method_signatures": {
                        "intake_request": {},
                        "validate_request": {},
                    },
                },
                "ComplianceRequest": {
                    "constructor_params": ["request_id", "request_type", "details", "timestamp"],
                    "methods": [],
                    "method_signatures": {},
                },
                "RiskScoringService": {
                    "constructor_params": [],
                    "methods": ["score_request"],
                    "method_signatures": {"score_request": {}},
                },
                "AuditLogger": {
                    "constructor_params": [],
                    "methods": ["log_action"],
                    "method_signatures": {"log_action": {}},
                },
            },
        }
    )

    assert "Allowed production imports: ComplianceIntakeService, ComplianceRequest" in summary
    assert "Preferred service or workflow facades: ComplianceIntakeService" in summary
    assert "ComplianceIntakeService.intake_request" in summary
    assert "ComplianceIntakeService.validate_request" in summary
    assert "ComplianceRequest(request_id, request_type, details, timestamp)" in summary
    assert "RiskScoringService" not in summary
    assert "AuditLogger" not in summary
    assert "score_request" not in summary
    assert "log_action" not in summary


def test_build_code_test_targets_keeps_required_constructor_logger_off_helper_avoid_list(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_test_targets(
        {
            "syntax_ok": True,
            "functions": [],
            "classes": {
                "ComplianceIntakeService": {
                    "constructor_params": ["audit_logger"],
                    "method_signatures": {"batch_process": {}},
                },
                "AuditLogger": {
                    "constructor_params": [],
                    "method_signatures": {"log_action": {}},
                },
            },
        }
    )

    assert "Preferred workflow classes: ComplianceIntakeService" in summary
    assert "Helper classes to avoid in compact workflow tests: none" in summary


def test_build_code_test_targets_keeps_multi_token_constructor_helpers_off_helper_avoid_list(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_test_targets(
        {
            "syntax_ok": True,
            "functions": [],
            "classes": {
                "ComplianceService": {
                    "constructor_params": ["repository", "scoring_service", "logging_service"],
                    "method_signatures": {"intake_request": {}, "validate_request": {}},
                },
                "ComplianceRepository": {
                    "constructor_params": [],
                    "method_signatures": {"store_request": {}},
                },
                "RiskScoringService": {
                    "constructor_params": [],
                    "method_signatures": {"calculate_score": {}},
                },
                "AuditLoggingService": {
                    "constructor_params": [],
                    "method_signatures": {"log_entry": {}},
                },
            },
        }
    )

    assert "Preferred workflow classes: ComplianceService" in summary
    assert "Helper classes to avoid in compact workflow tests: none" in summary


def test_build_code_behavior_contract_returns_empty_for_blank_and_syntax_invalid_modules(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._build_code_behavior_contract("   ") == ""
    assert orchestrator._build_code_behavior_contract("def broken(:\n    pass") == ""


def test_extract_required_fields_returns_declared_required_fields_list(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "def validate(payload):\n"
        "    required_fields = ['name', 1, 'email']\n"
        "    return payload\n"
    )

    assert orchestrator._extract_required_fields(function_node) == ["name", "email"]


def test_extract_required_fields_collects_unique_comparison_literals(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "def validate(payload):\n"
        "    if 'status' in payload:\n"
        "        return True\n"
        "    if 'status' not in payload:\n"
        "        return False\n"
        "    return 'request_id' in payload\n"
    )

    assert orchestrator._extract_required_fields(function_node) == ["status", "request_id"]


def test_extract_required_fields_returns_empty_for_blank_required_fields_list(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "def validate(payload):\n"
        "    required_fields = []\n"
        "    return payload\n"
    )

    assert orchestrator._extract_required_fields(function_node) == []


def test_comparison_required_field_rejects_invalid_shapes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    compare_nodes = [
        ast.Compare(left=ast.Constant("field"), ops=[], comparators=[]),
        ast.Compare(left=ast.Constant("field"), ops=[ast.In()], comparators=[ast.Constant("value")]),
        ast.Compare(left=ast.Constant("field"), ops=[ast.Eq()], comparators=[ast.Name("payload")]),
    ]

    assert [orchestrator._comparison_required_field(node) for node in compare_nodes] == ["", "", ""]


def test_extract_indirect_required_fields_supports_attribute_calls(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "def process(payload):\n"
        "    return helper.validate_request(payload)\n"
    )

    assert orchestrator._extract_indirect_required_fields(function_node, {"validate_request": ["request_id"]}) == ["request_id"]
    assert orchestrator._extract_indirect_required_fields(function_node, {"other": ["request_id"]}) == []


def test_extract_indirect_required_fields_ignores_unmatched_attribute_calls(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "def validate(payload):\n"
        "    service.other(payload)\n"
        "    return payload\n"
    )

    assert orchestrator._extract_indirect_required_fields(function_node, {"validate_request": ["request_id"]}) == []


def test_extract_lookup_field_rules_collects_literal_key_sets_and_skips_unknown_selectors(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "def score_request(request, payload, selector):\n"
        "    if True:\n"
        "        pass\n"
        "    risk_scores = {'approved': 1, 'denied': 0}\n"
        "    return risk_scores[request.status] + risk_scores[payload['state']] + risk_scores[selector]\n"
    )

    assert orchestrator._extract_lookup_field_rules(function_node) == {
        "status": ["approved", "denied"],
        "state": ["approved", "denied"],
    }
    assert orchestrator._field_selector_name(ast.Subscript(value=ast.Name("payload"), slice=ast.Constant("state"))) == "state"
    assert orchestrator._field_selector_name(ast.Constant("status")) == "status"
    assert orchestrator._field_selector_name(ast.Name("selector")) == ""


def test_extract_lookup_field_rules_ignores_empty_literal_key_sets(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "def validate(payload):\n"
        "    allowed = {}\n"
        "    return allowed[payload['status']]\n"
    )

    assert orchestrator._extract_lookup_field_rules(function_node) == {}


def test_extract_batch_rule_covers_direct_and_nested_shapes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    direct_batch = parse_function_node(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(item['request_id'], item)\n"
    )
    nested_batch = parse_function_node(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        self.intake_request(item['request_id'], item['payload'])\n"
    )
    wrapper_only_batch = parse_function_node(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(item.id, item['payload'])\n"
    )
    missing_args_batch = parse_function_node(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(item)\n"
    )
    not_batch = parse_function_node(
        "def process_items(items):\n"
        "    for item in items:\n"
        "        intake_request(item['request_id'], item)\n"
    )
    validation_rules = {"intake_request": ["name", "email"]}

    assert (
        orchestrator._extract_batch_rule(direct_batch, validation_rules)
        == "process_batch expects each batch item to include: request_id, name, email"
    )
    assert (
        orchestrator._extract_batch_rule(nested_batch, validation_rules)
        == "process_batch expects each batch item to include key `request_id` and nested `payload` fields: name, email"
    )
    assert (
        orchestrator._extract_batch_rule(wrapper_only_batch, validation_rules)
        == "process_batch expects nested `payload` fields: name, email"
    )
    assert orchestrator._extract_batch_rule(missing_args_batch, validation_rules) == ""
    assert orchestrator._extract_batch_rule(not_batch, validation_rules) == ""


def test_extract_batch_rule_ignores_non_matching_calls_and_empty_required_fields(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    validation_rules = {"intake_request": []}
    helper_batch = parse_function_node(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        service.validate(item)\n"
    )
    empty_direct_batch = parse_function_node(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(request_id, item)\n"
    )
    empty_nested_batch = parse_function_node(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(request_id, item['payload'])\n"
    )

    assert orchestrator._extract_batch_rule(helper_batch, validation_rules) == ""
    assert orchestrator._extract_batch_rule(empty_direct_batch, validation_rules) == ""
    assert orchestrator._extract_batch_rule(empty_nested_batch, validation_rules) == ""


def test_analyze_test_module_returns_default_shape_for_blank_and_syntax_invalid_input(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    blank_analysis = orchestrator._analyze_test_module("   ", "module_under_test", {})
    syntax_error_analysis = orchestrator._analyze_test_module("def broken(:\n    pass", "module_under_test", {})

    assert blank_analysis == {
        "syntax_ok": True,
        "syntax_error": None,
        "imported_module_symbols": [],
        "missing_function_imports": [],
        "unknown_module_symbols": [],
        "invalid_member_references": [],
        "call_arity_mismatches": [],
        "constructor_arity_mismatches": [],
        "payload_contract_violations": [],
        "non_batch_sequence_calls": [],
        "helper_surface_usages": [],
        "reserved_fixture_names": [],
        "undefined_fixtures": [],
        "undefined_local_names": [],
        "imported_entrypoint_symbols": [],
        "unsafe_entrypoint_calls": [],
        "unsupported_mock_assertions": [],
        "top_level_test_count": 0,
        "fixture_count": 0,
    }
    assert syntax_error_analysis["syntax_ok"] is False
    assert syntax_error_analysis["syntax_error"] == "invalid syntax at line 1"


def test_analyze_test_module_tracks_invalid_member_references_for_non_enum_class_fields(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [],
        "classes": {
            "Payload": {
                "name": "Payload",
                "bases": [],
                "is_enum": False,
                "fields": ["request_id"],
                "attributes": ["status"],
                "constructor_params": ["request_id"],
                "methods": [],
                "method_signatures": {},
            }
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": ["Payload"],
    }
    test_content = (
        "from module_under_test import Payload\n\n"
        "def test_payload_members():\n"
        "    assert Payload.request_id == 'id'\n"
        "    assert Payload.missing == 'oops'\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["invalid_member_references"] == ["Payload.missing (line 5)"]


def test_analyze_test_module_allows_existing_class_methods(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [],
        "classes": {
            "Validator": {
                "name": "Validator",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": ["validate(self, payload)"],
                "method_signatures": {
                    "validate": {
                        "params": ["payload"],
                        "min_args": 1,
                        "max_args": 1,
                        "return_annotation": None,
                    }
                },
            }
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": ["Validator"],
    }
    test_content = (
        "from module_under_test import Validator\n\n"
        "def test_validator():\n"
        "    assert Validator.validate({'ok': True}) is not None\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["invalid_member_references"] == []


def test_analyze_test_module_allows_importing_defined_module_variables(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = orchestrator._analyze_python_module(
        "audit_logs: list[str] = []\n\n"
        "def log_audit():\n"
        "    audit_logs.append('ok')\n"
    )
    test_content = (
        "from module_under_test import audit_logs, log_audit\n\n"
        "def test_log_audit_records_event():\n"
        "    log_audit()\n"
        "    assert audit_logs == ['ok']\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["imported_module_symbols"] == ["audit_logs", "log_audit"]
    assert analysis["unknown_module_symbols"] == []


def test_analyze_test_module_flags_helper_surface_usages_when_workflow_class_exists(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [],
        "classes": {
            "ComplianceService": {
                "name": "ComplianceService",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": ["process_request(self, request)", "validate_request(self, request)"],
                "method_signatures": {
                    "process_request": {"params": ["request"], "min_args": 1, "max_args": 1, "return_annotation": None},
                    "validate_request": {"params": ["request"], "min_args": 1, "max_args": 1, "return_annotation": None},
                },
            },
            "RiskScoringService": {
                "name": "RiskScoringService",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": ["score_request(self, request)"],
                "method_signatures": {
                    "score_request": {"params": ["request"], "min_args": 1, "max_args": 1, "return_annotation": None},
                },
            },
            "ComplianceRepository": {
                "name": "ComplianceRepository",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": ["store_request(self, request)"],
                "method_signatures": {
                    "store_request": {"params": ["request"], "min_args": 1, "max_args": 1, "return_annotation": None},
                },
            },
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": ["ComplianceService", "RiskScoringService", "ComplianceRepository"],
    }
    test_content = (
        "from module_under_test import ComplianceService, RiskScoringService, ComplianceRepository\n\n"
        "def test_service_flow():\n"
        "    service = ComplianceService()\n"
        "    assert service is not None\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["helper_surface_usages"] == ["ComplianceRepository", "RiskScoringService"]


def test_analyze_test_module_allows_required_constructor_helper_for_preferred_workflow_class(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [],
        "classes": {
            "ComplianceIntakeService": {
                "name": "ComplianceIntakeService",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": ["audit_logger"],
                "constructor_min_args": 1,
                "constructor_max_args": 1,
                "methods": ["intake(self, payload)"],
                "method_signatures": {
                    "intake": {"params": ["payload"], "min_args": 1, "max_args": 1, "return_annotation": None},
                },
            },
            "AuditLogger": {
                "name": "AuditLogger",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": ["log_action(self, action)"],
                "method_signatures": {
                    "log_action": {"params": ["action"], "min_args": 1, "max_args": 1, "return_annotation": None},
                },
            },
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": ["ComplianceIntakeService", "AuditLogger"],
    }
    test_content = (
        "from module_under_test import ComplianceIntakeService, AuditLogger\n\n"
        "def test_service_flow():\n"
        "    service = ComplianceIntakeService(AuditLogger())\n"
        "    assert service is not None\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["helper_surface_usages"] == []


def test_analyze_test_module_allows_multi_token_constructor_helpers_for_preferred_workflow_class(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [],
        "classes": {
            "ComplianceService": {
                "name": "ComplianceService",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": ["repository", "scoring_service", "logging_service"],
                "constructor_min_args": 3,
                "constructor_max_args": 3,
                "methods": ["intake_request(self, request)", "validate_request(self, request)"],
                "method_signatures": {
                    "intake_request": {"params": ["request"], "min_args": 1, "max_args": 1, "return_annotation": None},
                    "validate_request": {"params": ["request"], "min_args": 1, "max_args": 1, "return_annotation": None},
                },
            },
            "ComplianceRepository": {
                "name": "ComplianceRepository",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": ["store_request(self, request)"],
                "method_signatures": {
                    "store_request": {"params": ["request"], "min_args": 1, "max_args": 1, "return_annotation": None},
                },
            },
            "RiskScoringService": {
                "name": "RiskScoringService",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": ["calculate_score(self, request)"],
                "method_signatures": {
                    "calculate_score": {"params": ["request"], "min_args": 1, "max_args": 1, "return_annotation": None},
                },
            },
            "AuditLoggingService": {
                "name": "AuditLoggingService",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": ["log_entry(self, entry)"],
                "method_signatures": {
                    "log_entry": {"params": ["entry"], "min_args": 1, "max_args": 1, "return_annotation": None},
                },
            },
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": [
            "ComplianceService",
            "ComplianceRepository",
            "RiskScoringService",
            "AuditLoggingService",
        ],
    }
    test_content = (
        "from module_under_test import ComplianceService, ComplianceRepository, RiskScoringService, AuditLoggingService\n\n"
        "def test_service_flow():\n"
        "    service = ComplianceService(ComplianceRepository(), RiskScoringService(), AuditLoggingService())\n"
        "    assert service is not None\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["helper_surface_usages"] == []


def test_analyze_test_module_tracks_instance_call_arity_and_returned_member_refs(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [],
        "classes": {
            "ComplianceRequest": {
                "name": "ComplianceRequest",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": ["request_id", "status"],
                "constructor_params": ["request_id", "data", "timestamp", "status"],
                "constructor_min_args": 3,
                "constructor_max_args": 4,
                "methods": [],
                "method_signatures": {},
            },
            "ComplianceIntakeService": {
                "name": "ComplianceIntakeService",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": ["intake_request(self, request_data)"],
                "method_signatures": {
                    "intake_request": {
                        "params": ["request_data"],
                        "min_args": 1,
                        "max_args": 1,
                        "return_annotation": "ComplianceRequest",
                    }
                },
            },
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": ["ComplianceIntakeService", "ComplianceRequest"],
    }
    test_content = (
        "from module_under_test import ComplianceIntakeService\n\n"
        "def test_service_usage():\n"
        "    service = ComplianceIntakeService()\n"
        "    request = service.intake_request('req-1', {'ok': True})\n"
        "    assert request.id == 'req-1'\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["call_arity_mismatches"] == [
        "ComplianceIntakeService.intake_request expects 1 args but test uses 2 at line 5"
    ]
    assert analysis["invalid_member_references"] == ["ComplianceRequest.id (line 6)"]


def test_analyze_test_module_tracks_inline_constructor_member_refs_and_returned_types(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [],
        "classes": {
            "ComplianceData": {
                "name": "ComplianceData",
                "bases": [],
                "is_enum": False,
                "fields": ["id", "data", "timestamp"],
                "attributes": [],
                "constructor_params": ["id", "data", "timestamp"],
                "constructor_min_args": 2,
                "constructor_max_args": 3,
                "methods": [],
                "method_signatures": {},
            },
            "ComplianceResult": {
                "name": "ComplianceResult",
                "bases": [],
                "is_enum": False,
                "fields": ["id", "is_compliant", "risk_score"],
                "attributes": [],
                "constructor_params": ["id", "is_compliant", "risk_score"],
                "constructor_min_args": 3,
                "constructor_max_args": 3,
                "methods": [],
                "method_signatures": {},
            },
            "ComplianceIntakeService": {
                "name": "ComplianceIntakeService",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": [],
                "constructor_min_args": 0,
                "constructor_max_args": 0,
                "methods": [
                    "submit_intake(self, data)",
                    "batch_submit_intakes(self, data_list)",
                ],
                "method_signatures": {
                    "submit_intake": {
                        "params": ["data"],
                        "min_args": 1,
                        "max_args": 1,
                        "return_annotation": "ComplianceResult",
                    },
                    "batch_submit_intakes": {
                        "params": ["data_list"],
                        "min_args": 1,
                        "max_args": 1,
                        "return_annotation": None,
                    },
                },
            },
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": ["ComplianceData", "ComplianceIntakeService", "ComplianceResult"],
    }
    test_content = (
        "from module_under_test import ComplianceData, ComplianceIntakeService\n\n"
        "def test_inline_service_usage():\n"
        "    result = ComplianceIntakeService().submit_intake(ComplianceData('1', {'key': 'value'}))\n"
        "    ComplianceIntakeService().submit('x')\n"
        "    ComplianceIntakeService().batch_submit_intakes([], [])\n"
        "    assert result.invalid is True\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["call_arity_mismatches"] == [
        "ComplianceIntakeService.batch_submit_intakes expects 1 args but test uses 2 at line 6"
    ]
    assert analysis["invalid_member_references"] == [
        "ComplianceIntakeService.submit (line 5)",
        "ComplianceResult.invalid (line 7)",
    ]


def test_analyze_test_module_flags_mock_style_assertions_without_mock_setup(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [{"name": "log_audit"}],
        "classes": {},
        "imports": [],
        "third_party_imports": [],
        "symbols": ["log_audit"],
    }
    test_content = (
        "import logging\n"
        "from module_under_test import log_audit\n\n"
        "def test_log_audit():\n"
        "    log_audit(1, 'scored', True)\n"
        "    assert logging.getLogger().info.call_count == 1\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["unsupported_mock_assertions"] == [
        "logging.getLogger().info.call_count (line 6)"
    ]


def test_analyze_test_module_allows_mock_style_assertions_with_explicit_mock_setup(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    test_content = (
        "from unittest.mock import MagicMock\n\n"
        "def test_logger_calls():\n"
        "    mock_logger = MagicMock()\n"
        "    mock_logger.info('ok')\n"
        "    assert mock_logger.info.call_count == 1\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", {})

    assert analysis["unsupported_mock_assertions"] == []


def test_analyze_test_module_flags_reserved_request_fixture_and_missing_fixture_imports(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [{"name": "validate_request"}],
        "classes": {
            "ComplianceRequest": {
                "name": "ComplianceRequest",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": ["id", "customer_id", "document_type", "document_data"],
                "constructor_min_args": 4,
                "constructor_max_args": 4,
                "methods": [],
                "method_signatures": {},
            }
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": ["ComplianceRequest", "validate_request"],
    }
    test_content = (
        "import pytest\n"
        "from module_under_test import validate_request\n\n"
        "@pytest.fixture\n"
        "def request():\n"
        "    return ComplianceRequest(1, 2, 'contract', {'document_data': 'x'})\n\n"
        "def test_validate_request(request):\n"
        "    assert validate_request(request)\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["reserved_fixture_names"] == ["request (line 5)"]
    assert analysis["undefined_local_names"] == ["ComplianceRequest (line 6)"]


def test_binding_and_call_helpers_cover_annotation_attribute_and_keyword_paths(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "def test_case():\n"
        "    payload: dict = {'status': 'approved'}\n"
        "    service.validate_request(payload)\n"
        "    process_request('id-1', payload=payload)\n"
    )
    call_nodes = [node for node in ast.walk(function_node) if isinstance(node, ast.Call)]

    bindings = orchestrator._collect_local_bindings(function_node)

    assert isinstance(bindings["payload"], ast.Dict)
    assert orchestrator._callable_name(call_nodes[0]) == "validate_request"
    assert orchestrator._callable_name(call_nodes[1]) == "process_request"
    assert orchestrator._callable_name(ast.Call(func=ast.Lambda(args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=ast.Constant(None)), args=[], keywords=[])) == ""
    assert isinstance(orchestrator._first_call_argument(call_nodes[1]), ast.Constant)
    first_keyword_arg = orchestrator._first_call_argument(
        ast.Call(func=ast.Name("process_request"), args=[], keywords=[ast.keyword(arg="payload", value=ast.Name("payload"))])
    )
    assert isinstance(first_keyword_arg, ast.Name)
    assert first_keyword_arg.id == "payload"
    assert isinstance(orchestrator._payload_argument_for_validation(call_nodes[0], "validate_request"), ast.Name)
    assert isinstance(orchestrator._payload_argument_for_validation(call_nodes[1], "process_request"), ast.Name)
    keyword_only_call = ast.Call(func=ast.Name("process_request"), args=[], keywords=[ast.keyword(arg="payload", value=ast.Name("payload"))])
    assert orchestrator._payload_argument_for_validation(keyword_only_call, "process_request") == keyword_only_call.keywords[0].value


def test_analyze_test_behavior_contracts_reports_payload_value_and_batch_issues(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    tree = ast.parse(
        "def test_case():\n"
        "    validate_request({'name': 'Ada'})\n"
        "    score_request({'status': 'pending'})\n"
        "    helper([1, 2, 3])\n"
        "    (factory())()\n"
    )

    payload_violations, non_batch_calls = orchestrator._analyze_test_behavior_contracts(
        tree,
        {"validate_request": ["name", "email"]},
        {"score_request": {"status": ["approved"]}},
        {},
        set(),
        {"helper"},
        {},
    )

    assert payload_violations == [
        "score_request field `status` uses unsupported values: pending at line 3",
        "validate_request payload missing required fields: email at line 2",
    ]
    assert non_batch_calls == ["helper does not accept batch/list inputs at line 4"]


def test_analyze_test_behavior_contracts_ignores_negative_validation_expectations(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    tree = ast.parse(
        "import pytest\n\n"
        "def test_case():\n"
        "    with pytest.raises(ValueError):\n"
        "        intake_request('req-1', {'name': 'Ada'})\n"
        "    assert validate_request({'name': 'Ada'}) is False\n"
        "    assert not validate_request({'name': 'Ada'})\n"
    )

    payload_violations, non_batch_calls = orchestrator._analyze_test_behavior_contracts(
        tree,
        {"intake_request": ["name", "email"], "validate_request": ["name", "email"]},
        {},
        {},
        set(),
        set(),
        {},
    )

    assert payload_violations == []
    assert non_batch_calls == []


def test_analyze_test_behavior_contracts_ignores_validation_result_invalid_state_assertions(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    tree = ast.parse(
        "def test_case():\n"
        "    result = validate_submission({'name': 'Ada'})\n"
        "    assert result.is_valid is False\n"
        "    assert result.errors\n"
    )

    payload_violations, non_batch_calls = orchestrator._analyze_test_behavior_contracts(
        tree,
        {"validate_submission": ["name", "email"]},
        {},
        {},
        set(),
        set(),
        {},
    )

    assert payload_violations == []
    assert non_batch_calls == []


def test_analyze_test_behavior_contracts_allows_partial_invalid_batch_when_result_count_is_explicit(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    tree = ast.parse(
        "def test_case():\n"
        "    requests = [\n"
        "        {'request_id': 'req-1', 'name': 'Ada', 'email': 'ada@example.com'},\n"
        "        {'request_id': 'req-2', 'name': 'Bob'},\n"
        "    ]\n"
        "    results = process_batch(requests)\n"
        "    assert len(results) == 1\n"
    )

    payload_violations, non_batch_calls = orchestrator._analyze_test_behavior_contracts(
        tree,
        {},
        {},
        {
            "process_batch": {
                "fields": ["request_id", "name", "email"],
                "request_key": None,
                "wrapper_key": None,
            }
        },
        set(),
        {"process_batch"},
        {},
    )

    assert payload_violations == []
    assert non_batch_calls == []


def test_analyze_test_module_allows_optional_constructor_arguments(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [],
        "classes": {
            "ComplianceRequest": {
                "name": "ComplianceRequest",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": ["request_id", "data", "timestamp", "status"],
                "constructor_min_args": 3,
                "constructor_max_args": 4,
                "methods": [],
            }
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": ["ComplianceRequest"],
    }
    test_content = (
        "from module_under_test import ComplianceRequest\n\n"
        "def test_request_defaults():\n"
        "    request = ComplianceRequest('req-1', {'name': 'Ada'}, '2024-01-01T00:00:00Z')\n"
        "    assert request is not None\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["constructor_arity_mismatches"] == []


def test_analyze_python_module_tracks_optional_dataclass_constructor_fields(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    analysis = orchestrator._analyze_python_module(
        "from dataclasses import dataclass, field\n"
        "from datetime import datetime\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    request_id: str\n"
        "    requester_name: str\n"
        "    request_details: str\n"
        "    submission_date: datetime = field(default_factory=datetime.now)\n"
    )

    class_info = analysis["classes"]["ComplianceRequest"]

    assert class_info["constructor_params"] == [
        "request_id",
        "requester_name",
        "request_details",
        "submission_date",
    ]
    assert class_info["constructor_min_args"] == 3
    assert class_info["constructor_max_args"] == 4


def test_analyze_test_module_allows_omitted_defaulted_dataclass_field_from_module_analysis(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = orchestrator._analyze_python_module(
        "from dataclasses import dataclass, field\n"
        "from datetime import datetime\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    request_id: str\n"
        "    requester_name: str\n"
        "    request_details: str\n"
        "    submission_date: datetime = field(default_factory=datetime.now)\n"
    )
    test_content = (
        "from module_under_test import ComplianceRequest\n\n"
        "def test_request_defaults():\n"
        "    request = ComplianceRequest('req-1', 'Ada', 'High priority')\n"
        "    assert request.request_id == 'req-1'\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["constructor_arity_mismatches"] == []


def test_analyze_test_behavior_contracts_ignores_unresolved_payloads_and_supported_values(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    tree = ast.parse(
        "def test_case():\n"
        "    validate_request(payload)\n"
        "    score_request({'status': 'approved'})\n"
    )

    payload_violations, non_batch_calls = orchestrator._analyze_test_behavior_contracts(
        tree,
        {"validate_request": ["name"]},
        {"score_request": {"status": ["approved"]}},
        {},
        set(),
        set(),
        {},
    )

    assert payload_violations == []
    assert non_batch_calls == []


def test_payload_and_binding_resolution_helpers_cover_keyword_and_depth_paths(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    keyword_call = ast.Call(func=ast.Name("score_request"), args=[], keywords=[ast.keyword(arg="payload", value=ast.Name("payload"))])
    fallback_call = ast.Call(func=ast.Name("score_request"), args=[ast.Constant("first")], keywords=[ast.keyword(arg="other", value=ast.Constant("ignored"))])
    bindings = {
        "payload": ast.Name("payload_alias"),
        "payload_alias": ast.Name("payload_final"),
        "payload_final": ast.Dict(keys=[ast.Constant("name")], values=[ast.Constant("Ada")]),
    }

    assert isinstance(orchestrator._payload_argument_for_validation(keyword_call, "score_request"), ast.Name)
    fallback_value = orchestrator._payload_argument_for_validation(fallback_call, "score_request")
    assert isinstance(fallback_value, ast.Constant)
    assert fallback_value.value == "first"
    resolved = orchestrator._resolve_bound_value(ast.Name("payload"), bindings)
    assert isinstance(resolved, ast.Dict)


def test_literal_dict_and_field_value_helpers_cover_subscript_call_and_fallback_paths(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    bindings = {
        "payload": ast.Dict(
            keys=[ast.Constant("payload"), ast.Constant("status")],
            values=[ast.Dict(keys=[ast.Constant("name")], values=[ast.Constant("Ada")]), ast.Constant("approved")],
        ),
        "request_obj": ast.Call(
            func=ast.Name("Request"),
            args=[ast.Constant("pending")],
            keywords=[ast.keyword(arg="data", value=ast.Dict(keys=[ast.Constant("status")], values=[ast.Constant("denied")]))],
        ),
        "items": ast.List(elts=[ast.Dict(keys=[ast.Constant("request_id")], values=[ast.Constant("id-1")])]),
    }
    class_map = {"Request": {"constructor_params": ["status"]}}

    nested_keys = orchestrator._extract_literal_dict_keys(
        ast.Subscript(value=ast.Name("payload"), slice=ast.Constant("payload")),
        bindings,
        class_map,
    )
    call_keys = orchestrator._extract_literal_dict_keys(ast.Name("request_obj"), bindings, class_map)
    dict_field_values = orchestrator._extract_literal_field_values(ast.Name("payload"), bindings, "status", class_map)
    call_field_values = orchestrator._extract_literal_field_values(ast.Name("request_obj"), bindings, "status", class_map)
    list_items = orchestrator._extract_literal_list_items(ast.Name("items"), bindings)

    assert nested_keys == {"name"}
    assert call_keys == {"status"}
    assert dict_field_values == ["approved"]
    assert call_field_values == ["pending"]
    assert isinstance(list_items, list)
    assert orchestrator._extract_literal_list_items(ast.Constant("nope"), bindings) is None


def test_literal_helpers_cover_missing_keys_nested_data_and_non_string_values(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    bindings = {
        "container": ast.Dict(
            keys=[ast.Constant("payload")],
            values=[ast.Dict(keys=[ast.Constant("email")], values=[ast.Constant("ada@example.com")])],
        ),
        "request_obj": ast.Call(
            func=ast.Name("Request"),
            args=[],
            keywords=[ast.keyword(arg="data", value=ast.Dict(keys=[ast.Constant("email")], values=[ast.Constant("ada@example.com")]))],
        ),
    }
    class_map = {"Request": {"constructor_params": ["status", "data"]}}

    assert (
        orchestrator._extract_literal_dict_keys(
            ast.Subscript(value=ast.Name("container"), slice=ast.Constant("missing")),
            bindings,
            class_map,
        )
        is None
    )
    assert orchestrator._extract_literal_dict_keys(ast.Name("request_obj"), bindings, class_map) == {"email"}
    assert orchestrator._extract_literal_field_values(
        ast.Dict(keys=[ast.Constant("status")], values=[ast.Constant("approved")]),
        {},
        "missing",
        class_map,
    ) == []
    assert orchestrator._extract_literal_field_values(ast.Name("request_obj"), bindings, "email", class_map) == [
        "ada@example.com"
    ]
    assert orchestrator._extract_string_literals(ast.Constant(123), {}) == []
    assert orchestrator._extract_literal_dict_keys(
        ast.Subscript(
            value=ast.Dict(
                keys=[ast.Constant("data")],
                values=[ast.Dict(keys=[ast.Constant("email")], values=[ast.Constant("ada@example.com")])],
            ),
            slice=ast.Constant("data"),
        ),
        bindings,
        class_map,
    ) == {"email"}
    assert (
        orchestrator._extract_literal_field_values(
            ast.Call(func=ast.Name("Request"), args=[], keywords=[]),
            {},
            "email",
            class_map,
        )
        == []
    )
    assert (
        orchestrator._extract_literal_dict_keys(
            ast.Subscript(value=ast.Name("request_obj"), slice=ast.Constant("missing")),
            bindings,
            class_map,
        )
        is None
    )


def test_validate_test_output_rejects_top_level_test_count_mismatch(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(
        summary="tests",
        raw_content="def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n",
    )
    task = Task(
        id="tests",
        title="Tests",
        description="Write exactly 3 top-level test functions.",
        assigned_to="qa_tester",
    )

    monkeypatch.setattr(
        orchestrator,
        "_execute_generated_tests",
        lambda *args, **kwargs: {"available": True, "ran": False, "returncode": None, "summary": "not-run"},
    )

    with pytest.raises(AgentExecutionError, match="top-level test count 2 does not match required 3"):
        orchestrator._validate_test_output(
            {
                "module_name": "code_implementation",
                "code": "def ok():\n    return 1",
            },
            output,
            task=task,
        )


def test_validate_test_output_rejects_top_level_test_count_maximum(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(
        summary="tests",
        raw_content="def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n",
    )
    task = Task(
        id="tests",
        title="Tests",
        description="Write at most 1 top-level test function.",
        assigned_to="qa_tester",
    )

    monkeypatch.setattr(
        orchestrator,
        "_execute_generated_tests",
        lambda *args, **kwargs: {"available": True, "ran": False, "returncode": None, "summary": "not-run"},
    )

    with pytest.raises(AgentExecutionError, match="top-level test count 2 exceeds maximum 1"):
        orchestrator._validate_test_output(
            {
                "module_name": "code_implementation",
                "code": "def ok():\n    return 1",
            },
            output,
            task=task,
        )


def test_validate_test_output_rejects_fixture_budget_and_truncation(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    output = AgentOutput(summary="tests", raw_content="def test_one():\n    assert True\n")
    task = Task(
        id="tests",
        title="Tests",
        description="Write tests with at most 1 fixture.",
        assigned_to="qa_tester",
    )

    monkeypatch.setattr(
        orchestrator,
        "_analyze_test_module",
        lambda *args, **kwargs: {"syntax_ok": True, "top_level_test_count": 1, "fixture_count": 2},
    )
    monkeypatch.setattr(
        orchestrator,
        "_execute_generated_tests",
        lambda *args, **kwargs: {"available": True, "ran": False, "returncode": None, "summary": "not-run"},
    )
    monkeypatch.setattr(
        orchestrator,
        "_completion_diagnostics_from_output",
        lambda *args, **kwargs: {"likely_truncated": True, "hit_token_limit": False},
    )

    with pytest.raises(
        AgentExecutionError,
        match="fixture count 2 exceeds maximum 1; output likely truncated before the file ended cleanly",
    ):
        orchestrator._validate_test_output(
            {
                "module_name": "code_implementation",
                "code": "def ok():\n    return 1",
            },
            output,
            task=task,
        )


def test_call_argument_value_handles_keywords_constructors_and_non_name_callables(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    class_map = {"Request": {"constructor_params": ["status", "payload"]}}

    keyword_call = ast.Call(func=ast.Name("Request"), args=[], keywords=[ast.keyword(arg="payload", value=ast.Constant("kw"))])
    positional_call = ast.Call(func=ast.Name("Request"), args=[ast.Constant("approved")], keywords=[])
    attr_call = ast.Call(func=ast.Attribute(value=ast.Name("service"), attr="build"), args=[], keywords=[])

    assert isinstance(orchestrator._call_argument_value(keyword_call, "payload", class_map), ast.Constant)
    positional_value = orchestrator._call_argument_value(positional_call, "status", class_map)
    assert isinstance(positional_value, ast.Constant)
    assert positional_value.value == "approved"
    assert orchestrator._call_argument_value(attr_call, "payload", class_map) is None
    assert orchestrator._call_argument_value(positional_call, "missing", class_map) is None
    assert orchestrator._call_argument_value(positional_call, "payload", class_map) is None


def test_validate_batch_call_reports_non_dict_missing_keys_and_nested_field_violations(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    bindings: dict[str, ast.AST] = {
        "batch": ast.List(
            elts=[
                ast.Constant("bad-item"),
                ast.Dict(keys=[ast.Constant("payload")], values=[ast.Dict(keys=[ast.Constant("name")], values=[ast.Constant("Ada")])]),
                ast.Dict(keys=[ast.Constant("request_id")], values=[ast.Constant("id-1")]),
                ast.Dict(
                    keys=[ast.Constant("request_id"), ast.Constant("payload")],
                    values=[ast.Constant("id-2"), ast.Dict(keys=[ast.Constant("name")], values=[ast.Constant("Ada")])],
                ),
            ]
        )
    }
    call_node = ast.fix_missing_locations(ast.Call(func=ast.Name("process_batch"), args=[ast.Name("batch")], keywords=[]))
    batch_rule = {"fields": ["name", "email"], "request_key": "request_id", "wrapper_key": "payload"}

    violations = orchestrator._validate_batch_call(call_node, bindings, "process_batch", batch_rule)

    assert violations == [
        "process_batch expects dict-like batch items, but test uses Constant at line 1",
        "process_batch batch item missing required key: request_id at line 1",
        "process_batch batch item nested `payload` missing required fields: email at line 1",
        "process_batch batch item missing nested payload `payload` at line 1",
        "process_batch batch item nested `payload` missing required fields: email at line 1",
    ]
    no_batch_call = ast.fix_missing_locations(ast.Call(func=ast.Name("process_batch"), args=[ast.Constant("not-a-list")], keywords=[]))
    assert orchestrator._validate_batch_call(no_batch_call, {}, "process_batch", batch_rule) == []


def test_validate_batch_call_reports_missing_nested_fields_when_nested_payload_keys_are_available(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    bindings: dict[str, ast.AST] = {
        "batch": ast.List(
            elts=[
                ast.Dict(
                    keys=[ast.Constant("request_id"), ast.Constant("payload")],
                    values=[ast.Constant("id-2"), ast.Dict(keys=[ast.Constant("name")], values=[ast.Constant("Ada")])],
                ),
            ]
        )
    }
    call_node = ast.fix_missing_locations(ast.Call(func=ast.Name("process_batch"), args=[ast.Name("batch")], keywords=[]))
    batch_rule = {"fields": ["name", "email"], "request_key": "request_id", "wrapper_key": "payload"}
    real_extract = orchestrator._extract_literal_dict_keys

    def fake_extract(node, current_bindings, class_map=None):
        if isinstance(node, ast.Subscript):
            return {"name"}
        return real_extract(node, current_bindings, class_map)

    monkeypatch.setattr(orchestrator, "_extract_literal_dict_keys", fake_extract)

    assert orchestrator._validate_batch_call(call_node, bindings, "process_batch", batch_rule) == [
        "process_batch batch item nested `payload` missing required fields: email at line 1"
    ]


def test_validate_batch_call_reports_missing_required_fields_for_direct_items(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    bindings: dict[str, ast.AST] = {
        "batch": ast.List(
            elts=[
                ast.Dict(keys=[ast.Constant("name")], values=[ast.Constant("Ada")]),
            ]
        )
    }
    call_node = ast.fix_missing_locations(ast.Call(func=ast.Name("process_batch"), args=[ast.Name("batch")], keywords=[]))
    batch_rule = {"fields": ["name", "email"], "request_key": None, "wrapper_key": None}

    assert orchestrator._validate_batch_call(call_node, bindings, "process_batch", batch_rule) == [
        "process_batch batch item missing required fields: email at line 1"
    ]


def test_validate_batch_call_accepts_complete_direct_and_nested_items(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    real_extract = orchestrator._extract_literal_dict_keys

    def fake_extract(node, current_bindings, class_map=None):
        if isinstance(node, ast.Subscript):
            return {"name", "email"}
        return real_extract(node, current_bindings, class_map)

    monkeypatch.setattr(orchestrator, "_extract_literal_dict_keys", fake_extract)
    bindings: dict[str, ast.AST] = {
        "direct_batch": ast.List(
            elts=[
                ast.Dict(
                    keys=[ast.Constant("name"), ast.Constant("email")],
                    values=[ast.Constant("Ada"), ast.Constant("ada@example.com")],
                ),
            ]
        ),
        "nested_batch": ast.List(
            elts=[
                ast.Dict(
                    keys=[ast.Constant("request_id"), ast.Constant("payload")],
                    values=[
                        ast.Constant("id-1"),
                        ast.Dict(
                            keys=[ast.Constant("name"), ast.Constant("email")],
                            values=[ast.Constant("Ada"), ast.Constant("ada@example.com")],
                        ),
                    ],
                ),
            ]
        ),
    }
    direct_call = ast.fix_missing_locations(ast.Call(func=ast.Name("process_batch"), args=[ast.Name("direct_batch")], keywords=[]))
    nested_call = ast.fix_missing_locations(ast.Call(func=ast.Name("process_batch"), args=[ast.Name("nested_batch")], keywords=[]))

    assert orchestrator._validate_batch_call(direct_call, bindings, "process_batch", {"fields": ["name", "email"], "request_key": None, "wrapper_key": None}) == []
    assert orchestrator._validate_batch_call(nested_call, bindings, "process_batch", {"fields": ["name", "email"], "request_key": "request_id", "wrapper_key": "payload"}) == []


def test_is_pytest_fixture_detects_name_attribute_and_call_decorators(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    fixture_functions = ast.parse(
        "@fixture\n"
        "def a():\n"
        "    return 1\n\n"
        "@pytest.fixture\n"
        "def b():\n"
        "    return 1\n\n"
        "@fixture(scope='module')\n"
        "def c():\n"
        "    return 1\n\n"
        "@pytest.fixture(scope='module')\n"
        "def d():\n"
        "    return 1\n\n"
        "def e():\n"
        "    return 1\n"
    ).body

    assert [orchestrator._is_pytest_fixture(node) for node in fixture_functions if isinstance(node, ast.FunctionDef)] == [True, True, True, True, False]


def test_is_pytest_fixture_handles_multiple_decorators_before_fixture(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "@custom\n"
        "@pytest.fixture(scope='module')\n"
        "def sample():\n"
        "    return 1\n"
    )

    assert orchestrator._is_pytest_fixture(function_node) is True


def test_build_test_validation_summary_handles_syntax_unavailable_and_failed_pytest(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    syntax_summary = orchestrator._build_test_validation_summary(
        {
            "syntax_ok": False,
            "syntax_error": "invalid syntax",
            "line_count": 176,
            "line_budget": 90,
            "top_level_test_count": 0,
            "fixture_count": 0,
        },
        completion_diagnostics={
            "requested_max_tokens": 1600,
            "output_tokens": 1600,
            "finish_reason": None,
            "stop_reason": "max_tokens",
            "done_reason": None,
            "hit_token_limit": True,
            "likely_truncated": True,
        },
    )

    unavailable_summary = orchestrator._build_test_validation_summary(
        {"syntax_ok": True},
        {"available": False, "summary": "pytest missing"},
    )
    failed_summary = orchestrator._build_test_validation_summary(
        {
            "syntax_ok": True,
            "imported_module_symbols": ["add"],
            "missing_function_imports": ["add (line 2)"],
            "unsupported_mock_assertions": ["logging.getLogger().info.call_count (line 6)"],
        },
        {
            "available": True,
            "ran": True,
            "returncode": 1,
            "summary": "1 failed",
            "stdout": "FAILED tests_tests.py::test_add - assert 1 == 2\n",
        },
    )

    assert "Syntax OK: no" in syntax_summary
    assert "Syntax error: invalid syntax" in syntax_summary
    assert "Line count: 176/90" in syntax_summary
    assert "Top-level test functions: 0" in syntax_summary
    assert "Fixture count: 0" in syntax_summary
    assert "Completion diagnostics: likely truncated at completion limit, token usage recorded" in syntax_summary
    assert syntax_summary.endswith("- Verdict: FAIL")
    assert "- Pytest execution: unavailable (pytest missing)" in unavailable_summary
    assert unavailable_summary.endswith("- Verdict: PASS")
    assert "- Pytest execution: FAIL" in failed_summary
    assert "Call arity mismatches: none" in failed_summary
    assert "Unsupported mock assertions: logging.getLogger().info.call_count (line 6)" in failed_summary
    assert "Pytest failure details: FAILED tests_tests.py::test_add - assert 1 == 2" in failed_summary
    assert "- Pytest summary: 1 failed" in failed_summary
    assert failed_summary.endswith("- Verdict: FAIL")


def test_build_test_validation_summary_includes_exact_limits_and_fixture_budget(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    exact_summary = orchestrator._build_test_validation_summary(
        {
            "syntax_ok": True,
            "top_level_test_count": 2,
            "expected_top_level_test_count": 2,
            "fixture_count": 1,
            "fixture_budget": 1,
        }
    )
    max_summary = orchestrator._build_test_validation_summary(
        {
            "syntax_ok": True,
            "top_level_test_count": 2,
            "max_top_level_test_count": 3,
            "fixture_count": 1,
            "fixture_budget": 2,
        }
    )

    assert "Top-level test functions: 2/2" in exact_summary
    assert "Fixture count: 1/1" in exact_summary
    assert "Top-level test functions: 2/3 max" in max_summary


def test_run_task_fails_qa_tester_when_compact_suite_imports_helper_surfaces(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    code_content = (
        "class ComplianceRequest:\n"
        "    def __init__(self):\n"
        "        self.status = 'pending'\n\n"
        "class ComplianceService:\n"
        "    def validate_request(self, request):\n"
        "        return True\n\n"
        "    def process_request(self, request):\n"
        "        request.status = 'processed'\n"
        "        return request\n\n"
        "class RiskScoringService:\n"
        "    def score_request(self, request):\n"
        "        return 1\n\n"
        "class ComplianceRepository:\n"
        "    def store_request(self, request):\n"
        "        return None\n"
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=code_content,
            output_payload={
                "summary": "class ComplianceService:",
                "raw_content": code_content,
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": code_content,
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write one compact raw pytest module under 150 lines. Use at most 3 fixtures and at most 7 top-level test functions.",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import ComplianceRequest, ComplianceService, RiskScoringService, ComplianceRepository\n\n"
        "def test_service_flow():\n"
        "    request = ComplianceRequest()\n"
        "    service = ComplianceService()\n"
        "    helper = RiskScoringService()\n"
        "    repo = ComplianceRepository()\n"
        "    assert service.process_request(request) is request\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"helper surface usages"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["helper_surface_usages"] == [
        "ComplianceRepository",
        "ComplianceRepository (line 7)",
        "RiskScoringService",
        "RiskScoringService (line 6)",
    ]


def test_output_and_task_budget_helpers_handle_empty_and_optional_inputs(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._output_line_count("") == 0
    assert orchestrator._task_requires_cli_entrypoint(None) is False
    assert orchestrator._task_fixture_budget(
        Task(id="tests", title="Tests", description="Write at most 3 fixtures.", assigned_to="qa_tester")
    ) == 3


def test_truncation_and_completion_helpers_cover_edge_cases(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    class SplitlessStr(str):
        def strip(self, chars=None):
            return "content"

        def splitlines(self, keepends=False):
            return []

    assert orchestrator._looks_structurally_truncated("", "was never closed") is False
    assert orchestrator._looks_structurally_truncated("value = 1\n", "invalid syntax") is False
    assert orchestrator._looks_structurally_truncated(SplitlessStr("placeholder"), "was never closed") is False
    assert orchestrator._looks_structurally_truncated("return 1\n", "was never closed") is False
    assert orchestrator._looks_structurally_truncated("label:\n", "expected an indented block") is True
    assert orchestrator._looks_structurally_truncated('value = "unterminated\n', "unterminated string literal") is True
    assert orchestrator._completion_validation_issue({"hit_token_limit": True}) == (
        "output likely truncated at the completion token limit"
    )
    assert orchestrator._completion_validation_issue({"hit_token_limit": False}) == (
        "output likely truncated before the file ended cleanly"
    )
    assert orchestrator._completion_diagnostics_summary({}) == "none"
    assert orchestrator._completion_diagnostics_summary(
        {"done_reason": "length", "requested_max_tokens": 10}
    ) == "completion limit reached, token usage recorded"
    assert orchestrator._completion_diagnostics_summary({"done_reason": "stop"}) == "provider termination reason recorded"
    assert orchestrator._completion_diagnostics_summary({"output_tokens": 7}) == "token usage recorded"
    assert orchestrator._pytest_failure_details(None) == []


def test_batch_result_helpers_cover_reverse_comparisons_and_fallback_cases(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    call_node = parse_call_node("process_batch(requests)")

    assert orchestrator._call_has_negative_expectation(call_node, {}) is False
    assert orchestrator._call_has_negative_expectation(
        call_node,
        orchestrator._parent_map(ast.parse("process_batch(requests)")),
    ) is False
    assert orchestrator._batch_call_allows_partial_invalid_items(
        parse_function_node("def test_case():\n    result = process_batch(requests)\n"),
        parse_call_node("process_batch(requests)"),
        {},
        {},
    ) is False
    ann_assign_module = ast.parse("results: list[str] = process_batch(requests)")
    ann_assign = ann_assign_module.body[0]
    assert isinstance(ann_assign, ast.AnnAssign)
    assert isinstance(ann_assign.value, ast.Call)
    parent_map = orchestrator._parent_map(ann_assign_module)
    assert orchestrator._assigned_name_for_call(ann_assign.value, parent_map) == "results"
    assert orchestrator._assigned_name_for_call(call_node, {}) is None
    assert orchestrator._assert_limits_batch_result(
        parse_expr_node("1 > len(results)"),
        "results",
        call_node,
        3,
    ) is True
    assert orchestrator._assert_limits_batch_result(parse_expr_node("len(results)"), "results", call_node, 3) is False
    assert orchestrator._assert_limits_batch_result(parse_expr_node("count == 1"), "results", call_node, 3) is False
    assert orchestrator._len_call_matches_batch_result(ast.Name("results"), "results", call_node) is False
    assert orchestrator._len_call_matches_batch_result(parse_expr_node("count(results)"), "results", call_node) is False
    direct_len = parse_call_node("len(process_batch(requests))")
    assert isinstance(direct_len.args[0], ast.Call)
    assert orchestrator._len_call_matches_batch_result(direct_len, None, direct_len.args[0]) is True
    assert orchestrator._int_constant_value(ast.Constant("x")) is None
    assert orchestrator._comparison_implies_partial_batch_result(ast.Gt(), 1, 3) is False
    assert orchestrator._comparison_implies_partial_batch_result(ast.Lt(), 3, 3) is True
    assert orchestrator._comparison_implies_partial_batch_result(ast.LtE(), 2, 3) is True
    assert orchestrator._comparison_implies_partial_batch_result(ast.Eq(), None, 3) is False
    false_compare = parse_assert_node("assert False == validate_request(data)")
    assert isinstance(false_compare.test, ast.Compare)
    assert isinstance(false_compare.test.comparators[0], ast.Call)
    assert orchestrator._assert_expects_false(false_compare, false_compare.test.comparators[0]) is True
    plain_assert = parse_assert_node("assert validate_request(data)")
    assert isinstance(plain_assert.test, ast.Call)
    assert orchestrator._assert_expects_false(plain_assert, plain_assert.test) is False
    unrelated_compare = parse_assert_node("assert other_result == False")
    assert orchestrator._assert_expects_false(unrelated_compare, call_node) is False
    invalid_status_assert = parse_assert_node("assert request.status == 'Invalid'")
    assert orchestrator._assert_expects_invalid_outcome(invalid_status_assert.test, None, "request") is True
    pending_status_assert = parse_assert_node("assert request.status == 'Pending'")
    assert orchestrator._assert_expects_invalid_outcome(pending_status_assert.test, None, "request") is True
    false_result_assert = parse_assert_node("assert result is False")
    assert orchestrator._assert_expects_invalid_outcome(false_result_assert.test, "result", None) is True
    with_node = parse_with_node("with context_manager:\n    validate_request(data)\n")
    assert orchestrator._with_uses_pytest_raises(with_node) is False
    warns_with_node = parse_with_node("with pytest.warns(ValueError):\n    validate_request(data)\n")
    assert orchestrator._with_uses_pytest_raises(warns_with_node) is False


def test_batch_partial_invalid_detection_returns_false_when_asserts_do_not_limit_batch(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = parse_function_node(
        "def test_batch():\n"
        "    result = process_batch([1, 2, 3])\n"
        "    assert len(other) == 3\n"
    )
    tree = ast.parse(
        "def test_batch():\n"
        "    result = process_batch([1, 2, 3])\n"
        "    assert len(other) == 3\n"
    )
    first_statement = function_node.body[0]
    assert isinstance(first_statement, ast.Assign)
    assert isinstance(first_statement.value, ast.Call)
    call_node = first_statement.value
    parent_map = orchestrator._parent_map(tree)

    assert orchestrator._batch_call_allows_partial_invalid_items(function_node, call_node, {}, parent_map) is False


def test_name_binding_and_type_helpers_cover_remaining_edge_cases(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._collect_module_defined_names(ast.Constant(1)) == set()
    assert orchestrator._collect_module_defined_names(ast.parse("annotated_only: int\n")) == {"annotated_only"}
    assert orchestrator._collect_module_defined_names(ast.parse("42\nannotated_only: int\n")) == {"annotated_only"}
    module_tree = ast.parse(
        "from pkg import *\n"
        "import os as operating_system\n"
        "value = 1\n"
        "annotated: int = 2\n"
        "holder.value: int = 3\n"
    )
    assert orchestrator._collect_module_defined_names(module_tree) == {"operating_system", "value", "annotated"}

    function_node = parse_function_node(
        "@plain\n"
        "@pytest.mark.skip(reason='ignored')\n"
        "@custom.parametrize('ignored', [1])\n"
        "@pytest.mark.parametrize(argnames=['left', 'right'], argvalues=[(1, 2)])\n"
        "def test_sample(base, *args, **kwargs):\n"
        "    total: int = 0\n"
        "    total += 1\n"
        "    for item in items:\n"
        "        pass\n"
        "    with manager() as handle:\n"
        "        pass\n"
        "    try:\n"
        "        raise ValueError()\n"
        "    except ValueError as err:\n"
        "        pass\n"
        "    if (captured := base):\n"
        "        pass\n"
        "    values = [entry for entry in source]\n"
        "    import math as mathematics\n"
        "    from os import path as os_path\n"
        "    from os import *\n"
        "    helper = lambda value: missing\n"
        "    def nested():\n"
        "        return missing\n"
        "    class Nested:\n"
        "        attr = missing\n"
    )
    class_init = parse_function_node(
        "def __init__(self):\n"
        "    self.value: int = 1\n"
    )
    class_init_with_local = parse_function_node(
        "def __init__(self):\n"
        "    self.value: int = 1\n"
        "    local = 2\n"
    )

    assert orchestrator._function_argument_names(function_node) == {"base", "args", "kwargs"}
    assert orchestrator._collect_parametrized_argument_names(function_node) == {"left", "right"}
    bindings = orchestrator._collect_local_name_bindings(function_node)
    assert {
        "total",
        "item",
        "handle",
        "err",
        "captured",
        "entry",
        "mathematics",
        "os_path",
        "values",
    } <= bindings
    assert "missing" not in orchestrator._collect_undefined_local_names(function_node, {"items", "manager", "source"})
    assert orchestrator._self_assigned_attributes(class_init) == ["value"]
    assert orchestrator._self_assigned_attributes(class_init_with_local) == ["value"]
    starred_assign = ast.parse("first, *rest = values").body[0]
    assert isinstance(starred_assign, ast.Assign)
    starred_target = starred_assign.targets[0]
    assert orchestrator._bound_target_names(starred_target) == {"first", "rest"}
    assert orchestrator._bound_target_names(ast.Attribute(value=ast.Name("obj"), attr="field")) == set()


def test_type_inference_and_member_usage_helpers_cover_remaining_cases(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    class_map = {
        "Request": {
            "attributes": ["request_id"],
            "fields": [],
            "is_enum": False,
            "method_signatures": {},
        },
        "Service": {
            "attributes": [],
            "fields": [],
            "is_enum": False,
            "method_signatures": {
                "fetch": {"min_args": 1, "max_args": 2, "return_annotation": "Request"},
                "untyped": {"min_args": None, "max_args": None, "return_annotation": "Request"},
                "range_fetch": {"min_args": 1, "max_args": 2, "return_annotation": "Request"},
            },
        },
    }
    function_map = {
        "build_request": {"return_annotation": "Request"},
        "build_text": {"return_annotation": "str"},
    }
    test_node = parse_function_node(
        "def test_case():\n"
        "    request: Request = build_request()\n"
        "    text: str = build_text()\n"
        "    service = Service()\n"
        "    returned = service.fetch({'request_id': 'req-1'})\n"
        "    service.untyped('x')\n"
        "    service.range_fetch(1, 2, 3)\n"
        "    service.missing()\n"
        "    assert returned.invalid == 1\n"
    )

    local_types = orchestrator._collect_test_local_types(test_node, class_map, function_map)

    assert local_types["request"] == "Request"
    assert local_types["service"] == "Service"
    assert local_types["returned"] == "Request"
    assert "text" not in local_types
    assert orchestrator._infer_call_result_type(
        ast.parse("build_text()", mode="eval").body,
        {},
        class_map,
        function_map,
    ) is None
    assert orchestrator._infer_call_result_type(
        ast.parse("missing_factory()", mode="eval").body,
        {},
        class_map,
        function_map,
    ) is None
    assert orchestrator._infer_call_result_type(
        ast.parse("factory().fetch()", mode="eval").body,
        {},
        class_map,
        function_map,
    ) is None
    assert orchestrator._infer_call_result_type(
        ast.parse("service.fetch()", mode="eval").body,
        {},
        class_map,
        function_map,
    ) is None
    assert orchestrator._infer_call_result_type(
        ast.parse("service.unknown()", mode="eval").body,
        {"service": "Service"},
        class_map,
        function_map,
    ) is None

    invalid_refs, arity_mismatches = orchestrator._analyze_typed_test_member_usage(test_node, local_types, class_map)

    assert invalid_refs == ["Request.invalid (line 9)", "Service.missing (line 8)"]
    assert arity_mismatches == ["Service.range_fetch expects 1-2 args but test uses 3 at line 7"]


def test_type_inference_and_member_usage_helpers_support_inline_constructor_calls(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    class_map = {
        "Request": {
            "attributes": ["request_id"],
            "fields": [],
            "is_enum": False,
            "method_signatures": {},
        },
        "Service": {
            "attributes": [],
            "fields": [],
            "is_enum": False,
            "method_signatures": {
                "fetch": {"min_args": 1, "max_args": 1, "return_annotation": "Request"},
                "range_fetch": {"min_args": 1, "max_args": 2, "return_annotation": "Request"},
            },
        },
    }
    function_map: dict[str, dict[str, Any]] = {}
    test_node = parse_function_node(
        "def test_inline_case():\n"
        "    returned = Service().fetch({'request_id': 'req-1'})\n"
        "    Service().missing()\n"
        "    Service().range_fetch(1, 2, 3)\n"
        "    assert returned.invalid == 1\n"
    )

    local_types = orchestrator._collect_test_local_types(test_node, class_map, function_map)

    assert local_types["returned"] == "Request"
    assert orchestrator._infer_call_result_type(
        ast.parse("Service().fetch({'request_id': 'req-1'})", mode="eval").body,
        {},
        class_map,
        function_map,
    ) == "Request"

    invalid_refs, arity_mismatches = orchestrator._analyze_typed_test_member_usage(
        test_node,
        local_types,
        class_map,
        function_map,
    )

    assert invalid_refs == ["Request.invalid (line 5)", "Service.missing (line 3)"]
    assert arity_mismatches == ["Service.range_fetch expects 1-2 args but test uses 3 at line 4"]


def test_analyze_typed_test_member_usage_treats_enum_fields_as_invalid_members(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    test_node = parse_function_node(
        "def test_enum_usage():\n"
        "    status = Status()\n"
        "    assert status.value == 'ok'\n"
    )
    local_types = {"status": "Status"}
    class_map = {
        "Status": {
            "attributes": [],
            "fields": ["value"],
            "is_enum": True,
            "method_signatures": {},
        }
    }

    invalid_refs, arity_mismatches = orchestrator._analyze_typed_test_member_usage(test_node, local_types, class_map)

    assert invalid_refs == ["Status.value (line 3)"]
    assert arity_mismatches == []


def test_analyze_test_module_reports_constructor_arity_when_limits_fall_back_or_span_range(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    module_analysis = {
        "syntax_ok": True,
        "functions": [],
        "classes": {
            "Request": {
                "name": "Request",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": ["request_id"],
                "methods": [],
                "method_signatures": {},
            },
            "Envelope": {
                "name": "Envelope",
                "bases": [],
                "is_enum": False,
                "fields": [],
                "attributes": [],
                "constructor_params": ["left", "right"],
                "constructor_min_args": 1,
                "constructor_max_args": 2,
                "methods": [],
                "method_signatures": {},
            },
        },
        "imports": [],
        "third_party_imports": [],
        "symbols": ["Envelope", "Request"],
    }
    test_content = (
        "from module_under_test import Envelope, Request\n\n"
        "def test_request_shapes():\n"
        "    Request()\n"
        "    Envelope(1, 2, 3)\n"
    )

    analysis = orchestrator._analyze_test_module(test_content, "module_under_test", module_analysis)

    assert analysis["constructor_arity_mismatches"] == [
        "Envelope expects 1-2 args but test uses 3 at line 5",
        "Request expects 1 args but test uses 0 at line 4",
    ]


def test_extract_parametrize_argument_names_skips_irrelevant_keywords(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    keyword_decorator = parse_function_node(
        "@pytest.mark.parametrize(values=[1], argnames=['left'])\n"
        "def test_case():\n"
        "    pass\n"
    ).decorator_list[0]
    missing_decorator = parse_function_node(
        "@pytest.mark.parametrize(values=[1])\n"
        "def test_case():\n"
        "    pass\n"
    ).decorator_list[0]

    assert isinstance(keyword_decorator, ast.Call)
    assert isinstance(missing_decorator, ast.Call)

    assert orchestrator._extract_parametrize_argument_names(keyword_decorator) == {"left"}
    assert orchestrator._extract_parametrize_argument_names(missing_decorator) == set()


def test_build_code_behavior_contract_ignores_non_function_class_members(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    contract = orchestrator._build_code_behavior_contract(
        "class Request:\n"
        "    request_id: str\n"
        "    status = 'ok'\n"
        "    def validate(self, payload):\n"
        "        required_fields = ['request_id']\n"
        "        return payload\n"
    )

    assert "Behavior contract:" in contract
    assert "validate requires fields: request_id" in contract


def test_build_code_behavior_contract_reports_sequence_accepting_functions(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    contract = orchestrator._build_code_behavior_contract(
        "from typing import List\n\n"
        "def process_requests(requests: List[str]) -> None:\n"
        "    for request in requests:\n"
        "        print(request)\n"
    )

    assert "process_requests accepts sequence inputs via parameter `requests`" in contract


def test_build_test_validation_summary_omits_execution_lines_when_pytest_did_not_run(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_test_validation_summary(
        {"syntax_ok": True},
        {"available": True, "ran": False, "summary": "not-run"},
    )

    assert "- Pytest execution:" not in summary
    assert summary.endswith("- Verdict: PASS")


def test_ast_name_formats_nested_attributes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    node = ast.Attribute(value=ast.Attribute(value=ast.Name("pkg"), attr="module"), attr="Class")

    assert orchestrator._ast_name(node) == "pkg.module.Class"
    assert orchestrator._ast_name(ast.Constant("x")) == "x"


def test_summarize_output_returns_blank_for_whitespace_and_truncates_first_line(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._summarize_output("   ") == ""
    assert orchestrator._summarize_output("  first line  \nsecond line") == "first line"
    assert len(orchestrator._summarize_output("x" * 200)) == 120


@pytest.mark.parametrize(
    ("task", "expected_key"),
    [
        (Task(id="t1", title="Architecture Review", description="", assigned_to="unknown"), "architecture"),
        (Task(id="t2", title="Security Review", description="", assigned_to="unknown"), "review"),
        (Task(id="t3", title="Test Cases", description="", assigned_to="unknown"), "tests"),
        (Task(id="t4", title="Package Manifest", description="", assigned_to="unknown"), "dependencies"),
        (Task(id="t5", title="Docs Bundle", description="", assigned_to="unknown"), "documentation"),
        (Task(id="t6", title="License Scan", description="", assigned_to="unknown"), "legal"),
        (Task(id="t7", title="Misc Task", description="", assigned_to="unknown"), None),
    ],
)
def test_semantic_output_key_title_fallbacks(tmp_path, task, expected_key):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._semantic_output_key(task) == expected_key


def test_build_agent_input_uses_repair_defaults_when_optional_fields_are_blank(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    task = Task(
        id="repair",
        title="Repair architecture",
        description="Repair the architecture",
        assigned_to="architect",
        repair_context={
            "instruction": "",
            "failure_category": "",
            "failure_message": "   ",
            "validation_summary": "   ",
        },
    )
    project.add_task(task)

    agent_input = orchestrator._build_agent_input(task, project)

    assert "Repair objective:" in agent_input.task_description
    assert "Repair the previous failure." in agent_input.task_description
    assert f"Previous failure category: {FailureCategory.UNKNOWN.value}" in agent_input.task_description
    assert "Previous failure message:" not in agent_input.task_description
    assert "Validation summary:" not in agent_input.task_description


def test_validate_agent_resolution_accepts_known_registry(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": RecordingAgent("ok")}))

    assert orchestrator._validate_agent_resolution(project) is None


def test_execute_workflow_marks_failed_when_runnable_tasks_raise_definition_error(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": RecordingAgent("ARCH")}))

    monkeypatch.setattr(project, "runnable_tasks", lambda: (_ for _ in ()).throw(WorkflowDefinitionError("cycle")))

    with pytest.raises(WorkflowDefinitionError, match="cycle"):
        orchestrator.execute_workflow(project)

    assert project.phase == "failed"
    assert project.failure_category == FailureCategory.WORKFLOW_DEFINITION.value
    assert project.terminal_outcome == WorkflowOutcome.FAILED.value


def test_execute_workflow_marks_blocked_when_no_runnable_tasks_exist(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    blocked_task = Task(id="blocked", title="Blocked task", description="Wait", assigned_to="architect")
    project.add_task(blocked_task)
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": RecordingAgent("ARCH")}))

    monkeypatch.setattr(project, "runnable_tasks", lambda: [])
    monkeypatch.setattr(project, "blocked_tasks", lambda: [blocked_task])

    with pytest.raises(AgentExecutionError, match="Workflow is blocked"):
        orchestrator.execute_workflow(project)

    assert project.phase == "failed"
    assert project.failure_category == FailureCategory.WORKFLOW_BLOCKED.value
    assert project.terminal_outcome == WorkflowOutcome.FAILED.value


def test_execute_generated_tests_blocks_subprocess_calls_in_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import subprocess\n\n"
        "def spawn_child():\n"
        "    subprocess.run(['echo', 'hi'], check=False)\n",
        "tests_generated.py",
        "from code_under_test import spawn_child\n\n"
        "def test_spawn_child_is_blocked():\n"
        "    spawn_child()\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked" in result["stdout"] or "sandbox policy blocked" in result["stderr"]
    assert result["sandbox"]["allow_subprocesses"] is False


def test_execute_generated_tests_blocks_os_spawn_calls_in_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\nimport sys\n\n"
        "def spawn_child():\n"
        "    os.spawnv(os.P_WAIT, sys.executable, [sys.executable, '-c', 'print(123)'])\n",
        "tests_generated.py",
        "from code_under_test import spawn_child\n\n"
        "def test_spawnv_is_blocked():\n"
        "    spawn_child()\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked" in result["stdout"] or "sandbox policy blocked" in result["stderr"]
    assert result["sandbox"]["allow_subprocesses"] is False


def test_execute_generated_tests_blocks_network_calls_in_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import socket\n\n"
        "def open_socket():\n"
        "    socket.create_connection(('example.com', 80), timeout=1)\n",
        "tests_generated.py",
        "from code_under_test import open_socket\n\n"
        "def test_network_is_blocked():\n"
        "    open_socket()\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked this operation" in result["stdout"] or "sandbox policy blocked this operation" in result["stderr"]
    assert result["sandbox"]["allow_network"] is False


def test_execute_generated_tests_blocks_getaddrinfo_in_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import socket\n\n"
        "def resolve_host():\n"
        "    socket.getaddrinfo('example.com', 80)\n",
        "tests_generated.py",
        "from code_under_test import resolve_host\n\n"
        "def test_getaddrinfo_is_blocked():\n"
        "    resolve_host()\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked this operation" in result["stdout"] or "sandbox policy blocked this operation" in result["stderr"]
    assert result["sandbox"]["allow_network"] is False


def test_execute_generated_tests_blocks_gethostbyname_in_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import socket\n\n"
        "def resolve_host():\n"
        "    socket.gethostbyname('example.com')\n",
        "tests_generated.py",
        "from code_under_test import resolve_host\n\n"
        "def test_gethostbyname_is_blocked():\n"
        "    resolve_host()\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked this operation" in result["stdout"] or "sandbox policy blocked this operation" in result["stderr"]
    assert result["sandbox"]["allow_network"] is False


def test_execute_generated_tests_blocks_ctypes_loading_in_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import ctypes\nimport ctypes.util\n\n"
        "def load_native_library():\n"
        "    ctypes.CDLL(None)\n"
        "    ctypes.util.find_library('c')\n",
        "tests_generated.py",
        "from code_under_test import load_native_library\n\n"
        "def test_ctypes_loading_is_blocked():\n"
        "    load_native_library()\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked this operation" in result["stdout"] or "sandbox policy blocked this operation" in result["stderr"]


def test_execute_generated_tests_blocks_mmap_calls_in_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import mmap\n\n"
        "def allocate_memory_map():\n"
        "    mapping = mmap.mmap(-1, 64)\n"
        "    mapping.close()\n",
        "tests_generated.py",
        "from code_under_test import allocate_memory_map\n\n"
        "def test_mmap_is_blocked():\n"
        "    allocate_memory_map()\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked this operation" in result["stdout"] or "sandbox policy blocked this operation" in result["stderr"]


def test_execute_generated_tests_blocks_chdir_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_chdir").resolve()
    escaped_dir.mkdir()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def leave_sandbox(target_path):\n"
        "    os.chdir(target_path)\n",
        "tests_generated.py",
        "from code_under_test import leave_sandbox\n\n"
        f"def test_chdir_is_blocked():\n"
        f"    leave_sandbox({str(escaped_dir)!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked" in result["stdout"] or "sandbox policy blocked" in result["stderr"]


def test_execute_generated_tests_blocks_fd_duplication_in_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def duplicate_stdout():\n"
        "    os.dup(1)\n",
        "tests_generated.py",
        "from code_under_test import duplicate_stdout\n\n"
        "def test_fd_duplication_is_blocked():\n"
        "    duplicate_stdout()\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked this operation" in result["stdout"] or "sandbox policy blocked this operation" in result["stderr"]


def test_execute_generated_tests_blocks_fd_wrapping_in_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import io\nimport os\n\n"
        "def wrap_stdout():\n"
        "    handle = io.open(1, 'w', closefd=False)\n"
        "    try:\n"
        "        return handle.writable()\n"
        "    finally:\n"
        "        handle.close()\n",
        "tests_generated.py",
        "from code_under_test import wrap_stdout\n\n"
        "def test_fd_wrapping_is_blocked():\n"
        "    wrap_stdout()\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked this operation" in result["stdout"] or "sandbox policy blocked this operation" in result["stderr"]


def test_execute_generated_tests_blocks_xattr_reads_outside_sandbox_when_supported(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_xattr_read.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")
    attribute_name = "user.kycortex_read"
    attribute_value = b"secret"

    if not supports_user_xattrs(escaped_file):
        pytest.skip("user xattrs unsupported")

    os.setxattr(escaped_file, attribute_name, attribute_value)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_xattrs(target_path, attribute_name):\n"
        "    return (os.listxattr(target_path), os.getxattr(target_path, attribute_name))\n",
        "tests_generated.py",
        "from code_under_test import read_xattrs\n\n"
        f"def test_xattr_reads_are_blocked_when_supported():\n"
        f"    read_xattrs({str(escaped_file)!r}, {attribute_name!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_xattr_mutation_outside_sandbox_when_supported(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_xattr_write.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")
    attribute_name = "user.kycortex_write"
    attribute_value = b"secret"

    if not supports_user_xattrs(escaped_file):
        pytest.skip("user xattrs unsupported")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def write_xattr(target_path, attribute_name, attribute_value):\n"
        "    os.setxattr(target_path, attribute_name, attribute_value)\n",
        "tests_generated.py",
        "from code_under_test import write_xattr\n\n"
        f"def test_xattr_mutation_is_blocked_when_supported():\n"
        f"    write_xattr({str(escaped_file)!r}, {attribute_name!r}, {attribute_value!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked filesystem write outside sandbox root" in result["stdout"] or "sandbox policy blocked filesystem write outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_filesystem_writes_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_path = (tmp_path / "escaped.txt").resolve()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "def write_outside_sandbox(target_path):\n"
        "    with open(target_path, 'w', encoding='utf-8') as handle:\n"
        "        handle.write('escaped')\n",
        "tests_generated.py",
        "from code_under_test import write_outside_sandbox\n\n"
        f"def test_filesystem_write_is_blocked():\n"
        f"    write_outside_sandbox({str(escaped_path)!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked filesystem write outside sandbox root" in result["stdout"] or "sandbox policy blocked filesystem write outside sandbox root" in result["stderr"]
    assert not escaped_path.exists()


def test_execute_generated_tests_blocks_file_reads_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_path = (tmp_path / "escaped_read.txt").resolve()
    escaped_path.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "def read_outside_sandbox(target_path):\n"
        "    with open(target_path, 'r', encoding='utf-8') as handle:\n"
        "        return handle.read()\n",
        "tests_generated.py",
        "from code_under_test import read_outside_sandbox\n\n"
        f"def test_filesystem_read_is_blocked():\n"
        f"    read_outside_sandbox({str(escaped_path)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_directory_enumeration_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_listing").resolve()
    escaped_dir.mkdir()
    (escaped_dir / "secret.txt").write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def list_directory(target_path):\n"
        "    return os.listdir(target_path)\n",
        "tests_generated.py",
        "from code_under_test import list_directory\n\n"
        f"def test_directory_enumeration_is_blocked():\n"
        f"    list_directory({str(escaped_dir)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_file_metadata_probes_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_meta.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def file_exists(target_path):\n"
        "    return Path(target_path).exists()\n",
        "tests_generated.py",
        "from code_under_test import file_exists\n\n"
        f"def test_file_metadata_probe_is_blocked():\n"
        f"    file_exists({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_path_getsize_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_getsize.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_size(target_path):\n"
        "    return os.path.getsize(target_path)\n",
        "tests_generated.py",
        "from code_under_test import read_size\n\n"
        f"def test_os_path_getsize_is_blocked():\n"
        f"    read_size({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_path_getmtime_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_getmtime.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_mtime(target_path):\n"
        "    return os.path.getmtime(target_path)\n",
        "tests_generated.py",
        "from code_under_test import read_mtime\n\n"
        f"def test_os_path_getmtime_is_blocked():\n"
        f"    read_mtime({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_path_getctime_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_getctime.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_ctime(target_path):\n"
        "    return os.path.getctime(target_path)\n",
        "tests_generated.py",
        "from code_under_test import read_ctime\n\n"
        f"def test_os_path_getctime_is_blocked():\n"
        f"    read_ctime({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_path_getatime_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_getatime.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_atime(target_path):\n"
        "    return os.path.getatime(target_path)\n",
        "tests_generated.py",
        "from code_under_test import read_atime\n\n"
        f"def test_os_path_getatime_is_blocked():\n"
        f"    read_atime({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_glob_enumeration_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_glob").resolve()
    escaped_dir.mkdir()
    (escaped_dir / "secret.txt").write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import glob\n\n"
        "def list_matches(pattern):\n"
        "    return glob.glob(pattern)\n",
        "tests_generated.py",
        "from code_under_test import list_matches\n\n"
        f"def test_glob_enumeration_is_blocked():\n"
        f"    list_matches({str(escaped_dir / '*')!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_pathlib_iteration_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_iterdir").resolve()
    escaped_dir.mkdir()
    (escaped_dir / "secret.txt").write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def list_children(target_path):\n"
        "    return [child.name for child in Path(target_path).iterdir()]\n",
        "tests_generated.py",
        "from code_under_test import list_children\n\n"
        f"def test_pathlib_iteration_is_blocked():\n"
        f"    list_children({str(escaped_dir)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_walk_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_walk").resolve()
    escaped_dir.mkdir()
    (escaped_dir / "secret.txt").write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def walk_tree(target_path):\n"
        "    return list(os.walk(target_path))\n",
        "tests_generated.py",
        "from code_under_test import walk_tree\n\n"
        f"def test_os_walk_is_blocked():\n"
        f"    walk_tree({str(escaped_dir)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_fwalk_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_fwalk").resolve()
    escaped_dir.mkdir()
    (escaped_dir / "secret.txt").write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def walk_tree(target_path):\n"
        "    return list(os.fwalk(target_path))\n",
        "tests_generated.py",
        "from code_under_test import walk_tree\n\n"
        f"def test_os_fwalk_is_blocked():\n"
        f"    walk_tree({str(escaped_dir)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_path_readlink_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_target = (tmp_path / "escaped_target.txt").resolve()
    escaped_target.write_text("secret", encoding="utf-8")
    escaped_link = (tmp_path / "escaped_link_meta").resolve()
    escaped_link.symlink_to(escaped_target)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def resolve_link(target_path):\n"
        "    return str(Path(target_path).readlink())\n",
        "tests_generated.py",
        "from code_under_test import resolve_link\n\n"
        f"def test_path_readlink_is_blocked():\n"
        f"    resolve_link({str(escaped_link)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_readlink_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_target = (tmp_path / "escaped_os_readlink_target.txt").resolve()
    escaped_target.write_text("secret", encoding="utf-8")
    escaped_link = (tmp_path / "escaped_os_readlink_link").resolve()
    escaped_link.symlink_to(escaped_target)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def resolve_link(target_path):\n"
        "    return os.readlink(target_path)\n",
        "tests_generated.py",
        "from code_under_test import resolve_link\n\n"
        f"def test_os_readlink_is_blocked():\n"
        f"    resolve_link({str(escaped_link)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_samefile_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_samefile.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def is_same_file(left_path, right_path):\n"
        "    return Path(left_path).samefile(right_path)\n",
        "tests_generated.py",
        "from code_under_test import is_same_file\n\n"
        f"def test_samefile_is_blocked():\n"
        f"    is_same_file({str(escaped_file)!r}, {str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_path_realpath_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_target = (tmp_path / "escaped_realpath_target.txt").resolve()
    escaped_target.write_text("secret", encoding="utf-8")
    escaped_link = (tmp_path / "escaped_realpath_link.txt").resolve()
    escaped_link.symlink_to(escaped_target)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def resolve_path(target_path):\n"
        "    return os.path.realpath(target_path)\n",
        "tests_generated.py",
        "from code_under_test import resolve_path\n\n"
        f"def test_os_path_realpath_is_blocked():\n"
        f"    resolve_path({str(escaped_link)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_path_isabs_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_isabs_target.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def is_absolute_path(target_path):\n"
        "    return os.path.isabs(target_path)\n",
        "tests_generated.py",
        "from code_under_test import is_absolute_path\n\n"
        f"def test_os_path_isabs_is_blocked():\n"
        f"    is_absolute_path({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_path_samefile_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_os_path_samefile.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def is_same_file(left_path, right_path):\n"
        "    return os.path.samefile(left_path, right_path)\n",
        "tests_generated.py",
        "from code_under_test import is_same_file\n\n"
        f"def test_os_path_samefile_is_blocked():\n"
        f"    is_same_file({str(escaped_file)!r}, {str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_path_owner_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_path_owner.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def read_owner(target_path):\n"
        "    return Path(target_path).owner()\n",
        "tests_generated.py",
        "from code_under_test import read_owner\n\n"
        f"def test_path_owner_is_blocked():\n"
        f"    read_owner({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_path_group_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_path_group.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def read_group(target_path):\n"
        "    return Path(target_path).group()\n",
        "tests_generated.py",
        "from code_under_test import read_group\n\n"
        f"def test_path_group_is_blocked():\n"
        f"    read_group({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_path_ismount_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_os_path_ismount").resolve()
    escaped_dir.mkdir()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def is_mount_point(target_path):\n"
        "    return os.path.ismount(target_path)\n",
        "tests_generated.py",
        "from code_under_test import is_mount_point\n\n"
        f"def test_os_path_ismount_is_blocked():\n"
        f"    is_mount_point({str(escaped_dir)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_path_is_mount_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_path_is_mount").resolve()
    escaped_dir.mkdir()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def is_mount_point(target_path):\n"
        "    return Path(target_path).is_mount()\n",
        "tests_generated.py",
        "from code_under_test import is_mount_point\n\n"
        f"def test_path_is_mount_is_blocked():\n"
        f"    is_mount_point({str(escaped_dir)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_path_type_helpers_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_path_type_helpers.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def read_types(target_path):\n"
        "    target = Path(target_path)\n"
        "    return (\n"
        "        target.is_block_device(),\n"
        "        target.is_char_device(),\n"
        "        target.is_fifo(),\n"
        "        target.is_socket(),\n"
        "    )\n",
        "tests_generated.py",
        "from code_under_test import read_types\n\n"
        f"def test_path_type_helpers_are_blocked():\n"
        f"    read_types({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_path_isjunction_outside_sandbox_when_supported(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_os_path_isjunction").resolve()
    escaped_dir.mkdir()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def is_junction_point(target_path):\n"
        "    if not hasattr(os.path, 'isjunction'):\n"
        "        return 'unsupported'\n"
        "    return os.path.isjunction(target_path)\n",
        "tests_generated.py",
        "import os\nimport pytest\n"
        "from code_under_test import is_junction_point\n\n"
        "def test_os_path_isjunction_is_blocked_when_supported():\n"
        "    if not hasattr(os.path, 'isjunction'):\n"
        "        pytest.skip('os.path.isjunction unavailable')\n"
        f"    is_junction_point({str(escaped_dir)!r})\n",
    )

    if hasattr(os.path, "isjunction"):
        assert result["returncode"] != 0
        assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]
    else:
        assert result["returncode"] == 0
        assert "1 skipped" in result["stdout"]


def test_execute_generated_tests_blocks_path_is_junction_outside_sandbox_when_supported(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_path_is_junction").resolve()
    escaped_dir.mkdir()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def is_junction_point(target_path):\n"
        "    target = Path(target_path)\n"
        "    if not hasattr(target, 'is_junction'):\n"
        "        return 'unsupported'\n"
        "    return target.is_junction()\n",
        "tests_generated.py",
        "import pytest\n"
        "from pathlib import Path\n"
        "from code_under_test import is_junction_point\n\n"
        "def test_path_is_junction_is_blocked_when_supported():\n"
        "    if not hasattr(Path('.'), 'is_junction'):\n"
        "        pytest.skip('Path.is_junction unavailable')\n"
        f"    is_junction_point({str(escaped_dir)!r})\n",
    )

    if hasattr(pathlib.Path("."), "is_junction"):
        assert result["returncode"] != 0
        assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]
    else:
        assert result["returncode"] == 0
        assert "1 skipped" in result["stdout"]


def test_execute_generated_tests_blocks_os_stat_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_stat.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_mode(target_path):\n"
        "    return os.stat(target_path).st_mode\n",
        "tests_generated.py",
        "from code_under_test import read_mode\n\n"
        f"def test_os_stat_is_blocked():\n"
        f"    read_mode({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_os_lstat_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_target = (tmp_path / "escaped_lstat_target.txt").resolve()
    escaped_target.write_text("secret", encoding="utf-8")
    escaped_link = (tmp_path / "escaped_lstat_link.txt").resolve()
    escaped_link.symlink_to(escaped_target)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_link_mode(target_path):\n"
        "    return os.lstat(target_path).st_mode\n",
        "tests_generated.py",
        "from code_under_test import read_link_mode\n\n"
        f"def test_os_lstat_is_blocked():\n"
        f"    read_link_mode({str(escaped_link)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_path_stat_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_path_stat.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def read_mode(target_path):\n"
        "    return Path(target_path).stat().st_mode\n",
        "tests_generated.py",
        "from code_under_test import read_mode\n\n"
        f"def test_path_stat_is_blocked():\n"
        f"    read_mode({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_path_lstat_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_target = (tmp_path / "escaped_path_lstat_target.txt").resolve()
    escaped_target.write_text("secret", encoding="utf-8")
    escaped_link = (tmp_path / "escaped_path_lstat_link.txt").resolve()
    escaped_link.symlink_to(escaped_target)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def read_link_mode(target_path):\n"
        "    return Path(target_path).lstat().st_mode\n",
        "tests_generated.py",
        "from code_under_test import read_link_mode\n\n"
        f"def test_path_lstat_is_blocked():\n"
        f"    read_link_mode({str(escaped_link)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_path_resolve_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_target = (tmp_path / "escaped_resolve_target.txt").resolve()
    escaped_target.write_text("secret", encoding="utf-8")
    escaped_link = (tmp_path / "escaped_resolve_link").resolve()
    escaped_link.symlink_to(escaped_target)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def resolve_path(target_path):\n"
        "    return str(Path(target_path).resolve())\n",
        "tests_generated.py",
        "from code_under_test import resolve_path\n\n"
        f"def test_path_resolve_is_blocked():\n"
        f"    resolve_path({str(escaped_link)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]

def test_execute_generated_tests_blocks_path_walk_outside_sandbox_when_supported(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_path_walk").resolve()
    escaped_dir.mkdir()
    (escaped_dir / "secret.txt").write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def walk_tree(target_path):\n"
        "    target = Path(target_path)\n"
        "    if not hasattr(target, 'walk'):\n"
        "        return 'unsupported'\n"
        "    return list(target.walk())\n",
        "tests_generated.py",
        "import pytest\n"
        "from pathlib import Path\n\n"
        "from code_under_test import walk_tree\n\n"
        "def test_path_walk_is_blocked_when_supported():\n"
        "    if not hasattr(Path('.'), 'walk'):\n"
        "        pytest.skip('Path.walk unavailable')\n"
        f"    walk_tree({str(escaped_dir)!r})\n",
    )

    if hasattr(pathlib.Path("."), "walk"):
        assert result["returncode"] != 0
        assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]
    else:
        assert result["returncode"] == 0
        assert "1 skipped" in result["stdout"]


def test_execute_generated_tests_blocks_directory_creation_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_dir").resolve()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def create_directory(target_path):\n"
        "    os.mkdir(target_path)\n",
        "tests_generated.py",
        "from code_under_test import create_directory\n\n"
        f"def test_directory_creation_is_blocked():\n"
        f"    create_directory({str(escaped_dir)!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked filesystem write outside sandbox root" in result["stdout"] or "sandbox policy blocked filesystem write outside sandbox root" in result["stderr"]
    assert not escaped_dir.exists()


def test_execute_generated_tests_blocks_symlink_creation_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_link = (tmp_path / "escaped_link").resolve()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def create_symlink(target_path, link_path):\n"
        "    os.symlink(target_path, link_path)\n",
        "tests_generated.py",
        "from code_under_test import create_symlink\n\n"
        f"def test_symlink_creation_is_blocked():\n"
        f"    create_symlink('inside.txt', {str(escaped_link)!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked filesystem write outside sandbox root" in result["stdout"] or "sandbox policy blocked filesystem write outside sandbox root" in result["stderr"]
    assert not escaped_link.exists()


def test_execute_generated_tests_blocks_metadata_mutation_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_file.txt").resolve()
    escaped_file.write_text("data", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def mutate_permissions(target_path):\n"
        "    os.chmod(target_path, 0o600)\n",
        "tests_generated.py",
        "from code_under_test import mutate_permissions\n\n"
        f"def test_metadata_mutation_is_blocked():\n"
        f"    mutate_permissions({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked filesystem write outside sandbox root" in result["stdout"] or "sandbox policy blocked filesystem write outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_pathlib_mutation_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_pathlib.txt").resolve()
    escaped_file.write_text("data", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import pathlib\n\n"
        "def remove_file(target_path):\n"
        "    pathlib.Path(target_path).unlink()\n",
        "tests_generated.py",
        "from code_under_test import remove_file\n\n"
        f"def test_pathlib_unlink_is_blocked():\n"
        f"    remove_file({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked filesystem write outside sandbox root" in result["stdout"] or "sandbox policy blocked filesystem write outside sandbox root" in result["stderr"]
    assert escaped_file.exists()


def test_execute_generated_tests_blocks_pathlib_write_text_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_write_text.txt").resolve()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import pathlib\n\n"
        "def write_file(target_path):\n"
        "    pathlib.Path(target_path).write_text('escaped', encoding='utf-8')\n",
        "tests_generated.py",
        "from code_under_test import write_file\n\n"
        f"def test_pathlib_write_text_is_blocked():\n"
        f"    write_file({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked filesystem write outside sandbox root" in result["stdout"] or "sandbox policy blocked filesystem write outside sandbox root" in result["stderr"]
    assert not escaped_file.exists()


def test_execute_generated_tests_blocks_pathlib_read_text_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_read_text.txt").resolve()
    escaped_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import pathlib\n\n"
        "def read_file(target_path):\n"
        "    return pathlib.Path(target_path).read_text(encoding='utf-8')\n",
        "tests_generated.py",
        "from code_under_test import read_file\n\n"
        f"def test_pathlib_read_text_is_blocked():\n"
        f"    read_file({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_pathlib_read_bytes_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_file = (tmp_path / "escaped_read_bytes.bin").resolve()
    escaped_file.write_bytes(b"secret")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import pathlib\n\n"
        "def read_file(target_path):\n"
        "    return pathlib.Path(target_path).read_bytes()\n",
        "tests_generated.py",
        "from code_under_test import read_file\n\n"
        f"def test_pathlib_read_bytes_is_blocked():\n"
        f"    read_file({str(escaped_file)!r})\n",
    )

    assert result["returncode"] != 0
    assert "RuntimeError" in result["stdout"] or "sandbox policy blocked file access outside sandbox root" in result["stderr"]


def test_execute_generated_tests_blocks_shutil_rmtree_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_dir = (tmp_path / "escaped_tree").resolve()
    escaped_dir.mkdir()
    (escaped_dir / "data.txt").write_text("data", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import shutil\n\n"
        "def remove_tree(target_path):\n"
        "    shutil.rmtree(target_path)\n",
        "tests_generated.py",
        "from code_under_test import remove_tree\n\n"
        f"def test_shutil_rmtree_is_blocked():\n"
        f"    remove_tree({str(escaped_dir)!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked filesystem write outside sandbox root" in result["stdout"] or "sandbox policy blocked filesystem write outside sandbox root" in result["stderr"]
    assert escaped_dir.exists()


def test_execute_generated_tests_blocks_shutil_move_outside_sandbox(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    escaped_source = (tmp_path / "escaped_source.txt").resolve()
    escaped_target = (tmp_path / "escaped_target.txt").resolve()
    escaped_source.write_text("data", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import shutil\n\n"
        "def move_file(source_path, target_path):\n"
        "    shutil.move(source_path, target_path)\n",
        "tests_generated.py",
        "from code_under_test import move_file\n\n"
        f"def test_shutil_move_is_blocked():\n"
        f"    move_file({str(escaped_source)!r}, {str(escaped_target)!r})\n",
    )

    assert result["returncode"] != 0
    assert "sandbox policy blocked filesystem write outside sandbox root" in result["stdout"] or "sandbox policy blocked filesystem write outside sandbox root" in result["stderr"]
    assert escaped_source.exists()
    assert not escaped_target.exists()


def test_execute_generated_tests_allows_subprocesses_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import subprocess\n\n"
        "def spawn_child():\n"
        "    completed = subprocess.run(['echo', 'hi'], capture_output=True, text=True, check=False)\n"
        "    return completed.stdout.strip()\n",
        "tests_generated.py",
        "from code_under_test import spawn_child\n\n"
        "def test_spawn_child_runs_when_sandbox_is_disabled():\n"
        "    assert spawn_child() == 'hi'\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_ctypes_loading_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import ctypes\nimport ctypes.util\n\n"
        "def load_native_library():\n"
        "    return (ctypes.CDLL(None)._name, ctypes.util.find_library('c'))\n",
        "tests_generated.py",
        "from code_under_test import load_native_library\n\n"
        "def test_ctypes_loading_runs_when_sandbox_is_disabled():\n"
        "    library_name, lookup = load_native_library()\n"
        "    assert library_name is None\n"
        "    assert lookup is None or isinstance(lookup, str)\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_mmap_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import mmap\n\n"
        "def allocate_memory_map():\n"
        "    mapping = mmap.mmap(-1, 64)\n"
        "    try:\n"
        "        mapping[0:4] = b'test'\n"
        "        return bytes(mapping[0:4])\n"
        "    finally:\n"
        "        mapping.close()\n",
        "tests_generated.py",
        "from code_under_test import allocate_memory_map\n\n"
        "def test_mmap_runs_when_sandbox_is_disabled():\n"
        "    assert allocate_memory_map() == b'test'\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_chdir_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_dir = tmp_path / "chdir_target"
    target_dir.mkdir()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def change_directory(target_path):\n"
        "    original = os.getcwd()\n"
        "    try:\n"
        "        os.chdir(target_path)\n"
        "        return os.getcwd()\n"
        "    finally:\n"
        "        os.chdir(original)\n",
        "tests_generated.py",
        "from code_under_test import change_directory\n\n"
        f"def test_chdir_runs_when_sandbox_is_disabled():\n"
        f"    assert change_directory({str(target_dir)!r}) == {str(target_dir)!r}\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_fd_duplication_and_wrapping_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import io\nimport os\n\n"
        "def duplicate_and_wrap_stdout():\n"
        "    duplicated_fd = os.dup(1)\n"
        "    try:\n"
        "        handle = io.open(duplicated_fd, 'w', closefd=True)\n"
        "        try:\n"
        "            return handle.writable()\n"
        "        finally:\n"
        "            handle.close()\n"
        "    finally:\n"
        "        try:\n"
        "            os.close(duplicated_fd)\n"
        "        except OSError:\n"
        "            pass\n",
        "tests_generated.py",
        "from code_under_test import duplicate_and_wrap_stdout\n\n"
        "def test_fd_duplication_and_wrapping_run_when_sandbox_is_disabled():\n"
        "    assert duplicate_and_wrap_stdout() is True\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_xattr_helpers_when_sandbox_disabled_when_supported(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "xattr_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    if not supports_user_xattrs(target_file):
        pytest.skip("user xattrs unsupported")

    attribute_name = "user.kycortex_allowed"
    attribute_value = b"secret"

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def mutate_and_read_xattrs(target_path, attribute_name, attribute_value):\n"
        "    os.setxattr(target_path, attribute_name, attribute_value)\n"
        "    try:\n"
        "        return (attribute_name in os.listxattr(target_path), os.getxattr(target_path, attribute_name))\n"
        "    finally:\n"
        "        os.removexattr(target_path, attribute_name)\n",
        "tests_generated.py",
        "from code_under_test import mutate_and_read_xattrs\n\n"
        f"def test_xattr_helpers_run_when_supported_and_sandbox_is_disabled():\n"
        f"    has_attribute, attribute_value = mutate_and_read_xattrs({str(target_file)!r}, {attribute_name!r}, {attribute_value!r})\n"
        "    assert has_attribute is True\n"
        f"    assert attribute_value == {attribute_value!r}\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_file_reads_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "read_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "def read_file(target_path):\n"
        "    with open(target_path, 'r', encoding='utf-8') as handle:\n"
        "        return handle.read()\n",
        "tests_generated.py",
        "from code_under_test import read_file\n\n"
        f"def test_file_read_runs_when_sandbox_is_disabled():\n"
        f"    assert read_file({str(target_file)!r}) == 'secret'\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_directory_enumeration_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_dir = tmp_path / "listing_target"
    target_dir.mkdir()
    (target_dir / "secret.txt").write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def list_directory(target_path):\n"
        "    return sorted(os.listdir(target_path))\n",
        "tests_generated.py",
        "from code_under_test import list_directory\n\n"
        f"def test_directory_enumeration_runs_when_sandbox_is_disabled():\n"
        f"    assert list_directory({str(target_dir)!r}) == ['secret.txt']\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_file_metadata_probes_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "meta_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def file_exists(target_path):\n"
        "    return Path(target_path).exists()\n",
        "tests_generated.py",
        "from code_under_test import file_exists\n\n"
        f"def test_file_metadata_probe_runs_when_sandbox_is_disabled():\n"
        f"    assert file_exists({str(target_file)!r}) is True\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_os_path_metadata_helpers_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "os_path_meta_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_metadata(target_path):\n"
        "    return (\n"
        "        os.path.getsize(target_path),\n"
        "        os.path.getmtime(target_path),\n"
        "        os.path.getctime(target_path),\n"
        "        os.path.getatime(target_path),\n"
        "    )\n",
        "tests_generated.py",
        "from code_under_test import read_metadata\n\n"
        f"def test_os_path_metadata_helpers_run_when_sandbox_is_disabled():\n"
        f"    size, mtime, ctime, atime = read_metadata({str(target_file)!r})\n"
        "    assert size == 6\n"
        "    assert mtime >= 0\n"
        "    assert ctime >= 0\n"
        "    assert atime >= 0\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_glob_enumeration_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_dir = tmp_path / "glob_target"
    target_dir.mkdir()
    (target_dir / "secret.txt").write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import glob\n\n"
        "def list_matches(pattern):\n"
        "    return sorted(glob.glob(pattern))\n",
        "tests_generated.py",
        "from code_under_test import list_matches\n\n"
        f"def test_glob_enumeration_runs_when_sandbox_is_disabled():\n"
        f"    matches = list_matches({str(target_dir / '*')!r})\n"
        f"    assert matches == [{str(target_dir / 'secret.txt')!r}]\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_os_fwalk_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_dir = tmp_path / "fwalk_target"
    target_dir.mkdir()
    (target_dir / "secret.txt").write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def walk_tree(target_path):\n"
        "    return [(root, sorted(files)) for root, _dirs, files, _fd in os.fwalk(target_path)]\n",
        "tests_generated.py",
        "from code_under_test import walk_tree\n\n"
        f"def test_os_fwalk_runs_when_sandbox_is_disabled():\n"
        f"    walked = walk_tree({str(target_dir)!r})\n"
        f"    assert walked == [({str(target_dir)!r}, ['secret.txt'])]\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_path_readlink_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "readlink_target.txt"
    target_file.write_text("secret", encoding="utf-8")
    target_link = tmp_path / "readlink_link.txt"
    target_link.symlink_to(target_file)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def resolve_link(target_path):\n"
        "    return str(Path(target_path).readlink())\n",
        "tests_generated.py",
        "from code_under_test import resolve_link\n\n"
        f"def test_path_readlink_runs_when_sandbox_is_disabled():\n"
        f"    assert resolve_link({str(target_link)!r}) == {str(target_file)!r}\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_os_readlink_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "os_readlink_target.txt"
    target_file.write_text("secret", encoding="utf-8")
    target_link = tmp_path / "os_readlink_link.txt"
    target_link.symlink_to(target_file)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def resolve_link(target_path):\n"
        "    return os.readlink(target_path)\n",
        "tests_generated.py",
        "from code_under_test import resolve_link\n\n"
        f"def test_os_readlink_runs_when_sandbox_is_disabled():\n"
        f"    assert resolve_link({str(target_link)!r}) == {str(target_file)!r}\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_samefile_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "samefile_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def is_same_file(left_path, right_path):\n"
        "    return Path(left_path).samefile(right_path)\n",
        "tests_generated.py",
        "from code_under_test import is_same_file\n\n"
        f"def test_samefile_runs_when_sandbox_is_disabled():\n"
        f"    assert is_same_file({str(target_file)!r}, {str(target_file)!r}) is True\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_os_path_realpath_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "os_path_realpath_target.txt"
    target_file.write_text("secret", encoding="utf-8")
    target_link = tmp_path / "os_path_realpath_link.txt"
    target_link.symlink_to(target_file)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def resolve_path(target_path):\n"
        "    return os.path.realpath(target_path)\n",
        "tests_generated.py",
        "from code_under_test import resolve_path\n\n"
        f"def test_os_path_realpath_runs_when_sandbox_is_disabled():\n"
        f"    assert resolve_path({str(target_link)!r}) == {str(target_file)!r}\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_os_path_isabs_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "os_path_isabs_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def is_absolute_path(target_path):\n"
        "    return os.path.isabs(target_path)\n",
        "tests_generated.py",
        "from code_under_test import is_absolute_path\n\n"
        f"def test_os_path_isabs_runs_when_sandbox_is_disabled():\n"
        f"    assert is_absolute_path({str(target_file)!r}) is True\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_os_path_samefile_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "os_path_samefile_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def is_same_file(left_path, right_path):\n"
        "    return os.path.samefile(left_path, right_path)\n",
        "tests_generated.py",
        "from code_under_test import is_same_file\n\n"
        f"def test_os_path_samefile_runs_when_sandbox_is_disabled():\n"
        f"    assert is_same_file({str(target_file)!r}, {str(target_file)!r}) is True\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_path_owner_group_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "path_owner_group_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def read_identity(target_path):\n"
        "    target = Path(target_path)\n"
        "    return (target.owner(), target.group())\n",
        "tests_generated.py",
        "from code_under_test import read_identity\n\n"
        f"def test_path_owner_group_run_when_sandbox_is_disabled():\n"
        f"    owner, group = read_identity({str(target_file)!r})\n"
        "    assert owner\n"
        "    assert group\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_mount_helpers_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_dir = tmp_path / "mount_helper_target"
    target_dir.mkdir()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n"
        "from pathlib import Path\n\n"
        "def read_mount_flags(target_path):\n"
        "    target = Path(target_path)\n"
        "    return (os.path.ismount(target_path), target.is_mount())\n",
        "tests_generated.py",
        "from code_under_test import read_mount_flags\n\n"
        f"def test_mount_helpers_run_when_sandbox_is_disabled():\n"
        f"    os_mount, path_mount = read_mount_flags({str(target_dir)!r})\n"
        "    assert os_mount is False\n"
        "    assert path_mount is False\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_path_type_helpers_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "path_type_helpers_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def read_types(target_path):\n"
        "    target = Path(target_path)\n"
        "    return (\n"
        "        target.is_block_device(),\n"
        "        target.is_char_device(),\n"
        "        target.is_fifo(),\n"
        "        target.is_socket(),\n"
        "    )\n",
        "tests_generated.py",
        "from code_under_test import read_types\n\n"
        f"def test_path_type_helpers_run_when_sandbox_is_disabled():\n"
        f"    block_device, char_device, fifo, socket = read_types({str(target_file)!r})\n"
        "    assert block_device is False\n"
        "    assert char_device is False\n"
        "    assert fifo is False\n"
        "    assert socket is False\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_junction_helpers_when_sandbox_disabled_when_supported(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_dir = tmp_path / "junction_helper_target"
    target_dir.mkdir()

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n"
        "from pathlib import Path\n\n"
        "def read_junction_flags(target_path):\n"
        "    target = Path(target_path)\n"
        "    if not hasattr(os.path, 'isjunction') or not hasattr(target, 'is_junction'):\n"
        "        return 'unsupported'\n"
        "    return (os.path.isjunction(target_path), target.is_junction())\n",
        "tests_generated.py",
        "import os\nimport pytest\n"
        "from pathlib import Path\n"
        "from code_under_test import read_junction_flags\n\n"
        "def test_junction_helpers_run_when_supported_and_sandbox_is_disabled():\n"
        "    if not hasattr(os.path, 'isjunction') or not hasattr(Path('.'), 'is_junction'):\n"
        "        pytest.skip('junction helpers unavailable')\n"
        f"    os_junction, path_junction = read_junction_flags({str(target_dir)!r})\n"
        "    assert os_junction is False\n"
        "    assert path_junction is False\n",
    )

    if hasattr(os.path, "isjunction") and hasattr(pathlib.Path("."), "is_junction"):
        assert result["returncode"] == 0
        assert result["sandbox"]["enabled"] is False
    else:
        assert result["returncode"] == 0
        assert "1 skipped" in result["stdout"]


def test_execute_generated_tests_allows_os_stat_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "stat_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_mode(target_path):\n"
        "    return os.stat(target_path).st_mode\n",
        "tests_generated.py",
        "from code_under_test import read_mode\n\n"
        f"def test_os_stat_runs_when_sandbox_is_disabled():\n"
        f"    assert read_mode({str(target_file)!r}) > 0\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_os_lstat_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "lstat_target.txt"
    target_file.write_text("secret", encoding="utf-8")
    target_link = tmp_path / "lstat_link.txt"
    target_link.symlink_to(target_file)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def read_link_mode(target_path):\n"
        "    return os.lstat(target_path).st_mode\n",
        "tests_generated.py",
        "from code_under_test import read_link_mode\n\n"
        f"def test_os_lstat_runs_when_sandbox_is_disabled():\n"
        f"    assert read_link_mode({str(target_link)!r}) > 0\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_path_stat_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "path_stat_target.txt"
    target_file.write_text("secret", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def read_mode(target_path):\n"
        "    return Path(target_path).stat().st_mode\n",
        "tests_generated.py",
        "from code_under_test import read_mode\n\n"
        f"def test_path_stat_runs_when_sandbox_is_disabled():\n"
        f"    assert read_mode({str(target_file)!r}) > 0\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_path_lstat_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "path_lstat_target.txt"
    target_file.write_text("secret", encoding="utf-8")
    target_link = tmp_path / "path_lstat_link.txt"
    target_link.symlink_to(target_file)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def read_link_mode(target_path):\n"
        "    return Path(target_path).lstat().st_mode\n",
        "tests_generated.py",
        "from code_under_test import read_link_mode\n\n"
        f"def test_path_lstat_runs_when_sandbox_is_disabled():\n"
        f"    assert read_link_mode({str(target_link)!r}) > 0\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_path_resolve_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "resolve_target.txt"
    target_file.write_text("secret", encoding="utf-8")
    target_link = tmp_path / "resolve_link.txt"
    target_link.symlink_to(target_file)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "from pathlib import Path\n\n"
        "def resolve_path(target_path):\n"
        "    return str(Path(target_path).resolve())\n",
        "tests_generated.py",
        "from code_under_test import resolve_path\n\n"
        f"def test_path_resolve_runs_when_sandbox_is_disabled():\n"
        f"    assert resolve_path({str(target_link)!r}) == {str(target_file)!r}\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False




def test_execute_generated_tests_allows_pathlib_mutation_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "pathlib_target.txt"
    target_file.write_text("data", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import pathlib\n\n"
        "def remove_file(target_path):\n"
        "    pathlib.Path(target_path).unlink()\n"
        "    return not pathlib.Path(target_path).exists()\n",
        "tests_generated.py",
        "from code_under_test import remove_file\n\n"
        f"def test_pathlib_unlink_runs_when_sandbox_is_disabled():\n"
        f"    assert remove_file({str(target_file)!r}) is True\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False
    assert not target_file.exists()


def test_execute_generated_tests_allows_pathlib_write_text_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "pathlib_write_text_target.txt"

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import pathlib\n\n"
        "def write_file(target_path):\n"
        "    pathlib.Path(target_path).write_text('ok', encoding='utf-8')\n"
        "    return pathlib.Path(target_path).read_text(encoding='utf-8')\n",
        "tests_generated.py",
        "from code_under_test import write_file\n\n"
        f"def test_pathlib_write_text_runs_when_sandbox_is_disabled():\n"
        f"    assert write_file({str(target_file)!r}) == 'ok'\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False
    assert target_file.read_text(encoding="utf-8") == "ok"


def test_execute_generated_tests_allows_pathlib_read_text_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "pathlib_read_text_target.txt"
    target_file.write_text("ok", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import pathlib\n\n"
        "def read_file(target_path):\n"
        "    return pathlib.Path(target_path).read_text(encoding='utf-8')\n",
        "tests_generated.py",
        "from code_under_test import read_file\n\n"
        f"def test_pathlib_read_text_runs_when_sandbox_is_disabled():\n"
        f"    assert read_file({str(target_file)!r}) == 'ok'\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_pathlib_read_bytes_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "pathlib_read_bytes_target.bin"
    target_file.write_bytes(b"ok")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import pathlib\n\n"
        "def read_file(target_path):\n"
        "    return pathlib.Path(target_path).read_bytes()\n",
        "tests_generated.py",
        "from code_under_test import read_file\n\n"
        f"def test_pathlib_read_bytes_runs_when_sandbox_is_disabled():\n"
        f"    assert read_file({str(target_file)!r}) == b'ok'\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_shutil_move_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    source_file = tmp_path / "shutil_source.txt"
    target_file = tmp_path / "shutil_target.txt"
    source_file.write_text("data", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import pathlib\nimport shutil\n\n"
        "def move_file(source_path, target_path):\n"
        "    shutil.move(source_path, target_path)\n"
        "    return pathlib.Path(target_path).exists() and not pathlib.Path(source_path).exists()\n",
        "tests_generated.py",
        "from code_under_test import move_file\n\n"
        f"def test_shutil_move_runs_when_sandbox_is_disabled():\n"
        f"    assert move_file({str(source_file)!r}, {str(target_file)!r}) is True\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False
    assert not source_file.exists()
    assert target_file.exists()


def test_execute_generated_tests_allows_directory_creation_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    created_dir = tmp_path / "created_dir"

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def create_directory(target_path):\n"
        "    os.mkdir(target_path)\n"
        "    return os.path.isdir(target_path)\n",
        "tests_generated.py",
        "from code_under_test import create_directory\n\n"
        f"def test_directory_creation_runs_when_sandbox_is_disabled():\n"
        f"    assert create_directory({str(created_dir)!r}) is True\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False
    assert created_dir.exists()


def test_execute_generated_tests_allows_symlink_creation_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    created_link = tmp_path / "created_link"

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\n\n"
        "def create_symlink(target_path, link_path):\n"
        "    os.symlink(target_path, link_path)\n"
        "    return os.path.islink(link_path)\n",
        "tests_generated.py",
        "from code_under_test import create_symlink\n\n"
        f"def test_symlink_creation_runs_when_sandbox_is_disabled():\n"
        f"    assert create_symlink('inside.txt', {str(created_link)!r}) is True\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False
    assert created_link.is_symlink()


def test_execute_generated_tests_allows_metadata_mutation_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)
    target_file = tmp_path / "chmod_target.txt"
    target_file.write_text("data", encoding="utf-8")

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\nimport stat\n\n"
        "def mutate_permissions(target_path):\n"
        "    os.chmod(target_path, 0o600)\n"
        "    return stat.S_IMODE(os.stat(target_path).st_mode)\n",
        "tests_generated.py",
        "from code_under_test import mutate_permissions\n\n"
        f"def test_metadata_mutation_runs_when_sandbox_is_disabled():\n"
        f"    assert mutate_permissions({str(target_file)!r}) == 0o600\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_allows_os_spawn_calls_when_sandbox_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        execution_sandbox_enabled=False,
    )
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\nimport sys\n\n"
        "def spawn_child():\n"
        "    return os.spawnv(os.P_WAIT, sys.executable, [sys.executable, '-c', 'raise SystemExit(0)'])\n",
        "tests_generated.py",
        "from code_under_test import spawn_child\n\n"
        "def test_spawnv_runs_when_sandbox_is_disabled():\n"
        "    assert spawn_child() == 0\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is False


def test_execute_generated_tests_uses_sandbox_home_and_xdg_dirs(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    result = orchestrator._execute_generated_tests(
        "code_under_test.py",
        "import os\nimport tempfile\nfrom pathlib import Path\n\n"
        "def runtime_paths():\n"
        "    return {\n"
        "        'home': str(Path.home()),\n"
        "        'sandbox_root': os.environ.get('KYCORTEX_SANDBOX_ROOT', ''),\n"
        "        'sandbox_root_mode': Path(os.environ.get('KYCORTEX_SANDBOX_ROOT', '')).stat().st_mode & 0o777,\n"
        "        'path': os.environ.get('PATH', ''),\n"
        "        'user': os.environ.get('USER', ''),\n"
        "        'logname': os.environ.get('LOGNAME', ''),\n"
        "        'username': os.environ.get('USERNAME', ''),\n"
        "        'lang': os.environ.get('LANG', ''),\n"
        "        'lc_all': os.environ.get('LC_ALL', ''),\n"
        "        'language': os.environ.get('LANGUAGE', ''),\n"
        "        'pythonhashseed': os.environ.get('PYTHONHASHSEED', ''),\n"
        "        'term': os.environ.get('TERM', ''),\n"
        "        'tz': os.environ.get('TZ', ''),\n"
        "        'tmpdir': os.environ.get('TMPDIR', ''),\n"
        "        'tmp': os.environ.get('TMP', ''),\n"
        "        'temp': os.environ.get('TEMP', ''),\n"
        "        'tempdir_env': os.environ.get('TEMPDIR', ''),\n"
        "        'tempfile_dir': tempfile.gettempdir(),\n"
        "        'config': os.environ.get('XDG_CONFIG_HOME', ''),\n"
        "        'cache': os.environ.get('XDG_CACHE_HOME', ''),\n"
        "        'data': os.environ.get('XDG_DATA_HOME', ''),\n"
        "        'local': str(Path(os.environ.get('XDG_DATA_HOME', '')).parent),\n"
        "        'config_exists': Path(os.environ.get('XDG_CONFIG_HOME', '')).is_dir(),\n"
        "        'cache_exists': Path(os.environ.get('XDG_CACHE_HOME', '')).is_dir(),\n"
        "        'data_exists': Path(os.environ.get('XDG_DATA_HOME', '')).is_dir(),\n"
        "        'local_exists': Path(os.environ.get('XDG_DATA_HOME', '')).parent.is_dir(),\n"
        "        'config_mode': Path(os.environ.get('XDG_CONFIG_HOME', '')).stat().st_mode & 0o777,\n"
        "        'cache_mode': Path(os.environ.get('XDG_CACHE_HOME', '')).stat().st_mode & 0o777,\n"
        "        'local_mode': Path(os.environ.get('XDG_DATA_HOME', '')).parent.stat().st_mode & 0o777,\n"
        "        'data_mode': Path(os.environ.get('XDG_DATA_HOME', '')).stat().st_mode & 0o777,\n"
        "    }\n",
        "tests_generated.py",
        "from pathlib import Path\n"
        "from code_under_test import runtime_paths\n\n"
        "def test_runtime_paths_are_sandboxed(tmp_path):\n"
        "    paths = runtime_paths()\n"
        "    assert paths['home'] == paths['sandbox_root']\n"
        "    assert paths['sandbox_root_mode'] == 0o700\n"
        "    assert paths['path'] == paths['sandbox_root']\n"
        "    assert paths['user'] == 'sandbox_user'\n"
        "    assert paths['logname'] == 'sandbox_user'\n"
        "    assert paths['username'] == 'sandbox_user'\n"
        "    assert paths['lang'] == 'C.UTF-8'\n"
        "    assert paths['lc_all'] == 'C.UTF-8'\n"
        "    assert paths['language'] == 'en'\n"
        "    assert paths['pythonhashseed'] == '0'\n"
        "    assert paths['term'] == 'dumb'\n"
        "    assert paths['tz'] == 'UTC'\n"
        "    assert paths['tmpdir'] == paths['sandbox_root']\n"
        "    assert paths['tmp'] == paths['sandbox_root']\n"
        "    assert paths['temp'] == paths['sandbox_root']\n"
        "    assert paths['tempdir_env'] == paths['sandbox_root']\n"
        "    assert paths['tempfile_dir'] == paths['sandbox_root']\n"
        "    assert paths['config'] == str(Path(paths['home']) / '.config')\n"
        "    assert paths['cache'] == str(Path(paths['home']) / '.cache')\n"
        "    assert paths['data'] == str(Path(paths['home']) / '.local' / 'share')\n"
        "    assert paths['local'] == str(Path(paths['home']) / '.local')\n"
        "    assert paths['config_exists'] is True\n"
        "    assert paths['cache_exists'] is True\n"
        "    assert paths['data_exists'] is True\n"
        "    assert paths['local_exists'] is True\n"
        "    assert paths['config_mode'] == 0o700\n"
        "    assert paths['cache_mode'] == 0o700\n"
        "    assert paths['local_mode'] == 0o700\n"
        "    assert paths['data_mode'] == 0o700\n",
    )

    assert result["returncode"] == 0
    assert result["sandbox"]["enabled"] is True


def test_build_generated_test_env_omits_sandbox_hooks_when_disabled(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), execution_sandbox_enabled=False)
    orchestrator = Orchestrator(config)

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "KYCORTEX_SANDBOX_ALLOW_NETWORK" not in env
    assert "KYCORTEX_SANDBOX_ALLOW_SUBPROCESSES" not in env
    assert "KYCORTEX_SANDBOX_ROOT" not in env
    assert "XDG_CONFIG_HOME" not in env
    assert "XDG_CACHE_HOME" not in env
    assert "XDG_DATA_HOME" not in env
    assert "PYTHONPATH" not in env
    assert not (tmp_path / "sitecustomize.py").exists()


def test_build_generated_test_env_strips_inherited_python_startup_env(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setenv("PYTHONASYNCIODEBUG", "1")
    monkeypatch.setenv("PYTHONPATH", "/tmp/injected")
    monkeypatch.setenv("PYTHONHOME", "/tmp/home")
    monkeypatch.setenv("PYTHONSTARTUP", "/tmp/startup.py")
    monkeypatch.setenv("PYTHONBREAKPOINT", "evil.module:breakpoint")
    monkeypatch.setenv("PYTHONCASEOK", "1")
    monkeypatch.setenv("PYTHONDEBUG", "1")
    monkeypatch.setenv("PYTHONDEVMODE", "1")
    monkeypatch.setenv("PYTHONEXECUTABLE", "/tmp/python")
    monkeypatch.setenv("PYTHONFAULTHANDLER", "1")
    monkeypatch.setenv("PYTHONINTMAXSTRDIGITS", "1000")
    monkeypatch.setenv("PYTHONIOENCODING", "latin-1")
    monkeypatch.setenv("PYTHONINSPECT", "1")
    monkeypatch.setenv("PYTHONNODEBUGRANGES", "1")
    monkeypatch.setenv("PYTHONOPTIMIZE", "2")
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", "/tmp/pycache")
    monkeypatch.setenv("PYTHONPLATLIBDIR", "lib64")
    monkeypatch.setenv("PYTHONPROFILEIMPORTTIME", "1")
    monkeypatch.setenv("PYTHONSAFEPATH", "1")
    monkeypatch.setenv("PYTHONTRACEMALLOC", "25")
    monkeypatch.setenv("PYTHONUSERBASE", "/tmp/userbase")
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONVERBOSE", "1")
    monkeypatch.setenv("PYTHONWARNDEFAULTENCODING", "1")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "PYTHONASYNCIODEBUG" not in env
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert "PYTHONSTARTUP" not in env
    assert "PYTHONBREAKPOINT" not in env
    assert "PYTHONCASEOK" not in env
    assert "PYTHONDEBUG" not in env
    assert "PYTHONDEVMODE" not in env
    assert "PYTHONEXECUTABLE" not in env
    assert "PYTHONFAULTHANDLER" not in env
    assert "PYTHONINTMAXSTRDIGITS" not in env
    assert "PYTHONIOENCODING" not in env
    assert "PYTHONINSPECT" not in env
    assert "PYTHONNODEBUGRANGES" not in env
    assert "PYTHONOPTIMIZE" not in env
    assert "PYTHONPYCACHEPREFIX" not in env
    assert "PYTHONPLATLIBDIR" not in env
    assert "PYTHONPROFILEIMPORTTIME" not in env
    assert "PYTHONSAFEPATH" not in env
    assert "PYTHONTRACEMALLOC" not in env
    assert "PYTHONUSERBASE" not in env
    assert "PYTHONUTF8" not in env
    assert "PYTHONVERBOSE" not in env
    assert "PYTHONWARNDEFAULTENCODING" not in env


def test_build_generated_test_env_strips_inherited_pytest_env(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setenv("PYTEST_ADDOPTS", "-p external_plugin --maxfail=1")
    monkeypatch.setenv("PYTEST_PLUGINS", "external_plugin")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_demo.py::test_case (call)")
    monkeypatch.setenv("PYTEST_DEBUG", "1")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "PYTEST_ADDOPTS" not in env
    assert "PYTEST_PLUGINS" not in env
    assert "PYTEST_CURRENT_TEST" not in env
    assert "PYTEST_DEBUG" not in env


def test_build_generated_test_env_strips_terminal_and_color_markers(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("PY_COLORS", "1")
    monkeypatch.setenv("CLICOLOR", "1")
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    monkeypatch.setenv("COLUMNS", "240")
    monkeypatch.setenv("LINES", "70")
    monkeypatch.setenv("TERM", "xterm-256color")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "COLORTERM" not in env
    assert "FORCE_COLOR" not in env
    assert "NO_COLOR" not in env
    assert "PY_COLORS" not in env
    assert "CLICOLOR" not in env
    assert "CLICOLOR_FORCE" not in env
    assert "COLUMNS" not in env
    assert "LINES" not in env
    assert env["TERM"] == "dumb"


def test_sandbox_preexec_fn_sets_restrictive_umask(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    policy = config.execution_sandbox_policy()
    recorded_calls: list[tuple[object, tuple[int, int]]] = []
    recorded_umasks: list[int] = []

    monkeypatch.setattr(orchestrator_module.os, "name", "posix")
    monkeypatch.setattr(
        orchestrator_module.resource,
        "setrlimit",
        lambda limit, values: recorded_calls.append((limit, values)),
    )
    monkeypatch.setattr(orchestrator_module.os, "umask", lambda value: recorded_umasks.append(value) or 0)

    preexec = orchestrator._sandbox_preexec_fn(policy)

    assert callable(preexec)
    preexec()

    assert recorded_umasks == [0o077]
    assert len(recorded_calls) == 4


def test_build_generated_test_env_enforces_mandatory_sandbox_bindings(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    policy = config.execution_sandbox_policy()
    policy.sanitized_env = {
        "PATH": "/host/bin",
        "HOME": "/host/home",
        "TMPDIR": "/host/tmp",
        "USER": "host_user",
        "LOGNAME": "host_logname",
        "USERNAME": "host_username",
        "LANG": "pt_BR.UTF-8",
        "LC_ALL": "pt_BR.UTF-8",
        "LANGUAGE": "pt_BR",
        "PYTHONHASHSEED": "123",
        "TZ": "America/Sao_Paulo",
        "PYTHONDONTWRITEBYTECODE": "0",
        "PYTHONNOUSERSITE": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "0",
    }

    env = orchestrator._build_generated_test_env(tmp_path, policy)

    assert env["PATH"] == str(tmp_path)
    assert env["HOME"] == str(tmp_path)
    assert env["TMPDIR"] == str(tmp_path)
    assert env["USER"] == "sandbox_user"
    assert env["LOGNAME"] == "sandbox_user"
    assert env["USERNAME"] == "sandbox_user"
    assert env["LANG"] == "C.UTF-8"
    assert env["LC_ALL"] == "C.UTF-8"
    assert env["LANGUAGE"] == "en"
    assert env["PYTHONHASHSEED"] == "0"
    assert env["TZ"] == "UTC"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_build_generated_test_env_strips_package_manager_markers(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setenv("VIRTUAL_ENV", "/host/venv")
    monkeypatch.setenv("CONDA_PREFIX", "/host/conda")
    monkeypatch.setenv("PIP_INDEX_URL", "https://host.example/simple")
    monkeypatch.setenv("UV_INDEX_URL", "https://host.example/uv")
    monkeypatch.setenv("POETRY_VIRTUALENVS_PATH", "/host/poetry")
    monkeypatch.setenv("PIXI_PROJECT_ROOT", "/host/pixi")
    monkeypatch.setenv("PYENV_VERSION", "3.12.3")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "VIRTUAL_ENV" not in env
    assert "CONDA_PREFIX" not in env
    assert "PIP_INDEX_URL" not in env
    assert "UV_INDEX_URL" not in env
    assert "POETRY_VIRTUALENVS_PATH" not in env
    assert "PIXI_PROJECT_ROOT" not in env
    assert "PYENV_VERSION" not in env


def test_build_generated_test_env_strips_remaining_runtime_marker_prefixes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    policy = config.execution_sandbox_policy()
    policy.sanitized_env = {
        "PATH": "/host/bin",
        "VIRTUAL_ENV": "/host/venv",
        "HTTPS_PROXY": "https://proxy.example",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
        "LD_LIBRARY_PATH": "/host/lib",
    }

    env = orchestrator._build_generated_test_env(tmp_path, policy)

    assert "VIRTUAL_ENV" not in env
    assert "HTTPS_PROXY" not in env
    assert "DOCKER_HOST" not in env
    assert "LD_LIBRARY_PATH" not in env


def test_build_generated_test_env_strips_proxy_and_tls_markers(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setenv("HTTP_PROXY", "http://corp-proxy:8080")
    monkeypatch.setenv("HTTPS_PROXY", "https://corp-proxy:8443")
    monkeypatch.setenv("ALL_PROXY", "http://fallback:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/host/certs/requests.pem")
    monkeypatch.setenv("CURL_CA_BUNDLE", "/host/certs/curl.pem")
    monkeypatch.setenv("SSL_CERT_FILE", "/host/certs/ssl.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/host/certs")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "HTTP_PROXY" not in env
    assert "HTTPS_PROXY" not in env
    assert "ALL_PROXY" not in env
    assert "NO_PROXY" not in env
    assert "REQUESTS_CA_BUNDLE" not in env
    assert "CURL_CA_BUNDLE" not in env
    assert "SSL_CERT_FILE" not in env
    assert "SSL_CERT_DIR" not in env


def test_build_generated_test_env_strips_credential_and_provider_markers(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "azure-secret")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/host/gcp.json")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("HF_TOKEN", "hf-token")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "AWS_ACCESS_KEY_ID" not in env
    assert "AZURE_CLIENT_SECRET" not in env
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env
    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "OLLAMA_HOST" not in env
    assert "HF_TOKEN" not in env


def test_build_generated_test_env_strips_generic_secret_like_markers_from_sanitized_env(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    policy = config.execution_sandbox_policy()
    policy.sanitized_env = {
        "CUSTOM_API_TOKEN": "secret-token",
        "DB_PASSWORD": "password123",
        "PRIVATE_KEY_PATH": "/host/id_rsa",
        "SERVICE_CLIENT_SECRET": "client-secret",
        "TOKENIZERS_PARALLELISM": "false",
        "APP_API_VERSION": "v1",
    }

    env = orchestrator._build_generated_test_env(tmp_path, policy)

    assert "CUSTOM_API_TOKEN" not in env
    assert "DB_PASSWORD" not in env
    assert "PRIVATE_KEY_PATH" not in env
    assert "SERVICE_CLIENT_SECRET" not in env
    assert env["TOKENIZERS_PARALLELISM"] == "false"
    assert env["APP_API_VERSION"] == "v1"


def test_build_generated_test_env_strips_git_ssh_and_gnupg_markers(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setenv("GIT_AUTHOR_NAME", "Host User")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/host/.gitconfig")
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /host/key")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/host/ssh-agent.sock")
    monkeypatch.setenv("GNUPGHOME", "/host/.gnupg")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "GIT_AUTHOR_NAME" not in env
    assert "GIT_CONFIG_GLOBAL" not in env
    assert "GIT_SSH_COMMAND" not in env
    assert "SSH_AUTH_SOCK" not in env
    assert "GNUPGHOME" not in env


def test_build_generated_test_env_strips_container_and_ci_markers(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setenv("KUBECONFIG", "/host/.kube/config")
    monkeypatch.setenv("KUBE_NAMESPACE", "production")
    monkeypatch.setenv("PODMAN_SOCKET_PATH", "/host/podman.sock")
    monkeypatch.setenv("CONTAINER_RUNTIME", "docker")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTOR", "host-user")
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("BUILDKITE_BUILD_ID", "12345")
    monkeypatch.setenv("JENKINS_HOME", "/host/jenkins")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "DOCKER_HOST" not in env
    assert "KUBECONFIG" not in env
    assert "KUBE_NAMESPACE" not in env
    assert "PODMAN_SOCKET_PATH" not in env
    assert "CONTAINER_RUNTIME" not in env
    assert "CI" not in env
    assert "GITHUB_ACTOR" not in env
    assert "GITLAB_CI" not in env
    assert "BUILDKITE_BUILD_ID" not in env
    assert "JENKINS_HOME" not in env


def test_build_generated_test_env_strips_loader_and_native_runtime_markers(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    monkeypatch.setenv("LD_PRELOAD", "/host/libinject.so")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/host/lib")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/host/libinject.dylib")
    monkeypatch.setenv("PYTHONMALLOC", "malloc_debug")
    monkeypatch.setenv("PYTHONMALLOCSTATS", "1")
    monkeypatch.setenv("PYTHONWARNINGS", "error")

    env = orchestrator._build_generated_test_env(tmp_path, config.execution_sandbox_policy())

    assert "LD_PRELOAD" not in env
    assert "LD_LIBRARY_PATH" not in env
    assert "DYLD_INSERT_LIBRARIES" not in env
    assert "PYTHONMALLOC" not in env
    assert "PYTHONMALLOCSTATS" not in env
    assert "PYTHONWARNINGS" not in env


def test_execute_generated_tests_uses_isolated_runner_when_sandbox_enabled(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    orchestrator = Orchestrator(config, registry=AgentRegistry({}))
    captured: dict[str, Any] = {}

    def fake_run(command, **kwargs):
        runner_path = pathlib.Path(command[-1])
        sandbox_root = runner_path.parent
        captured["command"] = command
        captured["env"] = kwargs["env"]
        captured["runner"] = runner_path.read_text(encoding="utf-8")
        captured["runner_mode"] = runner_path.stat().st_mode & 0o777
        captured["module_mode"] = (sandbox_root / "code_implementation.py").stat().st_mode & 0o777
        captured["test_mode"] = (sandbox_root / "tests_tests.py").stat().st_mode & 0o777
        captured["config_mode"] = (sandbox_root / "pytest.ini").stat().st_mode & 0o777
        captured["sitecustomize_mode"] = (sandbox_root / "sitecustomize.py").stat().st_mode & 0o777
        return CompletedProcessStub()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = orchestrator._execute_generated_tests(
        "code_implementation.py",
        "def run():\n    return 1\n",
        "tests_tests.py",
        "from code_implementation import run\n\ndef test_run():\n    assert run() == 1\n",
    )

    assert result["ran"] is True
    assert result["returncode"] == 0
    assert captured["command"][:2] == [sys.executable, "-I"]
    assert pathlib.Path(captured["command"][-1]).name == "_kycortex_run_pytest.py"
    assert captured["runner_mode"] == 0o600
    assert captured["module_mode"] == 0o600
    assert captured["test_mode"] == 0o600
    assert captured["config_mode"] == 0o600
    assert captured["sitecustomize_mode"] == 0o600
    assert "spec_from_file_location" in captured["runner"]
    assert "_kycortex_sandbox_sitecustomize" in captured["runner"]
    assert "pytest.main" in captured["runner"]
    assert "PYTHONPATH" not in captured["env"]


def test_sanitize_generated_filename_strips_path_traversal():
    orchestrator = Orchestrator(KYCortexConfig(output_dir="./output_test"))

    assert orchestrator._sanitize_generated_filename("../../tests_generated.py", "generated_tests.py") == "tests_generated.py"
    assert orchestrator._sanitize_generated_filename("", "generated_tests.py") == "generated_tests.py"


def test_run_task_exposes_generated_test_validation_to_downstream_agents(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "from enum import Enum\n"
                "class Color(Enum):\n"
                "    RED = 1\n\n"
                "class Thing:\n"
                "    name: str\n\n"
                "def run(value):\n"
                "    return value\n"
            ),
            output_payload={
                "summary": "from enum import Enum",
                "raw_content": (
                    "from enum import Enum\n"
                    "class Color(Enum):\n"
                    "    RED = 1\n\n"
                    "class Thing:\n"
                    "    name: str\n\n"
                    "def run(value):\n"
                    "    return value\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "from enum import Enum\n"
                            "class Color(Enum):\n"
                            "    RED = 1\n\n"
                            "class Thing:\n"
                            "    name: str\n\n"
                            "def run(value):\n"
                            "    return value\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            status=TaskStatus.DONE.value,
            output=(
                "from code_implementation import Color, Thing\n\n"
                "def test_run():\n"
                "    assert run(1) == 1\n\n"
                "def test_enum_member():\n"
                "    assert Color.Red.name == 'RED'\n\n"
                "def test_ctor():\n"
                "    Thing()\n"
            ),
            output_payload={
                "summary": "from code_implementation import Color, Thing",
                "raw_content": (
                    "from code_implementation import Color, Thing\n\n"
                    "def test_run():\n"
                    "    assert run(1) == 1\n\n"
                    "def test_enum_member():\n"
                    "    assert Color.Red.name == 'RED'\n\n"
                    "def test_ctor():\n"
                    "    Thing()\n"
                ),
                "artifacts": [
                    {
                        "name": "tests_tests",
                        "artifact_type": ArtifactType.TEST.value,
                        "path": "artifacts/tests_tests.py",
                        "content": (
                            "from code_implementation import Color, Thing\n\n"
                            "def test_run():\n"
                            "    assert run(1) == 1\n\n"
                            "def test_enum_member():\n"
                            "    assert Color.Red.name == 'RED'\n\n"
                            "def test_ctor():\n"
                            "    Thing()\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the implementation",
            assigned_to="code_reviewer",
            dependencies=["tests"],
        )
    )

    agent = RecordingAgent("REVIEW")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"code_reviewer": agent}))

    orchestrator.run_task(project.tasks[2], project)

    assert "Generated test validation:" in agent.last_context["test_validation_summary"]
    assert "run (line 4)" in agent.last_context["test_validation_summary"]
    assert "Color.Red (line 7)" in agent.last_context["test_validation_summary"]
    assert "Thing expects 1 args but test uses 0 at line 10" in agent.last_context["test_validation_summary"]


def test_run_task_exposes_dependency_manifest_validation_to_downstream_agents(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "import json\n"
                "import numpy as np\n\n"
                "def run():\n"
                "    return np.array([1]).tolist()\n"
            ),
            output_payload={
                "summary": "import json",
                "raw_content": (
                    "import json\n"
                    "import numpy as np\n\n"
                    "def run():\n"
                    "    return np.array([1]).tolist()\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "import json\n"
                            "import numpy as np\n\n"
                            "def run():\n"
                            "    return np.array([1]).tolist()\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="deps",
            title="Dependencies",
            description="Infer dependencies",
            assigned_to="dependency_manager",
            status=TaskStatus.DONE.value,
            output="# No external runtime dependencies",
            output_payload={
                "summary": "# No external runtime dependencies",
                "raw_content": "# No external runtime dependencies",
                "artifacts": [
                    {
                        "name": "deps_requirements",
                        "artifact_type": ArtifactType.CONFIG.value,
                        "path": "artifacts/requirements.txt",
                        "content": "# No external runtime dependencies",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the implementation",
            assigned_to="code_reviewer",
            dependencies=["deps"],
        )
    )

    agent = RecordingAgent("REVIEW")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"code_reviewer": agent}))

    orchestrator.run_task(project.tasks[2], project)

    assert agent.last_context["dependency_manifest"] == "# No external runtime dependencies"
    assert agent.last_context["dependency_manifest_path"] == "artifacts/requirements.txt"
    assert agent.last_context["dependency_analysis"]["required_imports"] == ["numpy"]
    assert agent.last_context["dependency_analysis"]["missing_manifest_entries"] == ["numpy"]
    assert "Dependency manifest validation:" in agent.last_context["dependency_validation_summary"]
    assert "Missing manifest entries: numpy" in agent.last_context["dependency_validation_summary"]
    assert "Verdict: FAIL" in agent.last_context["dependency_validation_summary"]


def test_run_task_fails_dependency_manager_when_manifest_misses_required_imports(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="import numpy as np\n\ndef run():\n    return np.array([1])\n",
            output_payload={
                "summary": "import numpy as np",
                "raw_content": "import numpy as np\n\ndef run():\n    return np.array([1])\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "import numpy as np\n\ndef run():\n    return np.array([1])\n",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="deps",
            title="Dependencies",
            description="Infer dependencies",
            assigned_to="dependency_manager",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent("# No external runtime dependencies")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"dependency_manager": agent}))

    with pytest.raises(AgentExecutionError, match="missing manifest entries for numpy"):
        orchestrator.run_task(project.tasks[1], project)

    assert project.tasks[1].status == TaskStatus.FAILED.value
    assert project.tasks[1].output == "Dependency manifest validation failed: missing manifest entries for numpy"


def test_run_task_fails_dependency_manager_when_manifest_uses_unsupported_dependency_sources(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="import numpy as np\n\ndef run():\n    return np.array([1])\n",
            output_payload={
                "summary": "import numpy as np",
                "raw_content": "import numpy as np\n\ndef run():\n    return np.array([1])\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "import numpy as np\n\ndef run():\n    return np.array([1])\n",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="deps",
            title="Dependencies",
            description="Infer dependencies",
            assigned_to="dependency_manager",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent("numpy @ https://example.com/numpy.whl")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"dependency_manager": agent}))

    with pytest.raises(AgentExecutionError, match="unsupported dependency sources or installer directives"):
        orchestrator.run_task(project.tasks[1], project)

    assert project.tasks[1].status == TaskStatus.FAILED.value
    assert project.tasks[1].output == (
        "Dependency manifest validation failed: unsupported dependency sources or installer directives: "
        "numpy @ https://example.com/numpy.whl"
    )


def test_run_task_fails_code_engineer_when_generated_code_has_syntax_error(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
        )
    )

    agent = RecordingAgent("def broken(:\n    return 1\n")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"code_engineer": agent}))

    with pytest.raises(AgentExecutionError, match="Generated code validation failed: syntax error"):
        orchestrator.run_task(project.tasks[0], project)

    assert project.tasks[0].status == TaskStatus.FAILED.value
    assert project.tasks[0].output is not None
    assert "Generated code validation failed: syntax error" in project.tasks[0].output
    assert project.tasks[0].output_payload is not None
    assert project.tasks[0].output_payload["raw_content"] == "def broken(:\n    return 1\n"
    assert project.tasks[0].output_payload["metadata"]["validation"]["code_analysis"]["syntax_ok"] is False


def test_run_task_fails_qa_tester_when_generated_tests_fail_pytest_execution(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def run():\n    return 1\n",
            output_payload={
                "summary": "def run():",
                "raw_content": "def run():\n    return 1\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def run():\n    return 1\n",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import run\n\n"
        "def test_run():\n"
        "    assert run() == 2\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match="Generated test validation failed: pytest failed"):
        orchestrator.run_task(project.tasks[1], project)

    assert project.tasks[1].status == TaskStatus.FAILED.value
    assert project.tasks[1].output is not None
    assert "Generated test validation failed: pytest failed" in project.tasks[1].output
    assert project.tasks[1].output_payload is not None
    assert project.tasks[1].output_payload["raw_content"].startswith("from code_implementation import run")
    assert project.tasks[1].output_payload["metadata"]["validation"]["test_execution"]["returncode"] != 0


def test_run_task_redacts_sensitive_pytest_validation_output_in_live_state(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def run():\n    return 1\n",
            output_payload={
                "summary": "def run():",
                "raw_content": "def run():\n    return 1\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def run():\n    return 1\n",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    monkeypatch.setattr(
        orchestrator_module.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcessStub(
            returncode=1,
            stdout=(
                "FAILED tests_generated.py::test_run - Authorization: Bearer sk-ant-secret-987654\n"
                "E   password=hunter2\n"
            ),
            stderr="api_key=sk-secret-123456",
        ),
    )

    agent = RecordingAgent(
        "from code_implementation import run\n\n"
        "def test_run():\n"
        "    assert run() == 2\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match="Generated test validation failed: pytest failed"):
        orchestrator.run_task(project.tasks[1], project)

    assert project.tasks[1].output is not None
    assert "sk-secret-123456" not in project.tasks[1].output
    assert "sk-ant-secret-987654" not in project.tasks[1].output
    test_execution = project.tasks[1].output_payload["metadata"]["validation"]["test_execution"]
    assert "sk-secret-123456" not in test_execution["stderr"]
    assert "hunter2" not in test_execution["stdout"]
    assert "sk-ant-secret-987654" not in test_execution["summary"]
    assert "[REDACTED]" in test_execution["stdout"]
    assert "[REDACTED]" in test_execution["stderr"]
    assert "[REDACTED]" in test_execution["summary"]


def test_generated_test_subprocess_strips_inherited_coverage_env(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    orchestrator = Orchestrator(config, registry=AgentRegistry({}))
    captured_env: dict[str, str] = {}

    monkeypatch.setenv("COV_CORE_SOURCE", "kycortex_agents")
    monkeypatch.setenv("COV_CORE_CONFIG", "/tmp/.coveragerc")
    monkeypatch.setenv("COV_CORE_DATAFILE", "/tmp/.coverage")
    monkeypatch.setenv("COVERAGE_PROCESS_START", "/tmp/.coveragerc")
    monkeypatch.setenv("COVERAGE_FILE", "/tmp/custom.coverage")
    monkeypatch.setenv("COVERAGE_RCFILE", "/tmp/custom.coveragerc")
    monkeypatch.setenv("COVERAGE_DEBUG", "config")

    def fake_run(*args, **kwargs):
        captured_env.update(kwargs["env"])
        return CompletedProcessStub()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = orchestrator._execute_generated_tests(
        "code_implementation.py",
        "def run():\n    return 1\n",
        "tests_tests.py",
        "from code_implementation import run\n\ndef test_run():\n    assert run() == 1\n",
    )

    assert result["ran"] is True
    assert result["returncode"] == 0
    assert captured_env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "COV_CORE_SOURCE" not in captured_env
    assert "COV_CORE_CONFIG" not in captured_env
    assert "COV_CORE_DATAFILE" not in captured_env
    assert "COVERAGE_PROCESS_START" not in captured_env
    assert "COVERAGE_FILE" not in captured_env
    assert "COVERAGE_RCFILE" not in captured_env
    assert "COVERAGE_DEBUG" not in captured_env


def test_run_task_fails_qa_tester_when_generated_tests_use_undefined_fixtures(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def run():\n    return 1\n",
            output_payload={
                "summary": "def run():",
                "raw_content": "def run():\n    return 1\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def run():\n    return 1\n",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import run\n\n"
        "def test_run(sample_case):\n"
        "    assert run() == 1\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"undefined test fixtures: sample_case \(line 3\)"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["undefined_fixtures"] == ["sample_case (line 3)"]


def test_analyze_test_module_treats_parametrize_arguments_as_bound_names(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    analysis = orchestrator._analyze_test_module(
        "import pytest\n"
        "from module_under_test import batch_process\n\n"
        "@pytest.mark.parametrize(\"requests, expected\", [([1], [1])])\n"
        "def test_batch_process(requests, expected):\n"
        "    assert batch_process(requests) == expected\n",
        "module_under_test",
        {"syntax_ok": True, "functions": [{"name": "batch_process"}], "classes": {}, "symbols": ["batch_process"]},
    )

    assert analysis["undefined_fixtures"] == []
    assert analysis["undefined_local_names"] == []


def test_run_task_fails_qa_tester_when_generated_tests_use_undefined_local_names(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def run():\n    return 1\n",
            output_payload={
                "summary": "def run():",
                "raw_content": "def run():\n    return 1\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def run():\n    return 1\n",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import run\n\n"
        "def test_run():\n"
        "    assert run() == expected_result\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"undefined local names: expected_result \(line 4\)"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["undefined_local_names"] == ["expected_result (line 4)"]


def test_run_task_fails_qa_tester_when_generated_tests_call_entrypoints_directly(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "def cli_demo():\n"
                "    return 'demo'\n\n"
                "def main():\n"
                "    return cli_demo()\n"
            ),
            output_payload={
                "summary": "def cli_demo():",
                "raw_content": (
                    "def cli_demo():\n"
                    "    return 'demo'\n\n"
                    "def main():\n"
                    "    return cli_demo()\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "def cli_demo():\n"
                            "    return 'demo'\n\n"
                            "def main():\n"
                            "    return cli_demo()\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import main\n\n"
        "def test_main():\n"
        "    assert main() == 'demo'\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"unsafe entrypoint calls: main\(\) \(line 4\)"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["unsafe_entrypoint_calls"] == ["main() (line 4)"]


def test_run_task_fails_qa_tester_when_generated_tests_import_entrypoints(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "def run():\n"
                "    return 1\n\n"
                "def main():\n"
                "    return run()\n"
            ),
            output_payload={
                "summary": "def run():",
                "raw_content": (
                    "def run():\n"
                    "    return 1\n\n"
                    "def main():\n"
                    "    return run()\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "def run():\n"
                            "    return 1\n\n"
                            "def main():\n"
                            "    return run()\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import run, main\n\n"
        "def test_run():\n"
        "    assert run() == 1\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"imported entrypoint symbols: main"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["imported_entrypoint_symbols"] == ["main"]


def test_run_task_fails_qa_tester_when_generated_tests_import_cli_wrapper_classes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "class ComplianceService:\n"
                "    def process(self):\n"
                "        return 1\n\n"
                "class ComplianceCLI:\n"
                "    def run(self):\n"
                "        return 1\n"
            ),
            output_payload={
                "summary": "class ComplianceService:",
                "raw_content": (
                    "class ComplianceService:\n"
                    "    def process(self):\n"
                    "        return 1\n\n"
                    "class ComplianceCLI:\n"
                    "    def run(self):\n"
                    "        return 1\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "class ComplianceService:\n"
                            "    def process(self):\n"
                            "        return 1\n\n"
                            "class ComplianceCLI:\n"
                            "    def run(self):\n"
                            "        return 1\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import ComplianceCLI\n\n"
        "def test_cli_run():\n"
        "    cli = ComplianceCLI()\n"
        "    assert cli.run() == 1\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"imported entrypoint symbols: ComplianceCLI"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["imported_entrypoint_symbols"] == ["ComplianceCLI"]


def test_run_task_fails_qa_tester_when_generated_tests_violate_payload_contract(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    code_content = (
        "class Service:\n"
        "    def intake_request(self, request_id, data):\n"
        "        if not self.validate_request(data):\n"
        "            raise ValueError('Invalid request data')\n"
        "        return data\n\n"
        "    def validate_request(self, data):\n"
        "        required_fields = {'name', 'email', 'compliance_type'}\n"
        "        return all(field in data for field in required_fields)\n\n"
        "    def process_batch(self, requests):\n"
        "        for req in requests:\n"
        "            self.intake_request(req['request_id'], req)\n"
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=code_content,
            output_payload={
                "summary": "class Service:",
                "raw_content": code_content,
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": code_content,
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "import pytest\n"
        "from code_implementation import Service\n\n"
        "@pytest.fixture\n"
        "def service():\n"
        "    return Service()\n\n"
        "def test_intake_request(service):\n"
        "    payload = {'field1': 'value1'}\n"
        "    with pytest.raises(ValueError):\n"
        "        service.intake_request('req-1', payload)\n\n"
        "def test_process_batch(service):\n"
        "    requests = [{'request_id': 'req-1', 'field1': 'value1'}]\n"
        "    service.process_batch(requests)\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"payload contract violations"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["payload_contract_violations"] == [
        "process_batch batch item missing required fields: name, email, compliance_type at line 14",
    ]


def test_run_task_fails_qa_tester_when_generated_tests_treat_non_batch_api_as_batch(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    code_content = (
        "class ComplianceCase:\n"
        "    def __init__(self, case_id):\n"
        "        self.case_id = case_id\n\n"
        "def process_case(case):\n"
        "    return case.case_id\n"
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=code_content,
            output_payload={
                "summary": "class ComplianceCase:",
                "raw_content": code_content,
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": code_content,
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import ComplianceCase, process_case\n\n"
        "def test_process_case_list():\n"
        "    cases = [ComplianceCase(1), ComplianceCase(2)]\n"
        "    assert process_case(cases) == 1\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"non-batch sequence calls"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["non_batch_sequence_calls"] == [
        "process_case does not accept batch/list inputs at line 5"
    ]


def test_run_task_allows_generated_tests_to_use_list_for_sequence_function(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    code_content = (
        "from typing import List\n\n"
        "class ComplianceCase:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n\n"
        "def process_cases(cases: List[ComplianceCase]) -> int:\n"
        "    return len(cases)\n"
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=code_content,
            output_payload={
                "summary": "class ComplianceCase:",
                "raw_content": code_content,
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": code_content,
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import ComplianceCase, process_cases\n\n"
        "def test_process_cases_list():\n"
        "    cases = [ComplianceCase(1), ComplianceCase(2)]\n"
        "    assert process_cases(cases) == 2\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    result = orchestrator.run_task(project.tasks[1], project)

    assert "def test_process_cases_list" in result
    validation = require_test_validation(project.tasks[1])
    assert validation["non_batch_sequence_calls"] == []


def test_run_task_fails_qa_tester_when_generated_tests_miss_nested_constructor_payload_fields(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    code_content = (
        "class ComplianceRequest:\n"
        "    def __init__(self, request_id, data):\n"
        "        self.request_id = request_id\n"
        "        self.data = data\n\n"
        "class Service:\n"
        "    def validate_request(self, request):\n"
        "        return 'compliance_data' in request.data\n"
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=code_content,
            output_payload={
                "summary": "class ComplianceRequest:",
                "raw_content": code_content,
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": code_content,
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import ComplianceRequest, Service\n\n"
        "def test_validate_request(service=Service()):\n"
        "    request = ComplianceRequest(request_id='req-1', data={'key': 'value'})\n"
        "    assert service.validate_request(request) is True\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"payload contract violations"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["payload_contract_violations"] == [
        "validate_request payload missing required fields: compliance_data at line 5"
    ]


def test_run_task_fails_qa_tester_when_generated_tests_use_unsupported_field_literals(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    code_content = (
        "class ComplianceRequest:\n"
        "    def __init__(self, document_type):\n"
        "        self.document_type = document_type\n\n"
        "def score_request(request):\n"
        "    risk_scores = {'document_type': {'contract': 0.5}}\n"
        "    return risk_scores[request.document_type].get('contract', 0)\n"
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=code_content,
            output_payload={
                "summary": "class ComplianceRequest:",
                "raw_content": code_content,
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": code_content,
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import ComplianceRequest, score_request\n\n"
        "def test_score_request():\n"
        "    request = ComplianceRequest(document_type='type')\n"
        "    assert score_request(request) == 0.5\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(AgentExecutionError, match=r"payload contract violations"):
        orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["payload_contract_violations"] == [
        "score_request field `document_type` uses unsupported values: type at line 5"
    ]


def test_run_task_allows_missing_required_fields_for_intentional_invalid_status_assertion(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    code_content = (
        "class ComplianceRequest:\n"
        "    def __init__(self, request_id, data):\n"
        "        self.request_id = request_id\n"
        "        self.data = data\n"
        "        self.status = 'Pending'\n\n"
        "    def validate(self):\n"
        "        required_fields = {'name', 'amount', 'risk_factor'}\n"
        "        return all(field in self.data for field in required_fields)\n\n"
        "def process_request(request):\n"
        "    if not request.validate():\n"
        "        request.status = 'Invalid'\n"
        "        return\n"
        "    request.status = 'Processed'\n"
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=code_content,
            output_payload={
                "summary": "class ComplianceRequest:",
                "raw_content": code_content,
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": code_content,
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import ComplianceRequest, process_request\n\n"
        "def test_process_request_validation_failure():\n"
        "    request = ComplianceRequest('req-1', {'name': 'Test', 'amount': 200})\n"
        "    process_request(request)\n"
        "    assert request.status == 'Invalid'\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["payload_contract_violations"] == []
    assert project.tasks[1].status == TaskStatus.DONE.value


def test_run_task_allows_missing_required_fields_for_intentional_pending_status_assertion(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=30.0)
    project = ProjectState(project_name="Demo", goal="Build demo")
    code_content = (
        "class ComplianceRequest:\n"
        "    def __init__(self, request_id, data):\n"
        "        self.request_id = request_id\n"
        "        self.data = data\n"
        "        self.status = 'Pending'\n\n"
        "    def validate(self):\n"
        "        required_fields = {'name', 'amount', 'risk_factor'}\n"
        "        return all(field in self.data for field in required_fields)\n\n"
        "def process_request(request):\n"
        "    if not request.validate():\n"
        "        return\n"
        "    request.status = 'Processed'\n"
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=code_content,
            output_payload={
                "summary": "class ComplianceRequest:",
                "raw_content": code_content,
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": code_content,
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent(
        "from code_implementation import ComplianceRequest, process_request\n\n"
        "def test_process_request_validation_failure():\n"
        "    request = ComplianceRequest('req-1', {'name': 'Test', 'amount': 200})\n"
        "    process_request(request)\n"
        "    assert request.status == 'Pending'\n"
    )
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    orchestrator.run_task(project.tasks[1], project)

    validation = require_test_validation(project.tasks[1])
    assert validation["payload_contract_violations"] == []
    assert project.tasks[1].status == TaskStatus.DONE.value


def test_code_artifact_context_includes_behavior_contract(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "class Service:\n"
                "    def intake_request(self, request_id, data):\n"
                "        if not self.validate_request(data):\n"
                "            raise ValueError('Invalid request data')\n"
                "        return data\n\n"
                "    def validate_request(self, data):\n"
                "        required_fields = {'name', 'email', 'compliance_type'}\n"
                "        return all(field in data for field in required_fields)\n\n"
                "    def process_batch(self, requests):\n"
                "        for req in requests:\n"
                "            self.intake_request(req['request_id'], req)\n"
            ),
            output_payload={
                "summary": "class Service:",
                "raw_content": (
                    "class Service:\n"
                    "    def intake_request(self, request_id, data):\n"
                    "        if not self.validate_request(data):\n"
                    "            raise ValueError('Invalid request data')\n"
                    "        return data\n\n"
                    "    def validate_request(self, data):\n"
                    "        required_fields = {'name', 'email', 'compliance_type'}\n"
                    "        return all(field in data for field in required_fields)\n\n"
                    "    def process_batch(self, requests):\n"
                    "        for req in requests:\n"
                    "            self.intake_request(req['request_id'], req)\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "class Service:\n"
                            "    def intake_request(self, request_id, data):\n"
                            "        if not self.validate_request(data):\n"
                            "            raise ValueError('Invalid request data')\n"
                            "        return data\n\n"
                            "    def validate_request(self, data):\n"
                            "        required_fields = {'name', 'email', 'compliance_type'}\n"
                            "        return all(field in data for field in required_fields)\n\n"
                            "    def process_batch(self, requests):\n"
                            "        for req in requests:\n"
                            "            self.intake_request(req['request_id'], req)\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )

    orchestrator = Orchestrator(config)
    context = orchestrator._build_context(project.tasks[0], project)

    assert "Behavior contract:" in context["code_behavior_contract"]
    assert "Exact test contract:" in context["code_exact_test_contract"]
    assert "Allowed production imports: Service" in context["code_exact_test_contract"]
    assert "Exact public class methods:" in context["code_exact_test_contract"]
    assert "Service.intake_request" in context["code_exact_test_contract"]
    assert "Service.validate_request" in context["code_exact_test_contract"]
    assert "Service.process_batch" in context["code_exact_test_contract"]
    assert "Test targets:" in context["code_test_targets"]
    assert "Entry points to avoid in tests: none" in context["code_test_targets"]
    assert "validate_request requires fields: name, email, compliance_type" in context["code_behavior_contract"]
    assert "process_batch expects each batch item to include: request_id, name, email, compliance_type" in context["code_behavior_contract"]


def test_build_context_extracts_task_public_contract_anchor(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    task = Task(
        id="arch",
        title="Architecture",
        description=(
            "Design the system.\n\n"
            "Public contract anchor:\n"
            "- Public facade: ComplianceIntakeService\n"
            "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
            "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
            "\n"
            "Keep the design compact."
        ),
        assigned_to="architect",
    )
    project.add_task(task)

    orchestrator = Orchestrator(config)
    context = orchestrator._build_context(task, project)

    assert context["task_public_contract_anchor"] == (
        "- Public facade: ComplianceIntakeService\n"
        "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
        "- Required request workflow: ComplianceIntakeService.handle_request(request)"
    )


def test_build_context_includes_provider_max_tokens(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), max_tokens=900)
    project = ProjectState(project_name="Demo", goal="Build demo")
    task = Task(
        id="arch",
        title="Architecture",
        description="Design the system.",
        assigned_to="architect",
    )
    project.add_task(task)

    orchestrator = Orchestrator(config)
    context = orchestrator._build_context(task, project)

    assert context["provider_max_tokens"] == 900


def test_build_context_compacts_architecture_for_low_budget_code_tasks_with_anchor(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), max_tokens=900)
    project = ProjectState(project_name="Demo", goal="Build demo")
    architecture_output = "# Architecture\n\nVery long architecture document that should not be copied verbatim into the low-budget code prompt."
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output=architecture_output,
        )
    )
    code_task = Task(
        id="code",
        title="Implementation",
        description=(
            "Write one Python module under 300 lines with a CLI demo entrypoint.\n\n"
            "Public contract anchor:\n"
            "- Public facade: ComplianceIntakeService\n"
            "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
            "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
            "- Supporting validation surface: ComplianceIntakeService.validate_request(request)"
        ),
        assigned_to="code_engineer",
    )
    project.add_task(code_task)

    orchestrator = Orchestrator(config)
    context = orchestrator._build_context(code_task, project)

    assert context["architecture"].startswith("Low-budget architecture summary:")
    assert "- Public facade: ComplianceIntakeService" in context["architecture"]
    assert "Stay comfortably under 300 lines" in context["architecture"]
    assert 'main() plus a literal if __name__ == "__main__": block' in context["architecture"]
    assert context["arch"] == architecture_output
    assert context["completed_tasks"]["arch"] == architecture_output


def test_code_artifact_context_includes_field_value_contracts(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    code_content = (
        "class ComplianceRequest:\n"
        "    def __init__(self, document_type):\n"
        "        self.document_type = document_type\n\n"
        "def score_request(request):\n"
        "    risk_scores = {'document_type': {'contract': 0.5}}\n"
        "    return risk_scores[request.document_type].get('contract', 0)\n"
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=code_content,
            output_payload={
                "summary": "class ComplianceRequest:",
                "raw_content": code_content,
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": code_content,
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )

    orchestrator = Orchestrator(config)
    context = orchestrator._build_context(project.tasks[0], project)

    assert "score_request expects field `document_type` to be one of: document_type" in context["code_behavior_contract"]


@pytest.mark.parametrize(
    ("provider_name", "provider_factory"),
    [
        (
            "openai",
            lambda tmp_path: OpenAIProvider(
                KYCortexConfig(
                    output_dir=str(tmp_path / "output_openai"),
                    llm_provider="openai",
                    api_key="token",
                    llm_model="gpt-4o-mini",
                ),
                client=build_openai_client(
                    response=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="# No external runtime dependencies"))],
                        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                    ),
                    health_response=[SimpleNamespace(id="gpt-4o-mini")],
                ),
            ),
        ),
        (
            "anthropic",
            lambda tmp_path: AnthropicProvider(
                KYCortexConfig(
                    output_dir=str(tmp_path / "output_anthropic"),
                    llm_provider="anthropic",
                    api_key="token",
                    llm_model="claude-3-5-sonnet-latest",
                ),
                client=build_anthropic_client(
                    response=SimpleNamespace(
                        content=[SimpleNamespace(type="text", text="# No external runtime dependencies")],
                        usage=SimpleNamespace(input_tokens=12, output_tokens=8),
                    ),
                    health_response=[SimpleNamespace(id="claude-3-5-sonnet-latest")],
                ),
            ),
        ),
        (
            "ollama",
            lambda tmp_path: OllamaProvider(
                KYCortexConfig(
                    output_dir=str(tmp_path / "output_ollama"),
                    llm_provider="ollama",
                    llm_model="llama3",
                    base_url="http://localhost:11434",
                ),
                request_opener=build_ollama_opener(
                    payload=[
                        '{"response": "# No external runtime dependencies", "prompt_eval_count": 10, "eval_count": 5}',
                    ],
                    health_payload='{"models": [{"name": "llama3:latest"}]}'
                ),
            ),
        ),
    ],
)
def test_run_task_fails_dependency_manager_across_supported_providers(tmp_path, provider_name, provider_factory):
    provider = provider_factory(tmp_path)
    config = provider.config
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="import numpy as np\n\ndef run():\n    return np.array([1])\n",
            output_payload={
                "summary": "import numpy as np",
                "raw_content": "import numpy as np\n\ndef run():\n    return np.array([1])\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "import numpy as np\n\ndef run():\n    return np.array([1])\n",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="deps",
            title="Dependencies",
            description="Infer dependencies",
            assigned_to="dependency_manager",
            dependencies=["code"],
        )
    )

    agent = DependencyManagerAgent(config)
    agent._provider = provider
    orchestrator = Orchestrator(config, registry=AgentRegistry({"dependency_manager": agent}))

    with pytest.raises(AgentExecutionError, match="missing manifest entries for numpy"):
        orchestrator.run_task(project.tasks[1], project)

    assert project.tasks[1].status == TaskStatus.FAILED.value
    assert project.tasks[1].output == "Dependency manifest validation failed: missing manifest entries for numpy"
    assert project.tasks[1].last_provider_call is not None
    assert project.tasks[1].last_provider_call["provider"] == provider_name
    assert project.tasks[1].last_provider_call["success"] is True


def test_run_task_allows_dependency_manager_when_alias_matches_declared_package(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="import yaml\n\ndef run():\n    return yaml.safe_load('x: 1')\n",
            output_payload={
                "summary": "import yaml",
                "raw_content": "import yaml\n\ndef run():\n    return yaml.safe_load('x: 1')\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "import yaml\n\ndef run():\n    return yaml.safe_load('x: 1')\n",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="deps",
            title="Dependencies",
            description="Infer dependencies",
            assigned_to="dependency_manager",
            dependencies=["code"],
        )
    )

    agent = RecordingAgent("PyYAML>=6.0")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"dependency_manager": agent}))

    result = orchestrator.run_task(project.tasks[1], project)

    assert result == "PyYAML>=6.0"
    assert project.tasks[1].status == TaskStatus.DONE.value


def test_run_task_marks_failure_and_reraises(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": FailingAgent()}))

    with pytest.raises(RuntimeError, match="boom"):
        orchestrator.run_task(project.tasks[0], project)

    assert project.tasks[0].status == TaskStatus.FAILED.value
    assert project.tasks[0].output == "boom"
    assert project.tasks[0].last_error_type == "RuntimeError"
    assert project.tasks[0].last_provider_call is None


def test_run_task_persists_structured_agent_outputs(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": StructuredAgent()}))

    result = orchestrator.run_task(project.tasks[0], project)

    assert result == "STRUCTURED OUTPUT"
    assert project.tasks[0].status == TaskStatus.DONE.value
    assert project.tasks[0].output_payload is not None
    assert project.tasks[0].output_payload["summary"] == "Decision summary"
    assert project.tasks[0].last_provider_call is None
    assert project.tasks[0].history[0]["event"] == "started"
    assert project.tasks[0].history[-1]["event"] == "completed"
    assert project.execution_events[0]["event"] == "task_started"
    assert project.execution_events[-1]["event"] == "task_completed"
    assert project.decisions[0]["topic"] == "stack"
    artifact = require_artifact(project)
    assert artifact["name"] == "architecture_doc"
    assert artifact["path"] == "artifacts/architecture.md"
    assert artifact["artifact_type"] == ArtifactType.DOCUMENT.value


def test_run_task_sanitizes_custom_provider_call_metadata_in_output_payload(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    class MetadataOutputAgent:
        def execute(self, agent_input) -> AgentOutput:
            return AgentOutput(
                summary="Structured metadata",
                raw_content="SAFE OUTPUT",
                metadata={
                    "provider_call": {
                        "provider": "openai",
                        "model": "gpt-test",
                        "base_url": "https://alice:secret-pass@example.com/v1",
                        "error_type": "AgentExecutionError",
                        "error_message": "api_key=sk-secret-123456",
                        "provider_cancellation_reason": "operator requested stop api_key=sk-secret-123456",
                        "circuit_breaker_failure_streak": 3,
                        "circuit_breaker_threshold": 2,
                        "circuit_breaker_cooldown_seconds": 10.0,
                        "circuit_breaker_remaining_seconds": 4.0,
                        "provider_timeout_seconds": 11.0,
                        "provider_timeout_provider_count": 2,
                        "provider_timeout_seconds_by_provider": {
                            "openai": 11.0,
                            "anthropic": 22.0,
                        },
                        "provider_elapsed_seconds": 3.0,
                        "provider_max_elapsed_seconds_per_call": 6.0,
                        "provider_remaining_elapsed_seconds": 3.0,
                        "attempt_history": [
                            {
                                "attempt": 1,
                                "success": False,
                                "retryable": False,
                                "error_type": "AgentExecutionError",
                                "error_message": "api_key=sk-secret-123456",
                                "uncapped_backoff_seconds": 0.0,
                                "base_backoff_seconds": 0.0,
                                "jitter_seconds": 0.0,
                                "backoff_seconds": 0.0,
                            }
                        ],
                        "fallback_history": [
                            {
                                "provider": "anthropic",
                                "model": "claude-test",
                                "status": "failed_health_check",
                                "remaining_cooldown_seconds": 7.5,
                                "error_type": "AgentExecutionError",
                                "error_message": "api_key=sk-secret-123456",
                                "retryable": False,
                            }
                        ],
                        "fallback_count": 1,
                        "provider_health": {
                            "openai": {
                                "model": "gpt-test",
                                "status": "degraded",
                                "circuit_breaker_open": True,
                                "transient_failure_streak": 3,
                                "last_success_age_seconds": 12.0,
                                "last_failure_age_seconds": 1.25,
                                "last_failure_retryable": True,
                                "last_error_type": "AgentExecutionError",
                                "last_health_check": {
                                    "status": "degraded",
                                    "error_type": "AgentExecutionError",
                                    "cooldown_remaining_seconds": 7.5,
                                },
                                "last_health_check_age_seconds": 0.5,
                            }
                        },
                    }
                },
            )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": MetadataOutputAgent()}))

    result = orchestrator.run_task(project.tasks[0], project)

    assert result == "SAFE OUTPUT"
    assert project.tasks[0].last_provider_call is not None
    assert project.tasks[0].last_provider_call["provider"] == "openai"
    assert project.tasks[0].last_provider_call["model"] == "gpt-test"
    assert "secret-pass" not in str(project.tasks[0].last_provider_call)
    assert "sk-secret-123456" not in str(project.tasks[0].last_provider_call)
    assert "[REDACTED]" in project.tasks[0].last_provider_call["base_url"]
    assert project.tasks[0].last_provider_call["has_error_type"] is True
    assert "error_type" not in project.tasks[0].last_provider_call
    assert project.tasks[0].last_provider_call["has_error_message"] is True
    assert "error_message" not in project.tasks[0].last_provider_call
    assert project.tasks[0].last_provider_call["has_provider_cancellation_reason"] is True
    assert "provider_cancellation_reason" not in project.tasks[0].last_provider_call
    assert "circuit_breaker_threshold" not in project.tasks[0].last_provider_call
    assert "circuit_breaker_cooldown_seconds" not in project.tasks[0].last_provider_call
    assert "circuit_breaker_remaining_seconds" not in project.tasks[0].last_provider_call
    assert "circuit_breaker_failure_streak" not in project.tasks[0].last_provider_call
    assert "provider_timeout_seconds" not in project.tasks[0].last_provider_call
    assert "provider_timeout_provider_count" not in project.tasks[0].last_provider_call
    assert "provider_timeout_seconds_by_provider" not in project.tasks[0].last_provider_call
    assert project.tasks[0].last_provider_call["provider_elapsed_budget_limited"] is True
    assert project.tasks[0].last_provider_call["provider_elapsed_budget_exhausted"] is False
    assert "provider_elapsed_seconds" not in project.tasks[0].last_provider_call
    assert "provider_max_elapsed_seconds_per_call" not in project.tasks[0].last_provider_call
    assert "provider_remaining_elapsed_seconds" not in project.tasks[0].last_provider_call
    assert project.tasks[0].last_provider_call["attempt_history"][0]["has_error_type"] is True
    assert "error_type" not in project.tasks[0].last_provider_call["attempt_history"][0]
    assert project.tasks[0].last_provider_call["attempt_history"][0]["has_error_message"] is True
    assert "error_message" not in project.tasks[0].last_provider_call["attempt_history"][0]
    assert "uncapped_backoff_seconds" not in project.tasks[0].last_provider_call["attempt_history"][0]
    assert "base_backoff_seconds" not in project.tasks[0].last_provider_call["attempt_history"][0]
    assert "jitter_seconds" not in project.tasks[0].last_provider_call["attempt_history"][0]
    assert project.tasks[0].last_provider_call["fallback_history"][0]["has_error_type"] is True
    assert "error_type" not in project.tasks[0].last_provider_call["fallback_history"][0]
    assert project.tasks[0].last_provider_call["fallback_history"][0]["has_error_message"] is True
    assert "error_message" not in project.tasks[0].last_provider_call["fallback_history"][0]
    assert "fallback_count" not in project.tasks[0].last_provider_call
    assert (
        "remaining_cooldown_seconds"
        not in project.tasks[0].last_provider_call["fallback_history"][0]
    )
    assert project.tasks[0].last_provider_call["provider_health"]["openai"]["has_last_error_type"] is True
    assert "last_error_type" not in project.tasks[0].last_provider_call["provider_health"]["openai"]
    assert "circuit_breaker_open" not in project.tasks[0].last_provider_call["provider_health"]["openai"]
    assert "last_failure_retryable" not in project.tasks[0].last_provider_call["provider_health"]["openai"]
    assert "transient_failure_streak" not in project.tasks[0].last_provider_call["provider_health"]["openai"]
    assert "last_success_age_seconds" not in project.tasks[0].last_provider_call["provider_health"]["openai"]
    assert "last_failure_age_seconds" not in project.tasks[0].last_provider_call["provider_health"]["openai"]
    assert "last_health_check_age_seconds" not in project.tasks[0].last_provider_call["provider_health"]["openai"]
    assert (
        project.tasks[0].last_provider_call["provider_health"]["openai"]["last_health_check"]["has_error_type"]
        is True
    )
    assert (
        "error_type"
        not in project.tasks[0].last_provider_call["provider_health"]["openai"]["last_health_check"]
    )
    assert (
        "cooldown_remaining_seconds"
        not in project.tasks[0].last_provider_call["provider_health"]["openai"]["last_health_check"]
    )
    payload = require_output_payload(project.tasks[0])
    assert payload["metadata"]["provider_call"]["provider"] == "openai"
    assert payload["metadata"]["provider_call"]["model"] == "gpt-test"
    assert "active_provider" not in payload["metadata"]["provider_call"]
    assert "active_model" not in payload["metadata"]["provider_call"]
    assert "secret-pass" not in str(payload["metadata"]["provider_call"])
    assert "sk-secret-123456" not in str(payload["metadata"]["provider_call"])
    assert "[REDACTED]" in payload["metadata"]["provider_call"]["base_url"]
    assert payload["metadata"]["provider_call"]["has_error_type"] is True
    assert "error_type" not in payload["metadata"]["provider_call"]
    assert payload["metadata"]["provider_call"]["has_error_message"] is True
    assert "error_message" not in payload["metadata"]["provider_call"]
    assert payload["metadata"]["provider_call"]["has_provider_cancellation_reason"] is True
    assert "provider_cancellation_reason" not in payload["metadata"]["provider_call"]
    assert "circuit_breaker_threshold" not in payload["metadata"]["provider_call"]
    assert "circuit_breaker_cooldown_seconds" not in payload["metadata"]["provider_call"]
    assert "circuit_breaker_remaining_seconds" not in payload["metadata"]["provider_call"]
    assert "circuit_breaker_failure_streak" not in payload["metadata"]["provider_call"]
    assert "provider_timeout_seconds" not in payload["metadata"]["provider_call"]
    assert "provider_timeout_provider_count" not in payload["metadata"]["provider_call"]
    assert "provider_timeout_seconds_by_provider" not in payload["metadata"]["provider_call"]
    assert payload["metadata"]["provider_call"]["provider_elapsed_budget_limited"] is True
    assert payload["metadata"]["provider_call"]["provider_elapsed_budget_exhausted"] is False
    assert "provider_elapsed_seconds" not in payload["metadata"]["provider_call"]
    assert "provider_max_elapsed_seconds_per_call" not in payload["metadata"]["provider_call"]
    assert "provider_remaining_elapsed_seconds" not in payload["metadata"]["provider_call"]
    assert payload["metadata"]["provider_call"]["attempt_history"][0]["has_error_type"] is True
    assert "error_type" not in payload["metadata"]["provider_call"]["attempt_history"][0]
    assert payload["metadata"]["provider_call"]["attempt_history"][0]["has_error_message"] is True
    assert "error_message" not in payload["metadata"]["provider_call"]["attempt_history"][0]
    assert "uncapped_backoff_seconds" not in payload["metadata"]["provider_call"]["attempt_history"][0]
    assert "base_backoff_seconds" not in payload["metadata"]["provider_call"]["attempt_history"][0]
    assert "jitter_seconds" not in payload["metadata"]["provider_call"]["attempt_history"][0]
    assert payload["metadata"]["provider_call"]["fallback_history"][0]["has_error_type"] is True
    assert "error_type" not in payload["metadata"]["provider_call"]["fallback_history"][0]
    assert payload["metadata"]["provider_call"]["fallback_history"][0]["has_error_message"] is True
    assert "error_message" not in payload["metadata"]["provider_call"]["fallback_history"][0]
    assert "fallback_count" not in payload["metadata"]["provider_call"]
    assert "model" not in payload["metadata"]["provider_call"]["fallback_history"][0]
    assert (
        "remaining_cooldown_seconds"
        not in payload["metadata"]["provider_call"]["fallback_history"][0]
    )
    assert payload["metadata"]["provider_call"]["provider_health"]["openai"]["has_last_error_type"] is True
    assert "last_error_type" not in payload["metadata"]["provider_call"]["provider_health"]["openai"]
    assert "circuit_breaker_open" not in payload["metadata"]["provider_call"]["provider_health"]["openai"]
    assert "last_failure_retryable" not in payload["metadata"]["provider_call"]["provider_health"]["openai"]
    assert "transient_failure_streak" not in payload["metadata"]["provider_call"]["provider_health"]["openai"]
    assert "last_success_age_seconds" not in payload["metadata"]["provider_call"]["provider_health"]["openai"]
    assert "last_failure_age_seconds" not in payload["metadata"]["provider_call"]["provider_health"]["openai"]
    assert "last_health_check_age_seconds" not in payload["metadata"]["provider_call"]["provider_health"]["openai"]
    assert (
        payload["metadata"]["provider_call"]["provider_health"]["openai"]["last_health_check"]["has_error_type"]
        is True
    )
    assert (
        "error_type"
        not in payload["metadata"]["provider_call"]["provider_health"]["openai"]["last_health_check"]
    )
    assert (
        "cooldown_remaining_seconds"
        not in payload["metadata"]["provider_call"]["provider_health"]["openai"]["last_health_check"]
    )


def test_run_task_writes_default_artifact_content_to_output_dir(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    from kycortex_agents.agents.base_agent import BaseAgent

    class BaseArtifactAgent(BaseAgent):
        def __init__(self, cfg):
            super().__init__("Architect", "Architecture", cfg)

        def run(self, task_description: str, context: dict) -> str:
            return "ARCHITECTURE DOC"

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": BaseArtifactAgent(config)}))

    orchestrator.run_task(project.tasks[0], project)

    artifact = require_artifact(project)
    assert artifact["path"] == "artifacts/arch_output.txt"
    assert (tmp_path / "output" / "artifacts" / "arch_output.txt").read_text(encoding="utf-8") == "ARCHITECTURE DOC"


def test_run_task_redacts_default_artifact_content_before_persisting_to_output_dir(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    from kycortex_agents.agents.base_agent import BaseAgent

    class BaseArtifactAgent(BaseAgent):
        def __init__(self, cfg):
            super().__init__("Architect", "Architecture", cfg)

        def run(self, task_description: str, context: dict) -> str:
            return "api_key=sk-secret-123456\nAuthorization: Bearer sk-ant-secret-987654"

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": BaseArtifactAgent(config)}))

    orchestrator.run_task(project.tasks[0], project)

    artifact = require_artifact(project)
    persisted_content = (tmp_path / "output" / "artifacts" / "arch_output.txt").read_text(encoding="utf-8")

    assert project.tasks[0].output == "api_key=sk-secret-123456\nAuthorization: Bearer sk-ant-secret-987654"
    assert artifact["content"] == "api_key=[REDACTED]\nAuthorization: Bearer [REDACTED]"
    assert "sk-secret-123456" not in persisted_content
    assert "sk-ant-secret-987654" not in persisted_content
    assert persisted_content == artifact["content"]


def test_run_task_writes_structured_artifact_content_to_relative_output_path(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    class StructuredWritableAgent:
        def execute(self, agent_input) -> AgentOutput:
            return AgentOutput(
                summary="Architecture summary",
                raw_content="ARCHITECTURE DOC",
                artifacts=[
                    ArtifactRecord(
                        name="architecture_doc",
                        artifact_type=ArtifactType.DOCUMENT,
                        path="artifacts/architecture.md",
                        content="# Architecture\n\nSystem design",
                    )
                ],
            )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": StructuredWritableAgent()}))

    orchestrator.run_task(project.tasks[0], project)

    assert (tmp_path / "output" / "artifacts" / "architecture.md").read_text(encoding="utf-8") == "# Architecture\n\nSystem design"


def test_run_task_rejects_artifact_path_traversal(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    class TraversalArtifactAgent:
        def execute(self, agent_input) -> AgentOutput:
            return AgentOutput(
                summary="Architecture summary",
                raw_content="ARCHITECTURE DOC",
                artifacts=[
                    ArtifactRecord(
                        name="architecture_doc",
                        artifact_type=ArtifactType.DOCUMENT,
                        path="../escaped.md",
                        content="# escaped",
                    )
                ],
            )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": TraversalArtifactAgent()}))

    with pytest.raises(AgentExecutionError, match="parent-directory traversal is not allowed"):
        orchestrator.run_task(project.tasks[0], project)

    assert project.tasks[0].status == TaskStatus.FAILED.value
    assert not (tmp_path / "escaped.md").exists()


def test_run_task_rejects_absolute_artifact_path(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    class AbsoluteArtifactAgent:
        def execute(self, agent_input) -> AgentOutput:
            return AgentOutput(
                summary="Architecture summary",
                raw_content="ARCHITECTURE DOC",
                artifacts=[
                    ArtifactRecord(
                        name="architecture_doc",
                        artifact_type=ArtifactType.DOCUMENT,
                        path=str((tmp_path / "absolute.md").resolve()),
                        content="# escaped",
                    )
                ],
            )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": AbsoluteArtifactAgent()}))

    with pytest.raises(AgentExecutionError, match="absolute artifact paths are not allowed"):
        orchestrator.run_task(project.tasks[0], project)

    assert project.tasks[0].status == TaskStatus.FAILED.value
    assert not (tmp_path / "absolute.md").exists()


def test_run_task_rejects_artifact_output_escape_through_symlinked_directory(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    escaped_root = tmp_path / "escaped"
    escaped_root.mkdir()
    (tmp_path / "output").mkdir()
    linked_dir = tmp_path / "output" / "artifacts"
    linked_dir.symlink_to(escaped_root, target_is_directory=True)

    class SymlinkedArtifactAgent:
        def execute(self, agent_input) -> AgentOutput:
            return AgentOutput(
                summary="Architecture summary",
                raw_content="ARCHITECTURE DOC",
                artifacts=[
                    ArtifactRecord(
                        name="architecture_doc",
                        artifact_type=ArtifactType.DOCUMENT,
                        path="artifacts/architecture.md",
                        content="# escaped",
                    )
                ],
            )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": SymlinkedArtifactAgent()}))

    with pytest.raises(AgentExecutionError, match="resolves outside the output directory"):
        orchestrator.run_task(project.tasks[0], project)

    assert project.tasks[0].status == TaskStatus.FAILED.value
    assert not (escaped_root / "architecture.md").exists()


def test_run_task_persists_provider_call_metadata_from_base_agent(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    class ProviderBackedAgent(RecordingAgent):
        def __init__(self):
            super().__init__("unused")
            from kycortex_agents.agents.base_agent import BaseAgent
            from kycortex_agents.providers.base import BaseLLMProvider

            class InlineProvider(BaseLLMProvider):
                def generate(self, system_prompt: str, user_message: str) -> str:
                    return "ARCHITECTURE DOC"

                def get_last_call_metadata(self):
                    return {"usage": {"input_tokens": 21, "output_tokens": 13, "total_tokens": 34}}

            class InlineAgent(BaseAgent):
                def __init__(self, cfg):
                    super().__init__("Inline", "Testing", cfg)
                    self._provider = InlineProvider()

                def run(self, task_description: str, context: dict) -> str:
                    return self.chat("system", task_description)

            self.impl = InlineAgent(config)

        def execute(self, agent_input):
            return self.impl.execute(agent_input)

        def get_last_provider_call_metadata(self):
            return self.impl.get_last_provider_call_metadata()

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": ProviderBackedAgent()}))

    result = orchestrator.run_task(project.tasks[0], project)

    assert result == "ARCHITECTURE DOC"
    assert project.tasks[0].last_provider_call is not None
    assert project.tasks[0].last_provider_call["provider"] == "openai"
    assert project.tasks[0].last_provider_call["model"] == "gpt-4o"
    assert project.tasks[0].last_provider_call["success"] is True
    assert project.tasks[0].last_provider_call["usage"]["total_tokens"] == 34


def test_run_task_emits_structured_log_fields(tmp_path, caplog):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    class ProviderBackedAgent(RecordingAgent):
        def __init__(self):
            super().__init__("unused")
            from kycortex_agents.agents.base_agent import BaseAgent
            from kycortex_agents.providers.base import BaseLLMProvider

            class InlineProvider(BaseLLMProvider):
                def generate(self, system_prompt: str, user_message: str) -> str:
                    return "ARCHITECTURE DOC"

                def get_last_call_metadata(self):
                    return {"usage": {"input_tokens": 21, "output_tokens": 13, "total_tokens": 34}}

            class InlineAgent(BaseAgent):
                def __init__(self, cfg):
                    super().__init__("Inline", "Testing", cfg)
                    self._provider = InlineProvider()

                def run(self, task_description: str, context: dict) -> str:
                    return self.chat("system", task_description)

            self.impl = InlineAgent(config)

        def execute(self, agent_input):
            return self.impl.execute(agent_input)

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": ProviderBackedAgent()}))

    with caplog.at_level("INFO", logger="Orchestrator"):
        orchestrator.run_task(project.tasks[0], project)

    start_record = next(record for record in caplog.records if getattr(record, "event", None) == "task_started")
    complete_record = next(record for record in caplog.records if getattr(record, "event", None) == "task_completed")

    assert start_record.project_name == "Demo"
    assert start_record.task_id == "arch"
    assert start_record.assigned_to == "architect"
    assert complete_record.project_name == "Demo"
    assert complete_record.task_id == "arch"
    assert complete_record.provider == "openai"
    assert complete_record.total_tokens == 34


def test_execute_workflow_emits_structured_workflow_logs(tmp_path, caplog):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": RecordingAgent("ARCHITECTURE DOC")}))

    with caplog.at_level("INFO", logger="Orchestrator"):
        orchestrator.execute_workflow(project)

    events = [getattr(record, "event", None) for record in caplog.records]
    progress_record = next(record for record in caplog.records if getattr(record, "event", None) == "workflow_progress")
    finished_record = next(record for record in caplog.records if getattr(record, "event", None) == "workflow_finished")

    assert "workflow_started" in events
    assert "workflow_progress" in events
    assert "workflow_completed" in events
    assert "workflow_finished" in events
    assert progress_record.project_name == "Demo"
    assert progress_record.phase == "execution"
    assert progress_record.task_id == "arch"
    assert progress_record.task_status == TaskStatus.DONE.value
    assert progress_record.workflow_telemetry["task_status_counts"]["done"] == 1
    assert progress_record.workflow_telemetry["progress_summary"] == {
        "pending_task_count": 0,
        "running_task_count": 0,
        "runnable_task_count": 0,
        "blocked_task_count": 0,
        "terminal_task_count": 1,
        "completion_percent": 100,
    }
    assert finished_record.project_name == "Demo"
    assert finished_record.terminal_outcome == WorkflowOutcome.COMPLETED.value
    assert finished_record.workflow_telemetry["task_count"] == 1
    assert finished_record.workflow_telemetry["tasks_with_provider_calls"] == 0
    assert finished_record.workflow_telemetry["acceptance_summary"]["accepted"] is True


def test_orchestrator_control_logs_redact_sensitive_reasons(tmp_path, caplog):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config, registry=AgentRegistry({}))

    pause_project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(tmp_path / "pause.json"))
    pause_project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    pause_project.mark_workflow_running()

    skip_project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(tmp_path / "skip.json"))
    skip_project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Write docs",
            assigned_to="docs_writer",
        )
    )

    cancel_project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(tmp_path / "cancel.json"))
    cancel_project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Write docs",
            assigned_to="docs_writer",
        )
    )

    with caplog.at_level("INFO", logger="Orchestrator"):
        assert orchestrator.pause_workflow(pause_project, reason="api_key=sk-secret-123456") is True
        assert orchestrator.skip_task(skip_project, "docs", reason="Authorization: Bearer sk-ant-secret-987654") is True
        assert orchestrator.cancel_workflow(cancel_project, reason="password=hunter2") == ["docs"]

    pause_record = next(record for record in caplog.records if getattr(record, "event", None) == "workflow_paused")
    skip_record = next(record for record in caplog.records if getattr(record, "event", None) == "task_skipped")
    cancel_record = next(record for record in caplog.records if getattr(record, "event", None) == "workflow_cancelled")

    assert "sk-secret-123456" not in pause_record.reason
    assert "sk-ant-secret-987654" not in skip_record.reason
    assert "hunter2" not in cancel_record.reason
    assert "[REDACTED]" in pause_record.reason
    assert "[REDACTED]" in skip_record.reason
    assert "[REDACTED]" in cancel_record.reason
    assert not hasattr(cancel_record, "cancelled_task_ids")
    assert cancel_record.cancelled_task_count == 1


def test_orchestrator_log_event_minimizes_task_id_lists(tmp_path, caplog):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config, registry=AgentRegistry({}))

    with caplog.at_level("INFO", logger="Orchestrator"):
        orchestrator._log_event("info", "workflow_resumed", project_name="Demo", task_ids=["arch", "code"])
        orchestrator._log_event(
            "warning",
            "workflow_replayed",
            project_name="Demo",
            replayed_task_ids=["arch"],
            removed_task_ids=["code__repair_1", "code__repair_2"],
        )
        orchestrator._log_event(
            "error",
            "workflow_repair_budget_exhausted",
            project_name="Demo",
            failed_task_ids=["arch", "code"],
        )
        orchestrator._log_event(
            "warning",
            "workflow_blocked",
            project_name="Demo",
            blocked_task_ids=["docs"],
        )
        orchestrator._log_event(
            "warning",
            "dependent_tasks_skipped",
            project_name="Demo",
            task_id="arch",
            skipped_task_ids=["docs", "legal"],
        )
        orchestrator._log_event(
            "info",
            "task_repair_chained",
            project_name="Demo",
            task_id="arch",
            repair_task_ids=["arch__repair_1"],
        )

    resumed_record = next(record for record in caplog.records if getattr(record, "event", None) == "workflow_resumed")
    replayed_record = next(record for record in caplog.records if getattr(record, "event", None) == "workflow_replayed")
    exhausted_record = next(
        record for record in caplog.records if getattr(record, "event", None) == "workflow_repair_budget_exhausted"
    )
    blocked_record = next(record for record in caplog.records if getattr(record, "event", None) == "workflow_blocked")
    skipped_record = next(record for record in caplog.records if getattr(record, "event", None) == "dependent_tasks_skipped")
    repair_record = next(record for record in caplog.records if getattr(record, "event", None) == "task_repair_chained")

    assert not hasattr(resumed_record, "task_ids")
    assert resumed_record.task_count == 2
    assert not hasattr(replayed_record, "replayed_task_ids")
    assert not hasattr(replayed_record, "removed_task_ids")
    assert replayed_record.replayed_task_count == 1
    assert replayed_record.removed_task_count == 2
    assert not hasattr(exhausted_record, "failed_task_ids")
    assert exhausted_record.failed_task_count == 2
    assert not hasattr(blocked_record, "blocked_task_ids")
    assert blocked_record.blocked_task_count == 1
    assert not hasattr(skipped_record, "skipped_task_ids")
    assert skipped_record.skipped_task_count == 2
    assert not hasattr(repair_record, "repair_task_ids")
    assert repair_record.repair_task_count == 1


def test_execute_workflow_respects_task_dependencies(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": RecordingAgent("ARCHITECTURE DOC"),
                "code_engineer": RecordingAgent("IMPLEMENTED CODE"),
            }
        ),
    )

    orchestrator.execute_workflow(project)

    assert [task.status for task in project.tasks] == [TaskStatus.DONE.value, TaskStatus.DONE.value]
    assert project.tasks[1].output == "IMPLEMENTED CODE"
    assert project.phase == "completed"
    assert project.terminal_outcome == WorkflowOutcome.COMPLETED.value
    assert project.acceptance_criteria_met is True
    assert project.workflow_started_at is not None
    assert project.workflow_finished_at is not None
    assert project.execution_events[0]["event"] == "workflow_started"
    progress_events = [event for event in project.execution_events if event["event"] == "workflow_progress"]
    assert len(progress_events) == 2
    assert progress_events[0]["task_id"] == "arch"
    assert progress_events[0]["status"] == "execution"
    assert progress_events[0]["details"]["task_status"] == TaskStatus.DONE.value
    assert progress_events[0]["details"]["workflow_telemetry"]["task_status_counts"] == {
        "pending": 1,
        "running": 0,
        "done": 1,
        "failed": 0,
        "skipped": 0,
    }
    assert progress_events[0]["details"]["workflow_telemetry"]["progress_summary"] == {
        "pending_task_count": 1,
        "running_task_count": 0,
        "runnable_task_count": 1,
        "blocked_task_count": 0,
        "terminal_task_count": 1,
        "completion_percent": 50,
    }
    assert progress_events[1]["task_id"] == "code"
    assert progress_events[1]["details"]["workflow_telemetry"]["task_status_counts"]["done"] == 2
    assert progress_events[1]["details"]["workflow_telemetry"]["progress_summary"] == {
        "pending_task_count": 0,
        "running_task_count": 0,
        "runnable_task_count": 0,
        "blocked_task_count": 0,
        "terminal_task_count": 2,
        "completion_percent": 100,
    }
    assert project.execution_events[-1]["event"] == "workflow_finished"
    assert project.execution_events[-1]["details"]["workflow_duration_ms"] is not None
    assert project.execution_events[-1]["details"]["terminal_outcome"] == WorkflowOutcome.COMPLETED.value


def test_execute_workflow_raises_when_dependencies_cannot_be_satisfied(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            dependencies=["missing-arch"],
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"code_engineer": RecordingAgent("IMPLEMENTED CODE")}))

    with pytest.raises(WorkflowDefinitionError, match="depends on unknown task"):
        orchestrator.execute_workflow(project)


def test_execute_workflow_fails_when_task_assigned_to_missing_agent(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="missing_architect",
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({}))

    with pytest.raises(AgentExecutionError, match="Task 'arch' is assigned to unknown agent 'missing_architect'"):
        orchestrator.execute_workflow(project)

    assert project.phase == "init"
    assert project.workflow_started_at is None
    assert project.execution_events == []


def test_execute_workflow_fails_when_custom_registry_is_incomplete(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": RecordingAgent("ARCHITECTURE DOC")}))

    with pytest.raises(AgentExecutionError, match="Task 'code' is assigned to unknown agent 'code_engineer'"):
        orchestrator.execute_workflow(project)

    arch_task = require_task(project, "arch")
    code_task = require_task(project, "code")
    assert arch_task.status == TaskStatus.PENDING.value
    assert code_task.status == TaskStatus.PENDING.value


def test_execute_workflow_validates_all_tasks_before_any_execution(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the architecture",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )

    architect = RecordingAgent("ARCHITECTURE DOC")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": architect}))

    with pytest.raises(AgentExecutionError, match="Task 'review' is assigned to unknown agent 'code_reviewer'"):
        orchestrator.execute_workflow(project)

    assert architect.last_input is None
    assert all(task.attempts == 0 for task in project.tasks)
    assert all(task.status == TaskStatus.PENDING.value for task in project.tasks)


def test_execute_workflow_retries_task_until_success(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            retry_limit=1,
        )
    )

    agent = FlakyAgent(failures_before_success=1, success_response="IMPLEMENTED CODE")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"code_engineer": agent}))

    orchestrator.execute_workflow(project)

    assert agent.calls == 2
    assert project.tasks[0].status == TaskStatus.DONE.value
    assert project.tasks[0].output == "IMPLEMENTED CODE"
    assert project.tasks[0].attempts == 2


def test_execute_workflow_fails_when_retry_budget_is_exhausted(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            retry_limit=1,
        )
    )

    agent = FlakyAgent(failures_before_success=2, success_response="IMPLEMENTED CODE")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"code_engineer": agent}))

    with pytest.raises(RuntimeError, match="boom-2"):
        orchestrator.execute_workflow(project)

    assert agent.calls == 2
    assert project.tasks[0].status == TaskStatus.FAILED.value
    assert project.tasks[0].attempts == 2
    assert project.tasks[0].output == "boom-2"


def test_execute_workflow_resumes_interrupted_running_tasks(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    state_path = tmp_path / "state.json"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.RUNNING.value,
            attempts=1,
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": RecordingAgent("ARCHITECTURE DOC")}))

    orchestrator.execute_workflow(project)

    assert project.tasks[0].status == TaskStatus.DONE.value
    assert project.tasks[0].attempts == 2
    assert project.tasks[0].output == "ARCHITECTURE DOC"
    assert project.workflow_last_resumed_at is not None


def test_execute_workflow_returns_without_failure_when_project_is_prepaused(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.pause_workflow(reason="manual_operator_pause")

    agent = RecordingAgent("ARCHITECTURE DOC")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": agent}))

    orchestrator.execute_workflow(project)

    assert agent.last_input is None
    assert project.phase == WorkflowStatus.PAUSED.value
    assert project.workflow_finished_at is None
    assert project.tasks[0].status == TaskStatus.PENDING.value
    assert project.snapshot().workflow_status == WorkflowStatus.PAUSED


def test_execute_workflow_can_pause_between_tasks_and_resume_later(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Write the documentation",
            assigned_to="architect",
        )
    )

    pausing_agent = PausingAgent(["ARCHITECTURE DOC", "DOCUMENTATION"], project, "manual_operator_pause")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": pausing_agent}))

    orchestrator.execute_workflow(project)

    assert pausing_agent.calls == 1
    assert require_task(project, "arch").status == TaskStatus.DONE.value
    assert require_task(project, "docs").status == TaskStatus.PENDING.value
    assert project.phase == WorkflowStatus.PAUSED.value
    assert project.workflow_finished_at is None

    assert orchestrator.resume_workflow(project, reason="paused_workflow") is True
    orchestrator.execute_workflow(project)

    assert pausing_agent.calls == 2
    assert [task.status for task in project.tasks] == [TaskStatus.DONE.value, TaskStatus.DONE.value]
    assert project.phase == "completed"
    assert project.terminal_outcome == WorkflowOutcome.COMPLETED.value


def test_execute_workflow_returns_without_dispatch_when_project_is_precancelled(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.cancel_workflow(reason="manual_operator_cancel")

    agent = RecordingAgent("ARCHITECTURE DOC")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": agent}))

    orchestrator.execute_workflow(project)

    assert agent.last_input is None
    assert project.phase == WorkflowStatus.CANCELLED.value
    assert project.terminal_outcome == WorkflowOutcome.CANCELLED.value
    assert project.tasks[0].status == TaskStatus.SKIPPED.value
    assert project.snapshot().workflow_status == WorkflowStatus.CANCELLED


def test_execute_workflow_can_cancel_between_tasks(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Write the documentation",
            assigned_to="architect",
        )
    )

    cancelling_agent = CancellingAgent(["ARCHITECTURE DOC", "DOCUMENTATION"], project, "manual_operator_cancel")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": cancelling_agent}))

    orchestrator.execute_workflow(project)

    assert cancelling_agent.calls == 1
    assert require_task(project, "arch").status == TaskStatus.DONE.value
    assert require_task(project, "docs").status == TaskStatus.SKIPPED.value
    assert require_task(project, "docs").skip_reason_type == "workflow_cancelled"
    assert project.phase == WorkflowStatus.CANCELLED.value
    assert project.terminal_outcome == WorkflowOutcome.CANCELLED.value
    assert project.snapshot().workflow_status == WorkflowStatus.CANCELLED
    assert any(event["event"] == "workflow_cancelled" for event in project.execution_events)


def test_execute_workflow_can_continue_after_manual_task_override(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )

    architect = RecordingAgent("ARCHITECTURE DOC")
    code_engineer = RecordingAgent("IMPLEMENTED CODE")
    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry({"architect": architect, "code_engineer": code_engineer}),
    )

    assert orchestrator.override_task(project, "arch", "MANUAL ARCHITECTURE", reason="manual_operator_override") is True

    orchestrator.execute_workflow(project)

    assert architect.last_input is None
    assert require_task(project, "arch").status == TaskStatus.DONE.value
    assert require_task(project, "arch").output == "MANUAL ARCHITECTURE"
    assert require_task(project, "code").status == TaskStatus.DONE.value
    assert require_task(project, "code").output == "IMPLEMENTED CODE"
    assert any(event["event"] == "task_overridden" for event in project.execution_events)


def test_orchestrator_skip_task_marks_task_skipped_without_manual_state_edit(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Write docs",
            assigned_to="docs_writer",
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({}))

    assert orchestrator.skip_task(project, "docs", reason="manual_skip") is True
    assert require_task(project, "docs").status == TaskStatus.SKIPPED.value
    assert require_task(project, "docs").skip_reason_type == "manual"
    assert require_task(project, "docs").output == "manual_skip"


def test_orchestrator_replay_workflow_resets_completed_run_and_reexecutes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )

    architect = RecordingAgent("ARCHITECTURE DOC V1")
    code_engineer = RecordingAgent("IMPLEMENTED CODE V1")
    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry({"architect": architect, "code_engineer": code_engineer}),
    )

    orchestrator.execute_workflow(project)

    architect.response = "ARCHITECTURE DOC V2"
    code_engineer.response = "IMPLEMENTED CODE V2"

    replayed_task_ids = orchestrator.replay_workflow(project, reason="manual_replay")

    assert replayed_task_ids == ["arch", "code"]
    assert [task.status for task in project.tasks] == [TaskStatus.PENDING.value, TaskStatus.PENDING.value]
    assert all(task.output is None for task in project.tasks)
    assert project.phase == "init"

    orchestrator.execute_workflow(project)

    assert [task.status for task in project.tasks] == [TaskStatus.DONE.value, TaskStatus.DONE.value]
    assert require_task(project, "arch").output == "ARCHITECTURE DOC V2"
    assert require_task(project, "code").output == "IMPLEMENTED CODE V2"
    assert any(event["event"] == "workflow_replayed" for event in project.execution_events)


def test_execute_workflow_rejects_dependency_cycles(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            dependencies=["code"],
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry({"architect": RecordingAgent("ARCHITECTURE DOC"), "code_engineer": RecordingAgent("IMPLEMENTED CODE")}),
    )

    with pytest.raises(WorkflowDefinitionError, match="cyclic"):
        orchestrator.execute_workflow(project)


def test_execute_workflow_can_continue_after_terminal_failure(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), workflow_failure_policy="continue")
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the application",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": FailingAgent(),
                "code_engineer": RecordingAgent("IMPLEMENTED CODE"),
                "code_reviewer": RecordingAgent("REVIEWED"),
            }
        ),
    )

    orchestrator.execute_workflow(project)

    arch_task = require_task(project, "arch")
    code_task = require_task(project, "code")
    review_task = require_task(project, "review")
    assert arch_task.status == TaskStatus.FAILED.value
    assert code_task.status == TaskStatus.DONE.value
    assert review_task.status == TaskStatus.SKIPPED.value
    assert project.phase == "completed"
    assert project.terminal_outcome == WorkflowOutcome.DEGRADED.value
    assert project.acceptance_criteria_met is False


def test_execute_workflow_can_complete_under_required_task_acceptance_policy(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="continue",
        workflow_acceptance_policy="required_tasks",
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            required_for_acceptance=True,
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Document the application",
            assigned_to="docs_writer",
        )
    )

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "code_engineer": RecordingAgent("IMPLEMENTED CODE"),
                "docs_writer": FailingAgent(),
            }
        ),
    )

    orchestrator.execute_workflow(project)

    code_task = require_task(project, "code")
    docs_task = require_task(project, "docs")
    assert code_task.status == TaskStatus.DONE.value
    assert docs_task.status == TaskStatus.FAILED.value
    assert project.phase == "completed"
    assert project.acceptance_policy == "required_tasks"
    assert project.terminal_outcome == WorkflowOutcome.COMPLETED.value
    assert project.acceptance_criteria_met is True
    assert project.acceptance_evaluation["required_task_ids"] == ["code"]
    assert project.acceptance_evaluation["failed_task_ids"] == []
    assert project.snapshot().workflow_status == WorkflowStatus.COMPLETED


def test_execute_workflow_degrades_when_required_task_policy_has_no_required_tasks(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_acceptance_policy="required_tasks",
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description="Document the application",
            assigned_to="docs_writer",
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"docs_writer": RecordingAgent("DOCS")}))

    orchestrator.execute_workflow(project)

    docs_task = require_task(project, "docs")
    assert docs_task.status == TaskStatus.DONE.value
    assert project.phase == "completed"
    assert project.acceptance_policy == "required_tasks"
    assert project.terminal_outcome == WorkflowOutcome.DEGRADED.value
    assert project.acceptance_criteria_met is False
    assert project.acceptance_evaluation["reason"] == "no_required_tasks"


def test_execute_workflow_can_resume_failed_workflow(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the application",
            assigned_to="code_reviewer",
            dependencies=["arch"],
        )
    )

    architect = FlakyAgent(failures_before_success=1, success_response="ARCHITECTURE DOC")
    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": architect,
                "code_reviewer": RecordingAgent("REVIEWED"),
            }
        ),
    )

    with pytest.raises(RuntimeError, match="boom-1"):
        orchestrator.execute_workflow(project)

    arch_task = require_task(project, "arch")
    assert arch_task.status == TaskStatus.FAILED.value

    orchestrator.execute_workflow(project)

    arch_task = require_task(project, "arch")
    review_task = require_task(project, "review")
    repair_task = require_task(project, "arch__repair_1")
    assert arch_task.status == TaskStatus.DONE.value
    assert review_task.status == TaskStatus.DONE.value
    assert repair_task.status == TaskStatus.DONE.value
    assert repair_task.repair_origin_task_id == "arch"
    assert project.repair_cycle_count == 1
    assert project.repair_history[0]["reason"] == "resume_failed_tasks"
    assert project.repair_history[0]["failed_task_ids"] == ["arch"]
    assert project.execution_events[-1]["event"] == "workflow_finished"
    assert "requeued" in [entry["event"] for entry in arch_task.history]
    assert arch_task.history[-1]["event"] == "repaired"


def test_execute_workflow_resume_failed_routes_by_failure_category(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review generated code",
            description="Review the generated implementation",
            assigned_to="code_reviewer",
            status=TaskStatus.FAILED.value,
            output="Generated code validation failed",
            last_error="Generated code validation failed: syntax error '[' was never closed",
            last_error_type="AgentExecutionError",
            last_error_category=FailureCategory.CODE_VALIDATION.value,
            output_payload={
                "summary": "broken code",
                "raw_content": "def broken(:\n    pass",
                "artifacts": [
                    {
                        "name": "review_code",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/review_code.py",
                        "content": "def broken(:\n    pass",
                    }
                ],
                "decisions": [],
                "metadata": {
                    "validation": {
                        "code_analysis": {
                            "syntax_ok": False,
                            "syntax_error": "'[' was never closed",
                            "third_party_imports": [],
                        }
                    }
                },
            },
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )

    engineer = RecordingAgent("def repaired() -> int:\n    return 1")
    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry({"architect": RecordingAgent("ARCHITECTURE DOC"), "code_engineer": engineer, "code_reviewer": FailingAgent()}),
    )

    orchestrator.execute_workflow(project)

    review_task = require_task(project, "review")
    repair_task = require_task(project, "review__repair_1")
    assert review_task.status == TaskStatus.DONE.value
    assert review_task.output == "def repaired() -> int:\n    return 1"
    assert repair_task.status == TaskStatus.DONE.value
    assert repair_task.repair_origin_task_id == "review"
    assert engineer.last_context["repair_context"] == {
        "cycle": 1,
        "failure_category": FailureCategory.CODE_VALIDATION.value,
        "repair_owner": "code_engineer",
        "original_assigned_to": "code_reviewer",
    }
    assert engineer.last_context["existing_code"] == "def broken(:\n    pass"
    assert any(event["event"] == "task_repair_planned" for event in project.execution_events)
    assert any(event["event"] == "task_repair_created" for event in project.execution_events)


def test_execute_workflow_resume_failed_inserts_budget_decomposition_plan_before_code_repair(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write one Python module under 80 lines.",
            assigned_to="code_engineer",
            dependencies=["arch"],
            status=TaskStatus.FAILED.value,
            output="Generated code validation failed: syntax error '[' was never closed at line 2; output likely truncated at the completion token limit",
            last_error="Generated code validation failed: syntax error '[' was never closed at line 2; output likely truncated at the completion token limit",
            last_error_type="AgentExecutionError",
            last_error_category=FailureCategory.CODE_VALIDATION.value,
            output_payload={
                "summary": "broken code",
                "raw_content": "def risky():\n    values = [1, 2,\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def risky():\n    values = [1, 2,\n",
                    }
                ],
                "decisions": [],
                "metadata": {
                    "validation": {
                        "code_analysis": {
                            "syntax_ok": False,
                            "syntax_error": "'[' was never closed at line 2",
                            "third_party_imports": [],
                            "line_count": 82,
                            "line_budget": 80,
                        },
                        "completion_diagnostics": {
                            "requested_max_tokens": 900,
                            "output_tokens": 900,
                            "finish_reason": "length",
                            "stop_reason": None,
                            "done_reason": None,
                            "hit_token_limit": True,
                            "likely_truncated": True,
                        },
                    }
                },
            },
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )

    architect = RecordingAgent(
        "- Keep only the public risky() surface.\n- Remove optional helpers and comments.\n- Write the importable module top-down so required behavior appears first."
    )
    engineer = RecordingAgent("def risky() -> int:\n    return 1")
    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": architect,
                "code_engineer": engineer,
            }
        ),
    )

    orchestrator.execute_workflow(project)

    plan_task = require_task(project, "code__repair_1__budget_plan")
    repair_task = require_task(project, "code__repair_1")
    code_task = require_task(project, "code")
    assert plan_task.status == TaskStatus.DONE.value
    assert repair_task.status == TaskStatus.DONE.value
    assert code_task.status == TaskStatus.DONE.value
    assert "code__repair_1__budget_plan" in repair_task.dependencies
    assert engineer.last_context["budget_decomposition_brief"].startswith("- Keep only the public risky() surface.")
    assert "Budget decomposition brief:" in engineer.last_description
    assert any(event["event"] == "task_budget_decomposition_created" for event in project.execution_events)


def test_execute_workflow_resume_failed_hard_stops_for_non_repairable_failed_tasks(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            status=TaskStatus.FAILED.value,
            output="sandbox policy blocked filesystem write outside sandbox root",
            last_error="sandbox policy blocked filesystem write outside sandbox root",
            last_error_type="RuntimeError",
            last_error_category=FailureCategory.SANDBOX_SECURITY_VIOLATION.value,
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": RecordingAgent("TESTS")}))

    with pytest.raises(AgentExecutionError, match="cannot resume automatically"):
        orchestrator.execute_workflow(project)

    assert project.phase == "failed"
    assert project.failure_category == FailureCategory.SANDBOX_SECURITY_VIOLATION.value
    policy_event = next(event for event in project.execution_events if event["event"] == "policy_enforcement")
    workflow_event = next(event for event in project.execution_events if event["event"] == "workflow_finished")
    assert policy_event["task_id"] == "tests"
    assert policy_event["details"]["policy_area"] == "sandbox"
    assert policy_event["details"]["source_event"] == "workflow_finished"
    assert policy_event["details"]["failure_category"] == FailureCategory.SANDBOX_SECURITY_VIOLATION.value
    assert policy_event["details"]["message"] == "sandbox policy blocked filesystem write outside sandbox root"
    assert policy_event["details"]["error_type"] == "RuntimeError"
    assert workflow_event["details"]["failure_task_id"] == "tests"
    assert workflow_event["details"]["failure_message"] == "sandbox policy blocked filesystem write outside sandbox root"
    assert workflow_event["details"]["failure_error_type"] == "RuntimeError"
    assert project.get_task("tests__repair_1") is None
    assert project.repair_cycle_count == 0


def test_execute_workflow_fails_fast_for_provider_transient_without_repair_task(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    class ProviderFlakyAgent:
        def run(self, task_description: str, context: dict) -> str:
            raise ProviderTransientError("provider temporarily unavailable")

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": ProviderFlakyAgent()}))

    with pytest.raises(ProviderTransientError, match="provider temporarily unavailable"):
        orchestrator.execute_workflow(project)

    assert project.phase == "failed"
    assert project.failure_category == FailureCategory.PROVIDER_TRANSIENT.value
    assert project.get_task("arch__repair_1") is None


def test_execute_workflow_preserves_base_agent_provider_transients_without_repair_task(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
        )
    )

    class TimeoutProvider:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []
            self.health_calls = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls.append((system_prompt, user_message))
            raise ProviderTransientError("provider temporarily unavailable")

        def get_last_call_metadata(self) -> None:
            return None

        def health_check(self) -> dict[str, object]:
            self.health_calls += 1
            return {
                "provider": "openai",
                "model": "gpt-4o",
                "status": "healthy",
                "active_check": False,
                "retryable": False,
            }

    class ProviderBackedQATester(BaseAgent):
        output_artifact_type = ArtifactType.TEST

        def __init__(self, provider: TimeoutProvider, runtime_config: KYCortexConfig):
            super().__init__("QATester", "Quality Assurance & Testing", runtime_config)
            self._provider = cast(Any, provider)

        def run(self, task_description: str, context: dict[str, Any]) -> str:
            return self.chat("system", task_description)

    provider = TimeoutProvider()
    agent = ProviderBackedQATester(provider, config)
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": agent}))

    with pytest.raises(ProviderTransientError, match="QATester: provider temporarily unavailable"):
        orchestrator.execute_workflow(project)

    assert project.phase == "failed"
    assert project.failure_category == FailureCategory.PROVIDER_TRANSIENT.value
    assert project.get_task("tests__repair_1") is None


def test_execute_workflow_can_chain_new_failed_task_within_active_repair_cycle(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.FAILED.value,
            output="boom-1",
            last_error="boom-1",
            last_error_type="RuntimeError",
            last_error_category=FailureCategory.TASK_EXECUTION.value,
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            dependencies=["arch"],
        )
    )

    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": RecordingAgent("ARCHITECTURE DOC"),
                "qa_tester": AgentExecutionFlakyAgent(
                    failures_before_success=1,
                    success_response="def test_ok():\n    assert True",
                    error_message="generated tests failed",
                ),
            }
        ),
    )

    orchestrator.execute_workflow(project)

    assert project.repair_cycle_count == 1
    arch_task = require_task(project, "arch")
    arch_repair_task = require_task(project, "arch__repair_1")
    tests_task = require_task(project, "tests")
    tests_repair_task = require_task(project, "tests__repair_1")
    assert arch_task.status == TaskStatus.DONE.value
    assert arch_repair_task.status == TaskStatus.DONE.value
    assert tests_task.status == TaskStatus.DONE.value
    assert tests_repair_task.status == TaskStatus.DONE.value
    assert any(event["event"] == "task_repair_created" and event["task_id"] == "tests__repair_1" for event in project.execution_events)
    assert any(event["event"] == "task_repair_chained" and event["task_id"] == "tests" for event in project.execution_events)


def test_execute_workflow_does_not_spawn_duplicate_repair_task_when_pending_child_exists(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.FAILED.value,
            output="boom",
            attempts=1,
        )
    )
    project.add_task(
        Task(
            id="arch__repair_1",
            title="Repair Architecture",
            description="Design the architecture",
            assigned_to="architect",
            dependencies=[],
            repair_context={"cycle": 1, "instruction": "Repair the architecture."},
            repair_origin_task_id="arch",
            repair_attempt=1,
            status=TaskStatus.PENDING.value,
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": RecordingAgent("ARCHITECTURE DOC")}))

    orchestrator.execute_workflow(project)

    assert len([task for task in project.tasks if task.repair_origin_task_id == "arch"]) == 1
    arch_task = require_task(project, "arch")
    assert arch_task.status == TaskStatus.DONE.value


def test_build_agent_input_includes_test_repair_context(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config, registry=AgentRegistry({"qa_tester": RecordingAgent("TESTS")}))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def add(a, b):\n    return a + b",
            output_payload={
                "summary": "def add(a, b):",
                "raw_content": "def add(a, b):\n    return a + b",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def add(a, b):\n    return a + b",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": "Generated test validation:\n- Imported module symbols: add\n- Verdict: FAIL",
                "helper_surface_usages": ["RiskScoringService (line 33)"],
                "helper_surface_symbols": ["RiskScoringService"],
                "failed_output": "from code_implementation import missing_symbol",
                "failed_artifact_content": "from code_implementation import missing_symbol",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "Repair objective:" in agent_input.task_description
    assert "Previous failure category: test_validation" in agent_input.task_description
    assert agent_input.context["repair_context"] == {
        "cycle": 1,
        "failure_category": FailureCategory.TEST_VALIDATION.value,
        "repair_owner": "qa_tester",
    }
    assert agent_input.context["existing_tests"] == "from code_implementation import missing_symbol"
    assert agent_input.context["test_validation_summary"].endswith("Verdict: FAIL")
    assert agent_input.context["repair_helper_surface_usages"] == ["RiskScoringService (line 33)"]
    assert agent_input.context["repair_helper_surface_symbols"] == ["RiskScoringService"]


def test_build_agent_input_adds_targeted_test_repair_priorities(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def add(a, b):\n    return a + b",
            output_payload={
                "summary": "def add(a, b):",
                "raw_content": "def add(a, b):\n    return a + b",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def add(a, b):\n    return a + b",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Line count: 206/150\n"
                    "- Top-level test functions: 14/7 max\n"
                    "- Fixture count: 4/3\n"
                    "- Helper surface usages: RiskScoringService (line 33)\n"
                    "- Unknown module symbols: batch_processing\n"
                        "- Constructor arity mismatches: Validator expects 1 args but test uses 0 at line 12\n"
                    "- Undefined local names: RiskScoringService (line 33)\n"
                    "- Non-batch sequence calls: score_request does not accept batch/list inputs at line 46\n"
                    "- Reserved fixture names: request (line 5)\n"
                    "- Pytest execution: FAIL\n"
                    "- Verdict: FAIL"
                ),
                "helper_surface_usages": ["RiskScoringService (line 33)"],
                "helper_surface_symbols": ["RiskScoringService"],
                "failed_output": "from code_implementation import batch_processing",
                "failed_artifact_content": "from code_implementation import batch_processing",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "Repair priorities:" in agent_input.task_description
    assert "treat the current implementation artifact and api contract as fixed ground truth" in agent_input.task_description.lower()
    assert "Do not invent replacement classes, functions, validators, return-wrapper types" in agent_input.task_description
    assert "Delete every import, fixture, helper variable, and top-level test that references these flagged helper surfaces: RiskScoringService." in agent_input.task_description
    assert "do not reintroduce RiskScoringService anywhere in the rewritten file" in agent_input.task_description
    assert "Do not replace one guessed helper with another guessed helper during repair" in agent_input.task_description
    assert "Reduce scope aggressively: target 3 to 4 top-level tests" in agent_input.task_description
    assert "Count top-level tests and total lines before finalizing" in agent_input.task_description
    assert "Target clear headroom below the line ceiling instead of landing on the boundary" in agent_input.task_description
    assert "Drop validator, scorer, serialization, logger, and other helper-level tests" in agent_input.task_description
    assert "A suite over the hard cap is invalid even when pytest passes" in agent_input.task_description
    assert "delete standalone validator, scorer, and audit helper tests before keeping any extra coverage" in agent_input.task_description
    assert "Use only documented module symbols" in agent_input.task_description
    assert "Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols" in agent_input.task_description
    assert "keep imports limited to that facade and directly exchanged domain models" in agent_input.task_description
    assert "If you use isinstance or another exact type assertion against a production class, import that class explicitly" in agent_input.task_description
    assert "remove guessed helper wiring and rebuild the suite around the smallest documented public service or function surface" in agent_input.task_description
    assert "Instantiate typed request or result models with the exact field names and full constructor arity listed in the API contract" in agent_input.task_description
    assert "Pass every documented constructor field explicitly, including trailing defaulted fields" in agent_input.task_description
    assert "Keep scalar functions scalar" in agent_input.task_description
    assert "Never define a custom fixture named request." in agent_input.task_description
    assert "preserve its valid imports, constructor shapes, fixture payload structure, and scenario skeleton" in agent_input.task_description
    assert "prefer stable invariants and type or shape assertions" in agent_input.task_description


def test_build_agent_input_adds_runtime_only_test_repair_priorities(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def add(a, b):\n    return a + b",
            output_payload={
                "summary": "def add(a, b):",
                "raw_content": "def add(a, b):\n    return a + b",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def add(a, b):\n    return a + b",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Imported module symbols: add\n"
                    "- Unknown module symbols: none\n"
                    "- Constructor arity mismatches: none\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_add - AssertionError: assert add(1, 2) == 4\n"
                    "- Pytest summary: 1 failed, 1 passed in 0.01s\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "from code_implementation import add\n\ndef test_add():\n    assert add(1, 2) == 4",
                "failed_artifact_content": "from code_implementation import add\n\ndef test_add():\n    assert add(1, 2) == 4",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "Repair priorities:" in agent_input.task_description
    assert "treat the current implementation artifact and api contract as fixed ground truth" in agent_input.task_description.lower()
    assert "Do not invent replacement classes, functions, validators, return-wrapper types" in agent_input.task_description
    assert "preserve its valid imports, constructor shapes, fixture payload structure, and scenario skeleton" in agent_input.task_description
    assert "rewrite that assertion to a contract-backed invariant instead of forcing a guessed business rule" in agent_input.task_description
    assert "Do not assume empty strings, placeholder IDs, or domain keywords are invalid" in agent_input.task_description
    assert "If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict)" in agent_input.task_description
    assert "remove exact score totals and threshold-triggered boolean assertions" in agent_input.task_description
    assert "Do not infer derived statuses, labels, or report counters from suggestive field names or keywords alone" in agent_input.task_description


def test_build_agent_input_adds_audit_log_runtime_repair_priorities(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "from pathlib import Path\n\n"
                "def validate_request(request):\n"
                "    return bool(request)\n\n"
                "def score_request(request):\n"
                "    return {'request_id': 1, 'score': 0.5}\n\n"
                "def log_audit(message):\n"
                "    Path('audit.log').write_text(message + '\\n', encoding='utf-8')\n"
            ),
            output_payload={
                "summary": "def validate_request(request):",
                "raw_content": (
                    "from pathlib import Path\n\n"
                    "def validate_request(request):\n"
                    "    return bool(request)\n\n"
                    "def score_request(request):\n"
                    "    return {'request_id': 1, 'score': 0.5}\n\n"
                    "def log_audit(message):\n"
                    "    Path('audit.log').write_text(message + '\\n', encoding='utf-8')\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "from pathlib import Path\n\n"
                            "def validate_request(request):\n"
                            "    return bool(request)\n\n"
                            "def score_request(request):\n"
                            "    return {'request_id': 1, 'score': 0.5}\n\n"
                            "def log_audit(message):\n"
                            "    Path('audit.log').write_text(message + '\\n', encoding='utf-8')\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Imported module symbols: validate_request, score_request, log_audit\n"
                    "- Unknown module symbols: none\n"
                    "- Constructor arity mismatches: none\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_log_audit - AssertionError: assert audit_path.read_text(encoding='utf-8') == 'entry'; FAILED tests_tests.py::test_happy_path - AssertionError: assert 1 == 3\n"
                    "- Pytest summary: 1 failed, 3 passed in 0.01s\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": (
                    "from code_implementation import log_audit\n\n"
                    "def test_log_audit(tmp_path):\n"
                    "    log_audit('entry')\n"
                    "    assert (tmp_path / 'audit.log').read_text(encoding='utf-8') == 'entry'\n"
                ),
                "failed_artifact_content": (
                    "from code_implementation import log_audit\n\n"
                    "def test_log_audit(tmp_path):\n"
                    "    log_audit('entry')\n"
                    "    assert (tmp_path / 'audit.log').read_text(encoding='utf-8') == 'entry'\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "standalone audit or logging helper test" in agent_input.task_description
    assert "Do not compare full audit or log file contents by exact string equality" in agent_input.task_description
    assert "collapse the suite to exactly three tests" in agent_input.task_description
    assert "derive the exact expected score from only the branches exercised by the chosen input" in agent_input.task_description
    assert "should assert 1, not 3" in agent_input.task_description


def test_build_agent_input_adds_batch_audit_runtime_repair_priorities(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "from dataclasses import dataclass\n"
                "from typing import Any\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    id: str\n"
                "    data: Any\n\n"
                "@dataclass\n"
                "class AuditLog:\n"
                "    action: str\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self.audit_logs = []\n\n"
                "    def intake_request(self, request):\n"
                "        return request\n\n"
                "    def process_batch(self, requests):\n"
                "        return requests\n"
            ),
            output_payload={
                "summary": "class ComplianceIntakeService:",
                "raw_content": (
                    "from dataclasses import dataclass\n"
                    "from typing import Any\n\n"
                    "@dataclass\n"
                    "class ComplianceRequest:\n"
                    "    id: str\n"
                    "    data: Any\n\n"
                    "@dataclass\n"
                    "class AuditLog:\n"
                    "    action: str\n\n"
                    "class ComplianceIntakeService:\n"
                    "    def __init__(self):\n"
                    "        self.audit_logs = []\n\n"
                    "    def intake_request(self, request):\n"
                    "        return request\n\n"
                    "    def process_batch(self, requests):\n"
                    "        return requests\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "from dataclasses import dataclass\n"
                            "from typing import Any\n\n"
                            "@dataclass\n"
                            "class ComplianceRequest:\n"
                            "    id: str\n"
                            "    data: Any\n\n"
                            "@dataclass\n"
                            "class AuditLog:\n"
                            "    action: str\n\n"
                            "class ComplianceIntakeService:\n"
                            "    def __init__(self):\n"
                            "        self.audit_logs = []\n\n"
                            "    def intake_request(self, request):\n"
                            "        return request\n\n"
                            "    def process_batch(self, requests):\n"
                            "        return requests\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Imported module symbols: AuditLog, ComplianceIntakeService, ComplianceRequest\n"
                    "- Unknown module symbols: none\n"
                    "- Constructor arity mismatches: none\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_process_batch_with_failure - AssertionError: assert 2 == 3\n"
                    "- Pytest summary: 1 failed, 3 passed in 0.01s\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": (
                    "from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
                    "def test_process_batch_with_failure():\n"
                    "    service = ComplianceIntakeService()\n"
                    "    requests = [\n"
                    "        ComplianceRequest(id='1', data={'ok': True}),\n"
                    "        ComplianceRequest(id='2', data=None),\n"
                    "    ]\n"
                    "    service.process_batch(requests)\n"
                    "    assert len(service.audit_logs) == 2\n"
                ),
                "failed_artifact_content": (
                    "from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
                    "def test_process_batch_with_failure():\n"
                    "    service = ComplianceIntakeService()\n"
                    "    requests = [\n"
                    "        ComplianceRequest(id='1', data={'ok': True}),\n"
                    "        ComplianceRequest(id='2', data=None),\n"
                    "    ]\n"
                    "    service.process_batch(requests)\n"
                    "    assert len(service.audit_logs) == 2\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "Add logs from both inner failing operations and outer batch error handlers" in agent_input.task_description
    assert "one invalid item can emit two failure-related audit records" in agent_input.task_description
    assert "before asserting an exact audit total" in agent_input.task_description
    assert "a two-item valid batch can emit 5 audit logs, not 3" in agent_input.task_description
    assert "the suite guessed internal logging" in agent_input.task_description
    assert "Delete that exact len(service.audit_logs) == N assertion unless the contract explicitly enumerates every emitted batch log" in agent_input.task_description
    assert "Replace brittle batch audit counts with stable checks such as result length, required audit actions, a terminal batch marker, or monotonic audit growth" in agent_input.task_description
    assert "stop asserting an exact batch audit length and switch to stable checks" in agent_input.task_description


def test_build_agent_input_adds_weighted_score_and_guarded_nested_field_repair_priorities(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "from typing import Any\n\n"
                "def calculate_risk_score(request_data: dict[str, Any]) -> float:\n"
                "    score = 0.0\n"
                "    if 'risk_factor' in request_data and isinstance(request_data['risk_factor'], (int, float)):\n"
                "        score += request_data['risk_factor'] * 0.5\n"
                "    if 'compliance_history' in request_data and isinstance(request_data['compliance_history'], (int, float)):\n"
                "        score += (1 - request_data['compliance_history']) * 0.5\n"
                "    return score\n"
            ),
            output_payload={
                "summary": "def calculate_risk_score(request_data):",
                "raw_content": (
                    "from typing import Any\n\n"
                    "def calculate_risk_score(request_data: dict[str, Any]) -> float:\n"
                    "    score = 0.0\n"
                    "    if 'risk_factor' in request_data and isinstance(request_data['risk_factor'], (int, float)):\n"
                    "        score += request_data['risk_factor'] * 0.5\n"
                    "    if 'compliance_history' in request_data and isinstance(request_data['compliance_history'], (int, float)):\n"
                    "        score += (1 - request_data['compliance_history']) * 0.5\n"
                    "    return score\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "from typing import Any\n\n"
                            "def calculate_risk_score(request_data: dict[str, Any]) -> float:\n"
                            "    score = 0.0\n"
                            "    if 'risk_factor' in request_data and isinstance(request_data['risk_factor'], (int, float)):\n"
                            "        score += request_data['risk_factor'] * 0.5\n"
                            "    if 'compliance_history' in request_data and isinstance(request_data['compliance_history'], (int, float)):\n"
                            "        score += (1 - request_data['compliance_history']) * 0.5\n"
                            "    return score\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Imported module symbols: calculate_risk_score\n"
                    "- Unknown module symbols: none\n"
                    "- Constructor arity mismatches: none\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_score - AssertionError: assert 1.45 == 1.25; FAILED tests_tests.py::test_invalid_nested_value - Failed: DID NOT RAISE <class 'TypeError'>\n"
                    "- Pytest summary: 2 failed, 1 passed in 0.01s\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": (
                    "from code_implementation import calculate_risk_score\n\n"
                    "def test_score():\n"
                    "    assert calculate_risk_score({'risk_factor': 2, 'compliance_history': 0.1}) == 1.25\n\n"
                    "def test_invalid_nested_value():\n"
                    "    with pytest.raises(TypeError):\n"
                    "        calculate_risk_score({'risk_factor': 'invalid', 'compliance_history': 0.1})\n"
                ),
                "failed_artifact_content": (
                    "from code_implementation import calculate_risk_score\n\n"
                    "def test_score():\n"
                    "    assert calculate_risk_score({'risk_factor': 2, 'compliance_history': 0.1}) == 1.25\n\n"
                    "def test_invalid_nested_value():\n"
                    "    with pytest.raises(TypeError):\n"
                    "        calculate_risk_score({'risk_factor': 'invalid', 'compliance_history': 0.1})\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25" in agent_input.task_description
    assert "a wrong nested field type is ignored rather than raising" in agent_input.task_description


def test_build_agent_input_adds_required_string_modulo_repair_priorities(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "from dataclasses import dataclass\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    requester_name: str\n"
                "    request_details: str\n\n"
                "class ComplianceIntakeService:\n"
                "    def validate_request(self, request: ComplianceRequest) -> None:\n"
                "        if not request.request_id or not request.requester_name or not request.request_details:\n"
                "            raise ValueError('All fields must be filled in.')\n\n"
                "    def score_risk(self, request: ComplianceRequest) -> int:\n"
                "        self.validate_request(request)\n"
                "        return len(request.request_details) % 10\n"
            ),
            output_payload={
                "summary": "class ComplianceIntakeService:",
                "raw_content": (
                    "from dataclasses import dataclass\n\n"
                    "@dataclass\n"
                    "class ComplianceRequest:\n"
                    "    request_id: str\n"
                    "    requester_name: str\n"
                    "    request_details: str\n\n"
                    "class ComplianceIntakeService:\n"
                    "    def validate_request(self, request: ComplianceRequest) -> None:\n"
                    "        if not request.request_id or not request.requester_name or not request.request_details:\n"
                    "            raise ValueError('All fields must be filled in.')\n\n"
                    "    def score_risk(self, request: ComplianceRequest) -> int:\n"
                    "        self.validate_request(request)\n"
                    "        return len(request.request_details) % 10\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "from dataclasses import dataclass\n\n"
                            "@dataclass\n"
                            "class ComplianceRequest:\n"
                            "    request_id: str\n"
                            "    requester_name: str\n"
                            "    request_details: str\n\n"
                            "class ComplianceIntakeService:\n"
                            "    def validate_request(self, request: ComplianceRequest) -> None:\n"
                            "        if not request.request_id or not request.requester_name or not request.request_details:\n"
                            "            raise ValueError('All fields must be filled in.')\n\n"
                            "    def score_risk(self, request: ComplianceRequest) -> int:\n"
                            "        self.validate_request(request)\n"
                            "        return len(request.request_details) % 10\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Imported module symbols: ComplianceIntakeService, ComplianceRequest\n"
                    "- Unknown module symbols: none\n"
                    "- Constructor arity mismatches: none\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_score_risk_with_empty_details - ValueError: All fields must be filled in.\n"
                    "- Pytest summary: 1 failed, 2 passed in 0.01s\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": (
                    "from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
                    "def test_score_risk_with_empty_details():\n"
                    "    service = ComplianceIntakeService()\n"
                    "    empty_request = ComplianceRequest(request_id='req3', requester_name='Charlie', request_details='')\n"
                    "    assert service.score_risk(empty_request) == 0\n"
                ),
                "failed_artifact_content": (
                    "from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
                    "def test_score_risk_with_empty_details():\n"
                    "    service = ComplianceIntakeService()\n"
                    "    empty_request = ComplianceRequest(request_id='req3', requester_name='Charlie', request_details='')\n"
                    "    assert service.score_risk(empty_request) == 0\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "do not preserve that empty string just to force a zero score" in agent_input.task_description
    assert 'use "xxxxxxxxxx" rather than ""' in agent_input.task_description


def test_build_agent_input_preserves_valid_import_surface_on_pytest_only_repair(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "from dataclasses import dataclass\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: str\n\n"
                "@dataclass\n"
                "class AuditLog:\n"
                "    action: str\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self.batch = []\n\n"
                "    def handle_request(self, request: ComplianceRequest) -> None:\n"
                "        self.batch.append(request)\n"
            ),
            output_payload={
                "summary": "class ComplianceIntakeService:",
                "raw_content": (
                    "from dataclasses import dataclass\n\n"
                    "@dataclass\n"
                    "class ComplianceRequest:\n"
                    "    request_id: str\n"
                    "    request_type: str\n"
                    "    details: str\n\n"
                    "@dataclass\n"
                    "class AuditLog:\n"
                    "    action: str\n\n"
                    "class ComplianceIntakeService:\n"
                    "    def __init__(self):\n"
                    "        self.batch = []\n\n"
                    "    def handle_request(self, request: ComplianceRequest) -> None:\n"
                    "        self.batch.append(request)\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "from dataclasses import dataclass\n\n"
                            "@dataclass\n"
                            "class ComplianceRequest:\n"
                            "    request_id: str\n"
                            "    request_type: str\n"
                            "    details: str\n\n"
                            "@dataclass\n"
                            "class AuditLog:\n"
                            "    action: str\n\n"
                            "class ComplianceIntakeService:\n"
                            "    def __init__(self):\n"
                            "        self.batch = []\n\n"
                            "    def handle_request(self, request: ComplianceRequest) -> None:\n"
                            "        self.batch.append(request)\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Imported module symbols: AuditLog, ComplianceIntakeService, ComplianceRequest\n"
                    "- Unknown module symbols: none\n"
                    "- Invalid member references: none\n"
                    "- Constructor arity mismatches: none\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_handle_request_invalid - Failed: DID NOT RAISE <class 'ValueError'>\n"
                    "- Pytest summary: 1 failed, 2 passed in 0.01s\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": (
                    "import pytest\n"
                    "from code_implementation import ComplianceRequest, AuditLog, ComplianceIntakeService\n\n"
                    "def test_handle_request_invalid():\n"
                    "    service = ComplianceIntakeService()\n"
                    "    request = ComplianceRequest(request_id='', request_type='TypeA', details='Details of the request')\n"
                    "    with pytest.raises(ValueError):\n"
                    "        service.handle_request(request)\n"
                ),
                "failed_artifact_content": (
                    "import pytest\n"
                    "from code_implementation import ComplianceRequest, AuditLog, ComplianceIntakeService\n\n"
                    "def test_handle_request_invalid():\n"
                    "    service = ComplianceIntakeService()\n"
                    "    request = ComplianceRequest(request_id='', request_type='TypeA', details='Details of the request')\n"
                    "    with pytest.raises(ValueError):\n"
                    "        service.handle_request(request)\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "The previous suite already used a statically valid production import surface: AuditLog, ComplianceIntakeService, ComplianceRequest." in agent_input.task_description
    assert "If the valid suite imported ComplianceIntakeService, do not replace it with ComplianceService" in agent_input.task_description
    assert "The previous statically valid suite already exercised these production member calls: ComplianceIntakeService.handle_request." in agent_input.task_description
    assert "Do not replace a previously valid member call with a guessed workflow alias such as process_request or process_batch" in agent_input.task_description
    assert "When the previous suite had no constructor arity mismatches, keep the same request and result constructor field names and arity during repair" in agent_input.task_description
    assert "The previous statically valid suite already instantiated production models with these keyword fields: ComplianceRequest(request_id, request_type, details)." in agent_input.task_description
    assert "Do not rewrite a previously valid request model from fields such as request_id, request_type, details to guessed placeholders such as id, data, timestamp, or status" in agent_input.task_description


def test_build_agent_input_moves_invalid_required_field_case_off_scoring_surface(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output=(
                "from dataclasses import dataclass\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    details: str\n\n"
                "class ComplianceIntakeService:\n"
                "    def intake_request(self, request: ComplianceRequest) -> None:\n"
                "        self.validate_request(request)\n\n"
                "    def validate_request(self, request: ComplianceRequest) -> None:\n"
                "        if not request.request_id or not request.details:\n"
                "            raise ValueError('All fields must be filled in.')\n\n"
                "    def score_request(self, request: ComplianceRequest) -> int:\n"
                "        return len(request.details) % 10\n"
            ),
            output_payload={
                "summary": "class ComplianceIntakeService:",
                "raw_content": (
                    "from dataclasses import dataclass\n\n"
                    "@dataclass\n"
                    "class ComplianceRequest:\n"
                    "    request_id: str\n"
                    "    details: str\n\n"
                    "class ComplianceIntakeService:\n"
                    "    def intake_request(self, request: ComplianceRequest) -> None:\n"
                    "        self.validate_request(request)\n\n"
                    "    def validate_request(self, request: ComplianceRequest) -> None:\n"
                    "        if not request.request_id or not request.details:\n"
                    "            raise ValueError('All fields must be filled in.')\n\n"
                    "    def score_request(self, request: ComplianceRequest) -> int:\n"
                    "        return len(request.details) % 10\n"
                ),
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": (
                            "from dataclasses import dataclass\n\n"
                            "@dataclass\n"
                            "class ComplianceRequest:\n"
                            "    request_id: str\n"
                            "    details: str\n\n"
                            "class ComplianceIntakeService:\n"
                            "    def intake_request(self, request: ComplianceRequest) -> None:\n"
                            "        self.validate_request(request)\n\n"
                            "    def validate_request(self, request: ComplianceRequest) -> None:\n"
                            "        if not request.request_id or not request.details:\n"
                            "            raise ValueError('All fields must be filled in.')\n\n"
                            "    def score_request(self, request: ComplianceRequest) -> int:\n"
                            "        return len(request.details) % 10\n"
                        ),
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Imported module symbols: ComplianceIntakeService, ComplianceRequest\n"
                    "- Unknown module symbols: none\n"
                    "- Constructor arity mismatches: none\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_score_request_with_invalid_details - ValueError: All fields must be filled in.\n"
                    "- Pytest summary: 1 failed, 2 passed in 0.01s\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": (
                    "from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
                    "def test_score_request_with_invalid_details():\n"
                    "    service = ComplianceIntakeService()\n"
                    "    request = ComplianceRequest(request_id='1', details='')\n"
                    "    service.intake_request(request)\n"
                    "    with pytest.raises(ValueError):\n"
                    "        service.score_request(request)\n"
                ),
                "failed_artifact_content": (
                    "from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
                    "def test_score_request_with_invalid_details():\n"
                    "    service = ComplianceIntakeService()\n"
                    "    request = ComplianceRequest(request_id='1', details='')\n"
                    "    service.intake_request(request)\n"
                    "    with pytest.raises(ValueError):\n"
                    "        service.score_request(request)\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "do not keep a separate invalid-scoring test that first calls intake_request" in agent_input.task_description
    assert "Move that failure case to intake_request or validate_request" in agent_input.task_description


def test_build_agent_input_removes_copied_implementation_from_tests(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="from dataclasses import dataclass\n\n@dataclass\nclass Demo:\n    value: int\n",
            output_payload={
                "summary": "class Demo:",
                "raw_content": "from dataclasses import dataclass\n\n@dataclass\nclass Demo:\n    value: int\n",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "from dataclasses import dataclass\n\n@dataclass\nclass Demo:\n    value: int\n",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Line count: 217/150\n"
                    "- Top-level test functions: 12/7 max\n"
                    "- Imported module symbols: Demo\n"
                    "- Imported entrypoint symbols: cli_demo\n"
                    "- Unsafe entrypoint calls: cli_demo() (line 6)\n"
                    "- Undefined local names: argparse (line 46)\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: NameError: name 'dataclass' is not defined\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: line count 217 exceeds maximum 150; imported entrypoint symbols: cli_demo; unsafe entrypoint calls: cli_demo() (line 6); undefined local names: argparse (line 46); pytest failed: NameError: name 'dataclass' is not defined",
                "failed_artifact_content": (
                    "import pytest\n"
                    "from code_implementation import cli_demo\n\n"
                    "@dataclass\n"
                    "class Demo:\n"
                    "    value: int\n\n"
                    "def test_main():\n"
                    "    parser = argparse.ArgumentParser()\n"
                    "    cli_demo()\n\n"
                    "def test_all_tests():\n"
                    "    test_main()\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "Delete any copied implementation blocks from the pytest module" in agent_input.task_description
    assert "`test_main`, `test_all_tests`" in agent_input.task_description
    assert "Do not import or execute entrypoints in tests" in agent_input.task_description


def test_build_agent_input_adds_did_not_raise_and_numeric_type_repair_priorities(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Constructor arity mismatches: ComplianceRequest expects 4 args but test uses 2 at line 6\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest summary: 3 failed, 2 passed in 0.21s\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_intake_request_validation_failure - Failed: DID NOT RAISE <class 'ValueError'>; FAILED tests_tests.py::test_score_risk_happy_path - AssertionError: assert False\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: constructor arity mismatches: ComplianceRequest expects 4 args but test uses 2; pytest failed: DID NOT RAISE and assert False",
                "failed_artifact_content": (
                    "import pytest\n"
                    "from code_implementation import ComplianceRequest\n\n"
                    "def test_intake_request_validation_failure():\n"
                    "    request = ComplianceRequest(id='', data={'field': 'value'})\n"
                    "    with pytest.raises(ValueError):\n"
                    "        raise AssertionError()\n\n"
                    "def test_score_risk_happy_path():\n"
                    "    assert False\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "do not use empty-string ids or still-valid dict payloads as the failure input" in agent_input.task_description
    assert "ComplianceData(id=\"1\", data={\"key\": \"wrong_value\"}) is still valid input and should be asserted as a non-compliant result" in agent_input.task_description
    assert "empty dict is still a same-type placeholder and may pass when validation only checks dict type" in agent_input.task_description
    assert "do not assume a wrong nested value type makes the request invalid" in agent_input.task_description
    assert "choose an input that validate_request rejects before scoring runs" in agent_input.task_description
    assert "Do not require an exact runtime numeric type such as float" in agent_input.task_description
    assert "Do not rely on dataclass defaults just because omission would run" in agent_input.task_description
    assert "ComplianceRequest(id=\"1\", data={\"name\": \"John Doe\", \"amount\": 1000}, timestamp=1.0, status=\"pending\")" in agent_input.task_description
    assert "rewrite every constructor call for that type in the file until the mismatch list is empty" in agent_input.task_description


def test_build_agent_input_adds_assert_not_true_validation_repair_priorities(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest summary: 1 failed, 3 passed in 0.10s\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_validate_request_failure - AssertionError: assert not True\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: pytest failed: AssertionError: assert not True",
                "failed_artifact_content": (
                    "from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
                    "def test_validate_request_failure():\n"
                    "    service = ComplianceIntakeService()\n"
                    "    request = ComplianceRequest(request_id='', data={'field': 'value'}, timestamp=1.0)\n"
                    "    assert not service.validate_request(request)\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "If pytest reports `assert not True` or another failed falsy expectation" in agent_input.task_description
    assert "Replace it with a clearly wrong top-level type or a truly missing required field" in agent_input.task_description
    assert "do not use request_id='' or another same-type placeholder as the failing input" in agent_input.task_description
    assert "do not use an empty dict or nested None values to fake a validation failure" in agent_input.task_description


def test_build_agent_input_adds_exact_numeric_mismatch_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest summary: 1 failed, 4 passed in 0.08s\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_assess_risk_happy_path - AssertionError: assert 0.4 == 0.1\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: pytest failed: 1 failed, 4 passed in 0.08s",
                "failed_artifact_content": (
                    "def test_assess_risk_happy_path():\n"
                    "    risk_score = service.assess_risk(request)\n"
                    "    assert risk_score.score == 0.1\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "do not preserve the stale guessed literal from the earlier suite" in agent_input.task_description
    assert "Either recompute the expected value from the current implementation formula" in agent_input.task_description
    assert "or replace the equality with a stable contract-backed invariant" in agent_input.task_description


def test_build_agent_input_adds_batch_same_shape_score_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest summary: 1 failed, 5 passed in 0.08s\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_process_batch - AssertionError: assert 3.0 == 4.5 | AssertionError: assert 3.0 == 4.5\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: pytest failed: 1 failed, 5 passed in 0.08s",
                "failed_artifact_content": (
                    "def test_process_batch():\n"
                    "    risk_scores = service.process_batch(requests_data)\n"
                    "    assert risk_scores[0].score == 3.0\n"
                    "    assert risk_scores[1].score == 4.5\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "Recompute each batch item's expected score independently" in agent_input.task_description
    assert "if the formula counts top-level keys or container size, same-shape inputs produce the same score" in agent_input.task_description


def test_build_agent_input_adds_string_length_sample_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest summary: 1 failed, 4 passed in 0.08s\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_assess_risk_happy_path - AssertionError: assert 0.8 == 0.2\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: pytest failed: 1 failed, 4 passed in 0.08s",
                "failed_artifact_content": (
                    "def test_assess_risk_happy_path():\n"
                    "    request = ComplianceRequest(id='1', data={'compliance_data': 'data'}, timestamp=datetime.now(), status='pending')\n"
                    "    risk_score = service.assess_risk(request)\n"
                    "    assert risk_score.score == 0.2\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "do not keep word-like sample strings such as data, valid_data, or data1 together with exact score equality" in agent_input.task_description
    assert "Replace them with repeated-character literals whose length is obvious" in agent_input.task_description


def test_build_agent_input_adds_boundary_label_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest summary: 1 failed, 4 passed in 0.08s\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_assess_risk - AssertionError: assert 'medium' == 'low'\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: pytest failed: 1 failed, 4 passed in 0.08s",
                "failed_artifact_content": (
                    "def test_assess_risk(service):\n"
                    "    request_data = {'name': 'John Doe', 'amount': 100}\n"
                    "    risk_score = service.assess_risk(service.intake_request(request_data))\n"
                    "    assert risk_score.level == 'low'\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "Do not keep boundary-like inputs for exact categorical labels" in agent_input.task_description
    assert "do not use amount=100 to assert an exact level" in agent_input.task_description
    assert "do not use a borderline count such as 2 to assert an exact low label" in agent_input.task_description


def test_build_agent_input_adds_payload_shape_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest summary: 1 failed, 4 passed in 0.08s\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_intake_request_happy_path - AssertionError: assert {'data': {'field1': 'value1'}, 'id': 'req1'} == {'field1': 'value1'}\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: pytest failed: 1 failed, 4 passed in 0.08s",
                "failed_artifact_content": (
                    "def test_intake_request_happy_path():\n"
                    "    request_data = {'id': 'req1', 'data': {'field1': 'value1'}}\n"
                    "    compliance_request = service.intake_request(request_data)\n"
                    "    assert compliance_request.data == {'field1': 'value1'}\n"
                    "    assert risk_score.score == 7.0\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "If a returned request object's `.data` field stores the full input payload" in agent_input.task_description
    assert "Assert the full stored payload shape or direct nested keys instead" in agent_input.task_description
    assert "the score is 0.0, not 7.0" in agent_input.task_description


def test_build_agent_input_adds_self_referential_constructor_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Constructor arity mismatches: none\n"
                    "- Undefined local names: request (line 6), request (line 14)\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest summary: FAILED tests_tests.py::test_happy_path - NameError: name 'request' is not defined\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: undefined local names: request (line 6), request (line 14)",
                "failed_artifact_content": (
                    "def test_happy_path():\n"
                    "    request = ComplianceRequest(id=\"1\", user_id=\"u1\", data={\"field\": 1}, timestamp=request.timestamp, status=\"pending\")\n"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "Do not satisfy explicit constructor fields by reading attributes from the object you are still constructing" in agent_input.task_description
    assert "timestamp=fixed_time instead of timestamp=request.timestamp" in agent_input.task_description


def test_build_agent_input_adds_pytest_import_test_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def add(a, b):\n    return a + b",
            output_payload={
                "summary": "def add(a, b):",
                "raw_content": "def add(a, b):\n    return a + b",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def add(a, b):\n    return a + b",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Undefined local names: pytest (line 18)\n"
                    "- Pytest execution: FAIL\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "def test_add():\n    with pytest.raises(ValueError):\n        raise ValueError",
                "failed_artifact_content": "def test_add():\n    with pytest.raises(ValueError):\n        raise ValueError",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "add `import pytest` explicitly at the top of the file" in agent_input.task_description
    assert "Do not leave `pytest.raises`, `pytest.mark`, or similar helpers unimported" in agent_input.task_description


def test_build_agent_input_adds_payload_contract_test_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="def get_logs(filters=None):\n    return []",
            output_payload={
                "summary": "def get_logs(filters=None):",
                "raw_content": "def get_logs(filters=None):\n    return []",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def get_logs(filters=None):\n    return []",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Payload contract violations: get_logs payload missing required fields: action, record_id at line 14\n"
                    "- Pytest execution: PASS\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "from code_implementation import get_logs",
                "failed_artifact_content": "from code_implementation import get_logs",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "provide every required field or omit that optional payload entirely" in agent_input.task_description


def test_build_agent_input_adds_datetime_import_test_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            output="from dataclasses import dataclass\nfrom datetime import datetime\n\n@dataclass\nclass ComplianceRequest:\n    request_id: str\n    timestamp: datetime",
            output_payload={
                "summary": "from dataclasses import dataclass",
                "raw_content": "from dataclasses import dataclass\nfrom datetime import datetime\n\n@dataclass\nclass ComplianceRequest:\n    request_id: str\n    timestamp: datetime",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "from dataclasses import dataclass\nfrom datetime import datetime\n\n@dataclass\nclass ComplianceRequest:\n    request_id: str\n    timestamp: datetime",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Undefined local names: datetime (line 6), datetime (line 12)\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_request - NameError: name 'datetime' is not defined\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": (
                    "from module_under_test import ComplianceRequest\n\n"
                    "def test_request():\n"
                    "    request = ComplianceRequest(request_id='req-1', timestamp=datetime.now())\n"
                    "    assert request.request_id == 'req-1'"
                ),
                "failed_artifact_content": (
                    "from module_under_test import ComplianceRequest\n\n"
                    "def test_request():\n"
                    "    request = ComplianceRequest(request_id='req-1', timestamp=datetime.now())\n"
                    "    assert request.request_id == 'req-1'"
                ),
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "If the rewritten suite keeps any `datetime.now()` call or other bare `datetime` reference" in agent_input.task_description
    assert "add `from datetime import datetime` or `import datetime` explicitly at the top of the file before finalizing" in agent_input.task_description
    assert "Otherwise remove every bare datetime reference and use a self-contained timestamp value" in agent_input.task_description


def test_build_agent_input_adds_truncation_test_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Repair tests",
            description="Write tests",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: no\n"
                    "- Completion diagnostics: likely truncated before the file ended cleanly, tokens=508/3200\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "from module_under_test import add\n\ndef test_add():\n    assert add(1, 2)",
                "failed_artifact_content": "from module_under_test import add\n\ndef test_add():\n    assert add(1, 2)",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "If completion diagnostics say the previous pytest output was likely truncated" in agent_input.task_description
    assert "discard the partial tail and rewrite the complete pytest module from the top" in agent_input.task_description
    assert "Rebuild the minimum contract-backed suite first" in agent_input.task_description
    assert "leave visible headroom below the line, test-count, and fixture budgets" in agent_input.task_description


def test_build_repair_context_extracts_helper_surface_names_from_test_validation(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="tests",
        title="Tests",
        description="Write tests",
        assigned_to="qa_tester",
        last_error_category=FailureCategory.TEST_VALIDATION.value,
        output="Generated test validation failed",
        output_payload={
            "summary": "tests",
            "raw_content": "from code_implementation import ComplianceService",
            "artifacts": [],
            "decisions": [],
            "metadata": {
                "validation": {
                    "test_analysis": {
                        "helper_surface_usages": [
                            "RiskScoringService (line 33)",
                            "ComplianceRepository",
                        ]
                    }
                }
            },
        },
    )

    repair_context = orchestrator._build_repair_context(task, {"cycle": 1})

    assert repair_context["helper_surface_usages"] == [
        "RiskScoringService (line 33)",
        "ComplianceRepository",
    ]
    assert repair_context["helper_surface_symbols"] == [
        "RiskScoringService",
        "ComplianceRepository",
    ]


def test_build_agent_input_adds_targeted_code_repair_priorities_for_pytest_assertions(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.CODE_VALIDATION.value,
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module so it satisfies the existing valid pytest suite and the documented contract without shifting the failure onto the tests.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_threshold - AssertionError: assert False is True\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "def score():\n    return False",
                "failed_artifact_content": "def score():\n    return False",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "code"), project)

    assert "Repair priorities:" in agent_input.task_description
    assert "Treat the listed pytest failures as exact behavior requirements" in agent_input.task_description
    assert "change the implementation until that exact expectation holds" in agent_input.task_description
    assert "Preserve the documented public API and repair the module behavior itself" in agent_input.task_description
    assert "Repair the implementation module itself. Return only importable module code" in agent_input.task_description
    assert "If the task requires a CLI or demo entrypoint, preserve or restore a minimal main()" in agent_input.task_description


def test_build_agent_input_adds_object_semantics_code_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.CODE_VALIDATION.value,
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module so it satisfies the existing valid pytest suite and the documented contract without shifting the failure onto the tests.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_request - TypeError: argument of type 'ComplianceRequest' is not iterable\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "def validate_request(request):\n    return 'data' in request",
                "failed_artifact_content": "def validate_request(request):\n    return 'data' in request",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "code"), project)

    assert "Repair priorities:" in agent_input.task_description
    assert "Treat the listed pytest failures as exact behavior requirements" in agent_input.task_description
    assert "Preserve the documented public API and repair the module behavior itself" in agent_input.task_description
    assert "Repair the implementation module itself. Return only importable module code" in agent_input.task_description
    assert "Keep data-model semantics consistent" in agent_input.task_description
    assert "validate and read them via attributes instead of mapping membership or subscripting" in agent_input.task_description


def test_build_agent_input_adds_dataclass_field_order_code_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.CODE_VALIDATION.value,
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module so it satisfies the existing valid pytest suite and the documented contract without shifting the failure onto the tests.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest summary: ERROR tests_tests.py - TypeError: non-default argument 'user' follows default...\n"
                    "- Pytest failure details: TypeError: non-default argument 'user' follows default argument\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "@dataclass\nclass ComplianceRequest:\n    status: str = 'pending'\n    user: str",
                "failed_artifact_content": "@dataclass\nclass ComplianceRequest:\n    status: str = 'pending'\n    user: str",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "code"), project)

    assert "reorder the fields so every required non-default field appears before any field with a default" in agent_input.task_description
    assert "while preserving the documented constructor contract" in agent_input.task_description
    assert "AuditLog(action, details, timestamp=field(default_factory=...))" in agent_input.task_description


def test_build_agent_input_adds_dataclass_field_import_code_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.CODE_VALIDATION.value,
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module so it becomes syntactically valid and internally consistent.",
                "validation_summary": (
                    "Generated code validation:\n"
                    "- Syntax OK: yes\n"
                    "- Module import: FAIL\n"
                    "- Import summary: NameError: name 'field' is not defined\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "from dataclasses import dataclass\n\n@dataclass\nclass Demo:\n    values: list[int] = field(default_factory=list)",
                "failed_artifact_content": "from dataclasses import dataclass\n\n@dataclass\nclass Demo:\n    values: list[int] = field(default_factory=list)",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "code"), project)

    assert "import field explicitly from dataclasses" in agent_input.task_description
    assert "Do not leave field referenced without that import" in agent_input.task_description


def test_build_agent_input_adds_datetime_import_consistency_code_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.CODE_VALIDATION.value,
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module so it becomes syntactically valid and internally consistent.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Pytest failure details: FAILED tests_tests.py::test_audit - NameError: name 'datetime' is not defined\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "timestamp: str = field(default_factory=lambda: str(datetime.datetime.now()))",
                "failed_artifact_content": "timestamp: str = field(default_factory=lambda: str(datetime.datetime.now()))",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "code"), project)

    assert "If the module calls datetime.datetime.now() or datetime.date.today(), import datetime" in agent_input.task_description
    assert "call datetime.now() instead of datetime.datetime.now()" in agent_input.task_description


def test_build_agent_input_adds_code_truncation_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.CODE_VALIDATION.value,
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module so it becomes syntactically valid and internally consistent.",
                "validation_summary": (
                    "Generated code validation:\n"
                    "- Syntax OK: no\n"
                    "- Completion diagnostics: likely truncated at completion limit, token usage recorded\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "def run():\n    values = [1, 2,\n",
                "failed_artifact_content": "def run():\n    values = [1, 2,\n",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "code"), project)

    assert "If completion diagnostics say the module output was likely truncated" in agent_input.task_description
    assert "rewrite the full module from the top instead of patching a partial tail or appending a continuation" in agent_input.task_description
    assert "Restore a complete importable module first" in agent_input.task_description
    assert "stays comfortably under the size budget with visible headroom" in agent_input.task_description


def test_build_agent_input_adds_code_line_budget_repair_priority(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write code",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.CODE_VALIDATION.value,
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module so it becomes syntactically valid and internally consistent.",
                "validation_summary": (
                    "Generated code validation:\n"
                    "- Syntax OK: yes\n"
                    "- Line count: 312/300\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "def run():\n    return 1",
                "failed_artifact_content": "def run():\n    return 1",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "code"), project)

    assert "Repair priorities:" in agent_input.task_description
    assert "Rewrite the full module smaller and leave clear headroom below the reported line ceiling" in agent_input.task_description
    assert "Remove optional helper layers, repeated convenience wrappers, and non-essential docstrings" in agent_input.task_description


def test_build_agent_input_includes_budget_decomposition_brief_without_overriding_architecture(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
        )
    )
    project.add_task(
        Task(
            id="code__repair_1__budget_plan",
            title="Budget plan for Implementation",
            description="Write code",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="- Keep the public facade and request model.\n- Remove optional helpers and verbose CLI prose.",
            repair_context={"decomposition_mode": "budget_compaction_planner"},
        )
    )
    project.add_task(
        Task(
            id="code__repair_1",
            title="Repair Implementation",
            description="Write code",
            assigned_to="code_engineer",
            repair_origin_task_id="code",
            repair_attempt=1,
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.CODE_VALIDATION.value,
                "repair_owner": "code_engineer",
                "instruction": "Repair the generated Python module so it becomes syntactically valid and internally consistent.",
                "validation_summary": (
                    "Generated code validation:\n"
                    "- Syntax OK: yes\n"
                    "- Line count: 82/80\n"
                    "- Verdict: FAIL"
                ),
                "budget_decomposition_plan_task_id": "code__repair_1__budget_plan",
            },
        )
    )

    repair_task = require_task(project, "code__repair_1")
    agent_input = orchestrator._build_agent_input(repair_task, project)

    assert agent_input.context["architecture"] == "ARCHITECTURE DOC"
    assert agent_input.context["budget_decomposition_brief"].startswith("- Keep the public facade")
    assert "Budget decomposition brief:" in agent_input.task_description
    assert "Remove optional helpers and verbose CLI prose." in agent_input.task_description


def test_build_agent_input_preserves_public_method_names_for_pytest_only_repairs(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write tests",
            assigned_to="qa_tester",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.TEST_VALIDATION.value,
                "repair_owner": "qa_tester",
                "instruction": "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
                "validation_summary": (
                    "Generated test validation:\n"
                    "- Syntax OK: yes\n"
                    "- Pytest execution: FAIL\n"
                    "- Verdict: FAIL"
                ),
                "failed_output": "Generated test validation failed: pytest failed",
                "failed_artifact_content": "result = service.submit_intake(data)",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(require_task(project, "tests"), project)

    assert "Do not rename submit_intake(...) to submit(...) or batch_submit_intakes(...) to submit_batch(...)" in agent_input.task_description


def test_test_failure_requires_code_repair_for_code_tracebacks_and_assertion_mismatches(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    code_failure_task = Task(
        id="tests",
        title="Tests",
        description="Write tests",
        assigned_to="qa_tester",
        last_error_category=FailureCategory.TEST_VALIDATION.value,
        output_payload={
            "summary": "tests",
            "raw_content": "from code_implementation import risky",
            "artifacts": [],
            "decisions": [],
            "metadata": {
                "validation": {
                    "module_filename": "code_implementation.py",
                    "test_filename": "tests_tests.py",
                    "test_analysis": {
                        "syntax_ok": True,
                        "imported_module_symbols": ["risky"],
                        "missing_function_imports": [],
                        "unknown_module_symbols": [],
                        "invalid_member_references": [],
                        "call_arity_mismatches": [],
                        "constructor_arity_mismatches": ["Validator expects 1 args but test uses 0 at line 3"],
                        "payload_contract_violations": [],
                        "non_batch_sequence_calls": [],
                        "undefined_fixtures": [],
                        "undefined_local_names": [],
                        "imported_entrypoint_symbols": [],
                        "unsafe_entrypoint_calls": [],
                    },
                    "test_execution": {
                        "available": True,
                        "ran": True,
                        "returncode": 1,
                        "summary": "1 failed in 0.01s",
                        "stdout": "FAILED tests_tests.py::test_risky - AttributeError: boom\ncode_implementation.py:2: AttributeError\n",
                    },
                }
            },
        },
    )
    test_failure_task = Task(
        id="tests",
        title="Tests",
        description="Write tests",
        assigned_to="qa_tester",
        last_error_category=FailureCategory.TEST_VALIDATION.value,
        output_payload={
            "summary": "tests",
            "raw_content": "from code_implementation import risky",
            "artifacts": [],
            "decisions": [],
            "metadata": {
                "validation": {
                    "module_filename": "code_implementation.py",
                    "test_filename": "tests_tests.py",
                    "test_analysis": {
                        "syntax_ok": True,
                        "imported_module_symbols": ["risky"],
                        "missing_function_imports": [],
                        "unknown_module_symbols": [],
                        "invalid_member_references": [],
                        "call_arity_mismatches": [],
                        "constructor_arity_mismatches": [],
                        "payload_contract_violations": [],
                        "non_batch_sequence_calls": [],
                        "undefined_fixtures": [],
                        "undefined_local_names": [],
                        "imported_entrypoint_symbols": [],
                        "unsafe_entrypoint_calls": [],
                    },
                    "test_execution": {
                        "available": True,
                        "ran": True,
                        "returncode": 1,
                        "summary": "1 failed in 0.01s",
                        "stdout": "FAILED tests_tests.py::test_risky - assert 0 == 1\ntests_tests.py:4: AssertionError\n",
                    },
                }
            },
        },
    )
    test_local_failure_task = Task(
        id="tests",
        title="Tests",
        description="Write tests",
        assigned_to="qa_tester",
        last_error_category=FailureCategory.TEST_VALIDATION.value,
        output_payload={
            "summary": "tests",
            "raw_content": "from code_implementation import risky",
            "artifacts": [],
            "decisions": [],
            "metadata": {
                "validation": {
                    "module_filename": "code_implementation.py",
                    "test_filename": "tests_tests.py",
                    "test_analysis": {
                        "syntax_ok": True,
                        "imported_module_symbols": ["risky"],
                        "missing_function_imports": [],
                        "unknown_module_symbols": [],
                        "invalid_member_references": [],
                        "call_arity_mismatches": [],
                        "constructor_arity_mismatches": [],
                        "payload_contract_violations": [],
                        "non_batch_sequence_calls": [],
                        "undefined_fixtures": [],
                        "undefined_local_names": [],
                        "imported_entrypoint_symbols": [],
                        "unsafe_entrypoint_calls": [],
                    },
                    "test_execution": {
                        "available": True,
                        "ran": True,
                        "returncode": 1,
                        "summary": "1 failed in 0.01s",
                        "stdout": "FAILED tests_tests.py::test_risky - NameError: name 'expected' is not defined\ntests_tests.py:4: NameError\n",
                    },
                }
            },
        },
    )

    assert orchestrator._test_failure_requires_code_repair(code_failure_task) is True
    assert orchestrator._test_failure_requires_code_repair(test_failure_task) is True
    assert orchestrator._test_failure_requires_code_repair(test_local_failure_task) is False


def test_execute_workflow_resume_failed_repairs_code_before_rerunning_valid_tests(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="Architecture: expose risky() as a small API.",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Write one Python module under 50 lines.",
            assigned_to="code_engineer",
            dependencies=["arch"],
            status=TaskStatus.DONE.value,
            output="def risky() -> int:\n    raise AttributeError('boom')",
            output_payload={
                "summary": "def risky() -> int:",
                "raw_content": "def risky() -> int:\n    raise AttributeError('boom')",
                "artifacts": [
                    {
                        "name": "code_implementation",
                        "artifact_type": ArtifactType.CODE.value,
                        "path": "artifacts/code_implementation.py",
                        "content": "def risky() -> int:\n    raise AttributeError('boom')",
                    }
                ],
                "decisions": [],
                "metadata": {},
            },
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Write one compact raw pytest module under 50 lines. Use at most 2 top-level test functions.",
            assigned_to="qa_tester",
            dependencies=["code"],
            status=TaskStatus.FAILED.value,
            output="Generated test validation failed: pytest failed: 1 failed in 0.01s",
            last_error="Generated test validation failed: pytest failed: 1 failed in 0.01s",
            last_error_type="AgentExecutionError",
            last_error_category=FailureCategory.TEST_VALIDATION.value,
            output_payload={
                "summary": "tests",
                "raw_content": "from code_implementation import risky\n\ndef test_risky():\n    assert risky() == 1",
                "artifacts": [
                    {
                        "name": "tests_tests",
                        "artifact_type": ArtifactType.TEST.value,
                        "path": "artifacts/tests_tests.py",
                        "content": "from code_implementation import risky\n\ndef test_risky():\n    assert risky() == 1",
                    }
                ],
                "decisions": [],
                "metadata": {
                    "validation": {
                        "module_filename": "code_implementation.py",
                        "test_filename": "tests_tests.py",
                        "pytest_failure_origin": "code_under_test",
                        "test_analysis": {
                            "syntax_ok": True,
                            "line_count": 4,
                            "line_budget": 50,
                            "top_level_test_count": 1,
                            "max_top_level_test_count": 2,
                            "fixture_count": 0,
                            "imported_module_symbols": ["risky"],
                            "missing_function_imports": [],
                            "unknown_module_symbols": [],
                            "invalid_member_references": [],
                            "call_arity_mismatches": [],
                            "constructor_arity_mismatches": [],
                            "payload_contract_violations": [],
                            "non_batch_sequence_calls": [],
                            "undefined_fixtures": [],
                            "undefined_local_names": [],
                            "imported_entrypoint_symbols": [],
                            "unsafe_entrypoint_calls": [],
                        },
                        "test_execution": {
                            "available": True,
                            "ran": True,
                            "returncode": 1,
                            "summary": "1 failed in 0.01s",
                            "stdout": "FAILED tests_tests.py::test_risky - AttributeError: boom\ntests_tests.py:3: AssertionError\ncode_implementation.py:2: AttributeError\n",
                        },
                    }
                },
            },
            completed_at="2026-03-22T10:06:00+00:00",
        )
    )

    engineer = RecordingAgent("def risky() -> int:\n    return 1")
    tester = RecordingAgent("from code_implementation import risky\n\ndef test_risky():\n    assert risky() == 1")
    orchestrator = Orchestrator(
        config,
        registry=AgentRegistry(
            {
                "architect": RecordingAgent("Architecture: expose risky() as a small API."),
                "code_engineer": engineer,
                "qa_tester": tester,
            }
        ),
    )

    orchestrator.execute_workflow(project)

    code_task = require_task(project, "code")
    tests_task = require_task(project, "tests")
    code_repair_task = require_task(project, "code__repair_1")
    tests_repair_task = require_task(project, "tests__repair_1")
    assert code_task.status == TaskStatus.DONE.value
    assert tests_task.status == TaskStatus.DONE.value
    assert code_repair_task.status == TaskStatus.DONE.value
    assert tests_repair_task.status == TaskStatus.DONE.value
    assert "code__repair_1" in tests_repair_task.dependencies
    assert engineer.last_context["existing_code"] == "def risky() -> int:\n    raise AttributeError('boom')"
    assert engineer.last_context["existing_tests"] == "from code_implementation import risky\n\ndef test_risky():\n    assert risky() == 1"
    assert "Pytest failure details" in engineer.last_context["repair_validation_summary"]
    assert tester.last_context["code"] == "def risky() -> int:\n    return 1"


def test_build_context_includes_dependency_repair_manifest_and_summary(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config, registry=AgentRegistry({"dependency_manager": RecordingAgent("numpy")}))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="deps",
            title="Repair dependencies",
            description="Repair requirements",
            assigned_to="legal_advisor",
            repair_context={
                "cycle": 1,
                "failure_category": FailureCategory.DEPENDENCY_VALIDATION.value,
                "repair_owner": "dependency_manager",
                "instruction": "Repair the requirements manifest so every required third-party import is declared minimally and correctly.",
                "validation_summary": "Dependency manifest validation:\n- Missing manifest entries: numpy\n- Verdict: FAIL",
                "failed_output": "# No external runtime dependencies",
                "failed_artifact_content": "# No external runtime dependencies",
            },
        )
    )

    context = orchestrator._build_context(require_task(project, "deps"), project)

    assert context["repair_context"] == {
        "cycle": 1,
        "failure_category": FailureCategory.DEPENDENCY_VALIDATION.value,
        "repair_owner": "dependency_manager",
    }
    assert context["existing_dependency_manifest"] == "# No external runtime dependencies"
    assert context["dependency_validation_summary"].startswith("Dependency manifest validation:")


def test_build_context_preserves_full_repair_context_for_custom_repair_owner(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="custom_repair",
            title="Repair custom task",
            description="Repair custom output",
            assigned_to="docs_writer",
            repair_context={
                "cycle": 2,
                "failure_category": FailureCategory.TASK_EXECUTION.value,
                "repair_owner": "custom_specialist",
                "failure_message": "Custom runtime mismatch",
                "validation_summary": "Custom validation failed",
                "failed_output": "bad output",
            },
        )
    )

    context = orchestrator._build_context(require_task(project, "custom_repair"), project)

    assert context["repair_context"] == {
        "cycle": 2,
        "failure_category": FailureCategory.TASK_EXECUTION.value,
        "repair_owner": "custom_specialist",
        "failure_message": "Custom runtime mismatch",
        "validation_summary": "Custom validation failed",
        "failed_output": "bad output",
    }


def test_repair_helper_fallbacks_cover_missing_validation_payload(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="repair",
        title="Repair task",
        description="Repair",
        assigned_to="architect",
        output="provider timeout",
        last_error="provider timeout",
        output_payload=cast(dict[str, Any], "not-a-dict"),
    )

    assert orchestrator._validation_payload(task) == {}
    assert orchestrator._failed_artifact_content(task) == "provider timeout"
    assert orchestrator._failed_artifact_content_for_category(task, FailureCategory.UNKNOWN.value) == "provider timeout"
    assert orchestrator._build_repair_validation_summary(task, FailureCategory.UNKNOWN.value) == "provider timeout"
    assert orchestrator._repair_owner_for_category(task, FailureCategory.UNKNOWN.value) == "architect"
    assert "repair" in orchestrator._build_repair_instruction(task, "custom_failure")


def test_build_repair_validation_summary_uses_dependency_validation_payload(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="deps",
        title="Dependencies",
        description="Repair dependencies",
        assigned_to="dependency_manager",
        output_payload={
            "summary": "requirements",
            "raw_content": "# No external runtime dependencies",
            "artifacts": [
                {
                    "name": "requirements",
                    "artifact_type": ArtifactType.CONFIG.value,
                    "path": "artifacts/requirements.txt",
                    "content": "# No external runtime dependencies",
                }
            ],
            "decisions": [],
            "metadata": {
                "validation": {
                    "dependency_analysis": {
                        "required_imports": ["numpy"],
                        "declared_packages": [],
                        "missing_manifest_entries": ["numpy"],
                        "unused_manifest_entries": [],
                        "is_valid": False,
                    }
                }
            },
        },
    )

    summary = orchestrator._build_repair_validation_summary(task, FailureCategory.DEPENDENCY_VALIDATION.value)

    assert "Missing manifest entries: numpy" in summary
    assert "Verdict: FAIL" in summary


def test_failed_artifact_content_uses_raw_content_when_artifacts_are_missing(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="code",
        title="Code",
        description="Repair code",
        assigned_to="code_engineer",
        output_payload={
            "summary": "broken code",
            "raw_content": "def fallback() -> int:\n    return 1",
            "artifacts": None,
            "decisions": [],
            "metadata": {"validation": {"unexpected": True}},
        },
    )

    assert orchestrator._failed_artifact_content(task, ArtifactType.CODE) == "def fallback() -> int:\n    return 1"
    assert orchestrator._validation_payload(task) == {"unexpected": True}


def test_build_repair_validation_summary_uses_test_validation_payload(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    task = Task(
        id="tests",
        title="Tests",
        description="Repair tests",
        assigned_to="qa_tester",
        output_payload={
            "summary": "tests",
            "raw_content": "from module import missing",
            "artifacts": [],
            "decisions": [],
            "metadata": {
                "validation": {
                    "completion_diagnostics": {
                        "requested_max_tokens": 900,
                        "output_tokens": 900,
                        "finish_reason": "length",
                        "stop_reason": None,
                        "done_reason": None,
                        "hit_token_limit": True,
                        "likely_truncated": True,
                    },
                    "test_analysis": {
                        "syntax_ok": True,
                        "imported_module_symbols": ["missing"],
                        "missing_function_imports": ["add (line 4)"],
                        "unknown_module_symbols": [],
                        "invalid_member_references": [],
                        "constructor_arity_mismatches": [],
                        "undefined_fixtures": [],
                        "undefined_local_names": [],
                        "imported_entrypoint_symbols": [],
                        "unsafe_entrypoint_calls": [],
                    },
                    "test_execution": {
                        "available": True,
                        "ran": True,
                        "returncode": 1,
                        "summary": "1 failed in 0.01s",
                    },
                }
            },
        },
    )

    summary = orchestrator._build_repair_validation_summary(task, FailureCategory.TEST_VALIDATION.value)

    assert "Missing function imports: add (line 4)" in summary
    assert "Completion diagnostics: likely truncated at completion limit, token usage recorded" in summary
    assert "Pytest execution: FAIL" in summary
    assert summary.endswith("Verdict: FAIL")


def test_build_code_validation_summary_includes_completion_diagnostics(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_validation_summary(
        {
            "syntax_ok": False,
            "syntax_error": "'[' was never closed at line 96",
            "third_party_imports": [],
        },
        "Generated code validation failed: syntax error '[' was never closed at line 96; output likely truncated at the completion token limit",
        {
            "requested_max_tokens": 900,
            "output_tokens": 900,
            "finish_reason": "length",
            "stop_reason": None,
            "done_reason": None,
            "hit_token_limit": True,
            "likely_truncated": True,
        },
    )

    assert "Completion diagnostics: likely truncated at completion limit, token usage recorded" in summary


def test_completion_diagnostics_marks_syntax_invalid_length_limited_output_as_truncated(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    diagnostics = orchestrator._completion_diagnostics_from_provider_call(
        {
            "requested_max_tokens": 900,
            "finish_reason": "length",
            "usage": {"output_tokens": 900},
        },
        syntax_ok=False,
    )

    assert diagnostics == {
        "requested_max_tokens": 900,
        "output_tokens": 900,
        "finish_reason": "length",
        "stop_reason": None,
        "done_reason": None,
        "hit_token_limit": True,
        "likely_truncated": True,
    }


def test_completion_diagnostics_marks_structurally_incomplete_output_as_truncated(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    diagnostics = orchestrator._completion_diagnostics_from_provider_call(
        {
            "requested_max_tokens": 3200,
            "usage": {"output_tokens": 508},
        },
        raw_content=(
            "def main():\n"
            "    batch_data = [\n"
            "        {'request_id': 'req-1'},\n"
        ),
        syntax_ok=False,
        syntax_error="'[' was never closed at line 2",
    )

    assert diagnostics == {
        "requested_max_tokens": 3200,
        "output_tokens": 508,
        "finish_reason": None,
        "stop_reason": None,
        "done_reason": None,
        "hit_token_limit": False,
        "likely_truncated": True,
    }


def test_build_code_validation_summary_describes_structural_truncation(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    summary = orchestrator._build_code_validation_summary(
        {
            "syntax_ok": False,
            "syntax_error": "'[' was never closed at line 96",
            "third_party_imports": [],
        },
        "Generated code validation failed: syntax error '[' was never closed at line 96; output likely truncated before the file ended cleanly",
        {
            "requested_max_tokens": 3200,
            "output_tokens": 508,
            "finish_reason": None,
            "stop_reason": None,
            "done_reason": None,
            "hit_token_limit": False,
            "likely_truncated": True,
        },
    )

    assert "Completion diagnostics: likely truncated before the file ended cleanly, token usage recorded" in summary


def test_execute_workflow_fails_when_repair_budget_is_exhausted(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    architect = FlakyAgent(failures_before_success=2, success_response="ARCHITECTURE DOC")
    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": architect}))

    with pytest.raises(RuntimeError, match="boom-1"):
        orchestrator.execute_workflow(project)

    with pytest.raises(RuntimeError, match="boom-2"):
        orchestrator.execute_workflow(project)

    with pytest.raises(AgentExecutionError, match="Workflow repair budget exhausted before resuming failed tasks"):
        orchestrator.execute_workflow(project)

    assert project.repair_cycle_count == 1
    assert project.phase == "failed"
    assert project.failure_category == FailureCategory.REPAIR_BUDGET_EXHAUSTED.value
    assert project.acceptance_criteria_met is False
    assert project.repair_history[0]["failed_task_ids"] == ["arch"]