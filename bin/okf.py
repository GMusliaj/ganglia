#!/usr/bin/env python3
"""Small OKF-lite parser shared by Brain tooling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Document:
    path: Path
    metadata: dict[str, object]
    body: str


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse(path: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return Document(path, {}, text)
    end = text.find("\n---\n", 4)
    if end < 0:
        return Document(path, {}, text)

    metadata: dict[str, object] = {}
    active_list: str | None = None
    for line in text[4:end].splitlines():
        item = re.match(r"^\s+-\s+(.+)$", line)
        if item and active_list:
            values = metadata.setdefault(active_list, [])
            assert isinstance(values, list)
            values.append(unquote(item.group(1).strip()))
            continue

        field = re.match(r"^([a-z][a-z0-9_-]*):\s*(.*)$", line)
        if not field:
            continue
        key, raw = field.groups()
        if not raw:
            metadata[key] = []
            active_list = key
        elif raw.startswith("[") and raw.endswith("]"):
            metadata[key] = [
                unquote(value.strip())
                for value in raw[1:-1].split(",")
                if value.strip()
            ]
            active_list = None
        else:
            metadata[key] = unquote(raw)
            active_list = None

    return Document(path, metadata, text[end + 5 :])
