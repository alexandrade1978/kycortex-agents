"""Validation reporting helpers used by the Orchestrator facade."""

from __future__ import annotations

import io
import tokenize
from typing import Any, Dict, Optional

from kycortex_agents.types import FailureCategory

from kycortex_agents.orchestration.validation_analysis import (
	BLOCKING_TEST_ISSUE_KEYS,
	WARNING_TEST_ISSUE_KEYS,
	pytest_contract_overreach_signals,
	pytest_failure_details,
)


LIKELY_TRUNCATED_SYNTAX_MARKERS = (
	"was never closed",
	"unexpected eof while parsing",
	"unterminated string literal",
	"unterminated triple-quoted string literal",
	"eof while scanning triple-quoted string literal",
	"eol while scanning string literal",
	"expected an indented block",
)

LIKELY_TRUNCATED_TAIL_SUFFIXES = (
	"(",
	"[",
	"{",
	",",
	".",
	"=",
	"+",
	"-",
	"*",
	"/",
	"%",
	"\\",
	":",
)


def completion_diagnostics_from_provider_call(
	provider_call: Any,
	*,
	raw_content: str = "",
	syntax_ok: bool,
	syntax_error: Optional[str] = None,
) -> Dict[str, Any]:
	diagnostics: Dict[str, Any] = {
		"requested_max_tokens": None,
		"output_tokens": None,
		"finish_reason": None,
		"stop_reason": None,
		"done_reason": None,
		"hit_token_limit": False,
		"likely_truncated": False,
	}
	if not isinstance(provider_call, dict):
		return diagnostics

	usage = provider_call.get("usage")
	output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
	requested_max_tokens = provider_call.get("requested_max_tokens")
	finish_reason = provider_call.get("finish_reason")
	stop_reason = provider_call.get("stop_reason")
	done_reason = provider_call.get("done_reason")

	hit_token_limit = (
		isinstance(output_tokens, int)
		and isinstance(requested_max_tokens, int)
		and requested_max_tokens > 0
		and output_tokens >= requested_max_tokens
	)
	likely_truncated = bool(
		(not syntax_ok)
		and (
			hit_token_limit
			or finish_reason == "length"
			or stop_reason == "max_tokens"
			or done_reason == "length"
			or looks_structurally_truncated(raw_content, syntax_error)
		)
	)
	diagnostics.update(
		{
			"requested_max_tokens": requested_max_tokens,
			"output_tokens": output_tokens,
			"finish_reason": finish_reason,
			"stop_reason": stop_reason,
			"done_reason": done_reason,
			"hit_token_limit": hit_token_limit,
			"likely_truncated": likely_truncated,
		}
	)
	return diagnostics


def looks_structurally_truncated(raw_content: str, syntax_error: Optional[str]) -> bool:
	if not isinstance(raw_content, str) or not raw_content.strip():
		return False

	try:
		list(tokenize.generate_tokens(io.StringIO(raw_content).readline))
	except tokenize.TokenError as exc:
		message = str(exc).lower()
		if "eof in multi-line statement" in message or "eof in multi-line string" in message:
			return True

	normalized_error = syntax_error.lower() if isinstance(syntax_error, str) else ""
	if not normalized_error or not any(marker in normalized_error for marker in LIKELY_TRUNCATED_SYNTAX_MARKERS):
		return False

	last_non_empty_line = next(
		(line.strip() for line in reversed(raw_content.splitlines()) if line.strip()),
		"",
	)
	if not last_non_empty_line:
		return False
	if last_non_empty_line.endswith(LIKELY_TRUNCATED_TAIL_SUFFIXES):
		return True
	if last_non_empty_line.count('"') % 2 == 1 or last_non_empty_line.count("'") % 2 == 1:
		return True
	return False


def completion_hit_limit(completion_diagnostics: Dict[str, Any]) -> bool:
	return bool(
		completion_diagnostics.get("hit_token_limit")
		or completion_diagnostics.get("finish_reason") == "length"
		or completion_diagnostics.get("stop_reason") == "max_tokens"
		or completion_diagnostics.get("done_reason") == "length"
	)


def completion_validation_issue(completion_diagnostics: Dict[str, Any]) -> str:
	if completion_hit_limit(completion_diagnostics):
		return "output likely truncated at the completion token limit"
	return "output likely truncated before the file ended cleanly"


