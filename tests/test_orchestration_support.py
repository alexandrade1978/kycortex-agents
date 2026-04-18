import ast
import os
import re
import stat
from types import SimpleNamespace

import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.orchestration.ast_tools import AstNameReplacer
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.private_files import (
	harden_private_directory_permissions,
	harden_private_file_permissions,
)
from kycortex_agents.orchestration.sandbox_execution import (
	execute_generated_module_import,
	execute_generated_tests,
	sandbox_security_violation,
	write_generated_import_runner,
	write_generated_test_runner,
)
from kycortex_agents.orchestration.sandbox_runtime import (
	build_generated_test_env,
	build_sandbox_preexec_fn,
	looks_like_secret_env_var,
	sanitize_generated_filename,
)
from kycortex_agents.orchestration.sandbox_templates import (
	render_generated_import_runner,
	render_generated_test_runner,
	render_sandbox_sitecustomize,
)
from kycortex_agents.orchestration.task_constraints import (
	compact_architecture_context,
	should_compact_architecture_context,
	task_exact_top_level_test_count,
	task_fixture_budget,
	task_line_budget,
	task_max_top_level_test_count,
	task_requires_cli_entrypoint,
)
from kycortex_agents.orchestration.validation_reporting import (
	build_code_validation_summary,
	build_test_validation_summary,
	completion_diagnostics_from_provider_call,
	completion_diagnostics_summary,
	completion_validation_issue,
	looks_structurally_truncated,
)
from kycortex_agents.orchestration.validation_runtime import (
	provider_call_metadata,
	redact_validation_execution_result,
	sanitize_output_provider_call_metadata,
	summarize_pytest_output,
)
from kycortex_agents.orchestration.validation_analysis import (
	pytest_contract_overreach_signals,
	pytest_failure_details,
	pytest_failure_is_semantic_assertion_mismatch,
	pytest_failure_origin,
	validation_has_blocking_issues,
	validation_has_only_warnings,
	validation_has_static_issues,
)
from kycortex_agents.orchestration.workflow_control import (
	privacy_safe_log_fields,
	task_id_collection_count,
	task_id_count_log_field_name,
)
from kycortex_agents.memory.project_state import Task
from kycortex_agents.types import AgentOutput, ArtifactRecord, ArtifactType, ExecutionSandboxPolicy


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")
def test_harden_private_file_permissions_sets_mode_600(tmp_path):
	artifact_path = tmp_path / "artifact.txt"
	artifact_path.write_text("secret", encoding="utf-8")
	artifact_path.chmod(0o644)

	harden_private_file_permissions(artifact_path)

	assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")
def test_harden_private_directory_permissions_sets_mode_700(tmp_path):
	directory_path = tmp_path / "artifacts"
	directory_path.mkdir()
	directory_path.chmod(0o755)

	harden_private_directory_permissions(directory_path)

	assert stat.S_IMODE(directory_path.stat().st_mode) == 0o700


def test_artifact_persistence_support_redacts_and_updates_relative_path(tmp_path):
	support = ArtifactPersistenceSupport(output_dir=str(tmp_path / "output"))
	artifacts = [
		ArtifactRecord(
			name="Report Draft",
			artifact_type=ArtifactType.DOCUMENT,
			content="Authorization: Bearer sk-ant-secret-987654",
			path="reports/final draft.md",
		)
	]

	support.persist_artifacts(artifacts)

	persisted_path = tmp_path / "output" / "reports" / "final_draft.md"
	persisted_content = persisted_path.read_text(encoding="utf-8")

	assert artifacts[0].path == "reports/final_draft.md"
	assert artifacts[0].content == persisted_content
	assert persisted_content == "Authorization: Bearer [REDACTED]"


def test_artifact_persistence_support_rejects_symlink_escape(tmp_path):
	support = ArtifactPersistenceSupport(output_dir=str(tmp_path / "output"))
	escaped_root = tmp_path / "escaped"
	escaped_root.mkdir()
	(tmp_path / "output").mkdir()
	linked_dir = tmp_path / "output" / "artifacts"
	linked_dir.symlink_to(escaped_root, target_is_directory=True)
	artifacts = [
		ArtifactRecord(
			name="Report Draft",
			artifact_type=ArtifactType.DOCUMENT,
			content="hello",
			path="artifacts/final.md",
		)
	]

	with pytest.raises(AgentExecutionError, match="resolves outside the output directory"):
		support.persist_artifacts(artifacts)

	assert not (escaped_root / "final.md").exists()
	assert artifacts[0].path == "artifacts/final.md"


