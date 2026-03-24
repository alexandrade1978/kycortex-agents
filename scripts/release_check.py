from __future__ import annotations

from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

COMMANDS: list[tuple[str, list[str]]] = [
    ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
    ("mypy", [sys.executable, "-m", "mypy"]),
    (
        "focused regressions",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_public_api.py",
            "tests/test_public_smoke.py",
            "tests/test_package_metadata.py",
            "-q",
        ],
    ),
    ("package validation", [sys.executable, "scripts/package_check.py"]),
    (
        "coverage gate",
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=kycortex_agents",
            "--cov-report=term-missing",
            "--cov-report=xml",
            "-q",
        ],
    ),
    ("full test suite", [sys.executable, "-m", "pytest", "-q"]),
]


def main() -> int:
    for name, command in COMMANDS:
        print(f"==> Running {name}: {' '.join(command)}", flush=True)
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)

    print("Release readiness validation completed successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())