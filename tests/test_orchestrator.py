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
from kycortex_agents.exceptions import AgentExecutionError, WorkflowDefinitionError
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
        "        required_fields = ['name', 'email', 'compliance_type']\n"
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
        "intake_request payload missing required fields: name, email, compliance_type at line 11",
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
                    "test_analysis": {
                        "syntax_ok": True,
                        "imported_module_symbols": ["missing"],
                        "missing_function_imports": ["add (line 4)"],
                        "unknown_module_symbols": [],
                        "invalid_member_references": [],
                        "constructor_arity_mismatches": [],
                        "undefined_fixtures": [],
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
    assert "Pytest execution: FAIL" in summary
    assert summary.endswith("Verdict: FAIL")


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