def test_artifact_persistence_support_rejects_invalid_segment_from_injected_sanitizer(tmp_path):
	def fake_sub(pattern: str, replacement: str, value: str) -> str:
		if value == "unsafe":
			return "."
		return re.sub(pattern, replacement, value)

	support = ArtifactPersistenceSupport(
		output_dir=str(tmp_path / "output"),
		sanitize_sub=fake_sub,
	)

	with pytest.raises(AgentExecutionError, match="artifact path contains an invalid segment"):
		support.sanitize_artifact_relative_path("reports/unsafe/summary.md")


def test_ast_name_replacer_rewrites_names_in_expression():
	expression = ast.parse("foo + bar", mode="eval").body
	rewritten = AstNameReplacer(
		{
			"foo": ast.Constant(value=10),
			"bar": ast.Name(id="baz", ctx=ast.Load()),
		}
	).visit(expression)

	assert ast.unparse(ast.fix_missing_locations(rewritten)) == "10 + baz"


def test_render_sandbox_sitecustomize_returns_dedented_script():
	script = render_sandbox_sitecustomize()

	assert script.startswith("import asyncio\n")
	assert "sandbox policy blocked filesystem write outside sandbox root" in script
	assert script.endswith("\n")


def test_render_generated_test_runner_includes_configured_paths(tmp_path):
	script = render_generated_test_runner(
		sandbox_enabled=True,
		pytest_config_path=str(tmp_path / "pytest.ini"),
		rootdir_path=str(tmp_path),
		pytest_log_path=str(tmp_path / "pytest.log"),
		test_filename="generated_tests.py",
	)

	assert 'sandbox_sitecustomize = TMP_PATH / "sitecustomize.py"' in script
	assert repr(str(tmp_path / "pytest.ini")) in script
	assert repr("generated_tests.py") in script
	assert "pytest.main(pytest_args)" in script


def test_render_generated_import_runner_includes_module_filename():
	script = render_generated_import_runner(
		sandbox_enabled=False,
		module_filename="code_under_test.py",
	)

	assert 'TMP_PATH / "sitecustomize.py"' in script
	assert repr("code_under_test.py") in script
	assert '"code_under_test"' in script


def test_looks_like_secret_env_var_detects_generic_secret_markers():
	assert looks_like_secret_env_var("OPENAI_API_KEY") is True
	assert looks_like_secret_env_var("client_secret") is True
	assert looks_like_secret_env_var("NORMAL_ENV") is False


def test_sanitize_generated_filename_strips_traversal_and_preserves_suffix():
	assert sanitize_generated_filename("../../tests generated", "generated_tests.py") == "tests_generated.py"
	assert sanitize_generated_filename("custom-name", "generated_tests.py") == "custom-name.py"


def test_build_generated_test_env_writes_sandbox_bindings_and_sitecustomize(tmp_path):
	policy = KYCortexConfig(output_dir=str(tmp_path / "output")).execution_sandbox_policy()
	env = build_generated_test_env(tmp_path, policy, host_env={"PATH": "/usr/bin", "PYTHONPATH": "/tmp/injected"})

	assert env["PATH"] == str(tmp_path)
	assert env["HOME"] == str(tmp_path)
	assert env["KYCORTEX_SANDBOX_ROOT"] == str(tmp_path)
	assert env["PYTHONDONTWRITEBYTECODE"] == "1"
	assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
	assert "PYTHONPATH" not in env
	assert (tmp_path / "sitecustomize.py").read_text(encoding="utf-8").startswith("import asyncio\n")


def test_build_generated_test_env_omits_sandbox_files_when_disabled(tmp_path):
	policy = ExecutionSandboxPolicy(enabled=False)
	env = build_generated_test_env(tmp_path, policy, host_env={"PATH": "/usr/bin", "PYTHONPATH": "/tmp/injected"})

	assert env["PATH"] == "/usr/bin"
	assert "KYCORTEX_SANDBOX_ROOT" not in env
	assert "XDG_CONFIG_HOME" not in env
	assert "PYTHONPATH" not in env
	assert not (tmp_path / "sitecustomize.py").exists()


