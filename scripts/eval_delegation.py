#!/usr/bin/env python3
"""Run delegation regression evals offline; optionally make two live worker calls.

Offline results validate implementation contracts, not real model quality or
money saved. --live uses public synthetic fixtures and requires explicit local
model mapping. It prints quality checks and measured usage, never a savings claim.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))


class Report(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.cases = []

    def stopTest(self, test):
        super().stopTest(test)
        failing = {str(item) for item, _ in self.failures + self.errors}
        name = str(test)
        passed = name not in failing and not any(name.split(" (")[0] in item for item in failing)
        self.cases.append({"id": test.id(), "passed": passed})


def run_live(config: Path) -> dict:
    from delegation import INSTRUCTIONS, load_route, prepare, validate_result
    from delegation_codex import invoke

    # Reject either invalid mapping before incurring any worker usage.
    reader = load_route(config, "bulk-reader")
    writer = load_route(config, "code-writer")
    with tempfile.TemporaryDirectory(prefix="ganglia-delegation-eval-") as folder:
        root = Path(folder)
        # Stable, reproducible corpus. Sent to the worker, never to a grading LLM.
        source = "# Public synthetic evaluation fixture.\n" + "# unrelated implementation detail\n" * 600
        source += "MAX_ATTEMPTS = 7\nBACKOFF_SECONDS = 3\n\ndef next_delay(attempt):\n    return attempt * BACKOFF_SECONDS\n"
        (root / "service.py").write_text(source)
        (root / "test_reference.py").write_text("import unittest\n\nclass ArithmeticTests(unittest.TestCase):\n    def test_addition(self):\n        self.assertEqual(1 + 1, 2)\n")
        request = prepare(root, "bulk-reader", "List MAX_ATTEMPTS, BACKOFF_SECONDS, and next_delay with their exact values/behavior and line numbers. Answer in at most 120 words.", ["service.py"], reader)
        draft_request = prepare(root, "code-writer", "Write unittest tests importing next_delay from service. Test attempts 0, 1 and 4, with expected results 0, 3 and 12. Follow the reference style.", ["test_reference.py", "service.py"], writer)
        read_result = invoke(request["payload"], reader, INSTRUCTIONS["bulk-reader"])
        answer = validate_result(read_result, reader, "bulk-reader")
        write_result = invoke(draft_request["payload"], writer, INSTRUCTIONS["code-writer"])
        draft = validate_result(write_result, writer, "code-writer")
        try:
            tree = ast.parse(draft)
            syntactic = True
            has_tests = any(isinstance(node, ast.FunctionDef) and node.name.startswith("test_") for node in ast.walk(tree))
        except SyntaxError:
            syntactic = has_tests = False
        checks = {"reader_names": all(name in answer for name in ("MAX_ATTEMPTS", "BACKOFF_SECONDS", "next_delay")),
                  "reader_values_present": "7" in answer and "3" in answer,
                  "reader_concise": len(answer.split()) <= 160,
                  "writer_python_syntax": syntactic, "writer_test_functions": has_tests}
        return {"mode": "live", "calls": 2, "checks": checks,
                "reader": {"model_id": read_result["model_id"], "usage": read_result["usage"],
                           "source_bytes": request["source_bytes"], "answer_bytes": len(answer.encode()),
                           "host_context_reduction_fraction": 1 - len(answer.encode()) / request["source_bytes"], "answer": answer},
                "writer": {"model_id": write_result["model_id"], "usage": write_result["usage"], "draft": draft},
                "money_saved": None,
                "limitations": "Smoke checks only. Human review must verify citations, correctness, test quality and host skill selection. Generated code was parsed but not executed. Cost comparison needs a matched host baseline, cache/review overhead and configured rates; subscription usage is not API dollars."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="make two model calls with synthetic fixtures")
    parser.add_argument("--config", type=Path, default=ROOT / "local/delegation.json")
    args = parser.parse_args()
    if args.live:
        from delegation import DelegationError
        try:
            result = run_live(args.config)
        except (DelegationError, OSError) as exc:
            print(f"live delegation eval failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0 if all(result["checks"].values()) else 1
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_delegation*.py")
    report = Report()
    suite.run(report)
    print(json.dumps({"mode": "offline", "model_calls": 0, "tests_run": report.testsRun,
                      "passed": report.wasSuccessful(), "cases": report.cases,
                      "live_quality": "unverified", "money_saved": None}, indent=2))
    for _, detail in report.failures + report.errors:
        print(detail, file=sys.stderr)
    return 0 if report.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
