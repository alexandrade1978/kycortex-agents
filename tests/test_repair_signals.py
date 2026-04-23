from kycortex_agents.orchestration.repair_signals import (
	content_has_bare_datetime_reference,
	content_has_incomplete_required_evidence_payload,
	content_has_matching_datetime_import,
	implementation_prefers_direct_datetime_import,
	implementation_required_evidence_items,
	validation_summary_has_missing_datetime_import_issue,
	validation_summary_has_required_evidence_runtime_issue,
)


def test_datetime_signal_helpers_cover_import_and_reference_edges():
	assert validation_summary_has_missing_datetime_import_issue(None) is False
	assert content_has_matching_datetime_import(None) is False
	assert content_has_matching_datetime_import("from datetime import datetime\n") is True
	assert content_has_matching_datetime_import("import datetime\n") is True
	assert content_has_matching_datetime_import("from helpers import datetime\n") is False

	assert content_has_bare_datetime_reference("") is False
	assert content_has_bare_datetime_reference("value = datetime.now()\n") is True
	assert content_has_bare_datetime_reference("value = helper.datetime.now()\n") is False

	missing_import_tests = "request = build_request(timestamp=datetime.now())\n"
	assert validation_summary_has_missing_datetime_import_issue(
		"Generated test validation:\n- Undefined local names: datetime\n- Verdict: FAIL",
		missing_import_tests,
	) is True
	assert validation_summary_has_missing_datetime_import_issue(
		"Generated test validation:\n- Name 'datetime' is not defined\n- Verdict: FAIL",
		"from datetime import datetime\n" + missing_import_tests,
	) is False
	assert validation_summary_has_missing_datetime_import_issue(
		"Generated test validation:\n- Undefined local names: datetime\n- Verdict: FAIL",
		"",
	) is True

	assert implementation_prefers_direct_datetime_import(None) is False
	assert implementation_prefers_direct_datetime_import("import datetime\n") is False
	assert implementation_prefers_direct_datetime_import(
		"from datetime import datetime\n\ndef build_timestamp():\n    return datetime.now()\n"
	) is True


def test_required_evidence_item_extraction_supports_annotated_and_invalid_inputs():
	assert implementation_required_evidence_items(None) == []
	assert implementation_required_evidence_items("def broken(:\n    pass") == []
	assert implementation_required_evidence_items("required_evidence = docs\n") == []
	assert implementation_required_evidence_items("required_evidence = ['ID', 1]\n") == []
	assert implementation_required_evidence_items(
		"required_documents: tuple[str, ...] = ('ID', 'ID', 'Address')\n"
	) == ["ID", "Address"]
	assert implementation_required_evidence_items(
		"required_evidence = ['Passport', 'Proof of Address']\n"
	) == ["Passport", "Proof of Address"]


def test_required_evidence_payload_detection_handles_skip_and_runtime_gates():
	implementation_code = (
		"def validate_request(request):\n"
		"    required_evidence = ['ID', 'Address', 'Proof of Income']\n"
		"    return all(item in request.details.get('documents', []) for item in required_evidence)\n"
	)

	assert content_has_incomplete_required_evidence_payload("", implementation_code) is False
	assert content_has_incomplete_required_evidence_payload(
		"def broken(:\n    pass",
		implementation_code,
	) is False
	assert content_has_incomplete_required_evidence_payload(
		"def test_validation_failure():\n"
		"    request = {'documents': ['ID']}\n"
		"    assert len(service.risk_scores) == 1\n",
		implementation_code,
	) is False
	assert content_has_incomplete_required_evidence_payload(
		"def test_happy_path():\n"
		"    request = {'documents': ['ID']}\n"
		"    assert len(service.risk_scores) == 1\n",
		implementation_code,
	) is True
	assert content_has_incomplete_required_evidence_payload(
		"def test_neutral_path():\n"
		"    request = {'documents': ['ID']}\n"
		"    assert service.validate_request(request) is True\n",
		implementation_code,
	) is False
	assert content_has_incomplete_required_evidence_payload(
		"def test_batch_path():\n"
		"    request = {'files': ['ID']}\n"
		"    assert process_batch(request)\n",
		implementation_code,
	) is False
	assert content_has_incomplete_required_evidence_payload(
		"def test_batch_path():\n"
		"    request = {'documents': ['ID', 1]}\n"
		"    assert process_batch(request)\n",
		implementation_code,
	) is True
	assert content_has_incomplete_required_evidence_payload(
		"def test_happy_path():\n"
		"    request = {'documents': ['ID', 'Address']}\n"
		"    assert len(service.risk_scores) == 1\n",
		"required_evidence = ['ID']\n",
	) is False


def test_required_evidence_runtime_issue_requires_all_runtime_signals():
	implementation_code = (
		"def validate_request(request):\n"
		"    required_evidence = ['ID', 'Address']\n"
		"    return all(item in request.details.get('documents', []) for item in required_evidence)\n"
	)
	failed_tests = (
		"def test_happy_path():\n"
		"    request = {'documents': ['ID']}\n"
		"    assert len(service.risk_scores) == 1\n"
	)
	failed_tests_without_runtime_signal = (
		"def test_happy_path():\n"
		"    request = {'documents': ['ID']}\n"
		"    assert service.validate_request(request) is True\n"
	)

	assert validation_summary_has_required_evidence_runtime_issue(None, failed_tests, implementation_code) is False
	assert validation_summary_has_required_evidence_runtime_issue(
		"Generated test validation:\n- Pytest execution: FAIL\n- Pytest failure details: FAILED tests.py::test_happy_path - AssertionError: assert 1 == 1\n- Verdict: FAIL",
		"risk_scores = []\n" + failed_tests,
		implementation_code,
	) is False
	assert validation_summary_has_required_evidence_runtime_issue(
		"Generated test validation:\n- Verdict: FAIL",
		"risk_scores = []\n" + failed_tests,
		implementation_code,
	) is False
	assert validation_summary_has_required_evidence_runtime_issue(
		"Generated test validation:\n- Pytest execution: FAIL\n- Pytest failure details: FAILED tests.py::test_happy_path - AssertionError: assert 0 == 1\n- Verdict: FAIL",
		failed_tests_without_runtime_signal,
		implementation_code,
	) is False
	assert validation_summary_has_required_evidence_runtime_issue(
		"Generated test validation:\n- Pytest execution: FAIL\n- Pytest failure details: FAILED tests.py::test_happy_path - AssertionError: assert 0 == 1\n- Verdict: FAIL",
		"risk_scores = []\n" + failed_tests,
		implementation_code,
	) is True