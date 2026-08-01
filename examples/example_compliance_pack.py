from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator, ProjectState
from kycortex_agents.workflows.compliance import build_compliance_project, get_compliance_scenario, list_compliance_scenarios

DETERMINISTIC_CODE_MODULE = '''from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class ComplianceRequest:
    request_id: str
    request_type: str
    details: Dict[str, Any]
    timestamp: datetime


class ComplianceIntakeService:
    def __init__(self) -> None:
        self.audit_history: List[Dict[str, Any]] = []

    def validate_request(self, request: ComplianceRequest) -> bool:
        if not isinstance(request.details, dict):
            return False
        return isinstance(request.timestamp, datetime)

    def handle_request(self, request: ComplianceRequest) -> Dict[str, Any]:
        if not isinstance(request.details, dict):
            raise ValueError("details must be a dict")
        risk = 0
        risk += 5 if not request.details.get("identity_evidence") else 0
        risk += 3 * len(request.details.get("adverse_indicators", []))
        risk += 2 * len(request.details.get("missing_documents", []))
        outcome = "blocked" if risk >= 10 else "escalated" if risk >= 5 else "approved"
        record = {"request_id": request.request_id, "risk_score": risk, "outcome": outcome}
        self.audit_history.append(record)
        return record


if __name__ == "__main__":
    print("compliance intake demo ready")
'''


class RecordingAgent(BaseAgent):
    def __init__(self, config: KYCortexConfig, response: str):
        super().__init__(name="Recording Agent", role="deterministic", config=config)
        self.response = response

    def run(self, task_description: str, context: dict) -> str:
        return self.response


def build_deterministic_registry(config: KYCortexConfig) -> AgentRegistry:
    return AgentRegistry(
        {
            "architect": RecordingAgent(config, "ARCHITECTURE READY"),
            "code_engineer": RecordingAgent(config, DETERMINISTIC_CODE_MODULE),
            "dependency_manager": RecordingAgent(config, "NO THIRD-PARTY RUNTIME DEPENDENCIES"),
            "qa_tester": RecordingAgent(config, "TEST PLAN READY"),
            "code_reviewer": RecordingAgent(config, "REVIEW COMPLETE"),
            "docs_writer": RecordingAgent(config, "DOCUMENTATION READY"),
            "legal_advisor": RecordingAgent(config, "LEGAL NOTE READY"),
        }
    )


def print_scenario_catalog() -> None:
    print("Built-in compliance scenarios:")
    for scenario in list_compliance_scenarios():
        print(f"- {scenario.slug}: {scenario.domain_summary}")


def print_workflow_plan(project: ProjectState) -> None:
    print("\nDependency-safe execution plan:")
    for task in project.execution_plan():
        upstream = ", ".join(task.dependencies) if task.dependencies else "none"
        print(f"- {task.id} ({task.assigned_to}) depends on: {upstream}")


def main() -> None:
    config = KYCortexConfig(
        project_name="compliance-pack-demo",
        output_dir="./output_compliance_pack_demo",
    )
    scenario = get_compliance_scenario("kyc_compliance_intake")
    project = build_compliance_project(scenario, state_file="./output_compliance_pack_demo/project_state.json")

    print_scenario_catalog()
    print_workflow_plan(project)

    registry = build_deterministic_registry(config)
    orchestrator = Orchestrator(config, registry=registry)
    orchestrator.execute_workflow(project)

    print("\nCompliance pack workflow summary:")
    print(project.summary())
    print("\nTask statuses:")
    for task in project.tasks:
        print(f"- {task.id}: {task.status}")


if __name__ == "__main__":
    main()
