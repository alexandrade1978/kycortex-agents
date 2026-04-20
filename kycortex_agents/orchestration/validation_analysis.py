"""Test-validation and pytest-failure analysis helpers used by the Orchestrator facade."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional


BLOCKING_TEST_ISSUE_KEYS: frozenset[str] = frozenset(
    {
        "missing_function_imports",
        "undefined_fixtures",
        "undefined_local_names",
        "imported_entrypoint_symbols",
        "unsafe_entrypoint_calls",
    }
)

WARNING_TEST_ISSUE_KEYS: frozenset[str] = frozenset(
    {
        "unknown_module_symbols",
        "invalid_member_references",
        "call_arity_mismatches",
        "constructor_arity_mismatches",
        "contract_overreach_signals",
        "payload_contract_violations",
        "non_batch_sequence_calls",
        "type_mismatches",
        "reserved_fixture_names",
        "unsupported_mock_assertions",
    }
)


def collect_code_validation_issues(
    code_analysis: dict[str, Any],
    line_budget: Optional[int],
    task_public_contract_preflight: Optional[dict[str, Any]],
    import_validation: Optional[dict[str, Any]],
    completion_diagnostics: dict[str, Any],
    completion_validation_issue: Callable[[dict[str, Any]], str],
) -> list[str]:
    validation_issues: list[str] = []
    if not code_analysis.get("syntax_ok", True):
        validation_issues.append(f"syntax error {code_analysis.get('syntax_error') or 'unknown syntax error'}")
    if isinstance(line_budget, int) and code_analysis.get("line_count", 0) > line_budget:
        validation_issues.append(f"line count {code_analysis['line_count']} exceeds maximum {line_budget}")
    if code_analysis.get("main_guard_required") and not code_analysis.get("has_main_guard"):
        validation_issues.append("missing required CLI entrypoint")
    if isinstance(import_validation, dict) and import_validation.get("ran") and import_validation.get("returncode") not in (None, 0):
        import_summary = import_validation.get("summary") or "generated module failed to import"
        validation_issues.append(f"module import failed: {import_summary}")
    if isinstance(task_public_contract_preflight, dict):
        contract_issues = task_public_contract_preflight.get("issues") or []
        if contract_issues:
            validation_issues.append(f"task public contract mismatch: {', '.join(contract_issues)}")
    invalid_dataclass_field_usages = code_analysis.get("invalid_dataclass_field_usages") or []
    if invalid_dataclass_field_usages:
        validation_issues.append(
            f"non-dataclass field(...) usage: {', '.join(invalid_dataclass_field_usages)}"
        )
    if completion_diagnostics.get("likely_truncated"):
        validation_issues.append(completion_validation_issue(completion_diagnostics))
    return validation_issues


def pytest_failure_details(test_execution: Optional[dict[str, Any]], limit: int = 3) -> list[str]:
    if not isinstance(test_execution, dict):
        return []
    output_lines: list[str] = []
    for field_name in ("stdout", "stderr"):
        value = test_execution.get(field_name)
        if isinstance(value, str) and value.strip():
            output_lines.extend(value.splitlines())

    failed_lines = [line.strip() for line in output_lines if line.strip().startswith("FAILED ")]
    section_error_lines: list[str] = []
    in_failure_section = False
    for line in output_lines:
        stripped = line.strip()
        if re.match(r"^_{5,}.*_{5,}$", stripped):
            in_failure_section = True
            continue
        if not in_failure_section:
            continue
        if stripped.startswith("E   "):
            detail = stripped[4:]
            if detail and not detail.startswith("+"):
                section_error_lines.append(detail)
                in_failure_section = False
            continue
        if stripped.startswith("FAILED "):
            in_failure_section = False

    if failed_lines:
        detailed_failures: list[str] = []
        for index, line in enumerate(failed_lines):
            detail = line
            if index < len(section_error_lines):
                detail = f"{line} | {section_error_lines[index]}"
            else:
                line_index = next(
                    (candidate_index for candidate_index, candidate_line in enumerate(output_lines) if candidate_line.strip() == line),
                    -1,
                )
                if line_index >= 0:
                    for follow_line in output_lines[line_index + 1:line_index + 6]:
                        follow_stripped = follow_line.strip()
                        if not follow_stripped.startswith("E   "):
                            continue
                        detail = f"{line} | {follow_stripped[4:]}"
                        break
            detailed_failures.append(detail)
        return detailed_failures[:limit]

    error_lines = [line.strip()[4:] for line in output_lines if line.strip().startswith("E   ")]
    return error_lines[:limit]


def pytest_failure_origin(
    test_execution: Optional[dict[str, Any]],
    module_filename: Optional[str],
    test_filename: Optional[str],
) -> str:
    if not isinstance(test_execution, dict):
        return "unknown"
    output_lines: list[str] = []
    for field_name in ("stdout", "stderr"):
        value = test_execution.get(field_name)
        if isinstance(value, str) and value.strip():
            output_lines.extend(value.splitlines())

    module_marker = f"{module_filename}:" if isinstance(module_filename, str) and module_filename else None
    if module_marker and any(module_marker in line for line in output_lines):
        return "code_under_test"

    test_marker = f"{test_filename}:" if isinstance(test_filename, str) and test_filename else None
    if test_marker and any(test_marker in line for line in output_lines):
        return "tests"

    return "unknown"


def pytest_failure_is_semantic_assertion_mismatch(test_execution: Optional[dict[str, Any]]) -> bool:
    failure_details = pytest_failure_details(test_execution, limit=10)
    if not failure_details:
        return False

    joined_details = "\n".join(failure_details)
    if any(
        marker in joined_details
        for marker in (
            "NameError",
            "ImportError",
            "ModuleNotFoundError",
            "SyntaxError",
            "fixture ",
            "fixture'",
            'fixture"',
        )
    ):
        return False

    return "AssertionError" in joined_details or " - assert " in joined_details


def pytest_contract_overreach_signals(test_execution: Optional[dict[str, Any]]) -> list[str]:
    failure_details = pytest_failure_details(test_execution, limit=10)
    if not failure_details:
        return []
    output_chunks: list[str] = []
    if isinstance(test_execution, dict):
        for field_name in ("stdout", "stderr"):
            value = test_execution.get(field_name)
            if isinstance(value, str) and value.strip():
                output_chunks.append(value)
    output_text = "\n".join(output_chunks)

    status_like_aliases = {
        "accepted": "accepted",
        "abuse escalation": "abuse_escalation",
        "abuse_escalation": "abuse_escalation",
        "approved": "approved",
        "auto approve": "auto_approve",
        "auto-approve": "auto_approve",
        "auto_approve": "auto_approve",
        "blocked": "blocked",
        "conditional approval": "conditional_approval",
        "conditional_approval": "conditional_approval",
        "enhanced due diligence": "enhanced_due_diligence",
        "enhanced_due_diligence": "enhanced_due_diligence",
        "escalated": "escalated",
        "flagged": "flagged",
        "fraud": "fraud",
        "fraud escalation": "fraud_escalation",
        "fraud_escalation": "fraud_escalation",
        "invalid": "invalid",
        "manual inspection": "manual_inspection",
        "manual_inspection": "manual_inspection",
        "manual review": "manual_review",
        "manual_review": "manual_review",
        "manual investigation": "manual_investigation",
        "manual_investigation": "manual_investigation",
        "pending": "pending",
        "pending review": "pending_review",
        "pending_review": "pending_review",
        "rejected": "rejected",
        "security escalation": "security_escalation",
        "security_escalation": "security_escalation",
        "straight through": "straight_through_review",
        "straight through review": "straight_through_review",
        "straight-through": "straight_through_review",
        "straight-through review": "straight_through_review",
        "straight_through_review": "straight_through_review",
        "time boxed approval": "time_boxed_approval",
        "time-boxed approval": "time_boxed_approval",
        "time_boxed_approval": "time_boxed_approval",
    }
    status_like_pattern = re.compile(
        r"(?<![A-Za-z0-9_])(" + "|".join(
            sorted((re.escape(label) for label in status_like_aliases), key=len, reverse=True)
        ) + r")(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )
    primitive_runtime_types = {"NoneType", "bool", "dict", "float", "int", "list", "str", "tuple"}

    def extract_status_like_label(assertion_text: str) -> Optional[str]:
        matches = [status_like_aliases[match.lower()] for match in status_like_pattern.findall(assertion_text)]
        unique_matches = list(dict.fromkeys(matches))
        if len(unique_matches) != 1:
            return None
        return unique_matches[0]

    signals: list[str] = []
    seen: set[str] = set()
    for detail in failure_details:
        for pattern in (
            r"AssertionError: assert ['\"]([^'\"]+)['\"] == ['\"]([^'\"]+)['\"]",
            r"AssertionError: assert ['\"]([^'\"]+)['\"] in ['\"]([^'\"]+)['\"]",
        ):
            for match in re.finditer(pattern, detail):
                left = extract_status_like_label(match.group(1).strip())
                right = extract_status_like_label(match.group(2).strip())
                if left is None or right is None or left == right:
                    continue
                signal = (
                    f"exact status/action label mismatch ('{left}' vs '{right}') suggests an unsupported threshold assumption"
                )
                if signal in seen:
                    continue
                seen.add(signal)
                signals.append(signal)
        for match in re.finditer(
            r"AttributeError: ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] object has no attribute ['\"]([^'\"]+)['\"]",
            detail,
        ):
            runtime_type = match.group(1)
            attribute = match.group(2).strip()
            if runtime_type not in primitive_runtime_types or not attribute:
                continue
            signal = (
                f"exact return-shape attribute assumption ('.{attribute}' on '{runtime_type}') suggests an unsupported wrapper expectation"
            )
            if signal in seen:
                continue
            seen.add(signal)
            signals.append(signal)
    if output_text:
        for match in re.finditer(
            r"AssertionError:\s+assert ['\"](?P<asserted_key>[^'\"]+)['\"] in \{.*?\baction_id=['\"](?P<action_id>[^'\"]+)['\"].*?=\s*<[^>]+>\.(?P<collection>[A-Za-z_][A-Za-z0-9_]*)",
            output_text,
            re.IGNORECASE | re.DOTALL,
        ):
            collection_name = match.group("collection").strip()
            asserted_key = match.group("asserted_key").strip()
            action_id = match.group("action_id").strip()
            if "action" not in collection_name.lower() or not asserted_key or not action_id:
                continue
            if asserted_key == action_id:
                continue
            signal = (
                f"exact internal action-map key assumption for '{collection_name}' suggests an unsupported storage-key contract"
            )
            if signal in seen:
                continue
            seen.add(signal)
            signals.append(signal)
    return signals


def validation_has_static_issues(validation: dict[str, Any]) -> bool:
    test_analysis = validation.get("test_analysis")
    if not isinstance(test_analysis, dict):
        return True

    if not test_analysis.get("syntax_ok", True):
        return True

    line_count = test_analysis.get("line_count")
    line_budget = test_analysis.get("line_budget")
    if isinstance(line_count, int) and isinstance(line_budget, int) and line_count > line_budget:
        return True

    top_level_test_count = test_analysis.get("top_level_test_count")
    expected_top_level_test_count = test_analysis.get("expected_top_level_test_count")
    max_top_level_test_count = test_analysis.get("max_top_level_test_count")
    if (
        isinstance(top_level_test_count, int)
        and isinstance(expected_top_level_test_count, int)
        and top_level_test_count != expected_top_level_test_count
    ):
        return True
    if (
        isinstance(top_level_test_count, int)
        and isinstance(max_top_level_test_count, int)
        and top_level_test_count > max_top_level_test_count
    ):
        return True

    fixture_count = test_analysis.get("fixture_count")
    fixture_budget = test_analysis.get("fixture_budget")
    if isinstance(fixture_count, int) and isinstance(fixture_budget, int) and fixture_count > fixture_budget:
        return True

    for issue_key in (
        "missing_function_imports",
        "unknown_module_symbols",
        "invalid_member_references",
        "call_arity_mismatches",
        "constructor_arity_mismatches",
        "contract_overreach_signals",
        "payload_contract_violations",
        "non_batch_sequence_calls",
        "undefined_fixtures",
        "undefined_local_names",
        "imported_entrypoint_symbols",
        "unsafe_entrypoint_calls",
        "type_mismatches",
    ):
        if test_analysis.get(issue_key):
            return True

    return False


def validation_has_blocking_issues(validation: dict[str, Any]) -> bool:
    test_analysis = validation.get("test_analysis")
    if not isinstance(test_analysis, dict):
        return True

    if not test_analysis.get("syntax_ok", True):
        return True

    line_count = test_analysis.get("line_count")
    line_budget = test_analysis.get("line_budget")
    if isinstance(line_count, int) and isinstance(line_budget, int) and line_count > line_budget:
        return True

    top_level_test_count = test_analysis.get("top_level_test_count")
    expected_top_level_test_count = test_analysis.get("expected_top_level_test_count")
    max_top_level_test_count = test_analysis.get("max_top_level_test_count")
    if (
        isinstance(top_level_test_count, int)
        and isinstance(expected_top_level_test_count, int)
        and top_level_test_count != expected_top_level_test_count
    ):
        return True
    if (
        isinstance(top_level_test_count, int)
        and isinstance(max_top_level_test_count, int)
        and top_level_test_count > max_top_level_test_count
    ):
        return True

    fixture_count = test_analysis.get("fixture_count")
    fixture_budget = test_analysis.get("fixture_budget")
    if isinstance(fixture_count, int) and isinstance(fixture_budget, int) and fixture_count > fixture_budget:
        return True

    for issue_key in BLOCKING_TEST_ISSUE_KEYS:
        if test_analysis.get(issue_key):
            return True

    return False


def validation_has_only_warnings(validation: dict[str, Any]) -> bool:
    if validation_has_blocking_issues(validation):
        return False
    test_analysis = validation.get("test_analysis")
    if not isinstance(test_analysis, dict):
        return False
    return any(test_analysis.get(key) for key in WARNING_TEST_ISSUE_KEYS)


def collect_test_validation_issues(
    test_analysis: dict[str, Any],
    test_execution: dict[str, Any],
    completion_diagnostics: dict[str, Any],
    completion_validation_issue: Callable[[dict[str, Any]], str],
) -> tuple[list[str], list[str], bool]:
    validation_issues: list[str] = []
    warning_issues: list[str] = []

    if not test_analysis.get("syntax_ok", True):
        validation_issues.append(f"test syntax error {test_analysis.get('syntax_error') or 'unknown syntax error'}")

    line_count = test_analysis.get("line_count")
    line_budget = test_analysis.get("line_budget")
    if isinstance(line_count, int) and isinstance(line_budget, int) and line_count > line_budget:
        validation_issues.append(f"line count {line_count} exceeds maximum {line_budget}")

    top_level_test_count = test_analysis.get("top_level_test_count")
    expected_top_level_test_count = test_analysis.get("expected_top_level_test_count")
    if (
        isinstance(top_level_test_count, int)
        and isinstance(expected_top_level_test_count, int)
        and top_level_test_count != expected_top_level_test_count
    ):
        validation_issues.append(
            f"top-level test count {top_level_test_count} does not match required {expected_top_level_test_count}"
        )

    max_top_level_test_count = test_analysis.get("max_top_level_test_count")
    if (
        isinstance(top_level_test_count, int)
        and isinstance(max_top_level_test_count, int)
        and top_level_test_count > max_top_level_test_count
    ):
        validation_issues.append(
            f"top-level test count {top_level_test_count} exceeds maximum {max_top_level_test_count}"
        )

    fixture_count = test_analysis.get("fixture_count")
    fixture_budget = test_analysis.get("fixture_budget")
    if isinstance(fixture_count, int) and isinstance(fixture_budget, int) and fixture_count > fixture_budget:
        validation_issues.append(f"fixture count {fixture_count} exceeds maximum {fixture_budget}")

    tests_without_assertions = test_analysis.get("tests_without_assertions") or []
    if tests_without_assertions:
        warning_issues.append(
            f"tests without assertion-like checks: {', '.join(tests_without_assertions)}"
        )

    contract_overreach_signals = test_analysis.get("contract_overreach_signals") or []
    if contract_overreach_signals:
        warning_issues.append(
            f"contract overreach signals: {', '.join(contract_overreach_signals)}"
        )

    helper_surface_usages = test_analysis.get("helper_surface_usages") or []
    if helper_surface_usages and (
        isinstance(line_budget, int)
        or isinstance(max_top_level_test_count, int)
        or isinstance(fixture_budget, int)
    ):
        validation_issues.append(
            f"helper surface usages: {', '.join(helper_surface_usages)}"
        )

    for issue_key, label in (
        ("missing_function_imports", "missing function imports"),
        ("unknown_module_symbols", "unknown module symbols"),
        ("invalid_member_references", "invalid member references"),
        ("call_arity_mismatches", "call arity mismatches"),
        ("constructor_arity_mismatches", "constructor arity mismatches"),
        ("payload_contract_violations", "payload contract violations"),
        ("non_batch_sequence_calls", "non-batch sequence calls"),
        ("reserved_fixture_names", "reserved fixture names"),
        ("undefined_fixtures", "undefined test fixtures"),
        ("undefined_local_names", "undefined local names"),
        ("imported_entrypoint_symbols", "imported entrypoint symbols"),
        ("unsafe_entrypoint_calls", "unsafe entrypoint calls"),
        ("unsupported_mock_assertions", "unsupported mock assertions"),
    ):
        issues = test_analysis.get(issue_key) or []
        if issues:
            target = validation_issues if issue_key in BLOCKING_TEST_ISSUE_KEYS else warning_issues
            target.append(f"{label}: {', '.join(issues)}")

    if completion_diagnostics.get("likely_truncated"):
        validation_issues.append(completion_validation_issue(completion_diagnostics))

    pytest_ran = test_execution.get("ran")
    pytest_passed = bool(pytest_ran and test_execution.get("returncode") in (None, 0))

    if pytest_ran and test_execution.get("returncode") not in (None, 0):
        validation_issues.append(f"pytest failed: {test_execution.get('summary') or 'generated tests failed'}")

    return validation_issues, warning_issues, pytest_passed


def validation_error_message_for_test_result(
    validation_issues: list[str],
    warning_issues: list[str],
    pytest_passed: bool,
) -> Optional[str]:
    if validation_issues:
        all_issues = validation_issues + [f"(warning) {warning}" for warning in warning_issues]
        return f"Generated test validation failed: {'; '.join(all_issues)}"

    if warning_issues and not pytest_passed:
        return (
            f"Generated test validation failed: {'; '.join(warning_issues)} "
            "(pytest did not confirm correctness)"
        )

    return None