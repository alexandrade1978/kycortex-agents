import argparse
import importlib.util
import json
import os
import pytest
import stat
import sys
from pathlib import Path
from urllib.error import URLError

from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import WorkflowOutcome, WorkflowStatus


def _load_example_module(module_name: str, relative_path: str):
    project_root = Path(__file__).resolve().parents[1]
    examples_dir = project_root / "examples"
    module_path = project_root / relative_path
    sys.path.insert(0, str(examples_dir))
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_full_provider_workflow_build_config_accepts_resume_controls(tmp_path):
    module = _load_example_module(
        "example_full_provider_workflow_test",
        "examples/example_full_provider_workflow.py",
    )

    config = module.build_config(
        "ollama",
        "llama3",
        str(tmp_path / "output"),
        workflow_failure_policy="continue",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=2,
    )

    assert config.workflow_failure_policy == "continue"
    assert config.workflow_resume_policy == "resume_failed"
    assert config.workflow_max_repair_cycles == 2


def test_full_provider_workflow_example_limits_public_output_dir(capsys, monkeypatch):
    module = _load_example_module(
        "example_full_provider_workflow_public_output_test",
        "examples/example_full_provider_workflow.py",
    )

    output_dir = "/srv/customer-secret-root/full-provider-run"
    task = Task(
        id="arch",
        title="Architecture",
        description="Design the architecture",
        assigned_to="architect",
        status="done",
    )
    project = type(
        "FakeProject",
        (),
        {
            "phase": "completed",
            "terminal_outcome": "completed",
            "repair_cycle_count": 0,
            "tasks": [task],
        },
    )()

    class FakeParser:
        def parse_args(self):
            return argparse.Namespace(
                provider="ollama",
                model=None,
                output_dir=output_dir,
                failure_policy="continue",
                resume_policy="resume_failed",
                max_repair_cycles=1,
                summary_json=None,
            )

    monkeypatch.setattr(module, "build_parser", lambda: FakeParser())
    monkeypatch.setattr(module, "resolve_model", lambda provider, model: "qwen2.5-coder:7b")
    monkeypatch.setattr(module, "build_config", lambda *args, **kwargs: object())
    monkeypatch.setattr(module, "build_project", lambda output_dir, provider: project)
    monkeypatch.setattr(module, "execute_empirical_validation_workflow", lambda config, project: None)
    monkeypatch.setattr(module, "summarize_workflow_run", lambda *args, **kwargs: {})

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "provider=present" in captured
    assert "model=present" in captured
    assert "repair_cycles_present=none" in captured
    assert "repair_cycle_count=0" not in rendered
    assert "provider=ollama" not in rendered
    assert "model=qwen2.5-coder:7b" not in rendered
    assert "output_dir=full-provider-run" in captured
    assert all("customer-secret-root" not in line for line in captured)


def test_provider_smoke_example_limits_public_output_dir(capsys, monkeypatch):
    module = _load_example_module(
        "example_provider_smoke_public_output_test",
        "examples/example_provider_smoke.py",
    )

    output_dir = "/srv/customer-secret-root/provider-smoke"
    task = Task(
        id="arch",
        title="Architecture",
        description="Produce a concise architecture note.",
        assigned_to="architect",
        status="done",
        output="api_key=sk-secret-123456\nA short architecture preview.",
    )
    project = type(
        "FakeProject",
        (),
        {
            "phase": "completed",
            "tasks": [task],
        },
    )()

    class FakeParser:
        def parse_args(self):
            return argparse.Namespace(
                provider="ollama",
                model=None,
                output_dir=output_dir,
            )

    class FakeOrchestrator:
        def __init__(self, config):
            self.config = config

        def execute_workflow(self, project):
            return None

    monkeypatch.setattr(module, "build_parser", lambda: FakeParser())
    monkeypatch.setattr(module, "build_config", lambda *args, **kwargs: object())
    monkeypatch.setattr(module, "build_project", lambda output_dir, provider: project)
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "provider=present" in captured
    assert "model=present" in captured
    assert "output_dir=provider-smoke" in captured
    assert "output_present=present" in captured
    assert "provider=ollama" not in rendered
    assert "model=qwen2.5-coder:7b" not in rendered
    assert "preview=" not in rendered
    assert "A short architecture preview." not in rendered
    assert "sk-secret-123456" not in rendered
    assert all("customer-secret-root" not in line for line in captured)


def test_simple_project_example_limits_public_output_dir(capsys, monkeypatch):
    module = _load_example_module(
        "example_simple_project_public_output_test",
        "examples/example_simple_project.py",
    )

    output_dir = "/srv/customer-secret-root/simple-api"

    class FakeOrchestrator:
        def __init__(self, config):
            self.config = config

        def execute_workflow(self, project):
            return None

    monkeypatch.setattr(
        module,
        "KYCortexConfig",
        lambda **kwargs: type("Config", (), {"output_dir": output_dir})(),
    )
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()

    assert "Artifact files saved to simple-api" in captured
    assert all("customer-secret-root" not in line for line in captured)


