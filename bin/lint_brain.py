#!/usr/bin/env python3
"""Validate shared Brain entries without mutating them."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from okf import parse


SHARED_FOLDERS = (
    "patterns",
    "lessons",
    "decisions",
    "concepts",
    "snippets",
    "sources",
    "infra",
)
KEBAB_CASE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+\.md)(?:#[^)]+)?\)")


def taxonomy(root: Path) -> set[str]:
    path = root / "meta" / "tag-taxonomy.md"
    if not path.exists():
        return set()
    return set(re.findall(r"^- `([a-z0-9-]+)`\s+—", path.read_text(encoding="utf-8"), re.MULTILINE))


def lint(root: Path) -> tuple[list[str], list[str]]:
    root = root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    allowed_tags = taxonomy(root)
    documents: dict[Path, object] = {}
    inbound: dict[Path, int] = {}

    for folder in SHARED_FOLDERS:
        base = root / folder
        if not base.exists():
            errors.append(f"{folder}: missing shared knowledge folder")
            continue
        for path in sorted(base.rglob("*.md")):
            if path.name != "index.md":
                resolved = path.resolve()
                documents[resolved] = parse(path)
                inbound[resolved] = 0

    for _, document in sorted(documents.items(), key=lambda item: str(item[0])):
        path = document.path
        relative = path.relative_to(root)
        metadata = document.metadata

        if not KEBAB_CASE.fullmatch(path.name):
            errors.append(f"{relative}: filename must be lowercase kebab-case")
        if not metadata.get("type"):
            errors.append(f"{relative}: missing required frontmatter field 'type'")
        for field in ("title", "description", "tags", "date"):
            if field not in metadata:
                warnings.append(f"{relative}: optional retrieval field '{field}' is missing")
        if "date" in metadata and not DATE.fullmatch(str(metadata["date"])):
            errors.append(f"{relative}: date must use YYYY-MM-DD")

        raw_tags = metadata.get("tags", [])
        if raw_tags and not isinstance(raw_tags, list):
            errors.append(f"{relative}: tags must be a YAML list")
        elif isinstance(raw_tags, list):
            for tag in raw_tags:
                if tag not in allowed_tags:
                    errors.append(f"{relative}: unregistered tag '{tag}'")

        if "## Active" not in document.body and "## Superseded" not in document.body:
            warnings.append(
                f"{relative}: missing lifecycle section ('## Active' or '## Superseded')"
            )
        if "## Source" not in document.body:
            warnings.append(f"{relative}: missing provenance section '## Source'")

        for target in MARKDOWN_LINK.findall(document.body):
            if "://" in target:
                continue
            decoded = target.replace("%20", " ")
            resolved = (path.parent / decoded).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{relative}: link escapes Brain root: {target}")
                continue
            if not resolved.exists():
                errors.append(f"{relative}: broken Markdown link: {target}")
            elif resolved in inbound:
                inbound[resolved] += 1

    for path, count in sorted(inbound.items(), key=lambda item: str(item[0])):
        if count == 0:
            warnings.append(
                f"{path.relative_to(root)}: no inbound links from another shared entry"
            )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()
    errors, warnings = lint(args.root.resolve())
    for warning in warnings:
        print(f"warning: {warning}")
    for error in errors:
        print(f"error: {error}")
    print(f"Brain lint: {len(errors)} error(s), {len(warnings)} warning(s).")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
