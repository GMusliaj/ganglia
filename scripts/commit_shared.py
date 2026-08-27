#!/usr/bin/env python3
"""Commit the shared Brain allowlist without touching unrelated staged work."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


ALLOWLIST = (
    "MEMORY.md",
    "patterns",
    "lessons",
    "decisions",
    "concepts",
    "snippets",
    "sources",
    "infra",
    "meta/tag-taxonomy.md",
)


class CommitError(RuntimeError):
    """The isolated shared-memory commit failed."""


def run_git(
    root: Path,
    arguments: list[str],
    *,
    index: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if index is not None:
        environment["GIT_INDEX_FILE"] = str(index)
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise CommitError(message)
    return result


def commit_message(changed: list[str]) -> str:
    if len(changed) == 1:
        return f"brain: update {Path(changed[0]).stem}"
    return f"brain: update {len(changed)} knowledge files"


def commit_shared(root: Path) -> list[str]:
    root = root.resolve()
    descriptor, temporary_name = tempfile.mkstemp(prefix="brain-shared-index-")
    os.close(descriptor)
    temporary_index = Path(temporary_name)
    temporary_index.unlink()
    try:
        run_git(root, ["read-tree", "HEAD"], index=temporary_index)
        run_git(root, ["add", "--", *ALLOWLIST], index=temporary_index)
        changed_result = run_git(
            root,
            ["diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            index=temporary_index,
        )
        changed = [line for line in changed_result.stdout.splitlines() if line]
        if not changed:
            return []
        run_git(
            root,
            ["commit", "-m", commit_message(changed)],
            index=temporary_index,
        )
        run_git(root, ["reset", "-q", "HEAD", "--", *ALLOWLIST])
        return changed
    finally:
        temporary_index.unlink(missing_ok=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        changed = commit_shared(root)
    except CommitError as exc:
        print(f"shared commit failed: {exc}")
        return 1
    if not changed:
        print("No shared knowledge changes to commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
