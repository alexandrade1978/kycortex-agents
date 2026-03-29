import ast
import os
import pathlib
import subprocess
import sys
from types import SimpleNamespace

import pytest
import kycortex_agents.orchestrator as orchestrator_module

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
        self.last_description = None
        self.last_context = None
        self.last_input = None

    def run_with_input(self, agent_input) -> str:
        self.last_input = agent_input
        return self.run(agent_input.task_description, agent_input.context)

    def run(self, task_description: str, context: dict) -> str:
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
                DecisionRecord(
                    topic="stack",
                    decision="Use typed runtime",
                    rationale="Enables contract validation",
                )
            ],
        )


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
        return FakeHTTPResponse(current_payload)

    return open_request


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

    assert result == "def repaired() -> int:\n    return 1"
    assert project.get_task("repair").status == TaskStatus.DONE.value
    assert engineer.last_context["repair_context"]["repair_owner"] == "code_engineer"
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

    validation_rules, field_value_rules, batch_rules = orchestrator._parse_behavior_contract(contract)

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

    validation_rules, field_value_rules, batch_rules = orchestrator._parse_behavior_contract(contract)

    assert validation_rules == {}
    assert field_value_rules == {}
    assert batch_rules == {"process_batch": {"request_key": None, "wrapper_key": None, "fields": []}}


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
            return {"provider": "openai", "model": "gpt-test"}

    metadata = orchestrator._provider_call_metadata(MetadataAgent(), AgentOutput(summary="ok", raw_content="ok"))

    assert metadata == {"provider": "openai", "model": "gpt-test"}


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
    project.repair_history.append("invalid")

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
            "min_args": 1,
            "max_args": 1,
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
                "min_args": 1,
                "max_args": 1,
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


def test_build_code_behavior_contract_returns_empty_for_blank_and_syntax_invalid_modules(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)

    assert orchestrator._build_code_behavior_contract("   ") == ""
    assert orchestrator._build_code_behavior_contract("def broken(:\n    pass") == ""


