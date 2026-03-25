from types import SimpleNamespace

import pytest

from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider
from kycortex_agents.types import TaskStatus


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


class FakeHTTPResponse:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def build_ollama_opener(payload=None, error=None):
    def open_request(request, timeout=None):
        if error is not None:
            raise error
        return FakeHTTPResponse(payload)

    return open_request


class ProviderBackedAgent(BaseAgent):
    def __init__(self, name: str, role: str, provider, config: KYCortexConfig):
        super().__init__(name, role, config)
        self._provider = provider

    def run(self, task_description: str, context: dict) -> str:
        return self.chat("system", task_description)


def build_success_registry(tmp_path):
    openai_config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="openai", api_key="token", llm_model="gpt-4o")
    anthropic_config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic", api_key="token", llm_model="claude-3-5-sonnet")
    ollama_config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3", base_url="http://localhost:11434")

    return AgentRegistry(
        {
            "architect": ProviderBackedAgent(
                "ArchitectAgent",
                "Architecture",
                OpenAIProvider(
                    openai_config,
                    client=build_openai_client(
                        response=SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content="ARCHITECTURE DOC"))],
                            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                        )
                    ),
                ),
                openai_config,
            ),
            "code_engineer": ProviderBackedAgent(
                "CodeEngineerAgent",
                "Implementation",
                AnthropicProvider(
                    anthropic_config,
                    client=build_anthropic_client(
                        response=SimpleNamespace(
                            content=[SimpleNamespace(type="text", text="IMPLEMENTED CODE")],
                            usage=SimpleNamespace(
                                input_tokens=12,
                                output_tokens=8,
                                cache_creation_input_tokens=3,
                                cache_read_input_tokens=2,
                            ),
                        )
                    ),
                ),
                anthropic_config,
            ),
            "code_reviewer": ProviderBackedAgent(
                "CodeReviewerAgent",
                "Review",
                OllamaProvider(
                    ollama_config,
                    request_opener=build_ollama_opener(
                        payload='{"response": "PASS: reviewed", "prompt_eval_count": 14, "eval_count": 9, "total_duration": 125000000, "load_duration": 25000000}'
                    ),
                ),
                ollama_config,
            ),
        }
    )


def test_workflow_accumulates_provider_metadata_across_tasks(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    project.add_task(Task(id="code", title="Implementation", description="Implement", assigned_to="code_engineer", dependencies=["arch"]))
    project.add_task(Task(id="review", title="Review", description="Review", assigned_to="code_reviewer", dependencies=["code"]))

    Orchestrator(config, registry=build_success_registry(tmp_path)).execute_workflow(project)

    arch = project.get_task("arch")
    code = project.get_task("code")
    review = project.get_task("review")
    snapshot = project.snapshot()

    assert arch.last_provider_call["provider"] == "openai"
    assert arch.last_provider_call["usage"]["total_tokens"] == 15
    assert code.last_provider_call["provider"] == "anthropic"
    assert code.last_provider_call["usage"]["cache_creation_input_tokens"] == 3
    assert review.last_provider_call["provider"] == "ollama"
    assert review.last_provider_call["timing"]["total_duration_ms"] == 125.0
    assert snapshot.task_results["arch"].details["last_provider_call"]["model"] == "gpt-4o"
    assert snapshot.task_results["code"].details["last_provider_call"]["model"] == "claude-3-5-sonnet"
    assert snapshot.task_results["review"].details["last_provider_call"]["model"] == "llama3"


def test_failed_workflow_preserves_provider_metadata_on_failed_task(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), workflow_failure_policy="continue")
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    project.add_task(Task(id="code", title="Implementation", description="Implement", assigned_to="code_engineer"))

    failing_openai_config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="openai", api_key="token", llm_model="gpt-4o")
    registry = AgentRegistry(
        {
            "architect": ProviderBackedAgent(
                "ArchitectAgent",
                "Architecture",
                OpenAIProvider(failing_openai_config, client=build_openai_client(error=RuntimeError("down"))),
                failing_openai_config,
            ),
            "code_engineer": ProviderBackedAgent(
                "CodeEngineerAgent",
                "Implementation",
                OpenAIProvider(
                    failing_openai_config,
                    client=build_openai_client(
                        response=SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content="IMPLEMENTED CODE"))],
                            usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4, total_tokens=13),
                        )
                    ),
                ),
                failing_openai_config,
            ),
        }
    )

    Orchestrator(config, registry=registry).execute_workflow(project)

    failed = project.get_task("arch")
    completed = project.get_task("code")
    snapshot = project.snapshot()

    assert failed.status == TaskStatus.FAILED.value
    assert failed.last_provider_call["provider"] == "openai"
    assert failed.last_provider_call["success"] is False
    assert failed.last_provider_call["error_type"] == "AgentExecutionError"
    assert failed.last_provider_call["error_message"] == "OpenAI provider failed to call the model API"
    assert snapshot.task_results["arch"].failure.details["provider_call"]["model"] == "gpt-4o"
    assert completed.last_provider_call["usage"]["total_tokens"] == 13


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_provider_metadata_survives_save_load_round_trip(tmp_path, state_filename):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    state_path = tmp_path / state_filename
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    project.add_task(Task(id="code", title="Implementation", description="Implement", assigned_to="code_engineer", dependencies=["arch"]))
    registry = build_success_registry(tmp_path)
    orchestrator = Orchestrator(config, registry=registry)

    orchestrator.run_task(project.get_task("arch"), project)
    orchestrator.run_task(project.get_task("code"), project)
    project.save()

    reloaded = ProjectState.load(str(state_path))
    snapshot = reloaded.snapshot()

    assert reloaded.get_task("arch").last_provider_call["provider"] == "openai"
    assert reloaded.get_task("code").last_provider_call["provider"] == "anthropic"
    assert snapshot.task_results["arch"].details["last_provider_call"]["usage"]["total_tokens"] == 15
    assert snapshot.task_results["code"].details["last_provider_call"]["usage"]["total_tokens"] == 20