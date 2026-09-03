#!/usr/bin/env python3
"""Run deterministic behavior evals for zero-synthesis artifact recall."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "scripts"))

import artifact_bundle as artifact  # noqa: E402
import record_artifact_approval as approval_module  # noqa: E402
import reduce_artifact_review as review_module  # noqa: E402


SCHEMAS = ROOT / ".agents" / "skills" / "remember" / "schemas"
SUITE_SCHEMA = SCHEMAS / "artifact-eval-suite.schema.json"
RESULT_SCHEMA = SCHEMAS / "artifact-eval-result.schema.json"
DEFAULT_CASES = ROOT / "evals" / "artifact-cases.json"
PAYLOAD = b"""#!/usr/bin/env python3
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--text", default="EXAMPLE_TEXT")
args = parser.parse_args()
print(args.text.strip())
"""


def candidate(manifest: str = "snippets/normalize-text.md") -> dict[str, Any]:
    payload = Path(manifest).with_suffix(".py").as_posix()
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
        "working_directory": "ganglia-root",
        "dependencies": ["Python standard library"],
        "arguments": ["--text TEXT: text to normalize"],
        "environment": [],
        "inputs": ["Text supplied with --text"],
        "outputs": ["Normalized text on standard output"],
        "exit_behavior": ["0 on success", "2 on invalid arguments"],
        "applicability": ["Text accepted by Python 3.11 or newer"],
        "safety": "read-only",
        "mutation_default": "read-only",
        "purpose": "Normalize a text value without mutation.",
        "focused_test": {"arguments": ["--text", "focused"], "expected_stdout": "focused"},
        "representative_run": {"arguments": ["--text", "EXAMPLE_TEXT"], "expected_stdout": "EXAMPLE_TEXT"},
    }


def trace_request(**changes: Any) -> dict[str, Any]:
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


class Context:
    def __init__(self, base: Path):
        self.base = base

    def workspace(self, name: str) -> tuple[Path, Path]:
        root = self.base / name / "ganglia"
        scratch = self.base / name / "scratch"
        root.mkdir(parents=True)
        scratch.mkdir(parents=True)
        return root, scratch

    def prepare(
        self,
        root: Path,
        scratch: Path,
        value: dict[str, Any] | None = None,
        manifest: str = "snippets/normalize-text.md",
        payload: bytes = PAYLOAD,
    ) -> artifact.BundlePlan:
        value = value or candidate(manifest)
        candidate_path = scratch / "candidate.json"
        payload_path = scratch / value["payload_name"]
        candidate_path.write_text(json.dumps(value), encoding="utf-8")
        payload_path.write_bytes(payload)
        return artifact.prepare_bundle(root, candidate_path, payload_path, Path(manifest))

    def review(self, plan: artifact.BundlePlan) -> dict[str, Any]:
        review_id = f"{plan.candidate['artifact_id']}-review"
        packet = {
            "schema_version": 1,
            "kind": "review-packet",
            "id": review_id,
            "review_id": review_id,
            "base_revision": 0,
            "producer": "remember",
            "artifact_id": plan.candidate["artifact_id"],
            "bundle_digest": plan.bundle_digest,
            "evidence_digest": "none",
            "required_lenses": ["scriptability", "execution-risk", "retrieval-economics"],
            "max_revisions": 3,
            "candidate": {
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
            },
        }
        contributions = []
        for producer in ("scriptability", "execution-risk", "retrieval-economics"):
            contributions.append(
                {
                    "schema_version": 1,
                    "kind": "review-contribution",
                    "id": f"{producer}-contribution",
                    "review_id": review_id,
                    "base_revision": 0,
                    "producer": producer,
                    "artifact_id": plan.candidate["artifact_id"],
                    "bundle_digest": plan.bundle_digest,
                    "evidence_digest": "none",
                    "verdict": "accept",
                    "summary": "No material blocker in this deterministic fixture.",
                    "findings": [],
                    "confidence": 1.0,
                }
            )
        return review_module.reduce_review(packet, contributions)

    def review_packet_candidate(self, plan: artifact.BundlePlan) -> dict[str, Any]:
        return {
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

    def publish(
        self,
        root: Path,
        scratch: Path,
        value: dict[str, Any] | None = None,
        manifest: str = "snippets/normalize-text.md",
        payload: bytes = PAYLOAD,
    ) -> artifact.BundlePlan:
        plan = self.prepare(root, scratch, value, manifest, payload)
        review = self.review(plan)
        verified, evidence = artifact.verify_after_review(plan, review)
        approval = approval_module.record_approval(evidence, review, "accepted")
        artifact.publish_bundle(root, plan, evidence, review, approval)
        return verified


def expect_error(action: Callable[[], Any], expected: type[Exception] = ValueError) -> bool:
    try:
        action()
    except expected:
        return True
    return False


def evaluate(assertion: str, context: Context) -> str:
    if assertion == "eligible-operation":
        return "materialize" if artifact.trace_artifact(trace_request())["eligible"] else "prose"
    if assertion == "prose-only-knowledge":
        variants = [
            trace_request(conceptual=True),
            trace_request(one_off=True),
            trace_request(checkpoint=True),
            trace_request(complete=False),
        ]
        return "prose" if all(not artifact.trace_artifact(item)["eligible"] for item in variants) else "materialize"
    if assertion == "native-language":
        languages = [
            artifact.trace_artifact(trace_request(ecosystem=name))["language"]
            for name in ("python", "javascript", "shell")
        ]
        return "native-language" if languages == ["python", "javascript", "shell"] else "wrong-language"

    root, scratch = context.workspace(assertion)
    if assertion == "complete-manifest":
        projection = context.prepare(root, scratch).projection
        required = {
            "artifact_runtime", "artifact_dependencies", "artifact_arguments",
            "artifact_environment", "artifact_outputs", "artifact_exit_behavior",
            "artifact_applicability", "artifact_mutation_default",
        }
        return "complete" if required <= projection.keys() else "incomplete"
    if assertion == "safe-mutation-default":
        value = candidate()
        value.update({"safety": "mutating", "mutation_default": "preview"})
        return "reject-unsafe" if expect_error(lambda: context.prepare(root, scratch, value)) else "accepted-unsafe"
    if assertion == "private-routing":
        context.publish(root, scratch)
        local_scratch = scratch / "local"
        local_scratch.mkdir()
        context.publish(root, local_scratch, candidate("local/notes/normalize-text.md"), "local/notes/normalize-text.md")
        result = artifact.artifact_match_result(root, candidate(), Path("snippets/normalize-text.md"), [Path("local/notes/normalize-text.md")])
        return "no-local-leak" if "local/" not in json.dumps(result) else "local-leak"
    if assertion == "duplicate-update":
        first = context.publish(root, scratch)
        update_scratch = scratch / "update"
        update_scratch.mkdir()
        plan = context.prepare(root, update_scratch, payload=PAYLOAD + b"\n# revision\n")
        review = context.review(plan)
        _, evidence = artifact.verify_after_review(plan, review)
        approval = approval_module.record_approval(evidence, review, "accepted")
        artifact.publish_bundle(root, plan, evidence, review, approval)
        manifests = [path for path in root.rglob("*.md") if artifact.parse(path).metadata.get("artifact_id") == "normalize-text"]
        return "one-authoritative" if len(manifests) == 1 and plan.bundle_digest != first.bundle_digest else "duplicate"
    if assertion in {"review-grounding", "review-agreement", "stale-contribution"}:
        plan = context.prepare(root, scratch)
        review = context.review(plan)
        if assertion == "review-agreement":
            return "agreement" if review["agreement"] else "no-agreement"
        packet = {
            "schema_version": 1, "kind": "review-packet", "id": "normalize-text-review",
            "review_id": "normalize-text-review", "base_revision": 0, "producer": "remember",
            "artifact_id": plan.candidate["artifact_id"], "bundle_digest": plan.bundle_digest,
            "evidence_digest": "none", "required_lenses": ["scriptability", "execution-risk", "retrieval-economics"],
            "max_revisions": 3, "candidate": context.review_packet_candidate(plan),
        }
        contribution = {
            "schema_version": 1, "kind": "review-contribution", "id": "scriptability-contribution",
            "review_id": packet["review_id"], "base_revision": 1 if assertion == "stale-contribution" else 0,
            "producer": "scriptability", "artifact_id": packet["artifact_id"],
            "bundle_digest": (f"sha256:{'b' * 64}" if assertion == "review-grounding" else packet["bundle_digest"]),
            "evidence_digest": "none", "verdict": "accept", "summary": "Fixture.", "findings": [], "confidence": 1.0,
        }
        expected = "reject-stale" if assertion == "stale-contribution" else "reject-mismatch"
        return expected if expect_error(lambda: review_module.reduce_review(packet, [contribution])) else "accepted-invalid"
    if assertion == "verification-calibration":
        plan = context.prepare(root, scratch)
        evidence = artifact.verification_evidence(plan)
        evidence["status"] = "verified"
        evidence["evidence_digest"] = artifact.digest_evidence(evidence)
        return "reject-false-verified" if expect_error(lambda: artifact.validate_evidence(plan, evidence)) else "false-verified"
    if assertion == "approval-binding":
        plan = context.prepare(root, scratch)
        review = context.review(plan)
        _, evidence = artifact.verify_after_review(plan, review)
        approval = approval_module.record_approval(evidence, review, "accepted")
        approval["bundle_digest"] = f"sha256:{'b' * 64}"
        return "reject-stale-approval" if expect_error(lambda: artifact.publish_bundle(root, plan, evidence, review, approval)) else "accepted-stale"
    if assertion in {"recall-run-offer", "recall-byte-exact", "context-mismatch", "offline-read-only", "authoritative-ranking", "digest-mismatch"}:
        plan = context.publish(root, scratch)
        manifest = Path("snippets/normalize-text.md")
        if assertion == "recall-run-offer":
            output = artifact.recall_bundle(root, manifest).decode("utf-8").splitlines()
            expected_offer = "Run this stored invocation now? [yes/no]"
            return "exact-run-offer" if len(output) == 4 and output[-1] == expected_offer else "wrong-shape"
        if assertion == "recall-byte-exact":
            return "byte-exact" if artifact.recall_bundle(root, manifest, True) == PAYLOAD else "changed-bytes"
        if assertion == "authoritative-ranking":
            result = artifact.artifact_match_result(root, candidate(), manifest)
            return "authoritative" if result.get("selected_manifest") == manifest.as_posix() else "ambiguous"
        if assertion == "context-mismatch":
            output = artifact.recall_bundle(root, manifest, True, context_language="javascript")
            return "incompatible" if output.startswith(b"incompatible:") and PAYLOAD not in output else "adapted"
        if assertion == "offline-read-only":
            before = {path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes()) for path in root.rglob("*") if path.is_file()}
            artifact.recall_bundle(root, manifest)
            after = {path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes()) for path in root.rglob("*") if path.is_file()}
            return "no-write" if before == after else "wrote-state"
        payload_path = root / plan.payload_relative
        payload_path.write_bytes(payload_path.read_bytes() + b"\n# tampered\n")
        return "reject-digest" if expect_error(lambda: artifact.recall_bundle(root, manifest)) else "accepted-digest"
    if assertion == "malformed-json":
        path = scratch / "malformed.json"
        path.write_text("{", encoding="utf-8")
        return "reject-malformed" if expect_error(lambda: artifact.load_json(path)) else "accepted-malformed"
    if assertion == "incomplete-publication":
        plan = context.prepare(root, scratch)
        review = context.review(plan)
        _, evidence = artifact.verify_after_review(plan, review)
        approval = approval_module.record_approval(evidence, review, "accepted")
        target = root / plan.manifest_relative
        target.parent.mkdir(parents=True)
        target.write_text("partial", encoding="utf-8")
        return "reject-incomplete" if expect_error(lambda: artifact.publish_bundle(root, plan, evidence, review, approval)) else "accepted-incomplete"
    return "unknown-assertion"


def run_suite(suite: dict[str, Any], base: Path) -> dict[str, Any]:
    artifact.validate_against_schema(suite, SUITE_SCHEMA)
    context = Context(base)
    results = []
    for case in suite["cases"]:
        try:
            actual = evaluate(case["assertion"], context)
            reason = "observed expected behavior" if actual == case["expected_behavior"] else "behavior differed"
        except Exception as exc:  # fail closed while keeping result schema-valid
            actual = "evaluation-error"
            reason = f"unexpected {type(exc).__name__}"
        results.append({
            "id": case["id"], "category": case["category"],
            "expected_behavior": case["expected_behavior"], "actual_behavior": actual,
            "passed": actual == case["expected_behavior"], "reason": reason,
        })
    passed = sum(item["passed"] for item in results)
    result = {
        "schema_version": 1, "kind": "artifact-eval-result",
        "status": "passed" if passed == len(results) else "failed",
        "total": len(results), "passed": passed, "failed": len(results) - passed,
        "cases": results,
    }
    artifact.validate_against_schema(result, RESULT_SCHEMA)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        suite = artifact.load_json(args.cases)
        with tempfile.TemporaryDirectory() as temporary:
            result = run_suite(suite, Path(temporary))
    except artifact.ArtifactError as exc:
        print(f"artifact eval error: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    print(f"artifact eval: {result['passed']}/{result['total']} passed", file=sys.stderr)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
