#!/usr/bin/env python3
"""Evaluate the safety and gating contract of one skill-evolution snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from contract_eval import print_result


CASES = [
    {
        "id": "skill-identity",
        "weight": 1,
        "patterns": [r"(?m)^name:\s*skill-evolution\s*$", r"(?m)^description:\s*.+$"],
        "summary": "The snapshot declares the skill-evolution skill and description.",
    },
    {
        "id": "wikiskill-provenance",
        "weight": 1,
        "patterns": [r"WikiSkill", r"2608\.27454", r"prior-art"],
        "summary": "The skill preserves WikiSkill attribution and routes to deviations.",
    },
    {
        "id": "atomic-target",
        "weight": 1,
        "patterns": [r"exactly\s+one", r"\.agents/skills/.+SKILL\.md"],
        "summary": "Generated proposals target exactly one repo-local SKILL.md.",
    },
    {
        "id": "private-workspace",
        "weight": 1,
        "patterns": [r"local/skill-evolution", r"\.tmp/"],
        "summary": "Evidence and candidates remain in ignored private workspace paths.",
    },
    {
        "id": "privacy-exclusions",
        "weight": 1,
        "patterns": [r"raw\s+reasoning|unrestricted\s+traces", r"credentials|identity"],
        "summary": "The workflow excludes sensitive and unrestricted trace content.",
    },
    {
        "id": "distinct-task-recurrence",
        "weight": 1,
        "patterns": [r"two\s+distinct\s+task", r"one\s+task\s+cannot|one\s+task"],
        "summary": "Patterns require recurrence across distinct tasks.",
    },
    {
        "id": "deterministic-evaluator",
        "weight": 1,
        "patterns": [r"deterministic", r"evals/skills"],
        "summary": "Proposals use deterministic repository-owned evaluator adapters.",
    },
    {
        "id": "strict-no-regression-gate",
        "weight": 1,
        "patterns": [r"strictly\s+(greater|higher)", r"no\s+regression|regress"],
        "summary": "The automated gate requires strict improvement without regressions.",
    },
    {
        "id": "human-content-gate",
        "weight": 1,
        "patterns": [r"explicit\s+human", r"candidate\s+digest|exact\s+candidate\s+digest"],
        "summary": "Human acceptance is explicit and bound to the exact candidate.",
    },
    {
        "id": "no-automatic-publication",
        "weight": 1,
        "patterns": [
            r"never\s+commits?|does\s+not\s+commit|applying\s+does\s+not\s+commit",
            r"push",
        ],
        "summary": "Application does not commit or push automatically.",
    },
    {
        "id": "verified-rollback",
        "weight": 1,
        "patterns": [r"scripts/verify\.sh", r"rollback"],
        "summary": "Post-application verification has an explicit rollback response.",
    },
    {
        "id": "post-application-impact",
        "weight": 1,
        "patterns": [r"re-evaluat|remeasur|subsequent\s+evidence", r"impact"],
        "summary": "Later evidence remeasures post-application impact.",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-path", type=Path, required=True)
    args = parser.parse_args()
    print_result(args.skill_path, CASES)


if __name__ == "__main__":
    main()
