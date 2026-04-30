import importlib.util
import json
import sys
from pathlib import Path

from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import FailureCategory, WorkflowOutcome


def _load_script_module(module_name: str, relative_path: str):
    project_root = Path(__file__).resolve().parents[1]
    module_path = project_root / relative_path
    sys.path.insert(0, str(project_root))
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)
        sys.path.pop(0)


def _write_strict_invalid_request_tests_artifact(
    output_dir: Path,
    *,
    module_name: str,
    service_name: str,
    request_name: str,
) -> None:
    tests_path = output_dir / "artifacts" / "tests_tests.py"
    tests_path.write_text(
        "import pytest\n"
        "from datetime import datetime\n"
        f"from {module_name} import {service_name}, {request_name}\n\n"
        "def test_validation_failure():\n"
        f"    service = {service_name}()\n"
        "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
        f"    invalid_request = {request_name}(request_id='request_id-1', request_type='screening', details=None, timestamp=fixed_time)\n"
        "    assert service.validate_request(invalid_request) is False\n"
        "    with pytest.raises(ValueError):\n"
        "        service.handle_request(invalid_request)\n",
        encoding="utf-8",
    )


def _write_permissive_invalid_request_tests_artifact(
    output_dir: Path,
    *,
    module_name: str,
    service_name: str,
    request_name: str,
) -> None:
    tests_path = output_dir / "artifacts" / "tests_tests.py"
    tests_path.write_text(
        "from datetime import datetime\n"
        f"from {module_name} import {service_name}, {request_name}\n\n"
        "def test_validation_failure():\n"
        f"    service = {service_name}()\n"
        "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
        f"    invalid_request = {request_name}(request_id='request_id-1', request_type='screening', details=None, timestamp=fixed_time)\n"
        "    validation_result = service.validate_request(invalid_request)\n"
        "    assert validation_result is False\n"
        "    try:\n"
        "        fallback_result = service.handle_request(invalid_request)\n"
        "    except ValueError:\n"
        "        pass\n"
        "    else:\n"
        "        assert isinstance(fallback_result, dict)\n",
        encoding="utf-8",
    )


def test_validate_generated_scenario_accepts_public_contract_and_behavior(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_validation_success_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    output_dir = tmp_path / "campaign"
    artifact_path = output_dir / "artifacts" / "compliance_service.py"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        "from dataclasses import dataclass\n"
        "from datetime import datetime\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    request_id: str\n"
        "    request_type: str\n"
        "    details: dict\n"
        "    timestamp: datetime\n\n"
        "class ComplianceIntakeService:\n"
        "    def __init__(self):\n"
        "        self.audit_history = []\n\n"
        "    def validate_request(self, request):\n"
        "        return isinstance(request.details, dict) and 'identity_evidence' in request.details\n\n"
        "    def handle_request(self, request):\n"
        "        if not self.validate_request(request):\n"
        "            raise ValueError('invalid request')\n"
        "        risk = 1\n"
        "        if request.details.get('jurisdiction') == 'sanctioned':\n"
        "            risk += 5\n"
        "        if request.details.get('missing_documents'):\n"
        "            risk += 3\n"
        "        outcome = 'blocked' if risk >= 6 else 'approved'\n"
        "        self.audit_history.append({'request_id': request.request_id, 'risk': risk, 'outcome': outcome})\n"
        "        return {'risk': risk, 'outcome': outcome}\n",
        encoding="utf-8",
    )
    task = Task(
        id="code",
        title="Implementation",
        description="Implement",
        assigned_to="code_engineer",
        output_payload={"artifacts": [{"path": "artifacts/compliance_service.py"}]},
    )
    _write_strict_invalid_request_tests_artifact(
        output_dir,
        module_name="compliance_service",
        service_name="ComplianceIntakeService",
        request_name="ComplianceRequest",
    )

    result = module._validate_generated_scenario(module.SCENARIOS[0], task, str(output_dir))

    assert result["validated"] is True
    assert result["artifact_path"] == "compliance_service.py"
    assert result["checks"]["syntax_valid"] is True
    assert result["checks"]["stdlib_only"] is True
    assert result["checks"]["risk_signal_observable"] is True
    assert result["checks"]["audit_signal_present"] is True


def test_validate_generated_scenario_rejects_missing_real_workflow_signal(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_validation_failure_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    output_dir = tmp_path / "campaign"
    artifact_path = output_dir / "artifacts" / "compliance_service.py"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        "from dataclasses import dataclass\n"
        "from datetime import datetime\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    request_id: str\n"
        "    request_type: str\n"
        "    details: dict\n"
        "    timestamp: datetime\n\n"
        "class ComplianceIntakeService:\n"
        "    def validate_request(self, request):\n"
        "        return isinstance(request.details, dict)\n\n"
        "    def handle_request(self, request):\n"
        "        if not self.validate_request(request):\n"
        "            raise ValueError('invalid request')\n"
        "        return None\n",
        encoding="utf-8",
    )
    task = Task(
        id="code",
        title="Implementation",
        description="Implement",
        assigned_to="code_engineer",
        output_payload={"artifacts": [{"path": "artifacts/compliance_service.py"}]},
    )
    _write_strict_invalid_request_tests_artifact(
        output_dir,
        module_name="compliance_service",
        service_name="ComplianceIntakeService",
        request_name="ComplianceRequest",
    )

    result = module._validate_generated_scenario(module.SCENARIOS[0], task, str(output_dir))

    assert result["validated"] is False
    assert result["checks"]["valid_request_accepted"] is True
    assert result["checks"]["invalid_request_rejected"] is True
    assert result["checks"]["risk_signal_observable"] is False
    assert "low-risk and high-risk" in result["error"]


