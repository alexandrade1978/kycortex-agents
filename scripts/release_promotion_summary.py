from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


SUMMARY_FILENAME = "release-promotion-summary.json"
SUMMARY_VERSION = 1
WHEEL_VERSION_PATTERN = re.compile(
    r"^kycortex_agents-(?P<version>.+?)-[^-]+-[^-]+-[^-]+\.whl$"
)
SDIST_VERSION_PATTERN = re.compile(r"^kycortex_agents-(?P<version>.+)\.tar\.gz$")


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _artifact_paths(dist_dir: Path, excluded_names: set[str]) -> list[Path]:
    if not dist_dir.is_dir():
        raise ValueError(f"Distribution directory does not exist: {dist_dir}")

    artifacts = sorted(
        path for path in dist_dir.iterdir() if path.is_file() and path.name not in excluded_names
    )
    if not artifacts:
        raise ValueError(f"No promoted release artifacts found in {dist_dir}")
    if not any(path.suffix == ".whl" for path in artifacts):
        raise ValueError("Expected at least one wheel artifact in the distribution directory")
    if not any(path.name.endswith(".tar.gz") for path in artifacts):
        raise ValueError("Expected at least one source distribution artifact in the distribution directory")
    return artifacts


def _load_manifest(manifest_path: Path) -> dict[str, object]:
    if not manifest_path.is_file():
        raise ValueError(f"Release artifact manifest does not exist: {manifest_path}")

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Release artifact manifest is not valid JSON: {manifest_path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Release artifact manifest must contain a top-level JSON object")
    return payload


def _manifest_entries(manifest: dict[str, object]) -> list[dict[str, object]]:
    if manifest.get("manifest_version") != 1:
        raise ValueError(
            f"Unsupported release artifact manifest version: {manifest.get('manifest_version')}"
        )

    artifact_count = manifest.get("artifact_count")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifact_count, int):
        raise ValueError("Release artifact manifest must contain an integer artifact_count")
    if not isinstance(artifacts, list):
        raise ValueError("Release artifact manifest must contain an artifacts list")
    if artifact_count != len(artifacts):
        raise ValueError("Release artifact manifest artifact_count does not match the artifacts list")

    normalized_entries: list[dict[str, object]] = []
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise ValueError("Release artifact manifest artifacts must be JSON objects")
        name = entry.get("name")
        size_bytes = entry.get("size_bytes")
        sha256 = entry.get("sha256")
        if not isinstance(name, str) or not isinstance(size_bytes, int) or not isinstance(sha256, str):
            raise ValueError(
                "Release artifact manifest entries must contain string name, integer size_bytes, and string sha256"
            )
        normalized_entries.append({"name": name, "size_bytes": size_bytes, "sha256": sha256})

    return normalized_entries


def _extract_package_version(artifacts: list[Path]) -> str:
    versions: set[str] = set()
    for artifact in artifacts:
        wheel_match = WHEEL_VERSION_PATTERN.match(artifact.name)
        if wheel_match is not None:
            versions.add(wheel_match.group("version"))
            continue

        sdist_match = SDIST_VERSION_PATTERN.match(artifact.name)
        if sdist_match is not None:
            versions.add(sdist_match.group("version"))

    if not versions:
        raise ValueError("Unable to determine package version from promoted artifacts")
    if len(versions) != 1:
        raise ValueError("Promoted artifacts do not agree on a single package version")
    return next(iter(versions))


def _validate_manifest(
    dist_dir: Path, manifest_path: Path, summary_name: str
) -> tuple[dict[str, object], list[Path]]:
    manifest = _load_manifest(manifest_path)
    manifest_entries = _manifest_entries(manifest)
    artifacts = _artifact_paths(dist_dir, {manifest_path.name, summary_name})

    manifest_by_name = {str(entry["name"]): entry for entry in manifest_entries}
    artifact_names = {artifact.name for artifact in artifacts}
    if set(manifest_by_name) != artifact_names:
        raise ValueError(
            "Release artifact manifest entries do not match the current promoted artifacts"
        )

    for artifact in artifacts:
        manifest_entry = manifest_by_name[artifact.name]
        if manifest_entry["size_bytes"] != artifact.stat().st_size:
            raise ValueError(
                f"Promoted artifact {artifact.name} does not match the manifest entry size"
            )
        if manifest_entry["sha256"] != _sha256(artifact):
            raise ValueError(
                f"Promoted artifact {artifact.name} does not match the manifest entry checksum"
            )

    return manifest, artifacts


def _summary_payload(
    dist_dir: Path,
    manifest_path: Path,
    tag: str,
    commit_sha: str | None,
    summary_name: str,
) -> dict[str, object]:
    manifest, artifacts = _validate_manifest(dist_dir, manifest_path, summary_name)
    package_version = _extract_package_version(artifacts)
    expected_tag = f"v{package_version}"
    if tag != expected_tag:
        raise ValueError(
            f"Release tag does not match promoted artifact version: expected {expected_tag}, got {tag}"
        )

    payload: dict[str, object] = {
        "summary_version": SUMMARY_VERSION,
        "release_tag": tag,
        "package_version": package_version,
        "manifest_verified": True,
        "artifact_manifest": {
            "name": manifest_path.name,
            "sha256": _sha256(manifest_path),
            "manifest_version": manifest["manifest_version"],
            "artifact_count": manifest["artifact_count"],
        },
        "promoted_artifacts": [
            {
                "name": artifact.name,
                "size_bytes": artifact.stat().st_size,
                "sha256": _sha256(artifact),
            }
            for artifact in artifacts
        ],
    }
    if commit_sha is not None:
        payload["commit_sha"] = commit_sha
    return payload


def _write_summary(
    dist_dir: Path,
    manifest_path: Path,
    tag: str,
    output_path: Path,
    commit_sha: str | None,
) -> None:
    payload = _summary_payload(dist_dir, manifest_path, tag, commit_sha, output_path.name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote release promotion summary: {output_path}", flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a release promotion summary that ties the verified artifact manifest to the "
            "promoted release artifacts."
        )
    )
    parser.add_argument("--dist-dir", default="dist", help="Directory containing release artifacts")
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to the verified release artifact manifest",
    )
    parser.add_argument("--tag", required=True, help="Git tag associated with the promoted artifacts")
    parser.add_argument(
        "--output",
        help="Path to the promotion summary file to write",
    )
    parser.add_argument(
        "--commit-sha",
        help="Optional commit SHA associated with the release tag",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    dist_dir = Path(args.dist_dir).resolve()
    manifest_path = Path(args.manifest).resolve()
    output = args.output or str(dist_dir / SUMMARY_FILENAME)
    output_path = Path(output).resolve()
    try:
        _write_summary(
            dist_dir=dist_dir,
            manifest_path=manifest_path,
            tag=args.tag,
            output_path=output_path,
            commit_sha=args.commit_sha,
        )
    except Exception as exc:
        print(f"Release promotion summary failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())