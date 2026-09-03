#!/usr/bin/env python3
"""Evaluate the stable safety and evidence contract of one FAFO skill snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from contract_eval import print_result


CASES = [
    {
        "id": "skill-identity",
        "weight": 1,
        "patterns": [r"(?m)^name:\s*fafo\s*$", r"(?m)^description:\s*.+$"],
        "summary": "The snapshot declares the FAFO skill and a usable description.",
    },
    {
        "id": "explicit-hypothesis",
        "weight": 1,
        "patterns": [r"uncertain|uncertainty", r"baseline", r"success.*failure|failure.*success"],
        "summary": "The workflow makes the uncertainty and observable outcomes explicit.",
    },
    {
        "id": "bounded-stop",
        "weight": 1,
        "patterns": [r"bounded", r"stop condition"],
        "summary": "Experiments have a bound and an explicit stop condition.",
    },
    {
        "id": "reversible-rollback",
        "weight": 1,
        "patterns": [r"reversib", r"rollback|restore"],
        "summary": "The workflow requires reversible work and restoration planning.",
    },
    {
        "id": "authorization-boundary",
        "weight": 1,
        "patterns": [r"authorization", r"external|irreversible|destructive"],
        "summary": "FAFO cannot widen external or irreversible authorization.",
    },
    {
        "id": "contract-first",
        "weight": 1,
        "patterns": [
            r"contract",
            r"before\s+(executing|probing)|before\s+experiment|did\s+not\s+already",
        ],
        "summary": "Documented contracts and repository state precede experiments.",
    },
    {
        "id": "observation-inference",
        "weight": 1,
        "patterns": [r"observation", r"inference"],
        "summary": "Observed results remain separate from inference.",
    },
    {
        "id": "sanitized-evidence",
        "weight": 1,
        "patterns": [
            r"sanitized",
            r"raw\s+(model\s+)?reasoning|raw\s+transcript|unrestricted\s+execution\s+trace",
        ],
        "summary": "Reusable evidence is sanitized and excludes raw reasoning or traces.",
    },
    {
        "id": "recurrence-threshold",
        "weight": 1,
        "patterns": [r"two\s+distinct\s+task", r"one\s+(isolated\s+)?result|one\s+task"],
        "summary": "One task is insufficient and recurrence requires distinct tasks.",
    },
    {
        "id": "resource-budget",
        "weight": 1,
        "patterns": [
            r"no\s+more\s+than\s+five\s+actions|max_actions",
            r"elapsed-time\s+limit|timeout_seconds",
            r"resource\s+limit",
        ],
        "summary": "The experiment records bounded actions, time, and resources.",
    },
    {
        "id": "routing-exclusions",
        "weight": 1,
        "patterns": [
            r"prototype",
            r"tdd",
            r"adversarial-review",
            r"grilling",
            r"recall",
        ],
        "summary": "FAFO has explicit routing boundaries from overlapping skills.",
    },
    {
        "id": "effect-preflight",
        "weight": 1,
        "patterns": [
            r"effect\s+class",
            r"dirty-state",
            r"overlap",
            r"preview",
            r"authorization\s+basis",
        ],
        "summary": "Mutating probes require a fail-closed ownership and safety preflight.",
    },
    {
        "id": "interruption-reconciliation",
        "weight": 1,
        "patterns": [
            r"timeout",
            r"interruption",
            r"indeterminate",
            r"before\s+any\s+retry",
        ],
        "summary": "Interrupted or indeterminate actions reconcile actual state before retry.",
    },
    {
        "id": "terminal-states",
        "weight": 1,
        "patterns": [
            r"verified",
            r"falsified",
            r"inconclusive",
            r"authorization-blocked",
            r"safety-blocked",
            r"superseded",
        ],
        "summary": "Every invocation terminates in one explicit evidence state.",
    },
    {
        "id": "validated-receipt",
        "weight": 1,
        "patterns": [
            r"experiment_contract\.py\s+validate-plan",
            r"experiment_contract\.py\s+validate-result",
            r"plan\s+digest",
            r"terminal\s+receipt",
        ],
        "summary": "Plans and terminal receipts use the deterministic contract validator.",
    },
    {
        "id": "durable-routing",
        "weight": 1,
        "patterns": [
            r"stable\s+repeatable\s+operation",
            r"remember",
            r"skill-evolution",
            r"do\s+not\s+create\s+a\s+FAFO-specific\s+executor",
        ],
        "summary": "Stable operations and recurrent skill evidence use existing governed paths.",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-path", type=Path, required=True)
    args = parser.parse_args()
    print_result(args.skill_path, CASES)


if __name__ == "__main__":
    main()
