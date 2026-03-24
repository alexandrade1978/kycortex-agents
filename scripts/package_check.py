from __future__ import annotations

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


def _build_artifacts(dist_dir: Path) -> tuple[Path, Path]:
    _run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist_dir)])

    wheel = next(dist_dir.glob("*.whl"), None)
    sdist = next(dist_dir.glob("*.tar.gz"), None)
    if wheel is None or sdist is None:
        raise RuntimeError("Expected both wheel and source distribution artifacts to be built")
    return wheel, sdist


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


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="kycortex-package-check-") as temp_dir:
        work_dir = Path(temp_dir)
        dist_dir = work_dir / "dist"
        dist_dir.mkdir()

        wheel, sdist = _build_artifacts(dist_dir)
        _smoke_install(wheel, "wheel", work_dir)
        _smoke_install(sdist, "sdist", work_dir)

        print(f"Validated built artifacts: {wheel.name}, {sdist.name}")


if __name__ == "__main__":
    main()