def test_validate_generated_scenario_rejects_unbound_local_error_on_invalid_path(tmp_path):
    """The invalid_request_handled check must catch programming errors like
    UnboundLocalError in handle_request when given an invalid request."""
    module = _load_script_module(
        "real_world_complex_matrix_invalid_path_crash_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    output_dir = tmp_path / "campaign"
    artifact_path = output_dir / "artifacts" / "compliance_service.py"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    # This implementation has the exact bug pattern from insurance_claim_triage/ollama v21:
    # when validate_request returns False, risk_score is never assigned but still referenced.
    artifact_path.write_text(
        "from dataclasses import dataclass\n"
        "from datetime import datetime\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    request_id: str\n"
        "    request_type: str\n"
        "    details: dict\n"
        "    timestamp: datetime\n\n"
        "class ComplianceIntakeService:\n"
        "    def __init__(self):\n"
        "        self.audit_history = []\n\n"
        "    def validate_request(self, request):\n"
        "        return isinstance(request.details, dict) and 'identity_evidence' in request.details\n\n"
        "    def handle_request(self, request):\n"
        "        if not self.validate_request(request):\n"
        "            outcome = 'reject'\n"
        "        else:\n"
        "            risk = 1\n"
        "            if request.details.get('jurisdiction') == 'sanctioned':\n"
        "                risk += 5\n"
        "            if request.details.get('missing_documents'):\n"
        "                risk += 3\n"
        "            outcome = 'blocked' if risk >= 6 else 'approved'\n"
        "        # BUG: risk is not defined on the invalid path\n"
        "        self.audit_history.append({'request_id': request.request_id, 'risk': risk, 'outcome': outcome})\n"
        "        return {'risk': risk, 'outcome': outcome}\n",
        encoding="utf-8",
    )
    task = Task(
        id="code",
        title="Implementation",
        description="Implement",
        assigned_to="code_engineer",
        output_payload={"artifacts": [{"path": "artifacts/compliance_service.py"}]},
    )
    _write_strict_invalid_request_tests_artifact(
        output_dir,
        module_name="compliance_service",
        service_name="ComplianceIntakeService",
        request_name="ComplianceRequest",
    )

    result = module._validate_generated_scenario(module.SCENARIOS[0], task, str(output_dir))

    assert result["validated"] is False
    assert result["checks"]["invalid_request_rejected"] is True
    assert result["checks"]["invalid_request_handled"] is False
    assert "programming error" in result["error"].lower()


def test_validate_generated_scenario_rejects_malformed_request_without_explicit_handle_rejection(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_missing_explicit_invalid_rejection_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    output_dir = tmp_path / "campaign"
    artifact_path = output_dir / "artifacts" / "claim_service.py"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        "from dataclasses import dataclass\n"
        "from datetime import datetime\n"
        "from typing import Any\n\n"
        "@dataclass\n"
        "class ClaimRequest:\n"
        "    request_id: str\n"
        "    request_type: str\n"
        "    details: dict[str, Any] | Any\n"
        "    timestamp: datetime\n\n"
        "class ClaimTriageService:\n"
        "    def __init__(self):\n"
        "        self.audit_history = []\n\n"
        "    def validate_request(self, request):\n"
        "        return isinstance(request.details, dict) and 'policy_id' in request.details and 'claim_category' in request.details\n\n"
        "    def handle_request(self, request):\n"
        "        if not self.validate_request(request):\n"
        "            outcome = 'Invalid Request'\n"
        "            risk_score = 0.0\n"
        "        else:\n"
        "            risk_score = 0.0\n"
        "            if request.details.get('duplicate_claim', False):\n"
        "                risk_score += 0.5\n"
        "            if request.details.get('claim_amount', 0) > 100000:\n"
        "                risk_score += 0.3\n"
        "            if request.details.get('suspicious_timing', False):\n"
        "                risk_score += 0.2\n"
        "            if not request.details.get('evidence'):\n"
        "                risk_score += 0.4\n"
        "            outcome = 'Straight-Through Review' if risk_score < 0.3 else ('Manual Investigation' if risk_score < 0.7 else 'Fraud Escalation')\n"
        "        self.audit_history.append({'request_id': request.request_id, 'outcome': outcome, 'risk_score': risk_score})\n"
        "        return {'outcome': outcome, 'risk_score': risk_score}\n",
        encoding="utf-8",
    )
    task = Task(
        id="code",
        title="Implementation",
        description="Implement",
        assigned_to="code_engineer",
        output_payload={"artifacts": [{"path": "artifacts/claim_service.py"}]},
    )
    _write_strict_invalid_request_tests_artifact(
        output_dir,
        module_name="claim_service",
        service_name="ClaimTriageService",
        request_name="ClaimRequest",
    )

    insurance_spec = next(spec for spec in module.SCENARIOS if spec.slug == "insurance_claim_triage")
    result = module._validate_generated_scenario(insurance_spec, task, str(output_dir))

    assert result["validated"] is False
    assert result["checks"]["valid_request_accepted"] is True
    assert result["checks"]["invalid_request_rejected"] is True
    assert "explicitly reject a malformed request through handle_request" in result["error"]


def test_validate_generated_scenario_rejects_permissive_generated_invalid_request_test_artifact(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_permissive_invalid_request_test_artifact",
        "scripts/run_real_world_complex_matrix.py",
    )
    output_dir = tmp_path / "campaign"
    artifact_path = output_dir / "artifacts" / "compliance_service.py"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        "from dataclasses import dataclass\n"
        "from datetime import datetime\n\n"
        "@dataclass\n"
        "class ComplianceRequest:\n"
        "    request_id: str\n"
        "    request_type: str\n"
        "    details: dict | None\n"
        "    timestamp: datetime\n\n"
        "class ComplianceIntakeService:\n"
        "    def __init__(self):\n"
        "        self.audit_history = []\n\n"
        "    def validate_request(self, request):\n"
        "        return isinstance(request.details, dict) and 'identity_evidence' in request.details\n\n"
        "    def handle_request(self, request):\n"
        "        if not self.validate_request(request):\n"
        "            raise ValueError('invalid request')\n"
        "        risk = 1\n"
        "        if request.details.get('jurisdiction') == 'sanctioned':\n"
        "            risk += 5\n"
        "        if request.details.get('missing_documents'):\n"
        "            risk += 3\n"
        "        outcome = 'blocked' if risk >= 6 else 'approved'\n"
        "        self.audit_history.append({'request_id': request.request_id, 'risk': risk, 'outcome': outcome})\n"
        "        return {'risk': risk, 'outcome': outcome}\n",
        encoding="utf-8",
    )
    _write_permissive_invalid_request_tests_artifact(
        output_dir,
        module_name="compliance_service",
        service_name="ComplianceIntakeService",
        request_name="ComplianceRequest",
    )
    task = Task(
        id="code",
        title="Implementation",
        description="Implement",
        assigned_to="code_engineer",
        output_payload={"artifacts": [{"path": "artifacts/compliance_service.py"}]},
    )

    result = module._validate_generated_scenario(module.SCENARIOS[0], task, str(output_dir))

    assert result["validated"] is False
    assert result["checks"]["invalid_request_rejected"] is True
    assert result["checks"]["generated_tests_assert_invalid_request_value_error"] is False
    assert "Generated tests did not explicitly assert ValueError" in result["error"]


