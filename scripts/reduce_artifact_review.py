#!/usr/bin/env python3
"""Validate and deterministically reduce content-bound artifact reviews."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from artifact_bundle import ArtifactError, load_json, validate_against_schema  # noqa: E402


SCHEMAS = ROOT / ".agents" / "skills" / "remember" / "schemas"
PACKET_SCHEMA = SCHEMAS / "review-packet.schema.json"
CONTRIBUTION_SCHEMA = SCHEMAS / "review-contribution.schema.json"
STATE_SCHEMA = SCHEMAS / "review-state.schema.json"
LENSES = ("execution-risk", "retrieval-economics", "scriptability")


class ReviewError(ValueError):
    """A review object violates protocol invariants."""


def validate_packet(packet: dict[str, Any]) -> None:
    validate_against_schema(packet, PACKET_SCHEMA)
    if packet["id"] != packet["review_id"]:
        raise ReviewError("review packet id must equal review_id")
    if sorted(packet["required_lenses"]) != list(LENSES):
        raise ReviewError("review packet must require each review lens exactly once")
    if packet["base_revision"] >= packet["max_revisions"]:
        raise ReviewError("base revision is outside the configured review bound")


def validate_contribution(
    packet: dict[str, Any], contribution: dict[str, Any]
) -> None:
    validate_against_schema(contribution, CONTRIBUTION_SCHEMA)
    for field in (
        "review_id",
        "base_revision",
        "artifact_id",
        "bundle_digest",
        "evidence_digest",
    ):
        if contribution[field] != packet[field]:
            raise ReviewError(
                f"{contribution['producer']}: {field} does not match review packet"
            )
    if contribution["producer"] not in packet["required_lenses"]:
        raise ReviewError(f"unexpected review producer: {contribution['producer']}")
    finding_ids = [finding["id"] for finding in contribution["findings"]]
    if len(finding_ids) != len(set(finding_ids)):
        raise ReviewError(f"{contribution['producer']}: duplicate finding id")
    for finding in contribution["findings"]:
        if finding["line_end"] < finding["line_start"]:
            raise ReviewError(
                f"{contribution['producer']}: finding line_end precedes line_start"
            )
    if contribution["verdict"] == "block" and not any(
        finding["severity"] == "blocking" for finding in contribution["findings"]
    ):
        raise ReviewError(
            f"{contribution['producer']}: block verdict requires a blocking finding"
        )


def reduce_review(
    packet: dict[str, Any], contributions: list[dict[str, Any]]
) -> dict[str, Any]:
    validate_packet(packet)
    by_producer: dict[str, dict[str, Any]] = {}
    contribution_ids: set[str] = set()
    for contribution in contributions:
        validate_contribution(packet, contribution)
        producer = contribution["producer"]
        if producer in by_producer:
            raise ReviewError(f"duplicate contribution producer: {producer}")
        if contribution["id"] in contribution_ids:
            raise ReviewError(f"duplicate contribution id: {contribution['id']}")
        by_producer[producer] = contribution
        contribution_ids.add(contribution["id"])

    required = sorted(packet["required_lenses"])
    missing = [lens for lens in required if lens not in by_producer]
    accepted = sorted(
        producer
        for producer, contribution in by_producer.items()
        if contribution["verdict"] == "accept"
    )
    blockers: list[dict[str, Any]] = []
    for producer in sorted(by_producer):
        contribution = by_producer[producer]
        for finding in sorted(contribution["findings"], key=lambda item: item["id"]):
            if finding["severity"] != "blocking":
                continue
            blockers.append(
                {
                    "producer": producer,
                    "id": finding["id"],
                    "path": finding["path"],
                    "line_start": finding["line_start"],
                    "line_end": finding["line_end"],
                    "body": finding["body"],
                    "recommendation": finding["recommendation"],
                    "confidence": finding["confidence"],
                }
            )

    agreement = not missing and not blockers and len(accepted) == len(required)
    exhausted = (
        not agreement
        and packet["base_revision"] + 1 >= packet["max_revisions"]
    )
    if agreement:
        status = "agreement"
    elif exhausted:
        status = "exhausted"
    elif blockers:
        status = "blocked"
    else:
        status = "incomplete"
    state = {
        "schema_version": 1,
        "kind": "review-state",
        "id": f"{packet['review_id']}-state-{packet['base_revision']}",
        "review_id": packet["review_id"],
        "base_revision": packet["base_revision"],
        "producer": "reducer",
        "artifact_id": packet["artifact_id"],
        "bundle_digest": packet["bundle_digest"],
        "evidence_digest": packet["evidence_digest"],
        "status": status,
        "agreement": agreement,
        "accepted_lenses": accepted,
        "missing_lenses": missing,
        "blockers": blockers,
        "contributions": len(by_producer),
        "next_revision": (
            packet["base_revision"] if agreement else packet["base_revision"] + 1
        ),
        "exhausted": exhausted,
    }
    validate_against_schema(state, STATE_SCHEMA)
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--contribution", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        packet = load_json(args.packet)
        contributions = [load_json(path) for path in args.contribution]
        result = reduce_review(packet, contributions)
    except (ArtifactError, ReviewError) as exc:
        print(f"review error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
