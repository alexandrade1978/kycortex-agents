from types import SimpleNamespace

import pytest

from kycortex_agents.agents.dependency_manager import DependencyManagerAgent
from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider
from kycortex_agents.types import AgentOutput, ArtifactRecord, ArtifactType, DecisionRecord, TaskStatus, WorkflowOutcome


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


def build_openai_client(response=None, error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def build_anthropic_client(response=None, error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    return SimpleNamespace(messages=SimpleNamespace(create=create))


def build_ollama_opener(payload=None, error=None):
    calls = 0

    def open_request(request, timeout=None):
        nonlocal calls
        current_payload = payload[min(calls, len(payload) - 1)] if isinstance(payload, list) else payload
        current_error = error[min(calls, len(error) - 1)] if isinstance(error, list) else error
        calls += 1
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
                "        required_fields = ['name', 'email', 'compliance_type']\n"
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
                    "        required_fields = ['name', 'email', 'compliance_type']\n"
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
                            "        required_fields = ['name', 'email', 'compliance_type']\n"
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
                    )
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
                    )
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
                        '{"models": []}',
                        '{"response": "# No external runtime dependencies", "prompt_eval_count": 10, "eval_count": 5}',
                    ]
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

    assert "workflow_started" in events
    assert "workflow_completed" in events
    assert "workflow_finished" in events


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


def test_execute_workflow_can_resume_failed_workflow(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
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
    assert "requeued" in [entry["event"] for entry in project.get_task("arch").history]
    assert project.get_task("arch").history[-1]["event"] == "completed"