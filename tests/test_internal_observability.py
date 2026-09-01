from __future__ import annotations

import pytest

from kycortex_agents.memory.internal_observability import (
    build_internal_observability_view,
    load_internal_observability_view,
)
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import FailureCategory, TaskStatus, WorkflowOutcome, WorkflowStatus


def build_observability_project(state_file: str | None = None) -> ProjectState:
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        state_file=state_file,
        phase="review",
        acceptance_policy="strict",
        acceptance_criteria_met=False,
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category=FailureCategory.TEST_VALIDATION.value,
        repair_max_cycles=5,
        repair_cycle_count=2,
        acceptance_evaluation={
            "evaluated_task_ids": ["code", "review"],
            "required_task_ids": ["code"],
            "completed_task_ids": ["code"],
            "failed_task_ids": ["review"],
            "reason": "quality gate failed",
        },
    )
    project.workflow_last_resumed_at = "2026-03-22T10:08:00+00:00"
    project.repair_history = [
        {
            "cycle": 1,
            "started_at": "2026-03-22T10:09:00+00:00",
            "reason": "fix failing tests",
            "failure_category": FailureCategory.TEST_VALIDATION.value,
            "failed_task_ids": ["review"],
            "budget_remaining": 4,
        },
        {
            "cycle": 2,
            "started_at": "2026-03-22T10:10:00+00:00",
            "reason": "fix failing tests",
            "failure_category": FailureCategory.TEST_VALIDATION.value,
            "failed_task_ids": ["review"],
            "budget_remaining": 3,
        },
    ]
    project.execution_events.append(
        {
            "event": "workflow_resumed",
            "details": {
                "reason": "manual resume",
                "task_ids": ["code", "review"],
            },
        }
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description="Implement the application",
            assigned_to="code_engineer",
            status=TaskStatus.DONE.value,
            started_at="2026-03-22T10:00:00+00:00",
            last_attempt_started_at="2026-03-22T10:01:00+00:00",
            completed_at="2026-03-22T10:03:00+00:00",
            output="done",
            last_provider_call={
                "provider": "openai",
                "model": "gpt-4.1",
                "success": True,
                "duration_ms": 12.5,
                "latency_ms": 9.5,
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                "attempt_history": [
                    {"success": False, "retryable": True},
                    {"success": True, "retryable": False},
                ],
                "provider_health": {
                    "openai": {
                        "model": "gpt-4.1",
                        "status": "open_circuit",
                        "last_outcome": "failure",
                        "last_failure_retryable": True,
                        "last_health_check": {
                            "active_check": True,
                            "cooldown_cached": False,
                        },
                    }
                },
                "fallback_history": [
                    {
                        "provider": "anthropic",
                        "status": "failed_health_check",
                        "error_type": "ProviderTransientError",
                    }
                ],
            },
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description="Review the changes",
            assigned_to="code_reviewer",
            dependencies=["code"],
            status=TaskStatus.FAILED.value,
            started_at="2026-03-22T10:04:00+00:00",
            last_attempt_started_at="2026-03-22T10:05:00+00:00",
            completed_at="2026-03-22T10:07:00+00:00",
            last_error="quality gate failed",
            last_error_category=FailureCategory.TEST_VALIDATION.value,
            last_provider_call={
                "provider": "anthropic",
                "model": "claude-sonnet-4",
                "success": False,
                "timing": {"total_duration_ms": 40, "latency_ms": 30},
                "usage": {"prompt_tokens": 3},
                "error_type": "AgentExecutionError",
            },
        )
    )
    return project


def test_build_internal_observability_view_verifies_persisted_evidence(tmp_path):
    state_path = tmp_path / "project_state.json"
    project = build_observability_project(str(state_path))
    project._record_execution_event(
        event="workflow_started",
        timestamp="2026-03-22T10:00:00+00:00",
        status=project.phase,
        details={"reason": "persisted evidence smoke test"},
    )
    project.save()

    view = build_internal_observability_view(ProjectState.load(str(state_path)))
    evidence = view["evidence_panel"]

    assert evidence["state_sha256"]
    assert evidence["event_chain_head"]
    assert evidence["verification_checks"]["state_digest"] == "passed"
    assert evidence["verification_checks"]["event_chain"] == "passed"
    assert evidence["verification_checks"]["integrity_sidecar"] == "passed"
    assert evidence["verification_checks"]["artifact_manifest"] == "skipped"
    assert evidence["verification_passed"] is True


def test_build_internal_observability_view_projects_internal_runtime_telemetry_into_panel_ready_model():
    project = build_observability_project()

    view = build_internal_observability_view(project)

    assert view["source"] == {
        "state_file": None,
        "state_store_kind": "memory",
        "schema_version": project.schema_version,
    }

    overview = view["workflow_overview"]
    assert overview["project_name"] == "Demo"
    assert overview["goal"] == "Build demo"
    assert overview["workflow_status"] == WorkflowStatus.FAILED
    assert overview["phase"] == "review"
    assert overview["acceptance_policy"] == "strict"
    assert overview["terminal_outcome"] == WorkflowOutcome.FAILED.value
    assert overview["failure_category"] == FailureCategory.TEST_VALIDATION.value
    assert overview["task_status_counts"] == {
        TaskStatus.DONE.value: 1,
        TaskStatus.FAILED.value: 1,
    }
    assert overview["final_providers"] == ["anthropic", "openai"]
    assert overview["duration_ms"] == {"count": 2, "total": 52.5, "min": 12.5, "max": 40, "avg": 26.25}
    assert overview["usage"] == {"completion_tokens": 2, "prompt_tokens": 8}

    assert view["task_timeline"] == [
        {
            "task_id": "code",
            "title": "Implementation",
            "description": "Implement the application",
            "dependencies": [],
            "repair_origin_task_id": None,
            "assigned_to": "code_engineer",
            "status": TaskStatus.DONE.value,
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
            "provider_health": {
                "openai": {
                    "model": "gpt-4.1",
                    "status": "open_circuit",
                    "last_outcome": "failure",
                    "last_failure_retryable": True,
                    "last_health_check": {
                        "active_check": True,
                        "cooldown_cached": False,
                    },
                }
            },
        },
        {
            "task_id": "review",
            "title": "Review",
            "description": "Review the changes",
            "dependencies": ["code"],
            "repair_origin_task_id": None,
            "assigned_to": "code_reviewer",
            "status": TaskStatus.FAILED.value,
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
    ]

    assert view["provider_panels"] == [
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
    ]

    assert view["execution_panel"] == {
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
            "failure_category_counts": {FailureCategory.TEST_VALIDATION.value: 2},
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
    }


@pytest.mark.parametrize(
    "state_filename,expected_store_kind",
    [("project_state.json", "json"), ("project_state.sqlite", "sqlite")],
)
def test_load_internal_observability_view_supports_json_and_sqlite_persisted_state(
    tmp_path,
    state_filename,
    expected_store_kind,
):
    state_path = tmp_path / state_filename
    project = build_observability_project(str(state_path))
    project.save()

    view = load_internal_observability_view(str(state_path))

    assert view["source"] == {
        "state_file": str(state_path),
        "state_store_kind": expected_store_kind,
        "schema_version": project.schema_version,
    }
    assert view["workflow_overview"]["workflow_status"] == WorkflowStatus.FAILED
    assert [entry["task_id"] for entry in view["task_timeline"]] == ["code", "review"]
    assert [panel["provider"] for panel in view["provider_panels"]] == ["anthropic", "openai"]
    assert view["execution_panel"]["repair_summary"]["cycle_count"] == 2