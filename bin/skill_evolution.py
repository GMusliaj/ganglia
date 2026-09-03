#!/usr/bin/env python3
"""Run a private, human-gated skill-evolution workspace for Ganglia."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from guard_shared import (  # noqa: E402
    EMAIL,
    MACHINE_PATHS,
    SECRET_PATTERNS,
    denylist,
    runtime_identity_terms,
    safe_email,
    scan as guard_scan,
)


SCHEMA_ROOT = ROOT / ".agents" / "skills" / "skill-evolution" / "schemas"
EVIDENCE_INPUT_SCHEMA = SCHEMA_ROOT / "skill-evidence-input.schema.json"
EVIDENCE_SCHEMA = SCHEMA_ROOT / "skill-evidence.schema.json"
PROPOSAL_INPUT_SCHEMA = SCHEMA_ROOT / "skill-proposal-input.schema.json"
PROPOSAL_SCHEMA = SCHEMA_ROOT / "skill-proposal.schema.json"
EVAL_RESULT_SCHEMA = SCHEMA_ROOT / "skill-eval-result.schema.json"
EVALUATION_SCHEMA = SCHEMA_ROOT / "skill-evaluation.schema.json"
APPROVAL_SCHEMA = SCHEMA_ROOT / "skill-approval.schema.json"
APPLICATION_SCHEMA = SCHEMA_ROOT / "skill-application.schema.json"
ROLLBACK_SCHEMA = SCHEMA_ROOT / "skill-rollback.schema.json"
IMPACT_SCHEMA = SCHEMA_ROOT / "skill-impact.schema.json"

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TARGET_SKILL = re.compile(
    r"^\.agents/skills/(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*)/SKILL\.md$"
)
EVALUATOR = re.compile(r"^evals/skills/[A-Za-z0-9._/-]+$")
DOMAINS = {
    "evidence": b"ganglia-skill-evidence-v1\0",
    "proposal": b"ganglia-skill-proposal-v1\0",
    "skill": b"ganglia-skill-content-v1\0",
    "evaluator": b"ganglia-skill-evaluator-v1\0",
    "evaluation": b"ganglia-skill-evaluation-v1\0",
    "approval": b"ganglia-skill-approval-v1\0",
    "application": b"ganglia-skill-application-v1\0",
    "rollback": b"ganglia-skill-rollback-v1\0",
    "impact": b"ganglia-skill-impact-v1\0",
}


class SkillEvolutionError(ValueError):
    """A deterministic skill-evolution contract failure."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SkillEvolutionError(f"cannot read JSON: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SkillEvolutionError(
            f"invalid JSON: {path}:{exc.lineno}: {exc.msg}"
        ) from exc
    if not isinstance(value, dict):
        raise SkillEvolutionError(f"JSON root must be an object: {path}")
    return value