def test_resume_workflow_example_limits_public_state_file_path(tmp_path, capsys, monkeypatch):
    module = _load_example_module(
        "example_resume_workflow_public_state_file_test",
        "examples/example_resume_workflow.py",
    )

    output_dir = tmp_path / "customer-secret-root" / "output_resume_demo"
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "project_state.sqlite"

    class FakeOrchestrator:
        def __init__(self, config, registry=None):
            self.config = config
            self.registry = registry

        def execute_workflow(self, project):
            project.workflow_last_resumed_at = "2026-04-03T03:30:00+00:00"
            return None

    monkeypatch.setattr(module, "STATE_PATH", str(state_path))
    monkeypatch.setattr(module, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "State file: project_state.sqlite" in captured
    assert "Workflow resumed: present" in captured
    assert "2026-04-03T03:30:00+00:00" not in rendered
    assert all("customer-secret-root" not in line for line in captured)


def test_snapshot_inspection_example_limits_public_telemetry_dump(capsys, monkeypatch):
    module = _load_example_module(
        "example_snapshot_inspection_public_telemetry_test",
        "examples/example_snapshot_inspection.py",
    )

    task_result = type(
        "FakeTaskResult",
        (),
        {
            "status": type("FakeStatus", (), {"value": "done"})(),
            "output": type("FakeOutput", (), {"summary": "Architecture snapshot ready"})(),
            "resource_telemetry": {
                "provider": "openai",
                "model": "snapshot-openai-demo",
            },
            "details": {"has_provider_call": True},
        },
    )()
    snapshot = type(
        "FakeSnapshot",
        (),
        {
            "workflow_status": "completed",
            "task_results": {"arch": task_result},
            "workflow_telemetry": {
                "task_count": 2,
                "tasks_with_provider_calls": 1,
                "tasks_without_provider_calls": 1,
                "observed_providers": ["openai", "anthropic"],
                "final_providers": ["openai"],
                "attempt_count": 2,
                "retry_attempt_count": 0,
                "progress_summary": {
                    "pending_task_count": 0,
                    "running_task_count": 0,
                    "runnable_task_count": 0,
                    "blocked_task_count": 0,
                    "terminal_task_count": 2,
                    "completion_percent": 100.0,
                },
                "provider_health_summary": {
                    "openai": {
                        "models": ["snapshot-openai-demo"],
                        "status_counts": {"healthy": 1},
                        "last_outcome_counts": {"success": 1},
                        "circuit_open_count": 2,
                        "retryable_failure_count": 3,
                        "active_health_check_count": 1,
                    }
                },
            },
            "artifacts": [type("FakeArtifact", (), {"name": "architecture"})()],
            "decisions": [type("FakeDecision", (), {"topic": "architecture_snapshot"})()],
            "execution_events": [
                {"event": "workflow_started"},
                {"event": "workflow_finished"},
            ],
        },
    )()

    fake_project = type("FakeProject", (), {"snapshot": lambda self: snapshot})()

    class FakeOrchestrator:
        def __init__(self, config, registry=None):
            self.config = config
            self.registry = registry

        def execute_workflow(self, project):
            return None

    monkeypatch.setattr(module, "build_snapshot_project", lambda state_path: fake_project)
    monkeypatch.setattr(module, "build_snapshot_registry", lambda config: object())
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "task_count=2" in captured
    assert "- arch: status=done, summary=Architecture snapshot ready, provider=present, model=present" in captured
    assert "observed_provider_count=2" in captured
    assert "final_provider_count=1" in captured
    assert "attempts_present=present" in captured
    assert "retry_attempts_present=none" in captured
    assert "completion_percent=100.0" in captured
    assert "- entry_1: model_count=1; statuses=healthy:1; outcomes=success:1; active_checks=1" in captured
    assert "artifact_names=architecture" in captured
    assert "decision_topics=architecture_snapshot" in captured
    assert "event_count=2" in captured
    assert "last_event=workflow_finished" in captured
    assert "openai" not in rendered
    assert "anthropic" not in rendered
    assert "snapshot-openai-demo" not in rendered
    assert "attempt_count=2" not in rendered
    assert "retry_attempt_count=0" not in rendered
    assert "TimeoutError" not in rendered
    assert "last_error_types" not in rendered
    assert "circuit_open_count" not in rendered
    assert "retryable_failure_count" not in rendered
    assert "workflow_started" not in rendered
    assert "{" not in rendered
    assert "}" not in rendered
    assert "[" not in rendered
    assert "]" not in rendered


def test_failure_recovery_example_limits_public_exception_message(capsys, monkeypatch):
    module = _load_example_module(
        "example_failure_recovery_public_exception_test",
        "examples/example_failure_recovery.py",
    )

    failed_arch = type(
        "FakeTask",
        (),
        {
            "id": "arch",
            "status": "failed",
            "attempts": 2,
            "last_error_type": "RuntimeError",
            "history": [{"event": "task_started"}, {"event": "task_failed"}],
        },
    )()
    failed = type(
        "FakeFailedProject",
        (),
        {
            "workflow_last_resumed_at": None,
            "tasks": [failed_arch],
            "get_task": lambda self, task_id: failed_arch if task_id == "arch" else None,
            "summary": lambda self: "Workflow failed once and then recovered.",
        },
    )()

    class FakeOrchestrator:
        call_count = 0

        def __init__(self, config, registry=None):
            self.config = config
            self.registry = registry

        def execute_workflow(self, project):
            type(self).call_count += 1
            if type(self).call_count == 1:
                raise RuntimeError(
                    "token=sk-live-secret-123 path=/srv/customer-secret-root/failure-state.sqlite"
                )
            project.workflow_last_resumed_at = "2026-04-03T04:00:00+00:00"
            return None

    monkeypatch.setattr(module, "build_recovery_project", lambda state_path: object())
    monkeypatch.setattr(module.ProjectState, "load", staticmethod(lambda state_path: failed))
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "First run failed with RuntimeError" in captured
    assert "sk-live-secret-123" not in rendered
    assert "customer-secret-root" not in rendered
    assert "failure-state.sqlite" not in rendered


def test_failure_recovery_example_limits_public_task_history_events(capsys, monkeypatch):
    module = _load_example_module(
        "example_failure_recovery_public_history_test",
        "examples/example_failure_recovery.py",
    )

    failed_arch = type(
        "FakeTask",
        (),
        {
            "id": "arch",
            "status": "failed",
            "attempts": 2,
            "last_error_type": "RuntimeError",
            "history": [{"event": "task_started"}, {"event": "task_failed"}],
        },
    )()
    failed = type(
        "FakeFailedProject",
        (),
        {
            "workflow_last_resumed_at": "2026-04-03T04:10:00+00:00",
            "tasks": [failed_arch],
            "get_task": lambda self, task_id: failed_arch if task_id == "arch" else None,
            "summary": lambda self: "Workflow failed once and then recovered.",
        },
    )()

    class FakeOrchestrator:
        def __init__(self, config, registry=None):
            self.config = config
            self.registry = registry

        def execute_workflow(self, project):
            return None

    monkeypatch.setattr(module, "build_recovery_project", lambda state_path: object())
    monkeypatch.setattr(module.ProjectState, "load", staticmethod(lambda state_path: failed))
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "Workflow resumed: present" in captured
    assert "- arch attempts: present" in captured
    assert "- arch: status=failed, attempts=present, history_events_present=present" in captured
    assert "2026-04-03T04:10:00+00:00" not in rendered
    assert "attempts=2" not in rendered
    assert "history_event_count=2" not in rendered
    assert "task_started" not in rendered
    assert "task_failed" not in rendered


def test_failure_recovery_example_limits_public_last_error_type(capsys, monkeypatch):
    module = _load_example_module(
        "example_failure_recovery_public_error_type_test",
        "examples/example_failure_recovery.py",
    )

    failed_arch = type(
        "FakeTask",
        (),
        {
            "id": "arch",
            "status": "failed",
            "attempts": 2,
            "last_error_type": "ProviderSDKInitializationError",
            "history": [{"event": "task_started"}, {"event": "task_failed"}],
        },
    )()
    failed = type(
        "FakeFailedProject",
        (),
        {
            "workflow_last_resumed_at": "2026-04-03T04:15:00+00:00",
            "tasks": [failed_arch],
            "get_task": lambda self, task_id: failed_arch if task_id == "arch" else None,
            "summary": lambda self: "Workflow failed once and then recovered.",
        },
    )()

    class FakeOrchestrator:
        def __init__(self, config, registry=None):
            self.config = config
            self.registry = registry

        def execute_workflow(self, project):
            return None

    monkeypatch.setattr(module, "build_recovery_project", lambda state_path: object())
    monkeypatch.setattr(module.ProjectState, "load", staticmethod(lambda state_path: failed))
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "- persisted error: present" in captured
    assert "ProviderSDKInitializationError" not in rendered


def test_complex_workflow_example_limits_public_list_output(capsys, monkeypatch):
    module = _load_example_module(
        "example_complex_workflow_public_list_test",
        "examples/example_complex_workflow.py",
    )

    docs_task = type(
        "FakeTask",
        (),
        {"output": "Merged documentation bundle ready. token=sk-secret-123456"},
    )()
    snapshot = type(
        "FakeSnapshot",
        (),
        {
            "artifacts": [
                type("FakeArtifact", (), {"name": "architecture"})(),
                type("FakeArtifact", (), {"name": "implementation"})(),
            ],
            "decisions": [
                type("FakeDecision", (), {"topic": "architecture_style"})(),
                type("FakeDecision", (), {"topic": "review_status"})(),
            ],
        },
    )()
    project = type(
        "FakeProject",
        (),
        {
            "snapshot": lambda self: snapshot,
            "get_task": lambda self, task_id: docs_task if task_id == "docs" else None,
            "summary": lambda self: "Complex workflow completed.",
        },
    )()

    class FakeOrchestrator:
        def __init__(self, config, registry=None):
            self.config = config
            self.registry = registry

        def execute_workflow(self, project):
            return None

    monkeypatch.setattr(module, "build_complex_registry", lambda config: object())
    monkeypatch.setattr(module, "build_complex_project", lambda state_path: project)
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "docs_output_present=present" in captured
    assert "artifact_names=architecture, implementation" in captured
    assert "decision_topics=architecture_style, review_status" in captured
    assert "Merged documentation bundle ready." not in rendered
    assert "sk-secret-123456" not in rendered
    assert "[" not in rendered
    assert "]" not in rendered


def test_custom_agent_example_limits_public_task_output(capsys, monkeypatch):
    module = _load_example_module(
        "example_custom_agent_public_output_test",
        "examples/example_custom_agent.py",
    )

    class FakeOrchestrator:
        def __init__(self, config, registry=None):
            self.config = config
            self.registry = registry

        def execute_workflow(self, project):
            arch_task = project.get_task("arch")
            summary_task = project.get_task("summary")
            assert arch_task is not None
            assert summary_task is not None
            arch_task.status = "done"
            arch_task.output = "Service boundary: token=sk-live-secret-123"
            summary_task.status = "done"
            summary_task.output = (
                "Architecture summary: token=sk-live-secret-123 "
                "path=/srv/customer-secret-root/custom-agent-summary.txt"
            )
            return None

    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "summary_task_status=done" in captured
    assert "summary_output_present=present" in captured
    assert "Architecture summary:" not in rendered
    assert "sk-live-secret-123" not in rendered
    assert "customer-secret-root" not in rendered


def test_test_mode_example_limits_public_task_output(capsys, monkeypatch):
    module = _load_example_module(
        "example_test_mode_public_output_test",
        "examples/example_test_mode.py",
    )

    class FakeOrchestrator:
        def __init__(self, config, registry=None):
            self.config = config
            self.registry = registry

        def execute_workflow(self, project):
            for task_id in ["arch", "code", "review"]:
                task = project.get_task(task_id)
                assert task is not None
                task.status = "done"
                task.output = (
                    f"{task_id.upper()} token=sk-live-secret-123 "
                    "path=/srv/customer-secret-root/test-mode-output.txt"
                )
            return None

    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "- arch: status=done, output_present=present" in captured
    assert "- code: status=done, output_present=present" in captured
    assert "- review: status=done, output_present=present" in captured
    assert "sk-live-secret-123" not in rendered
    assert "customer-secret-root" not in rendered
    assert "ARCH token=" not in rendered
    assert "CODE token=" not in rendered
    assert "REVIEW token=" not in rendered


def test_provider_matrix_summary_reports_repair_lineage(tmp_path):
    from kycortex_agents.provider_matrix import summarize_workflow_run

    project = ProjectState(
        project_name="Demo",
        goal="Validate provider summary output",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.phase = "completed"
    project.terminal_outcome = "completed"
    project.acceptance_criteria_met = True
    project.acceptance_policy = "required_tasks"
    project.acceptance_evaluation = {
        "policy": "required_tasks",
        "accepted": True,
        "reason": "all_required_tasks_done",
        "evaluated_task_ids": ["tests"],
        "required_task_ids": ["tests"],
        "completed_task_ids": ["tests"],
        "failed_task_ids": [],
        "skipped_task_ids": [],
        "pending_task_ids": [],
    }
    project.repair_cycle_count = 1
    project.repair_max_cycles = 1
    project.repair_history = [{"cycle": 1, "failed_task_ids": ["tests"]}]
    project.workflow_last_resumed_at = "2026-03-28T12:00:00+00:00"
    project.workflow_finished_at = "2026-03-28T12:05:00+00:00"
    project.execution_events.append(
        {
            "event": "workflow_resumed",
            "timestamp": "2026-03-28T12:00:00+00:00",
            "task_id": None,
            "status": "execution",
            "details": {"reason": "failed_workflow", "task_ids": ["tests__repair_1"]},
        }
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Run tests",
            assigned_to="qa_tester",
            status="done",
            attempts=2,
        )
    )
    project.add_task(
        Task(
            id="tests__repair_1",
            title="Tests Repair",
            description="Repair tests",
            assigned_to="qa_tester",
            status="done",
            attempts=1,
            repair_origin_task_id="tests",
            repair_attempt=1,
        )
    )

    summary = summarize_workflow_run(
        project,
        provider="ollama",
        model="llama3",
        output_dir=str(tmp_path / "output"),
    )

    assert summary["terminal_outcome"] == "completed"
    assert summary["repair_cycle_count"] == 1
    assert summary["repair_task_count"] == 1
    assert summary["task_status_counts"] == {"done": 2}
    assert summary["repair_history"] == [
        {
            "cycle": 1,
            "started_at": None,
            "reason": None,
            "failure_category": None,
            "failed_task_count": 1,
            "budget_remaining": 0,
        }
    ]
    assert summary["workflow_telemetry"]["acceptance_summary"] == {
        "policy": "required_tasks",
        "accepted": True,
        "reason": "all_required_tasks_done",
        "terminal_outcome": "completed",
        "failure_category": None,
        "evaluated_task_count": 1,
        "required_task_count": 1,
        "completed_task_count": 1,
        "failed_task_count": 0,
        "skipped_task_count": 0,
        "pending_task_count": 0,
    }
    assert summary["workflow_telemetry"]["resume_summary"] == {
        "count": 1,
        "reason_count": 1,
        "task_count": 1,
        "unique_task_count": 1,
        "last_resumed_at": "2026-03-28T12:00:00+00:00",
    }
    assert "workflow_last_resumed_at" not in summary
    assert "workflow_finished_at" not in summary
    assert summary["workflow_telemetry"]["repair_summary"] == {
        "cycle_count": 1,
        "max_cycles": 1,
        "budget_remaining": 0,
        "history_count": 1,
        "reason_count": 0,
        "last_reason_present": False,
        "failure_category_count": 0,
        "failed_task_count": 1,
    }
    assert summary["task_summaries"][0]["has_repair_origin"] is False
    assert summary["task_summaries"][1]["has_repair_origin"] is True
    assert "repair_origin_task_id" not in summary["task_summaries"][0]
    assert "repair_origin_task_id" not in summary["task_summaries"][1]


def test_build_full_workflow_config_uses_larger_completion_budget_for_full_generation(monkeypatch, tmp_path):
    from kycortex_agents.provider_matrix import build_full_workflow_config

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    config = build_full_workflow_config("openai", "gpt-4o-mini", str(tmp_path / "output"))

    assert config.max_tokens == 3200


def test_build_full_workflow_config_accepts_completion_budget_override(monkeypatch, tmp_path):
    from kycortex_agents.provider_matrix import build_full_workflow_config

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    config = build_full_workflow_config(
        "openai",
        "gpt-4o-mini",
        str(tmp_path / "output"),
        max_tokens=900,
    )

    assert config.max_tokens == 900


def test_build_full_workflow_config_applies_ollama_runtime_overrides(tmp_path):
    from kycortex_agents.provider_matrix import build_full_workflow_config

    config = build_full_workflow_config(
        "ollama",
        "qwen2.5-coder:7b",
        str(tmp_path / "output"),
        ollama_base_url="http://localhost:11435",
        ollama_num_ctx=16384,
    )

    assert config.base_url == "http://localhost:11435"
    assert config.ollama_num_ctx == 16384


def test_build_full_workflow_project_uses_explicit_compact_output_constraints(tmp_path):
    from kycortex_agents.provider_matrix import build_full_workflow_project

    project = build_full_workflow_project(str(tmp_path / "output"), "anthropic")

    code_task = project.get_task("code")
    tests_task = project.get_task("tests")
    arch_task = project.get_task("arch")

    assert arch_task is not None
    assert code_task is not None
    assert tests_task is not None
    assert "Prefer one cohesive public service surface plus domain models over separate helper-only collaborators or interface sections" in arch_task.description
    assert "Do not describe standalone RiskScorer, AuditLogger, BatchProcessor, Manager, or Processor types" in arch_task.description
    assert "Public contract anchor:" in arch_task.description
    assert "Public facade: ComplianceIntakeService" in arch_task.description
    assert "ComplianceIntakeService.handle_request(request)" in arch_task.description
    assert "ComplianceIntakeService.validate_request(request)" in arch_task.description
    assert "repeated handle_request(request) calls" in arch_task.description
    assert "under 300 lines" in code_task.description
    assert "Prefer one cohesive public service surface or a very small set of top-level functions for validation, scoring, audit logging, and batch handling" in code_task.description
    assert "Do not split those behaviors into separate Logger, Scorer, Processor, Manager, or interface classes" in code_task.description
    assert "If the architecture sketch mentions optional helper collaborators such as RiskScorer, AuditLogger, or BatchProcessor" in code_task.description
    assert "Target roughly 240 to 280 lines" in code_task.description
    assert "Leave at least 15 lines of headroom under the hard cap" in code_task.description
    assert "Implement only the minimal core flow" in code_task.description
    assert "Avoid extra helper layers" in code_task.description
    assert "Prefer in-memory service state and audit records unless the architecture explicitly requires durable persistence" in code_task.description
    assert "Implement real validation and scoring behavior instead of constant-success validators" in code_task.description
    assert "prefer a direct, easy-to-verify formula and avoid hidden caps, clamps, or arbitrary thresholds" in code_task.description
    assert "use its truth value rather than mere field presence" in code_task.description
    assert "keep object access consistent and do not mix in dict-style membership checks or subscripting" in code_task.description
    assert "place every required non-default field before any defaulted field" in code_task.description
    assert "AuditLog has required fields action and details plus a defaulted timestamp" in code_task.description
    assert "If you use dataclasses.field(...) or field(default_factory=...) anywhere in the module, import field explicitly from dataclasses" in code_task.description
    assert "If you call datetime.datetime.now() or datetime.date.today(), import datetime" in code_task.description
    assert "Public contract anchor:" in code_task.description
    assert "Public facade: ComplianceIntakeService" in code_task.description
    assert "ComplianceIntakeService.handle_request(request)" in code_task.description
    assert "ComplianceIntakeService.validate_request(request)" in code_task.description
    assert "batch_intake_requests(...)" in code_task.description
    assert "under 150 lines" in tests_task.description
    assert "at most 7 top-level test functions" in tests_task.description
    assert "Prefer 3 to 5 top-level tests" in tests_task.description
    assert "Public contract anchor:" in tests_task.description
    assert "Public facade: ComplianceIntakeService" in tests_task.description
    assert "ComplianceIntakeService.handle_request(request)" in tests_task.description
    assert "ComplianceIntakeService.validate_request(request)" in tests_task.description
    assert "Do not omit timestamp from ComplianceRequest(...) calls" in tests_task.description
    assert "invent process_batch(...), batch_process(...), batch_intake_requests(...), validate_and_score(...), or similar aliases" in tests_task.description
    assert "Unless the current implementation or behavior contract explicitly enumerates every emitted batch log, do not write len(service.audit_logs) == N" in tests_task.description
    assert "If pytest or prior repair feedback showed a mismatch such as assert 5 == 3 on len(service.audit_logs)" in tests_task.description
    assert "Leave at least one full test of headroom below the stated maximum" in tests_task.description
    assert "If you draft more than 6 for this task" in tests_task.description
    assert "Target clear headroom below the 150-line ceiling" in tests_task.description
    assert "Stay comfortably under the fixture limit" in tests_task.description
    assert "Use the direct intake or validation surface for the validation-failure scenario" in tests_task.description
    assert "omit only the field under test and keep the rest of that payload valid" in tests_task.description
    assert "If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid" in tests_task.description
    assert "Concrete class, function, and field names used in the generic examples below are placeholders only." in tests_task.description
    assert "When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models" in tests_task.description
    assert "Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols" in tests_task.description
    assert "do not shorten them to submit(...) or submit_batch(...)" in tests_task.description
    assert "When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity" in tests_task.description
    assert "pass every listed field explicitly in test instantiations, including documented defaulted fields" in tests_task.description
    assert "Do not rely on dataclass defaults just because omission would run" in tests_task.description
    assert "ComplianceRequest(id=\"1\", data={\"name\": \"John Doe\", \"amount\": 1000}, timestamp=1.0, status=\"pending\")" in tests_task.description
    assert "If the public API contract lists ComplianceRequest(id, user_id, data, timestamp, status), every constructor call in the suite must pass all five named arguments" in tests_task.description
    assert "define fixed_time first and pass timestamp=fixed_time instead of writing timestamp=request.timestamp" in tests_task.description
    assert "If the implementation exposes no dedicated batch helper" in tests_task.description
    assert "If the implementation exposes only a single-request surface such as process_request(request) and no process_batch(...)" in tests_task.description
    assert "If the implementation exposes only scalar validation, scoring, or audit helpers" in tests_task.description
    assert "If a batch helper returns None or constructs its own domain objects from raw items" in tests_task.description
    assert "Do not import or test `main`, CLI/demo entrypoints" in tests_task.description
    assert "Do not spend standalone tests on simple logging or audit helpers" in tests_task.description
    assert "do not spend top-level tests on validator units, scorers, dataclass serialization, audit loggers" in tests_task.description
    assert "Do not add standalone caplog or raw logging-output assertions" in tests_task.description
    assert "assert only records for actions actually exercised in the scenario" in tests_task.description
    assert "One invalid batch item can emit two failure-related audit entries" in tests_task.description
    assert "a two-item valid batch can emit 5 audit logs, not 3" in tests_task.description
    assert "prefer assertions on returned results, terminal batch markers, or monotonic audit growth" in tests_task.description
    assert "Never define a custom fixture named `request`" in tests_task.description
    assert "Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions" in tests_task.description
    assert "If repair feedback reports undefined local names or undefined fixtures" in tests_task.description
    assert "If repair feedback reports helper surface usages" in tests_task.description
    assert "If the suite uses the `pytest.` namespace anywhere, add `import pytest` explicitly at the top of the file" in tests_task.description
    assert "Do not assume empty strings, placeholder IDs, or domain keywords are invalid" in tests_task.description
    assert "request_id=\"\" or another same-type placeholder can still pass" in tests_task.description
    assert "empty dict is still a same-type placeholder and may pass when validation only checks dict type" in tests_task.description
    assert "ComplianceData(id=\"1\", data={\"key\": \"wrong_value\"}) is still valid input and should be asserted as a non-compliant result" in tests_task.description
    assert "Do not write a validation-failure test as assert not validate_request(...)" in tests_task.description
    assert "choose an input that validate_request rejects before scoring runs" in tests_task.description
    assert "If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict)" in tests_task.description
    assert "do not create a separate invalid-scoring test that first calls intake_request on an invalid object" in tests_task.description
    assert "ComplianceRequest(id=\"\", data={\"field\": \"value\"}) still passes" in tests_task.description
    assert "do not assume a wrong nested value type makes the request invalid" in tests_task.description
    assert "risk_factor=\"invalid\" does not raise TypeError" in tests_task.description
    assert "If the implementation exposes only helper-level audit or logging functions" in tests_task.description
    assert "If the implementation exposes validate_request(request), score_request(request), and log_audit(request_id, action, result), write exactly three tests" in tests_task.description
    assert "use trivially countable inputs rather than prose strings" in tests_task.description
    assert "If an exact numeric assertion depends on nested payload shape" in tests_task.description
    assert "avoid threshold boundary values unless the contract explicitly defines those cutoffs" in tests_task.description
    assert "do not use amount=100 to assert an exact label" in tests_task.description
    assert "do not use borderline counts such as 2 to assert an exact low or medium label" in tests_task.description
    assert "Do not infer `FLAGGED` status, non-zero flagged/report counters" in tests_task.description
    assert "Prefer assertions on directly observable totals, persisted submissions, audit growth, or non-negative scores" in tests_task.description
    assert "do not assume that field was normalized to only an inner sub-dict" in tests_task.description
    assert "Never redeclare production dataclasses, business functions, CLI parsers, or other implementation code inside the pytest module" in tests_task.description
    assert "Do not turn copied implementation into `test_main`, `test_all_tests`, or similar meta-tests" in tests_task.description
    assert "Do not compare full audit or log file contents by exact string equality" in tests_task.description
    assert "Do not assert an exact runtime numeric type such as float unless the contract or current implementation explicitly casts to that type" in tests_task.description
    assert "compute it from only the branches exercised by the chosen input instead of summing unrelated categories" in tests_task.description
    assert "should assert 1, not 3" in tests_task.description
    assert "risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25" in tests_task.description
    assert "Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger" in tests_task.description
    assert "If an exact numeric assertion depends on top-level dict size or collection size" in tests_task.description
    assert "do not invent a guessed exact total such as 6.0 or a derived level such as medium" in tests_task.description
    assert "do not pair exact score equality with word-like sample strings such as data, valid_data, or data1" in tests_task.description
    assert "use xxxxxxxxxx rather than \"\"" in tests_task.description
    assert "either omit the optional filter dict or provide every documented required filter key" in tests_task.description
    assert "If you use isinstance or another exact type assertion against a returned production class, import that class explicitly" in tests_task.description
    assert "use repeated-character or similarly obvious inputs rather than natural-language sample text" in tests_task.description


def test_provider_matrix_summary_reports_failed_non_repair_tasks(tmp_path):
    from kycortex_agents.provider_matrix import summarize_workflow_run

    project = ProjectState(
        project_name="Demo",
        goal="Validate provider summary output",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.phase = "failed"
    project.terminal_outcome = "failed"
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Run tests",
            assigned_to="qa_tester",
            status="failed",
        )
    )
    project.add_task(
        Task(
            id="tests__repair_1",
            title="Tests Repair",
            description="Repair tests",
            assigned_to="qa_tester",
            status="failed",
            repair_origin_task_id="tests",
            repair_attempt=1,
        )
    )

    summary = summarize_workflow_run(
        project,
        provider="openai",
        model="gpt-4o-mini",
        output_dir=str(tmp_path / "output"),
    )

    assert summary["failed_task_count"] == 1