def test_extract_required_fields_returns_declared_required_fields_list(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = ast.parse(
        "def validate(payload):\n"
        "    required_fields = ['name', 1, 'email']\n"
        "    return payload\n"
    ).body[0]

    assert orchestrator._extract_required_fields(function_node) == ["name", "email"]


def test_extract_required_fields_collects_unique_comparison_literals(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = ast.parse(
        "def validate(payload):\n"
        "    if 'status' in payload:\n"
        "        return True\n"
        "    if 'status' not in payload:\n"
        "        return False\n"
        "    return 'request_id' in payload\n"
    ).body[0]

    assert orchestrator._extract_required_fields(function_node) == ["status", "request_id"]


def test_extract_required_fields_returns_empty_for_blank_required_fields_list(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = ast.parse(
        "def validate(payload):\n"
        "    required_fields = []\n"
        "    return payload\n"
    ).body[0]

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
    function_node = ast.parse(
        "def process(payload):\n"
        "    return helper.validate_request(payload)\n"
    ).body[0]

    assert orchestrator._extract_indirect_required_fields(function_node, {"validate_request": ["request_id"]}) == ["request_id"]
    assert orchestrator._extract_indirect_required_fields(function_node, {"other": ["request_id"]}) == []


def test_extract_indirect_required_fields_ignores_unmatched_attribute_calls(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = ast.parse(
        "def validate(payload):\n"
        "    service.other(payload)\n"
        "    return payload\n"
    ).body[0]

    assert orchestrator._extract_indirect_required_fields(function_node, {"validate_request": ["request_id"]}) == []


def test_extract_lookup_field_rules_collects_literal_key_sets_and_skips_unknown_selectors(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = ast.parse(
        "def score_request(request, payload, selector):\n"
        "    if True:\n"
        "        pass\n"
        "    risk_scores = {'approved': 1, 'denied': 0}\n"
        "    return risk_scores[request.status] + risk_scores[payload['state']] + risk_scores[selector]\n"
    ).body[0]

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
    function_node = ast.parse(
        "def validate(payload):\n"
        "    allowed = {}\n"
        "    return allowed[payload['status']]\n"
    ).body[0]

    assert orchestrator._extract_lookup_field_rules(function_node) == {}


def test_extract_batch_rule_covers_direct_and_nested_shapes(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    direct_batch = ast.parse(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(item['request_id'], item)\n"
    ).body[0]
    nested_batch = ast.parse(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        self.intake_request(item['request_id'], item['payload'])\n"
    ).body[0]
    wrapper_only_batch = ast.parse(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(item.id, item['payload'])\n"
    ).body[0]
    missing_args_batch = ast.parse(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(item)\n"
    ).body[0]
    not_batch = ast.parse(
        "def process_items(items):\n"
        "    for item in items:\n"
        "        intake_request(item['request_id'], item)\n"
    ).body[0]
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
    helper_batch = ast.parse(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        service.validate(item)\n"
    ).body[0]
    empty_direct_batch = ast.parse(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(request_id, item)\n"
    ).body[0]
    empty_nested_batch = ast.parse(
        "def process_batch(items):\n"
        "    for item in items:\n"
        "        intake_request(request_id, item['payload'])\n"
    ).body[0]

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
        "undefined_fixtures": [],
        "undefined_local_names": [],
        "imported_entrypoint_symbols": [],
        "unsafe_entrypoint_calls": [],
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


def test_binding_and_call_helpers_cover_annotation_attribute_and_keyword_paths(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    orchestrator = Orchestrator(config)
    function_node = ast.parse(
        "def test_case():\n"
        "    payload: dict = {'status': 'approved'}\n"
        "    service.validate_request(payload)\n"
        "    process_request('id-1', payload=payload)\n"
    ).body[0]
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
    bindings = {
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
    bindings = {
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
    bindings = {
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
    bindings = {
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
    function_node = ast.parse(
        "@custom\n"
        "@pytest.fixture(scope='module')\n"
        "def sample():\n"
        "    return 1\n"
    ).body[0]

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
    assert "Completion diagnostics: likely truncated at completion limit, output_tokens reached requested_max_tokens, stop_reason=max_tokens, tokens=1600/1600" in syntax_summary
    assert syntax_summary.endswith("- Verdict: FAIL")
    assert "- Pytest execution: unavailable (pytest missing)" in unavailable_summary
    assert unavailable_summary.endswith("- Verdict: PASS")
    assert "- Pytest execution: FAIL" in failed_summary
    assert "Call arity mismatches: none" in failed_summary
    assert "Pytest failure details: FAILED tests_tests.py::test_add - assert 1 == 2" in failed_summary
    assert "- Pytest summary: 1 failed" in failed_summary
    assert failed_summary.endswith("- Verdict: FAIL")


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
    assert orchestrator._ast_name(ast.Constant("x")) == ""


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
    captured: dict[str, object] = {}

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
    assert "Generated test validation failed: pytest failed" in project.tasks[1].output
    assert project.tasks[1].output_payload is not None
    assert project.tasks[1].output_payload["raw_content"].startswith("from code_implementation import run")
    assert project.tasks[1].output_payload["metadata"]["validation"]["test_execution"]["returncode"] != 0


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

    validation = project.tasks[1].output_payload["metadata"]["validation"]["test_analysis"]
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

    validation = project.tasks[1].output_payload["metadata"]["validation"]["test_analysis"]
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

    validation = project.tasks[1].output_payload["metadata"]["validation"]["test_analysis"]
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

    validation = project.tasks[1].output_payload["metadata"]["validation"]["test_analysis"]
    assert validation["imported_entrypoint_symbols"] == ["main"]


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

    validation = project.tasks[1].output_payload["metadata"]["validation"]["test_analysis"]
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

    validation = project.tasks[1].output_payload["metadata"]["validation"]["test_analysis"]
    assert validation["non_batch_sequence_calls"] == [
        "process_case does not accept batch/list inputs at line 5"
    ]


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

    validation = project.tasks[1].output_payload["metadata"]["validation"]["test_analysis"]
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

    validation = project.tasks[1].output_payload["metadata"]["validation"]["test_analysis"]
    assert validation["payload_contract_violations"] == [
        "score_request field `document_type` uses unsupported values: type at line 5"
    ]


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
    assert "Test targets:" in context["code_test_targets"]
    assert "Entry points to avoid in tests: none" in context["code_test_targets"]
    assert "validate_request requires fields: name, email, compliance_type" in context["code_behavior_contract"]
    assert "process_batch expects each batch item to include: request_id, name, email, compliance_type" in context["code_behavior_contract"]


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
    assert project.artifacts[0]["name"] == "architecture_doc"
    assert project.artifacts[0]["path"] == "artifacts/architecture.md"
    assert project.artifacts[0]["artifact_type"] == ArtifactType.DOCUMENT.value


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

    assert project.artifacts[0]["path"] == "artifacts/arch_output.txt"
    assert (tmp_path / "output" / "artifacts" / "arch_output.txt").read_text(encoding="utf-8") == "ARCHITECTURE DOC"


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

    assert project.get_task("arch").status == TaskStatus.PENDING.value
    assert project.get_task("code").status == TaskStatus.PENDING.value


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

    assert project.get_task("arch").status == TaskStatus.FAILED.value
    assert project.get_task("code").status == TaskStatus.DONE.value
    assert project.get_task("review").status == TaskStatus.SKIPPED.value
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

    assert project.get_task("code").status == TaskStatus.DONE.value
    assert project.get_task("docs").status == TaskStatus.FAILED.value
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

    assert project.get_task("docs").status == TaskStatus.DONE.value
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

    assert project.get_task("arch").status == TaskStatus.FAILED.value

    orchestrator.execute_workflow(project)

    assert project.get_task("arch").status == TaskStatus.DONE.value
    assert project.get_task("review").status == TaskStatus.DONE.value
    assert project.get_task("arch__repair_1").status == TaskStatus.DONE.value
    assert project.get_task("arch__repair_1").repair_origin_task_id == "arch"
    assert project.repair_cycle_count == 1
    assert project.repair_history[0]["reason"] == "resume_failed_tasks"
    assert project.repair_history[0]["failed_task_ids"] == ["arch"]
    assert project.execution_events[-1]["event"] == "workflow_finished"
    assert "requeued" in [entry["event"] for entry in project.get_task("arch").history]
    assert project.get_task("arch").history[-1]["event"] == "repaired"


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

    review_task = project.get_task("review")
    repair_task = project.get_task("review__repair_1")
    assert review_task.status == TaskStatus.DONE.value
    assert review_task.output == "def repaired() -> int:\n    return 1"
    assert repair_task.status == TaskStatus.DONE.value
    assert repair_task.repair_origin_task_id == "review"
    assert engineer.last_context["repair_context"]["original_assigned_to"] == "code_reviewer"
    assert engineer.last_context["repair_context"]["failure_category"] == FailureCategory.CODE_VALIDATION.value
    assert engineer.last_context["existing_code"] == "def broken(:\n    pass"
    assert any(event["event"] == "task_repair_planned" for event in project.execution_events)
    assert any(event["event"] == "task_repair_created" for event in project.execution_events)


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
    assert project.get_task("arch").status == TaskStatus.DONE.value
    assert project.get_task("arch__repair_1").status == TaskStatus.DONE.value
    assert project.get_task("tests").status == TaskStatus.DONE.value
    assert project.get_task("tests__repair_1").status == TaskStatus.DONE.value
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
    assert project.get_task("arch").status == TaskStatus.DONE.value


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
                "failed_output": "from code_implementation import missing_symbol",
                "failed_artifact_content": "from code_implementation import missing_symbol",
            },
        )
    )

    agent_input = orchestrator._build_agent_input(project.get_task("tests"), project)

    assert "Repair objective:" in agent_input.task_description
    assert "Previous failure category: test_validation" in agent_input.task_description
    assert agent_input.context["repair_context"]["repair_owner"] == "qa_tester"
    assert agent_input.context["existing_tests"] == "from code_implementation import missing_symbol"
    assert agent_input.context["test_validation_summary"].endswith("Verdict: FAIL")


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

    context = orchestrator._build_context(project.get_task("deps"), project)

    assert context["repair_context"]["repair_owner"] == "dependency_manager"
    assert context["existing_dependency_manifest"] == "# No external runtime dependencies"
    assert context["dependency_validation_summary"].startswith("Dependency manifest validation:")


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
        output_payload="not-a-dict",
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
    assert "Completion diagnostics: likely truncated at completion limit, output_tokens reached requested_max_tokens, finish_reason=length, tokens=900/900" in summary
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

    assert "Completion diagnostics: likely truncated at completion limit, output_tokens reached requested_max_tokens, finish_reason=length, tokens=900/900" in summary


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

    assert "Completion diagnostics: likely truncated before the file ended cleanly, tokens=508/3200" in summary


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