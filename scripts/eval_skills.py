#!/usr/bin/env python3
"""Run and validate the checked-in skill contract evaluators."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from skill_evolution import EVAL_RESULT_SCHEMA, validate  # noqa: E402


SUITES = {
    "fafo": {
        "adapter": ROOT / "evals" / "skills" / "evaluate_fafo.py",
        "required": {
            "skill-identity",
            "explicit-hypothesis",
            "bounded-stop",
            "reversible-rollback",
            "authorization-boundary",
            "contract-first",
            "observation-inference",
            "sanitized-evidence",
            "recurrence-threshold",
            "resource-budget",
            "routing-exclusions",
            "effect-preflight",
            "interruption-reconciliation",
            "terminal-states",
            "validated-receipt",
            "durable-routing",
        },
    },
    "skill-evolution": {
        "adapter": ROOT / "evals" / "skills" / "evaluate_skill_evolution.py",
        "required": {
            "skill-identity",
            "wikiskill-provenance",
            "atomic-target",
            "private-workspace",
            "privacy-exclusions",
            "distinct-task-recurrence",
            "deterministic-evaluator",
            "strict-no-regression-gate",
            "human-content-gate",
            "no-automatic-publication",
            "verified-rollback",
        },
    },
}


def main() -> int:
    aggregate: dict[str, object] = {
        "schema_version": 1,
        "kind": "checked-in-skill-evaluation",
        "skills": {},
    }
    failures: list[str] = []
    for skill_name, suite in SUITES.items():
        completed = subprocess.run(
            (
                str(suite["adapter"]),
                "--skill-path",
                str(ROOT / ".agents" / "skills" / skill_name),
            ),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            failures.append(
                f"{skill_name}: evaluator exited {completed.returncode}: "
                f"{completed.stderr.strip() or 'no diagnostic'}"
            )
            continue
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            failures.append(f"{skill_name}: invalid evaluator JSON: {exc.msg}")
            continue
        if not isinstance(result, dict):
            failures.append(f"{skill_name}: evaluator result is not an object")
            continue
        try:
            validate(result, EVAL_RESULT_SCHEMA)
        except ValueError as exc:
            failures.append(f"{skill_name}: {exc}")
            continue
        cases = {case["id"]: case for case in result["cases"]}
        missing = sorted(suite["required"] - cases.keys())
        failed = sorted(
            case_id
            for case_id in suite["required"]
            if case_id in cases and not cases[case_id]["passed"]
        )
        if missing:
            failures.append(f"{skill_name}: missing required cases: {', '.join(missing)}")
        if failed:
            failures.append(f"{skill_name}: failed required cases: {', '.join(failed)}")
        aggregate["skills"][skill_name] = result
    if failures:
        for failure in failures:
            print(f"skill evaluation error: {failure}", file=sys.stderr)
        return 1
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