def test_provider_matrix_summary_redacts_public_error_and_project_name_fields(tmp_path):
    from kycortex_agents.provider_matrix import summarize_workflow_run

    project = ProjectState(
        project_name="Demo api_key=sk-secret-123456",
        goal="Validate provider summary output",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.phase = "failed"
    project.terminal_outcome = "failed"
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Run tests",
            assigned_to="qa_tester",
            status="failed",
            last_error="Authorization: Bearer sk-ant-secret-987654",
            last_error_type="RuntimeError",
            last_error_category="task_execution",
        )
    )

    summary = summarize_workflow_run(
        project,
        provider="openai",
        model="gpt-4o-mini",
        output_dir="api_key=sk-secret-123456/output",
    )

    assert summary["project_name"] == "Demo api_key=[REDACTED]"
    assert summary["state_file"] == "project_state.json"
    assert summary["output_dir"] == "output"
    task_summary = summary["task_summaries"][0]
    assert task_summary["last_error_present"] is True
    assert task_summary["last_error_category"] == "task_execution"
    assert task_summary["has_provider_call"] is False
    assert "last_error" not in task_summary
    assert "last_error_type" not in task_summary
    assert "provider_budget" not in task_summary
    assert "sk-secret-123456" not in json.dumps(summary)
    assert "sk-ant-secret-987654" not in json.dumps(summary)


