import pytest

from kycortex_agents import AgentRegistry, BaseAgent, KYCortexConfig, Orchestrator
from kycortex_agents.agents.registry import build_default_registry
from kycortex_agents.exceptions import WorkflowDefinitionError
from kycortex_agents.types import TaskStatus, WorkflowOutcome
from kycortex_agents.workflows.compliance import (
    BUILTIN_COMPLIANCE_SCENARIOS,
    KYC_COMPLIANCE_INTAKE,
    build_compliance_project,
    get_compliance_scenario,
    list_compliance_scenarios,
)

EXPECTED_TASK_IDS = ["arch", "code", "deps", "tests", "review", "docs", "legal"]

DETERMINISTIC_CODE_MODULE = '''from dataclasses import dataclass, field
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


def test_builtin_scenario_registry_exposes_kyc_intake():
    scenarios = list_compliance_scenarios()

    assert scenarios == BUILTIN_COMPLIANCE_SCENARIOS
    assert KYC_COMPLIANCE_INTAKE in scenarios
    assert get_compliance_scenario("kyc_compliance_intake") is KYC_COMPLIANCE_INTAKE
    assert get_compliance_scenario("  KYC_Compliance_Intake  ") is KYC_COMPLIANCE_INTAKE


def test_unknown_scenario_slug_fails_fast():
    with pytest.raises(WorkflowDefinitionError) as excinfo:
        get_compliance_scenario("unknown_pack")

    assert "unknown_pack" in str(excinfo.value)
    assert "kyc_compliance_intake" in str(excinfo.value)


def test_build_compliance_project_produces_validated_task_graph(tmp_path):
    state_file = str(tmp_path / "project_state.json")
    project = build_compliance_project(KYC_COMPLIANCE_INTAKE, state_file=state_file)

    assert project.project_name == "KYCComplianceIntake"
    assert project.goal == KYC_COMPLIANCE_INTAKE.goal
    assert project.state_file == state_file
    assert [task.id for task in project.tasks] == EXPECTED_TASK_IDS

    plan_ids = [task.id for task in project.execution_plan()]
    assert plan_ids[0] == "arch"
    assert plan_ids[-1] == "legal"
    assert plan_ids.index("code") < plan_ids.index("tests")
    assert plan_ids.index("deps") < plan_ids.index("tests")

    default_agent_keys = set(build_default_registry(KYCortexConfig(output_dir=str(tmp_path / "output"))).keys())
    assigned_agents = {task.assigned_to for task in project.tasks}
    assert assigned_agents <= default_agent_keys


def test_build_compliance_project_embeds_scenario_contracts():
    project = build_compliance_project(KYC_COMPLIANCE_INTAKE)

    code_task = project.get_task("code")
    tests_task = project.get_task("tests")
    legal_task = project.get_task("legal")
    assert code_task is not None
    assert tests_task is not None
    assert legal_task is not None

    assert "Public facade: ComplianceIntakeService" in code_task.description
    assert "ComplianceRequest(request_id, request_type, details, timestamp)" in code_task.description
    assert "identity_evidence, jurisdiction, customer_type, adverse_indicators, and missing_documents" in code_task.description
    assert repr(dict(KYC_COMPLIANCE_INTAKE.detail_fixture_example)) in tests_task.description
    assert "privacy and retention of customer evidence" in legal_task.description


def test_compliance_project_runs_end_to_end_with_deterministic_agents(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    project = build_compliance_project(KYC_COMPLIANCE_INTAKE, state_file=str(tmp_path / "project_state.json"))

    Orchestrator(config, registry=build_deterministic_registry(config)).execute_workflow(project)

    assert project.terminal_outcome == WorkflowOutcome.COMPLETED.value
    assert all(task.status == TaskStatus.DONE.value for task in project.tasks)
    assert all(task.output for task in project.tasks)