def test_build_sandbox_preexec_fn_applies_limits_with_injected_modules():
	policy = ExecutionSandboxPolicy(enabled=True, max_cpu_seconds=5.2, max_memory_mb=128)
	recorded_calls: list[tuple[object, tuple[int, int]]] = []
	recorded_umasks: list[int] = []
	fake_os = SimpleNamespace(name="posix", umask=lambda value: recorded_umasks.append(value) or 0)
	fake_resource = SimpleNamespace(
		RLIMIT_CPU="cpu",
		RLIMIT_AS="as",
		RLIMIT_CORE="core",
		RLIMIT_FSIZE="fsize",
		setrlimit=lambda limit, values: recorded_calls.append((limit, values)),
	)

	preexec = build_sandbox_preexec_fn(policy, os_module=fake_os, resource_module=fake_resource)

	assert callable(preexec)
	preexec()
	assert recorded_umasks == [0o077]
	assert recorded_calls == [
		("cpu", (5, 5)),
		("as", (134217728, 134217728)),
		("core", (0, 0)),
		("fsize", (1048576, 1048576)),
	]


def test_write_generated_runner_helpers_persist_scripts(tmp_path):
	pytest_runner = write_generated_test_runner(tmp_path, "generated_tests.py", sandbox_enabled=True)
	import_runner = write_generated_import_runner(tmp_path, "generated_module.py", sandbox_enabled=False)

	assert pytest_runner.name == "_kycortex_run_pytest.py"
	assert import_runner.name == "_kycortex_import_module.py"
	assert "generated_tests.py" in pytest_runner.read_text(encoding="utf-8")
	assert "generated_module.py" in import_runner.read_text(encoding="utf-8")


def test_execute_generated_tests_returns_unavailable_when_pytest_missing_directly(tmp_path):
	policy = KYCortexConfig(output_dir=str(tmp_path / "output")).execution_sandbox_policy()

	result = execute_generated_tests(
		"generated_module.py",
		"def ok():\n    return 1\n",
		"generated_tests.py",
		"def test_ok():\n    assert True\n",
		policy,
		pytest_spec_finder=lambda name: None,
	)

	assert result == {
		"available": False,
		"ran": False,
		"returncode": None,
		"summary": "pytest is not installed in the current environment",
	}


def test_execute_generated_module_import_redacts_sensitive_output_directly(tmp_path):
	policy = KYCortexConfig(output_dir=str(tmp_path / "output")).execution_sandbox_policy()

	def fake_run(*args, **kwargs):
		return SimpleNamespace(
			returncode=1,
			stdout="api_key=sk-secret-123456",
			stderr="Authorization: Bearer sk-ant-secret-987654",
		)

	result = execute_generated_module_import(
		"generated_module.py",
		"def ok():\n    return 1\n",
		policy,
		subprocess_run=fake_run,
	)

	assert result["ran"] is True
	assert result["returncode"] == 1
	assert "[REDACTED]" in result["stdout"]
	assert "[REDACTED]" in result["stderr"]
	assert "sk-secret-123456" not in result["summary"]


def test_sandbox_security_violation_detects_blocked_message():
	assert sandbox_security_violation(RuntimeError("sandbox policy blocked filesystem write outside sandbox root")) is True
	assert sandbox_security_violation(RuntimeError("provider temporarily unavailable")) is False


def test_validation_reporting_detects_structural_truncation_and_completion_summary():
	assert looks_structurally_truncated("label:\n", "expected an indented block") is True
	assert looks_structurally_truncated("value = 1\n", "invalid syntax") is False
	assert completion_validation_issue({"hit_token_limit": True}) == "output likely truncated at the completion token limit"
	assert completion_diagnostics_summary({"done_reason": "stop"}) == "provider termination reason recorded"


def test_completion_diagnostics_from_provider_call_marks_length_limited_output_as_truncated():
	diagnostics = completion_diagnostics_from_provider_call(
		{
			"requested_max_tokens": 900,
			"finish_reason": "length",
			"usage": {"output_tokens": 900},
		},
		syntax_ok=False,
	)

	assert diagnostics == {
		"requested_max_tokens": 900,
		"output_tokens": 900,
		"finish_reason": "length",
		"stop_reason": None,
		"done_reason": None,
		"hit_token_limit": True,
		"likely_truncated": True,
	}


