from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "fafo" / "scripts" / "experiment_contract.py"
SPEC = importlib.util.spec_from_file_location("fafo_experiment_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def valid_plan() -> dict:
    return {
        "schema_version": 1,
        "kind": "fafo-plan",
        "experiment_id": "parser-boundary",
        "uncertainty": "The parser may reject the documented boundary value.",
        "contracts": ["README.md parser contract"],
        "success_condition": "The focused check accepts the boundary value.",
        "failure_condition": "The focused check rejects the boundary value.",
        "preflight": {
            "effect_class": "temporary-local",
            "working_directory": "/workspace/example",
            "targets": [".tmp/fafo/parser-boundary-output.json"],
            "baseline": "The focused check passes for the preceding value.",
            "ownership": "Only the ignored experiment output is created.",
            "dirty_state": "unrelated-changes-preserved",
            "overlap_targets": [],
            "preview": {
                "status": "not-applicable",
                "evidence": "The action writes only to the ignored temporary target.",
            },
            "authorization_basis": "The requested local diagnostic permits temporary output.",
            "rollback": "Delete the ignored temporary output after observing it.",
            "retry_semantics": "reconcile-before-retry",
            "reconciliation_check": "Inspect whether the output exists and parse it before retrying.",
            "independent_postcondition": "Run the focused parser assertion against the result.",
        },
        "budget": {
            "max_actions": 2,
            "timeout_seconds": 30,
            "resource_limit": "One temporary JSON file under 10 KB.",
        },
        "stop_condition": "Stop after either boundary outcome or the first indeterminate action.",
    }


def valid_result(plan: dict) -> dict:
    return {
        "schema_version": 1,
        "kind": "fafo-result",
        "experiment_id": plan["experiment_id"],
        "plan_digest": CONTRACT.plan_digest(plan),
        "terminal_state": "verified",
        "actions": [
            {
                "id": "focused-check",
                "summary": "Ran the focused boundary check.",
                "status": "passed",
                "evidence": "The process exited successfully and emitted the expected marker.",
            }
        ],
        "observations": ["The boundary value was accepted."],
        "postcondition": {
            "status": "passed",
            "evidence": "The independent assertion matched the expected value.",
        },
        "reconciliation": {
            "status": "not-needed",
            "evidence": "The action completed and the output parsed successfully.",
        },
        "rollback": {
            "status": "restored",
            "evidence": "The ignored temporary output was removed.",
        },
        "conclusion": "The documented boundary value is accepted.",
        "remaining_uncertainty": "No uncertainty remains for this boundary case.",
    }


class FafoContractTests(unittest.TestCase):
    def test_valid_plan_and_result_are_content_bound(self) -> None:
        plan = valid_plan()
        digest = CONTRACT.validate_plan(plan)
        self.assertEqual(CONTRACT.plan_digest(plan), digest)
        self.assertEqual(digest, CONTRACT.validate_result(plan, valid_result(plan)))

    def test_plan_rejects_unknown_fields_and_unsafe_effects(self) -> None:
        plan = valid_plan()
        plan["unexpected"] = "value"
        with self.assertRaisesRegex(CONTRACT.ContractError, "unknown field"):
            CONTRACT.validate_plan(plan)

        plan = valid_plan()
        plan["preflight"]["effect_class"] = "external"
        with self.assertRaisesRegex(CONTRACT.ContractError, "invalid value"):
            CONTRACT.validate_plan(plan)

    def test_plan_rejects_overlap_broad_mutation_and_missing_preview(self) -> None:
        plan = valid_plan()
        plan["preflight"]["overlap_targets"] = ["src/parser.py"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "overlaps existing changes"):
            CONTRACT.validate_plan(plan)

        plan = valid_plan()
        plan["preflight"]["effect_class"] = "repository-local"
        plan["preflight"]["targets"] = ["."]
        with self.assertRaisesRegex(CONTRACT.ContractError, "too broad"):
            CONTRACT.validate_plan(plan)

        plan = valid_plan()
        plan["preflight"]["targets"] = [".tmp/fafo/../outside.json"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "parent traversal"):
            CONTRACT.validate_plan(plan)

        plan = valid_plan()
        plan["preflight"]["effect_class"] = "repository-local"
        plan["preflight"]["targets"] = ["src/parser.py"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "passed preview"):
            CONTRACT.validate_plan(plan)

    def test_result_rejects_digest_budget_and_false_verification(self) -> None:
        plan = valid_plan()
        result = valid_result(plan)
        result["plan_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(CONTRACT.ContractError, "plan_digest"):
            CONTRACT.validate_result(plan, result)

        result = valid_result(plan)
        result["actions"] = [
            {
                **copy.deepcopy(result["actions"][0]),
                "id": f"focused-check-{index}",
            }
            for index in range(3)
        ]
        with self.assertRaisesRegex(CONTRACT.ContractError, "action budget"):
            CONTRACT.validate_result(plan, result)

        result = valid_result(plan)
        result["postcondition"]["status"] = "failed"
        with self.assertRaisesRegex(CONTRACT.ContractError, "passed independent"):
            CONTRACT.validate_result(plan, result)

    def test_indeterminate_and_failed_rollback_require_reconciliation(self) -> None:
        plan = valid_plan()
        result = valid_result(plan)
        result["terminal_state"] = "inconclusive"
        result["actions"][0]["status"] = "indeterminate"
        result["postcondition"]["status"] = "not-run"
        with self.assertRaisesRegex(CONTRACT.ContractError, "reconciliation"):
            CONTRACT.validate_result(plan, result)

        result["terminal_state"] = "safety-blocked"
        result["rollback"]["status"] = "failed"
        with self.assertRaisesRegex(CONTRACT.ContractError, "reconciliation"):
            CONTRACT.validate_result(plan, result)

        result["reconciliation"] = {
            "status": "required",
            "evidence": "The target state must be inspected before any retry.",
        }
        CONTRACT.validate_result(plan, result)

    def test_authorization_blocked_receipt_contains_no_actions(self) -> None:
        plan = valid_plan()
        result = valid_result(plan)
        result.update(
            {
                "terminal_state": "authorization-blocked",
                "actions": [],
                "observations": [],
                "postcondition": {
                    "status": "not-run",
                    "evidence": "No action was authorized.",
                },
                "rollback": {
                    "status": "not-needed",
                    "evidence": "No action changed state.",
                },
                "conclusion": "The experiment did not run.",
                "remaining_uncertainty": "The original uncertainty remains.",
            }
        )
        CONTRACT.validate_result(plan, result)

        result["actions"] = valid_result(plan)["actions"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "cannot contain executed actions"):
            CONTRACT.validate_result(plan, result)

    def test_cli_returns_closed_validation_result(self) -> None:
        plan = valid_plan()
        result = valid_result(plan)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            result_path = root / "result.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            result_path.write_text(json.dumps(result), encoding="utf-8")
            completed = subprocess.run(
                (
                    sys.executable,
                    str(SCRIPT),
                    "validate-result",
                    "--plan",
                    str(plan_path),
                    "--result",
                    str(result_path),
                ),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual("fafo-result-validation", output["kind"])
        self.assertEqual("verified", output["terminal_state"])


if __name__ == "__main__":
    unittest.main()
