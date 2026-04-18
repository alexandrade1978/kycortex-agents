"""Execution helpers for generated-module import and pytest sandbox runs."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Mapping

try:
	import resource
except ImportError:  # pragma: no cover - non-POSIX fallback
	resource = None  # type: ignore[assignment]

from kycortex_agents.orchestration.sandbox_runtime import (
	build_generated_test_env,
	build_sandbox_preexec_fn,
	sanitize_generated_filename,
)
from kycortex_agents.orchestration.sandbox_templates import (
	render_generated_import_runner,
	render_generated_test_runner,
)
from kycortex_agents.orchestration.validation_runtime import (
	redact_validation_execution_result,
	summarize_pytest_output,
)
from kycortex_agents.types import ExecutionSandboxPolicy


def sandbox_security_violation(exc: Exception) -> bool:
	return "sandbox policy blocked" in str(exc).lower()


def write_generated_test_runner(
	tmp_path: Path,
	test_filename: str,
	sandbox_enabled: bool,
) -> Path:
	runner_path = tmp_path / "_kycortex_run_pytest.py"
	runner_path.write_text(
		render_generated_test_runner(
			sandbox_enabled=sandbox_enabled,
			pytest_config_path=str(tmp_path / "pytest.ini"),
			rootdir_path=str(tmp_path),
			pytest_log_path=str(tmp_path / "pytest.log"),
			test_filename=test_filename,
		),
		encoding="utf-8",
	)
	return runner_path


def write_generated_import_runner(
	tmp_path: Path,
	module_filename: str,
	sandbox_enabled: bool,
) -> Path:
	runner_path = tmp_path / "_kycortex_import_module.py"
	runner_path.write_text(
		render_generated_import_runner(
			sandbox_enabled=sandbox_enabled,
			module_filename=module_filename,
		),
		encoding="utf-8",
	)
	return runner_path


def execute_generated_module_import(
	module_filename: str,
	code_content: str,
	sandbox_policy: ExecutionSandboxPolicy,
	*,
	python_executable: str = sys.executable,
	host_env: Mapping[str, str] | None = None,
	subprocess_run: Callable[..., Any] = subprocess.run,
	sanitize_filename: Callable[[str, str], str] = sanitize_generated_filename,
	write_import_runner_fn: Callable[[Path, str, bool], Path] = write_generated_import_runner,
	build_env_fn: Callable[[Path, ExecutionSandboxPolicy], Dict[str, str]] | None = None,
	build_preexec_fn: Callable[[ExecutionSandboxPolicy], Any] | None = None,
	redact_result: Callable[[Dict[str, Any]], Dict[str, Any]] = redact_validation_execution_result,
) -> Dict[str, Any]:
	result: Dict[str, Any] = {
		"ran": False,
		"returncode": None,
		"summary": "",
	}
	if not code_content.strip():
		result["summary"] = "generated code was empty"
		return result

	build_env = build_env_fn or (
		lambda tmp_path, policy: build_generated_test_env(tmp_path, policy, host_env=host_env or os.environ)
	)
	build_preexec = build_preexec_fn or (
		lambda policy: build_sandbox_preexec_fn(policy, os_module=os, resource_module=resource)
	)
	wall_clock_seconds = sandbox_policy.max_wall_clock_seconds
	with tempfile.TemporaryDirectory(
		prefix="kycortex-import-",
		dir=sandbox_policy.temp_root,
	) as tmp_dir:
		tmp_path = Path(tmp_dir)
		tmp_path.chmod(0o700)
		safe_module_filename = sanitize_filename(module_filename, "generated_module.py")
		import_runner_path = write_import_runner_fn(tmp_path, safe_module_filename, sandbox_policy.enabled)
		module_path = tmp_path / safe_module_filename
		module_path.write_text(code_content, encoding="utf-8")
		for path in (module_path, import_runner_path):
			path.chmod(0o600)
		env = build_env(tmp_path, sandbox_policy)
		command = [python_executable]
		if sandbox_policy.enabled:
			command.append("-I")
		command.append(str(import_runner_path))
		try:
			completed = subprocess_run(
				command,
				cwd=tmp_path,
				capture_output=True,
				text=True,
				timeout=wall_clock_seconds,
				env=env,
				preexec_fn=build_preexec(sandbox_policy),
				check=False,
			)
		except subprocess.TimeoutExpired:
			result["ran"] = True
			result["returncode"] = -1
			result["summary"] = f"module import timed out after {wall_clock_seconds:g} seconds"
			return redact_result(result)

	result["ran"] = True
	result["returncode"] = completed.returncode
	result["stdout"] = completed.stdout.strip()
	result["stderr"] = completed.stderr.strip()
	combined_lines = [line.strip() for line in f"{completed.stdout}\n{completed.stderr}".splitlines() if line.strip()]
	if completed.returncode == 0:
		result["summary"] = combined_lines[-1][:240] if combined_lines else "module import succeeded"
	else:
		result["summary"] = combined_lines[-1][:240] if combined_lines else (
			f"module import exited with code {completed.returncode}"
		)
	result["sandbox"] = _sandbox_metadata(sandbox_policy)
	return redact_result(result)


def execute_generated_tests(
	module_filename: str,
	code_content: str,
	test_filename: str,
	test_content: str,
	sandbox_policy: ExecutionSandboxPolicy,
	*,
	python_executable: str = sys.executable,
	host_env: Mapping[str, str] | None = None,
	pytest_spec_finder: Callable[[str], Any] = importlib.util.find_spec,
	subprocess_run: Callable[..., Any] = subprocess.run,
	sanitize_filename: Callable[[str, str], str] = sanitize_generated_filename,
	write_test_runner_fn: Callable[[Path, str, bool], Path] = write_generated_test_runner,
	build_env_fn: Callable[[Path, ExecutionSandboxPolicy], Dict[str, str]] | None = None,
	build_preexec_fn: Callable[[ExecutionSandboxPolicy], Any] | None = None,
	summarize_output: Callable[[str, str, int], str] = summarize_pytest_output,
	redact_result: Callable[[Dict[str, Any]], Dict[str, Any]] = redact_validation_execution_result,
) -> Dict[str, Any]:
	result: Dict[str, Any] = {
		"available": pytest_spec_finder("pytest") is not None,
		"ran": False,
		"returncode": None,
		"summary": "",
	}
	if not result["available"]:
		result["summary"] = "pytest is not installed in the current environment"
		return redact_result(result)
	if not code_content.strip() or not test_content.strip():
		result["summary"] = "generated code or tests were empty"
		return redact_result(result)

	build_env = build_env_fn or (
		lambda tmp_path, policy: build_generated_test_env(tmp_path, policy, host_env=host_env or os.environ)
	)
	build_preexec = build_preexec_fn or (
		lambda policy: build_sandbox_preexec_fn(policy, os_module=os, resource_module=resource)
	)
	wall_clock_seconds = sandbox_policy.max_wall_clock_seconds
	with tempfile.TemporaryDirectory(
		prefix="kycortex-tests-",
		dir=sandbox_policy.temp_root,
	) as tmp_dir:
		tmp_path = Path(tmp_dir)
		tmp_path.chmod(0o700)
		safe_module_filename = sanitize_filename(module_filename, "generated_module.py")
		safe_test_filename = sanitize_filename(test_filename, "generated_tests.py")
		pytest_config_path = tmp_path / "pytest.ini"
		pytest_runner_path = write_test_runner_fn(tmp_path, safe_test_filename, sandbox_policy.enabled)
		module_path = tmp_path / safe_module_filename
		test_path = tmp_path / safe_test_filename
		module_path.write_text(code_content, encoding="utf-8")
		test_path.write_text(test_content, encoding="utf-8")
		pytest_config_path.write_text("[pytest]\n", encoding="utf-8")
		for path in (module_path, test_path, pytest_config_path, pytest_runner_path):
			path.chmod(0o600)
		env = build_env(tmp_path, sandbox_policy)
		command = [python_executable]
		if sandbox_policy.enabled:
			command.append("-I")
		command.append(str(pytest_runner_path))
		try:
			completed = subprocess_run(
				command,
				cwd=tmp_path,
				capture_output=True,
				text=True,
				timeout=wall_clock_seconds,
				env=env,
				preexec_fn=build_preexec(sandbox_policy),
				check=False,
			)
		except subprocess.TimeoutExpired:
			result["ran"] = True
			result["returncode"] = -1
			result["summary"] = f"pytest timed out after {wall_clock_seconds:g} seconds"
			return redact_result(result)

	result["ran"] = True
	result["returncode"] = completed.returncode
	result["stdout"] = completed.stdout.strip()
	result["stderr"] = completed.stderr.strip()
	result["summary"] = summarize_output(completed.stdout, completed.stderr, completed.returncode)
	result["sandbox"] = _sandbox_metadata(sandbox_policy)
	return redact_result(result)


def _sandbox_metadata(sandbox_policy: ExecutionSandboxPolicy) -> Dict[str, Any]:
	return {
		"enabled": sandbox_policy.enabled,
		"allow_network": sandbox_policy.allow_network,
		"allow_subprocesses": sandbox_policy.allow_subprocesses,
		"max_cpu_seconds": sandbox_policy.max_cpu_seconds,
		"max_wall_clock_seconds": sandbox_policy.max_wall_clock_seconds,
		"max_memory_mb": sandbox_policy.max_memory_mb,
	}