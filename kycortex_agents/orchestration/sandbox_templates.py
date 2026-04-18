"""Generated sandbox helper templates used by orchestrator subprocess runners."""

from __future__ import annotations

import textwrap


SANDBOX_SITECUSTOMIZE = """
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

GENERATED_TEST_RUNNER = """
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

GENERATED_IMPORT_RUNNER = """
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


def render_sandbox_sitecustomize() -> str:
    return textwrap.dedent(SANDBOX_SITECUSTOMIZE).strip() + "\n"


def render_generated_test_runner(
    *,
    sandbox_enabled: bool,
    pytest_config_path: str,
    rootdir_path: str,
    pytest_log_path: str,
    test_filename: str,
) -> str:
    return (
        textwrap.dedent(
            GENERATED_TEST_RUNNER.format(
                sandbox_enabled=repr(sandbox_enabled),
                pytest_config_path=repr(pytest_config_path),
                rootdir_path=repr(rootdir_path),
                pytest_log_option=repr(f"log_file={pytest_log_path}"),
                test_filename=repr(test_filename),
            )
        ).strip()
        + "\n"
    )


def render_generated_import_runner(*, sandbox_enabled: bool, module_filename: str) -> str:
    return (
        textwrap.dedent(
            GENERATED_IMPORT_RUNNER.format(
                sandbox_enabled=repr(sandbox_enabled),
                module_filename=repr(module_filename),
            )
        ).strip()
        + "\n"
    )