def test_build_code_validation_summary_reports_import_and_contract_failures_directly():
	summary = build_code_validation_summary(
		{"syntax_ok": True, "third_party_imports": [], "line_count": 12, "line_budget": 20},
		"failed import",
		completion_diagnostics={"output_tokens": 120},
		import_validation={"ran": True, "returncode": 1, "summary": "TypeError"},
		task_public_contract_preflight={
			"anchor_present": True,
			"passed": False,
			"public_facade": "ComplianceIntakeService",
			"issues": ["missing public facade ComplianceIntakeService"],
		},
	)

	assert "Line count: 12/20" in summary
	assert "Completion diagnostics: token usage recorded" in summary
	assert "Module import: FAIL" in summary
	assert "Task public contract: FAIL" in summary


def test_build_test_validation_summary_reports_warning_override_and_pytest_details_directly():
	summary = build_test_validation_summary(
		{
			"syntax_ok": True,
			"constructor_arity_mismatches": ["MyClass (line 5)"],
		},
		{
			"available": True,
			"ran": True,
			"returncode": 0,
			"summary": "1 passed",
		},
	)

	assert "Constructor arity mismatches (warning): MyClass (line 5)" in summary
	assert "Pytest execution: PASS" in summary
	assert summary.endswith("- Verdict: PASS (warnings overridden by pytest)")


def test_summarize_pytest_output_handles_empty_and_fallback_cases_directly():
	assert summarize_pytest_output("", "", 5) == "pytest exited with code 5"
	assert summarize_pytest_output("line one", "line two", 1) == "line two"


def test_redact_validation_execution_result_redacts_sensitive_values():
	result = redact_validation_execution_result(
		{
			"stdout": "api_key=sk-secret-123456",
			"stderr": "Authorization: Bearer sk-ant-secret-987654",
		}
	)

	assert "sk-secret-123456" not in str(result)
	assert "sk-ant-secret-987654" not in str(result)
	assert "[REDACTED]" in result["stdout"]
	assert "[REDACTED]" in result["stderr"]


def test_provider_call_metadata_prefers_output_and_redacts_sensitive_fields():
	output = AgentOutput(
		summary="ok",
		raw_content="ok",
		metadata={
			"provider_call": {
				"provider": "anthropic",
				"model": "claude-test",
				"base_url": "https://bob:secret-pass@example.com/messages",
				"error_message": "Authorization: Bearer sk-ant-secret-987654",
			}
		},
	)

	metadata = provider_call_metadata(object(), output)

	assert metadata is not None
	assert metadata["provider"] == "anthropic"
	assert metadata["model"] == "claude-test"
	assert "secret-pass" not in str(metadata)
	assert "sk-ant-secret-987654" not in str(metadata)


def test_sanitize_output_provider_call_metadata_updates_output_copy_in_place():
	output = AgentOutput(
		summary="ok",
		raw_content="ok",
		metadata={
			"provider_call": {
				"provider": "openai",
				"base_url": "https://alice:secret-pass@example.com/v1",
			}
		},
	)

	sanitized = sanitize_output_provider_call_metadata(output)

	assert sanitized is output
	assert "secret-pass" not in str(sanitized.metadata["provider_call"])
	assert "[REDACTED]" in sanitized.metadata["provider_call"]["base_url"]


def test_task_constraint_helpers_parse_limits_and_optional_inputs_directly():
	task = Task(
		id="tests",
		title="Tests",
		description=(
			"Write exactly 2 top-level test functions at most 3 fixtures and under 40 lines. "
			"Include a CLI demo entrypoint."
		),
		assigned_to="qa_tester",
	)

	assert task_line_budget(task) == 40
	assert task_requires_cli_entrypoint(task) is True
	assert task_exact_top_level_test_count(task) == 2
	assert task_max_top_level_test_count(task) is None
	assert task_fixture_budget(task) == 3
	assert task_line_budget(None) is None
	assert task_requires_cli_entrypoint(None) is False


