import pytest

from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import ArtifactType, TaskStatus, WorkflowStatus


def build_project(state_path):
    return ProjectState(
        project_name="Demo",
        goal="Build demo",
        phase="failed",
        workflow_started_at="2026-03-22T10:00:00+00:00",
        workflow_finished_at="2026-03-22T10:09:00+00:00",
        workflow_last_resumed_at="2026-03-22T10:07:00+00:00",
        updated_at="2026-03-22T10:09:00+00:00",
        state_file=str(state_path),
        decisions=[
            {
                "topic": "architecture",
                "decision": "Use layered runtime",
                "rationale": "Keeps providers isolated",
                "at": "2026-03-22T10:01:00+00:00",
                "metadata": {"owner": "architect", "version": 2},
            }
        ],
        artifacts=[
            {
                "name": "architecture.md",
                "artifact_type": ArtifactType.DOCUMENT.value,
                "path": "docs/architecture.md",
                "content": "# Architecture",
                "created_at": "2026-03-22T10:02:00+00:00",
                "metadata": {"task_id": "arch", "source": "architect"},
            },
            {
                "name": "mystery.bin",
                "artifact_type": "unknown-kind",
                "content": "opaque",
                "created_at": "2026-03-22T10:02:30+00:00",
                "metadata": {"source": "migration"},
            },
            "legacy-report.md",
        ],
        execution_events=[
            {
                "event": "workflow_started",
                "timestamp": "2026-03-22T10:00:00+00:00",
                "task_id": None,
                "status": "execution",
                "details": {},
            },
            {
                "event": "task_failed",
                "timestamp": "2026-03-22T10:09:00+00:00",
                "task_id": "review",
                "status": "failed",
                "details": {"error_type": "ValueError", "provider_call": {"provider": "ollama"}},
            },
        ],
    )


