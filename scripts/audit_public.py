#!/usr/bin/env python3
"""Audit the current publication surface and all reachable Git history."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import guard_shared


def git_output(root: Path, *args: str) -> bytes | None:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def safe_author_email(value: str) -> bool:
    folded = value.casefold()
    if not value:
        return True
    if "@" not in folded:
        return False
    return folded.endswith("@users.noreply.github.com") or folded.endswith(
        "@localhost"
    ) or folded.rsplit("@", 1)[-1] in guard_shared.EXAMPLE_EMAIL_DOMAINS


def safe_author_name(value: str, private_terms: list[tuple[str, str]]) -> bool:
    folded = value.strip().casefold()
    return not folded or not any(
        term.casefold() in folded or folded in term.casefold()
        for _, term in private_terms
    )


def author_findings(root: Path) -> list[str]:
    output = git_output(root, "log", "--all", "--format=%H%x00%an%x00%ae")
    if output is None:
        return ["history: unable to inspect commit-author metadata"]
    findings: list[str] = []
    private_terms = guard_shared.runtime_identity_terms(root)
    for line in output.decode("utf-8", errors="replace").splitlines():
        commit, _, remainder = line.partition("\0")
        name, _, email = remainder.partition("\0")
        if not safe_author_email(email.strip()) or not safe_author_name(
            name, private_terms
        ):
            findings.append(
                f"history:{commit[:12]}: commit author identity exposes public metadata"
            )
    return findings


def ref_findings(root: Path) -> list[str]:
    output = git_output(root, "for-each-ref", "--format=%(refname)")
    if output is None:
        return ["history: unable to inspect Git reference names"]
    terms = guard_shared.denylist(root) + guard_shared.runtime_identity_terms(root)
    findings: list[str] = []
    for raw_ref in output.decode("utf-8", errors="replace").splitlines():
        if guard_shared.private_path_reason(Path(raw_ref), terms):
            findings.append(
                "history:<redacted-ref>: private identity exists in a reachable Git reference name"
            )
    return findings


def blob_records(root: Path) -> list[tuple[str, str]] | None:
    output = git_output(root, "rev-list", "--objects", "--all")
    if output is None:
        return None
    records: list[tuple[str, str]] = []
    for line in output.decode("utf-8", errors="surrogateescape").splitlines():
        object_id, _, path = line.partition(" ")
        object_type = git_output(root, "cat-file", "-t", object_id)
        if object_type and object_type.strip() == b"blob":
            records.append((object_id, path or "<unnamed-blob>"))
    return records


def history_findings(root: Path) -> list[str]:
    records = blob_records(root)
    if records is None:
        return ["history: unable to enumerate reachable Git objects"]
    findings: list[str] = []
    terms = guard_shared.denylist(root) + guard_shared.runtime_identity_terms(root)
    seen: set[str] = set()
    for object_id, raw_path in records:
        if object_id in seen:
            continue
        seen.add(object_id)
        path = Path(raw_path)
        if reason := guard_shared.private_path_reason(path, terms):
            findings.append(
                f"history:{object_id[:12]}:<redacted-path>: {reason} exists in reachable history"
            )
            continue
        content = git_output(root, "cat-file", "blob", object_id)
        if content is None:
            findings.append(
                f"history:{object_id[:12]}:{path}: unable to inspect reachable blob"
            )
            continue
        for line_number, line in enumerate(
            content.decode("utf-8", errors="replace").splitlines(), 1
        ):
            for pattern in guard_shared.MACHINE_PATHS:
                match = pattern.search(line)
                if match and not guard_shared.safe_example_machine_path(match):
                    findings.append(
                        f"history:{object_id[:12]}:{path}:{line_number}: machine-specific home path exists in reachable history"
                    )
                    break
            for source, term in terms:
                if term.casefold() in line.casefold():
                    findings.append(
                        f"history:{object_id[:12]}:{path}:{line_number}: private identity term from {source} exists in reachable history"
                    )
            for match in guard_shared.EMAIL.finditer(line):
                if not guard_shared.safe_email(match):
                    findings.append(
                        f"history:{object_id[:12]}:{path}:{line_number}: personal email address exists in reachable history"
                    )
            for label, pattern in guard_shared.SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        f"history:{object_id[:12]}:{path}:{line_number}: {label} exists in reachable history"
                    )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--working-tree-only",
        action="store_true",
        help="Skip reachable Git history and commit-author metadata",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    findings = guard_shared.scan(root, include_runtime_identity=True)
    if not args.working_tree_only:
        findings.extend(author_findings(root))
        findings.extend(ref_findings(root))
        findings.extend(history_findings(root))

    if findings:
        for finding in findings:
            print(finding)
        print("Public-release audit blocked publication.")
        return 1
    print("Public-release audit passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