def test_provider_matrix_summary_limits_public_path_fields_to_filenames():
    from kycortex_agents.provider_matrix import summarize_workflow_run

    project = ProjectState(
        project_name="Demo",
        goal="Validate provider summary output",
        state_file="/srv/acme-customer/provider-runs/project_state.json",
    )
    project.phase = "completed"
    project.terminal_outcome = "completed"

    summary = summarize_workflow_run(
        project,
        provider="openai",
        model="gpt-4o-mini",
        output_dir="/srv/acme-customer/provider-runs/output",
    )

    assert summary["state_file"] == "project_state.json"
    assert summary["output_dir"] == "output"
    assert "acme-customer" not in json.dumps(summary)


def test_write_summary_json_redacts_sensitive_strings_before_persisting(tmp_path):
    from kycortex_agents.provider_matrix import write_summary_json

    summary_path = tmp_path / "provider_matrix_summary.json"
    write_summary_json(
        {
            "project_name": "Demo api_key=sk-secret-123456",
            "task_summaries": [
                {"last_error": "Authorization: Bearer sk-ant-secret-987654"}
            ],
        },
        str(summary_path),
    )

    persisted = json.loads(summary_path.read_text(encoding="utf-8"))

    assert persisted["project_name"] == "Demo api_key=[REDACTED]"
    assert persisted["task_summaries"][0]["last_error"] == "Authorization: Bearer [REDACTED]"
    assert "sk-secret-123456" not in summary_path.read_text(encoding="utf-8")
    assert "sk-ant-secret-987654" not in summary_path.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only permission hardening")