def build_tasks():
    return [
        Task(
            id="arch",
            title="Architecture",
            description="Design",
            assigned_to="architect",
            status=TaskStatus.DONE.value,
            attempts=1,
            created_at="2026-03-22T10:00:30+00:00",
            started_at="2026-03-22T10:01:00+00:00",
            last_attempt_started_at="2026-03-22T10:01:00+00:00",
            completed_at="2026-03-22T10:03:00+00:00",
            output="ARCHITECTURE DOC",
            output_payload={
                "summary": "Architecture summary",
                "raw_content": "ARCHITECTURE DOC",
                "artifacts": [
                    {
                        "name": "architecture.md",
                        "artifact_type": ArtifactType.DOCUMENT.value,
                        "path": "docs/architecture.md",
                        "content": "# Architecture",
                        "created_at": "2026-03-22T10:02:00+00:00",
                        "metadata": {"task_id": "arch", "source": "architect"},
                    }
                ],
                "decisions": [
                    {
                        "topic": "runtime",
                        "decision": "Persist snapshots",
                        "rationale": "Supports resume",
                        "created_at": "2026-03-22T10:02:15+00:00",
                        "metadata": {"priority": "high"},
                    }
                ],
                "metadata": {"agent_name": "ArchitectAgent", "provider": "openai"},
            },
            last_provider_call={
                "provider": "openai",
                "model": "gpt-4o",
                "success": True,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "timing": {"duration_ms": 120.5},
            },
            history=[
                {
                    "event": "started",
                    "timestamp": "2026-03-22T10:01:00+00:00",
                    "status": "running",
                    "attempts": 1,
                    "error_message": None,
                },
                {
                    "event": "completed",
                    "timestamp": "2026-03-22T10:03:00+00:00",
                    "status": "done",
                    "attempts": 1,
                    "error_message": None,
                },
            ],
        ),
        Task(
            id="review",
            title="Review",
            description="Review",
            assigned_to="code_reviewer",
            dependencies=["arch"],
            retry_limit=1,
            attempts=2,
            status=TaskStatus.FAILED.value,
            created_at="2026-03-22T10:03:05+00:00",
            started_at="2026-03-22T10:03:30+00:00",
            last_attempt_started_at="2026-03-22T10:08:00+00:00",
            last_resumed_at="2026-03-22T10:07:00+00:00",
            completed_at="2026-03-22T10:09:00+00:00",
            output="Review failed",
            last_error="Review failed",
            last_error_type="ValueError",
            repair_context={
                "cycle": 2,
                "failure_category": "code_validation",
                "instruction": "Repair the generated Python module.",
                "repair_owner": "code_engineer",
                "original_assigned_to": "code_engineer",
                "helper_surface_usages": ["RiskScoringService (line 33)"],
                "helper_surface_symbols": ["RiskScoringService"],
                "decomposition_mode": "budget_compaction_planner",
                "decomposition_target_agent": "architect",
                "decomposition_failure_category": "code_validation",
                "failure_message": "Generated module failed import validation.",
                "failure_error_type": "ImportError",
                "failed_artifact_content": "def broken():\n    return missing_symbol",
                "failed_output": "def broken():\n    return missing_symbol",
                "validation_summary": "Generated code validation:\n- Syntax OK: no",
                "existing_tests": "def test_broken():\n    assert broken() == 1",
                "source_failure_task_id": "arch",
                "provider_call": {"provider": "ollama", "success": False},
            },
            last_provider_call={
                "provider": "ollama",
                "model": "llama3",
                "success": False,
                "error_type": "AgentExecutionError",
                "timing": {"total_duration_ms": 125.0},
            },
            history=[
                {
                    "event": "started",
                    "timestamp": "2026-03-22T10:08:00+00:00",
                    "status": "running",
                    "attempts": 2,
                    "error_message": None,
                },
                {
                    "event": "failed",
                    "timestamp": "2026-03-22T10:09:00+00:00",
                    "status": "failed",
                    "attempts": 2,
                    "error_message": "Review failed",
                },
            ],
        ),
        Task(
            id="docs",
            title="Docs",
            description="Document",
            assigned_to="docs_writer",
            dependencies=["arch"],
            status=TaskStatus.PENDING.value,
            created_at="2026-03-22T10:03:10+00:00",
        ),
        Task(
            id="tests",
            title="Tests",
            description="Validate",
            assigned_to="qa_tester",
            dependencies=["review"],
            status=TaskStatus.SKIPPED.value,
            created_at="2026-03-22T10:03:20+00:00",
            completed_at="2026-03-22T10:09:00+00:00",
            output="Skipped because dependency 'review' failed",
            history=[
                {
                    "event": "skipped",
                    "timestamp": "2026-03-22T10:09:00+00:00",
                    "status": "skipped",
                    "attempts": 0,
                    "error_message": "Skipped because dependency 'review' failed",
                }
            ],
        ),
    ]


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_snapshot_round_trip_preserves_mixed_task_state_integrity(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    project = build_project(state_path)
    project.tasks = build_tasks()

    project.save()
    reloaded = ProjectState.load(str(state_path))
    snapshot = reloaded.snapshot()

    assert snapshot.project_name == "Demo"
    assert snapshot.goal == "Build demo"
    assert snapshot.phase == "failed"
    assert snapshot.workflow_status == WorkflowStatus.FAILED
    assert snapshot.started_at == "2026-03-22T10:00:00+00:00"
    assert snapshot.finished_at == "2026-03-22T10:09:00+00:00"
    assert snapshot.last_resumed_at == "2026-03-22T10:07:00+00:00"
    assert snapshot.updated_at == reloaded.updated_at

    arch_result = snapshot.task_results["arch"]
    review_result = snapshot.task_results["review"]
    docs_result = snapshot.task_results["docs"]
    tests_result = snapshot.task_results["tests"]

    assert arch_result.status == TaskStatus.DONE
    assert arch_result.output is not None
    assert arch_result.output.summary == "Architecture summary"
    assert arch_result.output.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert arch_result.output.artifacts[0].metadata["source"] == "architect"
    assert arch_result.output.decisions[0].decision == "Persist snapshots"
    assert arch_result.output.decisions[0].metadata["priority"] == "high"
    assert "last_provider_call" not in arch_result.details
    assert arch_result.resource_telemetry == {
        "has_provider_call": True,
        "task_duration_ms": 120000,
        "last_attempt_duration_ms": 120000,
        "provider_duration_ms": 120.5,
        "usage": {"completion_tokens": 5, "prompt_tokens": 10, "total_tokens": 15},
    }

    assert review_result.status == TaskStatus.FAILED
    assert review_result.failure is not None
    assert review_result.failure.message == "Review failed"
    assert review_result.failure.error_type == "ValueError"
    assert "provider_call" not in review_result.failure.details
    assert review_result.failure.details["last_resumed_at"] == "2026-03-22T10:07:00+00:00"
    assert review_result.details["last_error_present"] is True
    assert "last_error" not in review_result.details
    assert review_result.details["repair_context"]["cycle"] == 2
    assert review_result.details["repair_context"]["failure_category"] == "code_validation"
    assert review_result.details["repair_context"]["has_failed_artifact_content"] is True
    assert review_result.details["repair_context"]["has_instruction"] is True
    assert review_result.details["repair_context"]["has_repair_owner"] is True
    assert review_result.details["repair_context"]["has_original_assigned_to"] is True
    assert review_result.details["repair_context"]["has_helper_surface_usages"] is True
    assert review_result.details["repair_context"]["has_helper_surface_symbols"] is True
    assert review_result.details["repair_context"]["has_decomposition_mode"] is True
    assert review_result.details["repair_context"]["has_decomposition_target_agent"] is True
    assert review_result.details["repair_context"]["has_decomposition_failure_category"] is True
    assert review_result.details["repair_context"]["has_failure_message"] is True
    assert review_result.details["repair_context"]["has_failure_error_type"] is True
    assert review_result.details["repair_context"]["has_failed_output"] is True
    assert review_result.details["repair_context"]["has_validation_summary"] is True
    assert review_result.details["repair_context"]["has_existing_tests"] is True
    assert review_result.details["repair_context"]["has_source_failure_task"] is True
    assert review_result.details["repair_context"]["has_provider_call"] is True
    assert "failed_artifact_content" not in review_result.details["repair_context"]
    assert "instruction" not in review_result.details["repair_context"]
    assert "repair_owner" not in review_result.details["repair_context"]
    assert "original_assigned_to" not in review_result.details["repair_context"]
    assert "helper_surface_usages" not in review_result.details["repair_context"]
    assert "helper_surface_symbols" not in review_result.details["repair_context"]
    assert "decomposition_mode" not in review_result.details["repair_context"]
    assert "decomposition_target_agent" not in review_result.details["repair_context"]
    assert "decomposition_failure_category" not in review_result.details["repair_context"]
    assert "failure_message" not in review_result.details["repair_context"]
    assert "failure_error_type" not in review_result.details["repair_context"]
    assert "failed_output" not in review_result.details["repair_context"]
    assert "validation_summary" not in review_result.details["repair_context"]
    assert "existing_tests" not in review_result.details["repair_context"]
    assert review_result.details["history"][1]["event"] == "failed"
    assert review_result.details["history"][1]["has_error_message"] is True
    assert "error_message" not in review_result.details["history"][1]
    assert review_result.failure.details["repair_context"]["has_failed_artifact_content"] is True
    assert review_result.failure.details["repair_context"]["has_instruction"] is True
    assert review_result.failure.details["repair_context"]["has_repair_owner"] is True
    assert review_result.failure.details["repair_context"]["has_original_assigned_to"] is True
    assert review_result.failure.details["repair_context"]["has_helper_surface_usages"] is True
    assert review_result.failure.details["repair_context"]["has_helper_surface_symbols"] is True
    assert review_result.failure.details["repair_context"]["has_decomposition_mode"] is True
    assert review_result.failure.details["repair_context"]["has_decomposition_target_agent"] is True
    assert review_result.failure.details["repair_context"]["has_decomposition_failure_category"] is True
    assert review_result.failure.details["repair_context"]["has_failure_message"] is True
    assert review_result.failure.details["repair_context"]["has_failure_error_type"] is True
    assert review_result.failure.details["repair_context"]["has_failed_output"] is True
    assert review_result.failure.details["repair_context"]["has_validation_summary"] is True
    assert review_result.failure.details["repair_context"]["has_existing_tests"] is True
    assert review_result.failure.details["repair_context"]["has_source_failure_task"] is True
    assert review_result.failure.details["repair_context"]["has_provider_call"] is True
    assert "failed_artifact_content" not in review_result.failure.details["repair_context"]
    assert "instruction" not in review_result.failure.details["repair_context"]
    assert "repair_owner" not in review_result.failure.details["repair_context"]
    assert "original_assigned_to" not in review_result.failure.details["repair_context"]
    assert "helper_surface_usages" not in review_result.failure.details["repair_context"]
    assert "helper_surface_symbols" not in review_result.failure.details["repair_context"]
    assert "decomposition_mode" not in review_result.failure.details["repair_context"]
    assert "decomposition_target_agent" not in review_result.failure.details["repair_context"]
    assert "decomposition_failure_category" not in review_result.failure.details["repair_context"]
    assert "failure_message" not in review_result.failure.details["repair_context"]
    assert "failure_error_type" not in review_result.failure.details["repair_context"]
    assert "failed_output" not in review_result.failure.details["repair_context"]
    assert "validation_summary" not in review_result.failure.details["repair_context"]
    assert "existing_tests" not in review_result.failure.details["repair_context"]
    assert review_result.failure.details["history"][1]["has_error_message"] is True
    assert "error_message" not in review_result.failure.details["history"][1]
    assert review_result.resource_telemetry == {
        "has_provider_call": True,
        "task_duration_ms": 330000,
        "last_attempt_duration_ms": 60000,
        "provider_duration_ms": 125,
        "usage": {},
    }

    assert docs_result.status == TaskStatus.PENDING
    assert docs_result.output is None
    assert docs_result.failure is None
    assert docs_result.resource_telemetry == {
        "has_provider_call": False,
        "task_duration_ms": None,
        "last_attempt_duration_ms": None,
        "provider_duration_ms": None,
        "usage": {},
    }

    assert tests_result.status == TaskStatus.SKIPPED
    assert tests_result.output is not None
    assert tests_result.output.summary == "Skipped because dependency 'review' failed"
    assert tests_result.output.artifacts[0].artifact_type == ArtifactType.TEST
    assert tests_result.output.metadata["assigned_to"] == "qa_tester"
    assert tests_result.details["last_error_present"] is False
    assert "last_error" not in tests_result.details
    assert tests_result.details["history"][0]["event"] == "skipped"
    assert tests_result.details["history"][0]["has_error_message"] is True
    assert "error_message" not in tests_result.details["history"][0]
    assert tests_result.resource_telemetry["has_provider_call"] is False

    assert snapshot.decisions[0].topic == "architecture"
    assert snapshot.decisions[0].metadata["version"] == 2
    assert snapshot.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert snapshot.artifacts[0].metadata["task_id"] == "arch"
    assert snapshot.artifacts[1].artifact_type == ArtifactType.OTHER
    assert snapshot.artifacts[1].name == "mystery.bin"
    assert snapshot.artifacts[2].name == "legacy-report.md"
    assert snapshot.artifacts[2].artifact_type == ArtifactType.OTHER
    assert snapshot.execution_events[1]["details"]["has_provider_call"] is True
    assert snapshot.execution_events[1]["details"]["has_error_type"] is True
    assert "provider_call" not in snapshot.execution_events[1]["details"]
    assert "error_type" not in snapshot.execution_events[1]["details"]
    assert snapshot.workflow_telemetry == {
        "task_count": 4,
        "task_status_counts": {
            "pending": 1,
            "running": 0,
            "done": 1,
            "failed": 1,
            "skipped": 1,
        },
        "progress_summary": {
            "pending_task_count": 1,
            "running_task_count": 0,
            "runnable_task_count": 1,
            "blocked_task_count": 0,
            "terminal_task_count": 3,
            "completion_percent": 75,
        },
        "tasks_with_provider_calls": 2,
        "tasks_without_provider_calls": 2,
        "acceptance_summary": {
            "policy": None,
            "accepted": False,
            "reason": None,
            "terminal_outcome": None,
            "failure_category": None,
            "evaluated_task_count": 0,
            "required_task_count": 0,
            "completed_task_count": 0,
            "failed_task_count": 0,
            "skipped_task_count": 0,
            "pending_task_count": 0,
        },
        "resume_summary": {
            "count": 0,
            "reason_count": 0,
            "task_count": 0,
            "unique_task_count": 0,
            "last_resumed_at": "2026-03-22T10:07:00+00:00",
        },
        "repair_summary": {
            "cycle_count": 0,
            "max_cycles": 0,
            "budget_remaining": 0,
            "history_count": 0,
            "reason_count": 0,
            "last_reason_present": False,
            "failure_category_count": 0,
            "failed_task_count": 0,
        },
        "final_provider_count": 2,
        "observed_provider_count": 2,
        "provider_summary": {
            "ollama": {
                "task_count": 1,
                "success_count": 0,
                "failure_count": 1,
                "has_attempts": False,
                "has_retry_attempts": False,
                "duration_ms": {"count": 1, "total": 125, "min": 125, "max": 125, "avg": 125},
                "usage": {},
            },
            "openai": {
                "task_count": 1,
                "success_count": 1,
                "failure_count": 0,
                "has_attempts": False,
                "has_retry_attempts": False,
                "duration_ms": {"count": 1, "total": 120.5, "min": 120.5, "max": 120.5, "avg": 120.5},
                "usage": {"completion_tokens": 5, "prompt_tokens": 10, "total_tokens": 15},
            },
        },
        "provider_health_summary": {},
        "has_attempts": False,
        "has_retry_attempts": False,
        "duration_ms": {"count": 2, "total": 245.5, "min": 120.5, "max": 125, "avg": 122.75},
        "usage": {"completion_tokens": 5, "prompt_tokens": 10, "total_tokens": 15},
        "fallback_summary": {
            "task_count": 0,
            "has_entries": False,
            "provider_count": 0,
            "status_count": 0,
        },
        "error_summary": {
            "final_error_count": 1,
            "fallback_error_count": 0,
        },
    }


@pytest.mark.parametrize("state_filename", ["project_state.json", "project_state.sqlite"])
def test_snapshot_round_trip_preserves_legacy_string_outputs_and_unknown_task_status(tmp_path, state_filename):
    state_path = tmp_path / state_filename
    project = ProjectState(
        project_name="Legacy",
        goal="Keep compatibility",
        state_file=str(state_path),
        tasks=[
            Task(
                id="legacy",
                title="Legacy task",
                description="Migrate",
                assigned_to="legal_advisor",
                status="migrated",
                output="Legacy output\nWith more detail",
                created_at="2026-03-22T10:00:00+00:00",
            )
        ],
        artifacts=["legacy.txt"],
    )

    project.save()
    snapshot = ProjectState.load(str(state_path)).snapshot()
    result = snapshot.task_results["legacy"]

    assert result.status == TaskStatus.PENDING
    assert result.output is not None
    assert result.output.summary == "Legacy output"
    assert result.output.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert result.output.artifacts[0].metadata["assigned_to"] == "legal_advisor"
    assert snapshot.artifacts[0].name == "legacy.txt"
    assert snapshot.artifacts[0].artifact_type == ArtifactType.OTHER
