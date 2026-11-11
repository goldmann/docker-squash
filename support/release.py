#!/usr/bin/env python3
"""release.py - Pre-flight checks and GitHub release around zest.releaser.

zest.releaser (``fullrelease``) bumps the version, tags, builds, uploads to
PyPI and pushes. This wrapper checks the repository before that, and creates
the GitHub release for the new tag afterwards. See RELEASE_PLAN.md.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Set

BRANCH = "main"
REMOTE = "origin"
TAG_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ReleaseError(Exception):
    """A check or step failed; the message tells the operator why."""


def run(*cmd: str, check: bool = True) -> str:
    """Run a command and return its stripped stdout."""
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise ReleaseError(
            f"'{' '.join(cmd)}' failed: {(proc.stderr or proc.stdout).strip()}"
        )
    return proc.stdout.strip()


def list_tags() -> Set[str]:
    return set(run("git", "tag", "--list").splitlines())


def find_prev(tags: Set[str]) -> Optional[str]:
    """Return the highest X.Y.Z tag, or None if there is none."""
    versions = [t for t in tags if TAG_RE.match(t)]
    if not versions:
        return None
    return max(versions, key=lambda t: tuple(int(p) for p in t.split(".")))


def find_new(before: Set[str], after: Set[str]) -> str:
    """Return the one tag created between the two sets, else raise."""
    added = sorted(after - before)
    if len(added) != 1:
        raise ReleaseError(
            f"Expected exactly one new tag, found {len(added)}: {added or 'none'}"
        )
    return added[0]


def preflight() -> str:
    """Read-only checks. Return PREV."""
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        raise ReleaseError(f"Must be on '{BRANCH}', currently on '{branch}'")
    if run("git", "status", "--porcelain"):
        raise ReleaseError("Working tree is not clean")
    run("git", "fetch", REMOTE, "--tags")
    if run("git", "rev-parse", "HEAD") != run("git", "rev-parse", f"{REMOTE}/{BRANCH}"):
        raise ReleaseError(f"HEAD is not equal to {REMOTE}/{BRANCH}")
    run("gh", "auth", "status")
    conclusion = run(
        "gh",
        "run",
        "list",
        "--branch",
        BRANCH,
        "--limit",
        "1",
        "--json",
        "conclusion",
        "-q",
        ".[0].conclusion",
    )
    if conclusion != "success":
        raise ReleaseError(f"Latest CI run on {BRANCH} is '{conclusion or 'unknown'}'")
    prev = find_prev(list_tags())
    if prev is None:
        raise ReleaseError("No previous X.Y.Z tag found")
    if not (Path.home() / ".pypirc").is_file():
        raise ReleaseError("~/.pypirc does not exist")
    return prev


def confirm(question: str) -> bool:
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def github_release(prev: str, new: str, draft: bool, assume_yes: bool) -> None:
    if not run("git", "ls-remote", "--tags", REMOTE, new):
        raise ReleaseError(
            f"Tag {new} is not on {REMOTE}. Run 'git push --tags', then "
            f"'support/release.py --github-only {new}'"
        )
    if not assume_yes and not confirm(f"Create GitHub release {new} (from {prev})?"):
        raise ReleaseError("Aborted")
    cmd = [
        "gh",
        "release",
        "create",
        "--target",
        BRANCH,
        "--generate-notes",
        "--notes-start-tag",
        prev,
        "--verify-tag",
    ]
    if draft:
        cmd.append("--draft")
    run(*cmd, new)
    print(run("gh", "release", "view", new, "--json", "url", "-q", ".url"))


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Run the pre-flight only; change nothing"
    )
    parser.add_argument(
        "--draft", action="store_true", help="Create the GitHub release as a draft"
    )
    parser.add_argument(
        "--github-only",
        metavar="NEW",
        help="Skip zest.releaser; only create the GitHub release for tag NEW",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip this script's own confirmation"
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        prev = preflight()
        print(f"Previous release: {prev}")
        if args.check:
            return 0
        if args.github_only:
            new = args.github_only
            # PREV must be the tag before NEW, not NEW itself
            prev = find_prev(list_tags() - {new}) or prev
        else:
            before = list_tags()
            if subprocess.run(["fullrelease"], check=False).returncode != 0:
                raise ReleaseError("fullrelease failed; see RELEASE_PLAN.md section 6")
            run("git", "fetch", REMOTE, "--tags")
            new = find_new(before, list_tags())
        github_release(prev, new, args.draft, args.yes)
    except ReleaseError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
