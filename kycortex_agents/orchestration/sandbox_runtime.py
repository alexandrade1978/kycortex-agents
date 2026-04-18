"""Sandbox runtime bootstrap helpers for generated validation subprocesses."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from kycortex_agents.orchestration.sandbox_templates import render_sandbox_sitecustomize
from kycortex_agents.types import ExecutionSandboxPolicy

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


def looks_like_secret_env_var(env_name: str) -> bool:
    tokens = {token for token in re.split(r"[^A-Za-z0-9]+", env_name.upper()) if token}
    if not tokens:
        return False
    if _GENERIC_SECRET_ENV_TOKENS & tokens:
        return True
    return any(token_pair.issubset(tokens) for token_pair in _GENERIC_SECRET_ENV_TOKEN_PAIRS)


def sanitize_generated_filename(filename: str, default_filename: str) -> str:
    candidate = Path(filename).name if isinstance(filename, str) else ""
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).strip("._")
    if not sanitized:
        sanitized = default_filename
    if "." not in sanitized and "." in default_filename:
        sanitized = f"{sanitized}{Path(default_filename).suffix}"
    return sanitized


def build_generated_test_env(
    tmp_path: Path,
    sandbox_policy: ExecutionSandboxPolicy,
    *,
    host_env: Mapping[str, str] | None = None,
    secret_env_detector: Callable[[str], bool] = looks_like_secret_env_var,
) -> dict[str, str]:
    source_env = dict(host_env) if host_env is not None else os.environ.copy()
    if sandbox_policy.enabled:
        env = {key: value for key, value in sandbox_policy.sanitized_env.items() if value}
    else:
        env = source_env.copy()
    env["PATH"] = source_env.get("PATH", "")
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
        if secret_env_detector(key):
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
            render_sandbox_sitecustomize(),
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


def build_sandbox_preexec_fn(
    sandbox_policy: ExecutionSandboxPolicy,
    *,
    os_module: Any,
    resource_module: Any,
) -> Callable[[], None] | None:
    if not sandbox_policy.enabled or os_module.name != "posix" or resource_module is None:
        return None

    def _apply_limits() -> None:
        cpu_seconds = max(int(sandbox_policy.max_cpu_seconds), 1)
        memory_bytes = max(sandbox_policy.max_memory_mb, 1) * 1024 * 1024
        os_module.umask(0o077)
        resource_module.setrlimit(resource_module.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource_module.setrlimit(resource_module.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource_module.setrlimit(resource_module.RLIMIT_CORE, (0, 0))
        resource_module.setrlimit(resource_module.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))

    return _apply_limits