from __future__ import annotations

from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 support path
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_text(relative_path: str) -> str:
    return PROJECT_ROOT.joinpath(relative_path).read_text(encoding="utf-8")


def _parse_semver(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        raise ValueError(f"invalid semantic version: {value}")

    return tuple(int(part) for part in match.groups())


def main() -> int:
    pyproject = tomllib.loads(_read_text("pyproject.toml"))
    package_init = _read_text("kycortex_agents/__init__.py")
    release_guide = _read_text("RELEASE.md")
    release_status = _read_text("RELEASE_STATUS.md")
    changelog = _read_text("CHANGELOG.md")

    project_version = pyproject["project"]["version"]

    package_version_match = re.search(r'__version__\s*=\s*"([^"]+)"', package_init)
    if package_version_match is None:
        raise ValueError("kycortex_agents/__init__.py does not define __version__")

    package_version = package_version_match.group(1)
    if package_version != project_version:
        raise ValueError(
            f"package version mismatch: pyproject.toml has {project_version}, __init__.py has {package_version}"
        )

    current_version_line = f"Package version in `pyproject.toml`: `{project_version}`"
    if current_version_line not in release_status:
        raise ValueError("RELEASE_STATUS.md does not reflect the current package version")

    target_version_match = re.search(r"Release target under final Phase 13 review: `([^`]+)`", release_status)
    if target_version_match is None:
        raise ValueError("RELEASE_STATUS.md does not declare a release target")

    target_version = target_version_match.group(1)
    if _parse_semver(target_version) <= _parse_semver(project_version):
        raise ValueError(
            f"release target {target_version} must be greater than current package version {project_version}"
        )

    if "git tag v<version>" not in release_guide or "git push origin v<version>" not in release_guide:
        raise ValueError("RELEASE.md must use generic version-tag examples")

    changelog_line = f"Current package version remains `{project_version}`"
    if changelog_line not in changelog:
        raise ValueError("CHANGELOG.md does not reflect the current package version")

    print(
        "Release metadata validation passed: "
        f"current={project_version}, target={target_version}, docs and package metadata are aligned.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())