from typing import Any, Mapping

from kycortex_agents import AgentRegistry, ArtifactType, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.providers import BaseLLMProvider
from kycortex_agents.types import AgentInput, AgentOutput, DecisionRecord, TaskStatus


class FakeMetadataProvider(BaseLLMProvider):
    def __init__(self, response: str, metadata: dict[str, Any]):
        self.response = response
        self.metadata = metadata

    def generate(self, system_prompt: str, user_message: str) -> str:
        return self.response

    def get_last_call_metadata(self) -> dict[str, Any]:
        return dict(self.metadata)

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.metadata.get("provider"),
            "model": self.metadata.get("model"),
            "status": "healthy",
            "active_check": True,
            "latency_ms": 1,
        }


class SnapshotAgent(BaseAgent):
    def __init__(
        self,
        config: KYCortexConfig,
        name: str,
        role: str,
        artifact_type: ArtifactType,
        artifact_name: str,
        response: str,
        provider_name: str,
        model_name: str,
        decision_topic: str,
    ):
        super().__init__(name=name, role=role, config=config)
        self.output_artifact_type = artifact_type
        self.output_artifact_name = artifact_name
        self._provider = FakeMetadataProvider(
            response=response,
            metadata={
                "usage": {"total_tokens": len(response.split()) + 5},
                "provider": provider_name,
                "model": model_name,
            },
        )
        self.decision_topic = decision_topic

    def run_with_input(self, agent_input: AgentInput) -> AgentOutput:
        raw_content = self.chat("system", agent_input.task_description)
        return AgentOutput(
            summary=raw_content.splitlines()[0].strip(),
            raw_content=raw_content,
            decisions=[
                DecisionRecord(
                    topic=self.decision_topic,
                    decision=f"{self.name} completed deterministically.",
                    rationale=f"Recorded while inspecting snapshot data for {agent_input.task_id}.",
                )
            ],
        )

    def run(self, task_description: str, context: dict) -> str:
        raise NotImplementedError


def build_snapshot_registry(config: KYCortexConfig) -> AgentRegistry:
    openai_config = KYCortexConfig(
        project_name=config.project_name,
        output_dir=config.output_dir,
        llm_provider="openai",
        llm_model="snapshot-openai-demo",
        api_key="demo-openai-key",
    )
    anthropic_config = KYCortexConfig(
        project_name=config.project_name,
        output_dir=config.output_dir,
        llm_provider="anthropic",
        llm_model="snapshot-anthropic-demo",
        api_key="demo-anthropic-key",
    )
    return AgentRegistry(
        {
            "architect": SnapshotAgent(
                openai_config,
                name="Snapshot Architect",
                role="architect",
                artifact_type=ArtifactType.DOCUMENT,
                artifact_name="architecture",
                response="Architecture snapshot ready",
                provider_name="openai",
                model_name="snapshot-openai-demo",
                decision_topic="architecture_snapshot",
            ),
            "code_reviewer": SnapshotAgent(
                anthropic_config,
                name="Snapshot Reviewer",
                role="code_reviewer",
                artifact_type=ArtifactType.DOCUMENT,
                artifact_name="review",
                response="Review snapshot ready",
                provider_name="anthropic",
                model_name="snapshot-anthropic-demo",
                decision_topic="review_snapshot",
            ),
        }
    )


def build_snapshot_project(state_path: str) -> ProjectState:
    project = ProjectState(
        project_name="SnapshotInspectionDemo",
        goal="Demonstrate how to inspect structured snapshot state after a workflow run.",
        state_file=state_path,
    )
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
    return project


def _format_csv(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _format_presence(values: dict[str, bool]) -> str:
    present_values = [name for name in sorted(values) if values[name]]
    return ", ".join(present_values) if present_values else "none"


def _presence_label(value: Any) -> str:
    return "present" if value else "none"


def _progress_presence(project: ProjectState, snapshot: Any) -> dict[str, bool]:
    task_results = list(snapshot.task_results.values())
    terminal_statuses = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.SKIPPED}

    def _normalized_status(task_result: Any) -> str | None:
        raw_status = getattr(task_result, "status", None)
        value = getattr(raw_status, "value", raw_status)
        return value if isinstance(value, str) else None

    try:
        has_runnable_tasks = bool(project.runnable_tasks())
        has_blocked_tasks = bool(project.blocked_tasks())
    except Exception:
        has_runnable_tasks = False
        has_blocked_tasks = False
    return {
        "has_pending_tasks": any(
            _normalized_status(task_result) == TaskStatus.PENDING.value for task_result in task_results
        ),
        "has_running_tasks": any(
            _normalized_status(task_result) == TaskStatus.RUNNING.value for task_result in task_results
        ),
        "has_runnable_tasks": has_runnable_tasks,
        "has_blocked_tasks": has_blocked_tasks,
        "has_terminal_tasks": any(
            _normalized_status(task_result) in {status.value for status in terminal_statuses}
            for task_result in task_results
        ),
        "all_tasks_terminal": bool(task_results)
        and all(
            _normalized_status(task_result) in {status.value for status in terminal_statuses}
            for task_result in task_results
        ),
    }