def completion_diagnostics_summary(completion_diagnostics: Dict[str, Any]) -> str:
	if not completion_diagnostics:
		return "none"
	details: list[str] = []
	hit_limit = completion_hit_limit(completion_diagnostics)
	if completion_diagnostics.get("likely_truncated"):
		if hit_limit:
			details.append("likely truncated at completion limit")
		else:
			details.append("likely truncated before the file ended cleanly")
	elif hit_limit:
		details.append("completion limit reached")

	if any(completion_diagnostics.get(field_name) for field_name in ("finish_reason", "stop_reason", "done_reason")):
		if not hit_limit:
			details.append("provider termination reason recorded")

	requested_max_tokens = completion_diagnostics.get("requested_max_tokens")
	output_tokens = completion_diagnostics.get("output_tokens")
	if requested_max_tokens is not None or output_tokens is not None:
		details.append("token usage recorded")
	return ", ".join(details) if details else "none"


def build_code_validation_summary(
	code_analysis: Dict[str, Any],
	fallback_message: str,
	completion_diagnostics: Optional[Dict[str, Any]] = None,
	import_validation: Optional[Dict[str, Any]] = None,
	task_public_contract_preflight: Optional[Dict[str, Any]] = None,
) -> str:
	lines = ["Generated code validation:"]
	lines.append(f"- Syntax OK: {'yes' if code_analysis.get('syntax_ok', True) else 'no'}")
	syntax_error = code_analysis.get("syntax_error")
	if syntax_error:
		lines.append(f"- Syntax error: {syntax_error}")
	line_count = code_analysis.get("line_count")
	line_budget = code_analysis.get("line_budget")
	if isinstance(line_count, int):
		if isinstance(line_budget, int):
			lines.append(f"- Line count: {line_count}/{line_budget}")
		else:
			lines.append(f"- Line count: {line_count}")
	if code_analysis.get("main_guard_required"):
		lines.append(
			f"- CLI entrypoint present: {'yes' if code_analysis.get('has_main_guard') else 'no'} (required by task)"
		)
	if isinstance(completion_diagnostics, dict):
		lines.append(f"- Completion diagnostics: {completion_diagnostics_summary(completion_diagnostics)}")
	if isinstance(import_validation, dict) and import_validation.get("ran"):
		lines.append(f"- Module import: {'PASS' if import_validation.get('returncode') == 0 else 'FAIL'}")
		import_summary = import_validation.get("summary")
		if isinstance(import_summary, str) and import_summary:
			lines.append(f"- Import summary: {import_summary}")
	if isinstance(task_public_contract_preflight, dict) and task_public_contract_preflight.get("anchor_present"):
		lines.append("- Task public contract anchor: present")
		lines.append(
			f"- Task public contract: {'PASS' if task_public_contract_preflight.get('passed', True) else 'FAIL'}"
		)
		public_facade = task_public_contract_preflight.get("public_facade")
		if isinstance(public_facade, str) and public_facade:
			lines.append(f"- Public facade anchor: {public_facade}")
		primary_request_model = task_public_contract_preflight.get("primary_request_model")
		if isinstance(primary_request_model, str) and primary_request_model:
			lines.append(f"- Primary request model anchor: {primary_request_model}")
		required_surfaces = task_public_contract_preflight.get("required_surfaces") or []
		if required_surfaces:
			lines.append(f"- Required public surfaces: {', '.join(required_surfaces)}")
		contract_issues = task_public_contract_preflight.get("issues") or []
		if contract_issues:
			lines.append(f"- Task public contract mismatches: {', '.join(contract_issues)}")
	if "invalid_dataclass_field_usages" in code_analysis:
		invalid_field_usages = code_analysis.get("invalid_dataclass_field_usages") or []
		lines.append(f"- Non-dataclass field(...) usages: {', '.join(invalid_field_usages or ['none'])}")
	third_party_imports = code_analysis.get("third_party_imports") or []
	lines.append(f"- Third-party imports: {', '.join(third_party_imports or ['none'])}")
	if fallback_message:
		lines.append(f"- Failure message: {fallback_message}")
	return "\n".join(lines)


def build_dependency_validation_summary(dependency_analysis: Dict[str, Any]) -> str:
	lines = ["Dependency manifest validation:"]
	lines.append(
		f"- Required third-party imports: {', '.join(dependency_analysis.get('required_imports') or ['none'])}"
	)
	lines.append(
		f"- Declared packages: {', '.join(dependency_analysis.get('declared_packages') or ['none'])}"
	)
	lines.append(
		f"- Missing manifest entries: {', '.join(dependency_analysis.get('missing_manifest_entries') or ['none'])}"
	)
	lines.append(
		f"- Unused manifest entries: {', '.join(dependency_analysis.get('unused_manifest_entries') or ['none'])}"
	)
	lines.append(
		f"- Provenance violations: {', '.join(dependency_analysis.get('provenance_violations') or ['none'])}"
	)
	lines.append(f"- Verdict: {'PASS' if dependency_analysis.get('is_valid') else 'FAIL'}")
	return "\n".join(lines)