def test_write_summary_json_uses_private_file_permissions(tmp_path):
    from kycortex_agents.provider_matrix import write_summary_json

    summary_path = tmp_path / "reports" / "provider_matrix_summary.json"

    write_summary_json({"provider": "openai", "available": True}, str(summary_path))

    assert stat.S_IMODE(summary_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only permission hardening")
def test_write_summary_json_uses_private_directory_permissions(tmp_path):
    from kycortex_agents.provider_matrix import write_summary_json

    summary_path = tmp_path / "reports" / "provider_matrix_summary.json"

    write_summary_json({"provider": "openai", "available": True}, str(summary_path))

    assert stat.S_IMODE(summary_path.parent.stat().st_mode) == 0o700


def test_provider_matrix_summary_limits_public_task_metadata(tmp_path):
    from kycortex_agents.provider_matrix import summarize_workflow_run

    project = ProjectState(
        project_name="Demo",
        goal="Validate provider summary output",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status="done",
            last_provider_call={
                "provider_call_count": 2,
                "provider_call_counts_by_provider": {"openai": 1, "anthropic": 1},
                "provider_max_calls_per_agent": 3,
                "provider_max_calls_per_provider": {"openai": 2},
                "provider_remaining_calls": 1,
                "provider_remaining_calls_by_provider": {"openai": 1},
            },
        )
    )

    summary = summarize_workflow_run(
        project,
        provider="openai",
        model="gpt-4o-mini",
        output_dir=str(tmp_path / "output"),
    )

    task_summary = summary["task_summaries"][0]

    assert task_summary["has_assigned_to"] is True
    assert task_summary["has_provider_call"] is True
    assert task_summary["last_error_present"] is False
    assert "assigned_to" not in task_summary
    assert "provider_budget" not in task_summary
    assert "last_error_type" not in task_summary


def test_provider_matrix_resolve_model_handles_override_and_ollama_probe(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    assert resolve_model("openai", None) == "gpt-4o-mini"
    assert resolve_model("ollama", "custom-model") == "custom-model"

    seen_urls: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "llama3.2:latest"}]}).encode("utf-8")

    def fake_urlopen(request, *args, **kwargs):
        seen_urls.append(request.full_url)
        return Response()

    assert resolve_model("ollama", None, ollama_base_url="http://localhost:11435", urlopen_fn=fake_urlopen) == "llama3.2:latest"
    assert seen_urls == ["http://localhost:11435/api/tags"]


def test_provider_matrix_resolve_model_uses_ollama_host_env_when_override_absent(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    seen_urls: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "qwen2.5-coder:7b"}]}).encode("utf-8")

    def fake_urlopen(request, *args, **kwargs):
        seen_urls.append(request.full_url)
        return Response()

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:15000")

    assert resolve_model("ollama", None, urlopen_fn=fake_urlopen) == "qwen2.5-coder:7b"
    assert seen_urls == ["http://127.0.0.1:15000/api/tags"]


def test_provider_matrix_resolve_model_prefers_default_when_installed(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3.2:latest"}]}).encode("utf-8")

    monkeypatch.setattr("kycortex_agents.provider_matrix.urlopen", lambda *args, **kwargs: Response())

    assert resolve_model("ollama", None) == "qwen2.5-coder:7b"


def test_provider_matrix_resolve_model_falls_back_when_probe_returns_no_models(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"models": []}).encode("utf-8")

    monkeypatch.setattr("kycortex_agents.provider_matrix.urlopen", lambda *args, **kwargs: Response())

    assert resolve_model("ollama", None) == "qwen2.5-coder:7b"


