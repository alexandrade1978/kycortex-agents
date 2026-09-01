from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator, ProjectState
from kycortex_agents.workflows.compliance import ComplianceScenario, build_compliance_project, get_compliance_scenario, list_compliance_scenarios

def build_deterministic_code_module(service_name: str, request_name: str) -> str:
    return f'''from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class {request_name}:
    request_id: str
    request_type: str
    details: Dict[str, Any]
    timestamp: datetime


class {service_name}:
    def __init__(self) -> None:
        self.audit_history: List[Dict[str, Any]] = []

    def validate_request(self, request: {request_name}) -> bool:
        if not isinstance(request.details, dict):
            return False
        return isinstance(request.timestamp, datetime)

    def handle_request(self, request: {request_name}) -> Dict[str, Any]:
        if not isinstance(request.details, dict):
            raise ValueError("details must be a dict")
        risk = 0
        risk += 5 if not request.details.get("identity_evidence") else 0
        risk += 3 * len(request.details.get("adverse_indicators", []))
        risk += 2 * len(request.details.get("missing_documents", []))
        outcome = "blocked" if risk >= 10 else "escalated" if risk >= 5 else "approved"
        record = {{"request_id": request.request_id, "risk_score": risk, "outcome": outcome}}
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


def build_deterministic_registry(config: KYCortexConfig, scenario: ComplianceScenario) -> AgentRegistry:
    code_module = build_deterministic_code_module(scenario.service_name, scenario.request_name)
    return AgentRegistry(
        {
            "architect": RecordingAgent(config, "ARCHITECTURE READY"),
            "code_engineer": RecordingAgent(config, code_module),
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
    
    print_scenario_catalog()

    # Verify lookup by slug
    _intake = get_compliance_scenario("kyc_compliance_intake")

    # Demonstrate running all built-in scenarios
    scenarios = list_compliance_scenarios()
    print(f"\nExecuting {len(scenarios)} compliance scenario workflows:")

    for scenario in scenarios:
        state_file = f"./output_compliance_pack_demo/{scenario.slug}_state.json"
        project = build_compliance_project(scenario, state_file=state_file)
        
        print(f"\n--- Scenario: {scenario.slug} ({scenario.project_name}) ---")
        print_workflow_plan(project)

        registry = build_deterministic_registry(config, scenario)
        orchestrator = Orchestrator(config, registry=registry)
        orchestrator.execute_workflow(project)

        print(f"Workflow status: {project.summary()}")



if __name__ == "__main__":
    main()
