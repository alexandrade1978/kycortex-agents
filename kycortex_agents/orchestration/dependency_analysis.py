"""Dependency-manifest helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import Any

from kycortex_agents.agents.dependency_manager import (
	extract_requirement_name,
	is_provenance_unsafe_requirement,
)


_THIRD_PARTY_PACKAGE_ALIASES = {
	"bs4": "beautifulsoup4",
	"cv2": "opencv_python",
	"dateutil": "python_dateutil",
	"dotenv": "python_dotenv",
	"fitz": "pymupdf",
	"jwt": "pyjwt",
	"pil": "pillow",
	"sklearn": "scikit_learn",
	"yaml": "pyyaml",
}


def normalize_package_name(package_name: str) -> str:
	return package_name.strip().lower().replace("-", "_")


def normalize_import_name(module_name: str) -> str:
	normalized_name = module_name.strip().lower().replace("-", "_")
	package_name = _THIRD_PARTY_PACKAGE_ALIASES.get(normalized_name, normalized_name)
	return normalize_package_name(package_name)


def analyze_dependency_manifest(
	manifest_content: str,
	code_analysis: dict[str, Any],
) -> dict[str, Any]:
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
		normalized_declared_packages.add(normalize_package_name(package_name))
		if is_provenance_unsafe_requirement(line):
			provenance_violations.append(line)

	required_imports = sorted(code_analysis.get("third_party_imports") or []) if isinstance(code_analysis, dict) else []
	normalized_required_imports = {normalize_import_name(module_name) for module_name in required_imports}
	missing_manifest_entries = [
		module_name
		for module_name in required_imports
		if normalize_import_name(module_name) not in normalized_declared_packages
	]
	unused_manifest_entries = [
		package_name
		for package_name in declared_packages
		if normalize_package_name(package_name) not in normalized_required_imports
	]
	return {
		"required_imports": required_imports,
		"declared_packages": declared_packages,
		"missing_manifest_entries": missing_manifest_entries,
		"unused_manifest_entries": unused_manifest_entries,
		"provenance_violations": provenance_violations,
		"is_valid": not missing_manifest_entries and not provenance_violations,
	}