#!/usr/bin/env python3
"""Fail when private, machine-specific, or secret material could be published."""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
from pathlib import Path
from typing import Iterable


FALLBACK_IGNORED_PARTS = {
    ".git",
    ".qmd",
    ".tmp",
    "__pycache__",
    "local",
    "node_modules",
}
MACHINE_PATHS = (
    re.compile(r"/Users/[A-Za-z0-9._-]+(?:/|$)"),
    re.compile(r"/home/[A-Za-z0-9._-]+(?:/|$)"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+(?:\\|$)"),
)
EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)
EXAMPLE_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "users.noreply.github.com",
}
SECRET_PATTERNS = (
    (
        "private key material",
        re.compile("-" * 5 + r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    ),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}")),
    ("OpenAI-style API key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
)
GENERIC_IDENTITY_TERMS = {
    "admin",
    "codex",
    "guest",
    "localhost",
    "macbook",
    "owner",
    "root",
    "unknown",
    "user",
}


def denylist(root: Path) -> list[tuple[str, str]]:
    path = root / "local" / "shared-denylist.txt"
    if not path.exists():
        return []
    return [
        (f"local/shared-denylist.txt:{number}", line.strip())
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        )
        if line.strip() and not line.lstrip().startswith("#")
    ]


def command_value(root: Path, *command: str) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def runtime_identity_terms(root: Path) -> list[tuple[str, str]]:
    candidates = {
        "home directory name": Path.home().name,
        "login name": os.environ.get("LOGNAME", ""),
        "user name": os.environ.get("USER", ""),
        "host name": socket.gethostname().split(".", 1)[0],
        "Git author name": command_value(root, "git", "config", "--get", "user.name"),
        "Git author email": command_value(root, "git", "config", "--get", "user.email"),
    }
    terms: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source, value in candidates.items():
        normalized = value.strip()
        folded = normalized.casefold()
        if len(normalized) < 4 or folded in GENERIC_IDENTITY_TERMS or folded in seen:
            continue
        seen.add(folded)
        terms.append((source, normalized))
    return terms


def git_candidates(root: Path) -> list[Path] | None:
    try:
        completed = subprocess.run(
            (
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ),
            cwd=root,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return sorted(
        root / Path(raw.decode("utf-8", errors="surrogateescape"))
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def publication_candidates(root: Path) -> list[Path]:
    candidates = git_candidates(root)
    if candidates is not None:
        return candidates
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(
            part in FALLBACK_IGNORED_PARTS
            for part in path.relative_to(root).parts
        )
    )


def safe_email(match: re.Match[str]) -> bool:
    domain = match.group(0).rsplit("@", 1)[1].casefold()
    return domain in EXAMPLE_EMAIL_DOMAINS


def safe_example_machine_path(match: re.Match[str]) -> bool:
    normalized = match.group(0).replace("\\", "/").casefold()
    return normalized.startswith("/users/example/") or normalized.startswith(
        "/home/example/"
    ) or normalized.startswith("c:/users/example/")


def private_path_reason(relative: Path, terms: list[tuple[str, str]]) -> str | None:
    value = relative.as_posix()
    for source, term in terms:
        if term.casefold() in value.casefold():
            return f"private identity term from {source}"
    for match in EMAIL.finditer(value):
        if not safe_email(match):
            return "personal email address"
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(value):
            return label
    return None


def scan(
    root: Path,
    paths: Iterable[Path] | None = None,
    *,
    include_runtime_identity: bool = False,
) -> list[str]:
    root = root.resolve()
    failures: list[str] = []
    terms = denylist(root)
    if include_runtime_identity:
        terms.extend(runtime_identity_terms(root))

    for path in paths if paths is not None else publication_candidates(root):
        candidate = path if path.is_absolute() else root / path
        if not candidate.exists():
            continue
        if candidate.is_symlink():
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                relative = Path("<outside-root>")
            failures.append(
                f"{relative}:1: symlinks are forbidden in publishable content because their target can bypass review"
            )
            continue
        path = candidate.resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            failures.append("<outside-root>:1: publication candidate escapes the repository")
            continue
        if reason := private_path_reason(relative, terms):
            failures.append(
                f"<redacted-path>:1: {reason} is forbidden in a publishable path"
            )
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as error:
            failures.append(
                f"{relative}:1: could not inspect publication candidate: {error}"
            )
            continue

        for line_number, line in enumerate(lines, 1):
            for pattern in MACHINE_PATHS:
                match = pattern.search(line)
                if match and not safe_example_machine_path(match):
                    failures.append(
                        f"{relative}:{line_number}: machine-specific home path is forbidden in publishable content"
                    )
                    break
            for source, term in terms:
                if term.casefold() in line.casefold():
                    failures.append(
                        f"{relative}:{line_number}: private identity term from {source} is forbidden in publishable content"
                    )
            for match in EMAIL.finditer(line):
                if not safe_email(match):
                    failures.append(
                        f"{relative}:{line_number}: personal email address is forbidden in publishable content"
                    )
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    failures.append(
                        f"{relative}:{line_number}: {label} is forbidden in publishable content"
                    )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    failures = scan(args.root.resolve(), include_runtime_identity=True)
    if failures:
        for failure in failures:
            print(failure)
        print("Publication guard blocked the operation.")
        return 1
    print("Publication guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
