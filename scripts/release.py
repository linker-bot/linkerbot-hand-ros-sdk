#!/usr/bin/env python3
"""Check and optionally tag a ROS source snapshot.

Users install Transport, Hand SDK and ROS from their latest main branches.
Optional signed tags and Gitea Releases contain source only. No package artifacts
are uploaded. GITEA_TOKEN is needed only to create a Release.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = "https://gitea.linkerhub.work"
OWNER = "zhuzhixiang"
REPOSITORY = "linkerbot-hand-ros2"
API = f"{HOST}/api/v1/repos/{OWNER}/{REPOSITORY}"

# Shown in the Gitea Release title. Nothing is uploaded, so there is no
# distribution name or wheel stem to track.
DIST = "linkerbot-hand-ros"

# The four places this repository states its own version. ``linkerbot_hand_gui``
# is versioned independently and deliberately absent.
VERSION_SOURCES: tuple[tuple[str, str], ...] = (
    ("linkerbot_hand_ros/setup.py", r'version="([^"]+)"'),
    ("linkerbot_hand_ros/package.xml", r"<version>([^<]+)</version>"),
    ("linkerbot_hand_msgs/package.xml", r"<version>([^<]+)</version>"),
    ("linkerbot_hand_ros/linkerbot_hand_ros/__init__.py", r'__version__ = "([^"]+)"'),
)


class Failure(Exception):
    """A gate rejected the release. The message says which one and why."""


def run(*args: str) -> str:
    """Run one command from the repository root, raising Failure on non-zero."""

    completed = subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise Failure(f"command failed: {' '.join(args)}\n{detail}")
    return (completed.stdout or "").strip()


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def declared_version() -> str:
    """Return the version, requiring all four declarations to agree.

    ``test_python_and_ros_package_versions_match`` checks the same invariant.
    """

    found: dict[str, str] = {}
    for relative, pattern in VERSION_SOURCES:
        match = re.search(pattern, read(relative))
        if match is None:
            raise Failure(f"{relative} declares no version matching {pattern}")
        found[relative] = match.group(1)
    distinct = set(found.values())
    if len(distinct) != 1:
        detail = "; ".join(f"{name} = {value}" for name, value in found.items())
        raise Failure(f"the four version declarations disagree: {detail}")
    return distinct.pop()


def check_working_tree(*, require_main: bool) -> None:
    """Reject a dirty tree, and on the tagging path an unsynced branch.

    ``require_main`` is False when back-filling a Release: that runs from a
    detached tag checkout, so "on main" cannot hold. The tracked-file half still
    applies — the release notes are generated from the working tree, and
    uncommitted edits would put text in a Release that is in no commit.
    """

    if run("git", "status", "--porcelain", "--untracked-files=no"):
        raise Failure("tracked files are modified; commit or stash first")
    if not require_main:
        return
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        raise Failure(f"releases are cut from main, not {branch!r}")
    run("git", "fetch", "origin", "--quiet")
    if run("git", "rev-parse", "HEAD") != run("git", "rev-parse", "origin/main"):
        raise Failure("main differs from origin/main; pull or push first")


def check_tag_absent(version: str) -> None:
    tag = f"v{version}"
    if run("git", "tag", "--list", tag):
        raise Failure(f"tag {tag} already exists locally")
    if run("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"):
        raise Failure(f"tag {tag} already exists on origin")


def check_tag_points_at_head(version: str) -> None:
    """Require ``v<version>`` to exist and to be the commit checked out.

    Used by ``release`` when back-filling a Release for a tag that already has
    one missing. The body is generated from the checked-out source, so
    creating it from any other commit would publish notes that do not describe the
    tagged source.
    """

    tag = f"v{version}"
    if not run("git", "tag", "--list", tag):
        raise Failure(f"tag {tag} does not exist; run 'release.py tag' first")
    tagged = run("git", "rev-list", "-n1", tag)
    head = run("git", "rev-parse", "HEAD")
    if tagged != head:
        raise Failure(
            f"HEAD is {head[:9]} but {tag} points at {tagged[:9]}; the release "
            f"notes come from the working tree — run 'git checkout {tag}' first"
        )


def api_token() -> str:
    """Return the Gitea token. Nothing is uploaded, so no username is needed."""

    token = os.environ.get("GITEA_TOKEN")
    if not token:
        raise Failure("set GITEA_TOKEN to create a Gitea Release")
    return token


def api_request(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> tuple[int, object]:
    """Call the Gitea API, returning the status and decoded body.

    A 404 is returned rather than raised: callers use it to decide whether a
    Release already exists, which is how creating one stays idempotent.
    """

    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(f"{API}{path}", data=body, method=method)
    request.add_header("Authorization", f"token {api_token()}")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", "replace")
            return response.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", "replace")
        if error.code == 404:
            return 404, None
        raise Failure(f"{method} {path} returned {error.code}: {text[:300]}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise Failure(f"{method} {path} failed: {error}") from error


def release_notes(version: str) -> str:
    """Describe an optional source snapshot and link its installation guide."""

    source = f"{HOST}/{OWNER}/{REPOSITORY}/src/tag/v{version}"
    history = f"{HOST}/{OWNER}/{REPOSITORY}/commits/tag/v{version}"
    return (
        f"源码快照 v{version}。变更见 [Git 历史]({history})。\n\n"
        "日常安装使用 Transport、Hand SDK 和 ROS 仓库的最新 `main` 分支，"
        "依赖安装和 colcon 构建步骤见 "
        f"[README_zh.md]({source}/README_zh.md)。\n\n"
        "本 Release 仅提供源码，不附二进制产物，也不上传到包 registry。"
    )


def create_release(version: str) -> None:
    """Create an optional source-only Gitea Release, skipping existing ones."""

    tag = f"v{version}"
    status, existing = api_request(f"/releases/tags/{tag}")
    if status == 200 and isinstance(existing, dict):
        print(f"  skip Release {tag} already exists")
        return
    _, created = api_request(
        "/releases",
        method="POST",
        payload={
            "tag_name": tag,
            "name": f"{DIST} {version}",
            "body": release_notes(version),
            "draft": False,
            "prerelease": False,
        },
    )
    if not isinstance(created, dict) or "id" not in created:
        raise Failure(f"creating Release {tag} returned no id: {created!r}")
    print(f"  ok   Release {tag} created with no attached artifact")


def check_quality() -> None:
    if shutil.which("ruff") is None:
        raise Failure("ruff is not on PATH")
    run("ruff", "check", ".")
    run("ruff", "format", "--check", ".")
    # The repository's pytest clashes with ROS jazzy's launch_testing plugin,
    # which registers an outdated pytest_pycollect_makemodule hookimpl.
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise Failure(f"pytest failed:\n{completed.stdout.strip()}")


def command_check(version: str, *, tag_exists: bool = False) -> None:
    """Run every gate in order, stopping at the first failure.

    ``tag_exists`` is set by ``release`` when back-filling: the tag is already
    pushed, so the gate becomes "it exists and is what is checked out" and the
    branch cannot be ``main``.
    """

    print(f"linkerbot-hand-ros {version}")
    print(f"  ok   four version declarations agree on {version}")

    check_working_tree(require_main=not tag_exists)
    print("  ok   working tree")

    if tag_exists:
        check_tag_points_at_head(version)
        print(f"  ok   tag v{version} points at HEAD")
    else:
        check_tag_absent(version)
        print(f"  ok   tag v{version} unused")

    check_quality()
    print("  ok   quality")


def command_tag(version: str) -> None:
    """Push the signed tag and create the Release.

    Both in one command because there is nothing to build in between, and because
    HEAD is the commit being tagged, so the release notes generated from the
    working tree describe exactly the tagged source.
    """

    command_check(version)
    tag = f"v{version}"
    run("git", "tag", "-s", tag, "-m", f"linkerbot-hand-ros {version}")
    run("git", "verify-tag", tag)
    run("git", "push", "origin", tag)
    print(f"  ok   pushed signed tag {tag}")
    create_release(version)


def command_release(version: str) -> None:
    """Create the Release for a tag that already has none.

    Requires the tag to be checked out so the notes match the tagged source.
    """

    command_check(version, tag_exists=True)
    create_release(version)


def command_verify_tag(version: str, tag: str) -> None:
    """Confirm a tag matches the package versions without a ROS toolchain."""

    print(f"linkerbot-hand-ros {version}, tag {tag}")
    if tag != f"v{version}":
        raise Failure(
            f"tag {tag} does not match the declared version {version}; either the "
            "tag is wrong or it was pushed before the version bump merged"
        )
    print(f"  ok   {tag} matches the four version declarations")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "tag", "release", "verify-tag"))
    parser.add_argument(
        "--tag", help="the tag to validate; required by verify-tag, ignored otherwise"
    )
    arguments = parser.parse_args()
    try:
        version = declared_version()
        if arguments.command == "check":
            command_check(version)
        elif arguments.command == "tag":
            command_tag(version)
        elif arguments.command == "release":
            command_release(version)
        else:
            if not arguments.tag:
                raise Failure("verify-tag needs --tag")
            command_verify_tag(version, arguments.tag)
    except Failure as error:
        print(f"\nrelease {arguments.command} refused:\n  {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
