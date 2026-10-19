#!/usr/bin/env python3
"""Compare the pinned upstream ref in the latest release manifest with the live
upstream main branch (GitHub API).

The "latest" manifest is picked from release-manifests/manifest-*.json by
sorting on `created` then `version` (both as strings) and taking the last.

Components:
  blender  — manifest components.blender.upstream_ref vs blender/blender@main
  zcode    — manifest components.zcode_runtime.upstream_ref vs zai-org/ZCode@main

A zcode pin starting with "pending:" means the audit is not done yet: the
script prints an audit notice and exits 0 (no automated comparison).

Exit codes:
  0  in sync (or audit-pending for zcode)
  1  HTTP / rate-limit / manifest error (clear message printed)
  2  DRIFT: pinned ref differs from upstream HEAD (a GitHub Actions failure
     step opens/comments the deduplicated drift issue)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = REPO_ROOT / "release-manifests"

COMPONENTS = {
    "blender": {
        "manifest_key": "blender",
        "upstream_repo": "blender/blender",
        "branch": "main",
        "issue_title": "Upstream drift: blender/blender",
    },
    "zcode": {
        "manifest_key": "zcode_runtime",
        "upstream_repo": "zai-org/ZCode",
        "branch": "main",
        "issue_title": "Upstream drift: zai-org/ZCode",
    },
}


def latest_manifest():
    """Return (data, filename) of the manifest latest by created, then version."""
    files = sorted(MANIFEST_DIR.glob("manifest-*.json"))
    if not files:
        raise RuntimeError(f"no release manifests found in {MANIFEST_DIR}")
    parsed = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{path.name}: cannot parse manifest: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"{path.name}: top level must be a JSON object")
        parsed.append((str(data.get("created", "")), str(data.get("version", "")), path.name, data))
    parsed.sort(key=lambda item: (item[0], item[1]))
    _, _, filename, data = parsed[-1]
    return data, filename


def fetch_upstream_sha(repo, branch):
    """Return the current HEAD sha of `repo`@`branch` via the GitHub API."""
    url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    headers = {
        "Accept": "application/vnd.github+json",
        # GitHub API requires a User-Agent header on every request.
        "User-Agent": "blender-cad-upstream-drift-check",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        if exc.code in (403, 429):
            detail = " (rate limit? set the GITHUB_TOKEN env var)"
        raise RuntimeError(f"GitHub API HTTP {exc.code} for {url}{detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"cannot reach GitHub API at {url}: {exc}") from exc
    sha = payload.get("sha") if isinstance(payload, dict) else None
    if not isinstance(sha, str) or len(sha) != 40:
        raise RuntimeError(f"unexpected GitHub API response for {url}: no 'sha' field")
    return sha


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare the pinned upstream ref in the latest release manifest "
                    "with the live upstream main branch (glossary §8 pin policy)."
    )
    parser.add_argument(
        "--component",
        required=True,
        choices=sorted(COMPONENTS),
        help="which upstream to check: blender (blender/blender) or zcode (zai-org/ZCode)",
    )
    args = parser.parse_args(argv)

    spec = COMPONENTS[args.component]
    try:
        manifest, manifest_name = latest_manifest()
        components = manifest.get("components")
        if not isinstance(components, dict) or spec["manifest_key"] not in components:
            print(
                f"ERROR: {manifest_name} has no components.{spec['manifest_key']}",
                file=sys.stderr,
            )
            return 1
        component = components[spec["manifest_key"]]
        if not isinstance(component, dict):
            print(
                f"ERROR: {manifest_name}: components.{spec['manifest_key']} must be an object",
                file=sys.stderr,
            )
            return 1
        pinned = component.get("upstream_ref")
        if not isinstance(pinned, str) or not pinned:
            print(
                f"ERROR: {manifest_name}: components.{spec['manifest_key']}.upstream_ref is missing",
                file=sys.stderr,
            )
            return 1

        if args.component == "zcode" and pinned.startswith("pending:"):
            print(
                f"AUDIT PENDING: {manifest_name} pins {pinned!r} — a human API-surface "
                "review is required before pinning (see docs/30-process/upstream-update-ci.md). "
                "No automated drift comparison performed."
            )
            return 0

        print(f"using {manifest_name} (created {manifest.get('created')}, version {manifest.get('version')})")
        upstream_sha = fetch_upstream_sha(spec["upstream_repo"], spec["branch"])
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if pinned == upstream_sha:
        print(f"in sync ({pinned})")
        return 0

    print(
        f"DRIFT: pinned {pinned} vs upstream {upstream_sha} "
        f"({spec['upstream_repo']}@{spec['branch']}) — triage the "
        f"'{spec['issue_title']}' issue and follow "
        "docs/00-architecture/repo-and-upstream-sync.md"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
