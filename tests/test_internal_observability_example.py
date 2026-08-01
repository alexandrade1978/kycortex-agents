import importlib.util
import sys
from pathlib import Path


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


def test_internal_observability_report_example_renders_adapter_backed_output(capsys, monkeypatch):
    module = _load_example_module(
        "example_internal_observability_report_test",
        "examples/example_internal_observability_report.py",
    )

    fake_view = {
        "source": {
            "state_file": "/srv/customer-secret-root/internal-observability/project_state.sqlite",
            "state_store_kind": "sqlite",
            "schema_version": 3,
        },
        "workflow_overview": {
            "project_name": "Demo",
            "goal": "Build demo",
            "workflow_status": "failed",
            "phase": "review",
            "acceptance_policy": "strict",
            "terminal_outcome": "failed",
            "failure_category": "test_validation",
            "acceptance_criteria_met": False,
            "acceptance_evaluation": {},
            "updated_at": "2026-05-19T14:00:00+00:00",
            "task_count": 2,
            "task_status_counts": {"done": 1, "failed": 1},
            "tasks_with_provider_calls": 2,
            "tasks_without_provider_calls": 0,
            "final_providers": ["anthropic", "openai"],
            "observed_providers": ["anthropic", "openai"],
            "attempt_count": 2,
            "retry_attempt_count": 1,
            "duration_ms": {"count": 2, "total": 52.5, "min": 12.5, "max": 40, "avg": 26.25},
            "usage": {"completion_tokens": 2, "prompt_tokens": 8},
        },
        "task_timeline": [
            {
                "task_id": "code",
                "title": "Implementation",
                "description": "Implement the application",
                "dependencies": [],
                "repair_origin_task_id": None,
                "assigned_to": "code_engineer",
                "status": "done",
                "has_output": True,
                "has_failure": False,
                "started_at": "2026-03-22T10:00:00+00:00",
                "last_attempt_started_at": "2026-03-22T10:01:00+00:00",
                "completed_at": "2026-03-22T10:03:00+00:00",
                "provider": "openai",
                "model": "gpt-4.1",
                "success": True,
                "attempts_used": 2,
                "retry_attempt_count": 1,
                "task_duration_ms": 180000,
                "last_attempt_duration_ms": 120000,
                "provider_duration_ms": 12.5,
                "provider_latency_ms": 9.5,
                "usage": {"completion_tokens": 2, "prompt_tokens": 5},
                "provider_health": {},
            },
            {
                "task_id": "review",
                "title": "Review",
                "description": "Review the changes",
                "dependencies": ["code"],
                "repair_origin_task_id": None,
                "assigned_to": "code_reviewer",
                "status": "failed",
                "has_output": False,
                "has_failure": True,
                "started_at": "2026-03-22T10:04:00+00:00",
                "last_attempt_started_at": "2026-03-22T10:05:00+00:00",
                "completed_at": "2026-03-22T10:07:00+00:00",
                "provider": "anthropic",
                "model": "claude-sonnet-4",
                "success": False,
                "attempts_used": 0,
                "retry_attempt_count": 0,
                "task_duration_ms": 180000,
                "last_attempt_duration_ms": 120000,
                "provider_duration_ms": 40,
                "provider_latency_ms": 30,
                "usage": {"prompt_tokens": 3},
                "provider_health": {},
            },
        ],
        "provider_panels": [
            {
                "provider": "anthropic",
                "task_count": 1,
                "success_count": 0,
                "failure_count": 1,
                "attempt_count": 0,
                "retry_attempt_count": 0,
                "models": ["claude-sonnet-4"],
                "duration_ms": {"count": 1, "total": 40, "min": 40, "max": 40, "avg": 40},
                "usage": {"prompt_tokens": 3},
                "status_counts": {},
                "last_outcome_counts": {},
                "retryable_failure_count": 0,
                "active_health_check_count": 0,
            },
            {
                "provider": "openai",
                "task_count": 1,
                "success_count": 1,
                "failure_count": 0,
                "attempt_count": 2,
                "retry_attempt_count": 1,
                "models": ["gpt-4.1"],
                "duration_ms": {"count": 1, "total": 12.5, "min": 12.5, "max": 12.5, "avg": 12.5},
                "usage": {"completion_tokens": 2, "prompt_tokens": 5},
                "status_counts": {"open_circuit": 1},
                "last_outcome_counts": {"failure": 1},
                "retryable_failure_count": 1,
                "active_health_check_count": 1,
            },
        ],
        "execution_panel": {
            "resume_summary": {
                "resume_event_count": 1,
                "reason_counts": {"manual resume": 1},
                "resumed_task_count": 2,
                "unique_task_count": 2,
                "last_resumed_at": "2026-03-22T10:08:00+00:00",
            },
            "repair_summary": {
                "cycle_count": 2,
                "max_cycles": 5,
                "budget_remaining": 3,
                "history_count": 2,
                "reason_counts": {"fix failing tests": 2},
                "failure_category_counts": {"test_validation": 2},
                "failed_task_count": 1,
            },
            "fallback_summary": {
                "task_count": 1,
                "entry_count": 1,
                "providers": ["anthropic"],
                "statuses": ["failed_health_check"],
            },
            "error_summary": {
                "final_error_count": 1,
                "fallback_error_count": 1,
            },
        },
    }

    fake_project = object()

    class FakeOrchestrator:
        def __init__(self, config, registry=None):
            self.config = config
            self.registry = registry

        def execute_workflow(self, project):
            return None

    monkeypatch.setattr(module, "STATE_PATH", "/srv/customer-secret-root/internal-observability/project_state.sqlite")
    monkeypatch.setattr(module, "OUTPUT_DIR", "/srv/customer-secret-root/internal-observability")
    monkeypatch.setattr(module, "build_observability_project", lambda state_path: fake_project)
    monkeypatch.setattr(module, "build_observability_registry", lambda config: object())
    monkeypatch.setattr(module, "load_internal_observability_view", lambda state_path: fake_view)
    monkeypatch.setattr(module, "Orchestrator", FakeOrchestrator)

    module.main()

    captured = capsys.readouterr().out.splitlines()
    rendered = "\n".join(captured)

    assert "State file: project_state.sqlite" in captured
    assert "State store: sqlite" in captured
    assert "Schema version: 3" in captured
    assert "Workflow status: failed" in captured
    assert "Phase: review" in captured
    assert "Acceptance met: false" in captured
    assert "Final providers: anthropic, openai" in captured
    assert "Observed providers: anthropic, openai" in captured
    assert (
        "- code: status=done, provider=openai, model=gpt-4.1, attempts=2, retries=1, task_ms=180000, provider_ms=12.5, output=present, failure=none"
        in captured
    )
    assert (
        "- review: status=failed, provider=anthropic, model=claude-sonnet-4, attempts=0, retries=0, task_ms=180000, provider_ms=40, output=none, failure=present"
        in captured
    )
    assert (
        "- openai: tasks=1; successes=1; failures=0; models=gpt-4.1; statuses=open_circuit; outcomes=failure; active_checks=present"
        in captured
    )
    assert (
        "- anthropic: tasks=1; successes=0; failures=1; models=claude-sonnet-4; statuses=none; outcomes=none; active_checks=none"
        in captured
    )
    assert "resume_events=1" in captured
    assert "repair_cycles=2" in captured
    assert "fallback_entries=1" in captured
    assert "final_errors=1" in captured
    assert "artifact_names=" not in rendered
    assert "decision_topics=" not in rendered
    assert "Architecture snapshot ready" not in rendered
    assert "customer-secret-root" not in rendered