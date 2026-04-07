from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_API_BASE_URL = "https://api.github.com"
DEFAULT_MAX_ATTEMPTS = 10
DEFAULT_RETRY_DELAY_SECONDS = 3.0
REQUEST_TIMEOUT_SECONDS = 30.0
REQUIRED_RELEASE_FILES = {
    "release-artifact-manifest.json",
    "release-promotion-summary.json",
}


def _expected_assets(dist_dir: Path) -> dict[str, int]:
    if not dist_dir.is_dir():
        raise ValueError(f"Distribution directory does not exist: {dist_dir}")

    artifacts = sorted(path for path in dist_dir.iterdir() if path.is_file())
    if not artifacts:
        raise ValueError(f"No release artifacts found in {dist_dir}")
    if not any(path.suffix == ".whl" for path in artifacts):
        raise ValueError("Expected at least one wheel artifact in the distribution directory")
    if not any(path.name.endswith(".tar.gz") for path in artifacts):
        raise ValueError("Expected at least one source distribution artifact in the distribution directory")

    asset_sizes = {path.name: path.stat().st_size for path in artifacts}
    missing_required_files = sorted(REQUIRED_RELEASE_FILES - set(asset_sizes))
    if missing_required_files:
        raise ValueError(
            "Distribution directory is missing required release evidence files: "
            + ", ".join(missing_required_files)
        )
    return asset_sizes


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("GitHub token is required via GITHUB_TOKEN or GH_TOKEN")
    return token


def _release_url(api_base_url: str, repository: str, tag: str) -> str:
    repository_path = quote(repository.strip("/"), safe="/")
    tag_path = quote(tag, safe="")
    return f"{api_base_url.rstrip('/')}/repos/{repository_path}/releases/tags/{tag_path}"


def _fetch_release_payload(api_base_url: str, repository: str, tag: str) -> dict[str, object]:
    request = Request(
        _release_url(api_base_url, repository, tag),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_github_token()}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        detail = body or exc.reason
        raise ValueError(f"GitHub release lookup failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(f"GitHub release lookup failed: {exc.reason}") from exc

    if not isinstance(payload, dict):
        raise ValueError("GitHub release lookup did not return a top-level JSON object")
    return payload


def _release_assets(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("GitHub release payload must contain an assets list")

    normalized: dict[str, dict[str, object]] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("GitHub release assets must be JSON objects")

        name = asset.get("name")
        size = asset.get("size")
        state = asset.get("state")
        browser_download_url = asset.get("browser_download_url")
        if (
            not isinstance(name, str)
            or not isinstance(size, int)
            or not isinstance(state, str)
            or not isinstance(browser_download_url, str)
        ):
            raise ValueError(
                "GitHub release assets must include string name, integer size, string state, "
                "and string browser_download_url"
            )
        if name in normalized:
            raise ValueError(f"GitHub release payload contains duplicate asset name: {name}")
        normalized[name] = {
            "size": size,
            "state": state,
            "browser_download_url": browser_download_url,
        }

    return normalized


def _verify_release_payload(
    payload: dict[str, object],
    repository: str,
    tag: str,
    expected_assets: dict[str, int],
) -> str:
    tag_name = payload.get("tag_name")
    if tag_name != tag:
        raise ValueError(f"GitHub release tag mismatch: expected {tag}, got {tag_name}")

    html_url = payload.get("html_url")
    if not isinstance(html_url, str) or not html_url:
        raise ValueError("GitHub release payload must contain a non-empty html_url")
    if repository not in html_url:
        raise ValueError(f"GitHub release URL does not reference the expected repository: {html_url}")

    release_assets = _release_assets(payload)
    expected_names = set(expected_assets)
    actual_names = set(release_assets)
    if actual_names != expected_names:
        missing_assets = sorted(expected_names - actual_names)
        extra_assets = sorted(actual_names - expected_names)
        details: list[str] = []
        if missing_assets:
            details.append("missing assets: " + ", ".join(missing_assets))
        if extra_assets:
            details.append("unexpected assets: " + ", ".join(extra_assets))
        raise ValueError("Published GitHub release assets do not match the expected set (" + "; ".join(details) + ")")

    for asset_name, expected_size in sorted(expected_assets.items()):
        asset = release_assets[asset_name]
        if asset["size"] != expected_size:
            raise ValueError(
                f"Published asset size mismatch for {asset_name}: expected {expected_size}, got {asset['size']}"
            )
        if asset["state"] != "uploaded":
            raise ValueError(
                f"Published asset {asset_name} is not fully uploaded: state={asset['state']}"
            )
        if not asset["browser_download_url"]:
            raise ValueError(f"Published asset {asset_name} is missing a browser_download_url")

    return html_url


def _verify_published_assets(
    api_base_url: str,
    repository: str,
    tag: str,
    expected_assets: dict[str, int],
    max_attempts: int,
    retry_delay_seconds: float,
) -> str:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds must be non-negative")

    last_error: ValueError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            payload = _fetch_release_payload(api_base_url, repository, tag)
            return _verify_release_payload(payload, repository, tag, expected_assets)
        except ValueError as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            print(
                f"Release asset verification retry {attempt}/{max_attempts}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(retry_delay_seconds)

    assert last_error is not None
    raise ValueError(
        f"Published GitHub release asset verification failed after {max_attempts} attempts: {last_error}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the published GitHub release for a tag exposes the exact asset set staged "
            "in the local distribution directory."
        )
    )
    parser.add_argument("--repository", required=True, help="GitHub repository in owner/repo form")
    parser.add_argument("--tag", required=True, help="Git tag associated with the published release")
    parser.add_argument("--dist-dir", default="dist", help="Directory containing the staged release artifacts")
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="Base GitHub API URL, for example https://api.github.com",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help="Maximum number of release lookup attempts before failing",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=DEFAULT_RETRY_DELAY_SECONDS,
        help="Delay between release lookup retries",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        expected_assets = _expected_assets(Path(args.dist_dir).resolve())
        html_url = _verify_published_assets(
            api_base_url=args.api_base_url,
            repository=args.repository,
            tag=args.tag,
            expected_assets=expected_assets,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
        )
    except Exception as exc:
        print(f"Published GitHub release asset verification failed: {exc}", file=sys.stderr, flush=True)
        return 1

    print(
        "Verified published GitHub release assets for "
        f"{args.tag}: {', '.join(sorted(expected_assets))}",
        flush=True,
    )
    print(f"Release URL: {html_url}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())