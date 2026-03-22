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
    assert arch_result.details["last_provider_call"]["usage"]["total_tokens"] == 15

    assert review_result.status == TaskStatus.FAILED
    assert review_result.failure is not None
    assert review_result.failure.message == "Review failed"
    assert review_result.failure.error_type == "ValueError"
    assert review_result.failure.details["provider_call"]["provider"] == "ollama"
    assert review_result.failure.details["last_resumed_at"] == "2026-03-22T10:07:00+00:00"
    assert review_result.details["history"][1]["event"] == "failed"

    assert docs_result.status == TaskStatus.PENDING
    assert docs_result.output is None
    assert docs_result.failure is None

    assert tests_result.status == TaskStatus.SKIPPED
    assert tests_result.output is not None
    assert tests_result.output.summary == "Skipped because dependency 'review' failed"
    assert tests_result.output.artifacts[0].artifact_type == ArtifactType.TEST
    assert tests_result.output.metadata["assigned_to"] == "qa_tester"

    assert snapshot.decisions[0].topic == "architecture"
    assert snapshot.decisions[0].metadata["version"] == 2
    assert snapshot.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert snapshot.artifacts[0].metadata["task_id"] == "arch"
    assert snapshot.artifacts[1].artifact_type == ArtifactType.OTHER
    assert snapshot.artifacts[1].name == "mystery.bin"
    assert snapshot.artifacts[2].name == "legacy-report.md"
    assert snapshot.artifacts[2].artifact_type == ArtifactType.OTHER
    assert snapshot.execution_events[1]["details"]["provider_call"]["provider"] == "ollama"


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
