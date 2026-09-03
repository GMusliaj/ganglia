#!/usr/bin/env python3
"""Build a compact, private Markdown catalog from local Codex JSONL sessions."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


IGNORED_PREFIXES = (
    "# AGENTS.md instructions",
    "<environment_context>",
    "<permissions instructions>",
    "<image name=",
    "Tip: New Use /fast",
)


@dataclass(frozen=True)
class SessionSummary:
    title: str
    description: str
    timestamp: str
    project: str
    requests: tuple[str, ...]


def compact(value: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def summarize(path: Path, request_limit: int = 16) -> SessionSummary:
    timestamp = ""
    project = ""
    requests: list[str] = []
    try:
        with path.open(encoding="utf-8") as source:
            for line in source:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = record.get("payload", {})
                if record.get("type") == "session_meta":
                    timestamp = str(
                        payload.get("timestamp") or record.get("timestamp") or ""
                    )
                    cwd = str(payload.get("cwd") or "")
                    project = Path(cwd).name if cwd else ""
                    continue
                if (
                    record.get("type") != "response_item"
                    or payload.get("type") != "message"
                    or payload.get("role") != "user"
                ):
                    continue
                for item in payload.get("content", []):
                    if item.get("type") != "input_text":
                        continue
                    text = str(item.get("text") or item.get("input_text") or "").strip()
                    if not text or text.startswith(IGNORED_PREFIXES):
                        continue
                    request = compact(text, 360)
                    if request not in requests:
                        requests.append(request)
                    if len(requests) >= request_limit:
                        break
                if len(requests) >= request_limit:
                    break
    except (OSError, UnicodeDecodeError):
        pass

    title = compact(requests[0], 88) if requests else path.stem
    description = f"Codex session{f' for {project}' if project else ''}: {title}"
    return SessionSummary(title, compact(description, 180), timestamp, project, tuple(requests))


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(summary: SessionSummary, source_path: Path) -> str:
    date = summary.timestamp[:10]
    request_lines = "\n".join(f"- {request}" for request in summary.requests)
    if not request_lines:
        request_lines = "- No user request could be extracted."
    return (
        "---\n"
        "type: session\n"
        f"title: {yaml_string(summary.title)}\n"
        f"description: {yaml_string(summary.description)}\n"
        f"date: {date}\n"
        f"timestamp: {yaml_string(summary.timestamp)}\n"
        f"project: {yaml_string(summary.project)}\n"
        f"source_path: {yaml_string(str(source_path))}\n"
        "---\n\n"
        f"# {summary.title}\n\n"
        "## Active\n\n"
        f"Project: {summary.project or 'unknown'}\n\n"
        "### User requests\n\n"
        f"{request_lines}\n\n"
        "## Source\n\n"
        "Generated locally from the corresponding Codex JSONL session.\n"
    )


def sync(source: Path, output: Path) -> tuple[int, int]:
    output.mkdir(parents=True, exist_ok=True)
    expected: set[Path] = set()
    written = 0
    for session_path in sorted(source.glob("**/*.jsonl")):
        relative = session_path.relative_to(source).with_suffix(".md")
        destination = output / relative
        expected.add(destination)
        content = render(summarize(session_path), session_path.resolve())
        if not destination.exists() or destination.read_text(encoding="utf-8") != content:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            written += 1

    removed = 0
    for existing in output.glob("**/*.md"):
        if existing not in expected:
            existing.unlink()
            removed += 1
    return written, removed


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.home() / ".codex" / "sessions")
    parser.add_argument("--output", type=Path, default=repository / "local" / "session-catalog")
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_dir():
        print(f"session catalog: source unavailable: {source}")
        return 0
    written, removed = sync(source, output)
    total = sum(1 for _ in output.glob("**/*.md"))
    print(f"session catalog: {total} sessions ({written} updated, {removed} removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
