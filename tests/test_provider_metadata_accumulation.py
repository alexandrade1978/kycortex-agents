from types import SimpleNamespace
from typing import Any

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


def require_task(project: ProjectState, task_id: str) -> Task:
    task = project.get_task(task_id)
    assert task is not None
    return task


def require_provider_call(task: Task) -> dict[str, Any]:
    assert task.last_provider_call is not None
    return task.last_provider_call


def build_openai_client(response=None, error=None, health_response=None, health_error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    def list_models(**kwargs):
        if health_error is not None:
            raise health_error
        return health_response if health_response is not None else [SimpleNamespace(id="gpt-4o")]

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
        return health_response if health_response is not None else [SimpleNamespace(id="claude-3-5-sonnet")]

    return SimpleNamespace(
        messages=SimpleNamespace(create=create),
        models=SimpleNamespace(list=list_models),
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


def build_ollama_opener(
    payload=None,
    error=None,
    health_payload='{"models": [{"name": "llama3:latest"}]}',
    health_error=None,
):
    def open_request(request, timeout=None):
        url = getattr(request, "full_url", None)
        if url is None and hasattr(request, "get_full_url"):
            url = request.get_full_url()
        if isinstance(url, str) and url.endswith("/api/tags"):
            if health_error is not None:
                raise health_error
            if error is not None and health_payload is None:
                raise error
            response_payload = health_payload if health_payload is not None else payload
            assert isinstance(response_payload, str)
            return FakeHTTPResponse(response_payload)
        if error is not None:
            raise error
        assert isinstance(payload, str)
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

    arch = require_task(project, "arch")
    code = require_task(project, "code")
    review = require_task(project, "review")
    snapshot = project.snapshot()
    arch_provider_call = require_provider_call(arch)
    code_provider_call = require_provider_call(code)
    review_provider_call = require_provider_call(review)

    assert arch_provider_call["provider"] == "openai"
    assert arch_provider_call["usage"]["total_tokens"] == 15
    assert code_provider_call["provider"] == "anthropic"
    assert code_provider_call["usage"]["cache_creation_input_tokens"] == 3
    assert review_provider_call["provider"] == "ollama"
    assert review_provider_call["timing"]["total_duration_ms"] == 125.0
    assert snapshot.task_results["arch"].resource_telemetry["provider"] == "openai"
    assert snapshot.task_results["arch"].resource_telemetry["model"] == "gpt-4o"
    assert snapshot.task_results["code"].resource_telemetry["model"] == "claude-3-5-sonnet"
    assert snapshot.task_results["review"].resource_telemetry["model"] == "llama3"
    assert snapshot.task_results["arch"].resource_telemetry["provider_duration_ms"] == arch_provider_call["duration_ms"]
    assert snapshot.task_results["arch"].resource_telemetry["usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    assert snapshot.task_results["review"].resource_telemetry["provider_duration_ms"] == review_provider_call["duration_ms"]
    assert snapshot.task_results["arch"].details["has_provider_call"] is True
    assert snapshot.task_results["arch"].details["last_error_present"] is False
    assert "last_provider_call" not in snapshot.task_results["arch"].details
    assert "last_provider_call" not in snapshot.task_results["code"].details
    assert "last_provider_call" not in snapshot.task_results["review"].details
    assert "provider_budget" not in snapshot.task_results["arch"].details
    assert snapshot.workflow_telemetry["tasks_with_provider_calls"] == 3
    assert snapshot.workflow_telemetry["final_providers"] == ["anthropic", "ollama", "openai"]
    assert snapshot.workflow_telemetry["acceptance_summary"]["accepted"] is True
    assert snapshot.workflow_telemetry["acceptance_summary"]["policy"] == snapshot.acceptance_policy
    assert snapshot.workflow_telemetry["acceptance_summary"]["terminal_outcome"] == snapshot.terminal_outcome
    assert snapshot.workflow_telemetry["provider_summary"]["openai"]["usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    assert snapshot.workflow_telemetry["provider_summary"]["anthropic"]["usage"] == {
        "cache_creation_input_tokens": 3,
        "cache_read_input_tokens": 2,
        "input_tokens": 12,
        "output_tokens": 8,
        "total_tokens": 20,
    }
    assert snapshot.workflow_telemetry["provider_health_summary"] == {
        "anthropic": {
            "models": ["claude-3-5-sonnet"],
            "status_counts": {"healthy": 1},
            "last_outcome_counts": {"success": 1},
            "circuit_open_count": 0,
            "retryable_failure_count": 0,
            "active_health_check_count": 1,
        },
        "ollama": {
            "models": ["llama3"],
            "status_counts": {"healthy": 1},
            "last_outcome_counts": {"success": 1},
            "circuit_open_count": 0,
            "retryable_failure_count": 0,
            "active_health_check_count": 1,
        },
        "openai": {
            "models": ["gpt-4o"],
            "status_counts": {"healthy": 1},
            "last_outcome_counts": {"success": 1},
            "circuit_open_count": 0,
            "retryable_failure_count": 0,
            "active_health_check_count": 1,
        },
    }
    assert snapshot.workflow_telemetry["provider_summary"]["ollama"]["duration_ms"] == {
        "count": 1,
        "total": review_provider_call["duration_ms"],
        "min": review_provider_call["duration_ms"],
        "max": review_provider_call["duration_ms"],
        "avg": review_provider_call["duration_ms"],
    }
    assert snapshot.workflow_telemetry["usage"] == {
        "cache_creation_input_tokens": 3,
        "cache_read_input_tokens": 2,
        "input_tokens": 36,
        "output_tokens": 22,
        "total_tokens": 58,
    }
    assert any(
        event["task_id"] == "arch"
        and (event["details"].get("provider_budget") or {})
        == {
            "call_budget_limited": False,
            "call_budget_exhausted": False,
            "limited_providers": [],
            "exhausted_providers": [],
        }
        for event in project.execution_events
    )


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
                OpenAIProvider(failing_openai_config, client=build_openai_client(error=TimeoutError("down"))),
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

    failed = require_task(project, "arch")
    completed = require_task(project, "code")
    snapshot = project.snapshot()
    failed_provider_call = require_provider_call(failed)
    completed_provider_call = require_provider_call(completed)
    arch_failure = snapshot.task_results["arch"].failure
    assert arch_failure is not None

    assert failed.status == TaskStatus.FAILED.value
    assert failed_provider_call["provider"] == "openai"
    assert failed_provider_call["success"] is False
    assert failed_provider_call["error_type"] == "ProviderTransientError"
    assert failed_provider_call["retryable"] is True
    assert failed_provider_call["error_message"] == "OpenAI provider failed to call the model API"
    assert arch_failure.details["has_provider_call"] is True
    assert "provider_call" not in arch_failure.details
    assert "provider_budget" not in arch_failure.details
    assert snapshot.task_results["arch"].resource_telemetry["has_provider_call"] is True
    assert snapshot.task_results["arch"].resource_telemetry["provider"] == "openai"
    assert snapshot.task_results["arch"].resource_telemetry["model"] == "gpt-4o"
    assert completed_provider_call["usage"]["total_tokens"] == 13


def test_cached_health_snapshots_do_not_increment_active_health_check_count(tmp_path):
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            last_provider_call={
                "provider": "openai",
                "model": "gpt-4o",
                "success": True,
                "duration_ms": 12.5,
                "provider_health": {
                    "openai": {
                        "model": "gpt-4o",
                        "status": "degraded",
                        "last_outcome": "failure",
                        "last_failure_retryable": True,
                        "last_error_type": "ProviderTransientError",
                        "last_health_check": {
                            "status": "degraded",
                            "active_check": True,
                            "cooldown_cached": True,
                        },
                    }
                },
            },
        )
    )

    snapshot = project.snapshot()

    assert snapshot.workflow_telemetry["provider_health_summary"] == {
        "openai": {
            "models": ["gpt-4o"],
            "status_counts": {"degraded": 1},
            "last_outcome_counts": {"failure": 1},
            "circuit_open_count": 0,
            "retryable_failure_count": 1,
            "active_health_check_count": 0,
        }
    }


def test_workflow_records_fallback_after_primary_health_check_failure(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), workflow_failure_policy="continue")
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))

    primary_config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="openai",
        api_key="token",
        llm_model="gpt-4o",
        provider_fallback_order=("anthropic",),
        provider_fallback_models={"anthropic": "claude-3-5-sonnet"},
    )
    primary_provider = OpenAIProvider(
        primary_config,
        client=build_openai_client(health_error=TimeoutError("openai health down")),
    )
    fallback_provider = AnthropicProvider(
        KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            llm_provider="anthropic",
            api_key="token",
            llm_model="claude-3-5-sonnet",
        ),
        client=build_anthropic_client(
            health_response=[SimpleNamespace(id="claude-3-5-sonnet")],
            response=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="FALLBACK RESULT")],
                usage=SimpleNamespace(input_tokens=12, output_tokens=8),
            ),
        ),
    )

    def create_fallback_provider(runtime_config: KYCortexConfig):
        assert runtime_config.llm_provider == "anthropic"
        return fallback_provider

    monkeypatch.setattr("kycortex_agents.agents.base_agent.create_provider", create_fallback_provider)
    registry = AgentRegistry(
        {
            "architect": ProviderBackedAgent(
                "ArchitectAgent",
                "Architecture",
                primary_provider,
                primary_config,
            )
        }
    )

    Orchestrator(config, registry=registry).execute_workflow(project)

    task = require_task(project, "arch")
    snapshot = project.snapshot()
    provider_call = require_provider_call(task)

    assert task.status == TaskStatus.DONE.value
    assert provider_call["provider"] == "anthropic"
    assert provider_call["fallback_history"] == [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "status": "failed_health_check",
            "error_type": "ProviderTransientError",
            "has_error_message": True,
            "retryable": True,
        }
    ]
    assert provider_call["provider_health"]["openai"]["status"] == "degraded"
    assert snapshot.task_results["arch"].resource_telemetry["provider"] == "anthropic"
    assert "last_provider_call" not in snapshot.task_results["arch"].details
    assert snapshot.workflow_telemetry["observed_providers"] == ["anthropic", "openai"]
    assert snapshot.workflow_telemetry["final_providers"] == ["anthropic"]
    assert snapshot.workflow_telemetry["fallback_summary"] == {
        "task_count": 1,
        "entry_count": 1,
        "provider_count": 1,
        "status_count": 1,
    }
    assert snapshot.workflow_telemetry["provider_health_summary"] == {
        "anthropic": {
            "models": ["claude-3-5-sonnet"],
            "status_counts": {"healthy": 1},
            "last_outcome_counts": {"success": 1},
            "circuit_open_count": 0,
            "retryable_failure_count": 0,
            "active_health_check_count": 1,
        },
        "openai": {
            "models": ["gpt-4o"],
            "status_counts": {"degraded": 1},
            "last_outcome_counts": {"failure": 1},
            "circuit_open_count": 0,
            "retryable_failure_count": 1,
            "active_health_check_count": 1,
        },
    }
    assert snapshot.workflow_telemetry["error_summary"]["fallback_error_count"] == 1
    assert any(
        event["task_id"] == "arch"
        and event["details"].get("provider_call", {}).get("fallback_history")
        for event in project.execution_events
    )


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_provider_metadata_survives_save_load_round_trip(tmp_path, state_filename):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    state_path = tmp_path / state_filename
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    project.add_task(Task(id="code", title="Implementation", description="Implement", assigned_to="code_engineer", dependencies=["arch"]))
    registry = build_success_registry(tmp_path)
    orchestrator = Orchestrator(config, registry=registry)

    orchestrator.run_task(require_task(project, "arch"), project)
    orchestrator.run_task(require_task(project, "code"), project)
    project.save()

    reloaded = ProjectState.load(str(state_path))
    snapshot = reloaded.snapshot()

    reloaded_arch = require_task(reloaded, "arch")
    reloaded_code = require_task(reloaded, "code")
    assert require_provider_call(reloaded_arch)["provider"] == "openai"
    assert require_provider_call(reloaded_code)["provider"] == "anthropic"
    assert snapshot.task_results["arch"].resource_telemetry["usage"]["total_tokens"] == 15
    assert snapshot.task_results["code"].resource_telemetry["usage"]["total_tokens"] == 20
    assert "last_provider_call" not in snapshot.task_results["arch"].details
    assert "last_provider_call" not in snapshot.task_results["code"].details