def test_build_project_includes_exact_details_contract_anchor_for_kyc_scenario(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_contract_anchor_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    project = module.build_project(module.SCENARIOS[0], str(tmp_path / "campaign" / "openai"))
    code_task = next(task for task in project.tasks if task.id == "code")
    tests_task = next(task for task in project.tasks if task.id == "tests")

    expected_keys = (
        "identity_evidence, jurisdiction, customer_type, adverse_indicators, and missing_documents"
    )
    anti_alias_instruction = (
        "Do not replace it with guessed aliases such as identity_proof, address_proof, documents, or document_list."
    )
    observable_outcome_instruction = "handle_request(request) must return a per-request outcome object or dict, not None."
    zero_arg_constructor_instruction = (
        "Keep ComplianceIntakeService instantiable with zero required constructor arguments."
    )

    assert expected_keys in code_task.description
    assert anti_alias_instruction in code_task.description
    assert observable_outcome_instruction in code_task.description
    assert zero_arg_constructor_instruction in code_task.description
    assert expected_keys in tests_task.description
    assert anti_alias_instruction in tests_task.description
    assert observable_outcome_instruction in tests_task.description
    assert zero_arg_constructor_instruction in tests_task.description


def test_build_project_includes_typed_detail_contract_anchor_for_kyc_scenario(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_kyc_typed_contract_anchor_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    project = module.build_project(module.SCENARIOS[0], str(tmp_path / "campaign" / "openai"))
    code_task = next(task for task in project.tasks if task.id == "code")
    tests_task = next(task for task in project.tasks if task.id == "tests")

    typed_detail_instruction = (
        "Keep jurisdiction and customer_type as strings. Keep identity_evidence, adverse_indicators, and missing_documents as list-like collections inside details, not numeric severity placeholders or plain strings."
    )

    assert typed_detail_instruction in code_task.description
    assert typed_detail_instruction in tests_task.description


def test_build_project_code_task_requires_dataclass_import_when_decorator_used(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_dataclass_import_prompt_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    project = module.build_project(module.SCENARIOS[0], str(tmp_path / "campaign" / "openai"))
    code_task = next(task for task in project.tasks if task.id == "code")

    assert "If you use @dataclass anywhere in the module, import dataclass explicitly from dataclasses so the module imports cleanly." in code_task.description


def test_kyc_scenario_request_payloads_preserve_typed_details():
    module = _load_script_module(
        "real_world_complex_matrix_kyc_payloads_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    payloads = module._scenario_request_payloads(module.SCENARIOS[0])

    low_details = payloads["low"]["details"]
    high_details = payloads["high"]["details"]

    assert isinstance(low_details["jurisdiction"], str)
    assert isinstance(low_details["customer_type"], str)
    assert isinstance(low_details["identity_evidence"], list)
    assert isinstance(low_details["adverse_indicators"], list)
    assert isinstance(low_details["missing_documents"], list)
    assert isinstance(high_details["jurisdiction"], str)
    assert isinstance(high_details["customer_type"], str)
    assert isinstance(high_details["identity_evidence"], list)
    assert isinstance(high_details["adverse_indicators"], list)
    assert isinstance(high_details["missing_documents"], list)


def test_build_project_includes_collection_type_contract_anchor_for_vendor_scenario(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_vendor_contract_anchor_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    vendor_spec = next(spec for spec in module.SCENARIOS if spec.slug == "vendor_onboarding_risk")
    project = module.build_project(vendor_spec, str(tmp_path / "campaign" / "ollama"))
    code_task = next(task for task in project.tasks if task.id == "code")
    tests_task = next(task for task in project.tasks if task.id == "tests")

    collection_type_instruction = (
        "Keep sanctioned_region and critical_service as boolean flags. Keep expired_certifications and unresolved_incidents as list-like collections, using [] when absent and explicit list entries when risk is present."
    )

    assert collection_type_instruction in code_task.description
    assert collection_type_instruction in tests_task.description


def test_build_project_includes_typed_detail_contract_anchor_for_insurance_scenario(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_insurance_contract_anchor_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    insurance_spec = next(spec for spec in module.SCENARIOS if spec.slug == "insurance_claim_triage")
    project = module.build_project(insurance_spec, str(tmp_path / "campaign" / "openai"))
    code_task = next(task for task in project.tasks if task.id == "code")
    tests_task = next(task for task in project.tasks if task.id == "tests")

    typed_detail_instruction = (
        "Keep policy_id and claim_category as strings, claim_amount as a numeric amount, evidence as a list-like collection, and duplicate_claim plus suspicious_timing as boolean flags."
    )

    assert typed_detail_instruction in code_task.description
    assert typed_detail_instruction in tests_task.description


def test_insurance_scenario_request_payloads_preserve_typed_details():
    module = _load_script_module(
        "real_world_complex_matrix_insurance_payloads_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    insurance_spec = next(spec for spec in module.SCENARIOS if spec.slug == "insurance_claim_triage")
    payloads = module._scenario_request_payloads(insurance_spec)

    low_details = payloads["low"]["details"]
    high_details = payloads["high"]["details"]

    assert isinstance(low_details["policy_id"], str)
    assert isinstance(low_details["claim_category"], str)
    assert isinstance(low_details["claim_amount"], (int, float))
    assert isinstance(low_details["evidence"], list)
    assert isinstance(low_details["duplicate_claim"], bool)
    assert isinstance(low_details["suspicious_timing"], bool)
    assert isinstance(high_details["policy_id"], str)
    assert isinstance(high_details["claim_category"], str)
    assert isinstance(high_details["claim_amount"], (int, float))
    assert isinstance(high_details["evidence"], list)
    assert isinstance(high_details["duplicate_claim"], bool)
    assert isinstance(high_details["suspicious_timing"], bool)


def test_vendor_scenario_request_payloads_preserve_collection_typed_risk_inputs():
    module = _load_script_module(
        "real_world_complex_matrix_vendor_payloads_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    vendor_spec = next(spec for spec in module.SCENARIOS if spec.slug == "vendor_onboarding_risk")
    payloads = module._scenario_request_payloads(vendor_spec)

    low_details = payloads["low"]["details"]
    high_details = payloads["high"]["details"]

    assert low_details["expired_certifications"] == []
    assert low_details["unresolved_incidents"] == []
    assert high_details["expired_certifications"] == ["iso27001"]
    assert high_details["unresolved_incidents"] == ["sev1", "sev2", "sev3"]


def test_build_project_includes_typed_detail_contract_anchor_for_returns_scenario(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_returns_contract_anchor_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    returns_spec = next(spec for spec in module.SCENARIOS if spec.slug == "returns_abuse_screening")
    project = module.build_project(returns_spec, str(tmp_path / "campaign" / "ollama"))
    code_task = next(task for task in project.tasks if task.id == "code")
    tests_task = next(task for task in project.tasks if task.id == "tests")

    typed_detail_instruction = (
        "Keep order_reference and return_reason as strings, receipt_present as a boolean flag, and prior_returns plus timing_days as integers. Keep items as a list-like collection of item payload records, not a plain string placeholder."
    )

    assert typed_detail_instruction in code_task.description
    assert typed_detail_instruction in tests_task.description


def test_returns_scenario_request_payloads_preserve_typed_details():
    module = _load_script_module(
        "real_world_complex_matrix_returns_payloads_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    returns_spec = next(spec for spec in module.SCENARIOS if spec.slug == "returns_abuse_screening")
    payloads = module._scenario_request_payloads(returns_spec)

    low_details = payloads["low"]["details"]
    high_details = payloads["high"]["details"]

    assert isinstance(low_details["items"], list)
    assert isinstance(low_details["receipt_present"], bool)
    assert isinstance(low_details["prior_returns"], int)
    assert isinstance(low_details["timing_days"], int)
    assert isinstance(high_details["items"], list)
    assert isinstance(high_details["receipt_present"], bool)
    assert isinstance(high_details["prior_returns"], int)
    assert isinstance(high_details["timing_days"], int)


def test_build_project_includes_typed_detail_contract_anchor_for_access_review_scenario(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_access_contract_anchor_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    access_spec = next(spec for spec in module.SCENARIOS if spec.slug == "access_review_audit")
    project = module.build_project(access_spec, str(tmp_path / "campaign" / "openai"))
    code_task = next(task for task in project.tasks if task.id == "code")
    tests_task = next(task for task in project.tasks if task.id == "tests")

    typed_detail_instruction = (
        "Keep requester_identity as a string, requested_roles and sod_conflicts as list-like collections, approval_metadata as a mapping object, and emergency_access plus stale_approval as boolean flags."
    )

    assert typed_detail_instruction in code_task.description
    assert typed_detail_instruction in tests_task.description


def test_access_review_scenario_request_payloads_preserve_typed_details():
    module = _load_script_module(
        "real_world_complex_matrix_access_payloads_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    access_spec = next(spec for spec in module.SCENARIOS if spec.slug == "access_review_audit")
    payloads = module._scenario_request_payloads(access_spec)

    low_details = payloads["low"]["details"]
    high_details = payloads["high"]["details"]

    assert isinstance(low_details["requester_identity"], str)
    assert isinstance(low_details["requested_roles"], list)
    assert isinstance(low_details["approval_metadata"], dict)
    assert isinstance(low_details["sod_conflicts"], list)
    assert isinstance(low_details["emergency_access"], bool)
    assert isinstance(low_details["stale_approval"], bool)
    assert isinstance(high_details["requester_identity"], str)
    assert isinstance(high_details["requested_roles"], list)
    assert isinstance(high_details["approval_metadata"], dict)
    assert isinstance(high_details["sod_conflicts"], list)
    assert isinstance(high_details["emergency_access"], bool)
    assert isinstance(high_details["stale_approval"], bool)


def test_validate_generated_returns_scenario_accepts_constructor_rejected_invalid_request(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_returns_constructor_rejection_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    output_dir = tmp_path / "campaign"
    artifact_path = output_dir / "artifacts" / "returns_service.py"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        "from dataclasses import dataclass\n"
        "from datetime import datetime\n"
        "from typing import Any\n\n"
        "@dataclass\n"
        "class ReturnCase:\n"
        "    request_id: str\n"
        "    request_type: str\n"
        "    details: dict[str, Any]\n"
        "    timestamp: datetime\n\n"
        "    def __post_init__(self):\n"
        "        if not isinstance(self.details, dict):\n"
        "            raise ValueError('details must be a dict')\n"
        "        if not isinstance(self.details.get('order_reference'), str):\n"
        "            raise ValueError('Invalid order_reference')\n"
        "        if not isinstance(self.details.get('return_reason'), str):\n"
        "            raise ValueError('Invalid return_reason')\n"
        "        if not isinstance(self.details.get('items'), list):\n"
        "            raise ValueError('Invalid items')\n"
        "        if not isinstance(self.details.get('receipt_present'), bool):\n"
        "            raise ValueError('Invalid receipt_present')\n"
        "        if not isinstance(self.details.get('prior_returns'), int):\n"
        "            raise ValueError('Invalid prior_returns')\n"
        "        if not isinstance(self.details.get('timing_days'), int):\n"
        "            raise ValueError('Invalid timing_days')\n\n"
        "class ReturnScreeningService:\n"
        "    def __init__(self):\n"
        "        self.audit_history = []\n\n"
        "    def validate_request(self, request):\n"
        "        try:\n"
        "            request.__post_init__()\n"
        "            return True\n"
        "        except ValueError:\n"
        "            return False\n\n"
        "    def handle_request(self, request):\n"
        "        if not self.validate_request(request):\n"
        "            raise ValueError('invalid request')\n"
        "        risk_score = 0\n"
        "        if request.details['prior_returns'] > 2:\n"
        "            risk_score += 3\n"
        "        if not request.details['receipt_present']:\n"
        "            risk_score += 2\n"
        "        if any(item.get('value', 0) > 1000 for item in request.details['items']):\n"
        "            risk_score += 4\n"
        "        outcome = 'escalated' if risk_score >= 5 else 'approved'\n"
        "        self.audit_history.append({'request_id': request.request_id, 'outcome': outcome, 'risk_score': risk_score})\n"
        "        return {'outcome': outcome, 'risk_score': risk_score}\n",
        encoding="utf-8",
    )
    task = Task(
        id="code",
        title="Implementation",
        description="Implement",
        assigned_to="code_engineer",
        output_payload={"artifacts": [{"path": "artifacts/returns_service.py"}]},
    )
    _write_strict_invalid_request_tests_artifact(
        output_dir,
        module_name="returns_service",
        service_name="ReturnScreeningService",
        request_name="ReturnCase",
    )

    returns_spec = next(spec for spec in module.SCENARIOS if spec.slug == "returns_abuse_screening")
    result = module._validate_generated_scenario(returns_spec, task, str(output_dir))

    assert result["validated"] is True
    assert result["checks"]["invalid_request_rejected"] is True
    assert result["checks"]["valid_request_accepted"] is True
    assert result["checks"]["audit_signal_present"] is True


def test_run_scenario_provider_reclassifies_scenario_validation_failure(tmp_path, monkeypatch):
    module = _load_script_module(
        "real_world_complex_matrix_run_reclassify_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    monkeypatch.setattr(module, "get_provider_availability", lambda provider, **kwargs: {"provider": provider, "available": True, "reason": None})
    monkeypatch.setattr(module, "resolve_model", lambda provider, model=None, **kwargs: "gpt-4o-mini")
    monkeypatch.setattr(module, "build_full_workflow_config", lambda *args, **kwargs: type("FakeConfig", (), {"workflow_acceptance_policy": "all_tasks"})())

    def fake_execute(config, project):
        run_root = Path(project.state_file).parent
        artifact_path = run_root / "artifacts" / "generated.py"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("def placeholder():\n    return 1\n", encoding="utf-8")
        project.mark_workflow_running(acceptance_policy="all_tasks", repair_max_cycles=1)
        for task in project.tasks:
            task.status = "done"
            if task.id == "code":
                task.output_payload = {"artifacts": [{"path": "artifacts/generated.py"}]}
        project.mark_workflow_finished(
            "completed",
            acceptance_policy="all_tasks",
            terminal_outcome=WorkflowOutcome.COMPLETED.value,
            acceptance_criteria_met=True,
            acceptance_evaluation={
                "policy": "all_tasks",
                "accepted": True,
                "reason": "all_evaluated_tasks_done",
                "evaluated_task_ids": [task.id for task in project.tasks],
                "required_task_ids": [],
                "completed_task_ids": [task.id for task in project.tasks],
                "failed_task_ids": [],
                "skipped_task_ids": [],
                "pending_task_ids": [],
            },
        )
        project.save()

    monkeypatch.setattr(module, "execute_empirical_validation_workflow", fake_execute)
    monkeypatch.setattr(
        module,
        "_validate_generated_scenario",
        lambda spec, task, output_dir: {
            "validated": False,
            "artifact_path": "generated.py",
            "checks": {
                "syntax_valid": True,
                "stdlib_only": True,
                "service_constructor_supported": True,
                "request_signature_supported": True,
                "validation_surface_supported": True,
                "valid_request_accepted": True,
                "invalid_request_rejected": True,
                "risk_signal_observable": False,
                "audit_signal_present": True,
                "batch_processing_supported": True,
            },
            "error": "Generated code did not expose an observable difference between low-risk and high-risk requests.",
            "observations": {},
        },
    )

    result = module.run_scenario_provider(
        module.SCENARIOS[0],
        "openai",
        output_root=tmp_path,
        failure_policy="continue",
        resume_policy="resume_failed",
        max_repair_cycles=1,
        ollama_base_url=None,
        ollama_num_ctx=16384,
        max_tokens=3200,
        run_index=1,
        total_runs=1,
    )

    assert result["status"] == "validation_error"
    assert result["acceptance_criteria_met"] is False
    assert result["failure_category"] == FailureCategory.SCENARIO_VALIDATION.value
    assert result["acceptance_reason"] == "scenario_validation_failed"
    assert result["summary"]["phase"] == "completed"
    assert result["summary"]["terminal_outcome"] == WorkflowOutcome.DEGRADED.value

    reloaded = ProjectState.load(str(tmp_path / module.SCENARIOS[0].slug / "openai" / "project_state.json"))
    assert reloaded.phase == "completed"
    assert reloaded.terminal_outcome == WorkflowOutcome.DEGRADED.value
    assert reloaded.failure_category == FailureCategory.SCENARIO_VALIDATION.value
    assert reloaded.acceptance_criteria_met is False
    assert reloaded.acceptance_evaluation["reason"] == "scenario_validation_failed"
    assert reloaded.acceptance_evaluation["acceptance_lanes"]["real_workflow"]["accepted"] is False


def test_run_scenario_provider_reuses_cached_result_for_terminal_state(tmp_path, monkeypatch):
    module = _load_script_module(
        "real_world_complex_matrix_cached_result_reuse_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    spec = module.SCENARIOS[0]
    run_root = tmp_path / spec.slug / "openai"
    run_root.mkdir(parents=True, exist_ok=True)

    project = module.build_project(spec, str(run_root))
    project.mark_workflow_running(acceptance_policy="all_tasks", repair_max_cycles=1)
    for task in project.tasks:
        task.status = "done"
    project.mark_workflow_finished(
        "completed",
        acceptance_policy="all_tasks",
        terminal_outcome=WorkflowOutcome.COMPLETED.value,
        acceptance_criteria_met=True,
        acceptance_evaluation={
            "policy": "all_tasks",
            "accepted": True,
            "reason": "all_evaluated_tasks_done",
            "evaluated_task_ids": [task.id for task in project.tasks],
            "required_task_ids": [],
            "completed_task_ids": [task.id for task in project.tasks],
            "failed_task_ids": [],
            "skipped_task_ids": [],
            "pending_task_ids": [],
        },
    )
    project.save()

    cached_result = {
        "scenario": spec.slug,
        "scenario_title": spec.project_name,
        "provider": "openai",
        "available": True,
        "availability_reason": None,
        "model": "gpt-4o-mini",
        "output_dir": str(run_root),
        "started_at": "2026-04-29T00:00:00+00:00",
        "status": "completed",
        "scenario_validation": {"validated": True, "checks": {}, "error": None, "observations": {}},
        "duration_seconds": 1.0,
        "completed_at": "2026-04-29T00:00:01+00:00",
        "summary": {"phase": "completed", "terminal_outcome": WorkflowOutcome.COMPLETED.value},
        "acceptance_criteria_met": True,
        "failure_category": None,
        "acceptance_reason": "all_evaluated_tasks_done",
    }
    (run_root / "run_result.json").write_text(json.dumps(cached_result), encoding="utf-8")

    def should_not_run(*args, **kwargs):
        raise AssertionError("existing terminal runs should be reused, not re-executed")

    monkeypatch.setattr(module, "build_project", should_not_run)
    monkeypatch.setattr(module, "get_provider_availability", should_not_run)
    monkeypatch.setattr(module, "execute_empirical_validation_workflow", should_not_run)

    result = module.run_scenario_provider(
        spec,
        "openai",
        output_root=tmp_path,
        failure_policy="continue",
        resume_policy="resume_failed",
        max_repair_cycles=1,
        ollama_base_url=None,
        ollama_num_ctx=16384,
        max_tokens=3200,
        run_index=1,
        total_runs=1,
    )

    assert result == cached_result


def test_run_scenario_provider_loads_existing_failed_state_when_resuming(tmp_path, monkeypatch):
    module = _load_script_module(
        "real_world_complex_matrix_resume_load_existing_state_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    monkeypatch.setattr(
        module,
        "get_provider_availability",
        lambda provider, **kwargs: {"provider": provider, "available": True, "reason": None},
    )
    monkeypatch.setattr(
        module,
        "resolve_model",
        lambda provider, model=None, **kwargs: "qwen2.5-coder:14b",
    )
    monkeypatch.setattr(
        module,
        "build_full_workflow_config",
        lambda *args, **kwargs: type("FakeConfig", (), {"workflow_acceptance_policy": "all_tasks"})(),
    )

    vendor_spec = next(spec for spec in module.SCENARIOS if spec.slug == "vendor_onboarding_risk")
    run_root = tmp_path / vendor_spec.slug / "ollama"
    run_root.mkdir(parents=True, exist_ok=True)

    existing_project = module.build_project(vendor_spec, str(run_root))
    existing_project.project_name = "SentinelResumeProject"
    failed_task = next(task for task in existing_project.tasks if task.id == "code")
    failed_task.status = "failed"
    failed_task.last_error = "boom"
    failed_task.last_error_type = "AgentExecutionError"
    failed_task.last_error_category = FailureCategory.CODE_VALIDATION.value
    existing_project.phase = "failed"
    existing_project.terminal_outcome = WorkflowOutcome.FAILED.value
    existing_project.repair_cycle_count = 1
    existing_project.save()

    def should_not_build(*args, **kwargs):
        raise AssertionError("resume should load the existing project state instead of rebuilding it")

    monkeypatch.setattr(module, "build_project", should_not_build)

    def fake_execute(config, project):
        assert project.project_name == "SentinelResumeProject"
        assert next(task for task in project.tasks if task.id == "code").status == "failed"
        project.mark_workflow_running(acceptance_policy="all_tasks", repair_max_cycles=1)
        for task in project.tasks:
            task.status = "done"
        project.mark_workflow_finished(
            "completed",
            acceptance_policy="all_tasks",
            terminal_outcome=WorkflowOutcome.COMPLETED.value,
            acceptance_criteria_met=True,
            acceptance_evaluation={
                "policy": "all_tasks",
                "accepted": True,
                "reason": "all_evaluated_tasks_done",
                "evaluated_task_ids": [task.id for task in project.tasks],
                "required_task_ids": [],
                "completed_task_ids": [task.id for task in project.tasks],
                "failed_task_ids": [],
                "skipped_task_ids": [],
                "pending_task_ids": [],
            },
        )
        project.save()

    monkeypatch.setattr(module, "execute_empirical_validation_workflow", fake_execute)
    monkeypatch.setattr(
        module,
        "_validate_generated_scenario",
        lambda spec, task, output_dir: {
            "validated": True,
            "artifact_path": None,
            "checks": {
                "syntax_valid": True,
                "stdlib_only": True,
                "service_constructor_supported": True,
                "request_signature_supported": True,
                "validation_surface_supported": True,
                "valid_request_accepted": True,
                "invalid_request_rejected": True,
                "generated_tests_assert_invalid_request_value_error": True,
                "risk_signal_observable": True,
                "audit_signal_present": True,
                "batch_processing_supported": True,
            },
            "error": None,
            "observations": {},
        },
    )

    result = module.run_scenario_provider(
        vendor_spec,
        "ollama",
        output_root=tmp_path,
        failure_policy="continue",
        resume_policy="resume_failed",
        max_repair_cycles=1,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_num_ctx=16384,
        ollama_timeout_seconds=420.0,
        max_tokens=3200,
        run_index=1,
        total_runs=1,
    )

    assert result["status"] == "completed"
    reloaded = ProjectState.load(str(run_root / "project_state.json"))
    assert reloaded.project_name == "SentinelResumeProject"
    assert reloaded.phase == "completed"


def test_run_scenario_provider_forwards_ollama_timeout_override(tmp_path, monkeypatch):
    module = _load_script_module(
        "real_world_complex_matrix_ollama_timeout_forwarding_test",
        "scripts/run_real_world_complex_matrix.py",
    )

    monkeypatch.setattr(
        module,
        "get_provider_availability",
        lambda provider, **kwargs: {"provider": provider, "available": True, "reason": None},
    )
    monkeypatch.setattr(
        module,
        "resolve_model",
        lambda provider, model=None, **kwargs: "qwen2.5-coder:7b",
    )

    captured: dict[str, object] = {}

    class FakeConfig:
        workflow_acceptance_policy = "all_tasks"

    def fake_build_full_workflow_config(provider, model, output_dir, **kwargs):
        captured["provider"] = provider
        captured["model"] = model
        captured["output_dir"] = output_dir
        captured.update(kwargs)
        return FakeConfig()

    def fake_execute(config, project):
        project.mark_workflow_running(acceptance_policy="all_tasks", repair_max_cycles=1)
        project.mark_workflow_finished(
            "completed",
            acceptance_policy="all_tasks",
            terminal_outcome=WorkflowOutcome.COMPLETED.value,
            acceptance_criteria_met=True,
            acceptance_evaluation={
                "policy": "all_tasks",
                "accepted": True,
                "reason": "all_evaluated_tasks_done",
                "evaluated_task_ids": [task.id for task in project.tasks],
                "required_task_ids": [],
                "completed_task_ids": [task.id for task in project.tasks],
                "failed_task_ids": [],
                "skipped_task_ids": [],
                "pending_task_ids": [],
            },
        )
        project.save()

    monkeypatch.setattr(module, "build_full_workflow_config", fake_build_full_workflow_config)
    monkeypatch.setattr(module, "execute_empirical_validation_workflow", fake_execute)
    monkeypatch.setattr(
        module,
        "_validate_generated_scenario",
        lambda spec, task, output_dir: {
            "validated": True,
            "artifact_path": None,
            "checks": {
                "syntax_valid": True,
                "stdlib_only": True,
                "service_constructor_supported": True,
                "request_signature_supported": True,
                "validation_surface_supported": True,
                "valid_request_accepted": True,
                "invalid_request_rejected": True,
                "generated_tests_assert_invalid_request_value_error": True,
                "risk_signal_observable": True,
                "audit_signal_present": True,
                "batch_processing_supported": True,
            },
            "error": None,
            "observations": {},
        },
    )

    result = module.run_scenario_provider(
        next(spec for spec in module.SCENARIOS if spec.slug == "returns_abuse_screening"),
        "ollama",
        output_root=tmp_path,
        failure_policy="continue",
        resume_policy="resume_failed",
        max_repair_cycles=1,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_num_ctx=16384,
        ollama_timeout_seconds=420.0,
        max_tokens=3200,
        run_index=1,
        total_runs=1,
    )

    assert result["status"] == "completed"
    assert captured["provider"] == "ollama"
    assert captured["ollama_base_url"] == "http://127.0.0.1:11434"
    assert captured["ollama_num_ctx"] == 16384


# ---------------------------------------------------------------------------
# _coerce_validation_bool  — tuple-return tolerance
# ---------------------------------------------------------------------------

def test_coerce_validation_bool_plain_true():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    assert module._coerce_validation_bool(True) is True


def test_coerce_validation_bool_plain_false():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    assert module._coerce_validation_bool(False) is False


def test_coerce_validation_bool_tuple_true():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    assert module._coerce_validation_bool((True, [])) is True


def test_coerce_validation_bool_tuple_false():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    assert module._coerce_validation_bool((False, ["bad details"])) is False


def test_coerce_validation_bool_tuple_false_empty_errors():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    assert module._coerce_validation_bool((False, [])) is False


def test_coerce_validation_bool_none_is_falsy():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    assert module._coerce_validation_bool(None) is False


def test_coerce_validation_bool_dict_valid_true():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    assert module._coerce_validation_bool({"valid": True, "errors": []}) is True


def test_coerce_validation_bool_dict_valid_false():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    assert module._coerce_validation_bool({"valid": False, "errors": ["bad"]}) is False


# ---------------------------------------------------------------------------
# _invalid_request_is_rejected  — tuple-return from validate_request
# ---------------------------------------------------------------------------

def test_invalid_request_is_rejected_tuple_false_counts_as_rejection():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    # validate_request returns (False, errors) — should be treated as rejection.
    assert module._invalid_request_is_rejected(
        lambda _req: (False, ["details must be a dict"]),
        lambda _req: None,
        object(),
    ) is True


def test_invalid_request_is_rejected_tuple_true_not_rejected():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    # validate_request returns (True, []) and handle_request does not raise.
    assert module._invalid_request_is_rejected(
        lambda _req: (True, []),
        lambda _req: None,
        object(),
    ) is False


def test_invalid_request_is_rejected_plain_false():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    assert module._invalid_request_is_rejected(
        lambda _req: False,
        lambda _req: None,
        object(),
    ) is True


def test_invalid_request_is_rejected_exception_is_rejection():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    def raise_value_error(_req):
        raise ValueError("invalid details")
    assert module._invalid_request_is_rejected(
        raise_value_error,
        lambda _req: None,
        object(),
    ) is True


# ---------------------------------------------------------------------------
# Contract anchor  — validate_request return-type and details-dict guidance
# ---------------------------------------------------------------------------

def test_contract_anchor_includes_validate_request_return_type_guidance():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    spec = module.SCENARIOS[0]  # kyc_compliance_intake
    anchor = module._contract_anchor(spec)
    assert "return a plain bool" in anchor
    assert "True for valid, False for invalid" in anchor


def test_contract_anchor_includes_details_dict_guidance():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    spec = module.SCENARIOS[0]  # kyc_compliance_intake
    anchor = module._contract_anchor(spec)
    assert "details.get" in anchor or "details['key']" in anchor
    assert "attribute access" in anchor


def test_contract_anchor_includes_timestamp_datetime_guidance():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    spec = module.SCENARIOS[0]
    anchor = module._contract_anchor(spec)
    assert "datetime object" in anchor
    assert "not a float, int, or string" in anchor


def test_contract_anchor_includes_request_type_freeform_guidance():
    module = _load_script_module("run_real_world_complex_matrix", "scripts/run_real_world_complex_matrix.py")
    spec = module.SCENARIOS[0]
    anchor = module._contract_anchor(spec)
    assert "free-form string label" in anchor
    assert "invented whitelist" in anchor


def test_insurance_detail_contract_includes_request_type_and_claim_category_guidance(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_insurance_rt_guidance_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    insurance_spec = next(spec for spec in module.SCENARIOS if spec.slug == "insurance_claim_triage")
    project = module.build_project(insurance_spec, str(tmp_path / "campaign" / "openai"))
    code_task = next(task for task in project.tasks if task.id == "code")

    assert 'request_type value in test payloads is "claim"' in code_task.description
    assert "claim_category field accepts free-form string labels" in code_task.description


def test_vendor_detail_contract_includes_request_type_guidance(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_vendor_rt_guidance_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    vendor_spec = next(spec for spec in module.SCENARIOS if spec.slug == "vendor_onboarding_risk")
    project = module.build_project(vendor_spec, str(tmp_path / "campaign" / "ollama"))
    code_task = next(task for task in project.tasks if task.id == "code")

    assert 'request_type value in test payloads is "vendor_submission"' in code_task.description


def test_vendor_detail_contract_discourages_happy_path_outcome_guessing(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_vendor_outcome_guidance_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    vendor_spec = next(spec for spec in module.SCENARIOS if spec.slug == "vendor_onboarding_risk")
    project = module.build_project(vendor_spec, str(tmp_path / "campaign" / "ollama"))
    code_task = next(task for task in project.tasks if task.id == "code")
    tests_task = next(task for task in project.tasks if task.id == "tests")

    guidance = (
        'The listed review outcomes are a possible label set, not proof that a chosen happy-path payload must resolve to "approved".'
    )

    assert guidance in code_task.description
    assert guidance in tests_task.description


def test_returns_detail_contract_includes_item_subfield_guidance(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_returns_item_guidance_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    returns_spec = next(spec for spec in module.SCENARIOS if spec.slug == "returns_abuse_screening")
    project = module.build_project(returns_spec, str(tmp_path / "campaign" / "ollama"))
    code_task = next(task for task in project.tasks if task.id == "code")

    assert "sku (str), category (str), and value (numeric)" in code_task.description
    assert "Do not rename value to price" in code_task.description


def test_access_review_detail_contract_includes_approval_metadata_subfield_guidance(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_access_approval_guidance_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    access_spec = next(spec for spec in module.SCENARIOS if spec.slug == "access_review_audit")
    project = module.build_project(access_spec, str(tmp_path / "campaign" / "openai"))
    code_task = next(task for task in project.tasks if task.id == "code")

    assert "approved_by (str) and age_days (int)" in code_task.description


def test_contract_anchor_rejects_nondict_details(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_nondict_reject_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    spec = next(spec for spec in module.SCENARIOS if spec.slug == "kyc_compliance_intake")
    anchor = module._contract_anchor(spec)
    assert "validate_request must return False immediately when details is not a dict" in anchor


def test_kyc_detail_contract_rejects_nondict_details(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_kyc_nondict_detail_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    kyc_spec = next(spec for spec in module.SCENARIOS if spec.slug == "kyc_compliance_intake")
    project = module.build_project(kyc_spec, str(tmp_path / "campaign" / "openai"))
    code_task = next(task for task in project.tasks if task.id == "code")
    assert "non-dict details" in code_task.description.lower()
    assert "raise ValueError" in code_task.description


def test_vendor_tests_prompt_requires_explicit_malformed_request_value_error(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_vendor_invalid_request_tests_prompt",
        "scripts/run_real_world_complex_matrix.py",
    )
    vendor_spec = next(spec for spec in module.SCENARIOS if spec.slug == "vendor_onboarding_risk")
    project = module.build_project(vendor_spec, str(tmp_path / "campaign" / "ollama"))
    tests_task = next(task for task in project.tasks if task.id == "tests")

    assert "details is not a dict" in tests_task.description
    assert "assert handle_request(...) raises ValueError" in tests_task.description


def test_access_detail_contract_rejects_nondict_details(tmp_path):
    module = _load_script_module(
        "real_world_complex_matrix_access_nondict_detail_test",
        "scripts/run_real_world_complex_matrix.py",
    )
    access_spec = next(spec for spec in module.SCENARIOS if spec.slug == "access_review_audit")
    project = module.build_project(access_spec, str(tmp_path / "campaign" / "anthropic"))
    code_task = next(task for task in project.tasks if task.id == "code")
    assert "non-dict details" in code_task.description.lower()
    assert "raise ValueError" in code_task.description
    assert "Do not invent additional required sub-keys" in code_task.description