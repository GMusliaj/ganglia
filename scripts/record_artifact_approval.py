#!/usr/bin/env python3
"""Record an explicit human artifact decision against one agreed review state."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from artifact_bundle import (  # noqa: E402
    APPROVAL_SCHEMA,
    EVIDENCE_SCHEMA,
    REVIEW_STATE_SCHEMA,
    ArtifactError,
    digest_evidence,
    load_json,
    validate_against_schema,
)


def record_approval(
    evidence: dict, review_state: dict, decision: str
) -> dict:
    validate_against_schema(evidence, EVIDENCE_SCHEMA)
    validate_against_schema(review_state, REVIEW_STATE_SCHEMA)
    if digest_evidence(evidence) != evidence["evidence_digest"]:
        raise ArtifactError("verification evidence digest mismatch")
    for field in ("artifact_id", "bundle_digest"):
        if review_state[field] != evidence[field]:
            raise ArtifactError(f"review state {field} does not match evidence")
    if review_state["evidence_digest"] not in ("none", evidence["evidence_digest"]):
        raise ArtifactError("review state evidence_digest does not match evidence")
    if decision == "accepted" and (
        not review_state["agreement"]
        or review_state["status"] != "agreement"
        or review_state["blockers"]
        or review_state["missing_lenses"]
        or review_state["exhausted"]
    ):
        raise ArtifactError("cannot accept a review state without clean agreement")
    approval = {
        "schema_version": 1,
        "kind": "human-approval",
        "id": f"{review_state['artifact_id']}-approval-{review_state['base_revision']}",
        "producer": "human",
        "artifact_id": review_state["artifact_id"],
        "bundle_digest": review_state["bundle_digest"],
        "evidence_digest": evidence["evidence_digest"],
        "review_id": review_state["review_id"],
        "base_revision": review_state["base_revision"],
        "decision": decision,
        "approved_at": date.today().isoformat(),
    }
    validate_against_schema(approval, APPROVAL_SCHEMA)
    return approval


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--review-state", type=Path, required=True)
    parser.add_argument("--decision", choices=("accepted", "rejected"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        approval = record_approval(
            load_json(args.evidence), load_json(args.review_state), args.decision
        )
    except ArtifactError as exc:
        print(f"approval error: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(approval, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(approval, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
