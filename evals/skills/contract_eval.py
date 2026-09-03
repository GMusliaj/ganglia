"""Deterministic Markdown contract evaluation for checked-in Ganglia skills."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def evaluate(skill_path: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    skill = skill_path / "SKILL.md"
    try:
        content = skill.read_text(encoding="utf-8")
    except OSError:
        content = ""
    results: list[dict[str, Any]] = []
    earned = 0.0
    available = 0.0
    for case in cases:
        weight = float(case["weight"])
        passed = all(
            re.search(pattern, content, re.IGNORECASE | re.DOTALL) is not None
            for pattern in case["patterns"]
        )
        available += weight
        if passed:
            earned += weight
        results.append(
            {
                "id": case["id"],
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "summary": case["summary"],
            }
        )
    score = round(earned / available, 12) if available else 0.0
    return {
        "schema_version": 1,
        "kind": "skill-eval-result",
        "score": score,
        "cases": results,
    }


def print_result(skill_path: Path, cases: list[dict[str, Any]]) -> None:
    print(json.dumps(evaluate(skill_path, cases), sort_keys=True))
