import pytest

from kycortex_agents.agents.registry import AgentRegistry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestrator import Orchestrator
from kycortex_agents.types import TaskStatus


class RetriableFailingAgent:
    def __init__(self):
        self.calls = 0

    def run(self, task_description: str, context: dict) -> str:
        self.calls += 1
        raise RuntimeError(f"boom-{self.calls}")


class ProviderFailingAgent:
    def run(self, task_description: str, context: dict) -> str:
        raise RuntimeError("terminal boom")

    def get_last_provider_call_metadata(self):
        return {
            "provider": "anthropic",
            "model": "claude-3-5-sonnet",
            "success": False,
            "error_type": "RuntimeError",
        }


def test_run_task_logs_retry_scheduled_for_retriable_failure(tmp_path, caplog):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            retry_limit=1,
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": RetriableFailingAgent()}))

    with caplog.at_level("INFO", logger="Orchestrator"):
        with pytest.raises(RuntimeError, match="boom-1"):
            orchestrator.run_task(project.tasks[0], project)

    retry_record = next(record for record in caplog.records if getattr(record, "event", None) == "task_retry_scheduled")

    assert retry_record.project_name == "Demo"
    assert retry_record.task_id == "arch"
    assert retry_record.assigned_to == "architect"
    assert retry_record.attempt == 1
    assert retry_record.error_type == "RuntimeError"
    assert all(getattr(record, "event", None) != "task_failed" for record in caplog.records)

    task = project.get_task("arch")
    assert task.status == TaskStatus.PENDING.value
    assert task.attempts == 1
    assert task.output is None
    assert task.last_error == "boom-1"
    assert task.last_error_type == "RuntimeError"
    assert task.history[-1]["event"] == "retry_scheduled"
    assert project.execution_events[-1]["event"] == "task_retry_scheduled"
    assert project.execution_events[-1]["details"]["error_type"] == "RuntimeError"


def test_run_task_logs_terminal_failure_with_provider_metadata(tmp_path, caplog):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
        )
    )

    orchestrator = Orchestrator(config, registry=AgentRegistry({"architect": ProviderFailingAgent()}))

    with caplog.at_level("INFO", logger="Orchestrator"):
        with pytest.raises(RuntimeError, match="terminal boom"):
            orchestrator.run_task(project.tasks[0], project)

    failed_record = next(record for record in caplog.records if getattr(record, "event", None) == "task_failed")

    assert failed_record.project_name == "Demo"
    assert failed_record.task_id == "arch"
    assert failed_record.assigned_to == "architect"
    assert failed_record.attempt == 1
    assert failed_record.error_type == "RuntimeError"
    assert failed_record.provider == "anthropic"
    assert failed_record.model == "claude-3-5-sonnet"
    assert all(getattr(record, "event", None) != "task_retry_scheduled" for record in caplog.records)

    task = project.get_task("arch")
    assert task.status == TaskStatus.FAILED.value
    assert task.output == "terminal boom"
    assert task.last_error == "terminal boom"
    assert task.last_error_type == "RuntimeError"
    assert task.last_provider_call is not None
    assert task.last_provider_call["provider"] == "anthropic"
    assert task.last_provider_call["model"] == "claude-3-5-sonnet"
    assert task.history[-1]["event"] == "failed"
    assert project.execution_events[-1]["event"] == "task_failed"
    assert project.execution_events[-1]["details"]["provider_call"]["provider"] == "anthropic"