def build_repair_validation_summary(task: Any, failure_category: str, validation: object) -> str:
	fallback_message = task.last_error or task.output or ""
	if not isinstance(validation, dict):
		return fallback_message
	if failure_category == FailureCategory.CODE_VALIDATION.value:
		code_analysis = validation.get("code_analysis")
		if isinstance(code_analysis, dict):
			completion_diagnostics = validation.get("completion_diagnostics")
			import_validation = validation.get("import_validation")
			task_public_contract_preflight = validation.get("task_public_contract_preflight")
			return build_code_validation_summary(
				code_analysis,
				fallback_message,
				completion_diagnostics if isinstance(completion_diagnostics, dict) else None,
				import_validation if isinstance(import_validation, dict) else None,
				task_public_contract_preflight if isinstance(task_public_contract_preflight, dict) else None,
			)
	if failure_category == FailureCategory.TEST_VALIDATION.value:
		test_analysis = validation.get("test_analysis")
		test_execution = validation.get("test_execution")
		if isinstance(test_analysis, dict):
			completion_diagnostics = validation.get("completion_diagnostics")
			return build_test_validation_summary(
				test_analysis,
				test_execution if isinstance(test_execution, dict) else None,
				completion_diagnostics if isinstance(completion_diagnostics, dict) else None,
			)
	if failure_category == FailureCategory.DEPENDENCY_VALIDATION.value:
		dependency_analysis = validation.get("dependency_analysis")
		if isinstance(dependency_analysis, dict):
			return build_dependency_validation_summary(dependency_analysis)
	return fallback_message


