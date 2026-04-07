from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _python_in(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def _run(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd or PROJECT_ROOT, check=True)


def _existing_artifacts(dist_dir: Path) -> tuple[Path, Path]:
    wheel_candidates = sorted(dist_dir.glob("*.whl"))
    sdist_candidates = sorted(dist_dir.glob("*.tar.gz"))

    if len(wheel_candidates) != 1:
        raise RuntimeError(
            f"Expected exactly one wheel artifact in {dist_dir}, found {len(wheel_candidates)}"
        )
    if len(sdist_candidates) != 1:
        raise RuntimeError(
            f"Expected exactly one source distribution artifact in {dist_dir}, found {len(sdist_candidates)}"
        )
    return wheel_candidates[0], sdist_candidates[0]


def _build_artifacts(dist_dir: Path) -> tuple[Path, Path]:
    _run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist_dir)])

    return _existing_artifacts(dist_dir)


def _smoke_install(artifact: Path, label: str, work_dir: Path) -> None:
    env_dir = work_dir / f"{label}-venv"
    _run([sys.executable, "-m", "venv", str(env_dir)], cwd=work_dir)

    env_python = _python_in(env_dir)
    _run([str(env_python), "-m", "pip", "install", "--upgrade", "pip"], cwd=work_dir)
    _run([str(env_python), "-m", "pip", "install", str(artifact)], cwd=work_dir)
    _run(
        [
            str(env_python),
            "-c",
            (
                "import kycortex_agents; "
                "from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task; "
                "assert kycortex_agents.__version__; "
                "assert KYCortexConfig and Orchestrator and ProjectState and Task"
            ),
        ],
        cwd=work_dir,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build or validate wheel and source-distribution artifacts, then smoke-install them "
            "in isolated virtual environments."
        )
    )
    parser.add_argument(
        "--dist-dir",
        help=(
            "Validate an existing distribution directory instead of building fresh artifacts in a "
            "temporary workspace"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="kycortex-package-check-") as temp_dir:
        work_dir = Path(temp_dir)
        try:
            if args.dist_dir is None:
                dist_dir = work_dir / "dist"
                dist_dir.mkdir()
                wheel, sdist = _build_artifacts(dist_dir)
                result_label = "Validated built artifacts"
            else:
                dist_dir = Path(args.dist_dir).resolve()
                if not dist_dir.is_dir():
                    raise RuntimeError(f"Distribution directory does not exist: {dist_dir}")
                wheel, sdist = _existing_artifacts(dist_dir)
                result_label = "Validated staged artifacts"

            _smoke_install(wheel, "wheel", work_dir)
            _smoke_install(sdist, "sdist", work_dir)
        except Exception as exc:
            print(f"Package validation failed: {exc}", file=sys.stderr, flush=True)
            return 1

        print(f"{result_label}: {wheel.name}, {sdist.name}", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())