def test_provider_matrix_resolve_model_falls_back_to_default_when_ollama_probe_fails(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    monkeypatch.setattr(
        "kycortex_agents.provider_matrix.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )

    assert resolve_model("ollama", None) == "qwen2.5-coder:7b"


def test_provider_matrix_resolve_model_falls_back_to_default_when_ollama_probe_raises_oserror(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    monkeypatch.setattr(
        "kycortex_agents.provider_matrix.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionRefusedError("offline")),
    )

    assert resolve_model("ollama", None) == "qwen2.5-coder:7b"


def test_provider_matrix_availability_uses_custom_ollama_base_url():
    from kycortex_agents.provider_matrix import get_provider_availability

    seen_urls: list[str] = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout=5):
        seen_urls.append(request.full_url)
        return Response()

    availability = get_provider_availability(
        "ollama",
        ollama_base_url="http://localhost:11435",
        urlopen_fn=fake_urlopen,
    )

    assert availability == {
        "provider": "ollama",
        "available": True,
        "reason": None,
    }
    assert seen_urls == ["http://localhost:11435/api/tags"]


def test_provider_matrix_availability_uses_ollama_host_env_when_override_absent(monkeypatch):
    from kycortex_agents.provider_matrix import get_provider_availability

    seen_urls: list[str] = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout=5):
        seen_urls.append(request.full_url)
        return Response()

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:15000")

    availability = get_provider_availability(
        "ollama",
        urlopen_fn=fake_urlopen,
    )

    assert availability == {
        "provider": "ollama",
        "available": True,
        "reason": None,
    }
    assert seen_urls == ["http://127.0.0.1:15000/api/tags"]


def test_provider_matrix_availability_uses_env_vars_and_ollama_probe(monkeypatch):
    from kycortex_agents.provider_matrix import get_provider_availability

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    assert get_provider_availability("openai")["available"] is False
    assert get_provider_availability("anthropic")["available"] is False
    assert get_provider_availability("ollama", urlopen_fn=lambda *args, **kwargs: Response())["available"] is True


def test_provider_matrix_availability_respects_explicit_empty_environ():
    from kycortex_agents.provider_matrix import get_provider_availability

    availability = get_provider_availability("openai", environ={})

    assert availability == {
        "provider": "openai",
        "available": False,
        "reason": "missing OPENAI_API_KEY",
    }


def test_provider_matrix_availability_reports_unknown_provider_and_ollama_failure():
    from kycortex_agents.provider_matrix import get_provider_availability

    try:
        get_provider_availability("custom")
    except ValueError as exc:
        assert "Unsupported provider: custom" in str(exc)
    else:  # pragma: no cover - safety assertion
        raise AssertionError("Expected unsupported provider to raise ValueError")

    availability = get_provider_availability(
        "ollama",
        urlopen_fn=lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    assert availability == {
        "provider": "ollama",
        "available": False,
        "reason": "ollama tags endpoint unreachable",
    }


def test_build_full_workflow_project_contains_expected_dependency_graph(tmp_path):
    from kycortex_agents.provider_matrix import build_full_workflow_project

    project = build_full_workflow_project(str(tmp_path / "output"), "ollama")
    code_task = project.get_task("code")
    tests_task = project.get_task("tests")
    legal_task = project.get_task("legal")

    assert code_task is not None
    assert tests_task is not None
    assert legal_task is not None

    assert [task.id for task in project.tasks] == ["arch", "code", "deps", "tests", "review", "docs", "legal"]
    assert code_task.dependencies == ["arch"]
    assert tests_task.dependencies == ["code", "deps"]
    assert legal_task.dependencies == ["docs"]


def test_write_summary_json_persists_sorted_payload(tmp_path):
    from kycortex_agents.provider_matrix import write_summary_json

    path = tmp_path / "summary" / "provider_summary.json"
    write_summary_json({"b": 2, "a": 1}, str(path))

    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "b": 2}


def test_provider_matrix_example_skips_unavailable_provider(tmp_path, monkeypatch):
    module = _load_example_module(
        "example_provider_matrix_validation_test",
        "examples/example_provider_matrix_validation.py",
    )

    monkeypatch.setattr(
        module,
        "get_provider_availability",
        lambda provider: {"provider": provider, "available": False, "reason": "missing credentials"},
    )

    result = module.run_provider(
        "openai",
        output_root=str(tmp_path / "matrix"),
        failure_policy="continue",
        resume_policy="resume_failed",
        max_repair_cycles=1,
    )

    assert result == {
        "provider": "openai",
        "available": False,
        "has_availability_reason": True,
        "status": "skipped",
    }


def test_provider_matrix_example_limits_public_availability_reason(tmp_path, monkeypatch, capsys):
    module = _load_example_module(
        "example_provider_matrix_validation_public_availability_reason_test",
        "examples/example_provider_matrix_validation.py",
    )

    summary_path = tmp_path / "provider_matrix_summary.json"

    class FakeParser:
        def parse_args(self):
            return argparse.Namespace(
                providers=["openai"],
                output_root=str(tmp_path / "matrix"),
                failure_policy="continue",
                resume_policy="resume_failed",
                max_repair_cycles=1,
                summary_json=str(summary_path),
                ollama_base_url=None,
                ollama_num_ctx=16384,
                max_tokens=3200,
            )

    monkeypatch.setattr(module, "build_parser", lambda: FakeParser())
    monkeypatch.setattr(module, "resolve_requested_providers", lambda providers: providers)
    monkeypatch.setattr(
        module,
        "run_provider",
        lambda provider, **kwargs: {
            "provider": provider,
            "available": False,
            "has_availability_reason": True,
            "status": "skipped",
        },
    )

    module.main()

    persisted_text = summary_path.read_text(encoding="utf-8")
    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "provider=present" in captured
    assert "available=False" in captured
    assert "status=skipped" in captured
    assert "availability_reason_present=present" in captured
    assert '"has_availability_reason": true' in persisted_text
    assert '"availability_reason"' not in persisted_text
    assert "missing credentials" not in rendered


def test_provider_matrix_parser_defaults_to_all_supported_providers():
    module = _load_example_module(
        "example_provider_matrix_validation_parser_test",
        "examples/example_provider_matrix_validation.py",
    )

    args = module.build_parser().parse_args([])

    assert args.providers == []
    assert module.resolve_requested_providers(args.providers) == ["anthropic", "ollama", "openai"]


def test_multi_provider_example_limits_public_output_dir_and_base_url(capsys, monkeypatch):
    module = _load_example_module(
        "example_multi_provider_public_output_test",
        "examples/example_multi_provider.py",
    )

    monkeypatch.setattr(
        module,
        "build_provider_configs",
        lambda: {
            "openai": type(
                "Config",
                (),
                {
                    "llm_model": "gpt-4o-mini",
                    "output_dir": "/srv/customer-secret-root/openai",
                    "base_url": None,
                },
            )(),
            "anthropic": type(
                "Config",
                (),
                {
                    "llm_model": "claude-haiku-4-5-20251001",
                    "output_dir": "/srv/customer-secret-root/anthropic",
                    "base_url": None,
                },
            )(),
            "ollama": type(
                "Config",
                (),
                {
                    "llm_model": "qwen2.5-coder:7b",
                    "output_dir": "/srv/customer-secret-root/ollama",
                    "base_url": "http://operator:secret@localhost:11435/private/api",
                },
            )(),
        },
    )

    module.main()

    captured = capsys.readouterr().out.splitlines()

    assert "  output_dir: openai" in captured
    assert "  output_dir: anthropic" in captured
    assert "  output_dir: ollama" in captured
    assert "  base_url: localhost:11435" in captured
    assert all("customer-secret-root" not in line for line in captured)
    assert all("operator" not in line for line in captured)
    assert all("secret" not in line for line in captured)
    assert all("private/api" not in line for line in captured)


def test_provider_matrix_parser_accepts_ollama_runtime_overrides():
    module = _load_example_module(
        "example_provider_matrix_validation_parser_ollama_override_test",
        "examples/example_provider_matrix_validation.py",
    )

    args = module.build_parser().parse_args(
        [
            "ollama",
            "--ollama-base-url",
            "http://localhost:11435",
            "--ollama-num-ctx",
            "16384",
        ]
    )

    assert args.providers == ["ollama"]
    assert args.ollama_base_url == "http://localhost:11435"
    assert args.ollama_num_ctx == 16384


def test_provider_matrix_parser_accepts_max_tokens_override():
    module = _load_example_module(
        "example_provider_matrix_validation_parser_max_tokens_override_test",
        "examples/example_provider_matrix_validation.py",
    )

    args = module.build_parser().parse_args([
        "openai",
        "--max-tokens",
        "900",
    ])

    assert args.providers == ["openai"]
    assert args.max_tokens == 900


def test_provider_matrix_parser_rejects_unsupported_provider():
    module = _load_example_module(
        "example_provider_matrix_validation_parser_invalid_provider_test",
        "examples/example_provider_matrix_validation.py",
    )

    try:
        module.resolve_requested_providers(["invalid-provider"])
    except SystemExit as exc:
        assert str(exc) == (
            "Unsupported providers: invalid-provider. Supported providers: anthropic, ollama, openai."
        )
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected unsupported provider to raise SystemExit")


def test_provider_matrix_example_limits_public_report_paths_and_base_url(tmp_path, monkeypatch, capsys):
    module = _load_example_module(
        "example_provider_matrix_validation_public_report_test",
        "examples/example_provider_matrix_validation.py",
    )

    output_root = tmp_path / "customer-secret-root" / "provider-runs"
    summary_path = tmp_path / "customer-secret-root" / "reports" / "provider_matrix_summary.json"

    class FakeParser:
        def parse_args(self):
            return argparse.Namespace(
                providers=["ollama"],
                output_root=str(output_root),
                failure_policy="continue",
                resume_policy="resume_failed",
                max_repair_cycles=1,
                summary_json=str(summary_path),
                ollama_base_url="http://operator:secret@localhost:11435/private/api",
                ollama_num_ctx=16384,
                max_tokens=3200,
            )

    monkeypatch.setattr(module, "build_parser", lambda: FakeParser())
    monkeypatch.setattr(module, "resolve_requested_providers", lambda providers: providers)
    monkeypatch.setattr(
        module,
        "run_provider",
        lambda provider, **kwargs: {
            "provider": provider,
            "available": True,
            "status": "completed",
            "summary": {
                "phase": "completed",
                "terminal_outcome": "completed",
                "repair_cycle_count": 0,
            },
        },
    )

    module.main()

    persisted_text = summary_path.read_text(encoding="utf-8")
    persisted = json.loads(persisted_text)
    captured = capsys.readouterr().out.splitlines()

    assert persisted["output_root"] == "provider-runs"
    assert persisted["ollama_base_url"] == "localhost:11435"
    assert "provider=present" in captured
    assert "repair_cycles_present=none" in captured
    assert "repair_cycle_count=0" not in "\n".join(captured)
    assert "provider=ollama" not in "\n".join(captured)
    assert "customer-secret-root" not in persisted_text
    assert "operator" not in persisted_text
    assert "secret" not in persisted_text
    assert "private/api" not in persisted_text
    assert "summary_json=provider_matrix_summary.json" in captured
    assert all("customer-secret-root" not in line for line in captured)


def test_release_user_smoke_example_limits_public_console_paths(tmp_path, monkeypatch, capsys):
    module = _load_example_module(
        "example_release_user_smoke_public_paths_test",
        "examples/example_release_user_smoke.py",
    )

    output_dir = tmp_path / "customer-secret-root" / "release-user-smoke"
    validated_artifact = output_dir / "artifacts" / "budget_planner.py"

    class FakeParser:
        def parse_args(self):
            return argparse.Namespace(
                provider="ollama",
                model=None,
                output_dir=str(output_dir),
                base_url=None,
                ollama_num_ctx=16384,
                failure_policy="continue",
                max_repair_cycles=1,
            )

    class FakeOrchestrator:
        def __init__(self, config):
            self.config = config

        def execute_workflow(self, project):
            return None

    code_task = Task(
        id="code",
        title="Implementation",
        description="Implement the budget planner",
        assigned_to="code_engineer",
        status="done",
        output=(
            "api_key=sk-secret-123456\n"
            "def calculate_budget_balance(income, expenses):\n"
            "    return income - sum(expenses)\n"
        ),
    )
    code_task.output_payload = {"artifacts": [{"path": "artifacts/budget_planner.py"}]}
    fake_project = type(
        "FakeProject",
        (),
        {
            "phase": "completed",
            "terminal_outcome": "completed",
            "repair_cycle_count": 0,
            "tasks": [code_task],
        },
    )()

    monkeypatch.setattr(module, "build_parser", lambda: FakeParser())
    monkeypatch.setattr(module, "build_config", lambda args, output_dir: type("Config", (), {"llm_model": "qwen2.5-coder:7b"})())
    monkeypatch.setattr(module, "build_project", lambda output_dir, provider: fake_project)
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        module,
        "_validate_generated_code",
        lambda task, output_dir: (2650.0, str(validated_artifact)),
    )

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "provider=present" in captured
    assert "model=present" in captured
    assert "output_dir=release-user-smoke" in captured
    assert "repair_cycles_present=none" in captured
    assert "repair_cycle_count=0" not in rendered
    assert "provider=ollama" not in rendered
    assert "model=qwen2.5-coder:7b" not in rendered
    assert "budget_planner.py" in captured
    assert "validated_artifact=budget_planner.py" in captured
    assert "output_present=present" in captured
    assert "preview=" not in rendered
    assert "calculate_budget_balance" not in rendered
    assert "sk-secret-123456" not in rendered
    assert all("artifacts/budget_planner.py" not in line for line in captured)
    assert all("customer-secret-root" not in line for line in captured)


