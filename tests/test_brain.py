from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "scripts"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reindex_module = load_module("brain_reindex", ROOT / "bin" / "reindex.py")
guard_module = load_module("brain_guard", ROOT / "scripts" / "guard_shared.py")
audit_module = load_module("brain_public_audit", ROOT / "scripts" / "audit_public.py")
lint_module = load_module("brain_lint", ROOT / "bin" / "lint_brain.py")
artifact_module = load_module(
    "brain_artifact_bundle", ROOT / "bin" / "artifact_bundle.py"
)
commit_module = load_module(
    "brain_commit_shared", ROOT / "scripts" / "commit_shared.py"
)
review_module = load_module(
    "brain_reduce_artifact_review", ROOT / "scripts" / "reduce_artifact_review.py"
)
approval_module = load_module(
    "brain_record_artifact_approval",
    ROOT / "scripts" / "record_artifact_approval.py",
)
artifact_eval_module = load_module(
    "brain_eval_artifacts", ROOT / "scripts" / "eval_artifacts.py"
)
canvas_module = load_module("brain_canvas", ROOT / "bin" / "canvas.py")
session_module = load_module(
    "brain_session_catalog", ROOT / "bin" / "sync_codex_sessions.py"
)


ENTRY = """---
type: pattern
title: Retrieval floor
description: Plain text search remains available.
tags: [retrieval]
date: 2026-08-27
---

# Retrieval floor

## Active

Use text search.

## Source

Test fixture.
"""

ARTIFACT_SCRIPT = """#!/usr/bin/env python3
import argparse


def main():
    parser = argparse.ArgumentParser(description="Normalize one text value.")
    parser.add_argument("--text", default="example")
    args = parser.parse_args()
    print(args.text.strip())


if __name__ == "__main__":
    main()
"""

SHELL_ARTIFACT_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--help" ]]; then
  printf 'usage: normalize-text --text TEXT\\n'
  exit 0
