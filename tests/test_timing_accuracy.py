from collections import deque
from datetime import datetime

from kycortex_agents.memory import project_state as project_state_module
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import TaskStatus


def fake_datetime_factory(timestamps):
    values = deque(datetime.fromisoformat(item) for item in timestamps)

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return values.popleft()

        @classmethod
        def fromisoformat(cls, value):
            return datetime.fromisoformat(value)

    return FakeDateTime


def test_retry_timing_distinguishes_total_duration_from_last_attempt(monkeypatch):
    monkeypatch.setattr(
        project_state_module,
        "datetime",
        fake_datetime_factory(
            [
                "2026-03-22T09:59:30+00:00",
                "2026-03-22T09:59:40+00:00",
                "2026-03-22T09:59:50+00:00",
                "2026-03-22T10:00:00+00:00",
                "2026-03-22T10:00:10+00:00",
                "2026-03-22T10:00:40+00:00",
                "2026-03-22T10:00:40+00:00",
                "2026-03-22T10:00:40+00:00",
                "2026-03-22T10:00:40+00:00",
                "2026-03-22T10:01:00+00:00",
                "2026-03-22T10:02:30+00:00",
                "2026-03-22T10:03:00+00:00",
            ]
        ),
    )
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

    project.mark_workflow_running()
    project.start_task("arch")
    project.fail_task("arch", "temporary failure")
    project.start_task("arch")
    project.complete_task("arch", "ARCHITECTURE DOC")
    project.mark_workflow_finished("completed")

    result = project.snapshot().task_results["arch"]
    retry_event = next(event for event in project.execution_events if event["event"] == "task_retry_scheduled")
    workflow_event = next(event for event in project.execution_events if event["event"] == "workflow_finished")

    assert result.details["has_task_duration"] is True
    assert result.details["has_last_attempt_duration"] is True
    assert "task_duration_ms" not in result.details
    assert "last_attempt_duration_ms" not in result.details
    assert result.resource_telemetry["task_duration_ms"] == 140000
    assert result.resource_telemetry["last_attempt_duration_ms"] == 90000
    assert retry_event["details"]["last_attempt_duration_ms"] == 30000.0
    assert workflow_event["details"]["workflow_duration_ms"] == 180000.0
    assert result.started_at == "2026-03-22T10:00:10+00:00"
    assert result.completed_at == "2026-03-22T10:02:30+00:00"


def test_resume_preserves_initial_workflow_and_task_start_times(monkeypatch):
    monkeypatch.setattr(
        project_state_module,
        "datetime",
        fake_datetime_factory(
            [
                "2026-03-22T10:05:10+00:00",
                "2026-03-22T10:05:20+00:00",
                "2026-03-22T10:05:30+00:00",
                "2026-03-22T10:06:00+00:00",
                "2026-03-22T10:06:30+00:00",
                "2026-03-22T10:07:00+00:00",
                "2026-03-22T10:08:00+00:00",
                "2026-03-22T10:09:00+00:00",
            ]
        ),
    )
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        workflow_started_at="2026-03-22T10:00:00+00:00",
        phase="execution",
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.RUNNING.value,
            attempts=1,
            started_at="2026-03-22T10:00:10+00:00",
            last_attempt_started_at="2026-03-22T10:00:10+00:00",
        )
    )

    resumed = project.resume_interrupted_tasks()
    project.mark_workflow_running()
    project.start_task("arch")
    project.complete_task("arch", "ARCHITECTURE DOC")
    project.mark_workflow_finished("completed")

    result = project.snapshot().task_results["arch"]
    workflow_event = next(event for event in project.execution_events if event["event"] == "workflow_finished")

    assert resumed == ["arch"]
    assert project.workflow_started_at == "2026-03-22T10:00:00+00:00"
    assert project.workflow_last_resumed_at == "2026-03-22T10:06:00+00:00"
    assert result.started_at == "2026-03-22T10:00:10+00:00"
    assert result.details["has_task_duration"] is True
    assert result.details["has_last_attempt_duration"] is True
    assert "task_duration_ms" not in result.details
    assert "last_attempt_duration_ms" not in result.details
    assert result.resource_telemetry["task_duration_ms"] == 470000
    assert result.resource_telemetry["last_attempt_duration_ms"] == 60000
    assert workflow_event["details"]["workflow_duration_ms"] == 540000.0


def test_snapshot_preserves_submillisecond_duration_precision():
    project = ProjectState(project_name="Demo", goal="Build demo")
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            output="ARCHITECTURE DOC",
            started_at="2026-03-22T10:00:00.000100+00:00",
            last_attempt_started_at="2026-03-22T10:00:00.000100+00:00",
            completed_at="2026-03-22T10:00:00.000500+00:00",
        )
    )
    project.workflow_started_at = "2026-03-22T10:00:00.000100+00:00"
    project.workflow_finished_at = "2026-03-22T10:00:00.000500+00:00"
    project.execution_events.append(
        {
            "event": "workflow_finished",
            "timestamp": "2026-03-22T10:00:00.000500+00:00",
            "task_id": None,
            "status": "completed",
            "details": {"workflow_duration_ms": 0.4},
        }
    )

    result = project.snapshot().task_results["arch"]

    assert result.details["has_task_duration"] is True
    assert result.details["has_last_attempt_duration"] is True
    assert "task_duration_ms" not in result.details
    assert "last_attempt_duration_ms" not in result.details
    assert result.resource_telemetry["task_duration_ms"] == 0.4
    assert result.resource_telemetry["last_attempt_duration_ms"] == 0.4
    assert project.snapshot().execution_events[0]["details"]["workflow_duration_ms"] == 0.4