def test_release_user_smoke_validation_errors_limit_public_artifact_path_to_filename(tmp_path, monkeypatch):
    module = _load_example_module(
        "example_release_user_smoke_validation_error_test",
        "examples/example_release_user_smoke.py",
    )

    output_dir = tmp_path / "customer-secret-root" / "release-user-smoke"
    artifact_path = output_dir / "artifacts" / "budget_planner.py"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        "def calculate_budget_balance(income: float, expenses: list[float]) -> float:\n    return income - sum(expenses)\n",
        encoding="utf-8",
    )

    code_task = Task(
        id="code",
        title="Implementation",
        description="Implement the budget planner",
        assigned_to="code_engineer",
        status="done",
    )
    code_task.output_payload = {"artifacts": [{"path": "artifacts/budget_planner.py"}]}

    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError) as exc_info:
        module._validate_generated_code(code_task, str(output_dir))

    assert str(exc_info.value) == "Could not load generated code artifact: budget_planner.py"
    assert "customer-secret-root" not in str(exc_info.value)


def test_provider_matrix_example_passes_completion_budget_override(tmp_path, monkeypatch):
    module = _load_example_module(
        "example_provider_matrix_validation_run_provider_max_tokens_test",
        "examples/example_provider_matrix_validation.py",
    )

    monkeypatch.setattr(
        module,
        "get_provider_availability",
        lambda provider: {"provider": provider, "available": True, "reason": None},
    )
    monkeypatch.setattr(module, "resolve_model", lambda provider, model_override=None: "gpt-4o-mini")

    captured: dict[str, object] = {}

    def fake_build_full_workflow_config(provider, model, output_dir, **kwargs):
        captured["provider"] = provider
        captured["model"] = model
        captured["output_dir"] = output_dir
        captured.update(kwargs)
        return object()

    class FakeProject:
        phase = "completed"
        terminal_outcome = "completed"
        repair_cycle_count = 0

    monkeypatch.setattr(module, "build_full_workflow_config", fake_build_full_workflow_config)
    monkeypatch.setattr(module, "build_full_workflow_project", lambda output_dir, provider: FakeProject())
    monkeypatch.setattr(module, "execute_empirical_validation_workflow", lambda config, project: None)
    monkeypatch.setattr(
        module,
        "summarize_workflow_run",
        lambda project, provider, model, output_dir: {
            "phase": "completed",
            "terminal_outcome": "completed",
            "repair_cycle_count": 0,
        },
    )

    result = module.run_provider(
        "openai",
        output_root=str(tmp_path / "matrix"),
        failure_policy="continue",
        resume_policy="resume_failed",
        max_repair_cycles=1,
        max_tokens=900,
    )

    assert captured["provider"] == "openai"
    assert captured["model"] == "gpt-4o-mini"
    assert captured["max_tokens"] == 900
    assert result["summary"]["repair_cycle_count"] == 0