def _print_provider_health_summary(provider_health_summary: Mapping[str, Mapping[str, Any]]) -> None:
    if not provider_health_summary:
        print("- none")
        return

    for index, provider_name in enumerate(sorted(provider_health_summary), start=1):
        health = provider_health_summary[provider_name]
        models = [str(model) for model in health.get("models", []) if model]
        print(
            f"- entry_{index}: model_count={len(models)}; "
            f"statuses={_format_presence({name: count > 0 for name, count in health.get('status_counts', {}).items()})}; "
            f"outcomes={_format_presence({name: count > 0 for name, count in health.get('last_outcome_counts', {}).items()})}; "
            f"active_checks={_presence_label(health.get('active_health_check_count', 0) > 0)}"
        )


def _print_execution_event_summary(execution_events: list[dict[str, Any]]) -> None:
    print(f"event_count={len(execution_events)}")
    if execution_events:
        print(f"last_event={execution_events[-1].get('event', 'unknown')}")
    else:
        print("last_event=none")


def main() -> None:
    state_path = "./output_snapshot_inspection_demo/project_state.json"
    config = KYCortexConfig(
        project_name="snapshot-inspection-demo",
        output_dir="./output_snapshot_inspection_demo",
    )
    project = build_snapshot_project(state_path)
    registry = build_snapshot_registry(config)

    Orchestrator(config, registry=registry).execute_workflow(project)

    snapshot = project.snapshot()
    internal_runtime_telemetry = project.internal_runtime_telemetry()
    workflow_telemetry = internal_runtime_telemetry["workflow"]
    provider_health_summary = workflow_telemetry["provider_health_summary"]
    progress_presence = _progress_presence(project, snapshot)

    print("Snapshot workflow status:")
    print(snapshot.workflow_status)
    print("\nTask results:")
    for task_id, task_result in snapshot.task_results.items():
        task_runtime_telemetry: Mapping[str, Any] = internal_runtime_telemetry["tasks"].get(task_id, {})
        print(
            f"- {task_id}: status={task_result.status.value}, "
            f"summary={task_result.output.summary if task_result.output else None}, "
            f"provider={_presence_label(task_runtime_telemetry.get('provider'))}, "
            f"model={_presence_label(task_runtime_telemetry.get('model'))}"
        )

    print("\nInternal workflow telemetry:")
    print(f"multiple_tasks={_presence_label(workflow_telemetry['task_count'] > 1)}")
    print(
        f"multiple_observed_providers={_presence_label(len(workflow_telemetry['observed_providers']) > 1)}"
    )
    print(
        f"multiple_final_providers={_presence_label(len(workflow_telemetry['final_providers']) > 1)}"
    )
    print(f"attempts_present={_presence_label(workflow_telemetry['attempt_count'] > 0)}")
    print(
        f"retry_attempts_present={_presence_label(workflow_telemetry['retry_attempt_count'] > 0)}"
    )
    print(f"pending_tasks_present={_presence_label(progress_presence['has_pending_tasks'])}")
    print(f"running_tasks_present={_presence_label(progress_presence['has_running_tasks'])}")
    print(f"runnable_tasks_present={_presence_label(progress_presence['has_runnable_tasks'])}")
    print(f"blocked_tasks_present={_presence_label(progress_presence['has_blocked_tasks'])}")
    print(f"terminal_tasks_present={_presence_label(progress_presence['has_terminal_tasks'])}")
    print(f"all_tasks_terminal={_presence_label(progress_presence['all_tasks_terminal'])}")
    print("\nInternal workflow provider health summary:")
    _print_provider_health_summary(provider_health_summary)

    print("\nArtifacts:")
    print(f"artifact_names={_format_csv([artifact.name for artifact in snapshot.artifacts])}")
    print("\nDecisions:")
    print(f"decision_topics={_format_csv([decision.topic for decision in snapshot.decisions])}")
    print("\nExecution events:")
    _print_execution_event_summary(snapshot.execution_events)


if __name__ == "__main__":
    main()
