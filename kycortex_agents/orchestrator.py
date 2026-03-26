import ast
import importlib.util
import logging
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Any, Optional, cast

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None  # type: ignore[assignment]

from kycortex_agents.agents.registry import AgentRegistry, build_default_registry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import (
    AgentInput,
    AgentOutput,
    ArtifactRecord,
    ArtifactType,
    ExecutionSandboxPolicy,
    FailureCategory,
    TaskStatus,
    WorkflowOutcome,
)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


_THIRD_PARTY_PACKAGE_ALIASES = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "crypto": "pycryptodome",
    "pil": "pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}

_STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", set()))
_PYTEST_BUILTIN_FIXTURES = {
    "cache",
    "capfd",
    "capfdbinary",
    "caplog",
    "capsys",
    "capsysbinary",
    "capteesys",
    "doctest_namespace",
    "monkeypatch",
    "pytestconfig",
    "record_property",
    "record_testsuite_property",
    "record_xml_attribute",
    "recwarn",
    "tmp_path",
    "tmp_path_factory",
    "tmpdir",
    "tmpdir_factory",
}

_SANDBOX_SITECUSTOMIZE = """
import asyncio
import builtins
import glob
import io
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile


_REAL_OPEN = builtins.open
_REAL_IO_OPEN = io.open
_REAL_OS_OPEN = os.open
_REAL_OS_STAT = os.stat
_REAL_OS_LSTAT = getattr(os, "lstat", None)
_REAL_OS_PATH_REALPATH = os.path.realpath
_REAL_GLOB_GLOB = glob.glob
_REAL_GLOB_IGLOB = glob.iglob
_REAL_PATH_RESOLVE = pathlib.Path.resolve
_REAL_PATH_STATS = {
    _class_name: getattr(getattr(pathlib, _class_name), "stat")
    for _class_name in ("Path", "PosixPath", "WindowsPath")
    if getattr(pathlib, _class_name, None) is not None and hasattr(getattr(pathlib, _class_name), "stat")
}
_SANDBOX_ROOT = pathlib.Path(os.environ.get("KYCORTEX_SANDBOX_ROOT", os.getcwd())).resolve()
_RUNTIME_SAFE_ROOTS = set()
_RUNTIME_SAFE_FILES = set()
_RUNTIME_SAFE_METADATA_PATHS = set()


def _add_runtime_safe_root(path_value):
    if not path_value:
        return
    try:
        _RUNTIME_SAFE_ROOTS.add(pathlib.Path(path_value).resolve())
    except Exception:
        return


for _path_value in sysconfig.get_paths().values():
    _add_runtime_safe_root(_path_value)

for _path_value in (
    sys.prefix,
    getattr(sys, "base_prefix", ""),
    sys.exec_prefix,
    getattr(sys, "base_exec_prefix", ""),
    sys.executable,
):
    _add_runtime_safe_root(_path_value)

for _path_value in (os.devnull, "/dev/urandom"):
    if not _path_value:
        continue
    try:
        _RUNTIME_SAFE_FILES.add(pathlib.Path(_path_value).resolve())
    except Exception:
        continue

try:
    _RUNTIME_SAFE_METADATA_PATHS.add(_SANDBOX_ROOT.parent.resolve())
except Exception:
    pass


def _is_write_mode(mode):
    if isinstance(mode, int):
        write_flags = (
            os.O_WRONLY
            | os.O_RDWR
            | os.O_APPEND
            | os.O_CREAT
            | os.O_TRUNC
        )
        return bool(mode & write_flags)
    normalized_mode = str(mode or "r")
    return any(flag in normalized_mode for flag in ("w", "a", "+", "x"))


def _resolve_path_unchecked(path_value):
    if isinstance(path_value, int):
        return path_value
    _saved_os_stat = os.stat
    _saved_os_lstat = getattr(os, "lstat", None)
    _saved_os_path_realpath = os.path.realpath
    _saved_path_stats = {}
    try:
        os.stat = _REAL_OS_STAT
        if _REAL_OS_LSTAT is not None:
            os.lstat = _REAL_OS_LSTAT
        os.path.realpath = _REAL_OS_PATH_REALPATH
        for _class_name, _real_stat in _REAL_PATH_STATS.items():
            _path_class = getattr(pathlib, _class_name, None)
            if _path_class is None:
                continue
            _saved_path_stats[_class_name] = getattr(_path_class, "stat", None)
            setattr(_path_class, "stat", _real_stat)
        return _REAL_PATH_RESOLVE(pathlib.Path(path_value))
    finally:
        os.stat = _saved_os_stat
        if _REAL_OS_LSTAT is not None and _saved_os_lstat is not None:
            os.lstat = _saved_os_lstat
        os.path.realpath = _saved_os_path_realpath
        for _class_name, _saved_stat in _saved_path_stats.items():
            _path_class = getattr(pathlib, _class_name, None)
            if _path_class is not None and _saved_stat is not None:
                setattr(_path_class, "stat", _saved_stat)


def _is_within_sandbox(path_value):
    if isinstance(path_value, int):
        return True
    try:
        candidate = _resolve_path_unchecked(path_value)
    except Exception:
        return False
    try:
        candidate.relative_to(_SANDBOX_ROOT)
        return True
    except ValueError:
        return False


def _is_runtime_safe_path(path_value):
    if isinstance(path_value, int):
        return True
    try:
        candidate = _resolve_path_unchecked(path_value)
    except Exception:
        return False
    if candidate in _RUNTIME_SAFE_FILES:
        return True
    for safe_root in _RUNTIME_SAFE_ROOTS:
        try:
            candidate.relative_to(safe_root)
            return True
        except ValueError:
            continue
    return False


def _blocked(*args, **kwargs):
    raise RuntimeError("sandbox policy blocked this operation")


def _blocked_filesystem_write(*args, **kwargs):
    raise RuntimeError("sandbox policy blocked filesystem write outside sandbox root")


def _blocked_filesystem_read(path_value=None, *args, **kwargs):
    raise RuntimeError("sandbox policy blocked file access outside sandbox root")


def _ensure_read_within_policy(path_value):
    if not (_is_within_sandbox(path_value) or _is_runtime_safe_path(path_value)):
        _blocked_filesystem_read(path_value)


def _ensure_metadata_read_within_policy(path_value):
    if _is_within_sandbox(path_value) or _is_runtime_safe_path(path_value):
        return
    try:
        candidate = _resolve_path_unchecked(path_value)
    except Exception:
        _blocked_filesystem_read(path_value)
    if candidate in _RUNTIME_SAFE_METADATA_PATHS:
        return
    _blocked_filesystem_read(path_value)


def _ensure_mutation_within_sandbox(*path_values):
    for path_value in path_values:
        if not _is_within_sandbox(path_value):
            _blocked_filesystem_write()


def _guarded_open(file, mode="r", *args, **kwargs):
    if _is_write_mode(mode):
        if not _is_within_sandbox(file):
            _blocked_filesystem_write()
    elif not (_is_within_sandbox(file) or _is_runtime_safe_path(file)):
        _blocked_filesystem_read()
    return _REAL_OPEN(file, mode, *args, **kwargs)


def _guarded_os_open(path, flags, mode=0o777, *args, **kwargs):
    if _is_write_mode(flags):
        if not _is_within_sandbox(path):
            _blocked_filesystem_write()
    elif not (_is_within_sandbox(path) or _is_runtime_safe_path(path)):
        _blocked_filesystem_read()
    return _REAL_OS_OPEN(path, flags, mode, *args, **kwargs)


builtins.open = _guarded_open
io.open = _guarded_open
os.open = _guarded_os_open
tempfile.tempdir = str(_SANDBOX_ROOT)


for _name in (
    "chmod",
    "chown",
    "lchown",
    "makedirs",
    "mkdir",
    "mkfifo",
    "mknod",
    "remove",
    "removedirs",
    "rmdir",
    "unlink",
    "utime",
):
    if hasattr(os, _name):
        _real = getattr(os, _name)

        def _guarded_single_path(*args, __real=_real, **kwargs):
            if args:
                _ensure_mutation_within_sandbox(args[0])
            return __real(*args, **kwargs)

        setattr(os, _name, _guarded_single_path)


for _name in ("access", "listdir", "scandir"):
    if hasattr(os, _name):
        _real = getattr(os, _name)

        def _guarded_read_path(*args, __real=_real, **kwargs):
            if args:
                _ensure_read_within_policy(args[0])
            return __real(*args, **kwargs)

        setattr(os, _name, _guarded_read_path)


for _name in ("stat", "lstat"):
    if hasattr(os, _name):
        _real = getattr(os, _name)

        def _guarded_metadata_read_path(*args, __real=_real, **kwargs):
            if args:
                _ensure_metadata_read_within_policy(args[0])
            return __real(*args, **kwargs)

        setattr(os, _name, _guarded_metadata_read_path)


if hasattr(os, "walk"):
    _real = os.walk

    def _guarded_walk(top, *args, __real=_real, **kwargs):
        _ensure_read_within_policy(top)
        return __real(top, *args, **kwargs)

    os.walk = _guarded_walk


if hasattr(os, "fwalk"):
    _real = os.fwalk

    def _guarded_fwalk(top, *args, __real=_real, **kwargs):
        _ensure_read_within_policy(top)
        return __real(top, *args, **kwargs)

    os.fwalk = _guarded_fwalk


def _guarded_glob(pathname, *args, __real=_REAL_GLOB_GLOB, **kwargs):
    _ensure_read_within_policy(pathname)
    return __real(pathname, *args, **kwargs)


def _guarded_iglob(pathname, *args, __real=_REAL_GLOB_IGLOB, **kwargs):
    _ensure_read_within_policy(pathname)
    return __real(pathname, *args, **kwargs)


glob.glob = _guarded_glob
glob.iglob = _guarded_iglob


for _name in (
    "exists",
    "getatime",
    "getctime",
    "getmtime",
    "getsize",
    "isdir",
    "isfile",
    "islink",
    "ismount",
    "lexists",
    "realpath",
):
    if hasattr(os.path, _name):
        _real = getattr(os.path, _name)

        def _guarded_os_path_read(path, *args, __real=_real, **kwargs):
            _ensure_metadata_read_within_policy(path)
            return __real(path, *args, **kwargs)

        setattr(os.path, _name, _guarded_os_path_read)


for _name in ("samefile",):
    if hasattr(os.path, _name):
        _real = getattr(os.path, _name)

        def _guarded_os_path_metadata_pair(left_path, right_path, *args, __real=_real, **kwargs):
            _ensure_metadata_read_within_policy(left_path)
            _ensure_metadata_read_within_policy(right_path)
            return __real(left_path, right_path, *args, **kwargs)

        setattr(os.path, _name, _guarded_os_path_metadata_pair)


for _name in ("link", "rename", "replace", "symlink"):
    if hasattr(os, _name):
        _real = getattr(os, _name)

        def _guarded_two_path(*args, __real=_real, **kwargs):
            if len(args) >= 2:
                _ensure_mutation_within_sandbox(args[0], args[1])
            return __real(*args, **kwargs)

        setattr(os, _name, _guarded_two_path)


for _path_class_name in ("Path", "PosixPath", "WindowsPath"):
    _path_class = getattr(pathlib, _path_class_name, None)
    if _path_class is None:
        continue

    if hasattr(_path_class, "open"):
        _real = getattr(_path_class, "open")

        def _guarded_path_open(*args, __real=_real, **kwargs):
            target_path = args[0] if args else kwargs.get("self")
            mode = args[1] if len(args) >= 2 else kwargs.get("mode", "r")
            if _is_write_mode(mode):
                _ensure_mutation_within_sandbox(target_path)
            else:
                _ensure_read_within_policy(target_path)
            return __real(*args, **kwargs)

        setattr(_path_class, "open", _guarded_path_open)

    for _name in ("chmod", "mkdir", "rmdir", "unlink"):
        if hasattr(_path_class, _name):
            _real = getattr(_path_class, _name)

            def _guarded_path_single(*args, __real=_real, **kwargs):
                if args:
                    _ensure_mutation_within_sandbox(args[0])
                return __real(*args, **kwargs)

            setattr(_path_class, _name, _guarded_path_single)

    for _name in (
        "exists",
        "is_block_device",
        "is_char_device",
        "is_dir",
        "is_fifo",
        "is_file",
        "is_mount",
        "is_socket",
        "is_symlink",
    ):
        if hasattr(_path_class, _name):
            _real = getattr(_path_class, _name)

            def _guarded_path_read(*args, __real=_real, **kwargs):
                if args:
                    _ensure_metadata_read_within_policy(args[0])
                return __real(*args, **kwargs)

            setattr(_path_class, _name, _guarded_path_read)

    for _name in ("group", "lstat", "owner", "readlink", "stat"):
        if hasattr(_path_class, _name):
            _real = getattr(_path_class, _name)

            def _guarded_path_metadata_single(*args, __real=_real, **kwargs):
                if args:
                    _ensure_metadata_read_within_policy(args[0])
                return __real(*args, **kwargs)

            setattr(_path_class, _name, _guarded_path_metadata_single)

    for _name in ("resolve",):
        if hasattr(_path_class, _name):
            _real = getattr(_path_class, _name)

            def _guarded_path_resolve(*args, __real=_real, **kwargs):
                if args:
                    _ensure_metadata_read_within_policy(args[0])
                return __real(*args, **kwargs)

            setattr(_path_class, _name, _guarded_path_resolve)

    for _name in ("samefile",):
        if hasattr(_path_class, _name):
            _real = getattr(_path_class, _name)

            def _guarded_path_metadata_pair(*args, __real=_real, **kwargs):
                if len(args) >= 2:
                    _ensure_metadata_read_within_policy(args[0])
                    _ensure_metadata_read_within_policy(args[1])
                return __real(*args, **kwargs)

            setattr(_path_class, _name, _guarded_path_metadata_pair)

    for _name in ("glob", "iterdir", "rglob", "walk"):
        if hasattr(_path_class, _name):
            _real = getattr(_path_class, _name)

            def _guarded_path_iter(*args, __real=_real, **kwargs):
                if args:
                    _ensure_read_within_policy(args[0])
                return __real(*args, **kwargs)

            setattr(_path_class, _name, _guarded_path_iter)

    for _name in ("hardlink_to", "rename", "replace", "symlink_to"):
        if hasattr(_path_class, _name):
            _real = getattr(_path_class, _name)

            def _guarded_path_double(*args, __real=_real, **kwargs):
                if len(args) >= 2:
                    _ensure_mutation_within_sandbox(args[0], args[1])
                return __real(*args, **kwargs)

            setattr(_path_class, _name, _guarded_path_double)


for _name in ("copy", "copy2", "copyfile", "copytree", "move"):
    if hasattr(shutil, _name):
        _real = getattr(shutil, _name)

        def _guarded_shutil_two_path(*args, __real=_real, **kwargs):
            if len(args) >= 2:
                _ensure_mutation_within_sandbox(args[0], args[1])
            return __real(*args, **kwargs)

        setattr(shutil, _name, _guarded_shutil_two_path)


for _name in ("rmtree",):
    if hasattr(shutil, _name):
        _real = getattr(shutil, _name)

        def _guarded_shutil_single(*args, __real=_real, **kwargs):
            if args:
                _ensure_mutation_within_sandbox(args[0])
            return __real(*args, **kwargs)

        setattr(shutil, _name, _guarded_shutil_single)


if os.environ.get("KYCORTEX_SANDBOX_ALLOW_NETWORK") != "1":
    socket.socket = _blocked
    socket.create_connection = _blocked


if os.environ.get("KYCORTEX_SANDBOX_ALLOW_SUBPROCESSES") != "1":
    subprocess.Popen = _blocked
    subprocess.run = _blocked
    subprocess.call = _blocked
    subprocess.check_call = _blocked
    subprocess.check_output = _blocked
    os.system = _blocked
    for _name in (
        "fork",
        "forkpty",
        "posix_spawn",
        "posix_spawnp",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    ):
        if hasattr(os, _name):
            setattr(os, _name, _blocked)
    asyncio.create_subprocess_exec = _blocked
    asyncio.create_subprocess_shell = _blocked
"""

