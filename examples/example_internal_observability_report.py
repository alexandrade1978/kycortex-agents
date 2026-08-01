from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.memory.internal_observability import load_internal_observability_view
from kycortex_agents.providers import BaseLLMProvider
from kycortex_agents.types import AgentInput, AgentOutput, DecisionRecord


OUTPUT_DIR = "./output_internal_observability_report_demo"
STATE_PATH = f"{OUTPUT_DIR}/project_state.sqlite"


class FakeMetadataProvider(BaseLLMProvider):
    def __init__(self, response: str, metadata: dict[str, Any]):
        self.response = response
        self.metadata = metadata

    def generate(self, system_prompt: str, user_message: str) -> str:
        return self.response

    def get_last_call_metadata(self) -> dict[str, Any]:
        return self.metadata.copy()

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.metadata.get("provider"),
            "model": self.metadata.get("model"),
            "status": "healthy",
            "active_check": True,
            "latency_ms": 1,
        }


class ObservabilityAgent(BaseAgent):
    def __init__(
        self,
        config: KYCortexConfig,
        name: str,
        role: str,
        response: str,
        provider_name: str,
        model_name: str,
        decision_topic: str,
    ):
        super().__init__(name=name, role=role, config=config)
        self._provider = FakeMetadataProvider(
            response=response,
            metadata={
                "usage": {"prompt_tokens": 5, "completion_tokens": len(response.split())},
                "provider": provider_name,
                "model": model_name,
                "duration_ms": 12.5,
                "latency_ms": 9.5,
                "attempt_history": [{"success": True, "retryable": False}],
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
                    rationale=f"Recorded while rendering internal observability state for {agent_input.task_id}.",
                )
            ],
        )

    def run(self, task_description: str, context: dict) -> str:
        raise NotImplementedError


def build_observability_registry(config: KYCortexConfig) -> AgentRegistry:
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
            "architect": ObservabilityAgent(
                openai_config,
                name="Observability Architect",
                role="architect",
                response="Architecture observability view ready",
                provider_name="openai",
                model_name="snapshot-openai-demo",
                decision_topic="architecture_observability",
            ),
            "code_reviewer": ObservabilityAgent(
                anthropic_config,
                name="Observability Reviewer",
                role="code_reviewer",
                response="Review observability view ready",
                provider_name="anthropic",
                model_name="snapshot-anthropic-demo",
                decision_topic="review_observability",
            ),
        }
    )


def build_observability_project(state_path: str) -> ProjectState:
    project = ProjectState(
        project_name="InternalObservabilityDemo",
        goal="Demonstrate an internal observability shell over persisted workflow state.",
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


def _format_metric(value: Any) -> str:
    return "none" if value is None else str(value)


def _presence_label(value: Any) -> str:
    return "present" if value else "none"


def _print_task_timeline(task_timeline: Sequence[Mapping[str, Any]]) -> None:
    for entry in task_timeline:
        print(
            f"- {entry['task_id']}: status={entry['status']}, "
            f"provider={entry['provider'] or 'none'}, "
            f"model={entry['model'] or 'none'}, "
            f"attempts={entry['attempts_used']}, retries={entry['retry_attempt_count']}, "
            f"task_ms={_format_metric(entry['task_duration_ms'])}, "
            f"provider_ms={_format_metric(entry['provider_duration_ms'])}, "
            f"output={_presence_label(entry['has_output'])}, "
            f"failure={_presence_label(entry['has_failure'])}"
        )


def _print_provider_panels(provider_panels: Sequence[Mapping[str, Any]]) -> None:
    for panel in provider_panels:
        status_names = [name for name, count in panel["status_counts"].items() if count > 0]
        outcome_names = [name for name, count in panel["last_outcome_counts"].items() if count > 0]
        print(
            f"- {panel['provider']}: tasks={panel['task_count']}; successes={panel['success_count']}; "
            f"failures={panel['failure_count']}; models={_format_csv(panel['models'])}; "
            f"statuses={_format_csv(status_names)}; outcomes={_format_csv(outcome_names)}; "
            f"active_checks={_presence_label(panel['active_health_check_count'] > 0)}"
        )


def main() -> None:
    config = KYCortexConfig(
        project_name="internal-observability-report-demo",
        output_dir=OUTPUT_DIR,
    )
    project = build_observability_project(STATE_PATH)
    registry = build_observability_registry(config)

    Orchestrator(config, registry=registry).execute_workflow(project)

    view = load_internal_observability_view(STATE_PATH)
    source = view["source"]
    overview = view["workflow_overview"]
    execution_panel = view["execution_panel"]

    print("Internal observability source:")
    print(f"State file: {Path(source['state_file']).name if source['state_file'] else 'none'}")
    print(f"State store: {source['state_store_kind']}")
    print(f"Schema version: {source['schema_version']}")

    print("\nWorkflow overview:")
    workflow_status = getattr(overview["workflow_status"], "value", overview["workflow_status"])
    print(f"Workflow status: {workflow_status}")
    print(f"Phase: {overview['phase']}")
    print(f"Acceptance met: {str(overview['acceptance_criteria_met']).lower()}")
    print(f"Final providers: {_format_csv(overview['final_providers'])}")
    print(f"Observed providers: {_format_csv(overview['observed_providers'])}")

    print("\nTask timeline:")
    _print_task_timeline(view["task_timeline"])

    print("\nProvider panels:")
    _print_provider_panels(view["provider_panels"])

    print("\nExecution diagnostics:")
    print(f"resume_events={execution_panel['resume_summary']['resume_event_count']}")
    print(f"repair_cycles={execution_panel['repair_summary']['cycle_count']}")
    print(f"fallback_entries={execution_panel['fallback_summary']['entry_count']}")
    print(f"final_errors={execution_panel['error_summary']['final_error_count']}")


if __name__ == "__main__":
    main()