def test_should_compact_architecture_context_uses_budget_and_repair_signals_directly():
	anchor = "- Public facade: ComplianceIntakeService"
	budget_task = Task(
		id="code",
		title="Implementation",
		description="Write one Python module under 300 lines.",
		assigned_to="code_engineer",
	)
	repair_task = Task(
		id="code_repair",
		title="Repair",
		description="Write one Python module.",
		assigned_to="code_engineer",
		repair_context={"cycle": 1},
	)

	assert should_compact_architecture_context(budget_task, anchor, "code_engineer", 900) is True
	assert should_compact_architecture_context(budget_task, anchor, "architect", 900) is False
	assert should_compact_architecture_context(repair_task, anchor, "code_engineer", 3200) is True
	assert should_compact_architecture_context(budget_task, "", "code_engineer", 900) is False


def test_compact_architecture_context_builds_low_budget_and_repair_summaries_directly():
	anchor = (
		"- Public facade: ComplianceIntakeService\n"
		"- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)"
	)
	budget_task = Task(
		id="code",
		title="Implementation",
		description="Write one Python module under 300 lines with a CLI demo entrypoint.",
		assigned_to="code_engineer",
	)
	repair_task = Task(
		id="repair",
		title="Repair",
		description="Write one Python module.",
		assigned_to="code_engineer",
		repair_context={"cycle": 1},
	)

	budget_summary = compact_architecture_context(budget_task, anchor)
	repair_summary = compact_architecture_context(repair_task, anchor)

	assert budget_summary.startswith("Low-budget architecture summary:")
	assert "Stay comfortably under 300 lines" in budget_summary
	assert 'main() plus a literal if __name__ == "__main__": block' in budget_summary
	assert repair_summary.startswith("Repair-focused architecture summary:")
	assert "Do not copy illustrative code blocks over the failing implementation" in repair_summary
	assert "prefer the existing failing module, the validation summary, and the cited pytest details" in repair_summary


def test_workflow_control_log_helpers_minimize_task_ids_directly():
	fields = privacy_safe_log_fields(
		{
			"task_ids": ["arch", "code"],
			"replayed_task_ids": ["arch"],
			"reason": "manual",
		}
	)

	assert fields == {"task_count": 2, "replayed_task_count": 1, "reason": "manual"}
	assert task_id_collection_count(["arch", "code"]) == 2
	assert task_id_collection_count("arch") == 1
	assert task_id_collection_count(None) == 0
	assert task_id_collection_count(3) is None
	assert task_id_count_log_field_name("task_ids") == "task_count"
	assert task_id_count_log_field_name("replayed_task_ids") == "replayed_task_count"
	assert task_id_count_log_field_name("task_id") is None


def test_validation_analysis_helpers_extract_failure_details_and_origin_directly():
	test_execution = {
		"stdout": "FAILED tests_tests.py::test_example - AssertionError: assert 1 == 2\nE   AssertionError: assert 1 == 2\n",
		"stderr": "",
	}

	assert pytest_failure_details(test_execution) == [
		"FAILED tests_tests.py::test_example - AssertionError: assert 1 == 2 | AssertionError: assert 1 == 2"
	]
	assert pytest_failure_origin({"stdout": "tests_tests.py:24: AssertionError\n", "stderr": ""}, "code.py", "tests_tests.py") == "tests"
	assert pytest_failure_is_semantic_assertion_mismatch(test_execution) is True


def test_validation_analysis_helpers_classify_blocking_and_warning_issues_directly():
	blocking_validation = {
		"test_analysis": {
			"syntax_ok": True,
			"undefined_local_names": ["result"],
		}
	}
	warning_validation = {
		"test_analysis": {
			"syntax_ok": True,
			"constructor_arity_mismatches": ["MyClass (line 5)"],
		}
	}

	assert validation_has_static_issues(blocking_validation) is True
	assert validation_has_blocking_issues(blocking_validation) is True
	assert validation_has_blocking_issues(warning_validation) is False
	assert validation_has_only_warnings(warning_validation) is True


def test_validation_analysis_helpers_detect_contract_overreach_directly():
	test_execution = {
		"stdout": "FAILED tests_tests.py::test_example - AssertionError: assert 'approved' == 'rejected'\n",
		"stderr": "",
	}

	signals = pytest_contract_overreach_signals(test_execution)

	assert signals == [
		"exact status/action label mismatch ('approved' vs 'rejected') suggests an unsupported threshold assumption"
	]