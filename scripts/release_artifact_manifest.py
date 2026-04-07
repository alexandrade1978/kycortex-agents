from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


MANIFEST_FILENAME = "release-artifact-manifest.json"
MANIFEST_VERSION = 1


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _artifact_paths(dist_dir: Path, manifest_name: str) -> list[Path]:
    if not dist_dir.is_dir():
        raise ValueError(f"Distribution directory does not exist: {dist_dir}")

    artifacts = sorted(
        path
        for path in dist_dir.iterdir()
        if path.is_file() and path.name != manifest_name
    )
    if not artifacts:
        raise ValueError(f"No release artifacts found in {dist_dir}")
    if not any(path.suffix == ".whl" for path in artifacts):
        raise ValueError("Expected at least one wheel artifact in the distribution directory")
    if not any(path.name.endswith(".tar.gz") for path in artifacts):
        raise ValueError("Expected at least one source distribution artifact in the distribution directory")
    return artifacts


def _manifest_payload(dist_dir: Path, manifest_name: str) -> dict[str, object]:
    artifacts = _artifact_paths(dist_dir, manifest_name)
    return {
        "manifest_version": MANIFEST_VERSION,
        "artifact_count": len(artifacts),
        "artifacts": [
            {
                "name": artifact.name,
                "size_bytes": artifact.stat().st_size,
                "sha256": _sha256(artifact),
            }
            for artifact in artifacts
        ],
    }


def _write_manifest(dist_dir: Path, output_path: Path) -> None:
    payload = _manifest_payload(dist_dir, output_path.name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote release artifact manifest: {output_path}", flush=True)


def _verify_manifest(dist_dir: Path, manifest_path: Path) -> None:
    if not manifest_path.is_file():
        raise ValueError(f"Release artifact manifest does not exist: {manifest_path}")

    expected = _manifest_payload(dist_dir, manifest_path.name)
    actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    if actual != expected:
        raise ValueError("Release artifact manifest does not match the current distribution artifacts")
    print(f"Verified release artifact manifest: {manifest_path}", flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or verify the staged release artifact manifest for built distribution artifacts."
    )
    parser.add_argument("--dist-dir", default="dist", help="Directory containing built distribution artifacts")
    parser.add_argument(
        "--output",
        help="Path to the manifest file to write when generating a new manifest",
    )
    parser.add_argument(
        "--manifest",
        help="Path to an existing manifest file when verifying distribution artifacts",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify an existing manifest instead of generating a new one",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    dist_dir = Path(args.dist_dir).resolve()
    try:
        if args.verify:
            if args.output is not None:
                parser.error("--output cannot be used together with --verify")
            if args.manifest is None:
                parser.error("--verify requires --manifest")
            _verify_manifest(dist_dir, Path(args.manifest).resolve())
        else:
            if args.manifest is not None:
                parser.error("--manifest is only supported together with --verify")
            output = args.output or str(dist_dir / MANIFEST_FILENAME)
            _write_manifest(dist_dir, Path(output).resolve())
    except Exception as exc:
        print(f"Release artifact manifest failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())