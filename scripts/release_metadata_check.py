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


def _parse_version(value: str) -> tuple[int, int, int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?", value)
    if match is None:
        raise ValueError(f"invalid package version: {value}")

    major, minor, patch, prerelease_label, prerelease_number = match.groups()
    prerelease_order = {
        None: 3,
        "rc": 2,
        "b": 1,
        "a": 0,
    }
    return (
        int(major),
        int(minor),
        int(patch),
        prerelease_order[prerelease_label],
        int(prerelease_number) if prerelease_number is not None else 0,
    )


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
    released_version_match = re.search(r"Latest released version: `([^`]+)`", release_status)

    if target_version_match is not None:
        target_version = target_version_match.group(1)
        if _parse_version(target_version) <= _parse_version(project_version):
            raise ValueError(
                f"release target {target_version} must be greater than current package version {project_version}"
            )
        release_state = f"target={target_version}"
    elif released_version_match is not None:
        released_version = released_version_match.group(1)
        if released_version != project_version:
            raise ValueError(
                "RELEASE_STATUS.md latest released version does not match the current package version"
            )
        release_state = f"released={released_version}"
    else:
        raise ValueError("RELEASE_STATUS.md must declare either a future release target or the latest released version")

    if "git tag v<version>" not in release_guide or "git push origin v<version>" not in release_guide:
        raise ValueError("RELEASE.md must use generic version-tag examples")

    changelog_line = f"Current package version remains `{project_version}`"
    released_changelog_line = f"Version `{project_version}` is now the released package baseline."
    if changelog_line not in changelog and released_changelog_line not in changelog:
        raise ValueError("CHANGELOG.md does not reflect the current package version")

    print(
        "Release metadata validation passed: "
        f"current={project_version}, {release_state}, docs and package metadata are aligned.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())