def test_provider_matrix_example_limits_public_execution_error_message(tmp_path, monkeypatch):
    module = _load_example_module(
        "example_provider_matrix_validation_execution_error_test",
        "examples/example_provider_matrix_validation.py",
    )

    monkeypatch.setattr(
        module,
        "get_provider_availability",
        lambda provider: {"provider": provider, "available": True, "reason": None},
    )
    monkeypatch.setattr(module, "resolve_model", lambda provider, model_override=None: "gpt-4o-mini")
    monkeypatch.setattr(module, "build_full_workflow_config", lambda *args, **kwargs: object())
    monkeypatch.setattr(module, "build_full_workflow_project", lambda output_dir, provider: object())

    def fake_execute_empirical_validation_workflow(config, project):
        raise RuntimeError("api_key=sk-secret-123456")

    monkeypatch.setattr(module, "execute_empirical_validation_workflow", fake_execute_empirical_validation_workflow)
    monkeypatch.setattr(
        module,
        "summarize_workflow_run",
        lambda project, provider, model, output_dir: {"phase": "failed", "terminal_outcome": "failed", "repair_cycle_count": 0},
    )

    result = module.run_provider(
        "openai",
        output_root=str(tmp_path / "matrix"),
        failure_policy="continue",
        resume_policy="resume_failed",
        max_repair_cycles=1,
    )

    assert result["provider"] == "openai"
    assert result["status"] == "execution_error"
    assert result["error_type"] == "RuntimeError"
    assert result["has_error_message"] is True
    assert "error_message" not in result


def test_execute_empirical_validation_workflow_consumes_bounded_repair_cycle(monkeypatch, tmp_path):
    import kycortex_agents.provider_matrix as provider_matrix

    config = provider_matrix.build_full_workflow_config(
        "ollama",
        "llama3",
        str(tmp_path / "output"),
        workflow_failure_policy="continue",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(
        project_name="Demo",
        goal="Exercise empirical repair loop",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.repair_max_cycles = 1
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))

    class FakeOrchestrator:
        def __init__(self, _config):
            self.config = _config

        def execute_workflow(self, state):
            arch = state.get_task("arch")
            if state.repair_cycle_count == 0:
                arch.status = "failed"
                state.phase = "failed"
                return
            arch.status = "done"
            state.phase = "completed"

    original_can_start_repair_cycle = project.can_start_repair_cycle

    def fake_can_start_repair_cycle():
        current_arch_task = project.get_task("arch")
        assert current_arch_task is not None
        if project.repair_cycle_count == 0 and current_arch_task.status == "failed":
            return True
        return original_can_start_repair_cycle()

    monkeypatch.setattr(project, "can_start_repair_cycle", fake_can_start_repair_cycle)

    original_execute_workflow = FakeOrchestrator.execute_workflow

    def wrapped_execute_workflow(self, state):
        current_arch_task = state.get_task("arch")
        assert current_arch_task is not None
        if state.repair_cycle_count == 0 and current_arch_task.status == "failed":
            state.start_repair_cycle(reason="retry failed arch", failed_task_ids=["arch"])
        original_execute_workflow(self, state)
        current_arch_task = state.get_task("arch")
        assert current_arch_task is not None
        if state.repair_cycle_count == 1 and current_arch_task.status == "done":
            repair_task = state.get_task("arch__repair_1")
            if repair_task is None:
                state.add_task(
                    Task(
                        id="arch__repair_1",
                        title="Architecture Repair",
                        description="Repair architecture",
                        assigned_to="architect",
                        repair_origin_task_id="arch",
                        repair_attempt=1,
                        status="done",
                    )
                )

    FakeOrchestrator.execute_workflow = wrapped_execute_workflow

    monkeypatch.setattr(provider_matrix, "Orchestrator", FakeOrchestrator)

    provider_matrix.execute_empirical_validation_workflow(config, project)

    arch_task = project.get_task("arch")
    repair_task = project.get_task("arch__repair_1")

    assert arch_task is not None
    assert repair_task is not None
    assert arch_task.status == "done"
    assert project.repair_cycle_count == 1
    assert repair_task.repair_origin_task_id == "arch"


def test_execute_empirical_validation_workflow_raises_last_error_when_resume_is_disabled(monkeypatch, tmp_path):
    import kycortex_agents.provider_matrix as provider_matrix

    config = provider_matrix.build_full_workflow_config(
        "ollama",
        "llama3",
        str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="interrupted_only",
        workflow_max_repair_cycles=0,
    )
    project = ProjectState(
        project_name="Demo",
        goal="Exercise non-resumable failure path",
        state_file=str(tmp_path / "project_state.json"),
    )

    class AlwaysFailingOrchestrator:
        def __init__(self, _config):
            self.config = _config

        def execute_workflow(self, state):
            state.phase = "failed"
            raise RuntimeError("provider boom")

    monkeypatch.setattr(provider_matrix, "Orchestrator", AlwaysFailingOrchestrator)

    try:
        provider_matrix.execute_empirical_validation_workflow(config, project)
    except RuntimeError as exc:
        assert str(exc) == "provider boom"
    else:  # pragma: no cover - safety assertion
        raise AssertionError("Expected runtime error to propagate when resume is disabled")


def test_execute_empirical_validation_workflow_does_not_resume_non_repairable_failures(monkeypatch, tmp_path):
    import kycortex_agents.provider_matrix as provider_matrix

    config = provider_matrix.build_full_workflow_config(
        "ollama",
        "llama3",
        str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(
        project_name="Demo",
        goal="Exercise non-repairable provider failure path",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.repair_max_cycles = 1
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    execute_calls = {"count": 0}

    class NonRepairableFailingOrchestrator:
        def __init__(self, _config):
            self.config = _config

        def execute_workflow(self, state):
            execute_calls["count"] += 1
            if execute_calls["count"] > 1:
                raise AssertionError("execute_workflow resumed a non-repairable failure")

            arch = state.get_task("arch")
            assert arch is not None
            arch.status = "failed"
            arch.last_error = "provider boom"
            arch.last_error_type = "ProviderTransientError"
            arch.last_error_category = "provider_transient"
            state.mark_workflow_finished(
                "failed",
                acceptance_policy=self.config.workflow_acceptance_policy,
                terminal_outcome="failed",
                failure_category="provider_transient",
                acceptance_criteria_met=False,
                acceptance_evaluation={"policy": self.config.workflow_acceptance_policy, "accepted": False},
            )
            raise RuntimeError("provider boom")

    monkeypatch.setattr(provider_matrix, "Orchestrator", NonRepairableFailingOrchestrator)

    try:
        provider_matrix.execute_empirical_validation_workflow(config, project)
    except RuntimeError as exc:
        assert str(exc) == "provider boom"
    else:  # pragma: no cover - safety assertion
        raise AssertionError("Expected non-repairable provider failure to propagate")

    workflow_finished_events = [
        event for event in project.execution_events if event.get("event") == "workflow_finished"
    ]
    assert execute_calls["count"] == 1
    assert len(workflow_finished_events) == 1
    assert project.failure_category == "provider_transient"
    assert project.repair_cycle_count == 0


def test_execute_empirical_validation_workflow_does_not_resume_cancelled_workflow(monkeypatch, tmp_path):
    import kycortex_agents.provider_matrix as provider_matrix

    config = provider_matrix.build_full_workflow_config(
        "ollama",
        "llama3",
        str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(
        project_name="Demo",
        goal="Exercise cancelled workflow path",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))
    execute_calls = {"count": 0}

    class CancelledOrchestrator:
        def __init__(self, _config):
            self.config = _config

        def execute_workflow(self, state):
            execute_calls["count"] += 1
            if execute_calls["count"] > 1:
                raise AssertionError("execute_workflow resumed a cancelled workflow")
            state.cancel_workflow(reason="manual_operator_cancel")

    monkeypatch.setattr(provider_matrix, "Orchestrator", CancelledOrchestrator)

    provider_matrix.execute_empirical_validation_workflow(config, project)

    assert execute_calls["count"] == 1
    assert project.terminal_outcome == WorkflowOutcome.CANCELLED.value
    assert project.phase == WorkflowStatus.CANCELLED.value