fi
if [[ "${1:-}" != "--text" || $# -ne 2 ]]; then
  exit 2
fi
printf '%s\\n' "$2"
"""


def artifact_candidate(manifest: str = "snippets/normalize-text.md"):
    payload = str(Path(manifest).with_suffix(".py"))
    return {
        "schema_version": 1,
        "kind": "artifact-candidate",
        "artifact_id": "normalize-text",
        "title": "Normalize text",
        "description": "Normalize one supplied text value.",
        "type": "snippet",
        "tags": [],
        "date": "2026-08-28",
        "payload_name": Path(payload).name,
        "language": "python",
        "runtime": "python>=3.11",
        "invocation": f"python3 {payload} --text EXAMPLE_TEXT",
        "working_directory": "brain-root",
        "dependencies": ["Python standard library"],
        "arguments": ["--text TEXT: text to normalize"],
        "environment": [],
        "inputs": ["Text supplied with --text"],
        "outputs": ["Normalized text on standard output"],
        "exit_behavior": ["0 on success", "2 on invalid arguments"],
        "applicability": ["Text values accepted by the active Python runtime"],
        "safety": "read-only",
        "mutation_default": "read-only",
        "purpose": "Normalize a text value without mutating files or services.",
        "focused_test": {
            "arguments": ["--text", "focused"],
            "expected_stdout": "focused",
        },
        "representative_run": {
            "arguments": ["--text", "EXAMPLE_TEXT"],
            "expected_stdout": "EXAMPLE_TEXT",
        },
    }


def publish_test_artifact(
    root: Path,
    scratch: Path,
    manifest: str,
    candidate_override=None,
    script_source: str = ARTIFACT_SCRIPT,
):
    candidate = candidate_override or artifact_candidate(manifest)
    candidate_path = scratch / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    payload_source = scratch / candidate["payload_name"]
    payload_source.write_text(script_source, encoding="utf-8")
    plan = artifact_module.prepare_bundle(
        root, candidate_path, payload_source, Path(manifest)
    )
    packet = review_packet()
    packet["artifact_id"] = plan.candidate["artifact_id"]
    packet["bundle_digest"] = plan.bundle_digest
    packet["evidence_digest"] = "none"
    packet["candidate"] = {
        "manifest_path": plan.manifest_relative.as_posix(),
        "payload_path": plan.payload_relative.as_posix(),
        "payload_source": script_source,
        "purpose": plan.candidate["purpose"],
        "invocation": plan.candidate["invocation"],
        "language": plan.candidate["language"],
        "runtime": plan.candidate["runtime"],
        "dependencies": plan.candidate["dependencies"],
        "arguments": plan.candidate["arguments"],
        "environment": plan.candidate["environment"],
        "outputs": plan.candidate["outputs"],
        "exit_behavior": plan.candidate["exit_behavior"],
        "applicability": plan.candidate["applicability"],
        "safety": plan.candidate["safety"],
        "mutation_default": plan.candidate["mutation_default"],
        "verification_status": plan.verification["status"],
    }
    contributions = []
    for producer in ("scriptability", "execution-risk", "retrieval-economics"):
        contribution = review_contribution(producer)
        for field in (
            "review_id",
            "base_revision",
            "artifact_id",
            "bundle_digest",
            "evidence_digest",
        ):
            contribution[field] = packet[field]
        contributions.append(contribution)
    review_state = review_module.reduce_review(packet, contributions)
    _, evidence = artifact_module.verify_after_review(plan, review_state)
    approval = approval_module.record_approval(evidence, review_state, "accepted")
    artifact_module.publish_bundle(root, plan, evidence, review_state, approval)
    return root / manifest, root / plan.payload_relative


def review_packet(revision: int = 0):
    digest = f"sha256:{'a' * 64}"
    return {
        "schema_version": 1,
        "kind": "review-packet",
        "id": "normalize-text-review",
        "review_id": "normalize-text-review",
        "base_revision": revision,
        "producer": "remember",
        "artifact_id": "normalize-text",
        "bundle_digest": digest,
        "evidence_digest": "none",
        "required_lenses": [
            "scriptability",
            "execution-risk",
            "retrieval-economics",
        ],
        "max_revisions": 3,
        "candidate": {
            "manifest_path": "snippets/normalize-text.md",
            "payload_path": "snippets/normalize-text.py",
            "payload_source": ARTIFACT_SCRIPT,
            "purpose": "Normalize a text value.",
            "invocation": "python3 snippets/normalize-text.py --text EXAMPLE_TEXT",
            "language": "python",
            "runtime": "python>=3.11",
            "dependencies": ["Python standard library"],
            "arguments": ["--text TEXT: text to normalize"],
            "environment": [],
            "outputs": ["Normalized text on standard output"],
            "exit_behavior": ["0 on success", "2 on invalid arguments"],
            "applicability": ["Text values accepted by the active Python runtime"],
            "safety": "read-only",
            "mutation_default": "read-only",
            "verification_status": "unverified",
        },
    }


def review_contribution(producer: str, revision: int = 0):
    packet = review_packet(revision)
    return {
        "schema_version": 1,
        "kind": "review-contribution",
        "id": f"{producer}-contribution-{revision}",
        "review_id": packet["review_id"],
        "base_revision": revision,
        "producer": producer,
        "artifact_id": packet["artifact_id"],
        "bundle_digest": packet["bundle_digest"],
        "evidence_digest": packet["evidence_digest"],
        "verdict": "accept",
        "summary": "No material blocker found in this review lens.",
        "findings": [],
        "confidence": 0.9,
    }


def agreed_review_state(plan, evidence_digest: str = "none"):
    packet = review_packet()
    packet["artifact_id"] = plan.candidate["artifact_id"]
    packet["bundle_digest"] = plan.bundle_digest
    packet["evidence_digest"] = evidence_digest
    packet["candidate"] = {
        "manifest_path": plan.manifest_relative.as_posix(),
        "payload_path": plan.payload_relative.as_posix(),
        "payload_source": plan.payload_bytes.decode("utf-8"),
        "purpose": plan.candidate["purpose"],
        "invocation": plan.candidate["invocation"],
        "language": plan.candidate["language"],
        "runtime": plan.candidate["runtime"],
        "dependencies": plan.candidate["dependencies"],
        "arguments": plan.candidate["arguments"],
        "environment": plan.candidate["environment"],
        "outputs": plan.candidate["outputs"],
        "exit_behavior": plan.candidate["exit_behavior"],
        "applicability": plan.candidate["applicability"],
        "safety": plan.candidate["safety"],
        "mutation_default": plan.candidate["mutation_default"],
        "verification_status": plan.verification["status"],
    }
    contributions = []
    for producer in ("scriptability", "execution-risk", "retrieval-economics"):
        contribution = review_contribution(producer)
        for field in (
            "review_id",
            "base_revision",
            "artifact_id",
            "bundle_digest",
            "evidence_digest",
        ):
            contribution[field] = packet[field]
        contributions.append(contribution)
    return review_module.reduce_review(packet, contributions)


class ReindexTests(unittest.TestCase):
    def test_generates_shared_and_local_indexes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "patterns").mkdir()
            (root / "patterns" / "retrieval-floor.md").write_text(ENTRY)
            (root / "local" / "notes").mkdir(parents=True)
            (root / "local" / "notes" / "preference.md").write_text(
                ENTRY.replace("type: pattern", "type: note")
            )

            changed = reindex_module.reindex(root)

            self.assertEqual(changed, (True, True))
            self.assertIn("patterns/retrieval-floor.md", (root / "MEMORY.md").read_text())
            self.assertIn("retrieval-floor.md", (root / "patterns" / "index.md").read_text())
            self.assertIn("notes/preference.md", (root / "local/MEMORY.local.md").read_text())
            self.assertEqual(reindex_module.reindex(root), (False, False))

    def test_omits_markdown_without_required_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "patterns").mkdir()
            (root / "patterns" / "invalid.md").write_text("# Missing type\n")

            reindex_module.reindex(root)

            self.assertNotIn("invalid.md", (root / "MEMORY.md").read_text())
            self.assertNotIn("invalid.md", (root / "patterns" / "index.md").read_text())


class GuardTests(unittest.TestCase):
    def test_allows_shareable_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "patterns").mkdir()
            (root / "patterns" / "entry.md").write_text(ENTRY)
            self.assertEqual(guard_module.scan(root), [])

    def test_blocks_machine_specific_home_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "snippets").mkdir()
            machine_path = "/" + "Users/private-user/private/tool"
            (root / "snippets" / "bad.md").write_text(f"run {machine_path}\n")
            failures = guard_module.scan(root)
            self.assertTrue(any("machine-specific" in failure for failure in failures))

    def test_blocks_case_insensitive_denylist_terms_without_echoing_term(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "decisions").mkdir()
            (root / "local").mkdir()
            (root / "local" / "shared-denylist.txt").write_text("Example Customer\n")
            (root / "decisions" / "bad.md").write_text("example customer detail\n")
            failures = guard_module.scan(root)
            self.assertEqual(len(failures), 1)
            self.assertIn("local/shared-denylist.txt:1", failures[0])
            self.assertNotIn("Example Customer", failures[0])

    def test_scans_operating_files_not_only_knowledge_folders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "local").mkdir()
            (root / "local" / "shared-denylist.txt").write_text("Private Persona\n")
            readme = root / "README.md"
            readme.write_text("Maintained by Private Persona.\n")

            failures = guard_module.scan(root, [readme])

            self.assertEqual(len(failures), 1)
            self.assertIn("README.md:1", failures[0])
            self.assertNotIn("Private Persona", failures[0])

    def test_blocks_personal_email_but_allows_example_domains(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "README.md"
            document.write_text("Public example: maintainer@example.com\n")
            self.assertEqual(guard_module.scan(root, [document]), [])

            private_email = "person" + "@private.invalid"
            document.write_text(f"Contact: {private_email}\n")
            failures = guard_module.scan(root, [document])

            self.assertEqual(len(failures), 1)
            self.assertIn("personal email address", failures[0])

    def test_runtime_identity_terms_are_checked_without_echoing_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "README.md"
            private_term = "Unique Local Identity"
            document.write_text(f"Maintained by {private_term}.\n")
            original = guard_module.runtime_identity_terms
            guard_module.runtime_identity_terms = lambda _root: [
                ("test identity", private_term)
            ]
            try:
                failures = guard_module.scan(
                    root, [document], include_runtime_identity=True
                )
            finally:
                guard_module.runtime_identity_terms = original

            self.assertEqual(len(failures), 1)
            self.assertIn("test identity", failures[0])
            self.assertNotIn(private_term, failures[0])

    def test_redacts_a_private_publication_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "local").mkdir()
            private_term = "Private Persona"
            (root / "local" / "shared-denylist.txt").write_text(
                f"{private_term}\n"
            )
            document = root / f"notes-by-{private_term}.md"
            document.write_text("Public-looking content.\n")

            failures = guard_module.scan(root, [document])

            self.assertEqual(len(failures), 1)
            self.assertIn("<redacted-path>:1", failures[0])
            self.assertNotIn(private_term, failures[0])


class PublicAuditTests(unittest.TestCase):
    def test_accepts_noreply_authors_and_rejects_personal_email(self):
        self.assertTrue(
            audit_module.safe_author_email("contributor@users.noreply.github.com")
        )
        private_email = "person" + "@private.invalid"
        self.assertFalse(audit_module.safe_author_email(private_email))

    def test_rejects_a_runtime_identity_as_commit_author_name(self):
        private_name = "Private Persona"
        self.assertFalse(
            audit_module.safe_author_name(
                private_name, [("test identity", private_name)]
            )
        )
        self.assertTrue(
            audit_module.safe_author_name(
                "Public Maintainer", [("test identity", private_name)]
            )
        )


class LintTests(unittest.TestCase):
    def test_accepts_valid_entry_and_rejects_unknown_tag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder in lint_module.SHARED_FOLDERS:
                (root / folder).mkdir()
            (root / "meta").mkdir()
            (root / "meta" / "tag-taxonomy.md").write_text(
                "- `retrieval` — search and ranking.\n"
            )
            entry = root / "patterns" / "retrieval-floor.md"
            entry.write_text(ENTRY)

            errors, _ = lint_module.lint(root)
            self.assertEqual(errors, [])

            entry.write_text(ENTRY.replace("[retrieval]", "[unknown-tag]"))
            errors, _ = lint_module.lint(root)
            self.assertTrue(any("unregistered tag" in error for error in errors))

    def test_lifecycle_provenance_and_orphan_checks_are_advisory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder in lint_module.SHARED_FOLDERS:
                (root / folder).mkdir()
            (root / "meta").mkdir()
            (root / "meta" / "tag-taxonomy.md").write_text(
                "- `retrieval` — search and ranking.\n"
            )
            (root / "patterns" / "advisory.md").write_text(
                ENTRY.replace(
                    "## Active\n\nUse text search.\n\n## Source\n\nTest fixture.\n",
                    "A useful claim.\n",
                )
            )

            errors, warnings = lint_module.lint(root)

            self.assertEqual(errors, [])
            self.assertTrue(any("missing lifecycle" in warning for warning in warnings))
            self.assertTrue(any("missing provenance" in warning for warning in warnings))
            self.assertTrue(any("no inbound links" in warning for warning in warnings))


class ArtifactBundleTests(unittest.TestCase):
    def test_materializes_and_recalls_exact_safe_python_artifact(self):
        script_source = ARTIFACT_SCRIPT
        candidate = artifact_candidate()

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            candidate_path = temporary_path / "candidate.json"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            payload_source = temporary_path / "normalize-text.py"
            payload_source.write_text(script_source, encoding="utf-8")
            command = [
                sys.executable,
                str(ROOT / "bin" / "artifact_bundle.py"),
            ]
            common = [
                "--root",
                str(root),
                "--candidate",
                str(candidate_path),
                "--payload",
                str(payload_source),
                "--manifest",
                "snippets/normalize-text.md",
            ]
            evidence_path = temporary_path / "evidence.json"

            prepared = subprocess.run(
                command
                + ["prepare"]
                + common
                + ["--evidence-output", str(evidence_path)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            preparation = json.loads(prepared.stdout)
            self.assertEqual(preparation["operation"], "prepare")
            self.assertFalse(preparation["written"])
            self.assertEqual(preparation["verification"]["status"], "unverified")
            preliminary_evidence = json.loads(
                evidence_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                preparation["evidence_digest"],
                preliminary_evidence["evidence_digest"],
            )
            self.assertTrue(
                all(
                    check["status"] == "authorization-blocked"
                    for check in preliminary_evidence["checks"][1:]
                )
            )
            self.assertFalse((root / "snippets" / "normalize-text.md").exists())
            self.assertFalse((root / "snippets" / "normalize-text.py").exists())

            packet = review_packet()
            packet["bundle_digest"] = preparation["bundle_digest"]
            packet["evidence_digest"] = "none"
            contributions = self._matching_contributions(packet)
            review_state = review_module.reduce_review(packet, contributions)
            review_path = temporary_path / "review.json"
            approval_path = temporary_path / "approval.json"
            review_path.write_text(json.dumps(review_state), encoding="utf-8")

            verified = subprocess.run(
                command
                + ["verify"]
                + common
                + [
                    "--review-state",
                    str(review_path),
                    "--evidence-output",
                    str(evidence_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(verified.returncode, 0, verified.stderr)
            verification_result = json.loads(verified.stdout)
            self.assertEqual(verification_result["operation"], "verify")
            self.assertEqual(
                verification_result["verification"]["status"], "verified"
            )
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertTrue(
                all(check["status"] == "passed" for check in evidence["checks"])
            )
            approval = approval_module.record_approval(
                evidence, review_state, "accepted"
            )
            approval_path.write_text(json.dumps(approval), encoding="utf-8")

            rejected_approval = copy.deepcopy(approval)
            rejected_approval["bundle_digest"] = f"sha256:{'0' * 64}"
            rejected_path = temporary_path / "rejected-approval.json"
            rejected_path.write_text(
                json.dumps(rejected_approval), encoding="utf-8"
            )

            rejected = subprocess.run(
                command
                + ["publish"]
                + common
                + [
                    "--evidence",
                    str(evidence_path),
                    "--review-state",
                    str(review_path),
                    "--approval",
                    str(rejected_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("human approval bundle_digest does not match", rejected.stderr)
            self.assertFalse((root / "snippets" / "normalize-text.md").exists())
            self.assertFalse((root / "snippets" / "normalize-text.py").exists())

            published = subprocess.run(
                command
                + ["publish"]
                + common
                + [
                    "--evidence",
                    str(evidence_path),
                    "--review-state",
                    str(review_path),
                    "--approval",
                    str(approval_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(published.returncode, 0, published.stderr)
            publication = json.loads(published.stdout)
            self.assertEqual(publication["bundle_digest"], preparation["bundle_digest"])
            self.assertTrue(publication["written"])
            manifest = root / "snippets" / "normalize-text.md"
            payload = root / "snippets" / "normalize-text.py"
            persisted_evidence = root / "snippets" / "normalize-text.evidence.json"
            persisted_review = root / "snippets" / "normalize-text.review.json"
            persisted_approval = root / "snippets" / "normalize-text.approval.json"
            self.assertTrue(manifest.exists())
            self.assertEqual(payload.read_bytes(), script_source.encode("utf-8"))
            self.assertTrue(persisted_evidence.exists())
            self.assertTrue(persisted_review.exists())
            self.assertTrue(persisted_approval.exists())

            before = {
                path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
                for path in (
                    manifest,
                    payload,
                    persisted_evidence,
                    persisted_review,
                    persisted_approval,
                )
            }
            recalled = subprocess.run(
                command
                + [
                    "recall",
                    "--root",
                    str(root),
                    "--manifest",
                    "snippets/normalize-text.md",
                ],
                capture_output=True,
                check=False,
            )
            after = {
                path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
                for path in (
                    manifest,
                    payload,
                    persisted_evidence,
                    persisted_review,
                    persisted_approval,
                )
            }

            self.assertEqual(recalled.returncode, 0, recalled.stderr.decode())
            metadata = artifact_module.parse(manifest).metadata
            self.assertEqual(
                recalled.stdout.decode(),
                "\n".join(
                    [
                        "snippets/normalize-text.py",
                        candidate["invocation"],
                        str(metadata["artifact_verification"]),
                        "",
                    ]
                ),
            )
            self.assertEqual(after, before)

            source_recall = subprocess.run(
                command
                + [
                    "recall",
                    "--root",
                    str(root),
                    "--manifest",
                    "snippets/normalize-text.md",
                    "--show-code",
                ],
                capture_output=True,
                check=False,
            )

            self.assertEqual(source_recall.returncode, 0)
            self.assertEqual(source_recall.stdout, script_source.encode("utf-8"))

    def _matching_contributions(self, packet):
        contributions = []
        for producer in (
            "scriptability",
            "execution-risk",
            "retrieval-economics",
        ):
            contribution = review_contribution(producer, packet["base_revision"])
            for field in (
                "review_id",
                "base_revision",
                "artifact_id",
                "bundle_digest",
                "evidence_digest",
            ):
                contribution[field] = packet[field]
            contributions.append(contribution)
        return contributions

    def test_shared_lint_accepts_declared_payload_and_rejects_orphan(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            for folder in lint_module.SHARED_FOLDERS:
                (root / folder).mkdir(parents=True)
            (root / "meta").mkdir()
            (root / "meta" / "tag-taxonomy.md").write_text("", encoding="utf-8")
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            _, payload = publish_test_artifact(
                root, scratch, "snippets/normalize-text.md"
            )

            errors, _ = lint_module.lint(root)
            self.assertEqual(errors, [])
            validation = artifact_module.validate_shared_tree(root)
            self.assertEqual(validation["status"], "valid")
            self.assertEqual(validation["manifests"], 1)
            self.assertEqual(validation["payloads"], 1)

            payload.write_text(
                payload.read_text(encoding="utf-8") + "# changed\n",
                encoding="utf-8",
            )
            errors, _ = lint_module.lint(root)
            self.assertTrue(
                any("invalid artifact bundle: bundle digest mismatch" in error for error in errors)
            )

            payload.write_text(ARTIFACT_SCRIPT, encoding="utf-8")

            (root / "snippets" / "orphan.py").write_text(
                "print('orphan')\n", encoding="utf-8"
            )
            errors, _ = lint_module.lint(root)

            self.assertTrue(
                any(
                    "orphan.py: invalid artifact bundle: orphaned artifact payload"
                    in error
                    for error in errors
                )
            )
            validation = artifact_module.validate_shared_tree(root)
            self.assertEqual(validation["status"], "invalid")
            self.assertEqual(validation["errors"][0]["path"], "snippets/orphan.py")

    def test_recall_rejects_invalid_shared_and_local_bundles_without_writes(self):
        def remove_payload(_manifest, payload):
            payload.unlink()

        def cross_privacy_layer(manifest, _payload):
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    "artifact_payload: snippets/normalize-text.py",
                    "artifact_payload: local/normalize-text.py",
                ),
                encoding="utf-8",
            )

        def change_stem(manifest, _payload):
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    "artifact_payload: snippets/normalize-text.py",
                    "artifact_payload: snippets/different.py",
                ),
                encoding="utf-8",
            )

        def escape_root(manifest, _payload):
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    "artifact_payload: snippets/normalize-text.py",
                    "artifact_payload: ../outside.py",
                ),
                encoding="utf-8",
            )

        def remove_identity(manifest, _payload):
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    "artifact_id: normalize-text\n", ""
                ),
                encoding="utf-8",
            )

        def require_future_runtime(manifest, _payload):
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    "artifact_runtime: python>=3.11",
                    "artifact_runtime: python>=999.0",
                ),
                encoding="utf-8",
            )

        def change_payload(_manifest, payload):
            payload.write_text(
                payload.read_text(encoding="utf-8") + "# changed\n",
                encoding="utf-8",
            )

        def corrupt_verification(manifest, _payload):
            text = manifest.read_text(encoding="utf-8")
            text = re.sub(
                r"artifact_verification: .+",
                "artifact_verification: probably fine",
                text,
                count=1,
            )
            manifest.write_text(text, encoding="utf-8")

        cases = [
            ("cannot read payload", remove_payload),
            ("crosses privacy layers", cross_privacy_layer),
            ("must share a stem", change_stem),
            ("payload escapes Brain root", escape_root),
            ("missing artifact field", remove_identity),
            ("requires Python 999.0", require_future_runtime),
            ("bundle digest mismatch", change_payload),
            ("artifact_verification has invalid format", corrupt_verification),
        ]
        for expected, mutate in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                temporary_path = Path(temporary)
                root = temporary_path / "brain"
                root.mkdir()
                scratch = temporary_path / "scratch"
                scratch.mkdir()
                manifest, payload = publish_test_artifact(
                    root, scratch, "snippets/normalize-text.md"
                )
                mutate(manifest, payload)
                before = {
                    path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
                    for path in root.rglob("*")
                    if path.is_file()
                }

                with self.assertRaisesRegex(artifact_module.ArtifactError, expected):
                    artifact_module.recall_bundle(
                        root, Path("snippets/normalize-text.md")
                    )

                after = {
                    path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
                    for path in root.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(after, before)

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            manifest, _ = publish_test_artifact(
                root, scratch, "local/notes/normalize-text.md"
            )

            recalled = artifact_module.recall_bundle(
                root, manifest.relative_to(root)
            ).decode("utf-8")

            self.assertTrue(recalled.startswith("local/notes/normalize-text.py\n"))

            before = manifest.read_bytes()
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    "artifact_payload: local/notes/normalize-text.py",
                    "artifact_payload: snippets/normalize-text.py",
                ),
                encoding="utf-8",
            )
            changed = manifest.read_bytes()
            with self.assertRaisesRegex(
                artifact_module.ArtifactError, "crosses privacy layers"
            ):
                artifact_module.recall_bundle(root, manifest.relative_to(root))
            self.assertNotEqual(before, changed)
            self.assertEqual(manifest.read_bytes(), changed)


class SharedCommitTests(unittest.TestCase):
    def git(self, root: Path, *arguments: str):
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def repository(self, root: Path):
        self.git(root, "init", "-q")
        self.git(root, "config", "user.name", "Test Maintainer")
        self.git(root, "config", "user.email", "maintainer@example.com")
        for folder in commit_module.ALLOWLIST:
            path = root / folder
            if path.suffix:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("initial\n", encoding="utf-8")
            else:
                path.mkdir(parents=True, exist_ok=True)
                (path / ".keep").write_text("initial\n", encoding="utf-8")
        (root / "unrelated.txt").write_text("initial\n", encoding="utf-8")
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "initial")

    def brain_repository(self, root: Path):
        for folder in lint_module.SHARED_FOLDERS:
            (root / folder).mkdir(parents=True)
        (root / "meta").mkdir()
        (root / "meta" / "tag-taxonomy.md").write_text("", encoding="utf-8")
        (root / ".gitignore").write_text(
            "local/\n.tmp/\n__pycache__/\n*.pyc\n", encoding="utf-8"
        )
        for relative in (
            "bin/artifact_bundle.py",
            "bin/lint_brain.py",
            "bin/okf.py",
            "bin/reindex.py",
            "scripts/auto-commit.sh",
            "scripts/commit_shared.py",
            "scripts/guard_shared.py",
        ):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        schema_source = ROOT / ".agents" / "skills" / "remember" / "schemas"
        schema_destination = (
            root / ".agents" / "skills" / "remember" / "schemas"
        )
        shutil.copytree(schema_source, schema_destination)
        reindex_module.reindex(root)
        (root / "unrelated.txt").write_text("initial\n", encoding="utf-8")
        self.git(root, "init", "-q")
        self.git(root, "config", "user.name", "Test Maintainer")
        self.git(root, "config", "user.email", "maintainer@example.com")
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "initial")

    def test_isolated_commit_preserves_unrelated_staged_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.repository(root)
            (root / "unrelated.txt").write_text("staged user work\n", encoding="utf-8")
            self.git(root, "add", "unrelated.txt")
            (root / "snippets" / "artifact.md").write_text(
                "artifact manifest\n", encoding="utf-8"
            )
            (root / "snippets" / "artifact.py").write_text(
                "print('artifact')\n", encoding="utf-8"
            )

            changed = commit_module.commit_shared(root)

            self.assertEqual(
                changed,
                ["snippets/artifact.md", "snippets/artifact.py"],
            )
            committed = self.git(
                root, "show", "--pretty=format:", "--name-only", "HEAD"
            ).splitlines()
            self.assertEqual(
                [line for line in committed if line],
                ["snippets/artifact.md", "snippets/artifact.py"],
            )
            self.assertEqual(
                self.git(root, "diff", "--cached", "--name-only"),
                "unrelated.txt",
            )
            self.assertEqual(
                self.git(root, "show", "HEAD:unrelated.txt"),
                "initial",
            )

    def test_failed_hook_leaves_head_and_real_index_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.repository(root)
            (root / "unrelated.txt").write_text("staged user work\n", encoding="utf-8")
            self.git(root, "add", "unrelated.txt")
            (root / "snippets" / "rejected.md").write_text(
                "rejected artifact\n", encoding="utf-8"
            )
            hook = root / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            hook.chmod(0o755)
            head_before = self.git(root, "rev-parse", "HEAD")
            staged_before = self.git(root, "diff", "--cached", "--name-only")

            with self.assertRaises(commit_module.CommitError):
                commit_module.commit_shared(root)

            self.assertEqual(self.git(root, "rev-parse", "HEAD"), head_before)
            self.assertEqual(
                self.git(root, "diff", "--cached", "--name-only"), staged_before
            )
            self.assertEqual(staged_before, "unrelated.txt")

    def test_auto_commit_publishes_complete_bundle_and_rejects_partial_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.brain_repository(root)
            scratch = root / ".tmp"
            scratch.mkdir()
            publish_test_artifact(root, scratch, "snippets/normalize-text.md")
            (root / "unrelated.txt").write_text("staged user work\n", encoding="utf-8")
            self.git(root, "add", "unrelated.txt")

            published = subprocess.run(
                ["bash", "scripts/auto-commit.sh"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(published.returncode, 0, published.stderr)
            committed = self.git(
                root, "show", "--pretty=format:", "--name-only", "HEAD"
            ).splitlines()
            self.assertIn("snippets/normalize-text.md", committed)
            self.assertIn("snippets/normalize-text.py", committed)
            self.assertNotIn("unrelated.txt", committed)
            self.assertEqual(
                self.git(root, "diff", "--cached", "--name-only"),
                "unrelated.txt",
            )

            (root / "snippets" / "orphan.py").write_text(
                "print('orphan')\n", encoding="utf-8"
            )
            head_before = self.git(root, "rev-parse", "HEAD")
            staged_before = self.git(root, "diff", "--cached", "--name-only")

            rejected = subprocess.run(
                ["bash", "scripts/auto-commit.sh"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(rejected.returncode, 0)
            validation = json.loads(rejected.stdout[rejected.stdout.index("{") :])
            self.assertEqual(validation["status"], "invalid")
            self.assertEqual(self.git(root, "rev-parse", "HEAD"), head_before)
            self.assertEqual(
                self.git(root, "diff", "--cached", "--name-only"), staged_before
            )


class ArtifactReviewTests(unittest.TestCase):
    def contributions(self, revision: int = 0):
        return [
            review_contribution("scriptability", revision),
            review_contribution("execution-risk", revision),
            review_contribution("retrieval-economics", revision),
        ]

    def test_reducer_is_order_independent_and_requires_all_lenses(self):
        packet = review_packet()
        contributions = self.contributions()

        forward = review_module.reduce_review(packet, contributions)
        reverse = review_module.reduce_review(packet, list(reversed(contributions)))

        self.assertEqual(forward, reverse)
        self.assertEqual(forward["status"], "agreement")
        self.assertTrue(forward["agreement"])
        self.assertEqual(
            forward["accepted_lenses"],
            ["execution-risk", "retrieval-economics", "scriptability"],
        )
        self.assertNotIn("verification_status", forward)

        incomplete = review_module.reduce_review(packet, contributions[:2])
        self.assertEqual(incomplete["status"], "incomplete")
        self.assertFalse(incomplete["agreement"])
        self.assertEqual(incomplete["missing_lenses"], ["retrieval-economics"])

    def test_reducer_preserves_blockers_and_enforces_revision_bound(self):
        packet = review_packet()
        contributions = self.contributions()
        blocker = contributions[1]
        blocker["verdict"] = "block"
        blocker["summary"] = "Help execution can mutate state."
        blocker["findings"] = [
            {
                "id": "help-side-effect",
                "severity": "blocking",
                "path": "snippets/normalize-text.py",
                "line_start": 1,
                "line_end": 8,
                "body": "Import-time behavior is not proven side-effect free.",
                "recommendation": "Move all behavior behind parsed command dispatch.",
                "confidence": 0.97,
            }
        ]

        state = review_module.reduce_review(packet, contributions)

        self.assertEqual(state["status"], "blocked")
        self.assertFalse(state["agreement"])
        self.assertEqual(state["blockers"][0]["id"], "help-side-effect")
        self.assertEqual(state["blockers"][0]["producer"], "execution-risk")
        self.assertEqual(state["next_revision"], 1)

        final_packet = review_packet(2)
        final_contributions = self.contributions(2)
        final_contributions[1]["verdict"] = "block"
        final_contributions[1]["findings"] = blocker["findings"]
        exhausted = review_module.reduce_review(final_packet, final_contributions)

        self.assertEqual(exhausted["status"], "exhausted")
        self.assertTrue(exhausted["exhausted"])
        self.assertEqual(exhausted["next_revision"], 3)

    def test_reducer_rejects_stale_mismatched_duplicate_and_owned_fields(self):
        packet = review_packet()
        base = review_contribution("scriptability")
        mutations = []
        for field, value, expected in (
            ("review_id", "other-review", "review_id does not match"),
            ("base_revision", 1, "base_revision does not match"),
            ("bundle_digest", f"sha256:{'b' * 64}", "bundle_digest does not match"),
            ("evidence_digest", f"sha256:{'c' * 64}", "evidence_digest does not match"),
        ):
            contribution = copy.deepcopy(base)
            contribution[field] = value
            mutations.append((contribution, expected))
        unknown = copy.deepcopy(base)
        unknown["candidate"] = {}
        mutations.append((unknown, "unknown field 'candidate'"))

        for contribution, expected in mutations:
            with self.subTest(expected=expected), self.assertRaisesRegex(
                ValueError, expected
            ):
                review_module.reduce_review(packet, [contribution])

        with self.assertRaisesRegex(
            review_module.ReviewError, "duplicate contribution producer"
        ):
            review_module.reduce_review(packet, [base, copy.deepcopy(base)])


class ArtifactEvidenceTests(unittest.TestCase):
    def prepared_plan(self, root: Path, scratch: Path):
        candidate = artifact_candidate()
        candidate_path = scratch / "candidate.json"
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        payload = scratch / candidate["payload_name"]
        payload.write_text(ARTIFACT_SCRIPT, encoding="utf-8")
        return artifact_module.prepare_bundle(
            root,
            candidate_path,
            payload,
            Path("snippets/normalize-text.md"),
        )

    def test_execution_checks_wait_for_agreement(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            plan = self.prepared_plan(root, scratch)
            packet = review_packet()
            packet["bundle_digest"] = plan.bundle_digest
            incomplete = review_module.reduce_review(packet, [])

            with self.assertRaisesRegex(
                ValueError, "review has not reached agreement"
            ):
                artifact_module.verify_after_review(plan, incomplete)

            preliminary = artifact_module.verification_evidence(plan)
            self.assertEqual(preliminary["status"], "unverified")
            self.assertEqual(
                [check["status"] for check in preliminary["checks"]],
                [
                    "passed",
                    "authorization-blocked",
                    "authorization-blocked",
                    "authorization-blocked",
                ],
            )

    def test_failed_or_unavailable_checks_never_become_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            plan = self.prepared_plan(root, scratch)
            review_state = agreed_review_state(plan)

            with mock.patch.object(
                artifact_module,
                "run_artifact_command",
                side_effect=[
                    ("passed", "help passed"),
                    ("failed", "focused test failed"),
                    ("unavailable", "runtime unavailable"),
                ],
            ):
                _, evidence = artifact_module.verify_after_review(
                    plan, review_state
                )

            self.assertEqual(evidence["status"], "unverified")
            self.assertEqual(
                [check["status"] for check in evidence["checks"]],
                ["passed", "passed", "failed", "unavailable"],
            )
            approval = approval_module.record_approval(
                evidence, review_state, "accepted"
            )
            with self.assertRaisesRegex(ValueError, "candidate is not verified"):
                artifact_module.publish_bundle(
                    root, plan, evidence, review_state, approval
                )
            self.assertFalse((root / "snippets" / "normalize-text.md").exists())

    def test_approval_is_bound_to_bundle_evidence_and_review_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            plan = self.prepared_plan(root, scratch)
            review_state = agreed_review_state(plan)
            _, evidence = artifact_module.verify_after_review(plan, review_state)
            approval = approval_module.record_approval(
                evidence, review_state, "accepted"
            )

            for field, value, expected in (
                ("bundle_digest", f"sha256:{'b' * 64}", "bundle_digest"),
                ("evidence_digest", f"sha256:{'c' * 64}", "evidence_digest"),
                ("base_revision", 1, "base_revision"),
                ("decision", "rejected", "decision is not accepted"),
            ):
                changed = copy.deepcopy(approval)
                changed[field] = value
                with self.subTest(field=field), self.assertRaisesRegex(
                    ValueError, expected
                ):
                    artifact_module.publish_bundle(
                        root, plan, evidence, review_state, changed
                    )

            artifact_module.publish_bundle(
                root, plan, evidence, review_state, approval
            )
            recalled = artifact_module.recall_bundle(
                root, Path("snippets/normalize-text.md")
            ).decode("utf-8")
            self.assertIn("verified", recalled)


class ArtifactUpdateTests(unittest.TestCase):
    def test_match_uses_identity_and_keeps_shared_results_free_of_local_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            publish_test_artifact(root, scratch, "snippets/normalize-text.md")
            local_candidate = artifact_candidate("local/notes/normalize-text.md")
            local_candidate["description"] = "PRIVATE_LOCAL_DESCRIPTION"
            publish_test_artifact(
                root,
                scratch,
                "local/notes/normalize-text.md",
                candidate_override=local_candidate,
            )

            shared = artifact_module.artifact_match_result(
                root,
                artifact_candidate("snippets/normalize-text.md"),
                Path("snippets/normalize-text.md"),
                [Path("local/notes/normalize-text.md")],
            )

            self.assertEqual(shared["status"], "authoritative")
            self.assertEqual(shared["scope"], "shared")
            self.assertEqual(
                shared["selected_manifest"], "snippets/normalize-text.md"
            )
            encoded = json.dumps(shared)
            self.assertNotIn("local/", encoded)
            self.assertNotIn("PRIVATE_LOCAL_DESCRIPTION", encoded)

            local = artifact_module.artifact_match_result(
                root,
                local_candidate,
                Path("local/notes/normalize-text.md"),
            )
            self.assertEqual(local["status"], "ambiguous")
            self.assertEqual(local["scope"], "local-and-shared")
            self.assertNotIn("selected_manifest", local)
            self.assertEqual(
                {item["manifest"] for item in local["candidates"]},
                {
                    "local/notes/normalize-text.md",
                    "snippets/normalize-text.md",
                },
            )

    def test_semantic_or_lexical_candidates_are_ambiguous_not_auto_merged(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            publish_test_artifact(root, scratch, "snippets/normalize-text.md")
            candidate = artifact_candidate("snippets/cleanup-text.md")
            candidate["artifact_id"] = "cleanup-text"
            candidate["payload_name"] = "cleanup-text.py"
            candidate["invocation"] = (
                "python3 snippets/cleanup-text.py --text EXAMPLE_TEXT"
            )

            result = artifact_module.artifact_match_result(
                root,
                candidate,
                Path("snippets/cleanup-text.md"),
                [Path("snippets/normalize-text.md")],
            )

            self.assertEqual(result["status"], "ambiguous")
            self.assertNotIn("selected_manifest", result)
            self.assertTrue(result["candidates"][0]["semantic_candidate"])
            self.assertFalse(result["candidates"][0]["identity_match"])

    def test_duplicate_shared_id_is_ambiguous_and_invalidates_the_shared_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            publish_test_artifact(root, scratch, "snippets/normalize-text.md")
            duplicate = artifact_candidate("patterns/normalize-text-copy.md")
            duplicate["payload_name"] = "normalize-text-copy.py"
            duplicate["invocation"] = (
                "python3 patterns/normalize-text-copy.py --text EXAMPLE_TEXT"
            )
            publish_test_artifact(
                root,
                scratch,
                "patterns/normalize-text-copy.md",
                candidate_override=duplicate,
            )

            result = artifact_module.artifact_match_result(
                root,
                artifact_candidate("snippets/normalize-text.md"),
                Path("snippets/normalize-text.md"),
            )
            validation = artifact_module.validate_shared_tree(root)

            self.assertEqual(result["status"], "ambiguous")
            self.assertNotIn("selected_manifest", result)
            self.assertEqual(len(result["candidates"]), 2)
            self.assertEqual(validation["status"], "invalid")
            self.assertTrue(
                any("duplicate artifact_id" in error["message"] for error in validation["errors"])
            )

    def test_update_in_place_preserves_history_and_invalidates_old_attestations(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            manifest, _ = publish_test_artifact(
                root, scratch, "snippets/normalize-text.md"
            )
            old_metadata = artifact_module.parse(manifest).metadata
            old_digest = old_metadata["bundle_digest"]
            stale_evidence = artifact_module.load_json(
                root / "snippets/normalize-text.evidence.json"
            )
            stale_review = artifact_module.load_json(
                root / "snippets/normalize-text.review.json"
            )
            stale_approval = artifact_module.load_json(
                root / "snippets/normalize-text.approval.json"
            )

            updated_candidate = artifact_candidate("snippets/normalize-text.md")
            updated_candidate["purpose"] = (
                "Normalize text deterministically while preserving internal spacing."
            )
            candidate_path = scratch / "updated-candidate.json"
            candidate_path.write_text(json.dumps(updated_candidate), encoding="utf-8")
            updated_source = ARTIFACT_SCRIPT + "\n# revision two\n"
            payload_source = scratch / "normalize-text.py"
            payload_source.write_text(updated_source, encoding="utf-8")
            plan = artifact_module.prepare_bundle(
                root,
                candidate_path,
                payload_source,
                Path("snippets/normalize-text.md"),
            )
            self.assertNotEqual(plan.bundle_digest, old_digest)

            with self.assertRaisesRegex(
                artifact_module.ArtifactError, "verification evidence bundle_digest"
            ):
                artifact_module.publish_bundle(
                    root, plan, stale_evidence, stale_review, stale_approval
                )

            review_state = agreed_review_state(plan)
            _, evidence = artifact_module.verify_after_review(plan, review_state)
            approval = approval_module.record_approval(
                evidence, review_state, "accepted"
            )
            artifact_module.publish_bundle(
                root, plan, evidence, review_state, approval
            )

            text = manifest.read_text(encoding="utf-8")
            self.assertIn("## Superseded", text)
            self.assertIn(str(old_digest), text)
            self.assertIn(
                "Normalize a text value without mutating files or services.", text
            )
            self.assertEqual(
                artifact_module.recall_bundle(
                    root, Path("snippets/normalize-text.md"), show_code=True
                ),
                updated_source.encode("utf-8"),
            )
            self.assertEqual(
                artifact_module.parse(manifest).metadata["bundle_digest"],
                plan.bundle_digest,
            )
            self.assertEqual(
                len(
                    [
                        path
                        for path in root.rglob("*.md")
                        if artifact_module.parse(path).metadata.get("artifact_id")
                        == "normalize-text"
                    ]
                ),
                1,
            )
            self.assertNotEqual(evidence["evidence_digest"], stale_evidence["evidence_digest"])
            self.assertNotEqual(review_state["bundle_digest"], stale_review["bundle_digest"])
            self.assertNotEqual(approval["bundle_digest"], stale_approval["bundle_digest"])

            with self.assertRaisesRegex(
                artifact_module.ArtifactError,
                "update does not change bundle identity",
            ):
                artifact_module.publish_bundle(
                    root, plan, evidence, review_state, approval
                )


class ArtifactGeneralizationTests(unittest.TestCase):
    def trace_request(self, **changes):
        request = {
            "schema_version": 1,
            "kind": "artifact-trace-request",
            "stable": True,
            "repeatable": True,
            "complete": True,
            "conceptual": False,
            "one_off": False,
            "checkpoint": False,
            "inputs_defined": True,
            "outputs_defined": True,
            "applicability_defined": True,
            "safety_defined": True,
            "ecosystem": "generic",
            "available_languages": ["python", "javascript", "shell"],
        }
        request.update(changes)
        return request

    def test_trace_rejects_non_operational_knowledge_and_selects_native_language(self):
        conceptual = artifact_module.trace_artifact(
            self.trace_request(conceptual=True)
        )
        javascript = artifact_module.trace_artifact(
            self.trace_request(
                ecosystem="javascript",
                available_languages=["javascript", "python"],
            )
        )
        generic = artifact_module.trace_artifact(
            self.trace_request(available_languages=["shell", "python"])
        )

        self.assertEqual(
            conceptual,
            {
                "schema_version": 1,
                "kind": "artifact-trace-result",
                "eligible": False,
                "reason": "non-operational",
            },
        )
        self.assertEqual(javascript["language"], "javascript")
        self.assertEqual(generic["language"], "python")

    def test_shell_bundle_records_complete_contract_and_recalls_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            candidate = artifact_candidate("snippets/normalize-shell.md")
            candidate.update(
                {
                    "artifact_id": "normalize-shell",
                    "title": "Normalize text with shell",
                    "payload_name": "normalize-shell.sh",
                    "language": "shell",
                    "runtime": "bash>=3.2",
                    "invocation": (
                        "bash snippets/normalize-shell.sh --text EXAMPLE_TEXT"
                    ),
                    "dependencies": ["Bash standard builtins"],
                    "environment": ["LC_ALL=EXAMPLE_LOCALE"],
                    "applicability": ["POSIX-like host with Bash 3.2 or newer"],
                }
            )
            manifest, _ = publish_test_artifact(
                root,
                scratch,
                "snippets/normalize-shell.md",
                candidate_override=candidate,
                script_source=SHELL_ARTIFACT_SCRIPT,
            )
            metadata = artifact_module.parse(manifest).metadata

            for field in (
                "artifact_arguments",
                "artifact_environment",
                "artifact_exit_behavior",
                "artifact_applicability",
                "artifact_mutation_default",
            ):
                self.assertIn(field, metadata)
            self.assertEqual(metadata["artifact_language"], "shell")
            self.assertEqual(
                artifact_module.recall_bundle(
                    root, Path("snippets/normalize-shell.md"), show_code=True
                ),
                SHELL_ARTIFACT_SCRIPT.encode("utf-8"),
            )

    def test_context_mismatch_returns_only_incompatibility_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            manifest, _ = publish_test_artifact(
                root, scratch, "snippets/normalize-text.md"
            )
            before = {
                path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
                for path in root.rglob("*")
                if path.is_file()
            }

            result = artifact_module.recall_bundle(
                root,
                manifest.relative_to(root),
                show_code=True,
                context_language="javascript",
            )
            after = {
                path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
                for path in root.rglob("*")
                if path.is_file()
            }

            self.assertEqual(
                result,
                b"incompatible: language requires python, got javascript; request adaptation separately\n",
            )
            self.assertEqual(after, before)

    def test_mutating_candidate_must_use_preview_for_invocation_and_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "brain"
            root.mkdir()
            scratch = temporary_path / "scratch"
            scratch.mkdir()
            candidate = artifact_candidate()
            candidate["safety"] = "mutating"
            candidate["mutation_default"] = "preview"
            candidate_path = scratch / "candidate.json"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            payload = scratch / candidate["payload_name"]
            payload.write_text(ARTIFACT_SCRIPT, encoding="utf-8")

            with self.assertRaisesRegex(
                artifact_module.ArtifactError,
                "invocation must select --preview",
            ):
                artifact_module.prepare_bundle(
                    root,
                    candidate_path,
                    payload,
                    Path("snippets/normalize-text.md"),
                )


class ArtifactEvalTests(unittest.TestCase):
    def test_eval_corpus_is_schema_valid_complete_and_deterministic(self):
        suite = artifact_module.load_json(ROOT / "evals" / "artifact-cases.json")
        required = {
            "eligible-operation",
            "prose-only-knowledge",
            "native-language",
            "complete-manifest",
            "safe-mutation-default",
            "private-routing",
            "duplicate-update",
            "review-grounding",
            "review-agreement",
            "verification-calibration",
            "approval-binding",
            "recall-three-fields",
            "recall-byte-exact",
            "authoritative-ranking",
            "context-mismatch",
            "offline-read-only",
            "malformed-json",
            "stale-contribution",
            "digest-mismatch",
            "incomplete-publication",
        }
        self.assertEqual({case["id"] for case in suite["cases"]}, required)

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            result_one = artifact_eval_module.run_suite(suite, Path(first))
            result_two = artifact_eval_module.run_suite(suite, Path(second))

        self.assertEqual(result_one, result_two)
        self.assertEqual(result_one["status"], "passed")
        self.assertEqual(result_one["passed"], len(required))


class CanvasTests(unittest.TestCase):
    def test_live_server_accepts_only_local_host_headers_in_loopback_mode(self):
        for value in ("localhost:8765", "localhost.", "127.0.0.1:8765", "[::1]:8765"):
            self.assertTrue(canvas_module.is_local_host_header(value))
        self.assertFalse(canvas_module.is_local_host_header("example.invalid:8765"))

    def test_canvas_omits_generated_navigation_but_keeps_sessions(self):
        self.assertFalse(canvas_module.is_canvas_content("MEMORY.md"))
        self.assertFalse(canvas_module.is_canvas_content("concepts/index.md"))
        self.assertFalse(canvas_module.is_canvas_content("local/projects/example/_index.md"))
        self.assertFalse(canvas_module.is_canvas_content("local/MEMORY.local.md"))
        self.assertFalse(canvas_module.is_canvas_content("README.md"))
        self.assertTrue(canvas_module.is_canvas_content("concepts/retrieval.md"))
        self.assertTrue(canvas_module.is_canvas_content("local/notes/retrieval.md"))
        self.assertTrue(canvas_module.is_canvas_content("session.jsonl", is_session=True))

    def test_normalizes_relative_markdown_and_wikilinks(self):
        self.assertEqual(
            canvas_module.normalize_target(
                "patterns/retrieval-floor.md", "../concepts/search.md#active"
            ),
            "concepts/search.md",
        )
        self.assertEqual(
            canvas_module.normalize_target("patterns/retrieval-floor.md", "related-note"),
            "patterns/related-note.md",
        )
        self.assertIsNone(
            canvas_module.normalize_target(
                "patterns/retrieval-floor.md", "https://example.com/source.md"
            )
        )

    def test_semantic_edges_are_thresholded_and_neighbor_limited(self):
        edges = canvas_module.semantic_edges(
            {
                "doc:a": [1.0, 0.0],
                "doc:b": [0.9, 0.1],
                "doc:c": [0.0, 1.0],
            },
            threshold=0.8,
            neighbors=1,
        )

        self.assertEqual(len(edges), 1)
        self.assertEqual({edges[0].source, edges[0].target}, {"doc:a", "doc:b"})
        self.assertEqual(edges[0].kind, "semantic")

    def test_render_is_offline_and_contains_layer_controls(self):
        graph = {
            "nodes": [
                {
                    "id": "doc:brain:patterns/example.md",
                    "label": "Example",
                    "kind": "document",
                    "category": "pattern",
                    "collection": "brain",
                    "path": "patterns/example.md",
                    "title": "Example",
                    "description": "Example entry.",
                    "tags": [],
                    "url": "",
                    "editor_url": "",
                    "date": "2026-08-27",
                    "project": "",
                    "is_session": False,
                }
            ],
            "links": [],
            "meta": {"collections": ["brain"], "scope": "shared"},
        }

        rendered = canvas_module.render_html(graph, "window.d3 = {};")

        self.assertIn('id="layer-link"', rendered)
        self.assertIn('id="layer-tag"', rendered)
        self.assertIn('id="layer-semantic"', rendered)
        self.assertIn('id="inspector" aria-label="Node details"', rendered)
        self.assertIn('id="relations"', rendered)
        self.assertIn('id="detail-editor"', rendered)
        self.assertIn("Open in VS Code", rendered)
        self.assertIn("Linked knowledge", rendered)
        self.assertIn("Map key", rendered)
        self.assertIn('id="search-results"', rendered)
        self.assertIn('id="zoom-in"', rendered)
        self.assertIn('id="zoom-out"', rendered)
        self.assertIn('data-category="pattern"', rendered)
        self.assertIn('placeholder="Search knowledge and sessions"', rendered)
        self.assertIn("prefers-reduced-motion:reduce", rendered)
        self.assertIn("pointer-events: none", rendered)
        self.assertIn('event.key === "Enter"', rendered)
        self.assertIn('role="status" aria-live="polite"', rendered)
        self.assertIn('class="identity-logo"', rendered)
        self.assertIn("Double link brackets surround one durable knowledge unit", rendered)
        self.assertNotIn("__BRAIN_LOGO__", rendered)
        self.assertIn("1 documents · 0 tags · 0 visible edges", rendered)
        self.assertIn("window.d3 = {};", rendered)
        self.assertNotIn("<script src=", rendered)
        self.assertNotIn('"liveReload"', rendered)

        live = canvas_module.render_html(graph, "window.d3 = {};", live_version=7)
        self.assertIn('"liveReload":{"version":7,"url":"/api/version"}', live)

    def test_vscode_url_uses_the_documented_file_scheme_and_escapes_spaces(self):
        path = ROOT / "concepts" / "example note.md"

        self.assertEqual(
            canvas_module.vscode_url(path),
            f"vscode://file{path.as_posix().replace(' ', '%20')}",
        )

    def test_canvas_interactive_icons_use_the_shared_icon_contract(self):
        template = (ROOT / "bin" / "canvas.html").read_text(encoding="utf-8")
        interactive_icons = re.findall(
            r'<(?:button|summary|a)\b[^>]*>\s*<svg\b([^>]*)>', template
        )

        self.assertGreaterEqual(len(interactive_icons), 12)
        for attributes in interactive_icons:
            self.assertIn('class="ui-icon"', attributes)

    def test_live_state_version_changes_when_a_watched_source_changes(self):
        graph = {"nodes": [], "links": [], "meta": {"collections": ["brain"], "scope": "shared"}}
        with tempfile.TemporaryDirectory() as temporary:
            watched = Path(temporary) / "canvas.js"
            watched.write_text("initial")
            state = canvas_module.CanvasState(graph, "window.d3 = {};", [watched], lambda: (graph, []))
            _, _, initial_version = state.snapshot()
            watched.write_text("changed")
            state.refresh_if_changed()
            _, _, changed_version = state.snapshot()

            self.assertEqual(initial_version, 1)
            self.assertEqual(changed_version, 2)

    def test_render_preserves_inlined_d3_license_notice(self):
        graph = {"nodes": [], "links": [], "meta": {"collections": [], "scope": "shared"}}
        d3_source = "/* D3.js license: example notice */\nwindow.d3 = {};"

        rendered = canvas_module.render_html(graph, d3_source)

        self.assertIn("D3.js license: example notice", rendered)
        self.assertIn("window.d3 = {};", rendered)

    def test_private_scope_adds_codex_sessions_to_brain(self):
        available = {
            "brain": canvas_module.Collection("brain", ".", True),
            "codex-sessions": canvas_module.Collection(
                "codex-sessions", "local/session-catalog", False
            ),
        }

        shared = canvas_module.choose_collections(available, [], False)
        private = canvas_module.choose_collections(
            available, [], False, include_private=True
        )

        self.assertEqual([item.name for item in shared], ["brain"])
        self.assertEqual(
            [item.name for item in private], ["brain", "codex-sessions"]
        )

    def test_extracts_private_codex_session_catalog_metadata(self):
        records = [
            {
                "type": "session_meta",
                "payload": {
                    "timestamp": "2026-08-27T15:03:28Z",
                    "cwd": "/private/example-project",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "# AGENTS.md instructions for a repository",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Map sessions into the knowledge canvas and explain their links.",
                        }
                    ],
                },
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "rollout.jsonl"
            session.write_text("\n".join(json.dumps(record) for record in records))

            title, description, timestamp, project = (
                canvas_module.codex_session_metadata(session)
            )

        self.assertEqual(
            title, "Map sessions into the knowledge canvas and explain their links."
        )
        self.assertEqual(description, "Codex session · example-project")
        self.assertEqual(timestamp, "2026-08-27T15:03:28Z")
        self.assertEqual(project, "example-project")


class SessionCatalogTests(unittest.TestCase):
    def test_syncs_compact_private_markdown_from_jsonl(self):
        records = [
            {
                "type": "session_meta",
                "payload": {
                    "timestamp": "2026-08-27T15:03:28Z",
                    "cwd": "/private/example-project",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Connect sessions to concepts in the canvas.",
                        }
                    ],
                },
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sessions"
            output = root / "catalog"
            session = source / "2026" / "08" / "27" / "rollout.jsonl"
            session.parent.mkdir(parents=True)
            session.write_text("\n".join(json.dumps(record) for record in records))

            changed = session_module.sync(source, output)
            catalog = output / "2026" / "08" / "27" / "rollout.md"
            parsed = canvas_module.parse(catalog).metadata

        self.assertEqual(changed, (1, 0))
        self.assertEqual(parsed["type"], "session")
        self.assertEqual(parsed["project"], "example-project")
        self.assertEqual(parsed["timestamp"], "2026-08-27T15:03:28Z")
        self.assertIn("Connect sessions to concepts", parsed["title"])


if __name__ == "__main__":
    unittest.main()
