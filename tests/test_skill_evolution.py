from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "bin"))

from skill_evolution import EvolutionWorkspace, SkillEvolutionError  # noqa: E402


BASE_SKILL = """---
name: demo
description: Exercise a deterministic demo workflow.
---

# Demo

Keep the stable baseline behavior.
"""

IMPROVED_SKILL = """---
name: demo
description: Exercise a deterministic demo workflow with recurrent evidence.
---

# Demo

Keep the stable baseline behavior.

IMPROVED: add the recurrent evidence gate.
"""

REGRESSED_SKILL = """---
name: demo
description: Exercise a deterministic demo workflow with a regression.
---

# Demo

REGRESSION: replace the stable baseline behavior.
"""

EVALUATOR = """#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--skill-path", type=Path, required=True)
args = parser.parse_args()
content = (args.skill_path / "SKILL.md").read_text(encoding="utf-8")

if "IMPROVED:" in content:
    score = 1.0
    stable = True
    recurrent = True
elif "REGRESSION:" in content:
    score = 0.75
    stable = False
    recurrent = True
else:
    score = 0.5
    stable = True
    recurrent = False

print(json.dumps({
    "schema_version": 1,
    "kind": "skill-eval-result",
    "score": score,
    "cases": [
        {
            "id": "stable-behavior",
            "passed": stable,
            "score": 1.0 if stable else 0.0,
            "summary": "Stable baseline behavior is preserved."
        },
        {
            "id": "recurrent-evidence",
            "passed": recurrent,
            "score": 1.0 if recurrent else 0.0,
            "summary": "The recurrent evidence behavior is present."
        }
    ]
}))
"""


class SkillEvolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".tmp").mkdir()
        (self.root / ".agents" / "skills" / "demo").mkdir(parents=True)
        (self.root / ".agents" / "skills" / "demo" / "SKILL.md").write_text(
            BASE_SKILL, encoding="utf-8"
        )
        evaluator = self.root / "evals" / "skills" / "evaluate_demo.py"
        evaluator.parent.mkdir(parents=True)
        evaluator.write_text(EVALUATOR, encoding="utf-8")
        evaluator.chmod(0o755)
        self.workspace = EvolutionWorkspace(
            self.root, clock=lambda: "2026-09-01T12:00:00Z"
        )
        self.private_path = "/" + "Users" + "/nonexampleuser/private"
        self.non_example_email = "EXAMPLE_PERSON" + "@" + "invalid.test"
        self.private_term = "EXAMPLE_PRIVATE_TERM"
        denylist = self.root / "local" / "shared-denylist.txt"
        denylist.parent.mkdir(parents=True)
        denylist.write_text(self.private_term + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_json(self, relative: str, value: dict) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return Path(relative)

    def evidence(self, task_id: str, summary: str = "Bounded check passed.") -> dict:
        return {
            "schema_version": 1,
            "kind": "skill-evidence",
            "skill_name": "demo",
            "task_id": task_id,
            "outcome": "passed",
            "summary": summary,
            "signals": [
                {
                    "key": "recurrent-gate",
                    "kind": "success",
                    "summary": "A repeated gate prevented an unsupported conclusion.",
                }
            ],
            "checks": [
                {
                    "id": "bounded-check",
                    "command": "run the deterministic example check",
                    "status": "passed",
                    "observation": "The expected result was observed.",
                }
            ],
        }

    def establish_pattern(self) -> None:
        for task_id in ("task-one", "task-two"):
            path = self.write_json(
                f".tmp/{task_id}.json", self.evidence(task_id)
            )
            self.workspace.capture(path)
        result = self.workspace.consolidate("demo")
        self.assertEqual(
            ["recurrent-gate"],
            [pattern["pattern_key"] for pattern in result["recurrent_patterns"]],
        )

    def prepare(self, candidate: str) -> dict:
        candidate_path = self.root / ".tmp" / "candidate" / "SKILL.md"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text(candidate, encoding="utf-8")
        proposal = {
            "schema_version": 1,
            "kind": "skill-proposal-input",
            "skill_name": "demo",
            "target_skill": ".agents/skills/demo/SKILL.md",
            "candidate_skill": ".tmp/candidate/SKILL.md",
            "pattern_keys": ["recurrent-gate"],
            "rationale": "The same gate recurred across independent tasks.",
            "evaluator": {
                "path": "evals/skills/evaluate_demo.py",
                "arguments": [],
                "timeout_seconds": 10,
            },
        }
        proposal_path = self.write_json(".tmp/proposal.json", proposal)
        return self.workspace.prepare(proposal_path)

    def test_capture_sanitizes_and_detects_tampering(self) -> None:
        input_path = self.write_json(
            ".tmp/evidence.json",
            self.evidence(
                "task-one",
                f"Observed {self.private_path}, {self.non_example_email}, and "
                f"{self.private_term}.",
            ),
        )
        first = self.workspace.capture(input_path)
        second = self.workspace.capture(input_path)
        self.assertEqual(first, second)
        stored_path = self.root / first["path"]
        stored = json.loads(stored_path.read_text(encoding="utf-8"))
        self.assertIn("EXAMPLE_REDACTED_HOME", stored["summary"])
        self.assertIn("EXAMPLE_REDACTED_EMAIL", stored["summary"])
        self.assertIn("EXAMPLE_REDACTED_IDENTITY", stored["summary"])
        stored["summary"] = "tampered"
        stored_path.write_text(json.dumps(stored), encoding="utf-8")
        with self.assertRaisesRegex(SkillEvolutionError, "evidence digest mismatch"):
            self.workspace.consolidate("demo")

    def test_consolidation_requires_distinct_tasks(self) -> None:
        first = self.write_json(".tmp/first.json", self.evidence("task-one"))
        self.workspace.capture(first)
        result = self.workspace.consolidate("demo")
        self.assertEqual([], result["recurrent_patterns"])

        duplicate = self.evidence("task-one")
        duplicate["summary"] = "A second record from the same task."
        second = self.write_json(".tmp/second.json", duplicate)
        self.workspace.capture(second)
        result = self.workspace.consolidate("demo")
        self.assertEqual([], result["recurrent_patterns"])

        third = self.write_json(".tmp/third.json", self.evidence("task-two"))
        self.workspace.capture(third)
        result = self.workspace.consolidate("demo")
        self.assertEqual(1, len(result["recurrent_patterns"]))

    def test_accept_apply_and_rollback_are_content_bound(self) -> None:
        self.establish_pattern()
        proposal = self.prepare(IMPROVED_SKILL)
        target = self.root / ".agents" / "skills" / "demo" / "SKILL.md"
        self.assertEqual(BASE_SKILL, target.read_text(encoding="utf-8"))

        evaluation = self.workspace.evaluate(proposal["proposal_id"])
        self.assertEqual("accepted", evaluation["gate_status"])
        self.assertEqual(0.5, evaluation["score_delta"])
        self.assertEqual([], evaluation["regressions"])
        self.assertEqual(BASE_SKILL, target.read_text(encoding="utf-8"))

        self.workspace.approve(proposal["proposal_id"], "accepted")
        with self.assertRaisesRegex(SkillEvolutionError, "confirmed digest"):
            self.workspace.apply(
                proposal["proposal_id"], "sha256:" + "0" * 64
            )
        application = self.workspace.apply(
            proposal["proposal_id"], proposal["candidate_digest"]
        )
        self.assertFalse(application["committed"])
        self.assertEqual(IMPROVED_SKILL, target.read_text(encoding="utf-8"))

        attributed = self.evidence("post-application-task")
        attributed["proposal_id"] = proposal["proposal_id"]
        attributed_path = self.write_json(".tmp/attributed.json", attributed)
        self.workspace.capture(attributed_path)
        impact = self.workspace.impact(proposal["proposal_id"])
        self.assertEqual(1, impact["task_count"])
        self.assertEqual(1.0, impact["pass_rate"])
        self.assertEqual(1, impact["signals"][0]["success_tasks"])

        rollback = self.workspace.rollback(proposal["proposal_id"])
        self.assertEqual(proposal["base_digest"], rollback["restored_digest"])
        self.assertEqual(BASE_SKILL, target.read_text(encoding="utf-8"))

    def test_regression_rejects_even_with_higher_score(self) -> None:
        self.establish_pattern()
        proposal = self.prepare(REGRESSED_SKILL)
        evaluation = self.workspace.evaluate(proposal["proposal_id"])
        self.assertGreater(evaluation["candidate"]["score"], evaluation["baseline"]["score"])
        self.assertEqual("rejected", evaluation["gate_status"])
        self.assertEqual(["stable-behavior"], evaluation["regressions"])
        with self.assertRaisesRegex(SkillEvolutionError, "cannot override"):
            self.workspace.approve(proposal["proposal_id"], "accepted")
        target = self.root / ".agents" / "skills" / "demo" / "SKILL.md"
        self.assertEqual(BASE_SKILL, target.read_text(encoding="utf-8"))

    def test_changed_evaluator_invalidates_prepared_proposal(self) -> None:
        self.establish_pattern()
        proposal = self.prepare(IMPROVED_SKILL)
        evaluator = self.root / "evals" / "skills" / "evaluate_demo.py"
        evaluator.write_text(EVALUATOR + "\n# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(SkillEvolutionError, "evaluator digest mismatch"):
            self.workspace.evaluate(proposal["proposal_id"])

    def test_changed_proposal_metadata_invalidates_approval_scope(self) -> None:
        self.establish_pattern()
        proposal = self.prepare(IMPROVED_SKILL)
        proposal_path = (
            self.root
            / "local"
            / "skill-evolution"
            / "proposals"
            / proposal["proposal_id"]
            / "proposal.json"
        )
        stored = json.loads(proposal_path.read_text(encoding="utf-8"))
        stored["evaluator"]["arguments"] = ["--changed"]
        proposal_path.write_text(json.dumps(stored), encoding="utf-8")
        with self.assertRaisesRegex(SkillEvolutionError, "proposal digest mismatch"):
            self.workspace.evaluate(proposal["proposal_id"])

    def test_candidate_uses_the_official_frontmatter_contract(self) -> None:
        self.establish_pattern()
        unsupported = IMPROVED_SKILL.replace(
            "description: Exercise", "unexpected: value\ndescription: Exercise"
        )
        with self.assertRaisesRegex(SkillEvolutionError, "unsupported fields"):
            self.prepare(unsupported)

    def test_validate_skill_operation_checks_repository_skill(self) -> None:
        skill = self.root / ".agents" / "skills" / "demo"
        (skill / "SKILL.md").write_text(IMPROVED_SKILL, encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "bin" / "skill_evolution.py"),
                "validate-skill",
                str(skill),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "skill validation: 1/1 passed")

    def test_validate_skill_operation_rejects_invalid_directory_name(self) -> None:
        skill = self.root / ".agents" / "skills" / "Invalid_Name"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            IMPROVED_SKILL.replace("name: demo", "name: Invalid_Name"),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "bin" / "skill_evolution.py"),
                "validate-skill",
                str(skill),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("lowercase letters, digits, and single hyphens", result.stderr)

    def test_candidate_and_full_publication_guards_fail_closed(self) -> None:
        self.establish_pattern()
        unsafe_candidate = IMPROVED_SKILL + f"\nRead {self.private_path}.\n"
        with self.assertRaisesRegex(SkillEvolutionError, "candidate publication guard"):
            self.prepare(unsafe_candidate)

        proposal = self.prepare(IMPROVED_SKILL)
        self.workspace.evaluate(proposal["proposal_id"])
        self.workspace.approve(proposal["proposal_id"], "accepted")
        (self.root / "unsafe.txt").write_text(
            f"Read {self.private_path}.\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(SkillEvolutionError, "active skill rolled back"):
            self.workspace.apply(proposal["proposal_id"], proposal["candidate_digest"])
        target = self.root / ".agents" / "skills" / "demo" / "SKILL.md"
        self.assertEqual(BASE_SKILL, target.read_text(encoding="utf-8"))

    def test_wikiskill_provenance_and_deviations_are_documented(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        skill = (
            ROOT / ".agents" / "skills" / "skill-evolution" / "SKILL.md"
        ).read_text(encoding="utf-8")
        workflow = (
            ROOT
            / ".agents"
            / "skills"
            / "skill-evolution"
            / "references"
            / "workflow.md"
        ).read_text(encoding="utf-8")
        for document in (readme, skill, workflow):
            self.assertIn("WikiSkill", document)
            self.assertIn("2608.27454v1", document)
        self.assertIn("Ganglia deliberately changes", workflow)
        self.assertIn("does **not** claim to reproduce", workflow)


if __name__ == "__main__":
    unittest.main()