def build_test_validation_summary(
	test_analysis: Dict[str, Any],
	test_execution: Optional[Dict[str, Any]] = None,
	completion_diagnostics: Optional[Dict[str, Any]] = None,
) -> str:
	lines = ["Generated test validation:"]
	syntax_ok = test_analysis.get("syntax_ok", True)
	static_contract_overreach_signals = test_analysis.get("contract_overreach_signals") or []
	runtime_contract_overreach_signals = pytest_contract_overreach_signals(test_execution)
	contract_overreach_signals = sorted(set(static_contract_overreach_signals) | set(runtime_contract_overreach_signals))
	lines.append(f"- Syntax OK: {'yes' if syntax_ok else 'no'}")
	syntax_error = test_analysis.get("syntax_error")
	if syntax_error:
		lines.append(f"- Syntax error: {syntax_error}")
	line_count = test_analysis.get("line_count")
	line_budget = test_analysis.get("line_budget")
	if isinstance(line_count, int):
		if isinstance(line_budget, int):
			lines.append(f"- Line count: {line_count}/{line_budget}")
		else:
			lines.append(f"- Line count: {line_count}")
	top_level_test_count = test_analysis.get("top_level_test_count")
	expected_top_level_test_count = test_analysis.get("expected_top_level_test_count")
	max_top_level_test_count = test_analysis.get("max_top_level_test_count")
	if isinstance(top_level_test_count, int):
		if isinstance(expected_top_level_test_count, int):
			lines.append(f"- Top-level test functions: {top_level_test_count}/{expected_top_level_test_count}")
		elif isinstance(max_top_level_test_count, int):
			lines.append(f"- Top-level test functions: {top_level_test_count}/{max_top_level_test_count} max")
		else:
			lines.append(f"- Top-level test functions: {top_level_test_count}")
	fixture_count = test_analysis.get("fixture_count")
	fixture_budget = test_analysis.get("fixture_budget")
	if isinstance(fixture_count, int):
		if isinstance(fixture_budget, int):
			lines.append(f"- Fixture count: {fixture_count}/{fixture_budget}")
		else:
			lines.append(f"- Fixture count: {fixture_count}")
	assertion_like_count = test_analysis.get("assertion_like_count")
	if isinstance(assertion_like_count, int):
		lines.append(f"- Assertion-like checks: {assertion_like_count}")
	if syntax_ok:
		lines.append(f"- Type mismatches (warning): {', '.join(test_analysis.get('type_mismatches') or ['none'])}")
		lines.append(f"- Imported module symbols: {', '.join(test_analysis.get('imported_module_symbols') or ['none'])}")
		lines.append(f"- Missing function imports (blocking): {', '.join(test_analysis.get('missing_function_imports') or ['none'])}")
		lines.append(f"- Unknown module symbols (warning): {', '.join(test_analysis.get('unknown_module_symbols') or ['none'])}")
		lines.append(f"- Invalid member references (warning): {', '.join(test_analysis.get('invalid_member_references') or ['none'])}")
		lines.append(f"- Call arity mismatches (warning): {', '.join(test_analysis.get('call_arity_mismatches') or ['none'])}")
		lines.append(f"- Constructor arity mismatches (warning): {', '.join(test_analysis.get('constructor_arity_mismatches') or ['none'])}")
		lines.append(f"- Payload contract violations (warning): {', '.join(test_analysis.get('payload_contract_violations') or ['none'])}")
		lines.append(f"- Non-batch sequence calls (warning): {', '.join(test_analysis.get('non_batch_sequence_calls') or ['none'])}")
		lines.append(f"- Helper surface usages: {', '.join(test_analysis.get('helper_surface_usages') or ['none'])}")
		lines.append(f"- Reserved fixture names (warning): {', '.join(test_analysis.get('reserved_fixture_names') or ['none'])}")
		lines.append(f"- Undefined test fixtures (blocking): {', '.join(test_analysis.get('undefined_fixtures') or ['none'])}")
		lines.append(f"- Undefined local names (blocking): {', '.join(test_analysis.get('undefined_local_names') or ['none'])}")
		lines.append(f"- Tests without assertion-like checks: {', '.join(test_analysis.get('tests_without_assertions') or ['none'])}")
		lines.append(f"- Contract overreach signals (warning): {', '.join(contract_overreach_signals or ['none'])}")
	if isinstance(completion_diagnostics, dict):
		lines.append(f"- Completion diagnostics: {completion_diagnostics_summary(completion_diagnostics)}")
	if syntax_ok:
		lines.append(f"- Imported entrypoint symbols (blocking): {', '.join(test_analysis.get('imported_entrypoint_symbols') or ['none'])}")
		lines.append(f"- Unsafe entrypoint calls (blocking): {', '.join(test_analysis.get('unsafe_entrypoint_calls') or ['none'])}")
		lines.append(f"- Unsupported mock assertions (warning): {', '.join(test_analysis.get('unsupported_mock_assertions') or ['none'])}")
	if isinstance(test_execution, dict):
		if not test_execution.get("available", True):
			lines.append(f"- Pytest execution: unavailable ({test_execution.get('summary') or 'pytest unavailable'})")
		elif test_execution.get("ran"):
			lines.append(f"- Pytest execution: {'PASS' if test_execution.get('returncode') == 0 else 'FAIL'}")
			lines.append(f"- Pytest summary: {test_execution.get('summary') or 'none'}")
			failure_details = pytest_failure_details(test_execution)
			if failure_details:
				lines.append(f"- Pytest failure details: {'; '.join(failure_details)}")

	has_blocking_issues = (not syntax_ok) or (
		isinstance(line_count, int) and isinstance(line_budget, int) and line_count > line_budget
	) or (
		isinstance(top_level_test_count, int)
		and isinstance(expected_top_level_test_count, int)
		and top_level_test_count != expected_top_level_test_count
	) or (
		isinstance(top_level_test_count, int)
		and isinstance(max_top_level_test_count, int)
		and top_level_test_count > max_top_level_test_count
	) or (
		isinstance(fixture_count, int) and isinstance(fixture_budget, int) and fixture_count > fixture_budget
	) or any(test_analysis.get(key) for key in BLOCKING_TEST_ISSUE_KEYS)
	has_warning_issues = any(test_analysis.get(key) for key in WARNING_TEST_ISSUE_KEYS) or bool(test_analysis.get("tests_without_assertions"))
	execution_failed = isinstance(test_execution, dict) and test_execution.get("ran") and test_execution.get("returncode") not in (None, 0)
	execution_passed = isinstance(test_execution, dict) and test_execution.get("ran") and test_execution.get("returncode") == 0
	if has_blocking_issues or execution_failed:
		lines.append("- Verdict: FAIL")
	elif has_warning_issues and execution_passed:
		lines.append("- Verdict: PASS (warnings overridden by pytest)")
	elif has_warning_issues:
		lines.append("- Verdict: FAIL (warnings without pytest confirmation)")
	else:
		lines.append("- Verdict: PASS")
	return "\n".join(lines)
