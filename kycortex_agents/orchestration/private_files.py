"""Private file and directory hardening helpers for persisted artifacts."""

from __future__ import annotations

import os
from pathlib import Path

from kycortex_agents.exceptions import AgentExecutionError


def harden_private_file_permissions(path: Path) -> None:
	"""Restrict a persisted artifact file to owner-only access on POSIX hosts."""
	if os.name != "posix":
		return
	try:
		path.chmod(0o600)
	except OSError as exc:
		raise AgentExecutionError(
			f"Artifact persistence failed: could not harden file permissions for {path.name}"
		) from exc


def harden_private_directory_permissions(path: Path) -> None:
	"""Restrict a persisted artifact directory to owner-only access on POSIX hosts."""
	if os.name != "posix":
		return
	try:
		path.chmod(0o700)
	except OSError as exc:
		raise AgentExecutionError(
			f"Artifact persistence failed: could not harden directory permissions for {path.name}"
		) from exc