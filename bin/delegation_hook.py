#!/usr/bin/env python3
"""Bounded read routing for Codex PreToolUse; never executes inspected commands.

Adapted from Spotify shunt's design (Apache-2.0), with issue #10 regressions.
This is a context guardrail for a documented shell subset, not a shell sandbox.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys


MAX_EVENT_BYTES = 128_000
MAX_FILES = 64
READERS = {"cat", "head", "tail", "less", "more", "sed"}


class ShellWord(str):
    """A decoded shell word retaining a quote-aware glob pattern."""

    def __new__(cls, value: str, glob_pattern: str):
        word = super().__new__(cls, value)
        word.glob_pattern = glob_pattern
        return word


def shell_words(command: str) -> list[ShellWord]:
    # shlex discards quoting. Tokenize a parallel copy with quoted/escaped glob
    # characters made literal, keeping the actual word for options, cd, etc.
    pattern_source = []
    quote = None
    escaped = False
    for char in command:
        if escaped:
            pattern_source.append(glob.escape(char))
            escaped = False
        elif char == "\\" and quote != "'":
            pattern_source.append(char)
            escaped = True
        elif char in {"'", '"'} and quote in {None, char}:
            quote = char if quote is None else None
            pattern_source.append(char)
        else:
            pattern_source.append(glob.escape(char) if quote else char)

    def tokenize(source: str) -> list[str]:
        lexer = shlex.shlex(source.replace("\n", " ; "), posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        return list(lexer)

    return [ShellWord(value, pattern) for value, pattern in
            zip(tokenize(command), tokenize("".join(pattern_source)), strict=True)]


def read_extent(path: Path, limit: int, offset: int = 0, tail: bool = False,
                byte_count: int | None = None, max_bytes: int = 50_000) -> tuple[int, int]:
    """Inspect at most max_bytes + 1 bytes, including a partial final line.

    Line slices are measured as well as counted: one minified line can exceed
    the byte budget. Offset scanning is capped to keep every hook inexpensive.
    """
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444:
        return 0, 0
    with path.open("rb") as stream:
        if byte_count is not None:
            selected_size = min(info.st_size, byte_count)
            if tail:
                stream.seek(info.st_size - selected_size)
            content = stream.read(min(selected_size, max_bytes + 1))
            # Count the output slice, including an unterminated final line.
            lines = content.count(b"\n") + int(bool(content) and not content.endswith(b"\n"))
            return lines, len(content)
        if tail:
            stream.seek(max(0, info.st_size - max_bytes - 1))
            content = stream.read(max_bytes + 1)
            lines = content.splitlines(keepends=True)
            selected = lines[-limit:] if limit else []
            return len(selected), sum(map(len, selected))
        scanned = 0
        for _ in range(offset):
            row = stream.readline(max_bytes + 1)
            scanned += len(row)
            if scanned > 1_000_000 or len(row) > max_bytes:
                return 0, max_bytes + 1
            if not row:
                return 0, 0
        lines = size = 0
        while lines < limit:
            row = stream.readline(max_bytes - size + 1)
            if not row:
                break
            lines += 1
            size += len(row)
            if size > max_bytes:
                break
        return lines, size


def count_option(args: list[str]) -> tuple[list[str], int | None, int | None]:
    """Parse head/tail's common numeric forms. Unknown flags aren't exemptions."""
    paths: list[str] = []
    lines: int | None = 10
    count_bytes: int | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            paths.extend(args[index + 1:])
            break
        if arg in {"-n", "-c", "--lines", "--bytes"}:
            index += 1
            if index >= len(args) or not args[index].isdigit():
                return paths + args[index + 1:], None, None
            count = int(args[index])
            if arg in {"-c", "--bytes"}:
                count_bytes = count
            else:
                lines = count
        elif re.fullmatch(r"-(?:n|c)?\d+", arg) or re.fullmatch(r"--(?:lines|bytes)=\d+", arg):
            count = int(re.search(r"\d+$", arg).group())
            if arg.startswith(("-c", "--bytes=")):
                count_bytes = count
            else:
                lines = count
        elif arg.startswith("-"):
            if arg not in {"-q", "--quiet", "--silent", "-v", "--verbose"}:
                lines = None
        else:
            paths.append(arg)
        index += 1
    return paths, lines, count_bytes


def command_reads(command: str, cwd: Path) -> tuple[list[tuple], bool]:
    """Recognize literal read commands, chains, basic cd, and bounded filters.

    Unknown expansions/interpreters are reported as unsupported; never eval or
    execute a shell to resolve them. Quoted control operators are unsupported.
    """
    tokens = shell_words(command)
    segments: list[tuple[list[str], str]] = []
    current: list[str] = []
    for token in tokens:
        if token in {";", "&&", "||", "|", "&"}:
            segments.append((current, token))
            current = []
        else:
            current.append(token)
    segments.append((current, ""))
    reads: list[tuple] = []
    unsupported = False
    for index, (args, separator) in enumerate(segments):
        if not args:
            continue
        while args and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", args[0]) or args[0] in {"command", "env"}):
            args = args[1:]
        if not args:
            continue
        name = Path(args[0]).name
        if name == "cd" and len(args) == 2:
            cwd = (cwd / args[1]).resolve()
            continue
        if name not in READERS:
            if name in {"bash", "sh", "zsh", "python", "python3", "node", "awk"}:
                unsupported = True
            continue
        if any("$" in arg or "`" in arg for arg in args):
            unsupported = True
            continue
        # Redirection is not an exemption: descriptors, quoted operators and
        # /dev/stdout make a blanket '>' shortcut unsound. Count conservatively.
        args = [arg for arg in args if arg != "<"]
        limit: int | None = None
        offset = 0
        byte_count = None
        is_tail = name == "tail"
        if name in {"head", "tail"}:
            paths, limit, byte_count = count_option(args[1:])
        elif name == "sed":
            match = re.fullmatch(r"(\d+)(?:,(\d+))?p", args[2]) if len(args) >= 4 and args[1] == "-n" else None
            if not match:
                unsupported = True
                continue
            offset = max(0, int(match[1]) - 1)
            limit = int(match[2] or match[1]) - offset
            paths = args[3:]
        else:
            paths = [arg for arg in args[1:] if not arg.startswith("-")]
        # Only a known numeric output bound reduces a pipeline's extent.
        if name in {"cat", "less", "more"} and separator == "|" and index + 1 < len(segments):
            following = segments[index + 1][0]
            if following and Path(following[0]).name in {"head", "tail"}:
                _, bound, byte_bound = count_option(following[1:])
                limit = bound if limit is None else min(limit, bound) if bound is not None else limit
                byte_count = byte_bound
                is_tail = Path(following[0]).name == "tail"
        for path in paths:
            # cwd is already resolved: its glob characters are always literal.
            pattern = str(Path(glob.escape(str(cwd))) / path.glob_pattern)
            matches = glob.iglob(pattern) if glob.has_magic(pattern) else iter([str(cwd / path)])
            for resolved in matches:
                reads.append((Path(resolved), limit, offset, is_tail, byte_count))
                if len(reads) > MAX_FILES:
                    return reads, True
    return reads, unsupported


def assess(event: dict, max_lines: int = 350, max_bytes: int = 50_000) -> tuple[bool, str]:
    if event.get("hook_event_name", "PreToolUse") != "PreToolUse":
        return False, ""
    tool = event.get("tool_name", "")
    values = event.get("tool_input", {})
    if not isinstance(values, dict):
        return False, ""
    cwd = Path(event.get("cwd") or os.getcwd())
    reads = []
    unsupported = False
    if tool in {"Bash", "exec_command", "shell_command"}:
        command = values.get("command", values.get("cmd", ""))
        if not isinstance(command, str):
            return False, ""
        reads, unsupported = command_reads(command, Path(values.get("workdir") or cwd))
    elif tool == "Read":
        path = values.get("file_path")
        if not isinstance(path, str) or not path:
            return False, ""
        limit = values.get("limit")
        offset = values.get("offset", 0)
        limit = limit if type(limit) is int and limit > 0 else None
        offset = max(0, offset - 1) if type(offset) is int else 0
        reads = [(cwd / path, limit, offset, False, None)]
    total_lines = total_bytes = 0
    for path, limit, offset, is_tail, byte_count in reads[:MAX_FILES]:
        # Mandatory instruction files must remain completely readable.
        if path.name in {"AGENTS.md", "AGENTS.override.md", "SKILL.md"}:
            continue
        try:
            lines, size = read_extent(path, limit if limit is not None else max_lines + 1,
                                      offset, is_tail, byte_count, max_bytes)
        except (OSError, ValueError):
            continue  # The real tool should explain an unreadable/missing file.
        total_lines += lines
        total_bytes += size
        if total_lines > max_lines or total_bytes > max_bytes:
            return True, "Large read exceeds the context budget. Use $bulk-reader for a summary, or a smaller line/byte slice for exact edits."
    if len(reads) > MAX_FILES:
        return True, "Read expands to too many files. Use explicit smaller batches with $bulk-reader."
    return False, "Shell form is outside the routing guard's supported subset." if unsupported else ""


def hook_output(denied: bool, reason: str, mode: str) -> dict:
    # Neutral success does not auto-approve a tool or override another policy.
    if denied and mode == "enforce":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}
    if reason:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": reason}}
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("observe", "enforce"), default="observe")
    parser.add_argument("--max-lines", type=int, default=350)
    parser.add_argument("--max-bytes", type=int, default=50_000)
    args = parser.parse_args()
    try:
        if not 1 <= args.max_lines <= 10_000 or not 1 <= args.max_bytes <= 1_000_000:
            raise ValueError("invalid routing limits")
        raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            raise ValueError("hook event exceeds byte limit")
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("hook input must be an object")
        denied, reason = assess(event, args.max_lines, args.max_bytes)
        print(json.dumps(hook_output(denied, reason, args.mode)))
        return 0
    except (ValueError, OSError, TypeError):
        # Exit 2 is Codex's documented blocking status. Never emit invalid JSON.
        print("Delegation hook could not validate the request; inspect the hook input.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
