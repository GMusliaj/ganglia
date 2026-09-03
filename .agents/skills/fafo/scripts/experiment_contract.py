#!/usr/bin/env python3
"""Validate content-bound FAFO plans and terminal results without executing them."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
BRAIN_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(BRAIN_ROOT / "bin"))

from skill_evolution import (  # noqa: E402
    SkillEvolutionError,
    canonical_json,
    load_json,
    validate,
)


PLAN_SCHEMA = SKILL_ROOT / "schemas" / "experiment-plan.schema.json"
RESULT_SCHEMA = SKILL_ROOT / "schemas" / "experiment-result.schema.json"
PLAN_DOMAIN = b"ganglia-fafo-plan-v1\0"
BROAD_TARGETS = {"", ".", "..", "/", "~", "$HOME", "${HOME}"}


class ContractError(ValueError):
    """A FAFO contract failed structural or semantic validation."""


def plan_digest(plan: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(PLAN_DOMAIN)
    digest.update(canonical_json(plan))
    return f"sha256:{digest.hexdigest()}"


def fail(message: str) -> None:
    raise ContractError(message)


def has_parent_escape(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return ".." in PurePosixPath(normalized).parts


def is_temporary_target(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if normalized.startswith(".tmp/"):
        return True
    candidate = Path(normalized)
    if not candidate.is_absolute():
        return False
    # The POSIX temporary root remains valid even when tempfile selects a
    # platform-specific per-user directory.
    roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path(os.sep, "tmp").resolve(),
    }
    for root in roots:
        try:
            candidate.resolve().relative_to(root)
            return True
        except ValueError:
            continue
    return False


def validate_plan(plan: dict[str, Any]) -> str:
    try:
        validate(plan, PLAN_SCHEMA)
    except (SkillEvolutionError, OSError) as exc:
        fail(str(exc))

    preflight = plan["preflight"]
    effect_class = preflight["effect_class"]
    working_directory = preflight["working_directory"].strip()
    if working_directory in BROAD_TARGETS:
        fail("working_directory must identify the repository or isolated workspace")
    if preflight["overlap_targets"]:
        fail("preflight overlaps existing changes; stop instead of experimenting")

    for target in preflight["targets"]:
        stripped = target.strip()
        if has_parent_escape(stripped):
            fail(f"target contains parent traversal: {target}")
        if stripped in BROAD_TARGETS:
            fail(f"experiment target is too broad: {target}")
        if effect_class == "temporary-local" and not is_temporary_target(stripped):
            fail(f"temporary-local target is outside an explicit temp path: {target}")
        if effect_class == "repository-local" and Path(stripped).is_absolute():
            fail(f"repository-local target must be repository-relative: {target}")

    preview = preflight["preview"]
    if effect_class == "repository-local" and preview["status"] != "passed":
        fail("repository-local experiments require a passed preview")
    return plan_digest(plan)


def validate_result(plan: dict[str, Any], result: dict[str, Any]) -> str:
    digest = validate_plan(plan)
    try:
        validate(result, RESULT_SCHEMA)
    except (SkillEvolutionError, OSError) as exc:
        fail(str(exc))

    if result["experiment_id"] != plan["experiment_id"]:
        fail("result experiment_id does not match plan")
    if result["plan_digest"] != digest:
        fail("result plan_digest does not match the validated plan")
    if len(result["actions"]) > plan["budget"]["max_actions"]:
        fail("result exceeds the plan action budget")

    terminal = result["terminal_state"]
    actions = result["actions"]
    observations = result["observations"]
    postcondition = result["postcondition"]["status"]
    reconciliation = result["reconciliation"]["status"]
    rollback = result["rollback"]["status"]
    indeterminate = any(action["status"] == "indeterminate" for action in actions)

    if terminal in {"verified", "falsified", "inconclusive"} and not actions:
        fail(f"{terminal} results require at least one recorded action")
    if terminal in {"verified", "falsified", "inconclusive"} and not observations:
        fail(f"{terminal} results require direct observations")
    if terminal == "verified" and postcondition != "passed":
        fail("verified results require a passed independent postcondition")
    if terminal == "falsified" and postcondition != "failed":
        fail("falsified results require a failed independent postcondition")
    if terminal in {"authorization-blocked", "superseded"} and actions:
        fail(f"{terminal} results cannot contain executed actions")
    if terminal in {"authorization-blocked", "superseded"} and postcondition != "not-run":
        fail(f"{terminal} results require a not-run postcondition")
    if terminal == "safety-blocked" and not actions and postcondition != "not-run":
        fail("a pre-execution safety block requires a not-run postcondition")
    if indeterminate and reconciliation == "not-needed":
        fail("indeterminate actions require completed or required reconciliation")
    if reconciliation == "required" and terminal in {"verified", "falsified"}:
        fail(f"{terminal} is impossible while reconciliation remains required")
    if rollback == "failed" and terminal != "safety-blocked":
        fail("a failed rollback must terminate as safety-blocked")
    if rollback == "failed" and reconciliation == "not-needed":
        fail("a failed rollback requires state reconciliation")
    return digest


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    operations = root.add_subparsers(dest="operation", required=True)
    plan = operations.add_parser("validate-plan", help="validate a FAFO plan")
    plan.add_argument("--plan", type=Path, required=True)
    result = operations.add_parser(
        "validate-result", help="validate a terminal result against its plan"
    )
    result.add_argument("--plan", type=Path, required=True)
    result.add_argument("--result", type=Path, required=True)
    return root


def main() -> int:
    args = build_parser().parse_args()
    try:
        plan = load_json(args.plan)
        if args.operation == "validate-plan":
            digest = validate_plan(plan)
            print(json.dumps({"kind": "fafo-plan-validation", "plan_digest": digest}))
            return 0
        result = load_json(args.result)
        digest = validate_result(plan, result)
        print(
            json.dumps(
                {
                    "kind": "fafo-result-validation",
                    "plan_digest": digest,
                    "terminal_state": result["terminal_state"],
                }
            )
        )
        return 0
    except (ContractError, SkillEvolutionError, OSError, json.JSONDecodeError) as exc:
        print(f"fafo contract error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