def validate_scalar(value: Any, contract: dict[str, Any], field: str) -> list[str]:
    expected = contract.get("type")
    valid = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }.get(expected, False)
    if not valid:
        return [f"{field}: expected {expected}"]
    errors: list[str] = []
    if "const" in contract and value != contract["const"]:
        errors.append(f"{field}: expected {contract['const']!r}")
    if "enum" in contract and value not in contract["enum"]:
        errors.append(f"{field}: invalid value {value!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in contract and value < contract["minimum"]:
            errors.append(f"{field}: value is below minimum {contract['minimum']}")
        if "maximum" in contract and value > contract["maximum"]:
            errors.append(f"{field}: value is above maximum {contract['maximum']}")
    if isinstance(value, str):
        if len(value) < contract.get("minLength", 0):
            errors.append(f"{field}: value is too short")
        pattern = contract.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            errors.append(f"{field}: value does not match {pattern!r}")
    if isinstance(value, list):
        if len(value) < contract.get("minItems", 0):
            errors.append(f"{field}: too few items")
        if contract.get("uniqueItems") and len(value) != len(
            {json.dumps(item, sort_keys=True) for item in value}
        ):
            errors.append(f"{field}: duplicate items are not allowed")
        item_contract = contract.get("items")
        if item_contract:
            for index, item in enumerate(value):
                errors.extend(validate_scalar(item, item_contract, f"{field}[{index}]"))
    if isinstance(value, dict):
        errors.extend(validate_object(value, contract, field))
    return errors


def validate_object(
    value: dict[str, Any], schema: dict[str, Any], field: str = "object"
) -> list[str]:
    errors: list[str] = []
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    for missing in sorted(required - value.keys()):
        errors.append(f"{field}: missing required field {missing!r}")
    if schema.get("additionalProperties") is False:
        for unknown in sorted(value.keys() - properties.keys()):
            errors.append(f"{field}: unknown field {unknown!r}")
    for name, contract in properties.items():
        if name in value:
            errors.extend(validate_scalar(value[name], contract, name))
    return errors


def validate(value: dict[str, Any], schema_path: Path) -> None:
    schema = load_json(schema_path)
    errors = validate_object(value, schema)
    if errors:
        raise SkillEvolutionError("; ".join(errors))


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest_value(domain: str, value: Any) -> str:
    digest = hashlib.sha256()
    digest.update(DOMAINS[domain])
    digest.update(value if isinstance(value, bytes) else canonical_json(value))
    return f"sha256:{digest.hexdigest()}"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def confined_relative(root: Path, value: Path, label: str) -> Path:
    if value.is_absolute():
        raise SkillEvolutionError(f"{label} must be repository-relative: {value}")
    resolved = (root / value).resolve()
    try:
        return resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise SkillEvolutionError(f"{label} escapes Ganglia root: {value}") from exc


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write(
        path,
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def sanitize_text(
    value: str, private_terms: list[tuple[str, str]] | None = None
) -> str:
    sanitized = value
    for pattern in MACHINE_PATHS:
        sanitized = pattern.sub("EXAMPLE_REDACTED_HOME/", sanitized)
    sanitized = EMAIL.sub(
        lambda match: match.group(0)
        if safe_email(match)
        else "EXAMPLE_REDACTED_EMAIL",
        sanitized,
    )
    for _label, pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("EXAMPLE_REDACTED_SECRET", sanitized)
    for _source, term in private_terms or []:
        sanitized = re.sub(
            re.escape(term),
            "EXAMPLE_REDACTED_IDENTITY",
            sanitized,
            flags=re.IGNORECASE,
        )
    return sanitized


def sanitize(
    value: Any, private_terms: list[tuple[str, str]] | None = None
) -> Any:
    if isinstance(value, str):
        return sanitize_text(value, private_terms)
    if isinstance(value, list):
        return [sanitize(item, private_terms) for item in value]
    if isinstance(value, dict):
        return {key: sanitize(item, private_terms) for key, item in value.items()}
    return value


def validate_skill_text(content: bytes, expected_name: str) -> None:
    if SLUG.fullmatch(expected_name) is None:
        raise SkillEvolutionError(
            "candidate skill name must contain lowercase letters, digits, and single hyphens"
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillEvolutionError("candidate SKILL.md must be UTF-8") from exc
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise SkillEvolutionError("candidate SKILL.md must start with YAML frontmatter")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise SkillEvolutionError("candidate SKILL.md frontmatter is not closed") from exc
    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        raise SkillEvolutionError(f"candidate SKILL.md frontmatter is invalid: {exc}") from exc
    if not isinstance(metadata, dict):
        raise SkillEvolutionError("candidate SKILL.md frontmatter must be an object")
    allowed = {"name", "description", "license", "allowed-tools", "metadata"}
    unexpected = sorted(metadata.keys() - allowed)
    if unexpected:
        raise SkillEvolutionError(
            "candidate SKILL.md frontmatter has unsupported fields: "
            + ", ".join(unexpected)
        )
    if metadata.get("name") != expected_name:
        raise SkillEvolutionError(
            f"candidate skill name must be {expected_name!r}, got {metadata.get('name')!r}"
        )
    if len(expected_name) > 64:
        raise SkillEvolutionError("candidate skill name exceeds 64 characters")
    if not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
        raise SkillEvolutionError("candidate skill description is required")
    description = metadata["description"].strip()
    if len(description) > 1024:
        raise SkillEvolutionError("candidate skill description exceeds 1024 characters")
    if "<" in description or ">" in description:
        raise SkillEvolutionError("candidate skill description contains angle brackets")
    if not any(line.strip() for line in lines[closing + 1 :]):
        raise SkillEvolutionError("candidate SKILL.md body is empty")
    if "TODO" in text or "Replace with" in text:
        raise SkillEvolutionError("candidate SKILL.md contains scaffold placeholders")


@dataclass
class EvolutionWorkspace:
    """Deep module for private evidence and gated repo-local skill updates."""

    root: Path
    clock: Callable[[], str] = now_utc

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.storage = self.root / "local" / "skill-evolution"

    def _private_terms(self) -> list[tuple[str, str]]:
        return [*denylist(self.root), *runtime_identity_terms(self.root)]

    def capture(self, input_path: Path) -> dict[str, Any]:
        relative = confined_relative(self.root, input_path, "evidence input")
        if not relative.parts or relative.parts[0] != ".tmp":
            raise SkillEvolutionError("evidence input must be under ignored .tmp/")
        raw = load_json(self.root / relative)
        sanitized = sanitize(raw, self._private_terms())
        validate(sanitized, EVIDENCE_INPUT_SCHEMA)
        if "proposal_id" in sanitized:
            _proposal_dir, proposal, _application = self._active_application(
                sanitized["proposal_id"]
            )
            if proposal["skill_name"] != sanitized["skill_name"]:
                raise SkillEvolutionError(
                    "attributed proposal does not match evidence skill name"
                )
        evidence_digest = digest_value("evidence", sanitized)
        evidence_id = f"{sanitized['skill_name']}-{evidence_digest[7:19]}"
        evidence = {
            **sanitized,
            "evidence_id": evidence_id,
            "evidence_digest": evidence_digest,
            "captured_at": self.clock(),
        }
        validate(evidence, EVIDENCE_SCHEMA)
        output = (
            self.storage
            / "evidence"
            / sanitized["skill_name"]
            / f"{evidence_id}.json"
        )
        if output.exists():
            existing = load_json(output)
            self._validate_evidence_record(existing, output)
            if existing["evidence_digest"] != evidence_digest:
                raise SkillEvolutionError(f"evidence identity collision: {evidence_id}")
            evidence = existing
        else:
            write_json(output, evidence)
        if "proposal_id" in evidence:
            self._append_impact(
                f"- `{evidence['proposal_id']}` observed task "
                f"`{evidence['task_id']}` outcome `{evidence['outcome']}`; "
                f"evidence `{evidence_id}`"
            )
        return {
            "evidence_id": evidence_id,
            "evidence_digest": evidence_digest,
            "path": output.relative_to(self.root).as_posix(),
        }

    def _validate_evidence_record(
        self, record: dict[str, Any], path: Path
    ) -> None:
        validate(record, EVIDENCE_SCHEMA)
        covered = {
            key: value
            for key, value in record.items()
            if key not in ("evidence_id", "evidence_digest", "captured_at")
        }
        expected_digest = digest_value("evidence", covered)
        if expected_digest != record["evidence_digest"]:
            raise SkillEvolutionError(f"evidence digest mismatch: {path}")
        expected_id = f"{record['skill_name']}-{expected_digest[7:19]}"
        if record["evidence_id"] != expected_id:
            raise SkillEvolutionError(f"evidence id mismatch: {path}")

    def _evidence(self, skill_name: str) -> list[dict[str, Any]]:
        if SLUG.fullmatch(skill_name) is None:
            raise SkillEvolutionError(f"invalid skill name: {skill_name!r}")
        records: list[dict[str, Any]] = []
        for path in sorted((self.storage / "evidence" / skill_name).glob("*.json")):
            record = load_json(path)
            self._validate_evidence_record(record, path)
            records.append(record)
        return records

    def consolidate(self, skill_name: str, minimum_tasks: int = 2) -> dict[str, Any]:
        if minimum_tasks < 2:
            raise SkillEvolutionError("recurrent patterns require at least two tasks")
        records = self._evidence(skill_name)
        grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for record in records:
            for signal in record["signals"]:
                grouped.setdefault(signal["key"], []).append((record, signal))
        pattern_root = self.storage / "wiki" / "patterns" / skill_name
        recurrent: list[dict[str, Any]] = []
        for key, observations in sorted(grouped.items()):
            task_ids = sorted({record["task_id"] for record, _signal in observations})
            if len(task_ids) < minimum_tasks:
                continue
            evidence_ids = sorted(
                {record["evidence_id"] for record, _signal in observations}
            )
            kinds = sorted({signal["kind"] for _record, signal in observations})
            summaries = sorted({signal["summary"] for _record, signal in observations})
            title = key.replace("-", " ").title()
            lines = [
                "---",
                "type: skill-pattern",
                f"title: {json.dumps(title, ensure_ascii=False)}",
                f"description: {json.dumps(summaries[0], ensure_ascii=False)}",
                f"skill: {skill_name}",
                f"pattern_key: {key}",
                f"signal_kinds: {json.dumps(kinds)}",
                f"task_count: {len(task_ids)}",
                f"evidence_count: {len(evidence_ids)}",
                "status: recurrent",
                "---",
                "",
                f"# {title}",
                "",
                "## Active",
                "",
                f"Observed across {len(task_ids)} distinct tasks.",
                "",
                "### Observations",
                "",
                *[f"- {summary}" for summary in summaries],
                "",
                "## Evidence",
                "",
                *[f"- `{evidence_id}`" for evidence_id in evidence_ids],
                "",
            ]
            output = pattern_root / f"{key}.md"
            atomic_write(output, "\n".join(lines).encode("utf-8"))
            recurrent.append(
                {
                    "pattern_key": key,
                    "task_count": len(task_ids),
                    "evidence_count": len(evidence_ids),
                    "path": output.relative_to(self.root).as_posix(),
                }
            )
        recurrent_keys = {pattern["pattern_key"] for pattern in recurrent}
        for stale in pattern_root.glob("*.md"):
            if stale.stem not in recurrent_keys:
                stale.unlink()
        index = self.storage / "wiki" / "index.md"
        index_lines = [
            "# Skill evolution patterns",
            "",
            "Generated from sanitized evidence with at least two distinct task IDs.",
            "",
        ]
        for pattern in recurrent:
            path = Path(pattern["path"])
            relative = os.path.relpath(self.root / path, index.parent)
            index_lines.append(
                f"- [{pattern['pattern_key']}]({relative}) — "
                f"{pattern['task_count']} tasks, {pattern['evidence_count']} records"
            )
        atomic_write(index, ("\n".join(index_lines) + "\n").encode("utf-8"))
        return {
            "skill_name": skill_name,
            "evidence_records": len(records),
            "recurrent_patterns": recurrent,
            "index": index.relative_to(self.root).as_posix(),
        }

    def prepare(self, input_path: Path) -> dict[str, Any]:
        relative = confined_relative(self.root, input_path, "proposal input")
        if not relative.parts or relative.parts[0] != ".tmp":
            raise SkillEvolutionError("proposal input must be under ignored .tmp/")
        proposal_input = load_json(self.root / relative)
        validate(proposal_input, PROPOSAL_INPUT_SCHEMA)
        match = TARGET_SKILL.fullmatch(proposal_input["target_skill"])
        if match is None or match.group("name") != proposal_input["skill_name"]:
            raise SkillEvolutionError(
                "target_skill must be .agents/skills/<skill_name>/SKILL.md"
            )
        candidate_relative = confined_relative(
            self.root, Path(proposal_input["candidate_skill"]), "candidate skill"
        )
        if not candidate_relative.parts or candidate_relative.parts[0] != ".tmp":
            raise SkillEvolutionError("candidate skill must be under ignored .tmp/")
        candidate_source = self.root / candidate_relative
        try:
            candidate_bytes = candidate_source.read_bytes()
        except OSError as exc:
            raise SkillEvolutionError(f"cannot read candidate skill: {exc}") from exc
        validate_skill_text(candidate_bytes, proposal_input["skill_name"])
        candidate_failures = guard_scan(
            self.root, [candidate_source], include_runtime_identity=True
        )
        if candidate_failures:
            raise SkillEvolutionError(
                "candidate publication guard failed: "
                + "; ".join(candidate_failures)
            )
        for key in proposal_input["pattern_keys"]:
            task_ids = {
                record["task_id"]
                for record in self._evidence(proposal_input["skill_name"])
                for signal in record["signals"]
                if signal["key"] == key
            }
            if len(task_ids) < 2:
                raise SkillEvolutionError(
                    f"pattern lacks evidence from two distinct tasks: {key}"
                )
            pattern = (
                self.storage
                / "wiki"
                / "patterns"
                / proposal_input["skill_name"]
                / f"{key}.md"
            )
            if not pattern.is_file():
                raise SkillEvolutionError(f"recurrent pattern is unavailable: {key}")
        evaluator_relative = confined_relative(
            self.root, Path(proposal_input["evaluator"]["path"]), "evaluator"
        )
        if EVALUATOR.fullmatch(evaluator_relative.as_posix()) is None:
            raise SkillEvolutionError("evaluator must be under evals/skills/")
        evaluator_path = self.root / evaluator_relative
        if not evaluator_path.is_file() or not os.access(evaluator_path, os.X_OK):
            raise SkillEvolutionError("evaluator must exist and be executable")
        target_relative = Path(proposal_input["target_skill"])
        target = self.root / target_relative
        base_bytes = target.read_bytes() if target.is_file() else b""
        base_digest = digest_value("skill", base_bytes)
        candidate_digest = digest_value("skill", candidate_bytes)
        evaluator_digest = digest_value("evaluator", evaluator_path.read_bytes())
        identity = {
            **proposal_input,
            "base_digest": base_digest,
            "candidate_digest": candidate_digest,
            "evaluator_digest": evaluator_digest,
        }
        proposal_id = f"{proposal_input['skill_name']}-{digest_value('proposal', identity)[7:19]}"
        proposal_dir = self.storage / "proposals" / proposal_id
        baseline_dir = proposal_dir / "baseline" / proposal_input["skill_name"]
        candidate_dir = proposal_dir / "candidate" / proposal_input["skill_name"]
        baseline_snapshot = baseline_dir / "SKILL.md"
        candidate_snapshot = candidate_dir / "SKILL.md"
        atomic_write(baseline_snapshot, base_bytes)
        atomic_write(candidate_snapshot, candidate_bytes)
        proposal = {
            "schema_version": 1,
            "kind": "skill-proposal",
            "proposal_id": proposal_id,
            "skill_name": proposal_input["skill_name"],
            "target_skill": target_relative.as_posix(),
            "pattern_keys": proposal_input["pattern_keys"],
            "rationale": sanitize_text(
                proposal_input["rationale"], self._private_terms()
            ),
            "evaluator": proposal_input["evaluator"],
            "base_digest": base_digest,
            "candidate_digest": candidate_digest,
            "evaluator_digest": evaluator_digest,
            "baseline_snapshot": baseline_dir.relative_to(self.root).as_posix(),
            "candidate_snapshot": candidate_dir.relative_to(self.root).as_posix(),
            "prepared_at": self.clock(),
            "proposal_digest": "",
        }
        proposal["proposal_digest"] = digest_value(
            "proposal",
            {key: value for key, value in proposal.items() if key != "proposal_digest"},
        )
        validate(proposal, PROPOSAL_SCHEMA)
        proposal_path = proposal_dir / "proposal.json"
        if proposal_path.exists():
            existing = load_json(proposal_path)
            if existing["candidate_digest"] != candidate_digest:
                raise SkillEvolutionError(f"proposal identity collision: {proposal_id}")
            proposal = existing
        else:
            write_json(proposal_path, proposal)
        return proposal

    def _proposal(self, proposal_id: str) -> tuple[Path, dict[str, Any]]:
        if SLUG.fullmatch(proposal_id) is None:
            raise SkillEvolutionError(f"invalid proposal id: {proposal_id!r}")
        proposal_dir = self.storage / "proposals" / proposal_id
        proposal = load_json(proposal_dir / "proposal.json")
        validate(proposal, PROPOSAL_SCHEMA)
        expected_proposal_digest = digest_value(
            "proposal",
            {key: value for key, value in proposal.items() if key != "proposal_digest"},
        )
        if proposal["proposal_digest"] != expected_proposal_digest:
            raise SkillEvolutionError("proposal digest mismatch")
        if proposal["proposal_id"] != proposal_id:
            raise SkillEvolutionError("proposal id does not match its path")
        target_match = TARGET_SKILL.fullmatch(proposal["target_skill"])
        if target_match is None or target_match.group("name") != proposal["skill_name"]:
            raise SkillEvolutionError("proposal target does not match its skill name")
        expected_baseline = (
            proposal_dir / "baseline" / proposal["skill_name"]
        ).relative_to(self.root).as_posix()
        expected_candidate = (
            proposal_dir / "candidate" / proposal["skill_name"]
        ).relative_to(self.root).as_posix()
        if proposal["baseline_snapshot"] != expected_baseline:
            raise SkillEvolutionError("baseline snapshot path mismatch")
        if proposal["candidate_snapshot"] != expected_candidate:
            raise SkillEvolutionError("candidate snapshot path mismatch")
        for field, label in (
            ("baseline_snapshot", "baseline snapshot"),
            ("candidate_snapshot", "candidate snapshot"),
            ("target_skill", "target skill"),
        ):
            relative = Path(proposal[field])
            if confined_relative(self.root, relative, label) != relative:
                raise SkillEvolutionError(f"{label} must not traverse a symlink")
        evaluator_relative = Path(proposal["evaluator"]["path"])
        if confined_relative(self.root, evaluator_relative, "evaluator") != evaluator_relative:
            raise SkillEvolutionError("evaluator must not traverse a symlink")
        candidate_dir = self.root / proposal["candidate_snapshot"]
        candidate = candidate_dir / "SKILL.md"
        baseline = self.root / proposal["baseline_snapshot"] / "SKILL.md"
        if digest_value("skill", candidate.read_bytes()) != proposal["candidate_digest"]:
            raise SkillEvolutionError("candidate snapshot digest mismatch")
        if digest_value("skill", baseline.read_bytes()) != proposal["base_digest"]:
            raise SkillEvolutionError("baseline snapshot digest mismatch")
        evaluator = self.root / proposal["evaluator"]["path"]
        if digest_value("evaluator", evaluator.read_bytes()) != proposal["evaluator_digest"]:
            raise SkillEvolutionError("evaluator digest mismatch; prepare a new proposal")
        return proposal_dir, proposal

    def _validate_application(
        self,
        proposal: dict[str, Any],
        evaluation: dict[str, Any],
        approval: dict[str, Any],
        application: dict[str, Any],
    ) -> None:
        validate(application, APPLICATION_SCHEMA)
        expected_digest = digest_value(
            "application",
            {
                key: value
                for key, value in application.items()
                if key != "application_digest"
            },
        )
        if application["application_digest"] != expected_digest:
            raise SkillEvolutionError("application digest mismatch")
        expected = {
            "proposal_id": proposal["proposal_id"],
            "skill_name": proposal["skill_name"],
            "candidate_digest": proposal["candidate_digest"],
            "proposal_digest": proposal["proposal_digest"],
            "evaluation_digest": evaluation["evaluation_digest"],
            "approval_digest": approval["approval_digest"],
            "target_skill": proposal["target_skill"],
        }
        for field, value in expected.items():
            if application[field] != value:
                raise SkillEvolutionError(f"application {field} mismatch")

    def _active_application(
        self, proposal_id: str
    ) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        proposal_dir, proposal = self._proposal(proposal_id)
        evaluation = load_json(proposal_dir / "evaluation.json")
        approval = load_json(proposal_dir / "approval.json")
        application = load_json(proposal_dir / "application.json")
        self._validate_evaluation(proposal, evaluation)
        self._validate_approval(proposal, evaluation, approval)
        self._validate_application(proposal, evaluation, approval, application)
        target = self.root / proposal["target_skill"]
        current = target.read_bytes() if target.is_file() else b""
        if digest_value("skill", current) != proposal["candidate_digest"]:
            raise SkillEvolutionError("attributed proposal is not the active skill")
        return proposal_dir, proposal, application

    def _run_evaluator(self, proposal: dict[str, Any], skill_dir: Path) -> dict[str, Any]:
        evaluator = self.root / proposal["evaluator"]["path"]
        command = [
            str(evaluator),
            *proposal["evaluator"]["arguments"],
            "--skill-path",
            str(skill_dir),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                text=True,
                capture_output=True,
                check=False,
                timeout=proposal["evaluator"]["timeout_seconds"],
                env={**os.environ, "BRAIN_SKILL_EVAL": "1"},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SkillEvolutionError(f"evaluator failed to run: {exc}") from exc
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "no output"
            raise SkillEvolutionError(
                "evaluator exited "
                f"{completed.returncode}: {sanitize_text(message, self._private_terms())}"
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SkillEvolutionError(
                f"evaluator stdout is not one JSON object: {exc.msg}"
            ) from exc
        if not isinstance(result, dict):
            raise SkillEvolutionError("evaluator stdout JSON must be an object")
        result = sanitize(result, self._private_terms())
        validate(result, EVAL_RESULT_SCHEMA)
        case_ids = [case["id"] for case in result["cases"]]
        if len(case_ids) != len(set(case_ids)):
            raise SkillEvolutionError("evaluator case ids must be unique")
        return result

    def evaluate(self, proposal_id: str) -> dict[str, Any]:
        proposal_dir, proposal = self._proposal(proposal_id)
        output = proposal_dir / "evaluation.json"
        if output.exists():
            evaluation = load_json(output)
            self._validate_evaluation(proposal, evaluation)
            self._append_impact(
                f"- `{proposal_id}` gate `{evaluation['gate_status']}`: "
                f"{evaluation['baseline']['score']:.4f} → "
                f"{evaluation['candidate']['score']:.4f} "
                f"(delta {evaluation['score_delta']:+.4f}); "
                f"candidate `{proposal['candidate_digest']}`"
            )
            return evaluation
        baseline_dir = self.root / proposal["baseline_snapshot"]
        candidate_dir = self.root / proposal["candidate_snapshot"]
        baseline = self._run_evaluator(proposal, baseline_dir)
        candidate = self._run_evaluator(proposal, candidate_dir)
        baseline_passed = {
            case["id"] for case in baseline["cases"] if case["passed"]
        }
        candidate_by_id = {case["id"]: case for case in candidate["cases"]}
        regressions = sorted(
            case_id
            for case_id in baseline_passed
            if case_id not in candidate_by_id or not candidate_by_id[case_id]["passed"]
        )
        delta = round(candidate["score"] - baseline["score"], 12)
        gate_status = "accepted" if delta > 0 and not regressions else "rejected"
        evaluation = {
            "schema_version": 1,
            "kind": "skill-evaluation",
            "proposal_id": proposal_id,
            "skill_name": proposal["skill_name"],
            "base_digest": proposal["base_digest"],
            "candidate_digest": proposal["candidate_digest"],
            "proposal_digest": proposal["proposal_digest"],
            "evaluator_digest": proposal["evaluator_digest"],
            "baseline": baseline,
            "candidate": candidate,
            "score_delta": delta,
            "regressions": regressions,
            "gate_status": gate_status,
            "evaluated_at": self.clock(),
            "evaluation_digest": "",
        }
        evaluation["evaluation_digest"] = digest_value(
            "evaluation",
            {key: value for key, value in evaluation.items() if key != "evaluation_digest"},
        )
        validate(evaluation, EVALUATION_SCHEMA)
        write_json(output, evaluation)
        self._append_impact(
            f"- `{proposal_id}` gate `{gate_status}`: "
            f"{baseline['score']:.4f} → {candidate['score']:.4f} "
            f"(delta {delta:+.4f}); candidate `{proposal['candidate_digest']}`"
        )
        return evaluation

    def _validate_evaluation(
        self, proposal: dict[str, Any], evaluation: dict[str, Any]
    ) -> None:
        validate(evaluation, EVALUATION_SCHEMA)
        expected_digest = digest_value(
            "evaluation",
            {key: value for key, value in evaluation.items() if key != "evaluation_digest"},
        )
        if evaluation["evaluation_digest"] != expected_digest:
            raise SkillEvolutionError("evaluation digest mismatch")
        for field in (
            "proposal_id",
            "skill_name",
            "base_digest",
            "candidate_digest",
            "proposal_digest",
            "evaluator_digest",
        ):
            if evaluation[field] != proposal[field]:
                raise SkillEvolutionError(f"evaluation {field} mismatch")

    def _validate_approval(
        self,
        proposal: dict[str, Any],
        evaluation: dict[str, Any],
        approval: dict[str, Any],
    ) -> None:
        validate(approval, APPROVAL_SCHEMA)
        expected_digest = digest_value(
            "approval",
            {key: value for key, value in approval.items() if key != "approval_digest"},
        )
        if approval["approval_digest"] != expected_digest:
            raise SkillEvolutionError("approval digest mismatch")
        if approval["proposal_id"] != proposal["proposal_id"]:
            raise SkillEvolutionError("approval proposal id mismatch")
        if approval["skill_name"] != proposal["skill_name"]:
            raise SkillEvolutionError("approval skill name mismatch")
        if approval["candidate_digest"] != proposal["candidate_digest"]:
            raise SkillEvolutionError("approval candidate digest mismatch")
        if approval["proposal_digest"] != proposal["proposal_digest"]:
            raise SkillEvolutionError("approval proposal digest mismatch")
        if approval["evaluation_digest"] != evaluation["evaluation_digest"]:
            raise SkillEvolutionError("approval evaluation digest mismatch")

    def _append_impact(self, entry: str) -> None:
        path = self.storage / "wiki" / "skill-impact.md"
        if path.exists():
            text = path.read_text(encoding="utf-8")
        else:
            text = (
                "# Skill impact history\n\n"
                "Append-only outcomes for content-bound proposals.\n\n"
            )
        if entry not in text.splitlines():
            atomic_write(path, (text.rstrip() + "\n\n" + entry + "\n").encode("utf-8"))

    def approve(self, proposal_id: str, decision: str) -> dict[str, Any]:
        proposal_dir, proposal = self._proposal(proposal_id)
        evaluation = load_json(proposal_dir / "evaluation.json")
        self._validate_evaluation(proposal, evaluation)
        output = proposal_dir / "approval.json"
        if output.exists():
            existing = load_json(output)
            self._validate_approval(proposal, evaluation, existing)
            if existing["decision"] != decision:
                raise SkillEvolutionError("proposal already has a different human decision")
            self._append_impact(
                f"- `{proposal_id}` human decision `{decision}`"
            )
            return existing
        if decision == "accepted" and evaluation["gate_status"] != "accepted":
            raise SkillEvolutionError("human acceptance cannot override a rejected gate")
        candidate = self.root / proposal["candidate_snapshot"] / "SKILL.md"
        failures = guard_scan(self.root, [candidate], include_runtime_identity=True)
        if failures:
            raise SkillEvolutionError("candidate publication guard failed: " + "; ".join(failures))
        approval = {
            "schema_version": 1,
            "kind": "skill-approval",
            "proposal_id": proposal_id,
            "skill_name": proposal["skill_name"],
            "candidate_digest": proposal["candidate_digest"],
            "proposal_digest": proposal["proposal_digest"],
            "evaluation_digest": evaluation["evaluation_digest"],
            "producer": "human",
            "decision": decision,
            "candidate_guard": "passed",
            "approved_at": self.clock(),
            "approval_digest": "",
        }
        approval["approval_digest"] = digest_value(
            "approval",
            {key: value for key, value in approval.items() if key != "approval_digest"},
        )
        validate(approval, APPROVAL_SCHEMA)
        write_json(output, approval)
        self._append_impact(f"- `{proposal_id}` human decision `{decision}`")
        return approval

    def apply(self, proposal_id: str, confirm_digest: str) -> dict[str, Any]:
        proposal_dir, proposal = self._proposal(proposal_id)
        if confirm_digest != proposal["candidate_digest"]:
            raise SkillEvolutionError("confirmed digest does not match candidate")
        evaluation = load_json(proposal_dir / "evaluation.json")
        approval = load_json(proposal_dir / "approval.json")
        self._validate_evaluation(proposal, evaluation)
        self._validate_approval(proposal, evaluation, approval)
        if evaluation["gate_status"] != "accepted":
            raise SkillEvolutionError("proposal did not pass the score gate")
        if approval["decision"] != "accepted":
            raise SkillEvolutionError("proposal does not have human acceptance")
        target = self.root / proposal["target_skill"]
        application_path = proposal_dir / "application.json"
        if application_path.exists():
            application = load_json(application_path)
            self._validate_application(proposal, evaluation, approval, application)
            current = target.read_bytes() if target.is_file() else b""
            if digest_value("skill", current) == proposal["candidate_digest"]:
                self._append_impact(
                    f"- `{proposal_id}` applied to "
                    f"`{proposal['target_skill']}`; not committed"
                )
                return application
            raise SkillEvolutionError("application record exists but active skill differs")
        current = target.read_bytes() if target.is_file() else b""
        if digest_value("skill", current) != proposal["base_digest"]:
            raise SkillEvolutionError("active skill changed after proposal preparation")
        candidate = self.root / proposal["candidate_snapshot"] / "SKILL.md"
        candidate_bytes = candidate.read_bytes()
        failures = guard_scan(self.root, [candidate], include_runtime_identity=True)
        if failures:
            raise SkillEvolutionError("candidate publication guard failed: " + "; ".join(failures))
        existed = target.exists()
        atomic_write(target, candidate_bytes)
        full_failures = guard_scan(self.root, include_runtime_identity=True)
        if full_failures:
            if existed:
                atomic_write(target, current)
            else:
                target.unlink(missing_ok=True)
                try:
                    target.parent.rmdir()
                except OSError:
                    pass
            raise SkillEvolutionError(
                "publication guard failed; active skill rolled back: "
                + "; ".join(full_failures)
            )
        application = {
            "schema_version": 1,
            "kind": "skill-application",
            "proposal_id": proposal_id,
            "skill_name": proposal["skill_name"],
            "candidate_digest": proposal["candidate_digest"],
            "proposal_digest": proposal["proposal_digest"],
            "evaluation_digest": evaluation["evaluation_digest"],
            "approval_digest": approval["approval_digest"],
            "target_skill": proposal["target_skill"],
            "applied_at": self.clock(),
            "committed": False,
            "application_digest": "",
        }
        application["application_digest"] = digest_value(
            "application",
            {key: value for key, value in application.items() if key != "application_digest"},
        )
        try:
            validate(application, APPLICATION_SCHEMA)
            write_json(application_path, application)
        except (OSError, SkillEvolutionError) as exc:
            if existed:
                atomic_write(target, current)
            else:
                target.unlink(missing_ok=True)
                try:
                    target.parent.rmdir()
                except OSError:
                    pass
            raise SkillEvolutionError(
                f"could not record application; active skill rolled back: {exc}"
            ) from exc
        self._append_impact(
            f"- `{proposal_id}` applied to `{proposal['target_skill']}`; not committed"
        )
        return application

    def impact(self, proposal_id: str) -> dict[str, Any]:
        _proposal_dir, proposal, application = self._active_application(proposal_id)
        records = [
            record
            for record in self._evidence(proposal["skill_name"])
            if record.get("proposal_id") == proposal_id
        ]
        if not records:
            raise SkillEvolutionError(
                "post-application impact requires attributed task evidence"
            )
        outcomes: dict[str, str] = {}
        signal_tasks: dict[str, dict[str, set[str]]] = {}
        for record in records:
            task_id = record["task_id"]
            previous = outcomes.setdefault(task_id, record["outcome"])
            if previous != record["outcome"]:
                raise SkillEvolutionError(
                    f"attributed task has conflicting outcomes: {task_id}"
                )
            for signal in record["signals"]:
                kinds = signal_tasks.setdefault(
                    signal["key"], {"success": set(), "failure": set()}
                )
                kinds[signal["kind"]].add(task_id)
        passed_tasks = sum(outcome == "passed" for outcome in outcomes.values())
        failed_tasks = sum(outcome == "failed" for outcome in outcomes.values())
        evidence_ids = sorted(record["evidence_id"] for record in records)
        identity = {
            "proposal_id": proposal_id,
            "proposal_digest": proposal["proposal_digest"],
            "candidate_digest": proposal["candidate_digest"],
            "application_digest": application["application_digest"],
            "evidence_ids": evidence_ids,
        }
        impact_id = f"{proposal_id}-{digest_value('impact', identity)[7:19]}"
        impact = {
            "schema_version": 1,
            "kind": "skill-impact",
            "impact_id": impact_id,
            **identity,
            "task_count": len(outcomes),
            "passed_tasks": passed_tasks,
            "failed_tasks": failed_tasks,
            "pass_rate": round(passed_tasks / len(outcomes), 12),
            "signals": [
                {
                    "key": key,
                    "success_tasks": len(kinds["success"]),
                    "failure_tasks": len(kinds["failure"]),
                }
                for key, kinds in sorted(signal_tasks.items())
            ],
            "measured_at": self.clock(),
            "impact_digest": "",
        }
        impact["impact_digest"] = digest_value(
            "impact",
            {key: value for key, value in impact.items() if key != "impact_digest"},
        )
        validate(impact, IMPACT_SCHEMA)
        output = self.storage / "impacts" / proposal_id / f"{impact_id}.json"
        if output.exists():
            existing = load_json(output)
            validate(existing, IMPACT_SCHEMA)
            expected_digest = digest_value(
                "impact",
                {
                    key: value
                    for key, value in existing.items()
                    if key != "impact_digest"
                },
            )
            if existing["impact_digest"] != expected_digest:
                raise SkillEvolutionError("impact digest mismatch")
            impact = existing
        else:
            write_json(output, impact)
        self._append_impact(
            f"- `{proposal_id}` measured across {impact['task_count']} tasks: "
            f"pass rate {impact['pass_rate']:.4f}; impact `{impact_id}`"
        )
        return impact

    def rollback(self, proposal_id: str) -> dict[str, Any]:
        proposal_dir, proposal = self._proposal(proposal_id)
        evaluation = load_json(proposal_dir / "evaluation.json")
        approval = load_json(proposal_dir / "approval.json")
        self._validate_evaluation(proposal, evaluation)
        self._validate_approval(proposal, evaluation, approval)
        application = load_json(proposal_dir / "application.json")
        self._validate_application(proposal, evaluation, approval, application)
        output = proposal_dir / "rollback.json"
        if output.exists():
            rollback = load_json(output)
            validate(rollback, ROLLBACK_SCHEMA)
            expected_rollback_digest = digest_value(
                "rollback",
                {
                    key: value
                    for key, value in rollback.items()
                    if key != "rollback_digest"
                },
            )
            if rollback["rollback_digest"] != expected_rollback_digest:
                raise SkillEvolutionError("rollback digest mismatch")
            expected = {
                "proposal_id": proposal_id,
                "skill_name": proposal["skill_name"],
                "candidate_digest": proposal["candidate_digest"],
                "restored_digest": proposal["base_digest"],
                "application_digest": application["application_digest"],
                "target_skill": proposal["target_skill"],
            }
            for field, value in expected.items():
                if rollback[field] != value:
                    raise SkillEvolutionError(f"rollback {field} mismatch")
            target = self.root / proposal["target_skill"]
            current = target.read_bytes() if target.is_file() else b""
            if digest_value("skill", current) != proposal["base_digest"]:
                raise SkillEvolutionError("rollback record exists but active skill differs")
            self._append_impact(
                f"- `{proposal_id}` rolled back to `{proposal['base_digest']}`"
            )
            return rollback
        target = self.root / proposal["target_skill"]
        current = target.read_bytes() if target.is_file() else b""
        if digest_value("skill", current) != proposal["candidate_digest"]:
            raise SkillEvolutionError("active skill no longer matches applied candidate")
        baseline = self.root / proposal["baseline_snapshot"] / "SKILL.md"
        baseline_bytes = baseline.read_bytes()
        if baseline_bytes:
            atomic_write(target, baseline_bytes)
        else:
            target.unlink(missing_ok=True)
            try:
                target.parent.rmdir()
            except OSError:
                pass
        rollback = {
            "schema_version": 1,
            "kind": "skill-rollback",
            "proposal_id": proposal_id,
            "skill_name": proposal["skill_name"],
            "candidate_digest": proposal["candidate_digest"],
            "restored_digest": proposal["base_digest"],
            "application_digest": application["application_digest"],
            "target_skill": proposal["target_skill"],
            "rolled_back_at": self.clock(),
            "rollback_digest": "",
        }
        rollback["rollback_digest"] = digest_value(
            "rollback",
            {key: value for key, value in rollback.items() if key != "rollback_digest"},
        )
        validate(rollback, ROLLBACK_SCHEMA)
        write_json(output, rollback)
        self._append_impact(
            f"- `{proposal_id}` rolled back to `{proposal['base_digest']}`"
        )
        return rollback


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    subparsers = argument_parser.add_subparsers(dest="operation", required=True)

    validate_skill = subparsers.add_parser(
        "validate-skill", help="validate one or more repository skill files"
    )
    validate_skill.add_argument("skill_paths", type=Path, nargs="+")

    capture = subparsers.add_parser("capture", help="store one sanitized evidence record")
    capture.add_argument("--input", type=Path, required=True)

    consolidate = subparsers.add_parser(
        "consolidate", help="materialize patterns seen in multiple tasks"
    )
    consolidate.add_argument("--skill", required=True)
    consolidate.add_argument("--minimum-tasks", type=int, default=2)

    prepare = subparsers.add_parser(
        "prepare", help="snapshot one atomic skill proposal and its evaluator"
    )
    prepare.add_argument("--input", type=Path, required=True)

    evaluate = subparsers.add_parser(
        "evaluate", help="run baseline and candidate evaluations and gate the result"
    )
    evaluate.add_argument("--proposal-id", required=True)

    approve = subparsers.add_parser(
        "approve", help="record a content-bound explicit human decision"
    )
    approve.add_argument("--proposal-id", required=True)
    approve.add_argument("--decision", choices=("accepted", "rejected"), required=True)

    apply = subparsers.add_parser(
        "apply", help="apply an accepted candidate or leave the active skill unchanged"
    )
    apply.add_argument("--proposal-id", required=True)
    apply.add_argument("--confirm-digest", required=True)

    rollback = subparsers.add_parser(
        "rollback", help="restore the baseline from an applied proposal"
    )
    rollback.add_argument("--proposal-id", required=True)

    impact = subparsers.add_parser(
        "impact", help="summarize attributed post-application task evidence"
    )
    impact.add_argument("--proposal-id", required=True)
    return argument_parser


def main() -> int:
    args = parser().parse_args()
    if args.operation == "validate-skill":
        try:
            for skill_path in args.skill_paths:
                skill_file = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path
                validate_skill_text(skill_file.read_bytes(), skill_file.parent.name)
        except (OSError, SkillEvolutionError) as exc:
            print(f"skill validation error: {exc}", file=sys.stderr)
            return 1
        print(f"skill validation: {len(args.skill_paths)}/{len(args.skill_paths)} passed")
        return 0

    workspace = EvolutionWorkspace(ROOT)
    try:
        if args.operation == "capture":
            result = workspace.capture(args.input)
        elif args.operation == "consolidate":
            result = workspace.consolidate(args.skill, args.minimum_tasks)
        elif args.operation == "prepare":
            result = workspace.prepare(args.input)
        elif args.operation == "evaluate":
            result = workspace.evaluate(args.proposal_id)
        elif args.operation == "approve":
            result = workspace.approve(args.proposal_id, args.decision)
        elif args.operation == "apply":
            result = workspace.apply(args.proposal_id, args.confirm_digest)
        elif args.operation == "rollback":
            result = workspace.rollback(args.proposal_id)
        else:
            result = workspace.impact(args.proposal_id)
    except (OSError, SkillEvolutionError) as exc:
        print(f"skill evolution error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