_GENERATED_TEST_RUNNER = """
import importlib
import importlib.util
import pathlib
import sys

TMP_PATH = pathlib.Path(__file__).resolve().parent
if str(TMP_PATH) not in sys.path:
    sys.path.insert(0, str(TMP_PATH))

if {sandbox_enabled}:
    sandbox_sitecustomize = TMP_PATH / "sitecustomize.py"
    sandbox_spec = importlib.util.spec_from_file_location(
        "_kycortex_sandbox_sitecustomize",
        sandbox_sitecustomize,
    )
    if sandbox_spec is None or sandbox_spec.loader is None:
        raise RuntimeError("sandbox startup failed: missing sitecustomize loader")
    sandbox_module = importlib.util.module_from_spec(sandbox_spec)
    sys.modules[sandbox_spec.name] = sandbox_module
    sandbox_spec.loader.exec_module(sandbox_module)

import pytest

raise SystemExit(
    pytest.main(
        [
            "-c",
            {pytest_config_path},
            "--rootdir",
            {rootdir_path},
            "-o",
            {pytest_log_option},
            {test_filename},
            "-q",
        ]
    )
)
"""


class Orchestrator:
    """Public workflow runtime for executing tasks with a configured or custom registry.

    Pass a custom AgentRegistry when consumers need to register their own agent
    implementations while keeping `execute_workflow()` and `run_task()` as the
    supported execution entry points.
    """

    def __init__(self, config: Optional[KYCortexConfig] = None, registry: Optional[AgentRegistry] = None):
        self.config = config or KYCortexConfig()
        self.registry = registry or build_default_registry(self.config)
        self.logger = logging.getLogger("Orchestrator")

    def _log_event(self, level: str, event: str, **fields: Any) -> None:
        log_method = getattr(self.logger, level)
        log_method(event, extra={"event": event, **fields})

    def run_task(self, task: Task, project: ProjectState) -> str:
        """Execute one task through the public orchestrator runtime contract."""
        execution_agent_name = self._execution_agent_name(task)
        self._log_event(
            "info",
            "task_started",
            project_name=project.project_name,
            task_id=task.id,
            task_title=task.title,
            assigned_to=execution_agent_name,
            attempt=task.attempts + 1,
        )
        agent = self.registry.get(execution_agent_name)
        agent_input = self._build_agent_input(task, project)
        project.start_task(task.id)
        normalized_output: Optional[AgentOutput] = None
        try:
            output = self._execute_agent(agent, agent_input)
            normalized_output = self._normalize_agent_result(output)
            self._validate_task_output(task, agent_input.context, normalized_output)
            self._persist_artifacts(normalized_output.artifacts)
            for decision in normalized_output.decisions:
                project.add_decision_record(decision)
            for artifact in normalized_output.artifacts:
                project.add_artifact_record(artifact)
            provider_call = self._provider_call_metadata(agent, normalized_output)
            project.complete_task(task.id, normalized_output, provider_call=provider_call)
        except Exception as exc:
            failure_category = self._classify_task_failure(task, exc)
            project.fail_task(
                task.id,
                exc,
                provider_call=self._provider_call_metadata(agent, normalized_output),
                output=normalized_output,
                error_category=failure_category,
            )
            if project.should_retry_task(task.id):
                self._log_event(
                    "warning",
                    "task_retry_scheduled",
                    project_name=project.project_name,
                    task_id=task.id,
                    task_title=task.title,
                    assigned_to=execution_agent_name,
                    attempt=task.attempts,
                    error_type=type(exc).__name__,
                )
            else:
                provider_call = self._provider_call_metadata(agent, normalized_output)
                self._log_event(
                    "error",
                    "task_failed",
                    project_name=project.project_name,
                    task_id=task.id,
                    task_title=task.title,
                    assigned_to=execution_agent_name,
                    attempt=task.attempts,
                    error_type=type(exc).__name__,
                    provider=provider_call.get("provider") if provider_call else None,
                    model=provider_call.get("model") if provider_call else None,
                )
            raise
        self._log_event(
            "info",
            "task_completed",
            project_name=project.project_name,
            task_id=task.id,
            task_title=task.title,
            assigned_to=execution_agent_name,
            attempt=task.attempts,
            provider=provider_call.get("provider") if provider_call else None,
            model=provider_call.get("model") if provider_call else None,
            total_tokens=(provider_call.get("usage") or {}).get("total_tokens") if provider_call else None,
        )
        return normalized_output.raw_content

    def _validate_task_output(self, task: Task, context: Dict[str, Any], output: AgentOutput) -> None:
        normalized_role = AgentRegistry.normalize_key(task.assigned_to)
        if normalized_role == "code_engineer":
            self._validate_code_output(output)
            return
        if normalized_role == "qa_tester":
            self._validate_test_output(context, output)
            return
        if normalized_role != "dependency_manager":
            return
        raw_code_analysis = context.get("code_analysis")
        code_analysis = cast(Dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
        dependency_analysis = self._analyze_dependency_manifest(output.raw_content, code_analysis)
        self._record_output_validation(output, "dependency_analysis", dependency_analysis)
        if dependency_analysis.get("is_valid"):
            return
        missing_entries = ", ".join(dependency_analysis.get("missing_manifest_entries") or []) or "unknown"
        raise AgentExecutionError(
            f"Dependency manifest validation failed: missing manifest entries for {missing_entries}"
        )

    def _validate_code_output(self, output: AgentOutput) -> None:
        code_artifact_content = self._artifact_content(output, ArtifactType.CODE)
        code_content = code_artifact_content or output.raw_content
        if not self._should_validate_code_content(code_content, has_typed_artifact=bool(code_artifact_content)):
            return
        code_analysis = self._analyze_python_module(code_content)
        self._record_output_validation(output, "code_analysis", code_analysis)
        if code_analysis.get("syntax_ok", True):
            return
        raise AgentExecutionError(
            f"Generated code validation failed: syntax error {code_analysis.get('syntax_error') or 'unknown syntax error'}"
        )

    def _validate_test_output(self, context: Dict[str, Any], output: AgentOutput) -> None:
        raw_code_analysis = context.get("code_analysis")
        code_analysis = cast(Dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
        if code_analysis and not code_analysis.get("syntax_ok", True):
            raise AgentExecutionError(
                f"Generated test validation failed: code under test has syntax error {code_analysis.get('syntax_error') or 'unknown syntax error'}"
            )

        module_name = context.get("module_name")
        module_filename = context.get("module_filename")
        code_content = context.get("code")
        if not isinstance(module_name, str) or not module_name.strip():
            return
        if not isinstance(module_filename, str) or not module_filename.strip():
            module_filename = f"{module_name}.py"
        if not isinstance(code_content, str) or not code_content.strip():
            return

        test_artifact_content = self._artifact_content(output, ArtifactType.TEST)
        test_content = test_artifact_content or output.raw_content
        if not self._should_validate_test_content(test_content, has_typed_artifact=bool(test_artifact_content)):
            return
        test_filename = self._artifact_filename(output, ArtifactType.TEST, default_filename="tests_tests.py")
        code_behavior_contract = context.get("code_behavior_contract")
        test_analysis = self._analyze_test_module(
            test_content,
            module_name,
            code_analysis,
            code_behavior_contract if isinstance(code_behavior_contract, str) else "",
        )
        test_execution = self._execute_generated_tests(module_filename, code_content, test_filename, test_content)
        self._record_output_validation(output, "test_analysis", test_analysis)
        self._record_output_validation(output, "test_execution", test_execution)

        validation_issues: list[str] = []
        if not test_analysis.get("syntax_ok", True):
            validation_issues.append(f"test syntax error {test_analysis.get('syntax_error') or 'unknown syntax error'}")
        for issue_key, label in (
            ("missing_function_imports", "missing function imports"),
            ("unknown_module_symbols", "unknown module symbols"),
            ("invalid_member_references", "invalid member references"),
            ("constructor_arity_mismatches", "constructor arity mismatches"),
            ("payload_contract_violations", "payload contract violations"),
            ("non_batch_sequence_calls", "non-batch sequence calls"),
            ("undefined_fixtures", "undefined test fixtures"),
            ("imported_entrypoint_symbols", "imported entrypoint symbols"),
            ("unsafe_entrypoint_calls", "unsafe entrypoint calls"),
        ):
            issues = test_analysis.get(issue_key) or []
            if issues:
                validation_issues.append(f"{label}: {', '.join(issues)}")

        if test_execution.get("ran") and test_execution.get("returncode") not in (None, 0):
            validation_issues.append(f"pytest failed: {test_execution.get('summary') or 'generated tests failed'}")

        if validation_issues:
            raise AgentExecutionError(f"Generated test validation failed: {'; '.join(validation_issues)}")

    def _classify_task_failure(self, task: Task, exc: Exception) -> str:
        normalized_role = AgentRegistry.normalize_key(self._execution_agent_name(task))
        if isinstance(exc, WorkflowDefinitionError):
            return FailureCategory.WORKFLOW_DEFINITION.value
        if isinstance(exc, AgentExecutionError):
            if normalized_role == "code_engineer":
                return FailureCategory.CODE_VALIDATION.value
            if normalized_role == "qa_tester":
                return FailureCategory.TEST_VALIDATION.value
            if normalized_role == "dependency_manager":
                return FailureCategory.DEPENDENCY_VALIDATION.value
        return FailureCategory.TASK_EXECUTION.value

    def _execution_agent_name(self, task: Task) -> str:
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        repair_owner = repair_context.get("repair_owner")
        if isinstance(repair_owner, str) and repair_owner.strip():
            return repair_owner
        return task.assigned_to

    def _artifact_content(self, output: AgentOutput, artifact_type: ArtifactType) -> str:
        for artifact in output.artifacts:
            if artifact.artifact_type != artifact_type:
                continue
            if isinstance(artifact.content, str) and artifact.content.strip():
                return artifact.content
        return ""

    def _artifact_filename(self, output: AgentOutput, artifact_type: ArtifactType, default_filename: str) -> str:
        for artifact in output.artifacts:
            if artifact.artifact_type != artifact_type:
                continue
            if artifact.path:
                return Path(artifact.path).name
        return default_filename

    def _record_output_validation(self, output: AgentOutput, key: str, value: Any) -> None:
        validation = output.metadata.setdefault("validation", {})
        if isinstance(validation, dict):
            validation[key] = value

    def _should_validate_code_content(self, content: str, has_typed_artifact: bool) -> bool:
        if has_typed_artifact:
            return True
        stripped = content.strip()
        if not stripped:
            return False
        return any(token in stripped for token in ("def ", "class ", "import ", "from ", "if __name__"))

    def _should_validate_test_content(self, content: str, has_typed_artifact: bool) -> bool:
        if has_typed_artifact:
            return True
        stripped = content.strip()
        if not stripped:
            return False
        return any(token in stripped for token in ("def test_", "assert ", "import pytest", "pytest."))

    def _execute_generated_tests(
        self,
        module_filename: str,
        code_content: str,
        test_filename: str,
        test_content: str,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "available": importlib.util.find_spec("pytest") is not None,
            "ran": False,
            "returncode": None,
            "summary": "",
        }
        if not result["available"]:
            result["summary"] = "pytest is not installed in the current environment"
            return result
        if not code_content.strip() or not test_content.strip():
            result["summary"] = "generated code or tests were empty"
            return result

        sandbox_policy = self.config.execution_sandbox_policy()
        with tempfile.TemporaryDirectory(
            prefix="kycortex-tests-",
            dir=sandbox_policy.temp_root,
        ) as tmp_dir:
            tmp_path = Path(tmp_dir)
            tmp_path.chmod(0o700)
            safe_module_filename = self._sanitize_generated_filename(module_filename, "generated_module.py")
            safe_test_filename = self._sanitize_generated_filename(test_filename, "generated_tests.py")
            pytest_config_path = tmp_path / "pytest.ini"
            pytest_runner_path = self._write_generated_test_runner(tmp_path, safe_test_filename, sandbox_policy.enabled)
            module_path = tmp_path / safe_module_filename
            test_path = tmp_path / safe_test_filename
            module_path.write_text(code_content, encoding="utf-8")
            test_path.write_text(test_content, encoding="utf-8")
            pytest_config_path.write_text("[pytest]\n", encoding="utf-8")
            for path in (module_path, test_path, pytest_config_path, pytest_runner_path):
                path.chmod(0o600)
            env = self._build_generated_test_env(tmp_path, sandbox_policy)
            command = [sys.executable]
            if sandbox_policy.enabled:
                command.append("-I")
            command.append(str(pytest_runner_path))
            try:
                completed = subprocess.run(
                    command,
                    cwd=tmp_path,
                    capture_output=True,
                    text=True,
                    timeout=max(self.config.timeout_seconds, 1.0),
                    env=env,
                    preexec_fn=self._sandbox_preexec_fn(sandbox_policy),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                result["ran"] = True
                result["returncode"] = -1
                result["summary"] = (
                    f"pytest timed out after {self.config.timeout_seconds:g} seconds"
                )
                return result

        result["ran"] = True
        result["returncode"] = completed.returncode
        result["stdout"] = completed.stdout.strip()
        result["stderr"] = completed.stderr.strip()
        result["summary"] = self._summarize_pytest_output(completed.stdout, completed.stderr, completed.returncode)
        result["sandbox"] = {
            "enabled": sandbox_policy.enabled,
            "allow_network": sandbox_policy.allow_network,
            "allow_subprocesses": sandbox_policy.allow_subprocesses,
            "max_cpu_seconds": sandbox_policy.max_cpu_seconds,
            "max_memory_mb": sandbox_policy.max_memory_mb,
        }
        return result

    def _build_generated_test_env(
        self,
        tmp_path: Path,
        sandbox_policy: ExecutionSandboxPolicy,
    ) -> Dict[str, str]:
        if sandbox_policy.enabled:
            env = {key: value for key, value in sandbox_policy.sanitized_env.items() if value}
        else:
            env = os.environ.copy()
        env["PATH"] = os.environ.get("PATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        for key in (
            "PYTHONASYNCIODEBUG",
            "PYTHONBREAKPOINT",
            "PYTHONCASEOK",
            "PYTHONDEBUG",
            "PYTHONDEVMODE",
            "PYTHONEXECUTABLE",
            "PYTHONFAULTHANDLER",
            "PYTHONHOME",
            "PYTHONINTMAXSTRDIGITS",
            "PYTHONIOENCODING",
            "PYTHONINSPECT",
            "PYTHONNODEBUGRANGES",
            "PYTHONOPTIMIZE",
            "PYTHONPATH",
            "PYTHONPYCACHEPREFIX",
            "PYTHONPLATLIBDIR",
            "PYTHONPROFILEIMPORTTIME",
            "PYTHONSAFEPATH",
            "PYTHONSTARTUP",
            "PYTHONTRACEMALLOC",
            "PYTHONUSERBASE",
            "PYTHONUTF8",
            "PYTHONVERBOSE",
            "PYTHONWARNDEFAULTENCODING",
        ):
            env.pop(key, None)
        for key in list(env):
            if key.startswith("PYTEST_"):
                env.pop(key, None)
        for key in list(env):
            if key.startswith(("VIRTUAL_ENV", "CONDA_", "PIP_", "UV_", "POETRY_", "PIXI_", "PYENV_")):
                env.pop(key, None)
        for key in list(env):
            if key.startswith(("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT")):
                env.pop(key, None)
        for key in list(env):
            if key.startswith(("AWS_", "AZURE_", "GCP_", "GOOGLE_", "HF_", "OLLAMA_")) or key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
                env.pop(key, None)
        for key in list(env):
            if key.startswith(("GIT_", "SSH_")) or key == "GNUPGHOME":
                env.pop(key, None)
        for key in list(env):
            if key.startswith(("DOCKER_", "KUBE", "PODMAN_", "CONTAINER_", "GITHUB_", "GITLAB_", "BUILDKITE_", "JENKINS_")) or key == "CI":
                env.pop(key, None)
        for key in list(env):
            if key.startswith(("LD_", "DYLD_", "PYTHONMALLOC")) or key == "PYTHONWARNINGS":
                env.pop(key, None)
        if sandbox_policy.enabled and sandbox_policy.disable_pytest_plugin_autoload:
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        for key in list(env):
            if key.startswith(("COV_CORE_", "COVERAGE_")):
                env.pop(key, None)
        for key in ("COLORTERM", "FORCE_COLOR", "NO_COLOR", "PY_COLORS", "CLICOLOR", "CLICOLOR_FORCE", "COLUMNS", "LINES"):
            env.pop(key, None)
        if sandbox_policy.enabled:
            sandbox_config_home = tmp_path / ".config"
            sandbox_cache_home = tmp_path / ".cache"
            sandbox_local_home = tmp_path / ".local"
            sandbox_data_home = sandbox_local_home / "share"
            sandbox_config_home.mkdir(parents=True, exist_ok=True)
            sandbox_cache_home.mkdir(parents=True, exist_ok=True)
            sandbox_data_home.mkdir(parents=True, exist_ok=True)
            sandbox_config_home.chmod(0o700)
            sandbox_cache_home.chmod(0o700)
            sandbox_local_home.chmod(0o700)
            sandbox_data_home.chmod(0o700)
            env["PATH"] = str(tmp_path)
            env["TMPDIR"] = str(tmp_path)
            env["TMP"] = str(tmp_path)
            env["TEMP"] = str(tmp_path)
            env["TEMPDIR"] = str(tmp_path)
            env["HOME"] = str(tmp_path)
            env["TERM"] = "dumb"
            env["USERPROFILE"] = str(tmp_path)
            env["USER"] = "sandbox_user"
            env["LOGNAME"] = "sandbox_user"
            env["USERNAME"] = "sandbox_user"
            env["LANG"] = "C.UTF-8"
            env["LC_ALL"] = "C.UTF-8"
            env["LANGUAGE"] = "en"
            env["TZ"] = "UTC"
            env["XDG_CONFIG_HOME"] = str(sandbox_config_home)
            env["XDG_CACHE_HOME"] = str(sandbox_cache_home)
            env["XDG_DATA_HOME"] = str(sandbox_data_home)
            env["KYCORTEX_SANDBOX_ALLOW_NETWORK"] = "1" if sandbox_policy.allow_network else "0"
            env["KYCORTEX_SANDBOX_ALLOW_SUBPROCESSES"] = "1" if sandbox_policy.allow_subprocesses else "0"
            env["KYCORTEX_SANDBOX_ROOT"] = str(tmp_path)
            (tmp_path / "sitecustomize.py").write_text(
                textwrap.dedent(_SANDBOX_SITECUSTOMIZE).strip() + "\n",
                encoding="utf-8",
            )
            (tmp_path / "sitecustomize.py").chmod(0o600)
        else:
            env.pop("TMPDIR", None)
            env.pop("KYCORTEX_SANDBOX_ALLOW_NETWORK", None)
            env.pop("KYCORTEX_SANDBOX_ALLOW_SUBPROCESSES", None)
            env.pop("KYCORTEX_SANDBOX_ROOT", None)
            env.pop("XDG_CONFIG_HOME", None)
            env.pop("XDG_CACHE_HOME", None)
            env.pop("XDG_DATA_HOME", None)
        return env

    def _write_generated_test_runner(
        self,
        tmp_path: Path,
        test_filename: str,
        sandbox_enabled: bool,
    ) -> Path:
        runner_path = tmp_path / "_kycortex_run_pytest.py"
        runner_path.write_text(
            textwrap.dedent(
                _GENERATED_TEST_RUNNER.format(
                    sandbox_enabled=repr(sandbox_enabled),
                    pytest_config_path=repr(str(tmp_path / "pytest.ini")),
                    rootdir_path=repr(str(tmp_path)),
                    pytest_log_option=repr(f"log_file={tmp_path / 'pytest.log'}"),
                    test_filename=repr(test_filename),
                )
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return runner_path

    def _sanitize_generated_filename(self, filename: str, default_filename: str) -> str:
        candidate = Path(filename).name if isinstance(filename, str) else ""
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).strip("._")
        if not sanitized:
            sanitized = default_filename
        if "." not in sanitized and "." in default_filename:
            sanitized = f"{sanitized}{Path(default_filename).suffix}"
        return sanitized

    def _sandbox_preexec_fn(self, sandbox_policy: ExecutionSandboxPolicy):
        if not sandbox_policy.enabled or os.name != "posix" or resource is None:
            return None

        def _apply_limits() -> None:
            cpu_seconds = max(int(sandbox_policy.max_cpu_seconds), 1)
            memory_bytes = max(sandbox_policy.max_memory_mb, 1) * 1024 * 1024
            os.umask(0o077)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))

        return _apply_limits

    def _summarize_pytest_output(self, stdout: str, stderr: str, returncode: int) -> str:
        combined_lines = [line.strip() for line in f"{stdout}\n{stderr}".splitlines() if line.strip()]
        if not combined_lines:
            return f"pytest exited with code {returncode}"
        for line in reversed(combined_lines):
            if line.startswith("=") or line.startswith("FAILED") or line.startswith("ERROR") or "passed" in line:
                return line
        return combined_lines[-1][:240]

    def _provider_call_metadata(self, agent: Any, output: Optional[AgentOutput] = None) -> Optional[Dict[str, Any]]:
        if output is not None:
            provider_call = output.metadata.get("provider_call")
            if isinstance(provider_call, dict):
                return dict(provider_call)
        getter = getattr(agent, "get_last_provider_call_metadata", None)
        if callable(getter):
            metadata = getter()
            if isinstance(metadata, dict):
                return metadata
        return None

    def _persist_artifacts(self, artifacts: list[ArtifactRecord]) -> None:
        for artifact in artifacts:
            content = artifact.content
            if not isinstance(content, str) or not content.strip():
                continue
            target_path = self._resolve_artifact_output_path(artifact)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            artifact.path = self._artifact_record_path(target_path)

    def _resolve_artifact_output_path(self, artifact: ArtifactRecord) -> Path:
        output_root = Path(self.config.output_dir).resolve()
        relative_path = self._sanitize_artifact_relative_path(
            artifact.path if artifact.path else self._default_artifact_path(artifact)
        )
        return output_root / relative_path

    def _sanitize_artifact_relative_path(self, artifact_path: str) -> Path:
        candidate = Path(artifact_path)
        if candidate.is_absolute():
            raise AgentExecutionError("Artifact persistence failed: absolute artifact paths are not allowed")

        sanitized_parts: list[str] = []
        for part in candidate.parts:
            if part in ("", "."):
                continue
            if part == "..":
                raise AgentExecutionError("Artifact persistence failed: parent-directory traversal is not allowed")
            cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", part).strip()
            if not cleaned or cleaned in (".", ".."):
                raise AgentExecutionError("Artifact persistence failed: artifact path contains an invalid segment")
            sanitized_parts.append(cleaned)

        if not sanitized_parts:
            raise AgentExecutionError("Artifact persistence failed: artifact path must not be empty")

        return Path(*sanitized_parts)

    def _artifact_record_path(self, target_path: Path) -> str:
        output_root = Path(self.config.output_dir).resolve()
        resolved_target = target_path.resolve()
        try:
            return str(resolved_target.relative_to(output_root))
        except ValueError:
            return str(resolved_target)

    def _default_artifact_path(self, artifact: ArtifactRecord) -> str:
        suffix_map = {
            ArtifactType.DOCUMENT: ".md",
            ArtifactType.CODE: ".py",
            ArtifactType.TEST: ".py",
            ArtifactType.CONFIG: ".json",
            ArtifactType.TEXT: ".txt",
            ArtifactType.OTHER: ".artifact",
        }
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", artifact.name).strip("._") or "artifact"
        return f"artifacts/{safe_name}{suffix_map.get(artifact.artifact_type, '.artifact')}"

    def _build_context(self, task: Task, project: ProjectState) -> Dict[str, Any]:
        snapshot = project.snapshot()
        execution_agent_name = self._execution_agent_name(task)
        ctx: Dict[str, Any] = {
            "goal": project.goal,
            "project_name": project.project_name,
            "phase": project.phase,
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "assigned_to": task.assigned_to,
                "execution_agent": execution_agent_name,
            },
            "snapshot": asdict(snapshot),
            "completed_tasks": {},
            "decisions": snapshot.decisions,
            "artifacts": snapshot.artifacts,
        }
        ctx.update(self._planned_module_context(project))
        default_module_name = self._default_module_name_for_task(task)
        if default_module_name:
            ctx["module_name"] = default_module_name
            ctx["module_filename"] = f"{default_module_name}.py"
        for prev_task in project.tasks:
            if prev_task.status == TaskStatus.DONE.value and prev_task.output:
                ctx[prev_task.id] = prev_task.output
                ctx["completed_tasks"][prev_task.id] = prev_task.output
                semantic_key = self._semantic_output_key(prev_task)
                if semantic_key:
                    ctx[semantic_key] = prev_task.output
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "code_engineer":
                    ctx.update(self._code_artifact_context(prev_task))
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "dependency_manager":
                    ctx.update(self._dependency_artifact_context(prev_task, ctx))
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "qa_tester":
                    ctx.update(self._test_artifact_context(prev_task, ctx))
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        if repair_context:
            ctx["repair_context"] = dict(repair_context)
            validation_summary = repair_context.get("validation_summary")
            if isinstance(validation_summary, str) and validation_summary.strip():
                ctx["repair_validation_summary"] = validation_summary
            failed_artifact_content = repair_context.get("failed_artifact_content")
            failed_output = repair_context.get("failed_output")
            repair_content = failed_artifact_content if isinstance(failed_artifact_content, str) and failed_artifact_content.strip() else failed_output
            normalized_execution_agent = AgentRegistry.normalize_key(execution_agent_name)
            if normalized_execution_agent == "code_engineer" and isinstance(repair_content, str) and repair_content.strip():
                ctx["existing_code"] = repair_content
            if normalized_execution_agent == "qa_tester":
                if isinstance(repair_content, str) and repair_content.strip():
                    ctx["existing_tests"] = repair_content
                if "test_validation_summary" not in ctx and isinstance(validation_summary, str) and validation_summary.strip():
                    ctx["test_validation_summary"] = validation_summary
            if normalized_execution_agent == "dependency_manager":
                if isinstance(repair_content, str) and repair_content.strip():
                    ctx["existing_dependency_manifest"] = repair_content
                if "dependency_validation_summary" not in ctx and isinstance(validation_summary, str) and validation_summary.strip():
                    ctx["dependency_validation_summary"] = validation_summary
        return ctx

    def _build_repair_instruction(self, task: Task, failure_category: str) -> str:
        instructions = {
            FailureCategory.CODE_VALIDATION.value: "Repair the generated Python module so it becomes syntactically valid and internally consistent.",
            FailureCategory.TEST_VALIDATION.value: "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
            FailureCategory.DEPENDENCY_VALIDATION.value: "Repair the requirements manifest so every required third-party import is declared minimally and correctly.",
            FailureCategory.TASK_EXECUTION.value: "Retry the task using the previous runtime failure details and correct the specific execution issue.",
            FailureCategory.UNKNOWN.value: "Retry the task using the previous failure details and produce a corrected result.",
        }
        return instructions.get(failure_category, f"Repair the previous failure for task '{task.id}' using the preserved evidence.")

    def _repair_owner_for_category(self, task: Task, failure_category: str) -> str:
        owner_by_category = {
            FailureCategory.CODE_VALIDATION.value: "code_engineer",
            FailureCategory.TEST_VALIDATION.value: "qa_tester",
            FailureCategory.DEPENDENCY_VALIDATION.value: "dependency_manager",
        }
        return owner_by_category.get(failure_category, task.assigned_to)

    def _validation_payload(self, task: Task) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        metadata = task.output_payload.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        validation = metadata.get("validation")
        return validation if isinstance(validation, dict) else {}

    def _failed_artifact_content(self, task: Task, artifact_type: Optional[ArtifactType] = None) -> str:
        if not isinstance(task.output_payload, dict):
            return task.output or ""
        artifacts = task.output_payload.get("artifacts")
        if not isinstance(artifacts, list):
            return task.output or task.output_payload.get("raw_content", "")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            if artifact_type is not None and artifact.get("artifact_type") != artifact_type.value:
                continue
            content = artifact.get("content")
            if isinstance(content, str) and content.strip():
                return content
        raw_content = task.output_payload.get("raw_content")
        return raw_content if isinstance(raw_content, str) else (task.output or "")

    def _build_code_validation_summary(self, code_analysis: Dict[str, Any], fallback_message: str) -> str:
        lines = ["Generated code validation:"]
        lines.append(f"- Syntax OK: {'yes' if code_analysis.get('syntax_ok', True) else 'no'}")
        syntax_error = code_analysis.get('syntax_error')
        if syntax_error:
            lines.append(f"- Syntax error: {syntax_error}")
        third_party_imports = code_analysis.get('third_party_imports') or []
        lines.append(f"- Third-party imports: {', '.join(third_party_imports or ['none'])}")
        if fallback_message:
            lines.append(f"- Failure message: {fallback_message}")
        return "\n".join(lines)

    def _build_repair_validation_summary(self, task: Task, failure_category: str) -> str:
        validation = self._validation_payload(task)
        fallback_message = task.last_error or task.output or ""
        if failure_category == FailureCategory.CODE_VALIDATION.value:
            code_analysis = validation.get("code_analysis")
            if isinstance(code_analysis, dict):
                return self._build_code_validation_summary(code_analysis, fallback_message)
        if failure_category == FailureCategory.TEST_VALIDATION.value:
            test_analysis = validation.get("test_analysis")
            test_execution = validation.get("test_execution")
            if isinstance(test_analysis, dict):
                return self._build_test_validation_summary(
                    test_analysis,
                    test_execution if isinstance(test_execution, dict) else None,
                )
        if failure_category == FailureCategory.DEPENDENCY_VALIDATION.value:
            dependency_analysis = validation.get("dependency_analysis")
            if isinstance(dependency_analysis, dict):
                return self._build_dependency_validation_summary(dependency_analysis)
        return fallback_message

    def _active_repair_cycle(self, project: ProjectState) -> Optional[Dict[str, Any]]:
        if not project.repair_history:
            return None
        current_cycle = project.repair_history[-1]
        if not isinstance(current_cycle, dict):
            return None
        return current_cycle

    def _build_repair_context(self, task: Task, cycle: Dict[str, Any]) -> Dict[str, Any]:
        failure_category = task.last_error_category or FailureCategory.UNKNOWN.value
        return {
            "cycle": cycle.get("cycle"),
            "failure_category": failure_category,
            "failure_message": task.last_error or task.output or "",
            "failure_error_type": task.last_error_type,
            "repair_owner": self._repair_owner_for_category(task, failure_category),
            "original_assigned_to": task.assigned_to,
            "instruction": self._build_repair_instruction(task, failure_category),
            "validation_summary": self._build_repair_validation_summary(task, failure_category),
            "failed_output": task.output or "",
            "failed_artifact_content": self._failed_artifact_content_for_category(task, failure_category),
            "provider_call": task.last_provider_call,
        }

    def _has_repair_task_for_cycle(self, project: ProjectState, task_id: str, cycle_number: int) -> bool:
        for existing_task in project.tasks:
            if existing_task.repair_origin_task_id != task_id:
                continue
            if existing_task.repair_attempt != cycle_number:
                continue
            return True
        return False

    def _queue_active_cycle_repair(self, project: ProjectState, task: Task) -> bool:
        if self.config.workflow_resume_policy != "resume_failed":
            return False
        if task.repair_origin_task_id is not None:
            return False
        current_cycle = self._active_repair_cycle(project)
        if current_cycle is None:
            return False
        cycle_number = int(current_cycle.get("cycle") or 0)
        if cycle_number <= 0:
            return False
        if self._has_repair_task_for_cycle(project, task.id, cycle_number):
            return False

        repair_context = self._build_repair_context(task, current_cycle)
        project._plan_task_repair(task.id, repair_context)
        repair_task_ids = self._repair_task_ids_for_cycle(project, [task.id])
        if not repair_task_ids:
            return False
        project.resume_failed_tasks(
            include_failed_tasks=False,
            failed_task_ids=[task.id],
            additional_task_ids=repair_task_ids,
        )
        project._record_execution_event(
            event="task_repair_chained",
            task_id=task.id,
            status=task.status,
            details={
                "repair_task_ids": repair_task_ids,
                "repair_cycle_count": project.repair_cycle_count,
            },
        )
        self._log_event(
            "info",
            "task_repair_chained",
            project_name=project.project_name,
            task_id=task.id,
            repair_task_ids=repair_task_ids,
            repair_cycle_count=project.repair_cycle_count,
        )
        return True

    def _failed_artifact_content_for_category(self, task: Task, failure_category: str) -> str:
        if failure_category == FailureCategory.CODE_VALIDATION.value:
            return self._failed_artifact_content(task, ArtifactType.CODE)
        if failure_category == FailureCategory.TEST_VALIDATION.value:
            return self._failed_artifact_content(task, ArtifactType.TEST)
        if failure_category == FailureCategory.DEPENDENCY_VALIDATION.value:
            return self._failed_artifact_content(task, ArtifactType.CONFIG)
        return self._failed_artifact_content(task)

    def _configure_repair_attempts(self, project: ProjectState, failed_task_ids: list[str], cycle: Dict[str, Any]) -> None:
        for task in project.tasks:
            if task.id not in failed_task_ids:
                continue
            repair_context = self._build_repair_context(task, cycle)
            project._plan_task_repair(task.id, repair_context)

    def _repair_task_ids_for_cycle(self, project: ProjectState, failed_task_ids: list[str]) -> list[str]:
        repair_task_ids: list[str] = []
        for task_id in failed_task_ids:
            task = project.get_task(task_id)
            if task is None:
                continue
            repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
            repair_owner = self._execution_agent_name(task)
            repair_task = project._create_repair_task(task_id, repair_owner, repair_context)
            if repair_task is not None:
                repair_task_ids.append(repair_task.id)
        return repair_task_ids

    def _failed_task_ids_for_repair(self, project: ProjectState) -> list[str]:
        active_repair_origins = {
            task.repair_origin_task_id
            for task in project.tasks
            if task.repair_origin_task_id
            and task.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}
        }
        return [
            task.id
            for task in project.tasks
            if task.status == TaskStatus.FAILED.value
            and not task.repair_origin_task_id
            and task.id not in active_repair_origins
        ]

    def _planned_module_context(self, project: ProjectState) -> Dict[str, Any]:
        for existing_task in project.tasks:
            if AgentRegistry.normalize_key(existing_task.assigned_to) != "code_engineer":
                continue
            module_name = self._default_module_name_for_task(existing_task)
            if not module_name:
                continue
            return {
                "planned_module_name": module_name,
                "planned_module_filename": f"{module_name}.py",
            }
        return {}

    def _default_module_name_for_task(self, task: Task) -> Optional[str]:
        if AgentRegistry.normalize_key(task.assigned_to) != "code_engineer":
            return None
        return f"{task.id}_implementation"

    def _code_artifact_context(self, task: Task) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        artifacts = task.output_payload.get("artifacts")
        if not isinstance(artifacts, list):
            return {}
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            if artifact.get("artifact_type") != ArtifactType.CODE.value:
                continue
            artifact_path = artifact.get("path")
            if not isinstance(artifact_path, str) or not artifact_path.strip():
                continue
            path_obj = Path(artifact_path)
            module_name = path_obj.stem
            code_analysis = self._analyze_python_module(task.output or "")
            return {
                "code_artifact_path": artifact_path,
                "module_name": module_name,
                "module_filename": path_obj.name,
                "code_summary": self._summarize_output(task.output or ""),
                "code_outline": self._build_code_outline(task.output or ""),
                "code_analysis": code_analysis,
                "code_public_api": self._build_code_public_api(code_analysis),
                "code_test_targets": self._build_code_test_targets(code_analysis),
                "code_behavior_contract": self._build_code_behavior_contract(task.output or ""),
                "module_run_command": self._build_module_run_command(path_obj.name, code_analysis),
            }
        return {}

    def _test_artifact_context(self, task: Task, context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        artifacts = task.output_payload.get("artifacts")
        if not isinstance(artifacts, list):
            return {}
        metadata = task.output_payload.get("metadata")
        validation = metadata.get("validation") if isinstance(metadata, dict) else None
        module_name = context.get("module_name")
        code_analysis = context.get("code_analysis")
        if not isinstance(module_name, str) or not module_name or not isinstance(code_analysis, dict):
            return {}
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            if artifact.get("artifact_type") != ArtifactType.TEST.value:
                continue
            artifact_path = artifact.get("path")
            if not isinstance(artifact_path, str) or not artifact_path.strip():
                continue
            test_analysis = validation.get("test_analysis") if isinstance(validation, dict) else None
            if not isinstance(test_analysis, dict):
                test_analysis = self._analyze_test_module(task.output or "", module_name, code_analysis)
            test_execution = validation.get("test_execution") if isinstance(validation, dict) else None
            return {
                "tests_artifact_path": artifact_path,
                "test_analysis": test_analysis,
                "test_execution": test_execution if isinstance(test_execution, dict) else None,
                "test_validation_summary": self._build_test_validation_summary(
                    test_analysis,
                    test_execution if isinstance(test_execution, dict) else None,
                ),
            }
        return {}

    def _dependency_artifact_context(self, task: Task, context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        artifacts = task.output_payload.get("artifacts")
        if not isinstance(artifacts, list):
            return {}
        raw_code_analysis = context.get("code_analysis")
        code_analysis = cast(Dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_path = artifact.get("path")
            if not isinstance(artifact_path, str) or not artifact_path.strip():
                continue
            path_obj = Path(artifact_path)
            if path_obj.name != "requirements.txt":
                continue
            dependency_analysis = self._analyze_dependency_manifest(task.output or "", code_analysis)
            return {
                "dependency_manifest": task.output or "",
                "dependency_manifest_path": artifact_path,
                "dependency_analysis": dependency_analysis,
                "dependency_validation_summary": self._build_dependency_validation_summary(dependency_analysis),
            }
        return {}

    def _analyze_dependency_manifest(self, manifest_content: str, code_analysis: Dict[str, Any]) -> Dict[str, Any]:
        declared_packages: list[str] = []
        normalized_declared_packages: set[str] = set()
        for raw_line in manifest_content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            package_name = re.split(r"\s*(?:==|>=|<=|~=|!=|>|<)", line, maxsplit=1)[0].strip()
            if not package_name:
                continue
            declared_packages.append(package_name)
            normalized_declared_packages.add(self._normalize_package_name(package_name))

        required_imports = sorted(code_analysis.get("third_party_imports") or []) if isinstance(code_analysis, dict) else []
        normalized_required_imports = {self._normalize_import_name(module_name) for module_name in required_imports}
        missing_manifest_entries = [
            module_name
            for module_name in required_imports
            if self._normalize_import_name(module_name) not in normalized_declared_packages
        ]
        unused_manifest_entries = [
            package_name
            for package_name in declared_packages
            if self._normalize_package_name(package_name) not in normalized_required_imports
        ]
        return {
            "required_imports": required_imports,
            "declared_packages": declared_packages,
            "missing_manifest_entries": missing_manifest_entries,
            "unused_manifest_entries": unused_manifest_entries,
            "is_valid": not missing_manifest_entries,
        }

    def _build_dependency_validation_summary(self, dependency_analysis: Dict[str, Any]) -> str:
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
        lines.append(f"- Verdict: {'PASS' if dependency_analysis.get('is_valid') else 'FAIL'}")
        return "\n".join(lines)

    def _normalize_package_name(self, package_name: str) -> str:
        return package_name.strip().lower().replace("-", "_")

    def _normalize_import_name(self, module_name: str) -> str:
        normalized_name = module_name.strip().lower().replace("-", "_")
        package_name = _THIRD_PARTY_PACKAGE_ALIASES.get(normalized_name, normalized_name)
        return self._normalize_package_name(package_name)

    def _build_code_outline(self, raw_content: str) -> str:
        if not raw_content.strip():
            return ""
        pattern = re.compile(r"^(class\s+\w+.*|def\s+\w+.*|async\s+def\s+\w+.*)$")
        outline_lines = [line.strip() for line in raw_content.splitlines() if pattern.match(line.strip())]
        return "\n".join(outline_lines[:40])

    def _analyze_python_module(self, raw_content: str) -> Dict[str, Any]:
        analysis: Dict[str, Any] = {
            "syntax_ok": True,
            "syntax_error": None,
            "functions": [],
            "classes": {},
            "imports": [],
            "third_party_imports": [],
            "symbols": [],
            "has_main_guard": '__name__ == "__main__"' in raw_content or "__name__ == '__main__'" in raw_content,
        }
        if not raw_content.strip():
            return analysis
        try:
            tree = ast.parse(raw_content)
        except SyntaxError as exc:
            analysis["syntax_ok"] = False
            analysis["syntax_error"] = f"{exc.msg} at line {exc.lineno}"
            return analysis

        functions: list[Dict[str, Any]] = []
        classes: Dict[str, Dict[str, Any]] = {}
        import_roots: set[str] = set()

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                params = [arg.arg for arg in node.args.args]
                functions.append({
                    "name": node.name,
                    "params": params,
                    "signature": f"{node.name}({', '.join(params)})",
                    "async": isinstance(node, ast.AsyncFunctionDef),
                })
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name:
                        import_roots.add(root_name)
                continue
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                module_name = (node.module or "").split(".", 1)[0]
                if module_name:
                    import_roots.add(module_name)
                continue
            if not isinstance(node, ast.ClassDef):
                continue

            field_names: list[str] = []
            class_attributes: list[str] = []
            init_params: list[str] = []
            methods: list[str] = []
            bases = [self._ast_name(base) for base in node.bases]
            is_enum = any(base.endswith("Enum") for base in bases)

            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    field_names.append(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            class_attributes.append(target.id)
                elif isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
                    init_params = [arg.arg for arg in stmt.args.args if arg.arg != "self"]
                elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and not stmt.name.startswith("_"):
                    params = [arg.arg for arg in stmt.args.args]
                    methods.append(f"{stmt.name}({', '.join(params)})")

            constructor_params = init_params or field_names
            classes[node.name] = {
                "name": node.name,
                "bases": bases,
                "is_enum": is_enum,
                "fields": field_names,
                "attributes": class_attributes,
                "constructor_params": constructor_params,
                "methods": methods,
            }

        analysis["functions"] = functions
        analysis["classes"] = classes
        analysis["imports"] = sorted(import_roots)
        analysis["third_party_imports"] = [
            module_name for module_name in sorted(import_roots) if self._is_probable_third_party_import(module_name)
        ]
        analysis["symbols"] = sorted([item["name"] for item in functions] + list(classes.keys()))
        return analysis

    def _is_probable_third_party_import(self, module_name: str) -> bool:
        normalized_name = module_name.strip()
        if not normalized_name:
            return False
        if normalized_name == "__future__":
            return False
        if normalized_name in _STDLIB_MODULES:
            return False
        return True

    def _build_code_public_api(self, code_analysis: Dict[str, Any]) -> str:
        if not code_analysis.get("syntax_ok", True):
            return f"Module syntax error: {code_analysis.get('syntax_error') or 'unknown syntax error'}"

        lines: list[str] = []
        functions = code_analysis.get("functions") or []
        classes = code_analysis.get("classes") or {}

        if functions:
            lines.append("Functions:")
            for function in functions:
                lines.append(f"- {function['signature']}")
        else:
            lines.append("Functions:\n- none")

        if classes:
            lines.append("Classes:")
            for class_name in sorted(classes):
                class_info = classes[class_name]
                if class_info.get("is_enum"):
                    members = ", ".join(class_info.get("attributes") or []) or "none"
                    lines.append(f"- {class_name} enum members: {members}")
                    continue
                constructor = ", ".join(class_info.get("constructor_params") or [])
                class_attrs = ", ".join(class_info.get("attributes") or class_info.get("fields") or [])
                methods = ", ".join(class_info.get("methods") or [])
                suffix = f"({constructor})" if constructor else "()"
                if class_attrs:
                    lines.append(f"- {class_name}{suffix}; class attributes/fields: {class_attrs}")
                else:
                    lines.append(f"- {class_name}{suffix}")
                if methods:
                    lines.append(f"  methods: {methods}")
        else:
            lines.append("Classes:\n- none")

        lines.append(
            f"Entrypoint: {'python ' + 'MODULE_FILE' if code_analysis.get('has_main_guard') else 'no __main__ entrypoint detected'}"
        )
        return "\n".join(lines)

    def _build_module_run_command(self, module_filename: str, code_analysis: Dict[str, Any]) -> str:
        if code_analysis.get("has_main_guard"):
            return f"python {module_filename}"
        return ""

    def _entrypoint_function_names(self, code_analysis: Dict[str, Any]) -> set[str]:
        function_names = {item["name"] for item in code_analysis.get("functions") or []}
        return {
            name
            for name in function_names
            if name == "main" or name.startswith("cli_") or name.endswith("_cli") or name.endswith("_demo")
        }

    def _build_code_test_targets(self, code_analysis: Dict[str, Any]) -> str:
        if not code_analysis.get("syntax_ok", True):
            return "Test targets unavailable because module syntax is invalid."

        entrypoint_names = self._entrypoint_function_names(code_analysis)
        testable_functions = [
            item["signature"]
            for item in code_analysis.get("functions") or []
            if item["name"] not in entrypoint_names
        ]
        classes = sorted((code_analysis.get("classes") or {}).keys())
        lines = ["Test targets:"]
        lines.append(f"- Functions to test: {', '.join(testable_functions or ['none'])}")
        lines.append(f"- Classes to test: {', '.join(classes or ['none'])}")
        lines.append(f"- Entry points to avoid in tests: {', '.join(sorted(entrypoint_names) or ['none'])}")
        return "\n".join(lines)

    def _build_code_behavior_contract(self, raw_content: str) -> str:
        if not raw_content.strip():
            return ""
        try:
            tree = ast.parse(raw_content)
        except SyntaxError:
            return ""

        validation_rules: dict[str, list[str]] = {}
        field_value_rules: dict[str, Dict[str, list[str]]] = {}
        batch_rules: list[str] = []
        function_map: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                function_nodes = [stmt for stmt in node.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_nodes = [node]
            else:
                continue

            for function_node in function_nodes:
                if not isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                function_map[function_node.name] = function_node
                required_fields = self._extract_required_fields(function_node)
                if required_fields:
                    validation_rules[function_node.name] = required_fields

        for function_name, function_node in function_map.items():
            if function_name in validation_rules:
                continue
            propagated_fields = self._extract_indirect_required_fields(function_node, validation_rules)
            if propagated_fields:
                validation_rules[function_name] = propagated_fields

        for function_name, function_node in function_map.items():
            lookup_rules = self._extract_lookup_field_rules(function_node)
            if lookup_rules:
                field_value_rules[function_name] = lookup_rules

        for function_node in function_map.values():
            batch_rule = self._extract_batch_rule(function_node, validation_rules)
            if batch_rule:
                batch_rules.append(batch_rule)

        if not validation_rules and not field_value_rules and not batch_rules:
            return ""

        lines = ["Behavior contract:"]
        for function_name in sorted(validation_rules):
            lines.append(
                f"- {function_name} requires fields: {', '.join(validation_rules[function_name])}"
            )
        for function_name in sorted(field_value_rules):
            for field_name in sorted(field_value_rules[function_name]):
                lines.append(
                    f"- {function_name} expects field `{field_name}` to be one of: {', '.join(field_value_rules[function_name][field_name])}"
                )
        for rule in batch_rules:
            lines.append(f"- {rule}")
        return "\n".join(lines)

    def _extract_required_fields(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        literal_fields: list[str] = []
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Assign):
                if not isinstance(stmt, ast.Compare):
                    continue
                field_name = self._comparison_required_field(stmt)
                if field_name and field_name not in literal_fields:
                    literal_fields.append(field_name)
                continue
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                continue
            if stmt.targets[0].id != "required_fields" or not isinstance(stmt.value, ast.List):
                continue
            fields: list[str] = []
            for element in stmt.value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    fields.append(element.value)
            if fields:
                return fields
        return literal_fields

    def _comparison_required_field(self, node: ast.Compare) -> str:
        if not node.ops or not isinstance(node.left, ast.Constant) or not isinstance(node.left.value, str):
            return ""
        comparator = node.comparators[0] if node.comparators else None
        if not isinstance(comparator, (ast.Name, ast.Attribute, ast.Subscript)):
            return ""
        if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            return ""
        return node.left.value

    def _extract_indirect_required_fields(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        validation_rules: Dict[str, list[str]],
    ) -> list[str]:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            callable_name = ""
            if isinstance(child.func, ast.Name):
                callable_name = child.func.id
            elif isinstance(child.func, ast.Attribute):
                callable_name = child.func.attr
            if callable_name in validation_rules:
                return list(validation_rules[callable_name])
        return []

    def _extract_lookup_field_rules(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, list[str]]:
        dict_key_sets: Dict[str, list[str]] = {}
        lookup_rules: Dict[str, list[str]] = {}

        for child in ast.walk(node):
            if isinstance(child, ast.Assign) and len(child.targets) == 1 and isinstance(child.targets[0], ast.Name):
                if not isinstance(child.value, ast.Dict):
                    continue
                literal_keys = [
                    key.value
                    for key in child.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                ]
                if literal_keys:
                    dict_key_sets[child.targets[0].id] = literal_keys

        for child in ast.walk(node):
            if not isinstance(child, ast.Subscript) or not isinstance(child.value, ast.Name):
                continue
            allowed_values = dict_key_sets.get(child.value.id)
            if not allowed_values:
                continue
            field_name = self._field_selector_name(child.slice)
            if not field_name:
                continue
            lookup_rules[field_name] = list(dict.fromkeys(allowed_values))

        return lookup_rules

    def _field_selector_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            return node.slice.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return ""

    def _extract_batch_rule(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        validation_rules: Dict[str, list[str]],
    ) -> str:
        if "batch" not in node.name:
            return ""
        for child in ast.walk(node):
            if not isinstance(child, ast.For) or not isinstance(child.target, ast.Name):
                continue
            iter_var = child.target.id
            for nested in ast.walk(child):
                if not isinstance(nested, ast.Call):
                    continue
                callable_name = ""
                if isinstance(nested.func, ast.Name):
                    callable_name = nested.func.id
                elif isinstance(nested.func, ast.Attribute):
                    callable_name = nested.func.attr
                if callable_name != "intake_request":
                    continue
                required_fields = validation_rules.get(callable_name) or []
                if len(nested.args) < 2:
                    continue
                payload_arg = nested.args[1]
                request_id_arg = nested.args[0]
                if isinstance(payload_arg, ast.Name) and payload_arg.id == iter_var:
                    batch_fields = list(required_fields)
                    if isinstance(request_id_arg, ast.Subscript) and isinstance(request_id_arg.slice, ast.Constant):
                        request_key = request_id_arg.slice.value
                        if isinstance(request_key, str):
                            batch_fields = [request_key, *batch_fields]
                    if batch_fields:
                        return (
                            f"{node.name} expects each batch item to include: {', '.join(dict.fromkeys(batch_fields))}"
                        )
                if (
                    isinstance(payload_arg, ast.Subscript)
                    and isinstance(payload_arg.value, ast.Name)
                    and payload_arg.value.id == iter_var
                    and isinstance(payload_arg.slice, ast.Constant)
                    and isinstance(payload_arg.slice.value, str)
                ):
                    wrapper_key = payload_arg.slice.value
                    batch_fields = list(required_fields)
                    if isinstance(request_id_arg, ast.Subscript) and isinstance(request_id_arg.slice, ast.Constant):
                        request_key = request_id_arg.slice.value
                        if isinstance(request_key, str):
                            return (
                                f"{node.name} expects each batch item to include key `{request_key}` and nested `{wrapper_key}` fields: {', '.join(batch_fields)}"
                            )
                    if batch_fields:
                        return (
                            f"{node.name} expects nested `{wrapper_key}` fields: {', '.join(batch_fields)}"
                        )
        return ""

    def _analyze_test_module(
        self,
        raw_content: str,
        module_name: str,
        code_analysis: Dict[str, Any],
        code_behavior_contract: str = "",
    ) -> Dict[str, Any]:
        analysis: Dict[str, Any] = {
            "syntax_ok": True,
            "syntax_error": None,
            "imported_module_symbols": [],
            "missing_function_imports": [],
            "unknown_module_symbols": [],
            "invalid_member_references": [],
            "constructor_arity_mismatches": [],
            "payload_contract_violations": [],
            "non_batch_sequence_calls": [],
            "undefined_fixtures": [],
            "imported_entrypoint_symbols": [],
            "unsafe_entrypoint_calls": [],
        }
        if not raw_content.strip():
            return analysis
        try:
            tree = ast.parse(raw_content)
        except SyntaxError as exc:
            analysis["syntax_ok"] = False
            analysis["syntax_error"] = f"{exc.msg} at line {exc.lineno}"
            return analysis

        module_symbols = set(code_analysis.get("symbols") or [])
        function_names = {item["name"] for item in code_analysis.get("functions") or []}
        class_map = code_analysis.get("classes") or {}
        entrypoint_names = self._entrypoint_function_names(code_analysis)
        validation_rules, field_value_rules, batch_rules = self._parse_behavior_contract(code_behavior_contract)

        imported_symbols: set[str] = set()
        called_names: list[tuple[str, int]] = []
        attribute_refs: list[tuple[str, str, int]] = []
        constructor_calls: list[tuple[str, int, int]] = []
        defined_fixtures: set[str] = set()
        referenced_fixtures: list[tuple[str, int]] = []
        unsafe_entrypoint_calls: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == module_name:
                for alias in node.names:
                    imported_symbols.add(alias.asname or alias.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._is_pytest_fixture(node):
                    defined_fixtures.add(node.name)
                if node.name.startswith("test_"):
                    for arg in node.args.args:
                        referenced_fixtures.append((arg.arg, node.lineno))
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.append((node.func.id, node.lineno))
                    if node.func.id in class_map:
                        constructor_calls.append((node.func.id, len(node.args) + len(node.keywords), node.lineno))
                    if node.func.id in imported_symbols and node.func.id in entrypoint_names:
                        unsafe_entrypoint_calls.append(f"{node.func.id}() (line {node.lineno})")
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    attribute_refs.append((node.func.value.id, node.func.attr, node.lineno))
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                attribute_refs.append((node.value.id, node.attr, node.lineno))

        missing_imports = sorted(
            {
                f"{name} (line {lineno})"
                for name, lineno in called_names
                if name in function_names and name not in imported_symbols
            }
        )
        unknown_symbols = sorted(symbol for symbol in imported_symbols if symbol not in module_symbols)

        invalid_member_refs: list[str] = []
        for owner, member, lineno in attribute_refs:
            if owner not in imported_symbols or owner not in class_map:
                continue
            class_info = class_map[owner]
            allowed = set(class_info.get("attributes") or [])
            if not class_info.get("is_enum"):
                allowed.update(class_info.get("fields") or [])
            if member not in allowed:
                invalid_member_refs.append(f"{owner}.{member} (line {lineno})")

        arity_mismatches: list[str] = []
        for class_name, actual_count, lineno in constructor_calls:
            expected_params = class_map.get(class_name, {}).get("constructor_params") or []
            expected_count = len(expected_params)
            if expected_count != actual_count:
                arity_mismatches.append(
                    f"{class_name} expects {expected_count} args but test uses {actual_count} at line {lineno}"
                )

        undefined_fixtures = sorted(
            {
                f"{fixture_name} (line {lineno})"
                for fixture_name, lineno in referenced_fixtures
                if fixture_name not in defined_fixtures and fixture_name not in _PYTEST_BUILTIN_FIXTURES
            }
        )
        imported_entrypoint_symbols = sorted(symbol for symbol in imported_symbols if symbol in entrypoint_names)
        payload_contract_violations, non_batch_sequence_calls = self._analyze_test_behavior_contracts(
            tree,
            validation_rules,
            field_value_rules,
            batch_rules,
            function_names,
            class_map,
        )

        analysis["imported_module_symbols"] = sorted(imported_symbols)
        analysis["missing_function_imports"] = missing_imports
        analysis["unknown_module_symbols"] = unknown_symbols
        analysis["invalid_member_references"] = sorted(set(invalid_member_refs))
        analysis["constructor_arity_mismatches"] = sorted(set(arity_mismatches))
        analysis["payload_contract_violations"] = payload_contract_violations
        analysis["non_batch_sequence_calls"] = non_batch_sequence_calls
        analysis["undefined_fixtures"] = undefined_fixtures
        analysis["imported_entrypoint_symbols"] = imported_entrypoint_symbols
        analysis["unsafe_entrypoint_calls"] = sorted(set(unsafe_entrypoint_calls))
        return analysis

    def _parse_behavior_contract(
        self,
        contract: str,
    ) -> tuple[Dict[str, list[str]], Dict[str, Dict[str, list[str]]], Dict[str, Dict[str, Any]]]:
        validation_rules: Dict[str, list[str]] = {}
        field_value_rules: Dict[str, Dict[str, list[str]]] = {}
        batch_rules: Dict[str, Dict[str, Any]] = {}
        if not contract.strip():
            return validation_rules, field_value_rules, batch_rules

        for raw_line in contract.splitlines():
            line = raw_line.strip()
            if not line.startswith("- "):
                continue
            validation_match = re.match(r"-\s+(\w+) requires fields: (.+)$", line)
            if validation_match:
                function_name = validation_match.group(1)
                fields = [field.strip() for field in validation_match.group(2).split(",") if field.strip()]
                if fields:
                    validation_rules[function_name] = fields
                continue

            field_value_match = re.match(r"-\s+(\w+) expects field `([^`]+)` to be one of: (.+)$", line)
            if field_value_match:
                function_name = field_value_match.group(1)
                field_name = field_value_match.group(2)
                values = [value.strip() for value in field_value_match.group(3).split(",") if value.strip()]
                if values:
                    field_value_rules.setdefault(function_name, {})[field_name] = values
                continue

            nested_match = re.match(
                r"-\s+(\w+) expects each batch item to include key `([^`]+)` and nested `([^`]+)` fields: (.+)$",
                line,
            )
            if nested_match:
                batch_rules[nested_match.group(1)] = {
                    "request_key": nested_match.group(2),
                    "wrapper_key": nested_match.group(3),
                    "fields": [field.strip() for field in nested_match.group(4).split(",") if field.strip()],
                }
                continue

            direct_match = re.match(r"-\s+(\w+) expects each batch item to include: (.+)$", line)
            if direct_match:
                batch_rules[direct_match.group(1)] = {
                    "request_key": None,
                    "wrapper_key": None,
                    "fields": [field.strip() for field in direct_match.group(2).split(",") if field.strip()],
                }
                continue

            wrapper_match = re.match(r"-\s+(\w+) expects nested `([^`]+)` fields: (.+)$", line)
            if wrapper_match:
                batch_rules[wrapper_match.group(1)] = {
                    "request_key": None,
                    "wrapper_key": wrapper_match.group(2),
                    "fields": [field.strip() for field in wrapper_match.group(3).split(",") if field.strip()],
                }

        return validation_rules, field_value_rules, batch_rules

    def _analyze_test_behavior_contracts(
        self,
        tree: ast.AST,
        validation_rules: Dict[str, list[str]],
        field_value_rules: Dict[str, Dict[str, list[str]]],
        batch_rules: Dict[str, Dict[str, Any]],
        function_names: set[str],
        class_map: Dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        payload_violations: set[str] = set()
        non_batch_calls: set[str] = set()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue

            bindings = self._collect_local_bindings(node)
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                callable_name = self._callable_name(child)
                if not callable_name:
                    continue

                if callable_name in validation_rules:
                    payload_arg = self._payload_argument_for_validation(child, callable_name)
                    payload_node = self._resolve_bound_value(payload_arg, bindings)
                    payload_keys = self._extract_literal_dict_keys(payload_node, bindings, class_map)
                    if payload_keys is not None:
                        missing_fields = [field for field in validation_rules[callable_name] if field not in payload_keys]
                        if missing_fields:
                            payload_violations.add(
                                f"{callable_name} payload missing required fields: {', '.join(missing_fields)} at line {child.lineno}"
                            )

                if callable_name in field_value_rules:
                    payload_arg = self._payload_argument_for_validation(child, callable_name)
                    payload_node = self._resolve_bound_value(payload_arg, bindings)
                    for field_name, allowed_values in field_value_rules[callable_name].items():
                        observed_values = self._extract_literal_field_values(payload_node, bindings, field_name, class_map)
                        invalid_values = [value for value in observed_values if value not in allowed_values]
                        if invalid_values:
                            payload_violations.add(
                                f"{callable_name} field `{field_name}` uses unsupported values: {', '.join(invalid_values)} at line {child.lineno}"
                            )

                if callable_name in batch_rules:
                    batch_violations = self._validate_batch_call(child, bindings, callable_name, batch_rules[callable_name])
                    payload_violations.update(batch_violations)
                    continue

                if callable_name in function_names and "batch" not in callable_name:
                    sequence_arg = self._first_call_argument(child)
                    sequence_node = self._resolve_bound_value(sequence_arg, bindings)
                    if isinstance(sequence_node, ast.List):
                        non_batch_calls.add(
                            f"{callable_name} does not accept batch/list inputs at line {child.lineno}"
                        )

        return sorted(payload_violations), sorted(non_batch_calls)

    def _collect_local_bindings(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, ast.AST]:
        bindings: Dict[str, ast.AST] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                bindings[stmt.targets[0].id] = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
                bindings[stmt.target.id] = stmt.value
        return bindings

    def _callable_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""

    def _first_call_argument(self, node: ast.Call) -> Optional[ast.AST]:
        if node.args:
            return node.args[0]
        if node.keywords:
            return node.keywords[0].value
        return None

    def _payload_argument_for_validation(self, node: ast.Call, callable_name: str) -> Optional[ast.AST]:
        if callable_name == "validate_request":
            return self._first_call_argument(node)
        if len(node.args) >= 2:
            return node.args[1]
        if node.keywords:
            for keyword in node.keywords:
                if keyword.arg in {"data", "payload", "request", "item"}:
                    return keyword.value
        return self._first_call_argument(node)

    def _resolve_bound_value(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        *,
        max_depth: int = 3,
    ) -> Optional[ast.AST]:
        current = node
        depth = 0
        while isinstance(current, ast.Name) and depth < max_depth:
            current = bindings.get(current.id, current)
            depth += 1
        return current

    def _extract_literal_dict_keys(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        class_map: Optional[Dict[str, Any]] = None,
    ) -> Optional[set[str]]:
        resolved = self._resolve_bound_value(node, bindings)
        if isinstance(resolved, ast.Dict):
            keys = {
                key.value
                for key in resolved.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            return keys
        if (
            isinstance(resolved, ast.Subscript)
            and isinstance(resolved.value, ast.Name)
            and isinstance(resolved.slice, ast.Constant)
            and isinstance(resolved.slice.value, str)
        ):
            source = self._resolve_bound_value(resolved.value, bindings)
            if isinstance(source, ast.Dict):
                for key_node, value_node in zip(source.keys, source.values):
                    if (
                        isinstance(key_node, ast.Constant)
                        and key_node.value == resolved.slice.value
                    ):
                        return self._extract_literal_dict_keys(value_node, bindings, class_map)
        if isinstance(resolved, ast.Call):
            for candidate_name in ("data", "payload", "request", "item"):
                candidate_value = self._call_argument_value(resolved, candidate_name, class_map or {})
                nested_keys = self._extract_literal_dict_keys(candidate_value, bindings, class_map)
                if nested_keys is not None:
                    return nested_keys
        return None

    def _extract_literal_field_values(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
        field_name: str,
        class_map: Dict[str, Any],
    ) -> list[str]:
        resolved = self._resolve_bound_value(node, bindings)
        if isinstance(resolved, ast.Dict):
            for key_node, value_node in zip(resolved.keys, resolved.values):
                if isinstance(key_node, ast.Constant) and key_node.value == field_name:
                    return self._extract_string_literals(value_node, bindings)
            return []
        if isinstance(resolved, ast.Call):
            direct_value = self._call_argument_value(resolved, field_name, class_map)
            if direct_value is not None:
                return self._extract_string_literals(direct_value, bindings)
            nested_payload = self._call_argument_value(resolved, "data", class_map)
            if nested_payload is not None:
                return self._extract_literal_field_values(nested_payload, bindings, field_name, class_map)
        return []

    def _extract_string_literals(self, node: Optional[ast.AST], bindings: Dict[str, ast.AST]) -> list[str]:
        resolved = self._resolve_bound_value(node, bindings)
        if isinstance(resolved, ast.Constant) and isinstance(resolved.value, str):
            return [resolved.value]
        return []

    def _call_argument_value(
        self,
        node: ast.Call,
        argument_name: str,
        class_map: Dict[str, Any],
    ) -> Optional[ast.AST]:
        for keyword in node.keywords:
            if keyword.arg == argument_name:
                return keyword.value
        if not isinstance(node.func, ast.Name):
            return None
        constructor_params = class_map.get(node.func.id, {}).get("constructor_params") or []
        if argument_name not in constructor_params:
            return None
        argument_index = constructor_params.index(argument_name)
        if argument_index < len(node.args):
            return node.args[argument_index]
        return None

    def _extract_literal_list_items(
        self,
        node: Optional[ast.AST],
        bindings: Dict[str, ast.AST],
    ) -> Optional[list[ast.AST]]:
        resolved = self._resolve_bound_value(node, bindings)
        if isinstance(resolved, ast.List):
            return list(resolved.elts)
        return None

    def _validate_batch_call(
        self,
        node: ast.Call,
        bindings: Dict[str, ast.AST],
        callable_name: str,
        batch_rule: Dict[str, Any],
    ) -> list[str]:
        violations: list[str] = []
        batch_arg = self._first_call_argument(node)
        batch_items = self._extract_literal_list_items(batch_arg, bindings)
        if batch_items is None:
            return violations

        required_fields = batch_rule.get("fields") or []
        request_key = batch_rule.get("request_key")
        wrapper_key = batch_rule.get("wrapper_key")
        for item in batch_items:
            resolved_item = self._resolve_bound_value(item, bindings)
            if not isinstance(resolved_item, ast.Dict):
                violations.append(
                    f"{callable_name} expects dict-like batch items, but test uses {type(resolved_item).__name__} at line {getattr(item, 'lineno', node.lineno)}"
                )
                continue

            item_keys = self._extract_literal_dict_keys(resolved_item, bindings) or set()
            if request_key and request_key not in item_keys:
                violations.append(
                    f"{callable_name} batch item missing required key: {request_key} at line {getattr(item, 'lineno', node.lineno)}"
                )
            if wrapper_key:
                nested_keys = self._extract_literal_dict_keys(
                    ast.Subscript(value=resolved_item, slice=ast.Constant(value=wrapper_key)),
                    bindings,
                )
                if nested_keys is None:
                    violations.append(
                        f"{callable_name} batch item missing nested payload `{wrapper_key}` at line {getattr(item, 'lineno', node.lineno)}"
                    )
                    continue
                missing_nested_fields = [field for field in required_fields if field not in nested_keys]
                if missing_nested_fields:
                    violations.append(
                        f"{callable_name} batch item nested `{wrapper_key}` missing required fields: {', '.join(missing_nested_fields)} at line {getattr(item, 'lineno', node.lineno)}"
                    )
                continue

            missing_fields = [field for field in required_fields if field not in item_keys]
            if missing_fields:
                violations.append(
                    f"{callable_name} batch item missing required fields: {', '.join(missing_fields)} at line {getattr(item, 'lineno', node.lineno)}"
                )

        return violations

    def _is_pytest_fixture(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "fixture":
                return True
            if isinstance(decorator, ast.Attribute) and decorator.attr == "fixture":
                return True
            if isinstance(decorator, ast.Call):
                func = decorator.func
                if isinstance(func, ast.Name) and func.id == "fixture":
                    return True
                if isinstance(func, ast.Attribute) and func.attr == "fixture":
                    return True
        return False

    def _build_test_validation_summary(
        self,
        test_analysis: Dict[str, Any],
        test_execution: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not test_analysis.get("syntax_ok", True):
            return f"Test syntax error: {test_analysis.get('syntax_error') or 'unknown syntax error'}"

        lines = ["Generated test validation:"]
        lines.append(
            f"- Imported module symbols: {', '.join(test_analysis.get('imported_module_symbols') or ['none'])}"
        )
        lines.append(
            f"- Missing function imports: {', '.join(test_analysis.get('missing_function_imports') or ['none'])}"
        )
        lines.append(
            f"- Unknown module symbols: {', '.join(test_analysis.get('unknown_module_symbols') or ['none'])}"
        )
        lines.append(
            f"- Invalid member references: {', '.join(test_analysis.get('invalid_member_references') or ['none'])}"
        )
        lines.append(
            f"- Constructor arity mismatches: {', '.join(test_analysis.get('constructor_arity_mismatches') or ['none'])}"
        )
        lines.append(
            f"- Payload contract violations: {', '.join(test_analysis.get('payload_contract_violations') or ['none'])}"
        )
        lines.append(
            f"- Non-batch sequence calls: {', '.join(test_analysis.get('non_batch_sequence_calls') or ['none'])}"
        )
        lines.append(
            f"- Undefined test fixtures: {', '.join(test_analysis.get('undefined_fixtures') or ['none'])}"
        )
        lines.append(
            f"- Imported entrypoint symbols: {', '.join(test_analysis.get('imported_entrypoint_symbols') or ['none'])}"
        )
        lines.append(
            f"- Unsafe entrypoint calls: {', '.join(test_analysis.get('unsafe_entrypoint_calls') or ['none'])}"
        )
        if isinstance(test_execution, dict):
            if not test_execution.get("available", True):
                lines.append(f"- Pytest execution: unavailable ({test_execution.get('summary') or 'pytest unavailable'})")
            elif test_execution.get("ran"):
                lines.append(
                    f"- Pytest execution: {'PASS' if test_execution.get('returncode') == 0 else 'FAIL'}"
                )
                lines.append(f"- Pytest summary: {test_execution.get('summary') or 'none'}")

        has_static_issues = any(
            test_analysis.get(key)
            for key in (
                "missing_function_imports",
                "unknown_module_symbols",
                "invalid_member_references",
                "constructor_arity_mismatches",
                "payload_contract_violations",
                "non_batch_sequence_calls",
                "undefined_fixtures",
                "imported_entrypoint_symbols",
                "unsafe_entrypoint_calls",
            )
        )
        execution_failed = isinstance(test_execution, dict) and test_execution.get("ran") and test_execution.get("returncode") not in (None, 0)
        lines.append(f"- Verdict: {'FAIL' if has_static_issues or execution_failed else 'PASS'}")
        return "\n".join(lines)

    def _ast_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._ast_name(node.value)}.{node.attr}"
        return ""

    def _build_agent_input(self, task: Task, project: ProjectState) -> AgentInput:
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        task_description = task.description
        if repair_context:
            repair_lines = [task.description, "", "Repair objective:", str(repair_context.get("instruction") or "Repair the previous failure."), "", f"Previous failure category: {repair_context.get('failure_category') or FailureCategory.UNKNOWN.value}"]
            failure_message = repair_context.get("failure_message")
            if isinstance(failure_message, str) and failure_message.strip():
                repair_lines.append(f"Previous failure message: {failure_message}")
            validation_summary = repair_context.get("validation_summary")
            if isinstance(validation_summary, str) and validation_summary.strip():
                repair_lines.extend(["", "Validation summary:", validation_summary])
            task_description = "\n".join(repair_lines)
        return AgentInput(
            task_id=task.id,
            task_title=task.title,
            task_description=task_description,
            project_name=project.project_name,
            project_goal=project.goal,
            context=self._build_context(task, project),
        )

    def _execute_agent(self, agent: Any, agent_input: AgentInput) -> Any:
        if hasattr(agent, "execute"):
            return agent.execute(agent_input)
        if hasattr(agent, "run_with_input"):
            return agent.run_with_input(agent_input)
        return agent.run(agent_input.task_description, agent_input.context)

    def _normalize_agent_result(self, result: Any) -> AgentOutput:
        if isinstance(result, AgentOutput):
            return result
        return AgentOutput(summary=self._summarize_output(result), raw_content=result)

    def _summarize_output(self, raw_content: str) -> str:
        stripped = raw_content.strip()
        if not stripped:
            return ""
        return stripped.splitlines()[0].strip()[:120]

    def _semantic_output_key(self, task: Task) -> Optional[str]:
        role_key = AgentRegistry.normalize_key(task.assigned_to)
        semantic_map = {
            "architect": "architecture",
            "code_engineer": "code",
            "dependency_manager": "dependencies",
            "code_reviewer": "review",
            "qa_tester": "tests",
            "docs_writer": "documentation",
            "legal_advisor": "legal",
        }
        if role_key in semantic_map:
            return semantic_map[role_key]
        title_key = task.title.lower().replace(" ", "_")
        if "architect" in title_key or "architecture" in title_key:
            return "architecture"
        if "review" in title_key:
            return "review"
        if "test" in title_key:
            return "tests"
        if "depend" in title_key or "requirement" in title_key or "package" in title_key:
            return "dependencies"
        if "doc" in title_key:
            return "documentation"
        if "legal" in title_key or "license" in title_key:
            return "legal"
        return None

    def _validate_agent_resolution(self, project: ProjectState) -> None:
        for task in project.tasks:
            if not self.registry.has(task.assigned_to):
                raise AgentExecutionError(
                    f"Task '{task.id}' is assigned to unknown agent '{task.assigned_to}'"
                )

    def _evaluate_workflow_acceptance(self, project: ProjectState) -> Dict[str, Any]:
        policy = self.config.workflow_acceptance_policy
        if policy == "required_tasks":
            evaluated_tasks = [task for task in project.tasks if task.required_for_acceptance]
            if not evaluated_tasks:
                return {
                    "policy": policy,
                    "accepted": False,
                    "reason": "no_required_tasks",
                    "evaluated_task_ids": [],
                    "required_task_ids": [],
                    "completed_task_ids": [],
                    "failed_task_ids": [],
                    "skipped_task_ids": [],
                    "pending_task_ids": [],
                }
        else:
            evaluated_tasks = list(project.tasks)

        completed_task_ids = [task.id for task in evaluated_tasks if task.status == TaskStatus.DONE.value]
        failed_task_ids = [task.id for task in evaluated_tasks if task.status == TaskStatus.FAILED.value]
        skipped_task_ids = [task.id for task in evaluated_tasks if task.status == TaskStatus.SKIPPED.value]
        pending_task_ids = [
            task.id
            for task in evaluated_tasks
            if task.status not in {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.SKIPPED.value}
        ]
        accepted = bool(evaluated_tasks) and len(completed_task_ids) == len(evaluated_tasks)
        return {
            "policy": policy,
            "accepted": accepted,
            "reason": "all_evaluated_tasks_done" if accepted else "evaluated_tasks_incomplete",
            "evaluated_task_ids": [task.id for task in evaluated_tasks],
            "required_task_ids": [task.id for task in project.tasks if task.required_for_acceptance],
            "completed_task_ids": completed_task_ids,
            "failed_task_ids": failed_task_ids,
            "skipped_task_ids": skipped_task_ids,
            "pending_task_ids": pending_task_ids,
        }

    def execute_workflow(self, project: ProjectState):
        """Execute the full workflow until completion or an unrecoverable failure."""
        project.execution_plan()
        self._validate_agent_resolution(project)
        project.repair_max_cycles = self.config.workflow_max_repair_cycles
        self._log_event("info", "workflow_started", project_name=project.project_name, phase=project.phase)
        resumed_task_ids = project.resume_interrupted_tasks()
        failed_task_ids = self._failed_task_ids_for_repair(project)
        if self.config.workflow_resume_policy == "resume_failed":
            if failed_task_ids:
                if not project.can_start_repair_cycle():
                    acceptance_evaluation = self._evaluate_workflow_acceptance(project)
                    project.mark_workflow_finished(
                        "failed",
                        acceptance_policy=self.config.workflow_acceptance_policy,
                        terminal_outcome=WorkflowOutcome.FAILED.value,
                        failure_category=FailureCategory.REPAIR_BUDGET_EXHAUSTED.value,
                        acceptance_criteria_met=False,
                        acceptance_evaluation=acceptance_evaluation,
                    )
                    project.save()
                    self._log_event(
                        "error",
                        "workflow_repair_budget_exhausted",
                        project_name=project.project_name,
                        failed_task_ids=list(failed_task_ids),
                        repair_cycle_count=project.repair_cycle_count,
                        repair_max_cycles=project.repair_max_cycles,
                    )
                    raise AgentExecutionError(
                        "Workflow repair budget exhausted before resuming failed tasks"
                    )
                failure_categories = {
                    task.last_error_category or FailureCategory.UNKNOWN.value
                    for task in project.tasks
                    if task.id in failed_task_ids
                }
                project.start_repair_cycle(
                    reason="resume_failed_tasks",
                    failure_category=(
                        next(iter(failure_categories)) if len(failure_categories) == 1 else FailureCategory.UNKNOWN.value
                    ),
                    failed_task_ids=failed_task_ids,
                )
                self._configure_repair_attempts(project, failed_task_ids, project.repair_history[-1])
                repair_task_ids = self._repair_task_ids_for_cycle(project, failed_task_ids)
                resumed_task_ids.extend(repair_task_ids)
                resumed_task_ids.extend(
                    project.resume_failed_tasks(
                        include_failed_tasks=False,
                        failed_task_ids=failed_task_ids,
                        additional_task_ids=repair_task_ids,
                    )
                )
        if resumed_task_ids:
            self._log_event("info", "workflow_resumed", project_name=project.project_name, task_ids=list(resumed_task_ids))
            project.save()
        project.mark_workflow_running(
            acceptance_policy=self.config.workflow_acceptance_policy,
            repair_max_cycles=self.config.workflow_max_repair_cycles,
        )
        while True:
            pending = project.pending_tasks()
            if not pending:
                acceptance_evaluation = self._evaluate_workflow_acceptance(project)
                acceptance_criteria_met = bool(acceptance_evaluation["accepted"])
                project.mark_workflow_finished(
                    "completed",
                    acceptance_policy=self.config.workflow_acceptance_policy,
                    terminal_outcome=(
                        WorkflowOutcome.COMPLETED.value
                        if acceptance_criteria_met
                        else WorkflowOutcome.DEGRADED.value
                    ),
                    acceptance_criteria_met=acceptance_criteria_met,
                    acceptance_evaluation=acceptance_evaluation,
                )
                project.save()
                self._log_event("info", "workflow_completed", project_name=project.project_name, phase=project.phase)
                break
            try:
                runnable = project.runnable_tasks()
            except WorkflowDefinitionError:
                project.mark_workflow_finished(
                    "failed",
                    acceptance_policy=self.config.workflow_acceptance_policy,
                    terminal_outcome=WorkflowOutcome.FAILED.value,
                    failure_category=FailureCategory.WORKFLOW_DEFINITION.value,
                    acceptance_criteria_met=False,
                    acceptance_evaluation=self._evaluate_workflow_acceptance(project),
                )
                project.save()
                self._log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)
                raise
            if not runnable:
                blocked_task_ids = ", ".join(task.id for task in project.blocked_tasks())
                project.mark_workflow_finished(
                    "failed",
                    acceptance_policy=self.config.workflow_acceptance_policy,
                    terminal_outcome=WorkflowOutcome.FAILED.value,
                    failure_category=FailureCategory.WORKFLOW_BLOCKED.value,
                    acceptance_criteria_met=False,
                    acceptance_evaluation=self._evaluate_workflow_acceptance(project),
                )
                project.save()
                self._log_event(
                    "error",
                    "workflow_blocked",
                    project_name=project.project_name,
                    phase=project.phase,
                    blocked_task_ids=blocked_task_ids,
                )
                raise AgentExecutionError(
                    f"Workflow is blocked because pending tasks have unsatisfied dependencies: {blocked_task_ids}"
                )
            for task in runnable:
                try:
                    self.run_task(task, project)
                except Exception as exc:
                    if project.should_retry_task(task.id):
                        project.save()
                        continue
                    if self._queue_active_cycle_repair(project, task):
                        project.save()
                        continue
                    project.save()
                    if self.config.workflow_failure_policy == "continue":
                        skipped = project.skip_dependent_tasks(
                            task.id,
                            f"Skipped because dependency '{task.id}' failed",
                        )
                        if skipped:
                            self._log_event(
                                "warning",
                                "dependent_tasks_skipped",
                                project_name=project.project_name,
                                task_id=task.id,
                                skipped_task_ids=list(skipped),
                            )
                        continue
                    project.mark_workflow_finished(
                        "failed",
                        acceptance_policy=self.config.workflow_acceptance_policy,
                        terminal_outcome=WorkflowOutcome.FAILED.value,
                        failure_category=self._classify_task_failure(task, exc),
                        acceptance_criteria_met=False,
                        acceptance_evaluation=self._evaluate_workflow_acceptance(project),
                    )
                    project.save()
                    self._log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)
                    raise
                project.save()
        self._log_event("info", "workflow_finished", project_name=project.project_name, phase=project.phase)
