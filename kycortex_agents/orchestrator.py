import ast
import copy
import builtins
import importlib.util
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import tokenize
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Any, Optional, cast

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None  # type: ignore[assignment]

from kycortex_agents.agents.dependency_manager import extract_requirement_name, is_provenance_unsafe_requirement
from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.agents.registry import AgentRegistry, build_default_registry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.providers.base import (
    redact_sensitive_data,
    redact_sensitive_text,
    sanitize_provider_call_metadata,
)
from kycortex_agents.types import (
    AgentView,
    AgentViewArtifactRecord,
    AgentViewDecisionRecord,
    AgentViewTaskResult,
    AgentInput,
    AgentOutput,
    ArtifactRecord,
    ArtifactType,
    ExecutionSandboxPolicy,
    FailureCategory,
    ProjectSnapshot,
    TaskStatus,
    TaskResult,
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
_LINE_BUDGET_PATTERNS = (
    re.compile(r"\bunder\s+(\d+)\s+lines?\b"),
    re.compile(r"\bwithin\s+(\d+)\s+lines?\b"),
    re.compile(r"\bat\s+most\s+(\d+)\s+lines?\b"),
    re.compile(r"\bno\s+more\s+than\s+(\d+)\s+lines?\b"),
)
_EXACT_TEST_COUNT_PATTERN = re.compile(r"\bexactly\s+(\d+)\s+top-level\s+test\s+functions?\b")
_MAX_TEST_COUNT_PATTERN = re.compile(r"\bat\s+most\s+(\d+)\s+top-level\s+test\s+functions?\b")
_FIXTURE_BUDGET_PATTERN = re.compile(r"\bat\s+most\s+(\d+)\s+fixtures?\b")
_LIKELY_TRUNCATED_SYNTAX_MARKERS = (
    "was never closed",
    "unexpected eof while parsing",
    "unterminated string literal",
    "unterminated triple-quoted string literal",
    "eof while scanning triple-quoted string literal",
    "eol while scanning string literal",
    "expected an indented block",
)
_LIKELY_TRUNCATED_TAIL_SUFFIXES = (
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
_MOCK_ASSERTION_ATTRIBUTES = {"call_count"}
_MOCK_ASSERTION_METHODS = {
    "assert_any_call",
    "assert_called",
    "assert_called_once",
    "assert_called_once_with",
    "assert_called_with",
    "assert_has_calls",
    "assert_not_called",
}


def _harden_private_file_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        path.chmod(0o600)
    except OSError as exc:
        raise AgentExecutionError(
            f"Artifact persistence failed: could not harden file permissions for {path.name}"
        ) from exc


def _harden_private_directory_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        path.chmod(0o700)
    except OSError as exc:
        raise AgentExecutionError(
            f"Artifact persistence failed: could not harden directory permissions for {path.name}"
        ) from exc
_RESERVED_FIXTURE_NAMES = {"request"}


class _AstNameReplacer(ast.NodeTransformer):
    def __init__(self, replacements: Dict[str, ast.expr]):
        self._replacements = replacements

    def visit_Name(self, node: ast.Name) -> ast.AST:
        replacement = self._replacements.get(node.id)
        if replacement is None:
            return node
        return ast.copy_location(copy.deepcopy(replacement), node)

_SANDBOX_SITECUSTOMIZE = """
import asyncio
import builtins
import ctypes
import ctypes.util
import glob
import io
import mmap
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
_REAL_OS_READLINK = getattr(os, "readlink", None)
_REAL_OS_PATH_ISABS = os.path.isabs
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
    _saved_os_readlink = getattr(os, "readlink", None)
    _saved_os_path_isabs = os.path.isabs
    _saved_os_path_realpath = os.path.realpath
    _saved_path_stats = {}
    try:
        os.stat = _REAL_OS_STAT
        if _REAL_OS_LSTAT is not None:
            os.lstat = _REAL_OS_LSTAT
        if _REAL_OS_READLINK is not None:
            os.readlink = _REAL_OS_READLINK
        os.path.isabs = _REAL_OS_PATH_ISABS
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
        if _REAL_OS_READLINK is not None and _saved_os_readlink is not None:
            os.readlink = _saved_os_readlink
        os.path.isabs = _saved_os_path_isabs
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
    if isinstance(file, int):
        _blocked()
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
    "chdir",
    "chown",
    "lchown",
    "makedirs",
    "mkdir",
    "mkfifo",
    "mknod",
    "remove",
    "removedirs",
    "removexattr",
    "rmdir",
    "setxattr",
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


for _name in ("getxattr", "listxattr"):
    if hasattr(os, _name):
        _real = getattr(os, _name)

        def _guarded_xattr_read_path(*args, __real=_real, **kwargs):
            if args:
                _ensure_metadata_read_within_policy(args[0])
            return __real(*args, **kwargs)

        setattr(os, _name, _guarded_xattr_read_path)


if hasattr(os, "readlink"):
    _real = os.readlink

    def _guarded_os_readlink(path, *args, __real=_real, **kwargs):
        _ensure_metadata_read_within_policy(path)
        return __real(path, *args, **kwargs)

    os.readlink = _guarded_os_readlink


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
    "isabs",
    "isdir",
    "isfile",
    "isjunction",
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
        "is_junction",
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


for _name in ("CDLL", "OleDLL", "PyDLL", "WinDLL"):
    if hasattr(ctypes, _name):
        setattr(ctypes, _name, _blocked)


for _loader_name in ("cdll", "oledll", "pydll", "windll"):
    if hasattr(ctypes, _loader_name):
        _loader = getattr(ctypes, _loader_name)
        if hasattr(_loader, "LoadLibrary"):
            _loader.LoadLibrary = _blocked


if hasattr(ctypes.util, "find_library"):
    ctypes.util.find_library = _blocked


if hasattr(mmap, "mmap"):
    mmap.mmap = _blocked


for _name in ("dup", "dup2"):
    if hasattr(os, _name):
        setattr(os, _name, _blocked)


if os.environ.get("KYCORTEX_SANDBOX_ALLOW_NETWORK") != "1":
    socket.socket = _blocked
    socket.create_connection = _blocked
    for _name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "getnameinfo", "gethostbyaddr"):
        if hasattr(socket, _name):
            setattr(socket, _name, _blocked)


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

pytest_args = [
    "-c",
    {pytest_config_path},
    "--rootdir",
    {rootdir_path},
    "-o",
    {pytest_log_option},
    {test_filename},
    "-q",
]

if {sandbox_enabled}:
    pytest_args.extend(["--capture=sys", "-p", "no:faulthandler"])

raise SystemExit(
    pytest.main(pytest_args)
)
"""

_GENERATED_IMPORT_RUNNER = """
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

module_spec = importlib.util.spec_from_file_location(
    "code_under_test",
    TMP_PATH / {module_filename},
)
if module_spec is None or module_spec.loader is None:
    raise RuntimeError("module import failed: missing module loader")

module = importlib.util.module_from_spec(module_spec)
sys.modules[module_spec.name] = module
module_spec.loader.exec_module(module)
"""


_GENERIC_SECRET_ENV_TOKENS = {
    "CREDENTIAL",
    "CREDENTIALS",
    "PASSWORD",
    "PASSWD",
    "SECRET",
    "SECRETS",
    "TOKEN",
}

_GENERIC_SECRET_ENV_TOKEN_PAIRS = {
    frozenset({"ACCESS", "KEY"}),
    frozenset({"API", "KEY"}),
    frozenset({"AUTH", "TOKEN"}),
    frozenset({"CLIENT", "SECRET"}),
    frozenset({"PRIVATE", "KEY"}),
    frozenset({"SESSION", "TOKEN"}),
}


def _looks_like_secret_env_var(env_name: str) -> bool:
    tokens = {token for token in re.split(r"[^A-Za-z0-9]+", env_name.upper()) if token}
    if not tokens:
        return False
    if _GENERIC_SECRET_ENV_TOKENS & tokens:
        return True
    return any(token_pair.issubset(tokens) for token_pair in _GENERIC_SECRET_ENV_TOKEN_PAIRS)


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
        safe_fields = cast(Dict[str, Any], redact_sensitive_data(self._privacy_safe_log_fields(fields)))
        log_method(event, extra={"event": event, **safe_fields})

    @staticmethod
    def _privacy_safe_log_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
        safe_fields: Dict[str, Any] = {}
        for field_name, value in fields.items():
            minimized_field_name = Orchestrator._task_id_count_log_field_name(field_name)
            if minimized_field_name is not None:
                count = Orchestrator._task_id_collection_count(value)
                if count is not None:
                    safe_fields[minimized_field_name] = count
                    continue
            safe_fields[field_name] = value
        return safe_fields

    @staticmethod
    def _task_id_collection_count(value: Any) -> Optional[int]:
        if isinstance(value, (list, tuple, set)):
            return len(value)
        if isinstance(value, str):
            return 1 if value else 0
        if value is None:
            return 0
        return None

    @staticmethod
    def _task_id_count_log_field_name(field_name: str) -> Optional[str]:
        if field_name == "task_ids" or field_name.endswith("_task_ids"):
            return f"{field_name[:-len('_ids')]}_count"
        return None

    def _emit_workflow_progress(self, project: ProjectState, *, task: Optional[Task] = None) -> None:
        workflow_telemetry = project.record_workflow_progress(
            task_id=task.id if task is not None else None,
            task_status=task.status if task is not None else None,
        )
        self._log_event(
            "info",
            "workflow_progress",
            project_name=project.project_name,
            phase=project.phase,
            task_id=task.id if task is not None else None,
            task_status=task.status if task is not None else None,
            workflow_telemetry=workflow_telemetry,
        )

    def pause_workflow(self, project: ProjectState, *, reason: str) -> bool:
        """Pause a workflow so the orchestrator stops dispatching new runnable tasks."""

        changed = project.pause_workflow(reason=reason)
        if changed:
            project.save()
            self._log_event(
                "info",
                "workflow_paused",
                project_name=project.project_name,
                phase=project.phase,
                reason=project.workflow_pause_reason,
            )
        return changed

    def resume_workflow(self, project: ProjectState, *, reason: str = "paused_workflow") -> bool:
        """Resume a paused workflow so execution can continue on the next run."""

        changed = project.resume_workflow(reason=reason)
        if changed:
            project.save()
            self._log_event(
                "info",
                "workflow_resumed",
                project_name=project.project_name,
                phase=project.phase,
                reason=reason,
            )
        return changed

    def cancel_workflow(self, project: ProjectState, *, reason: str = "manual_cancel") -> list[str]:
        """Cancel a workflow through the orchestrator control surface."""

        was_cancelled = project.is_workflow_cancelled()
        cancelled_task_ids = project.cancel_workflow(reason=reason)
        if not was_cancelled and project.is_workflow_cancelled():
            project.save()
            self._log_event(
                "warning",
                "workflow_cancelled",
                project_name=project.project_name,
                phase=project.phase,
                reason=reason,
                cancelled_task_ids=list(cancelled_task_ids),
            )
        return cancelled_task_ids

    def skip_task(self, project: ProjectState, task_id: str, *, reason: str) -> bool:
        """Skip a task manually through the orchestrator control surface."""

        task = project.get_task(task_id)
        if task is None:
            return False
        project.skip_task(task_id, reason, reason_type="manual")
        project.save()
        self._log_event(
            "info",
            "task_skipped",
            project_name=project.project_name,
            task_id=task_id,
            phase=project.phase,
            reason=reason,
        )
        return True

    def override_task(self, project: ProjectState, task_id: str, output: str | AgentOutput, *, reason: str) -> bool:
        """Complete a task manually through the orchestrator control surface."""

        changed = project.override_task(task_id, output, reason=reason)
        if changed:
            project.save()
            self._log_event(
                "info",
                "task_overridden",
                project_name=project.project_name,
                task_id=task_id,
                phase=project.phase,
                reason=reason,
            )
        return changed

    def replay_workflow(self, project: ProjectState, *, reason: str = "manual_replay") -> list[str]:
        """Reset a workflow so it can be executed again from its initial task set."""

        replayed_task_ids = project.replay_workflow(reason=reason)
        if replayed_task_ids:
            project.save()
            self._log_event(
                "info",
                "workflow_replayed",
                project_name=project.project_name,
                phase=project.phase,
                reason=reason,
                replayed_task_ids=list(replayed_task_ids),
            )
        return replayed_task_ids

    def _exit_if_workflow_paused(self, project: ProjectState) -> bool:
        if not project.is_workflow_paused():
            return False
        project.save()
        self._log_event(
            "info",
            "workflow_paused",
            project_name=project.project_name,
            phase=project.phase,
            reason=project.workflow_pause_reason,
        )
        return True

    def _exit_if_workflow_cancelled(self, project: ProjectState) -> bool:
        if not project.is_workflow_cancelled():
            return False
        project.save()
        self._log_event(
            "warning",
            "workflow_cancelled",
            project_name=project.project_name,
            phase=project.phase,
            terminal_outcome=project.terminal_outcome,
        )
        return True

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
            normalized_output = self._unredacted_agent_result(agent, normalized_output)
            normalized_output = self._sanitize_output_provider_call_metadata(normalized_output)
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
        normalized_role = AgentRegistry.normalize_key(self._execution_agent_name(task))
        if normalized_role == "code_engineer":
            self._validate_code_output(output, task=task)
            return
        if normalized_role == "qa_tester":
            self._validate_test_output(context, output, task=task)
            return
        if normalized_role != "dependency_manager":
            return
        raw_code_analysis = context.get("code_analysis")
        code_analysis = cast(Dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
        dependency_analysis = self._analyze_dependency_manifest(output.raw_content, code_analysis)
        self._record_output_validation(output, "dependency_analysis", dependency_analysis)
        if dependency_analysis.get("is_valid"):
            return
        validation_failures: list[str] = []
        missing_entries = ", ".join(dependency_analysis.get("missing_manifest_entries") or [])
        if missing_entries:
            validation_failures.append(f"missing manifest entries for {missing_entries}")
        provenance_violations = ", ".join(dependency_analysis.get("provenance_violations") or [])
        if provenance_violations:
            validation_failures.append(
                f"unsupported dependency sources or installer directives: {provenance_violations}"
            )
        failure_summary = "; ".join(validation_failures) or "unknown dependency validation failure"
        raise AgentExecutionError(f"Dependency manifest validation failed: {failure_summary}")

    def _validate_code_output(self, output: AgentOutput, task: Optional[Task] = None) -> None:
        code_artifact_content = self._artifact_content(output, ArtifactType.CODE)
        code_content = code_artifact_content or output.raw_content
        if not self._should_validate_code_content(code_content, has_typed_artifact=bool(code_artifact_content)):
            return
        code_analysis = self._analyze_python_module(code_content)
        code_analysis["line_count"] = self._output_line_count(code_content)
        line_budget = self._task_line_budget(task)
        if line_budget is not None:
            code_analysis["line_budget"] = line_budget
        if self._task_requires_cli_entrypoint(task):
            code_analysis["main_guard_required"] = True
        task_public_contract_preflight = self._task_public_contract_preflight(task, code_analysis)
        completion_diagnostics = self._completion_diagnostics_from_output(
            output,
            raw_content=code_content,
            syntax_ok=code_analysis.get("syntax_ok", True),
            syntax_error=code_analysis.get("syntax_error"),
        )
        import_validation: Optional[Dict[str, Any]] = None
        third_party_imports = code_analysis.get("third_party_imports") or []
        if code_analysis.get("syntax_ok", True) and not third_party_imports:
            module_filename = self._artifact_filename(
                output,
                ArtifactType.CODE,
                default_filename="code_implementation.py",
            )
            import_validation = self._execute_generated_module_import(module_filename, code_content)
        self._record_output_validation(output, "code_analysis", code_analysis)
        if task_public_contract_preflight is not None:
            self._record_output_validation(output, "task_public_contract_preflight", task_public_contract_preflight)
        if import_validation is not None:
            self._record_output_validation(output, "import_validation", import_validation)
        self._record_output_validation(output, "completion_diagnostics", completion_diagnostics)
        validation_issues: list[str] = []
        if not code_analysis.get("syntax_ok", True):
            validation_issues.append(f"syntax error {code_analysis.get('syntax_error') or 'unknown syntax error'}")
        if isinstance(line_budget, int) and code_analysis["line_count"] > line_budget:
            validation_issues.append(f"line count {code_analysis['line_count']} exceeds maximum {line_budget}")
        if code_analysis.get("main_guard_required") and not code_analysis.get("has_main_guard"):
            validation_issues.append("missing required CLI entrypoint")
        if (
            isinstance(import_validation, dict)
            and import_validation.get("ran")
            and import_validation.get("returncode") not in (None, 0)
        ):
            import_summary = import_validation.get("summary") or "generated module failed to import"
            validation_issues.append(f"module import failed: {import_summary}")
        if isinstance(task_public_contract_preflight, dict):
            contract_issues = task_public_contract_preflight.get("issues") or []
            if contract_issues:
                validation_issues.append(f"task public contract mismatch: {', '.join(contract_issues)}")
        if completion_diagnostics.get("likely_truncated"):
            validation_issues.append(self._completion_validation_issue(completion_diagnostics))
        if validation_issues:
            raise AgentExecutionError(f"Generated code validation failed: {'; '.join(validation_issues)}")

    def _task_public_contract_preflight(
        self,
        task: Optional[Task],
        code_analysis: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if task is None or not code_analysis.get("syntax_ok", True):
            return None

        task_public_contract_anchor = self._task_public_contract_anchor(task.description)
        if not task_public_contract_anchor:
            return None

        class_map = code_analysis.get("classes") or {}
        function_map = {
            item["name"]: item
            for item in code_analysis.get("functions") or []
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        issues: list[str] = []
        public_facade = ""
        primary_request_model = ""
        required_surfaces: list[str] = []

        for line in task_public_contract_anchor.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue

            label, separator, surface = stripped[2:].partition(":")
            if not separator:
                continue

            normalized_label = label.strip().lower()
            normalized_surface = surface.strip()
            if not normalized_surface:
                continue

            if normalized_label == "public facade":
                public_facade = normalized_surface
                if normalized_surface not in class_map:
                    issues.append(f"missing public facade {normalized_surface}")
                continue

            if normalized_label == "primary request model":
                primary_request_model = normalized_surface
                _, model_name, expected_params = self._parse_task_public_contract_surface(normalized_surface)
                class_info = class_map.get(model_name)
                if not isinstance(class_info, dict):
                    issues.append(f"missing primary request model {model_name}")
                    continue

                actual_params = list(class_info.get("constructor_params") or [])
                min_required_params = class_info.get("constructor_min_args")
                expected_prefix = actual_params[: len(expected_params)]
                if expected_params and expected_prefix != expected_params:
                    issues.append(
                        f"primary request model {model_name} must start with constructor fields ({', '.join(expected_params)})"
                    )
                    continue
                if isinstance(min_required_params, int) and min_required_params > len(expected_params):
                    issues.append(
                        f"primary request model {model_name} requires additional constructor fields beyond ({', '.join(expected_params)})"
                    )
                continue

            required_surfaces.append(normalized_surface)
            owner_name, callable_name, _ = self._parse_task_public_contract_surface(normalized_surface)
            if owner_name:
                class_info = class_map.get(owner_name)
                method_signatures = (class_info or {}).get("method_signatures") or {}
                method_info = method_signatures.get(callable_name) if isinstance(method_signatures, dict) else None
                if not isinstance(class_info, dict) or not isinstance(method_info, dict):
                    issues.append(f"missing required surface {owner_name}.{callable_name}")
                continue
            function_info = function_map.get(callable_name)
            if not isinstance(function_info, dict):
                issues.append(f"missing required surface {callable_name}")
                continue
            _, _, expected_params = self._parse_task_public_contract_surface(normalized_surface)
            actual_params = list(function_info.get("params") or [])
            if expected_params and actual_params[: len(expected_params)] != expected_params:
                issues.append(
                    f"required surface {callable_name} must expose parameters ({', '.join(expected_params)})"
                )
                continue
            if callable_name == "main" and "__main__" in normalized_surface and not code_analysis.get("has_main_guard", False):
                issues.append("missing required surface main guard")

        return {
            "anchor_present": True,
            "anchor": task_public_contract_anchor,
            "public_facade": public_facade,
            "primary_request_model": primary_request_model,
            "required_surfaces": required_surfaces,
            "issues": issues,
            "passed": not issues,
        }

    def _parse_task_public_contract_surface(self, surface: str) -> tuple[Optional[str], str, list[str]]:
        normalized_surface = surface.strip()
        match = re.match(
            r"^(?:(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\.)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\((?P<args>[^)]*)\)",
            normalized_surface,
        )
        if not match:
            return None, normalized_surface, []

        args_text = match.group("args").strip()
        args: list[str] = []
        if args_text:
            for part in args_text.split(","):
                cleaned = part.strip()
                if not cleaned:
                    continue
                cleaned = cleaned.split("=", 1)[0].strip()
                cleaned = cleaned.split(":", 1)[0].strip()
                cleaned = cleaned.lstrip("*")
                if cleaned and cleaned not in {"/", "*"}:
                    args.append(cleaned)
        return match.group("owner"), match.group("name"), args

    def _execute_generated_module_import(self, module_filename: str, code_content: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "ran": False,
            "returncode": None,
            "summary": "",
        }
        if not code_content.strip():
            result["summary"] = "generated code was empty"
            return result

        sandbox_policy = self.config.execution_sandbox_policy()
        wall_clock_seconds = sandbox_policy.max_wall_clock_seconds
        with tempfile.TemporaryDirectory(
            prefix="kycortex-import-",
            dir=sandbox_policy.temp_root,
        ) as tmp_dir:
            tmp_path = Path(tmp_dir)
            tmp_path.chmod(0o700)
            safe_module_filename = self._sanitize_generated_filename(module_filename, "generated_module.py")
            import_runner_path = self._write_generated_import_runner(
                tmp_path,
                safe_module_filename,
                sandbox_policy.enabled,
            )
            module_path = tmp_path / safe_module_filename
            module_path.write_text(code_content, encoding="utf-8")
            for path in (module_path, import_runner_path):
                path.chmod(0o600)
            env = self._build_generated_test_env(tmp_path, sandbox_policy)
            command = [sys.executable]
            if sandbox_policy.enabled:
                command.append("-I")
            command.append(str(import_runner_path))
            try:
                completed = subprocess.run(
                    command,
                    cwd=tmp_path,
                    capture_output=True,
                    text=True,
                    timeout=wall_clock_seconds,
                    env=env,
                    preexec_fn=self._sandbox_preexec_fn(sandbox_policy),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                result["ran"] = True
                result["returncode"] = -1
                result["summary"] = f"module import timed out after {wall_clock_seconds:g} seconds"
                return self._redact_validation_execution_result(result)

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
        result["sandbox"] = {
            "enabled": sandbox_policy.enabled,
            "allow_network": sandbox_policy.allow_network,
            "allow_subprocesses": sandbox_policy.allow_subprocesses,
            "max_cpu_seconds": sandbox_policy.max_cpu_seconds,
            "max_wall_clock_seconds": sandbox_policy.max_wall_clock_seconds,
            "max_memory_mb": sandbox_policy.max_memory_mb,
        }
        return self._redact_validation_execution_result(result)

    def _validate_test_output(self, context: Dict[str, Any], output: AgentOutput, task: Optional[Task] = None) -> None:
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
        code_exact_test_contract = context.get("code_exact_test_contract", "")
        finalized_test_content = QATesterAgent._finalize_generated_test_suite(
            test_content,
            module_name=module_name,
            implementation_code=code_content,
            code_exact_test_contract=code_exact_test_contract if isinstance(code_exact_test_contract, str) else "",
        )
        if finalized_test_content != test_content:
            output.raw_content = finalized_test_content
            output.summary = self._summarize_output(finalized_test_content)
            for artifact in output.artifacts:
                if artifact.artifact_type != ArtifactType.TEST:
                    continue
                artifact.content = finalized_test_content
            test_artifact_content = finalized_test_content if test_artifact_content else test_artifact_content
            test_content = finalized_test_content
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
        test_analysis["line_count"] = self._output_line_count(test_content)
        line_budget = self._task_line_budget(task)
        if line_budget is not None:
            test_analysis["line_budget"] = line_budget
        exact_test_count = self._task_exact_top_level_test_count(task)
        if exact_test_count is not None:
            test_analysis["expected_top_level_test_count"] = exact_test_count
        max_test_count = self._task_max_top_level_test_count(task)
        if max_test_count is not None:
            test_analysis["max_top_level_test_count"] = max_test_count
        fixture_budget = self._task_fixture_budget(task)
        if fixture_budget is not None:
            test_analysis["fixture_budget"] = fixture_budget
        test_execution = self._execute_generated_tests(module_filename, code_content, test_filename, test_content)
        completion_diagnostics = self._completion_diagnostics_from_output(
            output,
            raw_content=test_content,
            syntax_ok=test_analysis.get("syntax_ok", True),
            syntax_error=test_analysis.get("syntax_error"),
        )
        self._record_output_validation(output, "test_analysis", test_analysis)
        self._record_output_validation(output, "test_execution", test_execution)
        self._record_output_validation(output, "completion_diagnostics", completion_diagnostics)
        self._record_output_validation(output, "module_filename", module_filename)
        self._record_output_validation(output, "test_filename", test_filename)
        self._record_output_validation(
            output,
            "pytest_failure_origin",
            self._pytest_failure_origin(test_execution, module_filename, test_filename),
        )

        validation_issues: list[str] = []
        if not test_analysis.get("syntax_ok", True):
            validation_issues.append(f"test syntax error {test_analysis.get('syntax_error') or 'unknown syntax error'}")
        if isinstance(line_budget, int) and test_analysis["line_count"] > line_budget:
            validation_issues.append(f"line count {test_analysis['line_count']} exceeds maximum {line_budget}")
        if isinstance(exact_test_count, int) and test_analysis.get("top_level_test_count") != exact_test_count:
            validation_issues.append(
                f"top-level test count {test_analysis.get('top_level_test_count')} does not match required {exact_test_count}"
            )
        if isinstance(max_test_count, int) and test_analysis.get("top_level_test_count", 0) > max_test_count:
            validation_issues.append(
                f"top-level test count {test_analysis.get('top_level_test_count')} exceeds maximum {max_test_count}"
            )
        if isinstance(fixture_budget, int) and test_analysis.get("fixture_count", 0) > fixture_budget:
            validation_issues.append(
                f"fixture count {test_analysis.get('fixture_count')} exceeds maximum {fixture_budget}"
            )
        tests_without_assertions = test_analysis.get("tests_without_assertions") or []
        if tests_without_assertions:
            validation_issues.append(
                f"tests without assertion-like checks: {', '.join(tests_without_assertions)}"
            )
        contract_overreach_signals = test_analysis.get("contract_overreach_signals") or []
        if contract_overreach_signals:
            validation_issues.append(
                f"contract overreach signals: {', '.join(contract_overreach_signals)}"
            )
        if test_analysis.get("helper_surface_usages") and (
            isinstance(line_budget, int) or isinstance(max_test_count, int) or isinstance(fixture_budget, int)
        ):
            validation_issues.append(
                f"helper surface usages: {', '.join(test_analysis.get('helper_surface_usages') or [])}"
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
                validation_issues.append(f"{label}: {', '.join(issues)}")

        if test_execution.get("ran") and test_execution.get("returncode") not in (None, 0):
            validation_issues.append(f"pytest failed: {test_execution.get('summary') or 'generated tests failed'}")

        if completion_diagnostics.get("likely_truncated"):
            validation_issues.append(self._completion_validation_issue(completion_diagnostics))

        if validation_issues:
            raise AgentExecutionError(f"Generated test validation failed: {'; '.join(validation_issues)}")

    def _output_line_count(self, raw_content: str) -> int:
        if not raw_content:
            return 0
        return len(raw_content.splitlines())

    def _task_line_budget(self, task: Optional[Task]) -> Optional[int]:
        if task is None or not isinstance(task.description, str):
            return None
        description = task.description.lower()
        for pattern in _LINE_BUDGET_PATTERNS:
            match = pattern.search(description)
            if match is None:
                continue
            return int(match.group(1))
        return None

    def _task_requires_cli_entrypoint(self, task: Optional[Task]) -> bool:
        if task is None or not isinstance(task.description, str):
            return False
        description = task.description.lower()
        return any(keyword in description for keyword in ("cli", "entrypoint", "__main__", "command-line"))

    def _should_compact_architecture_context(self, task: Optional[Task], task_public_contract_anchor: str) -> bool:
        if task is None or not isinstance(task_public_contract_anchor, str) or not task_public_contract_anchor.strip():
            return False
        execution_agent_name = self._execution_agent_name(task)
        if AgentRegistry.normalize_key(execution_agent_name) != "code_engineer":
            return False
        if isinstance(task.repair_context, dict) and bool(task.repair_context):
            return True
        max_tokens = self.config.max_tokens
        return isinstance(max_tokens, int) and 0 < max_tokens <= 1200

    def _compact_architecture_context(self, task: Task, task_public_contract_anchor: str) -> str:
        repair_focused = isinstance(task.repair_context, dict) and bool(task.repair_context)
        compact_lines = [
            "Repair-focused architecture summary:" if repair_focused else "Low-budget architecture summary:",
            "- Keep one main facade plus the exact anchored request model and method names.",
            "- Public contract anchor:",
        ]
        compact_lines.extend(
            f"  {line}"
            for line in task_public_contract_anchor.splitlines()
            if isinstance(line, str) and line.strip()
        )
        if repair_focused:
            compact_lines.append(
                "- Treat prior architecture snippets as behavioral guidance only. Do not copy illustrative code blocks over the failing implementation, validation summary, or cited pytest failures."
            )
            compact_lines.append(
                "- During repair, prefer the existing failing module, the validation summary, and the cited pytest details over any stale field names or helper flows shown in the architecture sketch."
            )
        compact_lines.append(
            "- Keep validation, scoring, audit logging, and batch behavior on that same facade unless the task explicitly requires another public collaborator."
        )
        compact_lines.append(
            "- Inline optional scoring or audit detail instead of separate Logger, Scorer, Processor, Manager, or extra result dataclasses when the public contract does not require them."
        )
        line_budget = self._task_line_budget(task)
        if line_budget is not None:
            compact_lines.append(
                f"- Stay comfortably under {line_budget} lines and leave visible headroom for imports and the CLI."
            )
        if self._task_requires_cli_entrypoint(task):
            compact_lines.append(
                '- Include a minimal main() plus a literal if __name__ == "__main__": block in the same module.'
            )
        return "\n".join(compact_lines)

    def _task_exact_top_level_test_count(self, task: Optional[Task]) -> Optional[int]:
        if task is None or not isinstance(task.description, str):
            return None
        match = _EXACT_TEST_COUNT_PATTERN.search(task.description.lower())
        if match is None:
            return None
        return int(match.group(1))

    def _task_max_top_level_test_count(self, task: Optional[Task]) -> Optional[int]:
        if task is None or not isinstance(task.description, str):
            return None
        match = _MAX_TEST_COUNT_PATTERN.search(task.description.lower())
        if match is None:
            return None
        return int(match.group(1))

    def _task_fixture_budget(self, task: Optional[Task]) -> Optional[int]:
        if task is None or not isinstance(task.description, str):
            return None
        match = _FIXTURE_BUDGET_PATTERN.search(task.description.lower())
        if match is None:
            return None
        return int(match.group(1))

    def _classify_task_failure(self, task: Task, exc: Exception) -> str:
        normalized_role = AgentRegistry.normalize_key(self._execution_agent_name(task))
        if isinstance(exc, WorkflowDefinitionError):
            return FailureCategory.WORKFLOW_DEFINITION.value
        if isinstance(exc, ProviderTransientError):
            return FailureCategory.PROVIDER_TRANSIENT.value
        if self._is_sandbox_security_violation(exc):
            return FailureCategory.SANDBOX_SECURITY_VIOLATION.value
        if isinstance(exc, AgentExecutionError):
            if normalized_role == "code_engineer":
                return FailureCategory.CODE_VALIDATION.value
            if normalized_role == "qa_tester":
                return FailureCategory.TEST_VALIDATION.value
            if normalized_role == "dependency_manager":
                return FailureCategory.DEPENDENCY_VALIDATION.value
        return FailureCategory.TASK_EXECUTION.value

    def _is_sandbox_security_violation(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return "sandbox policy blocked" in message

    def _is_repairable_failure(self, failure_category: str) -> bool:
        return failure_category in {
            FailureCategory.UNKNOWN.value,
            FailureCategory.TASK_EXECUTION.value,
            FailureCategory.CODE_VALIDATION.value,
            FailureCategory.TEST_VALIDATION.value,
            FailureCategory.DEPENDENCY_VALIDATION.value,
        }

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
            return self._redact_validation_execution_result(result)
        if not code_content.strip() or not test_content.strip():
            result["summary"] = "generated code or tests were empty"
            return self._redact_validation_execution_result(result)

        sandbox_policy = self.config.execution_sandbox_policy()
        wall_clock_seconds = sandbox_policy.max_wall_clock_seconds
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
                    timeout=wall_clock_seconds,
                    env=env,
                    preexec_fn=self._sandbox_preexec_fn(sandbox_policy),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                result["ran"] = True
                result["returncode"] = -1
                result["summary"] = (
                    f"pytest timed out after {wall_clock_seconds:g} seconds"
                )
                return self._redact_validation_execution_result(result)

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
            "max_wall_clock_seconds": sandbox_policy.max_wall_clock_seconds,
            "max_memory_mb": sandbox_policy.max_memory_mb,
        }
        return self._redact_validation_execution_result(result)

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
            if _looks_like_secret_env_var(key):
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

    def _write_generated_import_runner(
        self,
        tmp_path: Path,
        module_filename: str,
        sandbox_enabled: bool,
    ) -> Path:
        runner_path = tmp_path / "_kycortex_import_module.py"
        runner_path.write_text(
            textwrap.dedent(
                _GENERATED_IMPORT_RUNNER.format(
                    sandbox_enabled=repr(sandbox_enabled),
                    module_filename=repr(module_filename),
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
        resource_module = resource
        if not sandbox_policy.enabled or os.name != "posix" or resource_module is None:
            return None

        def _apply_limits() -> None:
            cpu_seconds = max(int(sandbox_policy.max_cpu_seconds), 1)
            memory_bytes = max(sandbox_policy.max_memory_mb, 1) * 1024 * 1024
            os.umask(0o077)
            resource_module.setrlimit(resource_module.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource_module.setrlimit(resource_module.RLIMIT_AS, (memory_bytes, memory_bytes))
            resource_module.setrlimit(resource_module.RLIMIT_CORE, (0, 0))
            resource_module.setrlimit(resource_module.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))

        return _apply_limits

    def _summarize_pytest_output(self, stdout: str, stderr: str, returncode: int) -> str:
        combined_lines = [line.strip() for line in f"{stdout}\n{stderr}".splitlines() if line.strip()]
        if not combined_lines:
            return f"pytest exited with code {returncode}"
        for line in reversed(combined_lines):
            if line.startswith("=") or line.startswith("FAILED") or line.startswith("ERROR") or "passed" in line:
                return line
        return combined_lines[-1][:240]

    @staticmethod
    def _redact_validation_execution_result(result: Dict[str, Any]) -> Dict[str, Any]:
        return cast(Dict[str, Any], redact_sensitive_data(result))

    def _sanitize_provider_call_metadata(self, provider_call: Dict[str, Any]) -> Dict[str, Any]:
        return sanitize_provider_call_metadata(provider_call)

    def _sanitize_output_provider_call_metadata(self, output: AgentOutput) -> AgentOutput:
        provider_call = output.metadata.get("provider_call") if isinstance(output.metadata, dict) else None
        if not isinstance(provider_call, dict):
            return output
        output.metadata = dict(output.metadata)
        output.metadata["provider_call"] = self._sanitize_provider_call_metadata(provider_call)
        return output

    def _provider_call_metadata(self, agent: Any, output: Optional[AgentOutput] = None) -> Optional[Dict[str, Any]]:
        if output is not None:
            provider_call = output.metadata.get("provider_call")
            if isinstance(provider_call, dict):
                return self._sanitize_provider_call_metadata(provider_call)
        getter = getattr(agent, "get_last_provider_call_metadata", None)
        if callable(getter):
            metadata = getter()
            if isinstance(metadata, dict):
                return self._sanitize_provider_call_metadata(metadata)
        return None

    def _persist_artifacts(self, artifacts: list[ArtifactRecord]) -> None:
        for artifact in artifacts:
            content = artifact.content
            if not isinstance(content, str) or not content.strip():
                continue
            persisted_content = redact_sensitive_text(content)
            target_path = self._resolve_artifact_output_path(artifact)
            self._validate_artifact_output_path(target_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            _harden_private_directory_permissions(target_path.parent)
            self._validate_artifact_output_path(target_path)
            target_path.write_text(persisted_content, encoding="utf-8")
            _harden_private_file_permissions(target_path)
            artifact.content = persisted_content
            artifact.path = self._artifact_record_path(target_path)

    def _resolve_artifact_output_path(self, artifact: ArtifactRecord) -> Path:
        output_root = Path(self.config.output_dir).resolve()
        relative_path = self._sanitize_artifact_relative_path(
            artifact.path if artifact.path else self._default_artifact_path(artifact)
        )
        return output_root / relative_path

    def _validate_artifact_output_path(self, target_path: Path) -> None:
        output_root = Path(self.config.output_dir).resolve()
        resolved_target = target_path.resolve(strict=False)
        try:
            resolved_target.relative_to(output_root)
        except ValueError as exc:
            raise AgentExecutionError(
                "Artifact persistence failed: artifact path resolves outside the output directory"
            ) from exc

    def _sanitize_artifact_relative_path(self, artifact_path: str) -> Path:
        candidate = Path(artifact_path)
        if candidate.is_absolute():
            raise AgentExecutionError("Artifact persistence failed: absolute artifact paths are not allowed")

        sanitized_parts: list[str] = []
        for part in candidate.parts:
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

    @staticmethod
    def _agent_visible_repair_context(repair_context: Dict[str, Any], execution_agent_name: str) -> Dict[str, Any]:
        normalized_execution_agent = AgentRegistry.normalize_key(execution_agent_name)
        if normalized_execution_agent not in {"code_engineer", "qa_tester", "dependency_manager"}:
            return dict(repair_context)
        visible_keys = (
            "cycle",
            "failure_category",
            "repair_owner",
            "original_assigned_to",
            "source_failure_task_id",
            "source_failure_category",
        )
        return {
            key: repair_context[key]
            for key in visible_keys
            if key in repair_context
        }

    def _build_context(self, task: Task, project: ProjectState) -> Dict[str, Any]:
        snapshot = project.snapshot()
        agent_view = self._build_agent_view(task, project, snapshot)
        visible_task_ids = self._task_dependency_closure_ids(task, project)
        execution_agent_name = self._execution_agent_name(task)
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        budget_decomposition_plan_task_id = repair_context.get("budget_decomposition_plan_task_id")
        if not isinstance(budget_decomposition_plan_task_id, str) or not budget_decomposition_plan_task_id.strip():
            budget_decomposition_plan_task_id = None
        ctx: Dict[str, Any] = {
            "goal": project.goal,
            "project_name": project.project_name,
            "phase": project.phase,
            "provider_max_tokens": self.config.max_tokens,
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "assigned_to": task.assigned_to,
                "execution_agent": execution_agent_name,
            },
            "snapshot": asdict(agent_view),
            "completed_tasks": {},
            "decisions": agent_view.decisions,
            "artifacts": agent_view.artifacts,
        }
        ctx.update(self._planned_module_context(project, visible_task_ids, current_task=task))
        planned_module_name = ctx.get("planned_module_name")
        planned_module_filename = ctx.get("planned_module_filename")
        if isinstance(planned_module_name, str) and planned_module_name.strip():
            ctx["module_name"] = planned_module_name
        if isinstance(planned_module_filename, str) and planned_module_filename.strip():
            ctx["module_filename"] = planned_module_filename
        task_public_contract_anchor = self._task_public_contract_anchor(task.description)
        compact_architecture_context: Optional[str] = None
        if task_public_contract_anchor:
            ctx["task_public_contract_anchor"] = task_public_contract_anchor
            if self._should_compact_architecture_context(task, task_public_contract_anchor):
                compact_architecture_context = self._compact_architecture_context(task, task_public_contract_anchor)
        for prev_task in project.tasks:
            if prev_task.id not in visible_task_ids:
                continue
            visible_output = self._task_context_output(prev_task)
            if prev_task.status == TaskStatus.DONE.value and visible_output:
                ctx[prev_task.id] = visible_output
                ctx["completed_tasks"][prev_task.id] = visible_output
                if budget_decomposition_plan_task_id == prev_task.id:
                    ctx["budget_decomposition_brief"] = visible_output
                if self._is_budget_decomposition_planner(prev_task):
                    continue
                semantic_key = self._semantic_output_key(prev_task)
                if semantic_key:
                    semantic_output = visible_output
                    if semantic_key == "architecture" and compact_architecture_context:
                        semantic_output = compact_architecture_context
                    ctx[semantic_key] = semantic_output
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "code_engineer":
                    ctx.update(self._code_artifact_context(prev_task, project))
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "dependency_manager":
                    ctx.update(self._dependency_artifact_context(prev_task, ctx))
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "qa_tester":
                    ctx.update(self._test_artifact_context(prev_task, ctx))
        if repair_context:
            ctx["repair_context"] = self._agent_visible_repair_context(repair_context, execution_agent_name)
            if budget_decomposition_plan_task_id is not None:
                ctx["budget_decomposition_plan_task_id"] = budget_decomposition_plan_task_id
            validation_summary = repair_context.get("validation_summary")
            if isinstance(validation_summary, str) and validation_summary.strip():
                ctx["repair_validation_summary"] = validation_summary
            helper_surface_usages = [
                item.strip()
                for item in repair_context.get("helper_surface_usages", [])
                if isinstance(item, str) and item.strip()
            ]
            helper_surface_symbols = self._normalized_helper_surface_symbols(
                repair_context.get("helper_surface_symbols") or helper_surface_usages
            )
            existing_tests = repair_context.get("existing_tests")
            failed_artifact_content = repair_context.get("failed_artifact_content")
            failed_output = repair_context.get("failed_output")
            repair_content = failed_artifact_content if isinstance(failed_artifact_content, str) and failed_artifact_content.strip() else failed_output
            normalized_execution_agent = AgentRegistry.normalize_key(execution_agent_name)
            if normalized_execution_agent == "code_engineer" and isinstance(repair_content, str) and repair_content.strip():
                ctx["existing_code"] = repair_content
            if normalized_execution_agent == "code_engineer" and isinstance(existing_tests, str) and existing_tests.strip():
                ctx["existing_tests"] = existing_tests
            if normalized_execution_agent == "qa_tester":
                if (
                    isinstance(repair_content, str)
                    and repair_content.strip()
                    and self._qa_repair_should_reuse_failed_test_artifact(
                        validation_summary,
                        ctx.get("code", ""),
                        repair_content,
                    )
                ):
                    ctx["existing_tests"] = repair_content
                if "test_validation_summary" not in ctx and isinstance(validation_summary, str) and validation_summary.strip():
                    ctx["test_validation_summary"] = validation_summary
                if helper_surface_usages:
                    ctx["repair_helper_surface_usages"] = helper_surface_usages
                if helper_surface_symbols:
                    ctx["repair_helper_surface_symbols"] = helper_surface_symbols
            if normalized_execution_agent == "dependency_manager":
                if isinstance(repair_content, str) and repair_content.strip():
                    ctx["existing_dependency_manifest"] = repair_content
                if "dependency_validation_summary" not in ctx and isinstance(validation_summary, str) and validation_summary.strip():
                    ctx["dependency_validation_summary"] = validation_summary
        return cast(Dict[str, Any], redact_sensitive_data(ctx))

    def _task_dependency_closure_ids(self, task: Task, project: ProjectState) -> set[str]:
        visible_task_ids = {task.id}
        pending_task_ids = list(task.dependencies)
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        budget_decomposition_plan_task_id = repair_context.get("budget_decomposition_plan_task_id")
        if isinstance(budget_decomposition_plan_task_id, str) and budget_decomposition_plan_task_id.strip():
            pending_task_ids.append(budget_decomposition_plan_task_id)
        if task.repair_origin_task_id:
            pending_task_ids.append(task.repair_origin_task_id)

        while pending_task_ids:
            dependency_id = pending_task_ids.pop()
            if dependency_id in visible_task_ids:
                continue
            visible_task_ids.add(dependency_id)
            dependency_task = project.get_task(dependency_id)
            if dependency_task is None:
                continue
            pending_task_ids.extend(dependency_task.dependencies)

        return visible_task_ids

    @staticmethod
    def _direct_dependency_ids(task: Task) -> set[str]:
        direct_dependency_ids = set(task.dependencies)
        if task.repair_origin_task_id:
            direct_dependency_ids.add(task.repair_origin_task_id)
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        budget_decomposition_plan_task_id = repair_context.get("budget_decomposition_plan_task_id")
        if isinstance(budget_decomposition_plan_task_id, str) and budget_decomposition_plan_task_id.strip():
            direct_dependency_ids.add(budget_decomposition_plan_task_id)
        return direct_dependency_ids

    def _build_agent_view(self, task: Task, project: ProjectState, snapshot: ProjectSnapshot) -> AgentView:
        visible_task_ids = self._task_dependency_closure_ids(task, project)
        direct_dependency_ids = self._direct_dependency_ids(task)
        acceptance_evaluation = snapshot.acceptance_evaluation
        acceptance_policy = acceptance_evaluation.get("policy")
        if not isinstance(acceptance_policy, str):
            acceptance_policy = None
        terminal_outcome = acceptance_evaluation.get("terminal_outcome")
        if not isinstance(terminal_outcome, str):
            terminal_outcome = None
        failure_category = acceptance_evaluation.get("failure_category")
        if not isinstance(failure_category, str):
            failure_category = None
        acceptance_criteria_met = bool(acceptance_evaluation.get("accepted"))
        return AgentView(
            project_name=snapshot.project_name,
            goal=snapshot.goal,
            workflow_status=snapshot.workflow_status,
            phase=snapshot.phase,
            acceptance_policy=acceptance_policy,
            terminal_outcome=terminal_outcome,
            failure_category=failure_category,
            acceptance_criteria_met=acceptance_criteria_met,
            task_results=self._agent_view_task_results(snapshot.task_results, visible_task_ids),
            decisions=self._agent_view_decisions(snapshot.decisions),
            artifacts=self._agent_view_artifacts(snapshot.artifacts, visible_task_ids, direct_dependency_ids),
        )

    @staticmethod
    def _agent_view_task_results(
        task_results: Dict[str, TaskResult],
        visible_task_ids: set[str],
    ) -> Dict[str, AgentViewTaskResult]:
        filtered_results: Dict[str, AgentViewTaskResult] = {}
        for task_id, task_result in task_results.items():
            if task_id not in visible_task_ids:
                continue
            failure_category = None
            if task_result.failure is not None:
                failure_category = task_result.failure.category
            filtered_results[task_id] = AgentViewTaskResult(
                task_id=task_result.task_id,
                status=task_result.status,
                agent_name=task_result.agent_name,
                has_output=task_result.output is not None,
                failure_category=failure_category,
                started_at=task_result.started_at,
                completed_at=task_result.completed_at,
            )
        return filtered_results

    @staticmethod
    def _agent_view_decisions(decisions: list[Any]) -> list[AgentViewDecisionRecord]:
        filtered_decisions: list[AgentViewDecisionRecord] = []
        for decision in decisions:
            if isinstance(decision, dict):
                topic = decision.get("topic")
                decision_text = decision.get("decision")
                rationale = decision.get("rationale")
                created_at = decision.get("created_at")
            else:
                topic = getattr(decision, "topic", None)
                decision_text = getattr(decision, "decision", None)
                rationale = getattr(decision, "rationale", None)
                created_at = getattr(decision, "created_at", None)
            if isinstance(topic, str) and isinstance(decision_text, str) and isinstance(rationale, str):
                filtered_decisions.append(
                    AgentViewDecisionRecord(
                        topic=topic,
                        decision=decision_text,
                        rationale=rationale,
                        created_at=created_at if isinstance(created_at, str) else "",
                    )
                )
        return filtered_decisions

    @staticmethod
    def _agent_view_artifacts(
        artifacts: list[Any],
        visible_task_ids: set[str],
        direct_dependency_ids: set[str],
    ) -> list[AgentViewArtifactRecord]:
        filtered_artifacts: list[AgentViewArtifactRecord] = []
        for artifact in artifacts:
            if isinstance(artifact, dict):
                metadata = artifact.get("metadata")
                source_task_id = metadata.get("task_id") if isinstance(metadata, dict) else None
                artifact_name = artifact.get("name")
                artifact_type = artifact.get("artifact_type", ArtifactType.OTHER)
                artifact_content = artifact.get("content")
                created_at = artifact.get("created_at")
            else:
                metadata = artifact.metadata if isinstance(artifact.metadata, dict) else None
                source_task_id = metadata.get("task_id") if isinstance(metadata, dict) else None
                artifact_name = getattr(artifact, "name", None)
                artifact_type = getattr(artifact, "artifact_type", ArtifactType.OTHER)
                artifact_content = getattr(artifact, "content", None)
                created_at = getattr(artifact, "created_at", None)
            if isinstance(source_task_id, str) and source_task_id not in visible_task_ids:
                continue
            include_content = isinstance(source_task_id, str) and source_task_id in direct_dependency_ids
            if not isinstance(artifact_name, str):
                continue
            filtered_artifacts.append(
                AgentViewArtifactRecord(
                    name=artifact_name,
                    artifact_type=artifact_type if isinstance(artifact_type, ArtifactType) else ArtifactType(str(artifact_type)),
                    content=artifact_content if include_content and isinstance(artifact_content, str) else None,
                    created_at=created_at if isinstance(created_at, str) else "",
                    source_task_id=source_task_id if isinstance(source_task_id, str) else None,
                )
            )
        return filtered_artifacts

    def _build_repair_instruction(self, task: Task, failure_category: str) -> str:
        if failure_category == FailureCategory.CODE_VALIDATION.value:
            last_error = task.last_error if isinstance(task.last_error, str) else ""
            if "follows default argument" in last_error.lower():
                instruction = (
                    "Repair the generated Python module by reordering any dataclass fields that currently place a defaulted field before a required field. "
                    "Inspect every dataclass in the module, preserve the documented public names, and avoid unrelated behavior changes."
                )
                dataclass_examples = self._dataclass_default_order_repair_examples(
                    self._failed_artifact_content(task, ArtifactType.CODE)
                )
                if dataclass_examples:
                    instruction = f"{instruction} {dataclass_examples[0]}"
                return instruction

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

    def _task_context_output(self, task: Task) -> str:
        if isinstance(task.output, str) and task.output.strip():
            return task.output
        if isinstance(task.output_payload, dict):
            raw_content = task.output_payload.get("raw_content")
            if isinstance(raw_content, str) and raw_content.strip():
                return raw_content
        return task.output or ""

    def _completion_diagnostics_from_output(
        self,
        output: AgentOutput,
        *,
        raw_content: str = "",
        syntax_ok: bool,
        syntax_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        provider_call = output.metadata.get("provider_call") if isinstance(output.metadata, dict) else None
        return self._completion_diagnostics_from_provider_call(
            provider_call,
            raw_content=raw_content,
            syntax_ok=syntax_ok,
            syntax_error=syntax_error,
        )

    def _completion_diagnostics_from_provider_call(
        self,
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
                or self._looks_structurally_truncated(raw_content, syntax_error)
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

    def _looks_structurally_truncated(self, raw_content: str, syntax_error: Optional[str]) -> bool:
        if not isinstance(raw_content, str) or not raw_content.strip():
            return False

        try:
            list(tokenize.generate_tokens(io.StringIO(raw_content).readline))
        except tokenize.TokenError as exc:
            message = str(exc).lower()
            if "eof in multi-line statement" in message or "eof in multi-line string" in message:
                return True

        normalized_error = syntax_error.lower() if isinstance(syntax_error, str) else ""
        if not normalized_error or not any(marker in normalized_error for marker in _LIKELY_TRUNCATED_SYNTAX_MARKERS):
            return False

        last_non_empty_line = next(
            (line.strip() for line in reversed(raw_content.splitlines()) if line.strip()),
            "",
        )
        if not last_non_empty_line:
            return False
        if last_non_empty_line.endswith(_LIKELY_TRUNCATED_TAIL_SUFFIXES):
            return True
        if last_non_empty_line.count('"') % 2 == 1 or last_non_empty_line.count("'") % 2 == 1:
            return True
        return False

    def _completion_hit_limit(self, completion_diagnostics: Dict[str, Any]) -> bool:
        return bool(
            completion_diagnostics.get("hit_token_limit")
            or completion_diagnostics.get("finish_reason") == "length"
            or completion_diagnostics.get("stop_reason") == "max_tokens"
            or completion_diagnostics.get("done_reason") == "length"
        )

    def _completion_validation_issue(self, completion_diagnostics: Dict[str, Any]) -> str:
        if self._completion_hit_limit(completion_diagnostics):
            return "output likely truncated at the completion token limit"
        return "output likely truncated before the file ended cleanly"

    def _completion_diagnostics_summary(self, completion_diagnostics: Dict[str, Any]) -> str:
        if not completion_diagnostics:
            return "none"
        details: list[str] = []
        hit_limit = self._completion_hit_limit(completion_diagnostics)
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

    def _pytest_failure_details(self, test_execution: Optional[Dict[str, Any]], limit: int = 3) -> list[str]:
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

    def _pytest_failure_origin(
        self,
        test_execution: Optional[Dict[str, Any]],
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

    def _pytest_failure_is_semantic_assertion_mismatch(
        self,
        test_execution: Optional[Dict[str, Any]],
    ) -> bool:
        failure_details = self._pytest_failure_details(test_execution, limit=10)
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
                "fixture\"",
            )
        ):
            return False

        return "AssertionError" in joined_details or " - assert " in joined_details

    def _pytest_contract_overreach_signals(
        self,
        test_execution: Optional[Dict[str, Any]],
    ) -> list[str]:
        failure_details = self._pytest_failure_details(test_execution, limit=10)
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
            matches = [
                status_like_aliases[match.lower()]
                for match in status_like_pattern.findall(assertion_text)
            ]
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

    def _test_validation_has_static_issues(self, validation: Dict[str, Any]) -> bool:
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
        ):
            if test_analysis.get(issue_key):
                return True

        return False

    def _build_code_validation_summary(
        self,
        code_analysis: Dict[str, Any],
        fallback_message: str,
        completion_diagnostics: Optional[Dict[str, Any]] = None,
        import_validation: Optional[Dict[str, Any]] = None,
        task_public_contract_preflight: Optional[Dict[str, Any]] = None,
    ) -> str:
        lines = ["Generated code validation:"]
        lines.append(f"- Syntax OK: {'yes' if code_analysis.get('syntax_ok', True) else 'no'}")
        syntax_error = code_analysis.get('syntax_error')
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
            lines.append(
                f"- Completion diagnostics: {self._completion_diagnostics_summary(completion_diagnostics)}"
            )
        if isinstance(import_validation, dict) and import_validation.get("ran"):
            lines.append(
                f"- Module import: {'PASS' if import_validation.get('returncode') == 0 else 'FAIL'}"
            )
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
                completion_diagnostics = validation.get("completion_diagnostics")
                import_validation = validation.get("import_validation")
                task_public_contract_preflight = validation.get("task_public_contract_preflight")
                return self._build_code_validation_summary(
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
                return self._build_test_validation_summary(
                    test_analysis,
                    test_execution if isinstance(test_execution, dict) else None,
                    completion_diagnostics if isinstance(completion_diagnostics, dict) else None,
                )
        if failure_category == FailureCategory.DEPENDENCY_VALIDATION.value:
            dependency_analysis = validation.get("dependency_analysis")
            if isinstance(dependency_analysis, dict):
                return self._build_dependency_validation_summary(dependency_analysis)
        return fallback_message

    def _test_failure_requires_code_repair(self, task: Task) -> bool:
        if AgentRegistry.normalize_key(task.assigned_to) != "qa_tester":
            return False
        if task.last_error_category != FailureCategory.TEST_VALIDATION.value:
            return False

        validation = self._validation_payload(task)
        if not validation:
            return False

        test_execution = validation.get("test_execution")
        if not isinstance(test_execution, dict):
            return False
        if not test_execution.get("ran") or test_execution.get("returncode") in (None, 0):
            return False

        failure_origin = validation.get("pytest_failure_origin")
        if not isinstance(failure_origin, str) or not failure_origin:
            failure_origin = self._pytest_failure_origin(
                test_execution,
                validation.get("module_filename") if isinstance(validation.get("module_filename"), str) else None,
                validation.get("test_filename") if isinstance(validation.get("test_filename"), str) else None,
            )

        if failure_origin == "tests" and self._pytest_contract_overreach_signals(test_execution):
            return False

        if failure_origin == "code_under_test":
            return True

        if self._test_validation_has_static_issues(validation):
            return False

        return (
            failure_origin == "tests"
            and self._pytest_failure_is_semantic_assertion_mismatch(test_execution)
        )

    def _upstream_code_task_for_test_failure(self, project: ProjectState, task: Task) -> Optional[Task]:
        imported_code_task = self._imported_code_task_for_failed_test(project, task)
        preferred_dependency: Optional[Task] = None
        for dependency_id in reversed(task.dependencies):
            dependency = project.get_task(dependency_id)
            if dependency is None:
                continue
            if AgentRegistry.normalize_key(dependency.assigned_to) == "code_engineer":
                if dependency.repair_origin_task_id:
                    return dependency
                if preferred_dependency is None:
                    preferred_dependency = dependency
        return imported_code_task or preferred_dependency

    @staticmethod
    def _python_import_roots(raw_content: object) -> set[str]:
        if not isinstance(raw_content, str) or not raw_content.strip():
            return set()

        try:
            tree = ast.parse(raw_content)
        except SyntaxError:
            return set()

        import_roots: set[str] = set()
        for node in ast.walk(tree):
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
        return import_roots

    def _imported_code_task_for_failed_test(self, project: ProjectState, task: Task) -> Optional[Task]:
        import_roots = self._python_import_roots(
            self._failed_artifact_content(task, ArtifactType.TEST)
        )
        if not import_roots:
            return None

        preferred_task: Optional[Task] = None
        for existing_task in reversed(project.tasks):
            if AgentRegistry.normalize_key(existing_task.assigned_to) != "code_engineer":
                continue
            module_name = self._default_module_name_for_task(existing_task)
            if not module_name or module_name not in import_roots:
                continue
            if existing_task.repair_origin_task_id:
                return existing_task
            if preferred_task is None:
                preferred_task = existing_task
        return preferred_task

    def _build_code_repair_context_from_test_failure(
        self,
        code_task: Task,
        test_task: Task,
        cycle: Dict[str, Any],
    ) -> Dict[str, Any]:
        validation_summary = self._build_repair_validation_summary(
            test_task,
            FailureCategory.TEST_VALIDATION.value,
        )
        repair_context = {
            "cycle": cycle.get("cycle"),
            "failure_category": FailureCategory.CODE_VALIDATION.value,
            "failure_message": test_task.last_error or test_task.output or "",
            "failure_error_type": test_task.last_error_type,
            "repair_owner": "code_engineer",
            "original_assigned_to": code_task.assigned_to,
            "source_failure_task_id": test_task.id,
            "source_failure_category": test_task.last_error_category or FailureCategory.TEST_VALIDATION.value,
            "instruction": self._build_code_repair_instruction_from_test_failure(
                code_task,
                validation_summary,
            ),
            "validation_summary": validation_summary,
            "existing_tests": self._failed_artifact_content(test_task, ArtifactType.TEST),
            "failed_output": code_task.output or "",
            "failed_artifact_content": self._failed_artifact_content(code_task, ArtifactType.CODE),
            "provider_call": code_task.last_provider_call,
        }
        self._merge_prior_repair_context(code_task, repair_context)
        return repair_context

    def _build_code_repair_instruction_from_test_failure(
        self,
        code_task: Task,
        validation_summary: str,
    ) -> str:
        failed_artifact_content = self._failed_artifact_content(code_task, ArtifactType.CODE)
        duplicate_argument_details = self._duplicate_constructor_argument_details(validation_summary)
        if duplicate_argument_details is not None:
            class_name, field_name = duplicate_argument_details
            instruction = (
                "Repair the generated Python module so valid happy-path and batch requests do not fail because the same constructor field is bound twice. "
                "Keep internal constructor calls unambiguous and preserve the documented contract. "
                f"The current failed artifact still passes {field_name} twice to {class_name}(...). "
                f"Do not pass {field_name} both positionally and through **request.details or another expanded mapping. "
                "Remove the duplicate from the expanded payload or switch to explicit keyword construction so each constructor field is bound exactly once."
            )
            duplicate_call_hint = self._duplicate_constructor_argument_call_hint(
                validation_summary,
                failed_artifact_content,
            )
            if duplicate_call_hint:
                instruction = (
                    f"{instruction} The exact broken call {duplicate_call_hint} still appears in the failed artifact. "
                    f"Do not return that call unchanged; rewrite that construction so {field_name} is bound exactly once and that exact call no longer appears anywhere in the module."
                )
            explicit_rewrite_hint = self._duplicate_constructor_explicit_rewrite_hint(
                validation_summary,
                failed_artifact_content,
            )
            if duplicate_call_hint and explicit_rewrite_hint:
                instruction = (
                    f"{instruction} For this failed artifact, rewrite {duplicate_call_hint} to {explicit_rewrite_hint} "
                    "or an equivalent explicit constructor call that binds each field once and supplies safe defaults for fields omitted by valid inputs."
                )
            return instruction
        missing_attribute_details = self._missing_object_attribute_details(
            validation_summary,
            failed_artifact_content,
        )
        if missing_attribute_details is not None:
            class_name, attribute_name, class_fields = missing_attribute_details
            replacement_field = self._suggest_declared_attribute_replacement(attribute_name, class_fields)
            instruction = (
                "Repair the generated Python module so valid happy-path and batch requests do not fail on missing internal attributes. "
                "Keep dataclass fields, helper-return objects, and member accesses internally consistent."
            )
            if class_fields:
                instruction = (
                    f"{instruction} The current failed artifact reads {class_name}.{attribute_name} even though "
                    f"{class_name} only defines {self._render_name_list(class_fields)}."
                )
            else:
                instruction = (
                    f"{instruction} The current failed artifact reads {class_name}.{attribute_name} even though "
                    "that attribute is not defined on the returned object."
                )
            return (
                f"{instruction} Rename the access to an existing field or define and derive that attribute consistently "
                f"on the model. If the rewritten module keeps .{attribute_name} anywhere, {class_name} must declare "
                f"{attribute_name} and populate or derive it where {class_name} instances are built. Otherwise replace "
                f"that access with one of the existing fields and remove every undeclared read of .{attribute_name}; "
                + (
                    f"the closest declared field here is {replacement_field}, so prefer replacing {class_name}.{attribute_name} with {class_name}.{replacement_field} unless the task explicitly requires a separate {attribute_name} field. "
                    if replacement_field
                    else ""
                )
                + "do not leave near-match field names split across construction and scoring paths."
            )
        nested_payload_wrapper_details = self._nested_payload_wrapper_field_validation_details(
            validation_summary,
            failed_artifact_content,
        )
        if nested_payload_wrapper_details is not None:
            container_name, offending_fields, validation_line = nested_payload_wrapper_details
            rendered_fields = self._render_name_list(offending_fields)
            instruction = (
                "Repair the generated Python module so valid happy-path and batch requests do not fail because the validator is checking request-wrapper fields inside the nested payload container. "
                "Preserve the documented split between top-level request fields and nested payload data. "
                f"The current failed artifact still treats {rendered_fields} as required keys inside request.{container_name}. "
                f"Keep wrapper fields such as {rendered_fields} on the request object, and reserve request.{container_name} checks for actual payload keys only. "
                f"Do not require {rendered_fields} as keys inside request.{container_name}; validate them directly on the request object or drop that nested wrapper-field requirement entirely."
            )
            if validation_line:
                instruction = (
                    f"{instruction} The exact broken validation line `{validation_line}` still appears in the failed artifact. "
                    "Do not return that line unchanged; replace it with wrapper-field checks on the request object plus only true payload-key validation inside the nested container."
                )
            return instruction
        strictness_details = self._internal_constructor_strictness_details(
            validation_summary,
            failed_artifact_content,
        )
        if strictness_details is None:
            return (
                "Repair the generated Python module so it satisfies the existing valid pytest suite "
                "and the documented contract without shifting the failure onto the tests."
            )

        class_name, missing_fields, required_fields = strictness_details
        instruction = (
            "Repair the generated Python module so valid happy-path and batch requests do not fail "
            "while constructing internal models. Align internal constructor requirements with the "
            "documented contract, validate_request(...), and the existing valid pytest inputs. "
            "Do not shift new required payload fields onto the tests."
        )
        rendered_missing_fields = self._render_name_list(missing_fields)
        if required_fields:
            instruction = (
                f"{instruction} The current validator only requires "
                f"{self._render_name_list(required_fields)}, but {class_name}(...) still requires "
                f"{rendered_missing_fields}."
            )
        else:
            instruction = (
                f"{instruction} The current failed artifact still makes {class_name}(...) require "
                f"{rendered_missing_fields} during the cited valid pytest cases."
            )
        return (
            f"{instruction} Derive those internal values or give them safe defaults instead of "
            "demanding new input fields."
        )

    def _is_budget_decomposition_planner(self, task: Task) -> bool:
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        return repair_context.get("decomposition_mode") == "budget_compaction_planner"

    @staticmethod
    def _summary_limit_exceeded(validation_summary: object, label: str) -> bool:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return False
        pattern = rf"^- {re.escape(label)}:\s*(\d+)\s*/\s*(\d+)"
        for line in validation_summary.splitlines():
            match = re.match(pattern, line.strip(), re.IGNORECASE)
            if match is None:
                continue
            actual = int(match.group(1))
            limit = int(match.group(2))
            return actual > limit
        return False

    def _repair_requires_budget_decomposition(self, repair_context: Dict[str, Any]) -> bool:
        failure_category = repair_context.get("failure_category")
        if failure_category not in {
            FailureCategory.CODE_VALIDATION.value,
            FailureCategory.TEST_VALIDATION.value,
        }:
            return False
        validation_summary = repair_context.get("validation_summary")
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return False
        normalized = validation_summary.lower()
        if "completion diagnostics:" in normalized and "likely truncated" in normalized:
            return True
        if (
            failure_category == FailureCategory.CODE_VALIDATION.value
            and "completion diagnostics:" in normalized
            and "completion limit reached" in normalized
            and "missing required cli entrypoint" in normalized
        ):
            return True
        if self._summary_limit_exceeded(validation_summary, "Line count"):
            return True
        if failure_category == FailureCategory.TEST_VALIDATION.value:
            return any(
                self._summary_limit_exceeded(validation_summary, label)
                for label in ("Top-level test functions", "Fixture count")
            )
        return False

    def _build_budget_decomposition_instruction(self, failure_category: str) -> str:
        if failure_category == FailureCategory.TEST_VALIDATION.value:
            return (
                "Produce a compact budget decomposition brief for the next pytest repair. "
                "Distill only the minimum required imports, scenarios, helper removals, and rewrite order needed to keep the suite under budget while preserving the validated contract."
            )
        return (
            "Produce a compact budget decomposition brief for the next module repair. "
            "Distill only the minimum required public surface, behaviors, optional cuts, and rewrite order needed to keep the implementation under budget while preserving the validated contract."
        )

    def _build_budget_decomposition_task_context(
        self,
        task: Task,
        repair_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        failure_category = str(repair_context.get("failure_category") or FailureCategory.UNKNOWN.value)
        return {
            "cycle": repair_context.get("cycle"),
            "decomposition_mode": "budget_compaction_planner",
            "decomposition_target_task_id": task.id,
            "decomposition_target_agent": self._execution_agent_name(task),
            "decomposition_failure_category": failure_category,
            "failure_category": failure_category,
            "failure_message": repair_context.get("failure_message") or "",
            "instruction": self._build_budget_decomposition_instruction(failure_category),
            "validation_summary": repair_context.get("validation_summary") or "",
        }

    def _ensure_budget_decomposition_task(
        self,
        project: ProjectState,
        task: Task,
        repair_context: Dict[str, Any],
    ) -> Optional[Task]:
        decomposition_task_id = repair_context.get("budget_decomposition_plan_task_id")
        if isinstance(decomposition_task_id, str) and decomposition_task_id.strip():
            existing = project.get_task(decomposition_task_id)
            if existing is not None:
                return existing
        if not self._repair_requires_budget_decomposition(repair_context):
            return None
        decomposition_task = project._create_budget_decomposition_task(
            task.id,
            self._build_budget_decomposition_task_context(task, repair_context),
        )
        if decomposition_task is not None:
            repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
        return decomposition_task

    def _active_repair_cycle(self, project: ProjectState) -> Optional[Dict[str, Any]]:
        if not project.repair_history:
            return None
        current_cycle = project.repair_history[-1]
        if not isinstance(current_cycle, dict):
            return None
        return current_cycle

    def _build_repair_context(self, task: Task, cycle: Dict[str, Any]) -> Dict[str, Any]:
        failure_category = task.last_error_category or FailureCategory.UNKNOWN.value
        repair_context = {
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
        helper_surface_usages = self._test_repair_helper_surface_usages(task, failure_category)
        if helper_surface_usages:
            repair_context["helper_surface_usages"] = helper_surface_usages
            repair_context["helper_surface_symbols"] = self._normalized_helper_surface_symbols(
                helper_surface_usages
            )
        self._merge_prior_repair_context(task, repair_context)
        return repair_context

    def _merge_prior_repair_context(self, task: Task, repair_context: Dict[str, Any]) -> None:
        if not isinstance(repair_context, dict) or not task.repair_origin_task_id:
            return

        prior_repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        if not prior_repair_context:
            return

        current_instruction = str(repair_context.get("instruction") or "").strip()
        prior_instruction = str(prior_repair_context.get("instruction") or "").strip()
        if prior_instruction and prior_instruction not in current_instruction:
            merged_instruction_parts = [current_instruction] if current_instruction else []
            merged_instruction_parts.append(
                f"Also preserve and fully satisfy the prior unresolved repair objective from {task.repair_origin_task_id}: {prior_instruction}"
            )
            repair_context["instruction"] = " ".join(merged_instruction_parts).strip()

        current_validation_summary = str(repair_context.get("validation_summary") or "").strip()
        prior_validation_summary = str(prior_repair_context.get("validation_summary") or "").strip()
        if prior_validation_summary and prior_validation_summary not in current_validation_summary:
            merged_validation_parts = [current_validation_summary] if current_validation_summary else []
            merged_validation_parts.extend(
                [
                    "",
                    "Prior unresolved repair context:",
                    f"- Prior failure category: {prior_repair_context.get('failure_category') or FailureCategory.UNKNOWN.value}",
                ]
            )
            if prior_instruction:
                merged_validation_parts.append(f"- Prior repair objective: {prior_instruction}")
            merged_validation_parts.extend([
                "- Prior validation summary:",
                prior_validation_summary,
            ])
            repair_context["validation_summary"] = "\n".join(merged_validation_parts).strip()

    def _test_repair_helper_surface_usages(self, task: Task, failure_category: str) -> list[str]:
        if failure_category != FailureCategory.TEST_VALIDATION.value:
            return []

        validation = self._validation_payload(task)
        test_analysis = validation.get("test_analysis")
        if not isinstance(test_analysis, dict):
            return []

        raw_usages = test_analysis.get("helper_surface_usages")
        if not isinstance(raw_usages, list):
            return []

        return [item.strip() for item in raw_usages if isinstance(item, str) and item.strip()]

    def _normalized_helper_surface_symbols(self, raw_values: object) -> list[str]:
        if not isinstance(raw_values, list):
            return []

        seen: set[str] = set()
        symbols: list[str] = []
        for value in raw_values:
            if not isinstance(value, str):
                continue
            symbol = value.split(" (line ", 1)[0].strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
        return symbols

    @staticmethod
    def _validation_summary_symbols(validation_summary: str, label: str) -> list[str]:
        prefix = f"- {label}:"
        for line in validation_summary.splitlines():
            if not line.startswith(prefix):
                continue
            raw_value = line[len(prefix):].strip()
            if not raw_value or raw_value.lower() == "none":
                return []
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        return []

    @staticmethod
    def _module_defined_symbol_names(implementation_code: object) -> list[str]:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return []
        try:
            tree = ast.parse(implementation_code)
        except SyntaxError:
            return []

        names: list[str] = []
        seen: set[str] = set()
        for node in tree.body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in seen:
                continue
            seen.add(node.name)
            names.append(node.name)
        return names

    @staticmethod
    def _is_helper_alias_like_name(name: str) -> bool:
        normalized = name.strip().lower()
        if not normalized:
            return False
        return normalized.endswith((
            "logger",
            "scorer",
            "processor",
            "manager",
            "repository",
            "validator",
            "engine",
            "service",
        ))

    def _validation_summary_helper_alias_names(
        self,
        validation_summary: object,
        implementation_code: object = "",
    ) -> list[str]:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return []
        module_defined_symbols = {
            name.lower() for name in self._module_defined_symbol_names(implementation_code)
        }
        undefined_names = self._normalized_helper_surface_symbols(
            self._validation_summary_symbols(validation_summary, "Undefined local names")
        )
        return [
            name
            for name in undefined_names
            if name.lower() not in module_defined_symbols and self._is_helper_alias_like_name(name)
        ]

    @staticmethod
    def _content_has_matching_datetime_import(content: object) -> bool:
        if not isinstance(content, str) or not content.strip():
            return False
        return bool(
            re.search(
                r"^\s*(?:from\s+datetime\s+import\s+[^\n]*\bdatetime\b|import\s+datetime\b)",
                content,
                flags=re.MULTILINE,
            )
        )

    @staticmethod
    def _content_has_bare_datetime_reference(content: object) -> bool:
        if not isinstance(content, str) or not content.strip():
            return False
        return bool(
            re.search(
                r"(?<![A-Za-z0-9_\.])datetime(?:\.[A-Za-z_][A-Za-z0-9_]*)?\s*\(",
                content,
            )
        )

    def _validation_summary_has_missing_datetime_import_issue(
        self,
        validation_summary: object,
        failed_artifact_content: object = "",
    ) -> bool:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return False
        summary_lower = validation_summary.lower()
        if (
            "undefined local names: datetime" not in summary_lower
            and "name 'datetime' is not defined" not in summary_lower
        ):
            return False
        if isinstance(failed_artifact_content, str) and failed_artifact_content.strip():
            return (
                self._content_has_bare_datetime_reference(failed_artifact_content)
                and not self._content_has_matching_datetime_import(failed_artifact_content)
            )
        return True

    @staticmethod
    def _implementation_prefers_direct_datetime_import(implementation_code: object) -> bool:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return False
        return bool(
            re.search(
                r"^\s*from\s+datetime\s+import\s+[^\n]*\bdatetime\b",
                implementation_code,
                flags=re.MULTILINE,
            )
        )

    @staticmethod
    def _string_literal_sequence(node: ast.AST | None) -> list[str]:
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return []

        values: list[str] = []
        for element in node.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                return []
            values.append(element.value)
        return values

    def _implementation_required_evidence_items(self, implementation_code: object) -> list[str]:
        if not isinstance(implementation_code, str) or not implementation_code.strip():
            return []

        try:
            tree = ast.parse(implementation_code)
        except SyntaxError:
            return []

        for node in ast.walk(tree):
            target_names: list[str] = []
            value_node: ast.AST | None = None
            if isinstance(node, ast.Assign):
                target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target_names = [node.target.id]
                value_node = node.value
            if not any(name in {"required_evidence", "required_documents"} for name in target_names):
                continue
            items = self._string_literal_sequence(value_node)
            if items:
                unique_items: list[str] = []
                seen: set[str] = set()
                for item in items:
                    if item in seen:
                        continue
                    seen.add(item)
                    unique_items.append(item)
                return unique_items
        return []

    def _content_has_incomplete_required_evidence_payload(
        self,
        content: object,
        implementation_code: object,
    ) -> bool:
        required_evidence_items = self._implementation_required_evidence_items(implementation_code)
        if len(required_evidence_items) <= 1:
            return False
        if not isinstance(content, str) or not content.strip():
            return False

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return False

        required_evidence_set = set(required_evidence_items)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            function_name = node.name.lower()
            if any(token in function_name for token in ("validation", "invalid", "reject", "error", "failure")):
                continue
            if not (
                any(token in function_name for token in ("happy", "batch"))
                or any(
                    (isinstance(child, ast.Attribute) and child.attr == "risk_scores")
                    or (isinstance(child, ast.Name) and child.id == "risk_scores")
                    for child in ast.walk(node)
                )
            ):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Dict):
                    continue
                document_items: list[str] | None = None
                for key, value in zip(child.keys, child.values):
                    if isinstance(key, ast.Constant) and key.value == "documents":
                        document_items = self._string_literal_sequence(value)
                        break
                if document_items is None:
                    continue
                if not required_evidence_set.issubset(set(document_items)):
                    return True
        return False

    def _validation_summary_has_required_evidence_runtime_issue(
        self,
        validation_summary: object,
        failed_artifact_content: object = "",
        implementation_code: object = "",
    ) -> bool:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return False

        summary_lower = validation_summary.lower()
        if "pytest execution: fail" not in summary_lower and "pytest failure details:" not in summary_lower:
            return False
        if not any(
            int(actual_count) < int(expected_count)
            for actual_count, expected_count in re.findall(r"assert\s+(\d+)\s*==\s*(\d+)", summary_lower)
        ):
            return False
        if (
            isinstance(failed_artifact_content, str)
            and failed_artifact_content.strip()
            and "risk_scores" not in failed_artifact_content.lower()
        ):
            return False
        return self._content_has_incomplete_required_evidence_payload(
            failed_artifact_content,
            implementation_code,
        )

    def _qa_repair_should_reuse_failed_test_artifact(
        self,
        validation_summary: object,
        implementation_code: object = "",
        failed_artifact_content: object = "",
    ) -> bool:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return True
        available_module_symbols = {
            name.lower(): name for name in self._module_defined_symbol_names(implementation_code)
        }
        undefined_local_names = self._normalized_helper_surface_symbols(
            self._validation_summary_symbols(validation_summary, "Undefined local names")
        )
        has_reusable_missing_imports = any(
            name.lower() not in {"datetime", "pytest"}
            and name.lower() in available_module_symbols
            for name in undefined_local_names
        )
        has_required_evidence_runtime_issue = self._validation_summary_has_required_evidence_runtime_issue(
            validation_summary,
            failed_artifact_content,
            implementation_code,
        )
        if self._validation_summary_helper_alias_names(validation_summary, implementation_code):
            return False
        if has_required_evidence_runtime_issue and not has_reusable_missing_imports:
            return False
        if self._validation_summary_has_missing_datetime_import_issue(
            validation_summary,
            failed_artifact_content,
        ) and not has_reusable_missing_imports:
            return False
        return not any(
            self._validation_summary_symbols(validation_summary, label)
            for label in (
                "Tests without assertion-like checks",
                "Contract overreach signals",
            )
        )

    @staticmethod
    def _append_unique_mapping_value(mapping: dict[str, list[str]], key: str, value: str) -> None:
        values = mapping.setdefault(key, [])
        if value not in values:
            values.append(value)

    @staticmethod
    def _has_dataclass_decorator(node: ast.ClassDef) -> bool:
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Name) and target.id == "dataclass":
                return True
            if isinstance(target, ast.Attribute) and target.attr == "dataclass":
                return True
        return False

    def _dataclass_default_order_repair_examples(
        self,
        failed_artifact_content: object,
    ) -> list[str]:
        if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
            return []

        try:
            tree = ast.parse(failed_artifact_content)
        except SyntaxError:
            return []

        lines: list[str] = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not self._has_dataclass_decorator(node):
                continue

            field_entries: list[tuple[str, ast.AST | None]] = []
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign):
                    continue
                if not isinstance(statement.target, ast.Name):
                    continue
                field_entries.append((statement.target.id, statement.value))

            if not field_entries:
                continue

            required_fields: list[str] = []
            default_fields: list[tuple[str, ast.AST]] = []
            offending_required_fields: list[str] = []
            seen_default = False
            for field_name, default_value in field_entries:
                if default_value is None:
                    required_fields.append(field_name)
                    if seen_default:
                        offending_required_fields.append(field_name)
                    continue
                seen_default = True
                default_fields.append((field_name, default_value))

            if not offending_required_fields or not default_fields:
                continue

            rendered_signature = ", ".join(
                [
                    *required_fields,
                    *[
                        f"{field_name}={ast.unparse(default_value)}"
                        for field_name, default_value in default_fields
                    ],
                ]
            )
            offending_fields = ", ".join(offending_required_fields)
            lines.append(
                "The current failed artifact still has this ordering bug in "
                f"{node.name}: move required field(s) {offending_fields} ahead of every defaulted field and implement {node.name}({rendered_signature})."
            )
            if len(lines) >= 2:
                break

        return lines

    @staticmethod
    def _render_name_list(names: list[str]) -> str:
        cleaned = [name for name in names if isinstance(name, str) and name]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} and {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"

    @staticmethod
    def _missing_required_constructor_details(
        validation_summary: object,
    ) -> Optional[tuple[str, list[str]]]:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return None

        match = re.search(
            r"TypeError:\s+([A-Za-z_][A-Za-z0-9_]*)\.__init__\(\).*?missing\s+\d+\s+required positional arguments?:\s*([^\n;|]+)",
            validation_summary,
            re.IGNORECASE,
        )
        if match is None:
            return None

        missing_fields = list(dict.fromkeys(re.findall(r"'([^']+)'", match.group(2))))
        if not missing_fields:
            return None
        return match.group(1), missing_fields

    @staticmethod
    def _required_field_list_from_failed_artifact(
        failed_artifact_content: object,
    ) -> list[str]:
        if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
            return []

        try:
            tree = ast.parse(failed_artifact_content)
        except SyntaxError:
            return []

        for node in ast.walk(tree):
            target_names: list[str] = []
            value_node: ast.AST | None = None
            if isinstance(node, ast.Assign):
                target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target_names = [node.target.id]
                value_node = node.value
            if not any(name in {"required_fields", "required_keys"} for name in target_names):
                continue
            if value_node is None:
                continue

            items = Orchestrator._string_literal_sequence(value_node)
            if items:
                return items

            try:
                value = ast.literal_eval(value_node)
            except (ValueError, SyntaxError):
                continue
            if isinstance(value, (list, tuple, set)) and all(isinstance(item, str) for item in value):
                return list(value)

        return []

    def _nested_payload_wrapper_field_validation_details(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[str, list[str], str]]:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return None
        if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
            return None

        summary_lower = validation_summary.lower()
        if "valueerror" not in summary_lower or "invalid" not in summary_lower:
            return None
        if not any(token in summary_lower for token in ("test_happy_path", "test_batch", "test_batch_processing")):
            return None

        container_name = next(
            (
                name
                for name in ("details", "data", "metadata", "payload")
                if f"request.{name}" in failed_artifact_content
            ),
            "",
        )
        if not container_name:
            return None

        required_fields = self._required_field_list_from_failed_artifact(failed_artifact_content)
        if not required_fields:
            return None

        wrapper_field_names = {"request_id", "request_type", "details", "data", "metadata", "payload"}
        offending_fields = [
            field for field in required_fields
            if field in wrapper_field_names or field == container_name
        ]
        if not offending_fields:
            return None

        validation_line = ""
        for line in failed_artifact_content.splitlines():
            stripped = line.strip()
            if (
                stripped
                and f"request.{container_name}" in stripped
                and ("issubset" in stripped or " in request." in stripped)
            ):
                validation_line = stripped
                break

        return container_name, offending_fields, validation_line

    def _internal_constructor_strictness_details(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[str, list[str], list[str]]]:
        constructor_details = self._missing_required_constructor_details(validation_summary)
        if constructor_details is None:
            return None
        class_name, missing_fields = constructor_details
        required_fields = self._required_field_list_from_failed_artifact(failed_artifact_content)
        return class_name, missing_fields, required_fields

    @staticmethod
    def _duplicate_constructor_argument_details(
        validation_summary: object,
    ) -> Optional[tuple[str, str]]:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return None

        match = re.search(
            r"TypeError:\s+([A-Za-z_][A-Za-z0-9_]*)\.__init__\(\).*?got multiple values for argument '([^']+)'",
            validation_summary,
            re.IGNORECASE,
        )
        if match is None:
            return None
        return match.group(1), match.group(2)

    def _duplicate_constructor_argument_call_hint(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[str]:
        call_details = self._duplicate_constructor_argument_call_details(
            validation_summary,
            failed_artifact_content,
        )
        if call_details is None:
            return None
        return call_details[2]

    def _duplicate_constructor_argument_call_details(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[str, str, str, str, str]]:
        duplicate_argument_details = self._duplicate_constructor_argument_details(
            validation_summary,
        )
        if duplicate_argument_details is None:
            return None
        if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
            return None

        class_name, field_name = duplicate_argument_details
        try:
            tree = ast.parse(failed_artifact_content)
        except SyntaxError:
            return None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if self._callable_name(node) != class_name:
                continue

            mapping_expression = ""
            for keyword in node.keywords:
                if keyword.arg is None:
                    mapping_expression = self._render_expression(keyword.value).strip()
                    break
            if not mapping_expression:
                continue

            field_expression = ""
            for keyword in node.keywords:
                if keyword.arg == field_name:
                    field_expression = self._render_expression(keyword.value).strip()
                    break
            if not field_expression:
                for argument in node.args:
                    rendered_argument = self._render_expression(argument).strip()
                    if (
                        rendered_argument == field_name
                        or self._expression_root_name(argument) == field_name
                    ):
                        field_expression = rendered_argument
                        break
            if not field_expression:
                continue

            rendered_call = self._render_expression(node).strip()
            if rendered_call:
                return class_name, field_name, rendered_call, mapping_expression, field_expression
        return None

    def _duplicate_constructor_explicit_rewrite_hint(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[str]:
        call_details = self._duplicate_constructor_argument_call_details(
            validation_summary,
            failed_artifact_content,
        )
        if call_details is None:
            return None

        class_name, field_name, _, mapping_expression, field_expression = call_details
        class_fields = self._class_field_names_from_failed_artifact(
            failed_artifact_content,
            class_name,
        )
        if not class_fields:
            return None

        required_fields = set(self._required_field_list_from_failed_artifact(failed_artifact_content))
        annotation_map = self._class_field_annotations_from_failed_artifact(
            failed_artifact_content,
            class_name,
        )
        rendered_arguments: list[str] = []
        for class_field in class_fields:
            if class_field == field_name:
                field_value = field_expression
            elif class_field in required_fields:
                field_value = f"{mapping_expression}[{class_field!r}]"
            else:
                default_value = self._default_value_for_annotation(annotation_map.get(class_field, ""))
                if default_value:
                    field_value = f"{mapping_expression}.get({class_field!r}, {default_value})"
                else:
                    field_value = f"{mapping_expression}.get({class_field!r})"
            rendered_arguments.append(f"{class_field}={field_value}")

        if not rendered_arguments:
            return None
        return f"{class_name}({', '.join(rendered_arguments)})"

    @staticmethod
    def _class_field_annotations_from_failed_artifact(
        failed_artifact_content: object,
        class_name: str,
    ) -> dict[str, str]:
        if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
            return {}

        try:
            tree = ast.parse(failed_artifact_content)
        except SyntaxError:
            return {}

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != class_name:
                continue
            annotations: dict[str, str] = {}
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign):
                    continue
                if isinstance(statement.target, ast.Name):
                    annotations[statement.target.id] = ast.unparse(statement.annotation).strip()
            return annotations
        return {}

    @staticmethod
    def _default_value_for_annotation(annotation: str) -> str:
        normalized = annotation.strip()
        if not normalized:
            return ""
        if normalized == "bool":
            return "False"
        if normalized == "str":
            return "''"
        if normalized == "int":
            return "0"
        if normalized == "float":
            return "0.0"
        if normalized in {"dict", "Dict"} or normalized.startswith(("dict[", "Dict[")):
            return "{}"
        if normalized in {"list", "List"} or normalized.startswith(("list[", "List[")):
            return "[]"
        if normalized in {"set", "Set"} or normalized.startswith(("set[", "Set[")):
            return "set()"
        return ""

    @staticmethod
    def _class_field_names_from_failed_artifact(
        failed_artifact_content: object,
        class_name: str,
    ) -> list[str]:
        if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
            return []

        try:
            tree = ast.parse(failed_artifact_content)
        except SyntaxError:
            return []

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != class_name:
                continue
            fields: list[str] = []
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign):
                    continue
                if isinstance(statement.target, ast.Name):
                    fields.append(statement.target.id)
            return fields
        return []

    def _missing_object_attribute_details(
        self,
        validation_summary: object,
        failed_artifact_content: object,
    ) -> Optional[tuple[str, str, list[str]]]:
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return None

        match = re.search(
            r"AttributeError:\s+['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] object has no attribute ['\"]([^'\"]+)['\"]",
            validation_summary,
        )
        if match is None:
            return None

        class_name = match.group(1)
        attribute_name = match.group(2).strip()
        if not attribute_name:
            return None
        class_fields = self._class_field_names_from_failed_artifact(
            failed_artifact_content,
            class_name,
        )
        return class_name, attribute_name, class_fields

    @staticmethod
    def _suggest_declared_attribute_replacement(attribute_name: str, class_fields: list[str]) -> Optional[str]:
        if not attribute_name or not class_fields:
            return None

        normalized_attribute = attribute_name.lower()
        attribute_tokens = {token for token in normalized_attribute.split("_") if token}
        best_match: Optional[str] = None
        best_score = (-1, -1)

        for field_name in class_fields:
            normalized_field = field_name.lower()
            if normalized_field == normalized_attribute:
                return field_name

            field_tokens = {token for token in normalized_field.split("_") if token}
            overlap = len(field_tokens & attribute_tokens)
            prefix_suffix_bonus = 1 if (
                normalized_attribute.endswith(normalized_field)
                or normalized_field.endswith(normalized_attribute)
            ) else 0
            if overlap <= 0 and prefix_suffix_bonus == 0:
                continue

            score = (prefix_suffix_bonus, overlap)
            if score > best_score:
                best_score = score
                best_match = field_name

        return best_match

    def _previous_valid_test_surface(
        self, failed_artifact_content: object, imported_module_symbols: list[str]
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
            return {}, {}
        if not imported_module_symbols:
            return {}, {}

        try:
            tree = ast.parse(failed_artifact_content)
        except SyntaxError:
            return {}, {}

        imported_symbol_set = set(imported_module_symbols)
        instance_bindings: dict[str, str] = {}
        member_calls_by_class: dict[str, list[str]] = {}
        constructor_keywords_by_class: dict[str, list[str]] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in imported_symbol_set
            ):
                continue

            for target in node.targets:
                if isinstance(target, ast.Name):
                    instance_bindings[target.id] = value.func.id
            for keyword in value.keywords:
                if keyword.arg:
                    self._append_unique_mapping_value(
                        constructor_keywords_by_class, value.func.id, keyword.arg
                    )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if isinstance(node.func, ast.Name) and node.func.id in imported_symbol_set:
                for keyword in node.keywords:
                    if keyword.arg:
                        self._append_unique_mapping_value(
                            constructor_keywords_by_class, node.func.id, keyword.arg
                        )
                continue

            if not isinstance(node.func, ast.Attribute):
                continue

            owner_class: str | None = None
            value = node.func.value
            if isinstance(value, ast.Name):
                owner_class = instance_bindings.get(value.id)
            elif (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in imported_symbol_set
            ):
                owner_class = value.func.id
                for keyword in value.keywords:
                    if keyword.arg:
                        self._append_unique_mapping_value(
                            constructor_keywords_by_class, value.func.id, keyword.arg
                        )

            if owner_class:
                self._append_unique_mapping_value(
                    member_calls_by_class, owner_class, node.func.attr
                )

        return member_calls_by_class, constructor_keywords_by_class

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

        self._configure_repair_attempts(project, [task.id], current_cycle)
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
        planned_task_ids: set[str] = set()
        for failed_task_id in failed_task_ids:
            task = project.get_task(failed_task_id)
            if task is None:
                continue

            if self._test_failure_requires_code_repair(task):
                code_task = self._upstream_code_task_for_test_failure(project, task)
                if code_task is not None and code_task.id not in planned_task_ids:
                    code_repair_context = self._build_code_repair_context_from_test_failure(code_task, task, cycle)
                    decomposition_task = self._ensure_budget_decomposition_task(project, code_task, code_repair_context)
                    if decomposition_task is not None:
                        code_repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
                    project._plan_task_repair(code_task.id, code_repair_context)
                    planned_task_ids.add(code_task.id)

            if task.id in planned_task_ids:
                continue

            repair_context = self._build_repair_context(task, cycle)
            decomposition_task = self._ensure_budget_decomposition_task(project, task, repair_context)
            if decomposition_task is not None:
                repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
            project._plan_task_repair(task.id, repair_context)
            planned_task_ids.add(task.id)

    def _repair_task_ids_for_cycle(self, project: ProjectState, failed_task_ids: list[str]) -> list[str]:
        repair_task_ids: list[str] = []
        for task_id in failed_task_ids:
            task = project.get_task(task_id)
            if task is None:
                continue

            code_repair_task: Optional[Task] = None
            if self._test_failure_requires_code_repair(task):
                code_task = self._upstream_code_task_for_test_failure(project, task)
                if code_task is not None:
                    code_repair_context = code_task.repair_context if isinstance(code_task.repair_context, dict) else {}
                    code_decomposition_task = self._ensure_budget_decomposition_task(project, code_task, code_repair_context)
                    if code_decomposition_task is not None and code_decomposition_task.id not in repair_task_ids:
                        repair_task_ids.append(code_decomposition_task.id)
                    code_repair_owner = self._execution_agent_name(code_task)
                    code_repair_task = project._create_repair_task(code_task.id, code_repair_owner, code_repair_context)
                    if code_repair_task is not None:
                        if code_repair_task.id not in task.dependencies:
                            task.dependencies.append(code_repair_task.id)
                        if code_decomposition_task is not None:
                            if code_decomposition_task.id not in code_repair_task.dependencies:
                                code_repair_task.dependencies.append(code_decomposition_task.id)
                            if isinstance(code_repair_task.repair_context, dict):
                                code_repair_task.repair_context["budget_decomposition_plan_task_id"] = code_decomposition_task.id
                        if code_repair_task.id not in repair_task_ids:
                            repair_task_ids.append(code_repair_task.id)

            repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
            decomposition_task = self._ensure_budget_decomposition_task(project, task, repair_context)
            if decomposition_task is not None and decomposition_task.id not in repair_task_ids:
                repair_task_ids.append(decomposition_task.id)
            repair_owner = self._execution_agent_name(task)
            repair_task = project._create_repair_task(task_id, repair_owner, repair_context)
            if repair_task is not None:
                if decomposition_task is not None:
                    if decomposition_task.id not in repair_task.dependencies:
                        repair_task.dependencies.append(decomposition_task.id)
                    if isinstance(repair_task.repair_context, dict):
                        repair_task.repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
                if code_repair_task is not None and code_repair_task.id not in repair_task.dependencies:
                    repair_task.dependencies.append(code_repair_task.id)
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

    def _planned_module_context(
        self,
        project: ProjectState,
        visible_task_ids: Optional[set[str]] = None,
        current_task: Optional[Task] = None,
    ) -> Dict[str, Any]:
        module_task = self._context_module_task(project, current_task, visible_task_ids)
        if module_task is not None:
            module_name = self._default_module_name_for_task(module_task)
            if module_name:
                return {
                    "planned_module_name": module_name,
                    "planned_module_filename": f"{module_name}.py",
                }
        return {}

    def _context_module_task(
        self,
        project: ProjectState,
        current_task: Optional[Task],
        visible_task_ids: Optional[set[str]] = None,
    ) -> Optional[Task]:
        if current_task is not None and current_task.repair_origin_task_id:
            origin_task = project.get_task(current_task.repair_origin_task_id)
            if (
                origin_task is not None
                and AgentRegistry.normalize_key(origin_task.assigned_to) == "code_engineer"
                and (visible_task_ids is None or origin_task.id in visible_task_ids)
                and self._default_module_name_for_task(origin_task)
            ):
                return origin_task

        for existing_task in project.tasks:
            if visible_task_ids is not None and existing_task.id not in visible_task_ids:
                continue
            if AgentRegistry.normalize_key(existing_task.assigned_to) != "code_engineer":
                continue
            if existing_task.repair_origin_task_id:
                continue
            if self._default_module_name_for_task(existing_task):
                return existing_task

        if current_task is not None and self._default_module_name_for_task(current_task):
            return current_task

        for existing_task in project.tasks:
            if visible_task_ids is not None and existing_task.id not in visible_task_ids:
                continue
            if AgentRegistry.normalize_key(existing_task.assigned_to) != "code_engineer":
                continue
            if self._default_module_name_for_task(existing_task):
                return existing_task

        return None

    def _default_module_name_for_task(self, task: Task) -> Optional[str]:
        if AgentRegistry.normalize_key(task.assigned_to) != "code_engineer":
            return None
        return f"{task.id}_implementation"

    def _context_code_module_name(self, task: Task, project: Optional[ProjectState] = None) -> Optional[str]:
        if project is None:
            return self._default_module_name_for_task(task)

        current_task = task
        visited_task_ids: set[str] = set()
        while current_task.repair_origin_task_id:
            origin_task = project.get_task(current_task.repair_origin_task_id)
            if (
                origin_task is None
                or origin_task.id in visited_task_ids
                or AgentRegistry.normalize_key(origin_task.assigned_to) != "code_engineer"
            ):
                break
            visited_task_ids.add(origin_task.id)
            current_task = origin_task
        return self._default_module_name_for_task(current_task)

    def _task_public_contract_anchor(self, task_description: str) -> str:
        if not isinstance(task_description, str) or not task_description.strip():
            return ""

        lines = [line.rstrip() for line in task_description.splitlines()]
        collecting = False
        anchor_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not collecting:
                if stripped == "Public contract anchor:":
                    collecting = True
                continue
            if not stripped:
                break
            if stripped.startswith("- "):
                anchor_lines.append(stripped)
                continue
            if line.startswith((" ", "\t")):
                anchor_lines.append(line.rstrip())
                continue
            break
        return "\n".join(anchor_lines)

    def _code_artifact_context(
        self,
        task: Task,
        project: Optional[ProjectState] = None,
    ) -> Dict[str, Any]:
        module_name = self._context_code_module_name(task, project)
        if not module_name:
            return {}

        artifact_path = f"artifacts/{module_name}.py"
        code_content = task.output or ""
        task_module_name = self._default_module_name_for_task(task)
        allow_artifact_path_override = task_module_name == module_name

        if isinstance(task.output_payload, dict):
            artifacts = task.output_payload.get("artifacts")
            if isinstance(artifacts, list):
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        continue
                    if artifact.get("artifact_type") != ArtifactType.CODE.value:
                        continue
                    candidate_path = artifact.get("path")
                    if allow_artifact_path_override and isinstance(candidate_path, str) and candidate_path.strip():
                        artifact_path = candidate_path
                    candidate_content = artifact.get("content")
                    if isinstance(candidate_content, str) and candidate_content.strip():
                        code_content = candidate_content
                    break
            raw_content = task.output_payload.get("raw_content")
            if (not isinstance(code_content, str) or not code_content.strip()) and isinstance(raw_content, str):
                code_content = raw_content

        if not isinstance(code_content, str) or not code_content.strip():
            return {}

        path_obj = Path(artifact_path)
        code_analysis = self._analyze_python_module(code_content)
        return {
            "code_artifact_path": artifact_path,
            "module_name": path_obj.stem,
            "module_filename": path_obj.name,
            "code_summary": self._summarize_output(code_content),
            "code_outline": self._build_code_outline(code_content),
            "code_analysis": code_analysis,
            "code_public_api": self._build_code_public_api(code_analysis),
            "code_exact_test_contract": self._build_code_exact_test_contract(code_analysis),
            "code_test_targets": self._build_code_test_targets(code_analysis),
            "code_behavior_contract": self._build_code_behavior_contract(code_content),
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
        provenance_violations: list[str] = []
        for raw_line in manifest_content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            package_name = extract_requirement_name(line)
            if not package_name:
                if is_provenance_unsafe_requirement(line):
                    provenance_violations.append(line)
                continue
            declared_packages.append(package_name)
            normalized_declared_packages.add(self._normalize_package_name(package_name))
            if is_provenance_unsafe_requirement(line):
                provenance_violations.append(line)

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
            "provenance_violations": provenance_violations,
            "is_valid": not missing_manifest_entries and not provenance_violations,
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
        lines.append(
            f"- Provenance violations: {', '.join(dependency_analysis.get('provenance_violations') or ['none'])}"
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
            "module_variables": [],
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
        module_variables: set[str] = set()

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                signature = self._call_signature_details(node)
                functions.append({
                    "name": node.name,
                    "params": signature["params"],
                    "param_annotations": signature["param_annotations"],
                    "min_args": signature["min_args"],
                    "max_args": signature["max_args"],
                    "return_annotation": signature["return_annotation"],
                    "signature": f"{node.name}({', '.join(signature['params'])})",
                    "accepts_sequence_input": signature["accepts_sequence_input"],
                    "async": isinstance(node, ast.AsyncFunctionDef),
                })
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in self._bound_target_names(target):
                        if not name.startswith("_"):
                            module_variables.add(name)
                continue
            if isinstance(node, ast.AnnAssign):
                if node.value is not None:
                    for name in self._bound_target_names(node.target):
                        if not name.startswith("_"):
                            module_variables.add(name)
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:  # pragma: no branch
                    root_name = alias.name.split(".", 1)[0]
                    if root_name:  # pragma: no branch
                        import_roots.add(root_name)
                continue
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                module_name = (node.module or "").split(".", 1)[0]
                if module_name:  # pragma: no branch
                    import_roots.add(module_name)
                continue
            if not isinstance(node, ast.ClassDef):
                continue

            field_names: list[str] = []
            dataclass_init_params: list[str] = []
            dataclass_required_params: list[str] = []
            class_attributes: list[str] = []
            init_params: list[str] = []
            constructor_min_args: Optional[int] = None
            constructor_max_args: Optional[int] = None
            methods: list[str] = []
            method_signatures: Dict[str, Dict[str, Any]] = {}
            bases = [self._ast_name(base) for base in node.bases]
            is_enum = any(base.endswith("Enum") for base in bases)
            is_dataclass = any(self._ast_name(decorator).split(".")[-1] == "dataclass" for decorator in node.decorator_list)

            for stmt in node.body:  # pragma: no branch
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    field_name = stmt.target.id
                    field_names.append(field_name)
                    if is_dataclass:
                        has_default = self._dataclass_field_has_default(stmt.value)
                        if self._dataclass_field_is_init_enabled(stmt.value):
                            dataclass_init_params.append(field_name)
                            if not has_default:
                                dataclass_required_params.append(field_name)
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:  # pragma: no branch
                        if isinstance(target, ast.Name):  # pragma: no branch
                            class_attributes.append(target.id)
                elif isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
                    signature = self._call_signature_details(stmt, skip_first_param=True)
                    init_params = signature["params"]
                    constructor_min_args = signature["min_args"]
                    constructor_max_args = signature["max_args"]
                    class_attributes.extend(self._self_assigned_attributes(stmt))
                elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and not stmt.name.startswith("_"):  # pragma: no branch
                    signature = self._call_signature_details(stmt, skip_first_param=True)
                    params = ["self", *signature["params"]]
                    methods.append(f"{stmt.name}({', '.join(params)})")
                    method_signatures[stmt.name] = signature

            constructor_params = init_params or dataclass_init_params or field_names
            if constructor_min_args is None and constructor_max_args is None and is_dataclass:
                constructor_min_args = len(dataclass_required_params)
                constructor_max_args = len(dataclass_init_params)
            classes[node.name] = {
                "name": node.name,
                "bases": bases,
                "is_enum": is_enum,
                "fields": field_names,
                "attributes": sorted(set(class_attributes)),
                "constructor_params": constructor_params,
                "constructor_min_args": constructor_min_args if constructor_min_args is not None else len(constructor_params),
                "constructor_max_args": constructor_max_args if constructor_max_args is not None else len(constructor_params),
                "methods": methods,
                "method_signatures": method_signatures,
            }

        analysis["functions"] = functions
        analysis["classes"] = classes
        analysis["imports"] = sorted(import_roots)
        analysis["third_party_imports"] = [
            module_name for module_name in sorted(import_roots) if self._is_probable_third_party_import(module_name)
        ]
        analysis["module_variables"] = sorted(module_variables)
        analysis["symbols"] = sorted([item["name"] for item in functions] + list(classes.keys()))
        return analysis

    def _dataclass_field_has_default(self, value: Optional[ast.expr]) -> bool:
        if value is None:
            return False
        if not isinstance(value, ast.Call) or self._call_expression_basename(value.func) != "field":
            return True
        if value.args:
            return True
        return any(keyword.arg in {"default", "default_factory"} for keyword in value.keywords)

    def _dataclass_field_is_init_enabled(self, value: Optional[ast.expr]) -> bool:
        if not isinstance(value, ast.Call) or self._call_expression_basename(value.func) != "field":
            return True
        for keyword in value.keywords:
            if keyword.arg != "init":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, bool):
                return keyword.value.value
            return True
        return True

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
                if constructor:
                    lines.append(
                        f"  tests must instantiate with all listed constructor fields explicitly: {constructor}"
                    )
                if methods:
                    lines.append(f"  methods: {methods}")
        else:
            lines.append("Classes:\n- none")

        lines.append(
            f"Entrypoint: {'python ' + 'MODULE_FILE' if code_analysis.get('has_main_guard') else 'no __main__ entrypoint detected'}"
        )
        return "\n".join(lines)

    def _build_code_exact_test_contract(self, code_analysis: Dict[str, Any]) -> str:
        if not code_analysis.get("syntax_ok", True):
            return "Exact test contract unavailable because module syntax is invalid."

        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        functions = code_analysis.get("functions") or []
        classes = code_analysis.get("classes") or {}
        preferred_classes = self._preferred_test_class_names(code_analysis)
        exposed_class_names = self._exposed_test_class_names(code_analysis, preferred_classes)
        allowed_imports = sorted(
            [item["name"] for item in functions if item["name"] not in entrypoint_names]
            + exposed_class_names
        )
        exact_method_refs: list[str] = []
        constructor_refs: list[str] = []

        for class_name in exposed_class_names:
            class_info = classes[class_name]
            constructor_params = class_info.get("constructor_params") or []
            if constructor_params:
                constructor_refs.append(f"{class_name}({', '.join(constructor_params)})")
            for method_name in class_info.get("methods") or []:
                if method_name.startswith("_"):
                    continue
                exact_method_refs.append(f"{class_name}.{method_name}")

        callable_refs = [
            item["signature"]
            for item in functions
            if item["name"] not in entrypoint_names
        ]

        lines = ["Exact test contract:"]
        lines.append(f"- Allowed production imports: {', '.join(allowed_imports or ['none'])}")
        lines.append(f"- Preferred service or workflow facades: {', '.join(preferred_classes or ['none'])}")
        lines.append(f"- Exact public callables: {', '.join(callable_refs or ['none'])}")
        lines.append(f"- Exact public class methods: {', '.join(exact_method_refs or ['none'])}")
        lines.append(f"- Exact constructor fields: {', '.join(constructor_refs or ['none'])}")
        lines.append(
            "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
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

    def _entrypoint_class_names(self, code_analysis: Dict[str, Any]) -> set[str]:
        class_names = set((code_analysis.get("classes") or {}).keys())
        return {
            name
            for name in class_names
            if name.lower().endswith("cli") or name.lower().endswith("_cli") or name.lower().endswith("demo")
        }

    def _entrypoint_symbol_names(self, code_analysis: Dict[str, Any]) -> set[str]:
        return self._entrypoint_function_names(code_analysis) | self._entrypoint_class_names(code_analysis)

    def _exposed_test_class_names(
        self,
        code_analysis: Dict[str, Any],
        preferred_classes: Optional[list[str]] = None,
    ) -> list[str]:
        class_map = code_analysis.get("classes") or {}
        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        preferred = preferred_classes or self._preferred_test_class_names(code_analysis)
        helper_classes_to_avoid = set(self._helper_classes_to_avoid(code_analysis, preferred))
        return sorted(
            class_name
            for class_name in class_map.keys()
            if class_name not in entrypoint_names and class_name not in helper_classes_to_avoid
        )

    def _build_code_test_targets(self, code_analysis: Dict[str, Any]) -> str:
        if not code_analysis.get("syntax_ok", True):
            return "Test targets unavailable because module syntax is invalid."

        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        preferred_classes = self._preferred_test_class_names(code_analysis)
        helper_classes_to_avoid = self._helper_classes_to_avoid(code_analysis, preferred_classes)
        batch_capable_functions = [
            item["signature"]
            for item in code_analysis.get("functions") or []
            if item["name"] not in entrypoint_names and item.get("accepts_sequence_input")
        ]
        scalar_functions = [
            item["signature"]
            for item in code_analysis.get("functions") or []
            if item["name"] not in entrypoint_names and not item.get("accepts_sequence_input")
        ]
        testable_functions = [
            item["signature"]
            for item in code_analysis.get("functions") or []
            if item["name"] not in entrypoint_names
        ]
        classes = self._exposed_test_class_names(code_analysis, preferred_classes)
        lines = ["Test targets:"]
        lines.append(f"- Functions to test: {', '.join(testable_functions or ['none'])}")
        lines.append(f"- Batch-capable functions: {', '.join(batch_capable_functions or ['none'])}")
        lines.append(f"- Scalar-only functions: {', '.join(scalar_functions or ['none'])}")
        lines.append(f"- Classes to test: {', '.join(classes or ['none'])}")
        lines.append(f"- Preferred workflow classes: {', '.join(preferred_classes or ['none'])}")
        lines.append(
            f"- Helper classes to avoid in compact workflow tests: {', '.join(helper_classes_to_avoid or ['none'])}"
        )
        lines.append(f"- Entry points to avoid in tests: {', '.join(sorted(entrypoint_names) or ['none'])}")
        return "\n".join(lines)

    def _preferred_test_class_names(self, code_analysis: Dict[str, Any]) -> list[str]:
        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        workflow_method_prefixes = (
            "process_",
            "validate_",
            "intake_",
            "handle_",
            "submit_",
            "batch_",
            "export_",
        )
        preferred: list[str] = []
        for class_name, class_info in sorted((code_analysis.get("classes") or {}).items()):
            if class_name in entrypoint_names:
                continue
            method_names = list((class_info.get("method_signatures") or {}).keys())
            if any(method_name.startswith(workflow_method_prefixes) for method_name in method_names):
                preferred.append(class_name)
        return preferred

    def _constructor_param_matches_class(self, param_name: str, class_name: str) -> bool:
        normalized_param = param_name.strip().lower()
        if not normalized_param:
            return False

        snake_name = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
        candidate_names = {snake_name}
        parts = snake_name.split("_")
        if len(parts) > 2:
            for start in range(1, len(parts) - 1):
                candidate_names.add("_".join(parts[start:]))

        if normalized_param in candidate_names:
            return True

        suffix = snake_name.split("_")[-1]
        return suffix in {"logger", "repository", "service"} and normalized_param == suffix

    def _helper_classes_to_avoid(
        self,
        code_analysis: Dict[str, Any],
        preferred_classes: Optional[list[str]] = None,
    ) -> list[str]:
        preferred = set(preferred_classes or self._preferred_test_class_names(code_analysis))
        if not preferred:
            return []
        class_map = code_analysis.get("classes") or {}
        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        helper_suffixes = ("service", "repository", "logger")
        required_constructor_helpers: set[str] = set()
        for preferred_name in preferred:
            class_info = class_map.get(preferred_name) or {}
            constructor_params = [
                param_name
                for param_name in (class_info.get("constructor_params") or [])
                if isinstance(param_name, str)
            ]
            for helper_name in class_map.keys():
                if helper_name in preferred or helper_name in entrypoint_names:
                    continue
                if not helper_name.lower().endswith(helper_suffixes):
                    continue
                if any(
                    self._constructor_param_matches_class(param_name, helper_name)
                    for param_name in constructor_params
                ):
                    required_constructor_helpers.add(helper_name)
        helper_names: list[str] = []
        for class_name in sorted(class_map.keys()):
            if class_name in entrypoint_names or class_name in preferred or class_name in required_constructor_helpers:
                continue
            if class_name.lower().endswith(helper_suffixes):
                helper_names.append(class_name)
        return helper_names

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
        constructor_storage_rules: list[str] = []
        score_derivation_rules: list[str] = []
        sequence_input_rules: list[str] = []
        function_map: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                function_nodes = [stmt for stmt in node.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_nodes = [node]
            else:
                continue

            for function_node in function_nodes:
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

        for function_node in function_map.values():
            constructor_storage_rule = self._extract_constructor_storage_rule(function_node)
            if constructor_storage_rule:
                constructor_storage_rules.append(constructor_storage_rule)

        for function_node in function_map.values():
            score_derivation_rule = self._extract_score_derivation_rule(function_node, function_map)
            if score_derivation_rule:
                score_derivation_rules.append(score_derivation_rule)

        for function_node in function_map.values():
            sequence_rule = self._extract_sequence_input_rule(function_node)
            if sequence_rule:
                sequence_input_rules.append(sequence_rule)

        if not (
            validation_rules
            or field_value_rules
            or batch_rules
            or constructor_storage_rules
            or score_derivation_rules
            or sequence_input_rules
        ):
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
        for rule in sorted(dict.fromkeys(constructor_storage_rules)):
            lines.append(f"- {rule}")
        for rule in sorted(dict.fromkeys(score_derivation_rules)):
            lines.append(f"- {rule}")
        for rule in sorted(sequence_input_rules):
            lines.append(f"- {rule}")
        for rule in batch_rules:
            lines.append(f"- {rule}")
        return "\n".join(lines)

    def _extract_constructor_storage_rule(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        first_parameter = self._first_user_parameter(node)
        if first_parameter is None:
            return ""

        source_name = first_parameter.arg
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            constructor_name = self._ast_name(child.func)
            if not constructor_name:
                continue
            for keyword in child.keywords:
                if keyword.arg != "data":
                    continue
                if isinstance(keyword.value, ast.Name) and keyword.value.id == source_name:
                    return f"{node.name} stores full {source_name} in returned {constructor_name}.data"
        return ""

    def _extract_score_derivation_rule(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    ) -> str:
        score_expression_node: Optional[ast.expr] = None

        for child in ast.walk(node):
            if not isinstance(child, ast.Assign) or len(child.targets) != 1:
                continue
            target = child.targets[0]
            if isinstance(target, ast.Name) and target.id == "score":
                score_expression_node = child.value
                break

        if score_expression_node is not None:
            if not self._function_returns_score_value(node):
                return ""
            score_expression = self._render_score_expression(
                self._expand_local_name_aliases(score_expression_node, node),
                function_map,
            )
            if not score_expression:
                return ""
            return f"{node.name} derives score from {score_expression}"

        if "score" not in node.name.lower():
            return ""

        return_expression = self._direct_return_expression(node)
        if return_expression is None:
            return ""
        score_expression = self._render_score_expression(
            self._expand_local_name_aliases(return_expression, node),
            function_map,
        )
        if not score_expression:
            return ""
        return f"{node.name} derives score from {score_expression}"

    def _function_returns_score_value(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and isinstance(child.value, ast.Name) and child.value.id == "score":
                return True
            if not isinstance(child, ast.Call):
                continue
            if any(
                keyword.arg == "score" and isinstance(keyword.value, ast.Name) and keyword.value.id == "score"
                for keyword in child.keywords
            ):
                return True
            if child.args and isinstance(child.args[0], ast.Name) and child.args[0].id == "score":
                return True
        return False

    def _render_score_expression(
        self,
        expression: ast.expr,
        function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    ) -> str:
        rendered_expression = self._inline_score_helper_expression(expression, function_map)
        try:
            return ast.unparse(rendered_expression).strip()
        except Exception:  # pragma: no cover - ast.unparse is available on supported versions
            return self._ast_name(rendered_expression)

    def _inline_score_helper_expression(
        self,
        expression: ast.expr,
        function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    ) -> ast.expr:
        if not isinstance(expression, ast.Call):
            return expression

        helper_name = self._call_expression_basename(expression.func)
        if not helper_name:
            return expression
        helper_node = function_map.get(helper_name)
        if helper_node is None:
            return expression

        helper_return_expression = self._direct_return_expression(helper_node)
        if helper_return_expression is None:
            return expression
        helper_return_expression = self._expand_local_name_aliases(helper_return_expression, helper_node)

        parameter_names = self._callable_parameter_names(helper_node)
        replacements: dict[str, ast.expr] = {}
        for parameter_name, argument in zip(parameter_names, expression.args):
            replacements[parameter_name] = argument
        for keyword in expression.keywords:
            if keyword.arg is None or keyword.arg not in parameter_names:
                continue
            replacements[keyword.arg] = keyword.value

        if not replacements:
            return expression

        replacer = _AstNameReplacer(replacements)
        inlined_expression = replacer.visit(copy.deepcopy(helper_return_expression))
        if isinstance(inlined_expression, ast.expr):
            return ast.fix_missing_locations(inlined_expression)
        return expression

    def _expand_local_name_aliases(
        self,
        expression: ast.expr,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> ast.expr:
        replacements: dict[str, ast.expr] = {}
        for statement in node.body:
            if isinstance(statement, ast.Return):
                break
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            target = statement.targets[0]
            if not isinstance(target, ast.Name):
                continue
            expanded_value = _AstNameReplacer(replacements).visit(copy.deepcopy(statement.value))
            if isinstance(expanded_value, ast.expr):
                replacements[target.id] = ast.fix_missing_locations(expanded_value)

        if not replacements:
            return expression

        expanded_expression = _AstNameReplacer(replacements).visit(copy.deepcopy(expression))
        if isinstance(expanded_expression, ast.expr):
            return ast.fix_missing_locations(expanded_expression)
        return expression

    def _call_expression_basename(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""

    def _direct_return_expression(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[ast.expr]:
        for statement in node.body:
            if isinstance(statement, ast.Return) and statement.value is not None:
                return statement.value
        return None

    def _callable_parameter_names(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        positional = [*node.args.posonlyargs, *node.args.args]
        if positional and positional[0].arg in {"self", "cls"}:
            positional = positional[1:]
        return [argument.arg for argument in positional]

    def _extract_sequence_input_rule(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        first_parameter = self._first_user_parameter(node)
        if first_parameter is None:
            return ""
        annotation = self._ast_name(first_parameter.annotation) if first_parameter.annotation is not None else ""
        if self._annotation_accepts_sequence_input(annotation):
            return f"{node.name} accepts sequence inputs via parameter `{first_parameter.arg}`"
        if self._parameter_is_iterated(node, first_parameter.arg):
            return f"{node.name} accepts sequence inputs via parameter `{first_parameter.arg}`"
        return ""

    def _first_user_parameter(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[ast.arg]:
        positional = [*node.args.posonlyargs, *node.args.args]
        if positional and positional[0].arg in {"self", "cls"}:
            positional = positional[1:]
        return positional[0] if positional else None

    def _annotation_accepts_sequence_input(self, annotation: str) -> bool:
        normalized = annotation.replace(" ", "").lower()
        if not normalized:
            return False
        return any(
            marker in normalized
            for marker in (
                "list[",
                "typing.list",
                "sequence[",
                "typing.sequence",
                "iterable[",
                "typing.iterable",
                "tuple[",
                "set[",
                "collections.abc.sequence",
                "collections.abc.iterable",
            )
        )

    def _parameter_is_iterated(self, node: ast.FunctionDef | ast.AsyncFunctionDef, parameter_name: str) -> bool:
        for child in ast.walk(node):
            if not isinstance(child, ast.For):
                continue
            iterator = child.iter
            if isinstance(iterator, ast.Name) and iterator.id == parameter_name:
                return True
        return False

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
            if stmt.targets[0].id != "required_fields" or not isinstance(stmt.value, (ast.List, ast.Set, ast.Tuple)):
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
            elif isinstance(child.func, ast.Attribute):  # pragma: no branch
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
                elif isinstance(nested.func, ast.Attribute):  # pragma: no branch
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
                        if isinstance(request_key, str):  # pragma: no branch
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
                        if isinstance(request_key, str):  # pragma: no branch
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
            "call_arity_mismatches": [],
            "constructor_arity_mismatches": [],
            "payload_contract_violations": [],
            "non_batch_sequence_calls": [],
            "helper_surface_usages": [],
            "reserved_fixture_names": [],
            "undefined_fixtures": [],
            "undefined_local_names": [],
            "imported_entrypoint_symbols": [],
            "unsafe_entrypoint_calls": [],
            "unsupported_mock_assertions": [],
            "top_level_test_count": 0,
            "fixture_count": 0,
            "assertion_like_count": 0,
            "tests_without_assertions": [],
            "contract_overreach_signals": [],
        }
        if not raw_content.strip():
            return analysis
        try:
            tree = ast.parse(raw_content)
        except SyntaxError as exc:
            analysis["syntax_ok"] = False
            analysis["syntax_error"] = f"{exc.msg} at line {exc.lineno}"
            return analysis

        module_symbols = set(code_analysis.get("symbols") or []) | set(code_analysis.get("module_variables") or [])
        function_names = {item["name"] for item in code_analysis.get("functions") or []}
        function_map = {item["name"]: item for item in code_analysis.get("functions") or []}
        class_map = code_analysis.get("classes") or {}
        helper_classes_to_avoid = set(self._helper_classes_to_avoid(code_analysis))
        module_defined_names = self._collect_module_defined_names(tree)
        entrypoint_names = self._entrypoint_symbol_names(code_analysis)
        validation_rules, field_value_rules, batch_rules, sequence_input_functions = self._parse_behavior_contract(
            code_behavior_contract
        )
        analysis["top_level_test_count"] = sum(
            1
            for stmt in tree.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("test_")
        )
        analysis["fixture_count"] = sum(
            1
            for stmt in tree.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and self._is_pytest_fixture(stmt)
        )

        imported_symbols: set[str] = set()
        called_names: list[tuple[str, int]] = []
        attribute_refs: list[tuple[str, str, int]] = []
        constructor_calls: list[tuple[str, int, int]] = []
        call_arity_mismatches: list[str] = []
        defined_fixtures: set[str] = set()
        reserved_fixture_names: list[str] = []
        referenced_fixtures: list[tuple[str, int]] = []
        undefined_local_names: set[str] = set()
        unsafe_entrypoint_calls: list[str] = []
        assertion_like_count = 0
        tests_without_assertions: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == module_name:
                for alias in node.names:
                    imported_symbols.add(alias.asname or alias.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._is_pytest_fixture(node):
                    defined_fixtures.add(node.name)
                    undefined_local_names.update(
                        self._collect_undefined_local_names(node, module_defined_names)
                    )
                    if node.name in _RESERVED_FIXTURE_NAMES:
                        reserved_fixture_names.append(f"{node.name} (line {node.lineno})")
                if node.name.startswith("test_"):
                    test_assertion_like_count = self._count_test_assertion_like_checks(node)
                    assertion_like_count += test_assertion_like_count
                    if test_assertion_like_count == 0:
                        tests_without_assertions.append(f"{node.name} (line {node.lineno})")
                    parametrized_arguments = self._collect_parametrized_argument_names(node)
                    for arg_name in self._function_argument_names(node):
                        if arg_name not in parametrized_arguments:
                            referenced_fixtures.append((arg_name, node.lineno))
                    undefined_local_names.update(
                        self._collect_undefined_local_names(node, module_defined_names)
                    )
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.append((node.func.id, node.lineno))
                    if node.func.id in class_map:
                        constructor_calls.append((node.func.id, len(node.args) + len(node.keywords), node.lineno))
                    if node.func.id in imported_symbols and node.func.id in entrypoint_names:
                        unsafe_entrypoint_calls.append(f"{node.func.id}() (line {node.lineno})")
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):  # pragma: no branch
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
        unsupported_mock_assertions: list[str] = []
        contract_overreach_signals: list[str] = []
        for owner, member, lineno in attribute_refs:
            if owner not in imported_symbols or owner not in class_map:
                continue
            class_info = class_map[owner]
            allowed = set(class_info.get("attributes") or [])
            if not class_info.get("is_enum"):
                allowed.update(class_info.get("fields") or [])
            allowed.update((class_info.get("method_signatures") or {}).keys())
            if member not in allowed:
                invalid_member_refs.append(f"{owner}.{member} (line {lineno})")

        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            bindings = self._collect_local_bindings(node)
            local_types = self._collect_test_local_types(node, class_map, function_map)
            typed_invalid_refs, typed_arity_mismatches = self._analyze_typed_test_member_usage(
                node,
                local_types,
                class_map,
                function_map,
            )
            invalid_member_refs.extend(typed_invalid_refs)
            call_arity_mismatches.extend(typed_arity_mismatches)
            unsupported_mock_assertions.extend(
                self._find_unsupported_mock_assertions(node, local_types, class_map)
            )
            contract_overreach_signals.extend(
                self._find_contract_overreach_signals(
                    node,
                    bindings,
                    code_behavior_contract if isinstance(code_behavior_contract, str) else "",
                )
            )

        arity_mismatches: list[str] = []
        for class_name, actual_count, lineno in constructor_calls:
            class_info = class_map.get(class_name, {})
            expected_params = class_info.get("constructor_params") or []
            min_expected = class_info.get("constructor_min_args")
            max_expected = class_info.get("constructor_max_args")
            if not isinstance(min_expected, int) or not isinstance(max_expected, int):
                min_expected = len(expected_params)
                max_expected = len(expected_params)
            if min_expected <= actual_count <= max_expected:
                continue
            if min_expected == max_expected:
                arity_mismatches.append(
                    f"{class_name} expects {max_expected} args but test uses {actual_count} at line {lineno}"
                )
                continue
            arity_mismatches.append(
                f"{class_name} expects {min_expected}-{max_expected} args but test uses {actual_count} at line {lineno}"
            )

        undefined_fixtures = sorted(
            {
                f"{fixture_name} (line {lineno})"
                for fixture_name, lineno in referenced_fixtures
                if fixture_name not in defined_fixtures and fixture_name not in _PYTEST_BUILTIN_FIXTURES
            }
        )
        imported_entrypoint_symbols = sorted(symbol for symbol in imported_symbols if symbol in entrypoint_names)
        helper_surface_usages = sorted(
            {symbol for symbol in imported_symbols if symbol in helper_classes_to_avoid}
            | {
                f"{name} (line {lineno})"
                for name, lineno in called_names
                if name in helper_classes_to_avoid
            }
        )
        payload_contract_violations, non_batch_sequence_calls = self._analyze_test_behavior_contracts(
            tree,
            validation_rules,
            field_value_rules,
            batch_rules,
            sequence_input_functions,
            function_names,
            class_map,
        )

        analysis["imported_module_symbols"] = sorted(imported_symbols)
        analysis["missing_function_imports"] = missing_imports
        analysis["unknown_module_symbols"] = unknown_symbols
        analysis["invalid_member_references"] = sorted(set(invalid_member_refs))
        analysis["call_arity_mismatches"] = sorted(set(call_arity_mismatches))
        analysis["constructor_arity_mismatches"] = sorted(set(arity_mismatches))
        analysis["payload_contract_violations"] = payload_contract_violations
        analysis["non_batch_sequence_calls"] = non_batch_sequence_calls
        analysis["helper_surface_usages"] = helper_surface_usages
        analysis["reserved_fixture_names"] = sorted(set(reserved_fixture_names))
        analysis["undefined_fixtures"] = undefined_fixtures
        analysis["undefined_local_names"] = sorted(undefined_local_names)
        analysis["imported_entrypoint_symbols"] = imported_entrypoint_symbols
        analysis["unsafe_entrypoint_calls"] = sorted(set(unsafe_entrypoint_calls))
        analysis["unsupported_mock_assertions"] = sorted(set(unsupported_mock_assertions))
        analysis["assertion_like_count"] = assertion_like_count
        analysis["tests_without_assertions"] = sorted(set(tests_without_assertions))
        analysis["contract_overreach_signals"] = sorted(set(contract_overreach_signals))
        return analysis

    def _parse_behavior_contract(
        self,
        contract: str,
    ) -> tuple[Dict[str, list[str]], Dict[str, Dict[str, list[str]]], Dict[str, Dict[str, Any]], set[str]]:
        validation_rules: Dict[str, list[str]] = {}
        field_value_rules: Dict[str, Dict[str, list[str]]] = {}
        batch_rules: Dict[str, Dict[str, Any]] = {}
        sequence_input_functions: set[str] = set()
        if not contract.strip():
            return validation_rules, field_value_rules, batch_rules, sequence_input_functions

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

            sequence_input_match = re.match(r"-\s+(\w+) accepts sequence inputs via parameter `([^`]+)`$", line)
            if sequence_input_match:
                sequence_input_functions.add(sequence_input_match.group(1))
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
            if wrapper_match:  # pragma: no branch
                batch_rules[wrapper_match.group(1)] = {
                    "request_key": None,
                    "wrapper_key": wrapper_match.group(2),
                    "fields": [field.strip() for field in wrapper_match.group(3).split(",") if field.strip()],
                }

        return validation_rules, field_value_rules, batch_rules, sequence_input_functions

    def _analyze_test_behavior_contracts(
        self,
        tree: ast.AST,
        validation_rules: Dict[str, list[str]],
        field_value_rules: Dict[str, Dict[str, list[str]]],
        batch_rules: Dict[str, Dict[str, Any]],
        sequence_input_functions: set[str],
        function_names: set[str],
        class_map: Dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        payload_violations: set[str] = set()
        non_batch_calls: set[str] = set()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue

            bindings = self._collect_local_bindings(node)
            parent_map = self._parent_map(node)
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                callable_name = self._callable_name(child)
                if not callable_name:
                    continue
                negative_expectation = self._call_has_negative_expectation(child, parent_map)
                invalid_outcome_expectation = negative_expectation or self._call_expects_invalid_outcome(
                    node,
                    child,
                    parent_map,
                )

                if callable_name in validation_rules:
                    payload_arg = self._payload_argument_for_validation(child, callable_name)
                    payload_node = self._resolve_bound_value(payload_arg, bindings)
                    payload_keys = self._extract_literal_dict_keys(payload_node, bindings, class_map)
                    if payload_keys is not None:
                        missing_fields = [field for field in validation_rules[callable_name] if field not in payload_keys]
                        if missing_fields and not invalid_outcome_expectation:  # pragma: no branch
                            payload_violations.add(
                                f"{callable_name} payload missing required fields: {', '.join(missing_fields)} at line {child.lineno}"
                            )

                if callable_name in field_value_rules:
                    payload_arg = self._payload_argument_for_validation(child, callable_name)
                    payload_node = self._resolve_bound_value(payload_arg, bindings)
                    for field_name, allowed_values in field_value_rules[callable_name].items():
                        observed_values = self._extract_literal_field_values(payload_node, bindings, field_name, class_map)
                        invalid_values = [value for value in observed_values if value not in allowed_values]
                        if invalid_values and not invalid_outcome_expectation:
                            payload_violations.add(
                                f"{callable_name} field `{field_name}` uses unsupported values: {', '.join(invalid_values)} at line {child.lineno}"
                            )

                if callable_name in batch_rules:
                    batch_allows_partial_invalid = self._batch_call_allows_partial_invalid_items(
                        node,
                        child,
                        bindings,
                        parent_map,
                    )
                    batch_violations = [] if negative_expectation or batch_allows_partial_invalid else self._validate_batch_call(
                        child,
                        bindings,
                        callable_name,
                        batch_rules[callable_name],
                    )
                    payload_violations.update(batch_violations)
                    continue

                if callable_name in sequence_input_functions:
                    continue

                if callable_name in function_names and "batch" not in callable_name:
                    sequence_arg = self._first_call_argument(child)
                    sequence_node = self._resolve_bound_value(sequence_arg, bindings)
                    if isinstance(sequence_node, ast.List):
                        non_batch_calls.add(
                            f"{callable_name} does not accept batch/list inputs at line {child.lineno}"
                        )

        return sorted(payload_violations), sorted(non_batch_calls)

    def _parent_map(self, root: ast.AST) -> Dict[ast.AST, ast.AST]:
        return {
            child: parent
            for parent in ast.walk(root)
            for child in ast.iter_child_nodes(parent)
        }

    def _call_has_negative_expectation(self, node: ast.Call, parent_map: Dict[ast.AST, ast.AST]) -> bool:
        current: Optional[ast.AST] = node
        while current is not None:
            parent = parent_map.get(current)
            if parent is None:
                return False
            if isinstance(parent, ast.Assert) and self._assert_expects_false(parent, node):
                return True
            if isinstance(parent, (ast.With, ast.AsyncWith)) and self._with_uses_pytest_raises(parent):
                return True
            current = parent
        return False

    def _call_expects_invalid_outcome(
        self,
        test_node: ast.FunctionDef | ast.AsyncFunctionDef,
        call_node: ast.Call,
        parent_map: Dict[ast.AST, ast.AST],
    ) -> bool:
        result_name = self._assigned_name_for_call(call_node, parent_map)
        payload_arg = self._first_call_argument(call_node)
        payload_name = payload_arg.id if isinstance(payload_arg, ast.Name) else None

        for child in ast.walk(test_node):
            if not isinstance(child, ast.Assert) or getattr(child, "lineno", 0) <= getattr(call_node, "lineno", 0):
                continue
            if self._assert_expects_invalid_outcome(child.test, result_name, payload_name):
                return True
        return False

    def _assert_expects_invalid_outcome(
        self,
        node: ast.AST,
        result_name: Optional[str],
        payload_name: Optional[str],
    ) -> bool:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self._invalid_outcome_subject_matches(node.operand, result_name, payload_name)

        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            return False
        if not isinstance(node.ops[0], (ast.Eq, ast.Is)):
            return False

        left = node.left
        right = node.comparators[0]
        return (
            self._invalid_outcome_subject_matches(left, result_name, payload_name)
            and self._invalid_outcome_marker_matches(right)
        ) or (
            self._invalid_outcome_subject_matches(right, result_name, payload_name)
            and self._invalid_outcome_marker_matches(left)
        )

    def _invalid_outcome_subject_matches(
        self,
        node: ast.AST,
        result_name: Optional[str],
        payload_name: Optional[str],
    ) -> bool:
        if result_name and isinstance(node, ast.Name) and node.id == result_name:
            return True
        if (
            result_name is not None
            and isinstance(node, ast.Attribute)
            and node.attr in {"status", "state", "outcome", "result", "valid", "is_valid", "success", "accepted"}
            and isinstance(node.value, ast.Name)
            and node.value.id == result_name
        ):
            return True
        return (
            payload_name is not None
            and isinstance(node, ast.Attribute)
            and node.attr in {"status", "state", "outcome", "result", "valid", "is_valid", "success", "accepted"}
            and isinstance(node.value, ast.Name)
            and node.value.id == payload_name
        )

    def _invalid_outcome_marker_matches(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Constant):
            return False
        if node.value is False or node.value is None:
            return True
        return isinstance(node.value, str) and node.value.strip().lower() in {
            "invalid",
            "failed",
            "error",
            "pending",
            "rejected",
            "reject",
        }

    def _batch_call_allows_partial_invalid_items(
        self,
        test_node: ast.FunctionDef | ast.AsyncFunctionDef,
        call_node: ast.Call,
        bindings: Dict[str, ast.AST],
        parent_map: Dict[ast.AST, ast.AST],
    ) -> bool:
        batch_items = self._extract_literal_list_items(self._first_call_argument(call_node), bindings)
        if batch_items is None or len(batch_items) <= 1:
            return False

        result_name = self._assigned_name_for_call(call_node, parent_map)
        batch_size = len(batch_items)
        for child in ast.walk(test_node):
            if not isinstance(child, ast.Assert):
                continue
            if self._assert_limits_batch_result(child.test, result_name, call_node, batch_size):
                return True
        return False

    def _assigned_name_for_call(self, call_node: ast.Call, parent_map: Dict[ast.AST, ast.AST]) -> Optional[str]:
        parent = parent_map.get(call_node)
        if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
            return parent.targets[0].id
        if isinstance(parent, ast.AnnAssign) and isinstance(parent.target, ast.Name):
            return parent.target.id
        return None

    def _assert_limits_batch_result(
        self,
        test: ast.AST,
        result_name: Optional[str],
        call_node: ast.Call,
        batch_size: int,
    ) -> bool:
        if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
            return False
        op = test.ops[0]

        if self._len_call_matches_batch_result(test.left, result_name, call_node):
            compared_value = self._int_constant_value(test.comparators[0])
            return self._comparison_implies_partial_batch_result(op, compared_value, batch_size)

        if self._len_call_matches_batch_result(test.comparators[0], result_name, call_node):
            compared_value = self._int_constant_value(test.left)
            reversed_op = {
                ast.Lt: ast.Gt,
                ast.LtE: ast.GtE,
                ast.Gt: ast.Lt,
                ast.GtE: ast.LtE,
            }.get(type(op), type(op))
            return self._comparison_implies_partial_batch_result(reversed_op(), compared_value, batch_size)

        return False

    def _len_call_matches_batch_result(
        self,
        node: ast.AST,
        result_name: Optional[str],
        call_node: ast.Call,
    ) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if not isinstance(node.func, ast.Name) or node.func.id != "len" or len(node.args) != 1:
            return False
        candidate = node.args[0]
        if result_name is not None and isinstance(candidate, ast.Name) and candidate.id == result_name:
            return True
        return candidate is call_node

    def _int_constant_value(self, node: ast.AST) -> Optional[int]:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        return None

    def _comparison_implies_partial_batch_result(
        self,
        op: ast.cmpop,
        compared_value: Optional[int],
        batch_size: int,
    ) -> bool:
        if compared_value is None:
            return False
        if isinstance(op, ast.Eq):
            return compared_value < batch_size
        if isinstance(op, ast.Lt):
            return compared_value <= batch_size
        if isinstance(op, ast.LtE):
            return compared_value < batch_size
        return False

    @staticmethod
    def _test_name_suggests_validation_failure(test_name: str) -> bool:
        normalized_test_name = test_name.lower()
        return any(
            token in normalized_test_name
            for token in ("validation", "invalid", "reject", "failure", "error")
        )

    @staticmethod
    def _is_internal_score_state_target(rendered_target: str) -> bool:
        normalized_target = rendered_target.replace(" ", "").lower()
        if "score" not in normalized_target:
            return False
        if not ("." in normalized_target or "get_" in normalized_target):
            return False
        return bool(
            re.search(r"\.(?:get_)?(?:risk_)?scores?\b", normalized_target)
            or any(
                token in normalized_target
                for token in (
                    "score_record",
                    "score_records",
                    "score_cache",
                    "score_map",
                )
            )
        )

    @staticmethod
    def _behavior_contract_explicitly_limits_score_state_to_valid_requests(
        code_behavior_contract: str,
        rendered_target: str,
    ) -> bool:
        normalized_target = rendered_target.replace(" ", "").lower()
        if "risk_score" not in normalized_target:
            return False

        normalized_contract = code_behavior_contract.lower()
        if not re.search(r"risk[_ ]scores?", normalized_contract):
            return False

        return bool(
            re.search(r"risk[_ ]scores?.*\bonly\b.*\bvalid\b", normalized_contract)
            or re.search(r"appends?.*risk[_ ]scores?.*\bonly\b.*\bvalid\b", normalized_contract)
            or re.search(r"only\s+valid\s+requests?.*risk[_ ]scores?", normalized_contract)
            or re.search(r"valid\s+requests?.*append.*risk[_ ]scores?", normalized_contract)
        )

    def _find_contract_overreach_signals(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        bindings: Dict[str, ast.AST],
        code_behavior_contract: str = "",
    ) -> list[str]:
        visible_batch_sizes = self._visible_repeated_single_call_batch_sizes(node, bindings)
        signals: set[str] = set()
        largest_batch_size = max(visible_batch_sizes) if visible_batch_sizes else None
        for child in ast.walk(node):
            if not isinstance(child, ast.Assert):
                continue
            exact_len_assertion = self._exact_len_assertion(child.test)
            if exact_len_assertion is None:
                continue
            asserted_target, compared_value = exact_len_assertion
            normalized_target = asserted_target.replace(" ", "").lower()
            if largest_batch_size is not None and (
                "audit_log" in normalized_target or "audit_logs" in normalized_target
            ):
                if compared_value > largest_batch_size:
                    signals.add(
                        f"exact batch audit length {compared_value} exceeds visible batch size {largest_batch_size} in {node.name} (line {child.lineno})"
                    )

            if not self._test_name_suggests_validation_failure(node.name):
                continue
            if compared_value != 0:
                continue
            if not self._is_internal_score_state_target(asserted_target):
                continue
            if self._behavior_contract_explicitly_limits_score_state_to_valid_requests(
                code_behavior_contract,
                asserted_target,
            ):
                continue
            signals.add(
                "exact validation-failure score-state emptiness assertion on "
                f"'{asserted_target}' in {node.name} (line {child.lineno}) assumes rejected input leaves internal score state empty"
            )
        return sorted(signals)

    def _visible_repeated_single_call_batch_sizes(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        bindings: Dict[str, ast.AST],
    ) -> list[int]:
        batch_sizes: list[int] = []
        for child in ast.walk(node):
            if not isinstance(child, (ast.For, ast.AsyncFor)):
                continue
            batch_items = self._extract_literal_list_items(child.iter, bindings)
            if batch_items is None or len(batch_items) <= 1:
                continue
            if not self._loop_contains_non_batch_call(child):
                continue
            batch_sizes.append(len(batch_items))
        return batch_sizes

    def _loop_contains_non_batch_call(self, node: ast.AST) -> bool:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            callable_name = self._callable_name(child)
            if not callable_name or callable_name == "len":
                continue
            if "batch" in callable_name.lower():
                continue
            return True
        return False

    def _exact_len_assertion(self, node: ast.AST) -> Optional[tuple[str, int]]:
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            return None
        if not isinstance(node.ops[0], ast.Eq):
            return None

        left = node.left
        right = node.comparators[0]
        if self._is_len_call(left):
            compared_value = self._int_constant_value(right)
            if compared_value is None:
                return None
            left_call = cast(ast.Call, left)
            return self._render_expression(left_call.args[0]), compared_value
        if self._is_len_call(right):
            compared_value = self._int_constant_value(left)
            if compared_value is None:
                return None
            right_call = cast(ast.Call, right)
            return self._render_expression(right_call.args[0]), compared_value
        return None

    def _is_len_call(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and len(node.args) == 1
            and not node.keywords
        )

    def _assert_expects_false(self, node: ast.Assert, call_node: ast.Call) -> bool:
        test = node.test
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return self._ast_contains_node(test.operand, call_node)
        if not isinstance(test, ast.Compare):
            return False

        def false_constant(item: ast.AST) -> bool:
            return isinstance(item, ast.Constant) and item.value is False

        if self._ast_contains_node(test.left, call_node):
            return any(false_constant(comparator) for comparator in test.comparators) and any(
                isinstance(op, (ast.Is, ast.Eq)) for op in test.ops
            )
        if any(self._ast_contains_node(comparator, call_node) for comparator in test.comparators):
            return false_constant(test.left) and any(isinstance(op, (ast.Is, ast.Eq)) for op in test.ops)
        return False

    def _with_uses_pytest_raises(self, node: ast.With | ast.AsyncWith) -> bool:
        for item in node.items:
            context_expr = item.context_expr
            if not isinstance(context_expr, ast.Call):
                continue
            callable_name = self._callable_name(context_expr)
            if callable_name == "raises":
                return True
        return False

    def _with_uses_pytest_assertion_context(self, node: ast.With | ast.AsyncWith) -> bool:
        for item in node.items:
            context_expr = item.context_expr
            if not isinstance(context_expr, ast.Call):
                continue
            callable_name = self._callable_name(context_expr)
            if callable_name in {"raises", "warns", "deprecated_call"}:
                return True
        return False

    def _count_test_assertion_like_checks(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        assertion_like_count = 0
        mock_bindings, patched_targets = self._collect_mock_support(node)

        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                assertion_like_count += 1
                continue
            if isinstance(child, (ast.With, ast.AsyncWith)) and self._with_uses_pytest_assertion_context(child):
                assertion_like_count += 1
                continue

            target_node: Optional[ast.AST] = None
            if isinstance(child, ast.Attribute) and child.attr in _MOCK_ASSERTION_ATTRIBUTES:
                target_node = child.value
            elif (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _MOCK_ASSERTION_METHODS
            ):
                target_node = child.func.value

            if target_node is None:
                continue
            if self._supports_mock_assertion_target(target_node, mock_bindings, patched_targets):
                assertion_like_count += 1

        return assertion_like_count

    def _ast_contains_node(self, root: ast.AST, target: ast.AST) -> bool:
        return any(candidate is target for candidate in ast.walk(root))

    def _collect_local_bindings(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, ast.AST]:
        bindings: Dict[str, ast.AST] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                bindings[stmt.targets[0].id] = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
                bindings[stmt.target.id] = stmt.value
        return bindings

    def _collect_module_defined_names(self, tree: ast.AST) -> set[str]:
        if not isinstance(tree, ast.Module):
            return set()

        names: set[str] = set()
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(stmt.name)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                for alias in stmt.names:
                    if alias.name != "*":
                        names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    names.update(self._bound_target_names(target))
            elif isinstance(stmt, ast.AnnAssign):
                names.update(self._bound_target_names(stmt.target))
        return names

    def _function_argument_names(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        names = {
            arg.arg
            for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        }
        if node.args.vararg is not None:
            names.add(node.args.vararg.arg)
        if node.args.kwarg is not None:
            names.add(node.args.kwarg.arg)
        return names

    def _collect_parametrized_argument_names(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> set[str]:
        names: set[str] = set()
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute) or func.attr != "parametrize":
                continue
            parent = func.value
            if not (
                (isinstance(parent, ast.Attribute) and parent.attr == "mark")
                or (isinstance(parent, ast.Name) and parent.id == "mark")
            ):
                continue
            names.update(self._extract_parametrize_argument_names(decorator))
        return names

    def _extract_parametrize_argument_names(self, decorator: ast.Call) -> set[str]:
        argnames_node: Optional[ast.AST] = decorator.args[0] if decorator.args else None
        if argnames_node is None:
            for keyword in decorator.keywords:
                if keyword.arg == "argnames":
                    argnames_node = keyword.value
                    break
        if isinstance(argnames_node, ast.Constant) and isinstance(argnames_node.value, str):
            return {name.strip() for name in argnames_node.value.split(",") if name.strip()}
        if isinstance(argnames_node, (ast.List, ast.Tuple)):
            return {
                element.value.strip()
                for element in argnames_node.elts
                if isinstance(element, ast.Constant)
                and isinstance(element.value, str)
                and element.value.strip()
            }
        return set()

    def _collect_undefined_local_names(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        module_defined_names: set[str],
    ) -> list[str]:
        allowed_names = set(dir(builtins))
        allowed_names.update(module_defined_names)
        allowed_names.update(self._collect_local_name_bindings(node))

        undefined_names: set[str] = set()
        for stmt in node.body:
            for child in self._iter_relevant_test_body_nodes(stmt):
                if not isinstance(child, ast.Name) or not isinstance(child.ctx, ast.Load):
                    continue
                if child.id in allowed_names:
                    continue
                undefined_names.add(f"{child.id} (line {child.lineno})")
        return sorted(undefined_names)

    def _collect_local_name_bindings(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        names = self._function_argument_names(node)
        names.update(self._collect_parametrized_argument_names(node))

        for stmt in node.body:
            for child in self._iter_relevant_test_body_nodes(stmt):
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        names.update(self._bound_target_names(target))
                elif isinstance(child, ast.AnnAssign):
                    names.update(self._bound_target_names(child.target))
                elif isinstance(child, ast.AugAssign):
                    names.update(self._bound_target_names(child.target))
                elif isinstance(child, (ast.For, ast.AsyncFor)):
                    names.update(self._bound_target_names(child.target))
                elif isinstance(child, (ast.With, ast.AsyncWith)):
                    for item in child.items:
                        if item.optional_vars is not None:
                            names.update(self._bound_target_names(item.optional_vars))
                elif isinstance(child, ast.ExceptHandler) and child.name:
                    names.add(child.name)
                elif isinstance(child, ast.NamedExpr):
                    names.update(self._bound_target_names(child.target))
                elif isinstance(child, ast.comprehension):
                    names.update(self._bound_target_names(child.target))
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    for alias in child.names:
                        if alias.name != "*":
                            names.add(alias.asname or alias.name.split(".")[0])
        return names

    def _call_signature_details(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        skip_first_param: bool = False,
    ) -> Dict[str, Any]:
        positional_args = [*node.args.posonlyargs, *node.args.args]
        if skip_first_param and positional_args:
            positional_args = positional_args[1:]
        keyword_only_args = list(node.args.kwonlyargs)
        positional_params = [arg.arg for arg in positional_args]
        keyword_only_params = [arg.arg for arg in keyword_only_args]
        params = [*positional_params, *keyword_only_params]
        param_annotations = [
            self._ast_name(arg.annotation) if arg.annotation is not None else None
            for arg in [*positional_args, *keyword_only_args]
        ]
        optional_positional = len(node.args.defaults)
        optional_kwonly = sum(default is not None for default in node.args.kw_defaults)
        max_args = len(params)
        min_args = max(0, max_args - optional_positional - optional_kwonly)
        accepts_sequence_input = bool(param_annotations) and self._annotation_accepts_sequence_input(
            param_annotations[0] or ""
        )
        return {
            "params": params,
            "param_annotations": param_annotations,
            "min_args": min_args,
            "max_args": max_args,
            "accepts_sequence_input": accepts_sequence_input,
            "return_annotation": self._ast_name(node.returns) if node.returns is not None else None,
        }

    def _self_assigned_attributes(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        attributes: list[str] = []
        for child in ast.walk(node):
            targets: list[ast.AST] = []
            if isinstance(child, ast.Assign):
                targets.extend(child.targets)
            elif isinstance(child, ast.AnnAssign):
                targets.append(child.target)
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                    attributes.append(target.attr)
        return attributes

    def _call_argument_count(self, node: ast.Call) -> int:
        return len(node.args) + sum(1 for keyword in node.keywords if keyword.arg is not None)

    def _infer_expression_type(
        self,
        node: Optional[ast.AST],
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
        function_map: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        if isinstance(node, ast.Name):
            owner_type = local_types.get(node.id)
            return owner_type if owner_type in class_map else None
        if isinstance(node, ast.Call):
            return self._infer_call_result_type(node, local_types, class_map, function_map)
        return None

    def _collect_test_local_types(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_map: Dict[str, Any],
        function_map: Dict[str, Dict[str, Any]],
    ) -> Dict[str, str]:
        local_types: Dict[str, str] = {}
        for stmt in node.body:
            for child in ast.walk(stmt):
                if isinstance(child, ast.Assign):
                    inferred_type = self._infer_call_result_type(child.value, local_types, class_map, function_map)
                    if inferred_type is None:
                        continue
                    for target in child.targets:
                        for name in self._bound_target_names(target):
                            local_types[name] = inferred_type
                elif isinstance(child, ast.AnnAssign):
                    inferred_type = self._infer_call_result_type(child.value, local_types, class_map, function_map)
                    if inferred_type is None:
                        continue
                    for name in self._bound_target_names(child.target):
                        local_types[name] = inferred_type
        return local_types

    def _find_unsupported_mock_assertions(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
    ) -> list[str]:
        mock_bindings, patched_targets = self._collect_mock_support(node)
        issues: set[str] = set()

        for child in ast.walk(node):
            member_node: Optional[ast.Attribute] = None
            target_node: Optional[ast.AST] = None

            if isinstance(child, ast.Attribute) and child.attr in _MOCK_ASSERTION_ATTRIBUTES:
                member_node = child
                target_node = child.value
            elif (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _MOCK_ASSERTION_METHODS
            ):
                member_node = child.func
                target_node = child.func.value

            if member_node is None or target_node is None:
                continue
            if self._known_type_allows_member(member_node, local_types, class_map):
                continue
            if self._supports_mock_assertion_target(target_node, mock_bindings, patched_targets):
                continue
            issues.add(f"{self._render_expression(child)} (line {getattr(child, 'lineno', '?')})")

        return sorted(issues)

    def _collect_mock_support(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> tuple[set[str], set[str]]:
        mock_bindings = {
            name
            for name in self._function_argument_names(node)
            if name == "mocker" or name.startswith("mock")
        }
        patched_targets: set[str] = set()

        for stmt in node.body:
            for child in self._iter_relevant_test_body_nodes(stmt):
                if isinstance(child, ast.Assign):
                    value = child.value
                    if self._is_mock_factory_call(value) or self._is_patch_call(value):
                        for target in child.targets:
                            mock_bindings.update(self._bound_target_names(target))
                    if isinstance(value, ast.Call) and self._is_patch_call(value):
                        patched_target = self._patched_target_name_from_call(value)
                        if patched_target:
                            patched_targets.add(patched_target)
                elif isinstance(child, ast.AnnAssign) and child.value is not None:
                    value = child.value
                    if self._is_mock_factory_call(value) or self._is_patch_call(value):
                        mock_bindings.update(self._bound_target_names(child.target))
                    if isinstance(value, ast.Call) and self._is_patch_call(value):
                        patched_target = self._patched_target_name_from_call(value)
                        if patched_target:
                            patched_targets.add(patched_target)
                elif isinstance(child, (ast.With, ast.AsyncWith)):
                    for item in child.items:
                        context_expr = item.context_expr
                        if not isinstance(context_expr, ast.Call) or not self._is_patch_call(context_expr):
                            continue
                        patched_target = self._patched_target_name_from_call(context_expr)
                        if patched_target:
                            patched_targets.add(patched_target)
                        if item.optional_vars is not None:
                            mock_bindings.update(self._bound_target_names(item.optional_vars))

        return mock_bindings, patched_targets

    def _supports_mock_assertion_target(
        self,
        node: ast.AST,
        mock_bindings: set[str],
        patched_targets: set[str],
    ) -> bool:
        target_name = self._attribute_chain(node)
        root_name = self._expression_root_name(node)
        if root_name and (root_name in mock_bindings or root_name.startswith("mock")):
            return True
        if target_name and target_name in patched_targets:
            return True
        return False

    def _known_type_allows_member(
        self,
        node: ast.Attribute,
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
    ) -> bool:
        if not isinstance(node.value, ast.Name):
            return False
        owner_name = node.value.id
        owner_type = local_types.get(owner_name)
        if owner_type not in class_map and owner_name in class_map:
            owner_type = owner_name
        if owner_type not in class_map:
            return False
        class_info = class_map.get(owner_type, {})
        allowed = set(class_info.get("attributes") or [])
        if not class_info.get("is_enum"):
            allowed.update(class_info.get("fields") or [])
        allowed.update((class_info.get("method_signatures") or {}).keys())
        return node.attr in allowed

    def _is_mock_factory_call(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        callable_name = self._attribute_chain(node.func)
        if not callable_name:
            return False
        return callable_name in {"Mock", "MagicMock", "AsyncMock", "create_autospec"} or any(
            callable_name.endswith(suffix)
            for suffix in (
                ".Mock",
                ".MagicMock",
                ".AsyncMock",
                ".create_autospec",
            )
        )

    def _is_patch_call(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        callable_name = self._attribute_chain(node.func)
        if not callable_name:
            return False
        return (
            callable_name == "patch"
            or callable_name.endswith(".patch")
            or callable_name == "patch.object"
            or callable_name.endswith(".patch.object")
        )

    def _patched_target_name_from_call(self, node: ast.Call) -> Optional[str]:
        callable_name = self._attribute_chain(node.func)
        if not callable_name:
            return None
        if callable_name == "patch.object" or callable_name.endswith(".patch.object"):
            target_node = node.args[0] if len(node.args) >= 1 else None
            attribute_node = node.args[1] if len(node.args) >= 2 else None
            if target_node is None:
                for keyword in node.keywords:
                    if keyword.arg == "target":
                        target_node = keyword.value
                    elif keyword.arg in {"attribute", "name", "attr"}:
                        attribute_node = keyword.value
            target_name = self._attribute_chain(target_node) if target_node is not None else ""
            if (
                target_name
                and isinstance(attribute_node, ast.Constant)
                and isinstance(attribute_node.value, str)
            ):
                return f"{target_name}.{attribute_node.value}"
            return None
        target_node = self._first_call_argument(node)
        if isinstance(target_node, ast.Constant) and isinstance(target_node.value, str):
            return target_node.value
        return None

    def _infer_call_result_type(
        self,
        node: Optional[ast.AST],
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
        function_map: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        if not isinstance(node, ast.Call):
            return None
        if isinstance(node.func, ast.Name):
            if node.func.id in class_map:
                return node.func.id
            function_info = function_map.get(node.func.id)
            if not isinstance(function_info, dict):
                return None
            return_annotation = function_info.get("return_annotation")
            return return_annotation if isinstance(return_annotation, str) and return_annotation in class_map else None
        if not isinstance(node.func, ast.Attribute):
            return None
        owner_type = self._infer_expression_type(node.func.value, local_types, class_map, function_map)
        if owner_type not in class_map:
            return None
        method_info = (class_map.get(owner_type, {}).get("method_signatures") or {}).get(node.func.attr)
        if not isinstance(method_info, dict):
            return None
        return_annotation = method_info.get("return_annotation")
        return return_annotation if isinstance(return_annotation, str) and return_annotation in class_map else None

    def _analyze_typed_test_member_usage(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        local_types: Dict[str, str],
        class_map: Dict[str, Any],
        function_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[list[str], list[str]]:
        invalid_member_refs: set[str] = set()
        call_arity_mismatches: set[str] = set()
        resolved_function_map = function_map or {}
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                owner_type = self._infer_expression_type(
                    child.func.value,
                    local_types,
                    class_map,
                    resolved_function_map,
                )
                if owner_type not in class_map:
                    continue
                method_info = (class_map.get(owner_type, {}).get("method_signatures") or {}).get(child.func.attr)
                if not isinstance(method_info, dict):
                    invalid_member_refs.add(f"{owner_type}.{child.func.attr} (line {child.lineno})")
                    continue
                actual_count = self._call_argument_count(child)
                min_expected = method_info.get("min_args")
                max_expected = method_info.get("max_args")
                if not isinstance(min_expected, int) or not isinstance(max_expected, int):
                    continue
                if min_expected <= actual_count <= max_expected:
                    continue
                if min_expected == max_expected:
                    call_arity_mismatches.add(
                        f"{owner_type}.{child.func.attr} expects {max_expected} args but test uses {actual_count} at line {child.lineno}"
                    )
                else:
                    call_arity_mismatches.add(
                        f"{owner_type}.{child.func.attr} expects {min_expected}-{max_expected} args but test uses {actual_count} at line {child.lineno}"
                    )
            elif isinstance(child, ast.Attribute):
                owner_type = self._infer_expression_type(
                    child.value,
                    local_types,
                    class_map,
                    resolved_function_map,
                )
                if owner_type not in class_map:
                    continue
                class_info = class_map.get(owner_type, {})
                allowed = set(class_info.get("attributes") or [])
                if not class_info.get("is_enum"):
                    allowed.update(class_info.get("fields") or [])
                allowed.update((class_info.get("method_signatures") or {}).keys())
                if child.attr not in allowed:
                    invalid_member_refs.add(f"{owner_type}.{child.attr} (line {child.lineno})")
        return sorted(invalid_member_refs), sorted(call_arity_mismatches)

    def _iter_relevant_test_body_nodes(self, node: ast.AST):
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            yield from self._iter_relevant_test_body_nodes(child)

    def _bound_target_names(self, target: ast.AST) -> set[str]:
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, ast.Starred):
            return self._bound_target_names(target.value)
        if isinstance(target, (ast.List, ast.Tuple)):
            names: set[str] = set()
            for element in target.elts:
                names.update(self._bound_target_names(element))
            return names
        return set()

    def _callable_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""

    def _attribute_chain(self, node: Optional[ast.AST]) -> str:
        if node is None:
            return ""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._attribute_chain(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            base = self._attribute_chain(node.func)
            return f"{base}()" if base else ""
        return ""

    def _expression_root_name(self, node: ast.AST) -> Optional[str]:
        current = node
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Call):
            current = current.func
            while isinstance(current, ast.Attribute):
                current = current.value
        if isinstance(current, ast.Name):
            return current.id
        return None

    def _render_expression(self, node: ast.AST) -> str:
        try:
            return ast.unparse(node)
        except Exception:  # pragma: no cover - ast.unparse is available on supported versions
            return self._attribute_chain(node) or node.__class__.__name__

    def _first_call_argument(self, node: ast.Call) -> Optional[ast.expr]:
        if node.args:
            return node.args[0]
        if node.keywords:
            return node.keywords[0].value
        return None

    def _payload_argument_for_validation(self, node: ast.Call, callable_name: str) -> Optional[ast.expr]:
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
            for candidate_name in ("data", "payload", "request", "item"):  # pragma: no branch
                candidate_value = self._call_argument_value(resolved, candidate_name, class_map or {})
                nested_keys = self._extract_literal_dict_keys(candidate_value, bindings, class_map)
                if nested_keys is not None:  # pragma: no branch
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
        if isinstance(resolved, ast.Call):  # pragma: no branch
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
                if isinstance(func, ast.Attribute) and func.attr == "fixture":  # pragma: no branch
                    return True
        return False

    def _build_test_validation_summary(
        self,
        test_analysis: Dict[str, Any],
        test_execution: Optional[Dict[str, Any]] = None,
        completion_diagnostics: Optional[Dict[str, Any]] = None,
    ) -> str:
        lines = ["Generated test validation:"]
        syntax_ok = test_analysis.get("syntax_ok", True)
        static_contract_overreach_signals = test_analysis.get("contract_overreach_signals") or []
        runtime_contract_overreach_signals = self._pytest_contract_overreach_signals(test_execution)
        contract_overreach_signals = sorted(
            set(static_contract_overreach_signals) | set(runtime_contract_overreach_signals)
        )
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
                f"- Call arity mismatches: {', '.join(test_analysis.get('call_arity_mismatches') or ['none'])}"
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
                f"- Helper surface usages: {', '.join(test_analysis.get('helper_surface_usages') or ['none'])}"
            )
            lines.append(
                f"- Reserved fixture names: {', '.join(test_analysis.get('reserved_fixture_names') or ['none'])}"
            )
            lines.append(
                f"- Undefined test fixtures: {', '.join(test_analysis.get('undefined_fixtures') or ['none'])}"
            )
            lines.append(
                f"- Undefined local names: {', '.join(test_analysis.get('undefined_local_names') or ['none'])}"
            )
            lines.append(
                f"- Tests without assertion-like checks: {', '.join(test_analysis.get('tests_without_assertions') or ['none'])}"
            )
            lines.append(
                f"- Contract overreach signals: {', '.join(contract_overreach_signals or ['none'])}"
            )
        if isinstance(completion_diagnostics, dict):
            lines.append(
                f"- Completion diagnostics: {self._completion_diagnostics_summary(completion_diagnostics)}"
            )
        if syntax_ok:
            lines.append(
                f"- Imported entrypoint symbols: {', '.join(test_analysis.get('imported_entrypoint_symbols') or ['none'])}"
            )
            lines.append(
                f"- Unsafe entrypoint calls: {', '.join(test_analysis.get('unsafe_entrypoint_calls') or ['none'])}"
            )
            lines.append(
                f"- Unsupported mock assertions: {', '.join(test_analysis.get('unsupported_mock_assertions') or ['none'])}"
            )
        if isinstance(test_execution, dict):
            if not test_execution.get("available", True):
                lines.append(f"- Pytest execution: unavailable ({test_execution.get('summary') or 'pytest unavailable'})")
            elif test_execution.get("ran"):
                lines.append(
                    f"- Pytest execution: {'PASS' if test_execution.get('returncode') == 0 else 'FAIL'}"
                )
                lines.append(f"- Pytest summary: {test_execution.get('summary') or 'none'}")
                failure_details = self._pytest_failure_details(test_execution)
                if failure_details:
                    lines.append(f"- Pytest failure details: {'; '.join(failure_details)}")

        has_static_issues = (not syntax_ok) or (
            isinstance(line_count, int)
            and isinstance(line_budget, int)
            and line_count > line_budget
        ) or (
            isinstance(top_level_test_count, int)
            and isinstance(expected_top_level_test_count, int)
            and top_level_test_count != expected_top_level_test_count
        ) or (
            isinstance(top_level_test_count, int)
            and isinstance(max_top_level_test_count, int)
            and top_level_test_count > max_top_level_test_count
        ) or (
            isinstance(fixture_count, int)
            and isinstance(fixture_budget, int)
            and fixture_count > fixture_budget
        ) or any(
            test_analysis.get(key)
            for key in (
                "missing_function_imports",
                "unknown_module_symbols",
                "invalid_member_references",
                "call_arity_mismatches",
                "constructor_arity_mismatches",
                "contract_overreach_signals",
                "payload_contract_violations",
                "non_batch_sequence_calls",
                "reserved_fixture_names",
                "undefined_fixtures",
                "undefined_local_names",
                "tests_without_assertions",
                "imported_entrypoint_symbols",
                "unsafe_entrypoint_calls",
                "unsupported_mock_assertions",
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
        if isinstance(node, ast.Subscript):
            value_name = self._ast_name(node.value)
            slice_name = self._ast_name(node.slice)
            if value_name and slice_name:
                return f"{value_name}[{slice_name}]"
            return value_name
        if isinstance(node, ast.Tuple):
            return ", ".join(filter(None, (self._ast_name(element) for element in node.elts)))
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
            return str(node.value)
        return ""

    def _build_agent_input(self, task: Task, project: ProjectState) -> AgentInput:
        context = self._build_context(task, project)
        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        task_description = task.description
        if repair_context:
            repair_lines = [task.description, "", "Repair objective:", str(repair_context.get("instruction") or "Repair the previous failure."), "", f"Previous failure category: {repair_context.get('failure_category') or FailureCategory.UNKNOWN.value}"]
            source_failure_task_id = repair_context.get("source_failure_task_id")
            if isinstance(source_failure_task_id, str) and source_failure_task_id.strip():
                repair_lines.append(f"Source failure task: {source_failure_task_id}")
            source_failure_category = repair_context.get("source_failure_category")
            if isinstance(source_failure_category, str) and source_failure_category.strip():
                repair_lines.append(f"Source failure category: {source_failure_category}")
            failure_message = repair_context.get("failure_message")
            if isinstance(failure_message, str) and failure_message.strip():
                repair_lines.append(f"Previous failure message: {failure_message}")
            validation_summary = repair_context.get("validation_summary")
            if isinstance(validation_summary, str) and validation_summary.strip():
                repair_lines.extend(["", "Validation summary:", validation_summary])
            budget_decomposition_brief = context.get("budget_decomposition_brief")
            if isinstance(budget_decomposition_brief, str) and budget_decomposition_brief.strip():
                repair_lines.extend(["", "Budget decomposition brief:", budget_decomposition_brief])
            repair_focus_lines = self._repair_focus_lines(repair_context, context)
            if repair_focus_lines:
                repair_lines.extend(["", "Repair priorities:"])
                repair_lines.extend(f"- {line}" for line in repair_focus_lines)
            task_description = "\n".join(repair_lines)
        return AgentInput(
            task_id=task.id,
            task_title=redact_sensitive_text(task.title),
            task_description=redact_sensitive_text(task_description),
            project_name=redact_sensitive_text(project.project_name),
            project_goal=redact_sensitive_text(project.goal),
            context=context,
        )

    def _repair_focus_lines(
        self,
        repair_context: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> list[str]:
        failure_category = repair_context.get("failure_category")
        validation_summary = repair_context.get("validation_summary")
        if not isinstance(validation_summary, str) or not validation_summary.strip():
            return []

        failed_artifact_content = repair_context.get("failed_artifact_content")
        failed_content_lower = (
            failed_artifact_content.lower()
            if isinstance(failed_artifact_content, str)
            else ""
        )
        missing_datetime_import_issue = self._validation_summary_has_missing_datetime_import_issue(
            validation_summary,
            failed_artifact_content,
        )
        required_evidence_runtime_issue = self._validation_summary_has_required_evidence_runtime_issue(
            validation_summary,
            failed_artifact_content,
            context.get("code", "") if isinstance(context, dict) else "",
        )
        dataclass_order_examples = self._dataclass_default_order_repair_examples(
            failed_artifact_content,
        )
        duplicate_constructor_argument_details = self._duplicate_constructor_argument_details(
            validation_summary,
        )
        duplicate_constructor_call_hint = self._duplicate_constructor_argument_call_hint(
            validation_summary,
            failed_artifact_content,
        )
        duplicate_constructor_explicit_rewrite_hint = self._duplicate_constructor_explicit_rewrite_hint(
            validation_summary,
            failed_artifact_content,
        )
        missing_attribute_details = self._missing_object_attribute_details(
            validation_summary,
            failed_artifact_content,
        )
        nested_payload_wrapper_details = self._nested_payload_wrapper_field_validation_details(
            validation_summary,
            failed_artifact_content,
        )
        constructor_strictness_details = self._internal_constructor_strictness_details(
            validation_summary,
            failed_artifact_content,
        )
        required_evidence_items = self._implementation_required_evidence_items(
            context.get("code", "") if isinstance(context, dict) else ""
        )

        summary_lower = validation_summary.lower()
        lines: list[str] = []
        if failure_category == FailureCategory.CODE_VALIDATION.value:
            if "task public contract: fail" in summary_lower:
                lines.append(
                    "Treat the task public contract anchor as exact. Restore the named public facade, request model, and required workflow or validation methods before making secondary refactors."
                )
                lines.append(
                    "Do not rename the public facade, request model, or required workflow surface to guessed aliases. Match the anchor-defined surface first, then repair behavior under that same surface."
                )
            if "pytest failure details:" in summary_lower:
                lines.append(
                    "Treat the listed pytest failures as exact behavior requirements for the implementation. Fix the module so each cited assertion passes without changing the valid test surface."
                )
            if "assertionerror" in summary_lower or " - assert " in summary_lower:
                lines.append(
                    "When the summary shows an exact boolean, numeric, or returned-value mismatch, change the implementation until that exact expectation holds; do not stop at a nearby constant tweak if the same assertion would still fail."
                )
            if "pytest execution: fail" in summary_lower or "pytest failed:" in summary_lower:
                lines.append(
                    "Preserve the documented public API and repair the module behavior itself instead of renaming helpers, reshaping return values, or shifting the failure onto the tests."
                )
                lines.append(
                    "Repair the implementation module itself. Return only importable module code, not pytest test functions, copied test bodies, or bare assertion snippets from the tests context."
                )
                lines.append(
                    "If the task requires a CLI or demo entrypoint, preserve or restore a minimal main() plus a literal if __name__ == \"__main__\": block while fixing the cited behavior. Do not drop the entrypoint just to save lines."
                )
            if duplicate_constructor_argument_details is not None:
                class_name, field_name = duplicate_constructor_argument_details
                lines.append(
                    f"If pytest reports TypeError from {class_name}.__init__() saying it got multiple values for argument '{field_name}', do not pass {field_name} both positionally and through **request.details, **request.data, **payload, or a duplicated keyword."
                )
                lines.append(
                    f"When {field_name} is extracted separately before constructing {class_name}(...), remove it from any expanded mapping or switch to explicit keyword construction so each constructor field is bound exactly once."
                )
                if duplicate_constructor_call_hint:
                    lines.append(
                        f"The exact broken call {duplicate_constructor_call_hint} still appears in the failed artifact. Do not return that call unchanged; rewrite that construction so {field_name} is bound once and that exact call disappears from the final module."
                    )
                if duplicate_constructor_call_hint and duplicate_constructor_explicit_rewrite_hint:
                    lines.append(
                        f"For this failed artifact, rewrite {duplicate_constructor_call_hint} to {duplicate_constructor_explicit_rewrite_hint} or an equivalent explicit constructor call that binds each field once and supplies safe defaults for fields omitted by valid inputs."
                    )
            if missing_attribute_details is not None:
                class_name, attribute_name, class_fields = missing_attribute_details
                replacement_field = self._suggest_declared_attribute_replacement(attribute_name, class_fields)
                lines.append(
                    f"If pytest reports AttributeError that '{class_name}' has no attribute '{attribute_name}', align the model fields and member accesses so every referenced attribute is actually declared or derived on that object."
                )
                if class_fields:
                    lines.append(
                        f"{class_name} currently defines {self._render_name_list(class_fields)}. If you keep .{attribute_name} in the rewritten module, add {attribute_name} to {class_name} and populate or derive it where {class_name} objects are created. Otherwise replace that access with one of the declared fields and remove every remaining read of .{attribute_name}."
                    )
                    if replacement_field:
                        lines.append(
                            f"The closest declared field is {replacement_field}. Prefer replacing .{attribute_name} with .{replacement_field} rather than preserving an undeclared near-match attribute."
                        )
                else:
                    lines.append(
                        f"If you keep .{attribute_name} in the rewritten module, declare it on {class_name} and populate or derive it where {class_name} objects are created. Otherwise remove every read of .{attribute_name} and use an existing declared field instead."
                    )
            if nested_payload_wrapper_details is not None:
                container_name, offending_fields, validation_line = nested_payload_wrapper_details
                rendered_fields = self._render_name_list(offending_fields)
                lines.append(
                    f"The current failed artifact still treats {rendered_fields} as required keys inside request.{container_name}. Keep those wrapper fields on the request object and reserve request.{container_name} checks for actual payload keys only."
                )
                if validation_line:
                    lines.append(
                        f"Do not return the broken validation line `{validation_line}` unchanged. Replace it with wrapper-field checks on the request object plus only true payload-key validation inside request.{container_name}."
                    )
            if constructor_strictness_details is not None:
                class_name, missing_fields, required_fields = constructor_strictness_details
                rendered_missing_fields = self._render_name_list(missing_fields)
                lines.append(
                    f"If valid happy-path or batch pytest cases fail with TypeError from {class_name}.__init__(), the implementation is stricter than the documented contract. Align that internal model with validate_request(...) and the cited valid inputs instead of pushing new required payload keys onto the tests."
                )
                if required_fields:
                    lines.append(
                        f"The current validator only requires {self._render_name_list(required_fields)}, so do not make {class_name}(...) additionally require {rendered_missing_fields}. Derive those internal values or give them safe defaults when building the internal record."
                    )
                else:
                    lines.append(
                        f"Do not make {class_name}(...) additionally require {rendered_missing_fields} when those fields are not part of the documented valid input contract. Derive them or give them safe defaults when building the internal record."
                    )
            if "follows default argument" in summary_lower:
                lines.append(
                    "If a dataclass or typed record model fails with a 'non-default argument ... follows default argument' error, reorder the fields so every required non-default field appears before any field with a default while preserving the documented constructor contract."
                )
                lines.append(
                    "Inspect every dataclass declaration in the failed module, including audit, review, and result record types. This import error can come from a helper record class even when the anchored request model already matches the public contract."
                )
                lines.append(
                    "Example: declare AuditLog(action, details, timestamp=field(default_factory=...)) rather than placing timestamp before the required details field."
                )
                lines.extend(dataclass_order_examples)
            if "name 'field' is not defined" in summary_lower:
                lines.append(
                    "If a dataclass uses field(...) or default_factory anywhere in the module, import field explicitly from dataclasses. Do not leave field referenced without that import."
                )
            if (
                "name 'datetime' is not defined" in summary_lower
                or "name 'date' is not defined" in summary_lower
                or "name 'timedelta' is not defined" in summary_lower
                or "name 'timezone' is not defined" in summary_lower
                or (
                    "nameerror" in summary_lower
                    and any(
                        token in failed_content_lower
                        for token in ("datetime.", "timedelta(", "timezone.")
                    )
                )
            ):
                lines.append(
                    "Keep imports consistent with referenced names. If the module calls datetime.datetime.now(), datetime.date.today(), datetime.timedelta(...), or datetime.timezone.utc, import datetime; if it imports symbols directly with `from datetime import datetime, timedelta, timezone`, call datetime.now(), timedelta(...), or timezone.utc instead of datetime.datetime.now(), bare missing helpers, or mismatched module-qualified references. Do not leave module-qualified or bare references pointing at names that were never imported."
                )
            if "assert not true" in summary_lower or "assert true is false" in summary_lower:
                lines.append(
                    "If pytest reports `assert not True` or `assert True is False` for validate_request or another validator, repair the implementation so that the cited invalid sample is actually rejected. Do not leave the validator as a presence-only required-key check when the failing sample already uses a clearly wrong required-field value or type."
                )
                lines.append(
                    "Implement concrete reject conditions for clearly invalid required-field values or types instead of only checking whether every required key is present."
                )
            if (
                "valueerror" in summary_lower
                and "invalid" in summary_lower
                and any(token in summary_lower for token in ("test_happy_path", "test_batch", "test_batch_processing"))
                and "required_fields" in failed_content_lower
                and any(token in failed_content_lower for token in ("request.details", "request.data", "request.metadata", "request.payload"))
            ):
                lines.append(
                    "If happy-path or batch pytest cases now raise `ValueError(...)` after a validator repair, inspect whether the validator started checking wrapper fields on the nested payload container. Keep top-level request fields such as request_id and request_type on the request object, and reserve request.details, request.data, request.metadata, or request.payload checks for actual payload keys only."
                )
                lines.append(
                    "Do not require wrapper fields such as request_id, request_type, details, data, metadata, or payload as keys inside request.details, request.data, request.metadata, or request.payload unless the contract explicitly duplicates them there."
                )
            if "likely truncated" in summary_lower:
                lines.append(
                    "If completion diagnostics say the module output was likely truncated, rewrite the full module from the top instead of patching a partial tail or appending a continuation."
                )
                lines.append(
                    "Restore a complete importable module first, then trim optional helpers, comments, blank lines, and other non-essential scaffolding so the repaired file stays comfortably under the size budget with visible headroom."
                )
            if "typeerror" in summary_lower:
                lines.append(
                    "Keep data-model semantics consistent: if the module defines dataclasses or typed request objects, validate and read them via attributes instead of mapping membership or subscripting unless the public contract explicitly uses dict inputs."
                )
            if "offset-naive and offset-aware datetimes" in summary_lower:
                lines.append(
                    "Normalize every datetime comparison to one timezone convention before comparing timestamps. Do not mix parsed timezone-aware datetimes with naive datetime.now() values in certification, incident, cache, scoring, or audit paths."
                )
                lines.append(
                    "If the cited tests construct naive datetimes with datetime(...), keep compared implementation timestamps naive too or convert both sides consistently before comparison. Every compared datetime in the same branch must share the same timezone awareness."
                )
            if "line count:" in summary_lower:
                lines.append(
                    "Rewrite the full module smaller and leave clear headroom below the reported line ceiling. Remove optional helper layers, repeated convenience wrappers, and non-essential docstrings before touching required behavior."
                )
            return lines

        if failure_category != FailureCategory.TEST_VALIDATION.value:
            return lines

        implementation_code = context.get("code", "") if isinstance(context, dict) else ""
        available_module_symbol_map = {
            name.lower(): name for name in self._module_defined_symbol_names(implementation_code)
        }
        imported_module_symbols = self._validation_summary_symbols(
            validation_summary, "Imported module symbols"
        )
        undefined_local_names = self._normalized_helper_surface_symbols(
            self._validation_summary_symbols(validation_summary, "Undefined local names")
        )
        undefined_available_module_symbols: list[str] = []
        for name in undefined_local_names:
            normalized_name = name.lower()
            if normalized_name in {"pytest", "datetime"}:
                continue
            actual_name = available_module_symbol_map.get(normalized_name)
            if actual_name and actual_name not in imported_module_symbols and actual_name not in undefined_available_module_symbols:
                undefined_available_module_symbols.append(actual_name)
        helper_alias_names = [
            name
            for name in undefined_local_names
            if name not in imported_module_symbols
            and name.lower() not in available_module_symbol_map
            and self._is_helper_alias_like_name(name)
        ]
        unknown_module_symbols = self._validation_summary_symbols(
            validation_summary, "Unknown module symbols"
        )
        previous_member_calls, previous_constructor_keywords = self._previous_valid_test_surface(
            failed_artifact_content, imported_module_symbols
        )

        lines.append(
            "Rewrite the full pytest module from the top, but treat the current implementation artifact and API contract as fixed ground truth. Remove any test, fixture, or helper that is not required by the documented scenarios."
        )
        lines.append(
            "Do not invent replacement classes, functions, validators, return-wrapper types, helper names, or alternate constructor signatures during repair."
        )
        helper_surface_symbols = self._normalized_helper_surface_symbols(
            repair_context.get("helper_surface_symbols")
        )
        if not helper_surface_symbols:
            helper_surface_symbols = self._normalized_helper_surface_symbols(
                repair_context.get("helper_surface_usages")
            )
        if helper_surface_symbols:
            lines.append(
                "Delete every import, fixture, helper variable, and top-level test that references these flagged helper surfaces: "
                f"{', '.join(helper_surface_symbols)}. Do not repair those helper-surface tests in place."
            )
            lines.append(
                "Replace that coverage with the documented higher-level workflow or service surface from the test targets, and do not reintroduce "
                f"{', '.join(helper_surface_symbols)} anywhere in the rewritten file unless the public API contract explicitly makes one of them the primary surface under test."
            )
            lines.append(
                "When the module exposes a higher-level service or workflow facade, keep imports limited to that facade and directly exchanged domain models instead of auxiliary validators, scorers, loggers, repositories, processors, or engines."
            )
            lines.append(
                "Do not replace one guessed helper with another guessed helper during repair. If a helper-surface test was invalid for a name such as ComplianceScorer, ComplianceBatchProcessor, or AuditLogger, delete that helper-oriented test and rebuild around the documented service facade and request or result models only."
            )
        elif "helper surface usages:" in summary_lower:
            lines.append(
                "Delete every import, fixture, helper variable, and top-level test that references the flagged helper surfaces from the validation summary. Do not repair those helper-surface tests in place."
            )
            lines.append(
                "Replace removed helper-surface coverage with the documented higher-level workflow or service surface from the test targets, and do not reintroduce the flagged helper names anywhere in the rewritten file."
            )
            lines.append(
                "When the module exposes a higher-level service or workflow facade, keep imports limited to that facade and directly exchanged domain models instead of auxiliary validators, scorers, loggers, repositories, processors, or engines."
            )
            lines.append(
                "Do not replace one guessed helper with another guessed helper during repair. If a helper-surface test was invalid for a name such as ComplianceScorer, ComplianceBatchProcessor, or AuditLogger, delete that helper-oriented test and rebuild around the documented service facade and request or result models only."
            )
        if any(marker in summary_lower for marker in ("line count:", "top-level test functions:", "fixture count:")):
            lines.append(
                "Reduce scope aggressively: target 3 to 4 top-level tests and no more than 2 fixtures unless the contract explicitly requires more. Count top-level tests and total lines before finalizing, and if you are still over budget, delete helper-only coverage first."
            )
            lines.append(
                "Target clear headroom below the line ceiling instead of landing on the boundary. Strip docstrings, comments, blank lines, and optional helper scaffolding before deleting any required scenario."
            )
            lines.append(
                "Keep only the minimum required scenarios: one happy path, one validation failure, and one batch or audit/integration path unless the contract explicitly requires more. Drop validator, scorer, serialization, logger, and other helper-level tests before cutting any required scenario."
            )
            lines.append(
                "When a compact suite is already over the top-level cap, delete standalone validator, scorer, and audit helper tests before keeping any extra coverage."
            )
        if "top-level test functions:" in summary_lower:
            lines.append(
                "If the validation summary reports too many top-level tests, delete or merge the lowest-value extra scenarios until the rewritten file is back under the stated maximum before addressing optional cleanup. A suite over the hard cap is invalid even when pytest passes."
            )
        assertionless_tests = self._validation_summary_symbols(
            validation_summary,
            "Tests without assertion-like checks",
        )
        if "tests without assertion-like checks:" in summary_lower and "tests without assertion-like checks: none" not in summary_lower:
            lines.append(
                "Every top-level test must contain at least one explicit assertion-like check such as assert ..., with pytest.raises(...), or another direct contract-backed expectation. Rewrite any hollow smoke test that only calls production code without verifying the outcome."
            )
            if assertionless_tests:
                lines.append(
                    "The validation summary already flagged these hollow top-level tests: "
                    f"{', '.join(assertionless_tests)}. Rewrite each named test so it contains at least one direct contract-backed expectation, or delete the test if you cannot assert a stable observable outcome without guessing internals."
                )
                lines.append(
                    "Do not keep a call-only happy-path or batch test. For every named hollow test, assert returned values, raised exceptions, mutated state, audit record growth, or another externally observable outcome instead of only calling production code."
                )
                if len(assertionless_tests) > 1:
                    lines.append(
                        "When more than one top-level test is hollow, discard the current pytest skeleton and rewrite the entire suite from scratch around only the minimum required scenarios instead of patching the previous file in place. Preserve only the valid import surface and constructor shapes from the old suite."
                    )
        if any(marker in summary_lower for marker in ("unknown module symbols:", "missing function imports:", "undefined local names:")):
            lines.append(
                "Use only documented module symbols and explicitly import every production class or function you reference in tests or fixtures."
            )
            lines.append(
                "Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols. If the contract lists BatchProcessor or RiskScorer, do not invent ComplianceBatchProcessor, ComplianceScorer, ComplianceIntake, AuditLogger, or similar aliases."
            )
            lines.append(
                "If you use isinstance or another exact type assertion against a production class, import that class explicitly; otherwise rewrite the assertion to check returned fields or behavior without naming an unimported type."
            )
            if "request.timestamp" in failed_content_lower or "timestamp=request." in failed_content_lower:
                lines.append(
                    "Do not satisfy explicit constructor fields by reading attributes from the object you are still constructing or any other undefined local. Define a self-contained value first and pass it directly, for example timestamp=fixed_time instead of timestamp=request.timestamp."
                )
            if undefined_available_module_symbols:
                lines.append(
                    "The previous file referenced real module symbols without importing them: "
                    f"{', '.join(undefined_available_module_symbols)}. Add those names to the import list from the target module before use instead of deleting, renaming, or leaving them as undefined locals."
                )
            if helper_alias_names:
                rendered_names = ", ".join(helper_alias_names)
                lines.append(
                    "The previous file referenced undefined helper or collaborator aliases outside the documented import surface: "
                    f"{rendered_names}. Delete that guessed helper wiring instead of preserving or patching those aliases in place."
                )
                near_match_pairs: list[str] = []
                for helper_name in helper_alias_names:
                    normalized_helper = helper_name.lower()
                    for symbol in imported_module_symbols:
                        normalized_symbol = symbol.lower()
                        if normalized_symbol == normalized_helper:
                            continue
                        if normalized_symbol in normalized_helper or normalized_helper in normalized_symbol:
                            pair = f"{helper_name} -> {symbol}"
                            if pair not in near_match_pairs:
                                near_match_pairs.append(pair)
                if near_match_pairs:
                    lines.append(
                        "Do not repair those names by swapping to a near-match imported symbol with a different role or constructor contract, such as "
                        f"{', '.join(near_match_pairs)}."
                    )
                lines.append(
                    "Record or value classes such as audit logs, score records, and result objects are not service collaborators unless the contract explicitly says so. Assert on the outputs they produce instead of constructing them as service wiring."
                )
        if "invalid member references:" in summary_lower and "invalid member references: none" not in summary_lower:
            lines.append(
                "When invalid member references are reported, rewrite every method or attribute access to the exact documented public API for that class. Do not call guessed aliases on inline service instances such as ComplianceIntakeService().submit(...) or .submit_batch(...); use only the listed names like submit_intake(...) and batch_submit_intakes(...)."
            )
            lines.append(
                "Do not assume constructor chaining authorizes new member names. If the validation summary names Class.member as invalid, delete or rename that member access exactly as reported until the invalid-member list is empty."
            )
        if "imported entrypoint symbols:" in summary_lower or "unsafe entrypoint calls:" in summary_lower:
            lines.append(
                "Delete imported entrypoint symbols such as main, cli_demo, or similar CLI/demo helpers from the pytest module. Do not import or execute entrypoints in tests; cover only documented service, batch, or domain-model behavior."
            )
        if "undefined local names: pytest" in summary_lower:
            lines.append(
                "If the rewritten suite uses the `pytest.` namespace anywhere, add `import pytest` explicitly at the top of the file. Do not leave `pytest.raises`, `pytest.mark`, or similar helpers unimported."
            )
        if "undefined local names: datetime" in summary_lower or "name 'datetime' is not defined" in summary_lower:
            lines.append(
                "If the rewritten suite keeps any `datetime.now()` call or other bare `datetime` reference, add `from datetime import datetime` or `import datetime` explicitly at the top of the file before finalizing. Otherwise remove every bare datetime reference and use a self-contained timestamp value that still matches the implementation contract."
            )
            lines.append(
                "The current failed suite still contains bare `datetime` constructor arguments without a valid import. Before finalizing, either add the import or remove every bare `datetime.now()` reference; no unresolved bare `datetime` token should remain anywhere in the rewritten file."
            )
            if missing_datetime_import_issue:
                lines.append(
                    "Do not copy the current failed suite forward unchanged. It already contains bare `datetime` references without a matching import, so rebuild the file from the documented contract and deterministic scaffold instead of preserving that invalid import surface."
                )
                if self._implementation_prefers_direct_datetime_import(implementation_code):
                    lines.append(
                        "The current implementation already imports `from datetime import datetime`. Match that style in tests and prefer a local fixed timestamp such as `fixed_time = datetime(2024, 1, 1, 0, 0, 0)` for constructor arguments instead of repeating bare `datetime.now()` calls."
                    )
        if "likely truncated" in summary_lower:
            lines.append(
                "If completion diagnostics say the previous pytest output was likely truncated, discard the partial tail and rewrite the complete pytest module from the top before reintroducing any optional assertions or fixtures."
            )
            lines.append(
                "Rebuild the minimum contract-backed suite first and leave visible headroom below the line, test-count, and fixture budgets before adding extra assertions."
            )
        if "constructor arity mismatches:" in summary_lower and "constructor arity mismatches: none" not in summary_lower:
            lines.append(
                "When constructor arity mismatches are reported, remove guessed helper wiring and rebuild the suite around the smallest documented public service or function surface using only listed constructor signatures."
            )
            lines.append(
                "Instantiate typed request or result models with the exact field names and full constructor arity listed in the API contract instead of inventing generic placeholders such as id, data, timestamp, or status. Pass every documented constructor field explicitly, including trailing defaulted fields, unless the contract explicitly shows omission as valid."
            )
            lines.append(
                "Do not rely on dataclass defaults just because omission would run. If the contract lists defaulted fields such as timestamp and status, pass them explicitly in every constructor call. Example: ComplianceRequest(id=\"1\", data={\"name\": \"John Doe\", \"amount\": 1000}, timestamp=1.0, status=\"pending\")."
            )
            lines.append(
                "When the mismatch report names multiple lines for the same constructor, rewrite every constructor call for that type in the file until the mismatch list is empty."
            )
        if "payload contract violations:" in summary_lower and "payload contract violations: none" not in summary_lower:
            lines.append(
                "When a called API expects a payload or filter dict with documented required fields, either provide every required field or omit that optional payload entirely. Do not keep partial dicts that the contract does not permit."
            )
        if "non-batch sequence calls:" in summary_lower:
            lines.append(
                "Keep scalar functions scalar: do not pass lists into single-request validators or scorers. Use the real batch API or iterate over valid single items."
            )
        if "reserved fixture names:" in summary_lower:
            lines.append("Never define a custom fixture named request.")
        if "unsupported mock assertions:" in summary_lower:
            lines.append(
                "Do not use mock-style assertion bookkeeping unless the same test installs the exact mock or patch target first."
            )
        if "pytest execution: fail" in summary_lower or "pytest failed:" in summary_lower:
            lines.append(
                "If the previous suite already passed static validation, preserve its valid imports, constructor shapes, fixture payload structure, and scenario skeleton unless the validation summary explicitly says one of those pieces is wrong."
            )
            if imported_module_symbols and not unknown_module_symbols:
                lines.append(
                    "The previous suite already used a statically valid production import surface: "
                    f"{', '.join(imported_module_symbols)}. Preserve that exact production symbol set during repair unless the validation summary explicitly marks one of those imports invalid."
                )
                lines.append(
                    "Do not swap a previously valid documented symbol for a guessed alias or renamed service class. If the valid suite imported ComplianceIntakeService, do not replace it with ComplianceService or another invented variant just because pytest failed elsewhere."
                )
            if previous_member_calls:
                formatted_calls = "; ".join(
                    f"{class_name}.{', '.join(member_names)}"
                    for class_name, member_names in previous_member_calls.items()
                )
                lines.append(
                    "The previous statically valid suite already exercised these production member calls: "
                    f"{formatted_calls}. Preserve those exact member names during repair unless the validation summary explicitly marks one of them invalid."
                )
                lines.append(
                    "Do not replace a previously valid member call with a guessed workflow alias such as process_request or process_batch when the valid suite already used a different documented member name."
                )
            if "constructor arity mismatches: none" in summary_lower:
                lines.append(
                    "When the previous suite had no constructor arity mismatches, keep the same request and result constructor field names and arity during repair unless the validation summary explicitly reports a constructor problem. Do not rewrite a statically valid request model to a different field set just because pytest failed on behavior."
                )
            if previous_constructor_keywords:
                formatted_keywords = "; ".join(
                    f"{class_name}({', '.join(keyword_names)})"
                    for class_name, keyword_names in previous_constructor_keywords.items()
                )
                lines.append(
                    "The previous statically valid suite already instantiated production models with these keyword fields: "
                    f"{formatted_keywords}. Preserve those field names during repair unless the validation summary explicitly reports a constructor mismatch."
                )
                lines.append(
                    "Do not rewrite a previously valid request model from fields such as request_id, request_type, details to guessed placeholders such as id, data, timestamp, or status unless the contract and validation summary explicitly require that change."
                )
            lines.append(
                "When repairing a suite that was already statically valid, preserve the exact documented public method names from the current suite and API contract. Do not rename submit_intake(...) to submit(...) or batch_submit_intakes(...) to submit_batch(...), even when calling the service inline."
            )
            lines.append(
                "If a pytest-only runtime failure comes from an overreaching assertion rather than a documented contract guarantee, rewrite that assertion to a contract-backed invariant instead of forcing a guessed business rule into the implementation."
            )
            if "assertionerror: assert" in summary_lower and " == " in summary_lower:
                lines.append(
                    "When pytest reports an exact numeric mismatch such as `assert 0.4 == 0.1`, do not preserve the stale guessed literal from the earlier suite. Either recompute the expected value from the current implementation formula and the exact input used in that test, or replace the equality with a stable contract-backed invariant such as non-negativity, type, or relative ordering."
                )
                if "score ==" in failed_content_lower:
                    lines.append(
                        "If an exact score depends on string length or character count, do not keep word-like sample strings such as data, valid_data, or data1 together with exact score equality. Replace them with repeated-character literals whose length is obvious, or switch the assertion to a non-exact invariant."
                    )
                    if any(token in failed_content_lower for token in ("name", "email", "@")):
                        lines.append(
                            "Do not hand-count human-readable names or email addresses into an exact score literal. If the formula uses lengths such as (len(name) + len(email)) / 10.0, compute the expected value from the current formula and the exact strings used, or switch to repeated-character inputs whose lengths are obvious."
                        )
                if any(token in failed_content_lower for token in ("risk_factor", "compliance_history")):
                    lines.append(
                        "If a score formula combines weighted numeric fields, recompute the exact total from every exercised term using the current input values before asserting equality. Example: if score += request_data['risk_factor'] * 0.5 and score += (1 - request_data['compliance_history']) * 0.5, then risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25."
                    )
                if "process_batch" in failed_content_lower and "score ==" in failed_content_lower:
                    lines.append(
                        "Recompute each batch item's expected score independently from the same current formula applied to that item's actual input. Do not assume a later batch item should have a larger exact score just because nested values differ; if the formula counts top-level keys or container size, same-shape inputs produce the same score."
                    )
            if "valueerror" in summary_lower and "must be filled" in summary_lower:
                lines.append(
                    "If a non-error scoring or happy-path test fails because a required string field is empty, do not preserve that empty string just to force a zero score. Use a valid non-empty input that still yields the intended observable result, or replace the exact equality with a stable invariant."
                )
                if any(token in failed_content_lower for token in ("score_request", "score_risk")) and "intake_request" in failed_content_lower:
                    lines.append(
                        "If invalid required fields are rejected during intake or validation, do not keep a separate invalid-scoring test that first calls intake_request and then expects score_request or score_risk to fail on the same invalid object. Move that failure case to intake_request or validate_request, and keep scoring tests on already-valid requests."
                    )
                if any(token in failed_content_lower for token in ('""', "''")):
                    lines.append(
                        "If a required string field participates in a length- or modulo-based score, an empty string is invalid once the implementation validates that field before scoring. Use a non-empty repeated-character literal with the needed length instead; for len(details) % 10 == 0, use \"xxxxxxxxxx\" rather than \"\"."
                    )
            if "documents" in failed_content_lower and "risk_scores" in failed_content_lower:
                lines.append(
                    "When the implementation validates a required document or evidence list before scoring, every happy-path or valid batch item must include the full required set named by that validator. Do not keep a single placeholder document such as ['ID'] if the implementation names additional required evidence items."
                )
                lines.append(
                    "If the implementation shows a named required_evidence or required_documents list, copy that full list verbatim into every valid happy-path or valid batch payload instead of shrinking it to a representative subset."
                )
                lines.append(
                    "Keep the missing-document scenario isolated to the explicit validation-failure test, and make every supposedly valid happy-path or batch item fully valid before asserting scored outcomes or approved audit entries."
                )
                if "test_validation_failure" in failed_content_lower or '"documents": []' in failed_content_lower or "'documents': []" in failed_content_lower:
                    lines.append(
                        "When the suite already contains a dedicated validation-failure case, do not reuse that invalid missing-document payload inside test_batch_processing or any other supposedly valid batch scenario. Keep every batch item fully valid unless the contract explicitly documents partial batch failure handling."
                    )
            if required_evidence_runtime_issue:
                lines.append(
                    "Do not copy the current failed suite forward unchanged. The supposed happy-path or batch payloads still omit required evidence named by the implementation validator, so rebuild those valid request payloads from the current validator contract before returning the rewritten file."
                )
                if required_evidence_items:
                    lines.append(
                        f"The implementation names the full required evidence list as {required_evidence_items!r}. Copy that exact list into every valid happy-path or valid batch payload, and keep missing-document coverage isolated to the explicit validation-failure test."
                    )
                lines.append(
                    "If test_batch_processing asserts the full batch size on len(service.risk_scores) or another success-path count, every batch item in that scenario must be fully valid. Do not keep a second batch request with reduced or empty documents such as ['ID'] or [] unless the contract explicitly documents partial batch failure handling."
                )
            if "risk_scores" in failed_content_lower and ".score > 0" in failed_content_lower:
                lines.append(
                    "Do not require a strictly positive score or non-empty risk list from a generic happy-path input unless the chosen payload actually exercises a documented risk factor. For a plain valid request, prefer asserting that scoring completed, a risk record exists, or the score is non-negative."
                )
            if ".data ==" in failed_content_lower:
                lines.append(
                    "If a returned request object's `.data` field stores the full input payload, do not assert that it equals only a guessed inner sub-dict. Assert the full stored payload shape or direct nested keys instead."
                )
                if "score ==" in failed_content_lower or "data_field" in failed_content_lower:
                    lines.append(
                        "If an exact score depends on nested payload shape, compute it from the actual object passed into the scoring function rather than from an inner dict you assume the service extracted. If request.data stores {'id': '1', 'data': {'data_field': 'example'}, 'timestamp': '...'} and calculate_risk_score reads data.get('data_field', ''), the score is 0.0, not 7.0."
                    )
            lines.append(
                "Do not assume empty strings, placeholder IDs, or domain keywords are invalid unless the contract or implementation explicitly says so. For validation-failure coverage, prefer missing required fields or clearly wrong types over guessed business rules."
            )
            lines.append(
                "If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict), do not use empty strings or same-type placeholders as the failing input because they still satisfy that validator. Switch the failure case to a clearly wrong type or a truly missing required field instead."
            )
            if "audit" in summary_lower or "log" in summary_lower:
                lines.append(
                    "If the remaining pytest failure comes from a standalone audit or logging helper test in a compact helper-only suite, delete that standalone helper test or fold the audit call into a required happy-path or batch scenario instead."
                )
                lines.append(
                    "Do not compare full audit or log file contents by exact string equality or trailing-newline-sensitive text unless the contract explicitly defines that serialized format. Prefer stable assertions such as file creation, non-empty content, append growth, line count, or required substring presence."
                )
                if "audit_logs" in failed_content_lower or "len(service.audit_logs)" in failed_content_lower:
                    lines.append(
                        "If pytest shows a mismatch such as `assert 5 == 3` or `assert 2 == 3` on len(service.audit_logs) in a batch scenario, the suite guessed internal logging. Delete that exact len(service.audit_logs) == N assertion unless the contract explicitly enumerates every emitted batch log."
                    )
                    lines.append(
                        "Replace brittle batch audit counts with stable checks such as result length, required audit actions, a terminal batch marker, or monotonic audit growth."
                    )
                    lines.append(
                        "If an audit-count assertion failed, recount only the audit actions that the scenario actually executes. Add logs from both inner failing operations and outer batch error handlers instead of assuming one failure contributes only one audit record. When the test performs intake, scoring, and one error path, the expected audit count is three entries, not two."
                    )
                    lines.append(
                        "If you cannot enumerate every emitted audit event from the current implementation, stop asserting an exact batch audit length and switch to stable checks such as required actions, terminal batch markers, result counts, or monotonic audit growth."
                    )
                    if "process_batch" in failed_content_lower:
                        lines.append(
                            "In a mixed valid/invalid batch scenario, one invalid item can emit two failure-related audit records, such as an intake or validation failure log plus a batch-level failure log. Add those to any success-path logs from valid items before asserting an exact audit total."
                        )
                        lines.append(
                            "If process_batch internally performs more than one logged success step per valid item, count each of those inner success-path logs before any batch-level or failure logs. Example: a two-item valid batch can emit 5 audit logs, not 3, and a batch that fails on the second item can still already emit 2 logs, not 1, from the first valid item."
                        )
            if "exact batch audit length" in summary_lower:
                lines.append(
                    "The previous suite overreached by asserting a batch audit length larger than the visible number of processed items. Delete that guessed extra-count assertion and rebuild the batch scenario around result count, request identity, or monotonic audit growth unless the contract explicitly defines extra summary entries."
                )
            if "exact status/action label mismatch" in summary_lower:
                lines.append(
                    "The previous runtime failure came from a brittle exact status or action label guess. Unless the contract explicitly defines the trigger, replace blocked, escalated, or approved label guesses with stable invariants or with clearly non-borderline inputs whose outcome is documented."
                )
                lines.append(
                    "If you keep an exact status or action assertion, anchor it to a validation-failure path or another trigger that the implementation summary or behavior contract defines directly."
                )
                lines.append(
                    "For happy-path or valid batch scenarios, do not assert exact outcome strings such as straight-through, manual review, manual investigation, fraud, fraud escalation, or time-boxed approval unless the contract explicitly defines that input-to-label mapping. Prefer request identity, audit growth, or another documented invariant instead."
                )
                lines.append(
                    "Apply the same rule to return-review labels such as auto-approve, manual inspection, and abuse escalation. Do not hard-code those happy-path or batch outcomes unless the contract explicitly defines that mapping."
                )
            if "exact internal action-map key assumption" in summary_lower:
                lines.append(
                    "The previous runtime failure came from assuming an internal action or review map used request identity as its key. Do not assert request.request_id in service.review_actions or a similar membership check unless the contract explicitly defines that storage key."
                )
                lines.append(
                    "If the implementation stores ReviewAction(action_id, ...) or another action record with its own generated identifier, assert the collection size, inspect stored action values, or check a documented action_type instead of assuming the map key equals request_id, vendor_id, or another request-identity field."
                )
            if "exact validation-failure score-state emptiness assertion" in summary_lower:
                lines.append(
                    "The previous runtime failure came from assuming a rejected or invalid request leaves internal score state empty. Do not assert len(service.get_risk_scores()) == 0 or a similar exact zero-length check on internal score maps, caches, or derived-state collections unless the behavior contract explicitly guarantees that post-validation state."
                )
                lines.append(
                    "For validation-failure coverage, prefer the rejected return value, documented audit or action evidence, or another observable contract-backed effect over a guessed exact internal score-state size."
                )
                lines.append(
                    "In a validation-failure test, remove direct reads of service.get_risk_scores() or similar internal score state unless that post-failure state is itself the documented contract. Assert the rejected return value, blocked audit entry, or another documented effect instead."
                )
            if "exact return-shape attribute assumption" in summary_lower:
                lines.append(
                    "The previous runtime failure came from assuming a wrapped object return shape that the current runtime did not provide. Delete `.request_id`, `.outcome`, and similar attribute reads on the workflow return value unless the contract explicitly exposes that wrapper type."
                )
                lines.append(
                    "If the workflow currently returns a direct string or other primitive, keep happy-path and batch assertions on that direct value or on documented side effects instead of inventing a wrapper object."
                )
            if all(name in summary_lower for name in ("validate_request", "score_request", "log_audit")):
                lines.append(
                    "For a helper-only trio such as validate_request(request), score_request(request), and log_audit(request_id, action, result), collapse the suite to exactly three tests: one happy-path test that validates and scores a valid request and may check audit file creation or required substring presence, one validation-failure test using an invalid document_type or wrong-type document_data, and one batch-style loop over two valid requests. Delete standalone score_request, log_audit, and extra invalid-case tests."
                )
                lines.append(
                    "When a helper-only trio has branch-specific score increments, derive the exact expected score from only the branches exercised by the chosen input. Do not add values from categories the input does not trigger."
                )
                lines.append(
                    "Example: if score_request adds 1 for document_type == 'income' and 2 for document_type == 'employment', a request with document_type='income' should assert 1, not 3."
                )
            if "argparse" in summary_lower or "dataclass" in summary_lower:
                lines.append(
                    "Delete any copied implementation blocks from the pytest module. Do not redeclare dataclasses, business functions, CLI parsers, `test_main`, `test_all_tests`, or similar scaffolding inside tests; import production symbols and keep only focused test cases."
                )
            lines.append(
                "When behavior is uncertain, prefer stable invariants and type or shape assertions over guessed exact numeric values."
            )
            lines.append(
                "If the implementation summary or behavior contract does not explicitly define a score formula or threshold flag trigger, remove exact score totals and threshold-triggered boolean assertions and replace them with stable invariants or relative comparisons."
            )
        if "did not raise" in summary_lower:
            lines.append(
                "When a failure case did not raise, rebuild that scenario around an input that actually violates the current validator or contract. If validation only checks isinstance(id, str) and isinstance(data, dict), do not use empty-string ids or still-valid dict payloads as the failure input."
            )
            lines.append(
                "If a workflow input still has the correct top-level type, do not expect ValueError just because one business value changed. Example: if submit_intake only validates that data.data is a dict, ComplianceData(id=\"1\", data={\"key\": \"wrong_value\"}) is still valid input and should be asserted as a non-compliant result instead of being wrapped in pytest.raises(ValueError). Use a non-dict payload if you need a ValueError case."
            )
            lines.append(
                "If the field under test is a dict payload such as data, details, metadata, request_data, or document_data, an empty dict is still a same-type placeholder and may pass when validation only checks dict type. Use None, a non-dict value, or omit the field only when omission is explicitly allowed."
            )
            lines.append(
                "If validation only checks an outer container type, do not assume a wrong nested value type makes the request invalid. When validate_request(request) returns bool(request.id) and isinstance(request.data, dict), ComplianceRequest(id=\"1\", data={\"check\": \"not_a_bool\"}, timestamp=\"2023-01-01T00:00:00Z\", status=\"pending\") still passes; use a non-dict data value or another explicitly invalid top-level field instead."
            )
            lines.append(
                "For process_request or other validation-gated workflow tests, choose an input that validate_request rejects before scoring runs. Do not use nested None values or same-type empty containers that can slip past validation and then fail later inside score_risk, calculate_risk_score, or similar scoring helpers with a different exception."
            )
            if "exact return-shape attribute assumption" in summary_lower:
                lines.append(
                    "If the same failed suite also overreached on return shape, rebuild happy-path and batch checks around the direct primitive returned by the workflow, and reserve pytest.raises only for an input that the current validator demonstrably rejects."
                )
            if any(token in failed_content_lower for token in ("risk_factor", "compliance_history", "request_data")):
                lines.append(
                    "Do not expect a wrong nested field type to raise just because that field participates in scoring. When the implementation guards a nested field with isinstance(...) before using it, a wrong nested field type is ignored rather than raising; use a wrong top-level type or missing required field for failure coverage instead."
                )
        if "assert false" in summary_lower or "assert true" in failed_content_lower or "assuming " in failed_content_lower:
            lines.append(
                "Do not leave placeholder assertions such as assert True, assert False, or comments like 'Assuming ...' in the rewritten suite. Replace them with a concrete contract-backed expectation."
            )
            lines.append(
                "For validation-failure coverage, prefer an explicit validation result, a documented raised exception, or another observable side effect over a placeholder boolean assertion."
            )
        if "assert not true" in summary_lower or "assert true is false" in summary_lower:
            lines.append(
                "If pytest reports `assert not True` or another failed falsy expectation from validate_request, process_request, or a similar validator, the supposed invalid sample likely still satisfies the current contract. Apply the same rule to `assert True is False`. Replace it with a clearly wrong top-level type or a truly missing required field instead of an empty-string or same-type placeholder."
            )
            lines.append(
                "Apply the same rule to request_id, entity_id, document_id, and similar identifiers: unless the contract explicitly says empty strings are invalid, do not use request_id='' or another same-type placeholder as the failing input."
            )
            lines.append(
                "If the field under test is a dict payload such as data, details, metadata, request_data, or document_data, do not use an empty dict or nested None values to fake a validation failure. Use a wrong top-level type or another input that validate_request actually rejects before scoring runs."
            )
            lines.append(
                "If the current validator only checks for the presence of required payload fields, do not keep every named key with same-type placeholder values like \"value\" in the rejection case. Omit one required field or use another clearly invalid top-level type instead."
            )
        if "assert false" in summary_lower:
            lines.append(
                "Do not require an exact runtime numeric type such as float unless the contract or implementation explicitly casts to that type. For numeric scores, prefer the documented value, non-negativity, or a broader numeric invariant such as isinstance(value, (int, float))."
            )
        if "assertionerror" in summary_lower or " - assert " in summary_lower:
            lines.append(
                "Do not infer derived statuses, labels, or report counters from suggestive field names or keywords alone. Keep exact categorical or counter assertions only when the contract or current implementation explicitly defines that trigger."
            )
            if any(label in summary_lower for label in ("low", "medium", "high")):
                lines.append(
                    "Do not keep boundary-like inputs for exact categorical labels. If score = amount * 0.1 and the label may change at 10, do not use amount=100 to assert an exact level; use 50 for a clear low case, 150 for a clear medium case, or assert only the numeric score unless the thresholds are explicit."
                )
                lines.append(
                    "If the score is count-based and the thresholds are not explicit, do not use a borderline count such as 2 to assert an exact low label; use 1 for a clear low case, 3 for a clear medium case, or assert only the numeric score."
                )
        return lines

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

    def _unredacted_agent_result(self, agent: Any, result: AgentOutput) -> AgentOutput:
        getter = getattr(agent, "_consume_last_unredacted_output", None)
        if callable(getter):
            unredacted = getter()
            if isinstance(unredacted, AgentOutput):
                return unredacted
        return result

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
        if self._exit_if_workflow_cancelled(project):
            return
        project.execution_plan()
        self._validate_agent_resolution(project)
        project.repair_max_cycles = self.config.workflow_max_repair_cycles
        resumed_task_ids = project.resume_interrupted_tasks()
        failed_task_ids = self._failed_task_ids_for_repair(project)
        if self.config.workflow_resume_policy == "resume_failed":
            if failed_task_ids:
                failure_categories = {
                    task.last_error_category or FailureCategory.UNKNOWN.value
                    for task in project.tasks
                    if task.id in failed_task_ids
                }
                non_repairable_categories = {
                    category for category in failure_categories if not self._is_repairable_failure(category)
                }
                if non_repairable_categories:
                    resolved_category = (
                        next(iter(non_repairable_categories))
                        if len(non_repairable_categories) == 1
                        else FailureCategory.UNKNOWN.value
                    )
                    acceptance_evaluation = self._evaluate_workflow_acceptance(project)
                    project.mark_workflow_finished(
                        "failed",
                        acceptance_policy=self.config.workflow_acceptance_policy,
                        terminal_outcome=WorkflowOutcome.FAILED.value,
                        failure_category=resolved_category,
                        acceptance_criteria_met=False,
                        acceptance_evaluation=acceptance_evaluation,
                    )
                    project.save()
                    raise AgentExecutionError(
                        "Workflow contains non-repairable failed tasks and cannot resume automatically"
                    )
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
        if self._exit_if_workflow_cancelled(project):
            return
        if self._exit_if_workflow_paused(project):
            return
        if project.workflow_started_at is None or project.phase != "execution":
            project.mark_workflow_running(
                acceptance_policy=self.config.workflow_acceptance_policy,
                repair_max_cycles=self.config.workflow_max_repair_cycles,
            )
            self._log_event("info", "workflow_started", project_name=project.project_name, phase=project.phase)
        while True:
            if self._exit_if_workflow_cancelled(project):
                return
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
            if self._exit_if_workflow_cancelled(project):
                return
            if self._exit_if_workflow_paused(project):
                return
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
                if self._exit_if_workflow_cancelled(project):
                    return
                if self._exit_if_workflow_paused(project):
                    return
                try:
                    self.run_task(task, project)
                except Exception as exc:
                    if self._exit_if_workflow_cancelled(project):
                        return
                    failure_category = self._classify_task_failure(task, exc)
                    if project.should_retry_task(task.id):
                        self._emit_workflow_progress(project, task=task)
                        project.save()
                        continue
                    if not self._is_repairable_failure(failure_category):
                        if self.config.workflow_failure_policy == "continue":
                            skipped = project.skip_dependent_tasks(
                                task.id,
                                f"Skipped because dependency '{task.id}' failed",
                            )
                            self._emit_workflow_progress(project, task=task)
                            project.save()
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
                            failure_category=failure_category,
                            acceptance_criteria_met=False,
                            acceptance_evaluation=self._evaluate_workflow_acceptance(project),
                        )
                        project.save()
                        self._log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)
                        raise
                    if self._queue_active_cycle_repair(project, task):
                        self._emit_workflow_progress(project, task=task)
                        project.save()
                        continue
                    if self.config.workflow_failure_policy == "continue":
                        skipped = project.skip_dependent_tasks(
                            task.id,
                            f"Skipped because dependency '{task.id}' failed",
                        )
                        self._emit_workflow_progress(project, task=task)
                        project.save()
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
                        failure_category=failure_category,
                        acceptance_criteria_met=False,
                        acceptance_evaluation=self._evaluate_workflow_acceptance(project),
                    )
                    project.save()
                    self._log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)
                    raise
                self._emit_workflow_progress(project, task=task)
                project.save()
        self._log_event(
            "info",
            "workflow_finished",
            project_name=project.project_name,
            phase=project.phase,
            terminal_outcome=project.terminal_outcome,
            workflow_telemetry=project.internal_runtime_telemetry()["workflow"],
        )
