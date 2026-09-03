#!/usr/bin/env python3
"""Prepare, publish, and recall one content-bound Ganglia artifact bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from okf import parse


DOMAIN = b"ganglia-artifact-bundle-v1\0"
EVIDENCE_DOMAIN = b"ganglia-artifact-evidence-v1\0"
SHARED_FOLDERS = {
    "patterns",
    "lessons",
    "decisions",
    "concepts",
    "snippets",
    "sources",
    "infra",
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_SCHEMA = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "remember"
    / "schemas"
    / "artifact-candidate.schema.json"
)
RESULT_SCHEMA = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "remember"
    / "schemas"
    / "artifact-operation-result.schema.json"
)
TREE_RESULT_SCHEMA = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "remember"
    / "schemas"
    / "artifact-tree-validation-result.schema.json"
)
EVIDENCE_SCHEMA = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "remember"
    / "schemas"
    / "verification-evidence.schema.json"
)
APPROVAL_SCHEMA = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "remember"
    / "schemas"
    / "human-approval.schema.json"
)
REVIEW_STATE_SCHEMA = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "remember"
    / "schemas"
    / "review-state.schema.json"
)
MATCH_RESULT_SCHEMA = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "remember"
    / "schemas"
    / "artifact-match-result.schema.json"
)
TRACE_REQUEST_SCHEMA = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "remember"
    / "schemas"
    / "artifact-trace-request.schema.json"
)
TRACE_RESULT_SCHEMA = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "remember"
    / "schemas"
    / "artifact-trace-result.schema.json"
)
PROJECTION_FIELDS = (
    "artifact_id",
    "artifact_payload",
    "artifact_language",
    "artifact_runtime",
    "artifact_invocation",
    "artifact_working_directory",
    "artifact_dependencies",
    "artifact_arguments",
    "artifact_environment",
    "artifact_inputs",
    "artifact_outputs",
    "artifact_exit_behavior",
    "artifact_applicability",
    "artifact_safety",
    "artifact_mutation_default",
    "artifact_purpose",
    "artifact_focused_test_arguments",
    "artifact_focused_test_expected_stdout",
    "artifact_representative_run_arguments",
    "artifact_representative_run_expected_stdout",
)


class ArtifactError(ValueError):
    """A deterministic artifact-contract failure."""


@dataclass(frozen=True)
class BundlePlan:
    root: Path
    candidate: dict[str, Any]
    manifest_relative: Path
    payload_relative: Path
    payload_source: Path
    payload_bytes: bytes
    projection: dict[str, Any]
    bundle_digest: str
    verification: dict[str, Any]


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ArtifactError(f"cannot read JSON: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"invalid JSON: {path}:{exc.lineno}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"JSON root must be an object: {path}")
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
                errors.extend(
                    validate_value(item, item_contract, f"{field}[{index}]")
                )
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
            errors.extend(validate_value(value[name], contract, name))
    return errors


def validate_value(value: Any, schema: dict[str, Any], field: str) -> list[str]:
    return validate_scalar(value, schema, field)


def validate_against_schema(value: dict[str, Any], schema_path: Path) -> None:
    schema = load_json(schema_path)
    errors = validate_object(value, schema)
    if errors:
        raise ArtifactError("; ".join(errors))


def confined_relative(root: Path, value: Path, label: str) -> Path:
    if value.is_absolute():
        raise ArtifactError(f"{label} must be repository-relative: {value}")
    resolved = (root / value).resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ArtifactError(f"{label} escapes Ganglia root: {value}") from exc
    return relative


def privacy_layer(relative: Path) -> str:
    if not relative.parts:
        raise ArtifactError("artifact path is empty")
    if relative.parts[0] == "local":
        return "local"
    if relative.parts[0] in SHARED_FOLDERS:
        return "shared"
    raise ArtifactError(f"artifact path is outside a knowledge layer: {relative}")


def yaml_list(name: str, values: list[str]) -> list[str]:
    lines = [f"{name}:"]
    lines.extend(f"  - {value}" for value in values)
    return lines


def projection_from_candidate(
    candidate: dict[str, Any], payload_relative: Path
) -> dict[str, Any]:
    return {
        "artifact_id": candidate["artifact_id"],
        "artifact_payload": payload_relative.as_posix(),
        "artifact_language": candidate["language"],
        "artifact_runtime": candidate["runtime"],
        "artifact_invocation": candidate["invocation"],
        "artifact_working_directory": candidate["working_directory"],
        "artifact_dependencies": candidate["dependencies"],
        "artifact_arguments": candidate["arguments"],
        "artifact_environment": candidate["environment"],
        "artifact_inputs": candidate["inputs"],
        "artifact_outputs": candidate["outputs"],
        "artifact_exit_behavior": candidate["exit_behavior"],
        "artifact_applicability": candidate["applicability"],
        "artifact_safety": candidate["safety"],
        "artifact_mutation_default": candidate["mutation_default"],
        "artifact_purpose": candidate["purpose"],
        "artifact_focused_test_arguments": candidate["focused_test"]["arguments"],
        "artifact_focused_test_expected_stdout": candidate["focused_test"]["expected_stdout"],
        "artifact_representative_run_arguments": candidate["representative_run"]["arguments"],
        "artifact_representative_run_expected_stdout": candidate["representative_run"]["expected_stdout"],
    }


def lexical_tokens(*values: object) -> set[str]:
    return {
        token
        for value in values
        for token in re.findall(r"[a-z0-9]+", str(value).lower())
        if len(token) > 1
    }


def trace_artifact(request: dict[str, Any]) -> dict[str, Any]:
    """Classify materialization eligibility and select a natural runtime."""
    validate_against_schema(request, TRACE_REQUEST_SCHEMA)
    reason = "eligible"
    if not request["stable"]:
        reason = "unstable"
    elif not request["repeatable"]:
        reason = "not-repeatable"
    elif request["conceptual"] or request["one_off"] or request["checkpoint"]:
        reason = "non-operational"
    elif not all(
        request[field]
        for field in (
            "complete",
            "inputs_defined",
            "outputs_defined",
            "applicability_defined",
            "safety_defined",
        )
    ):
        reason = "incomplete-contract"

    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "artifact-trace-result",
        "eligible": reason == "eligible",
        "reason": reason,
    }
    if reason == "eligible":
        available = request["available_languages"]
        ecosystem = request["ecosystem"]
        if ecosystem != "generic" and ecosystem in available:
            result["language"] = ecosystem
        elif ecosystem == "generic":
            result["language"] = next(
                language
                for language in ("python", "javascript", "shell")
                if language in available
            )
        else:
            result["eligible"] = False
            result["reason"] = "ecosystem-runtime-unavailable"
    validate_against_schema(result, TRACE_RESULT_SCHEMA)
    return result


def artifact_match_result(
    root: Path,
    candidate: dict[str, Any],
    target_manifest: Path,
    semantic_candidates: list[Path] | None = None,
) -> dict[str, Any]:
    """Find an authoritative update target without making semantic judgments."""
    root = root.resolve()
    validate_against_schema(candidate, CANDIDATE_SCHEMA)
    target_relative = confined_relative(root, target_manifest, "manifest")
    target_layer = privacy_layer(target_relative)
    scope = "shared" if target_layer == "shared" else "local-and-shared"
    permitted_roots = sorted(SHARED_FOLDERS)
    if target_layer == "local":
        permitted_roots.append("local")

    semantic: set[Path] = set()
    for supplied in semantic_candidates or []:
        relative = confined_relative(root, supplied, "semantic candidate")
        if relative.parts and relative.parts[0] in permitted_roots:
            semantic.add(relative)

    query_tokens = lexical_tokens(
        candidate["artifact_id"],
        candidate["title"],
        candidate["description"],
        candidate["purpose"],
        *candidate["inputs"],
        *candidate["outputs"],
        *candidate["applicability"],
    )
    matches: list[dict[str, Any]] = []
    exact_count = 0
    for folder in permitted_roots:
        base = root / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.name == "index.md":
                continue
            document = parse(path)
            metadata = document.metadata
            artifact_id = metadata.get("artifact_id")
            if not isinstance(artifact_id, str) or not artifact_id:
                continue
            relative = path.relative_to(root)
            identity_match = artifact_id == candidate["artifact_id"]
            exact_count += int(identity_match)
            applicability_matches: list[str] = []
            for name, manifest_name, value in (
                ("language", "artifact_language", candidate["language"]),
                ("runtime", "artifact_runtime", candidate["runtime"]),
                ("safety", "artifact_safety", candidate["safety"]),
            ):
                if metadata.get(manifest_name) == value:
                    applicability_matches.append(name)
            for name, manifest_name, values in (
                ("inputs", "artifact_inputs", candidate["inputs"]),
                ("outputs", "artifact_outputs", candidate["outputs"]),
                ("applicability", "artifact_applicability", candidate["applicability"]),
            ):
                stored = metadata.get(manifest_name)
                if isinstance(stored, list) and set(stored) & set(values):
                    applicability_matches.append(name)
            stored_tokens = lexical_tokens(
                artifact_id,
                metadata.get("title", ""),
                metadata.get("description", ""),
                metadata.get("artifact_purpose", ""),
                *(metadata.get("artifact_inputs", []) or []),
                *(metadata.get("artifact_outputs", []) or []),
                *(metadata.get("artifact_applicability", []) or []),
            )
            lexical_score = (
                round(len(query_tokens & stored_tokens) / len(query_tokens | stored_tokens), 4)
                if query_tokens | stored_tokens
                else 0.0
            )
            semantic_candidate = relative in semantic
            if not (
                identity_match
                or semantic_candidate
                or lexical_score >= 0.35
                or len(applicability_matches) >= 4
            ):
                continue
            try:
                load_valid_manifest(root, relative)
            except ArtifactError:
                ready = False
            else:
                ready = True
            matches.append(
                {
                    "manifest": relative.as_posix(),
                    "artifact_id": artifact_id,
                    "identity_match": identity_match,
                    "applicability_matches": applicability_matches,
                    "lexical_score": lexical_score,
                    "semantic_candidate": semantic_candidate,
                    "ready": ready,
                }
            )

    matches.sort(
        key=lambda item: (
            not item["identity_match"],
            not item["ready"],
            not item["semantic_candidate"],
            -len(item["applicability_matches"]),
            -item["lexical_score"],
            item["manifest"],
        )
    )
    exact_ready = [
        item for item in matches if item["identity_match"] and item["ready"]
    ]
    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "artifact-match-result",
        "status": "no-match" if not matches else "ambiguous",
        "scope": scope,
        "query_artifact_id": candidate["artifact_id"],
        "candidates": matches,
    }
    if exact_count == 1 and len(exact_ready) == 1:
        result["status"] = "authoritative"
        result["selected_manifest"] = exact_ready[0]["manifest"]
    validate_against_schema(result, MATCH_RESULT_SCHEMA)
    return result


def validate_projection_contract(
    manifest_relative: Path, payload_relative: Path, projection: dict[str, Any]
) -> None:
    manifest_layer = privacy_layer(manifest_relative)
    payload_layer = privacy_layer(payload_relative)
    if manifest_layer != payload_layer:
        raise ArtifactError(
            f"artifact crosses privacy layers: {manifest_relative} -> {payload_relative}"
        )
    if manifest_relative.parent != payload_relative.parent:
        raise ArtifactError(
            f"artifact payload must be beside its manifest: {payload_relative}"
        )
    if manifest_relative.stem != payload_relative.stem:
        raise ArtifactError(
            f"artifact manifest and payload must share a stem: {manifest_relative.name} != {payload_relative.name}"
        )
    language = str(projection["artifact_language"])
    language_contracts = {
        "python": (".py", r"python(?:3)?(?:>=(\d+)\.(\d+))?"),
        "javascript": (".mjs", r"node(?:>=(\d+)\.(\d+))?"),
        "shell": (".sh", r"bash(?:>=(\d+)\.(\d+))?"),
    }
    if language not in language_contracts:
        raise ArtifactError(f"unsupported artifact language: {language}")
    extension, runtime_pattern = language_contracts[language]
    if payload_relative.suffix != extension:
        raise ArtifactError(
            f"{language} artifact payload must use {extension}: {payload_relative}"
        )
    if projection["artifact_working_directory"] != "ganglia-root":
        raise ArtifactError("artifact working directory must be ganglia-root")
    safety = projection["artifact_safety"]
    mutation_default = projection["artifact_mutation_default"]
    if safety == "read-only" and mutation_default != "read-only":
        raise ArtifactError("read-only artifact must have a read-only mutation default")
    if safety == "mutating":
        if mutation_default != "preview":
            raise ArtifactError("mutating artifact must default to preview")
        if "--preview" not in projection["artifact_invocation"]:
            raise ArtifactError("mutating artifact invocation must select --preview")
        for field in (
            "artifact_focused_test_arguments",
            "artifact_representative_run_arguments",
        ):
            if "--preview" not in projection[field]:
                raise ArtifactError(
                    f"mutating artifact {field} must select --preview"
                )
    if payload_relative.as_posix() not in projection["artifact_invocation"]:
        raise ArtifactError(
            f"artifact invocation must name its payload: {payload_relative}"
        )
    runtime = str(projection["artifact_runtime"])
    match = re.fullmatch(runtime_pattern, runtime)
    if not match:
        raise ArtifactError(f"unsupported {language} runtime constraint: {runtime}")
    if language == "python" and match.group(1):
        required = (int(match.group(1)), int(match.group(2)))
        current = (sys.version_info.major, sys.version_info.minor)
        if current < required:
            raise ArtifactError(
                f"artifact requires Python {required[0]}.{required[1]} or newer; current runtime is {current[0]}.{current[1]}"
            )
    for field in (
        "artifact_dependencies",
        "artifact_arguments",
        "artifact_environment",
        "artifact_inputs",
        "artifact_outputs",
        "artifact_exit_behavior",
        "artifact_applicability",
        "artifact_focused_test_arguments",
        "artifact_representative_run_arguments",
    ):
        values = projection[field]
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise ArtifactError(f"manifest field {field} must be a string list")


def digest_bundle(projection: dict[str, Any], payload: bytes) -> str:
    canonical = json.dumps(
        projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(DOMAIN)
    digest.update(canonical)
    digest.update(b"\0payload\0")
    digest.update(payload)
    return f"sha256:{digest.hexdigest()}"


def digest_evidence(evidence: dict[str, Any]) -> str:
    covered = {key: value for key, value in evidence.items() if key != "evidence_digest"}
    canonical = json.dumps(
        covered, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(EVIDENCE_DOMAIN)
    digest.update(canonical)
    return f"sha256:{digest.hexdigest()}"


def syntax_check_id(language: str) -> str:
    return f"{language}-syntax" if language != "shell" else "shell-syntax"


def runtime_prefix(language: str) -> list[str] | None:
    if language == "python":
        return [sys.executable]
    executable = shutil.which("node" if language == "javascript" else "bash")
    return [executable] if executable else None


def inspect_payload(payload_source: Path, language: str) -> dict[str, Any]:
    check_id = syntax_check_id(language)
    status = "failed"
    if language == "python":
        try:
            source = payload_source.read_text(encoding="utf-8")
            compile(source, payload_source.name, "exec")
        except (OSError, SyntaxError, UnicodeDecodeError):
            pass
        else:
            status = "passed"
    else:
        prefix = runtime_prefix(language)
        if prefix is None:
            status = "unavailable"
        else:
            flag = "--check" if language == "javascript" else "-n"
            try:
                result = subprocess.run(
                    [*prefix, flag, str(payload_source)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                status = "unavailable"
            else:
                status = "passed" if result.returncode == 0 else "failed"
    checks: list[dict[str, str]] = [{"id": check_id, "status": status}]

    checks.extend(
        {"id": check_id, "status": "authorization-blocked"}
        for check_id in ("help-output", "focused-test", "representative-run")
    )
    return {
        "status": "unverified",
        "verified_at": date.today().isoformat(),
        "checks": checks,
    }


def run_artifact_command(
    payload_source: Path,
    root: Path,
    language: str,
    arguments: list[str],
    expected_stdout: str | None,
) -> tuple[str, str]:
    prefix = runtime_prefix(language)
    if prefix is None:
        return "unavailable", f"{language} runtime was unavailable"
    try:
        result = subprocess.run(
            [*prefix, str(payload_source), *arguments],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return "unavailable", "Python command could not be started"
    except subprocess.TimeoutExpired:
        return "failed", "command timed out"
    if result.returncode != 0:
        return "failed", f"command exited {result.returncode}"
    if expected_stdout is None:
        if not result.stdout.strip():
            return "failed", "command returned empty standard output"
    elif result.stdout.rstrip("\n") != expected_stdout:
        return "failed", "standard output did not match the declared expectation"
    return "passed", "command exited zero with expected standard output"


def execute_artifact_verification(plan: BundlePlan) -> dict[str, Any]:
    language = plan.candidate["language"]
    syntax = inspect_payload(plan.payload_source, language)["checks"][0]
    checks = [syntax]
    help_status, _ = run_artifact_command(
        plan.payload_source, plan.root, language, ["--help"], None
    )
    checks.append({"id": "help-output", "status": help_status})
    for check_id, candidate_field in (
        ("focused-test", "focused_test"),
        ("representative-run", "representative_run"),
    ):
        contract = plan.candidate[candidate_field]
        status, _ = run_artifact_command(
            plan.payload_source,
            plan.root,
            language,
            contract["arguments"],
            contract["expected_stdout"],
        )
        checks.append({"id": check_id, "status": status})
    status = "verified" if all(check["status"] == "passed" for check in checks) else "unverified"
    return {
        "status": status,
        "verified_at": date.today().isoformat(),
        "checks": checks,
    }


def prepare_bundle(
    root: Path, candidate_path: Path, payload_source: Path, manifest: Path
) -> BundlePlan:
    root = root.resolve()
    candidate = load_json(candidate_path)
    validate_against_schema(candidate, CANDIDATE_SCHEMA)
    scalar_fields = (
        "artifact_id",
        "title",
        "description",
        "type",
        "date",
        "payload_name",
        "language",
        "runtime",
        "invocation",
        "working_directory",
        "safety",
        "mutation_default",
        "purpose",
    )
    rendered_values = [str(candidate[field]) for field in scalar_fields]
    rendered_values.extend(
        str(value)
        for field in (
            "tags",
            "dependencies",
            "arguments",
            "environment",
            "inputs",
            "outputs",
            "exit_behavior",
            "applicability",
        )
        for value in candidate[field]
    )
    rendered_values.extend(
        str(value)
        for field in ("focused_test", "representative_run")
        for value in (
            *candidate[field]["arguments"],
            candidate[field]["expected_stdout"],
        )
    )
    if any("\n" in value or "\r" in value for value in rendered_values):
        raise ArtifactError("artifact manifest values cannot contain newlines")
    manifest_relative = confined_relative(root, manifest, "manifest")
    if manifest_relative.suffix != ".md":
        raise ArtifactError("manifest must use a .md suffix")
    if manifest_relative.parts[0] not in SHARED_FOLDERS and manifest_relative.parts[0] != "local":
        raise ArtifactError("manifest must be in a shared knowledge folder or local/")
    payload_relative = confined_relative(
        root, manifest_relative.parent / candidate["payload_name"], "payload"
    )
    try:
        payload_bytes = payload_source.resolve().read_bytes()
    except OSError as exc:
        raise ArtifactError(f"cannot read payload source: {payload_source}: {exc}") from exc
    projection = projection_from_candidate(candidate, payload_relative)
    validate_projection_contract(manifest_relative, payload_relative, projection)
    bundle_digest = digest_bundle(projection, payload_bytes)
    verification = inspect_payload(payload_source.resolve(), candidate["language"])
    plan = BundlePlan(
        root=root,
        candidate=candidate,
        manifest_relative=manifest_relative,
        payload_relative=payload_relative,
        payload_source=payload_source.resolve(),
        payload_bytes=payload_bytes,
        projection=projection,
        bundle_digest=bundle_digest,
        verification=verification,
    )
    validate_against_schema(operation_result(plan, "prepare", False), RESULT_SCHEMA)
    return plan


def verification_summary(verification: dict[str, Any]) -> str:
    passed = [check["id"] for check in verification["checks"] if check["status"] == "passed"]
    if verification["status"] == "verified":
        return f"verified {verification['verified_at']} ({', '.join(passed)})"
    unresolved = [
        f"{check['id']} {check['status']}"
        for check in verification["checks"]
        if check["status"] != "passed"
    ]
    return f"unverified: {', '.join(unresolved)}"


def verification_evidence(plan: BundlePlan) -> dict[str, Any]:
    language = plan.candidate["language"]
    syntax_id = syntax_check_id(language)
    executable = {"python": "python3", "javascript": "node", "shell": "bash"}[language]
    result_by_id = {
        syntax_id: {
            "command": (
                "compile payload source in memory"
                if language == "python"
                else f"{executable} {'--check' if language == 'javascript' else '-n'} {plan.payload_relative.as_posix()}"
            ),
            "passed": "source compiled successfully",
            "failed": "source did not compile",
        },
        "help-output": {
            "command": f"{executable} {plan.payload_relative.as_posix()} --help",
        },
        "focused-test": {
            "command": f"{executable} "
            + plan.payload_relative.as_posix()
            + " "
            + " ".join(plan.candidate["focused_test"]["arguments"]),
        },
        "representative-run": {
            "command": f"{executable} "
            + plan.payload_relative.as_posix()
            + " "
            + " ".join(plan.candidate["representative_run"]["arguments"]),
        },
    }
    result_text = {
        "passed": "check ran and passed",
        "failed": "check ran and failed",
        "unavailable": "required runtime or command was unavailable",
        "authorization-blocked": "execution withheld until source review agreement",
    }
    checks = [
        {
            "id": check["id"],
            "status": check["status"],
            "command": result_by_id[check["id"]]["command"],
            "result": result_text[check["status"]],
        }
        for check in plan.verification["checks"]
    ]
    evidence = {
        "schema_version": 1,
        "kind": "verification-evidence",
        "id": f"{plan.candidate['artifact_id']}-evidence-{plan.bundle_digest[7:19]}",
        "producer": "artifact-bundle",
        "artifact_id": plan.candidate["artifact_id"],
        "bundle_digest": plan.bundle_digest,
        "evidence_digest": "",
        "generated_at": plan.verification["verified_at"],
        "runtime": plan.candidate["runtime"],
        "status": plan.verification["status"],
        "checks": checks,
    }
    evidence["evidence_digest"] = digest_evidence(evidence)
    validate_against_schema(evidence, EVIDENCE_SCHEMA)
    return evidence


def render_manifest(
    plan: BundlePlan,
    evidence: dict[str, Any],
    review_state: dict[str, Any],
    approval: dict[str, Any],
    superseded: str = "",
) -> str:
    candidate = plan.candidate
    projection = plan.projection
    lines = [
        "---",
        f"type: {candidate['type']}",
        f"title: {candidate['title']}",
        f"description: {candidate['description']}",
    ]
    lines.extend(yaml_list("tags", candidate["tags"]))
    lines.extend(
        [
            f"date: {candidate['date']}",
            f"artifact_id: {projection['artifact_id']}",
            f"artifact_payload: {projection['artifact_payload']}",
            f"artifact_language: {projection['artifact_language']}",
            f"artifact_runtime: {projection['artifact_runtime']}",
            f"artifact_invocation: {projection['artifact_invocation']}",
            f"artifact_working_directory: {projection['artifact_working_directory']}",
        ]
    )
    lines.extend(yaml_list("artifact_dependencies", projection["artifact_dependencies"]))
    lines.extend(yaml_list("artifact_arguments", projection["artifact_arguments"]))
    lines.extend(yaml_list("artifact_environment", projection["artifact_environment"]))
    lines.extend(yaml_list("artifact_inputs", projection["artifact_inputs"]))
    lines.extend(yaml_list("artifact_outputs", projection["artifact_outputs"]))
    lines.extend(yaml_list("artifact_exit_behavior", projection["artifact_exit_behavior"]))
    lines.extend(yaml_list("artifact_applicability", projection["artifact_applicability"]))
    lines.extend(
        yaml_list(
            "artifact_focused_test_arguments",
            projection["artifact_focused_test_arguments"],
        )
    )
    lines.extend(
        yaml_list(
            "artifact_representative_run_arguments",
            projection["artifact_representative_run_arguments"],
        )
    )
    lines.extend(
        [
            f"artifact_safety: {projection['artifact_safety']}",
            f"artifact_mutation_default: {projection['artifact_mutation_default']}",
            f"artifact_purpose: {projection['artifact_purpose']}",
            f"artifact_focused_test_expected_stdout: {projection['artifact_focused_test_expected_stdout']}",
            f"artifact_representative_run_expected_stdout: {projection['artifact_representative_run_expected_stdout']}",
            f"artifact_verification: {verification_summary(plan.verification)}",
            f"artifact_evidence: {plan.manifest_relative.with_suffix('.evidence.json').as_posix()}",
            f"artifact_evidence_digest: {evidence['evidence_digest']}",
            f"artifact_review: {plan.manifest_relative.with_suffix('.review.json').as_posix()}",
            f"artifact_review_id: {review_state['review_id']}",
            f"artifact_review_revision: {review_state['base_revision']}",
            f"artifact_approval: {plan.manifest_relative.with_suffix('.approval.json').as_posix()}",
            f"bundle_digest: {plan.bundle_digest}",
            "---",
            "",
            f"# {candidate['title']}",
            "",
            "## Active",
            "",
            candidate["purpose"],
            "",
            "### Usage",
            "",
            "```sh",
            candidate["invocation"],
            "```",
            "",
            f"Working directory: `{candidate['working_directory']}`.",
            "",
            "### Verification",
            "",
            f"- State: {verification_summary(plan.verification)}",
        ]
    )
    lines.extend(
        f"- {check['id']}: {check['status']}" for check in plan.verification["checks"]
    )
    if superseded:
        lines.extend(["", "## Superseded", "", superseded])
    lines.extend(
        [
            "",
            "## Source",
            "",
            "Materialized by the Ganglia remember workflow from an explicitly accepted artifact candidate.",
            "",
        ]
    )
    return "\n".join(lines)


def superseded_history(manifest_path: Path, metadata: dict[str, Any]) -> str:
    previous = (
        f"- `{metadata['bundle_digest']}`: "
        f"{metadata['artifact_purpose']}"
    )
    body = parse(manifest_path).body
    match = re.search(
        r"(?:^|\n)## Superseded\n+(.*?)(?=\n## [^#]|\Z)",
        body,
        flags=re.DOTALL,
    )
    if match and match.group(1).strip():
        return f"{previous}\n{match.group(1).strip()}"
    return previous


def operation_result(
    plan: BundlePlan,
    operation: str,
    written: bool,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = evidence or verification_evidence(plan)
    return {
        "schema_version": 1,
        "kind": "artifact-operation-result",
        "operation": operation,
        "artifact_id": plan.candidate["artifact_id"],
        "manifest": plan.manifest_relative.as_posix(),
        "payload": plan.payload_relative.as_posix(),
        "bundle_digest": plan.bundle_digest,
        "evidence_digest": evidence["evidence_digest"],
        "verification": plan.verification,
        "written": written,
    }


def validate_evidence(plan: BundlePlan, evidence: dict[str, Any]) -> None:
    validate_against_schema(evidence, EVIDENCE_SCHEMA)
    if digest_evidence(evidence) != evidence["evidence_digest"]:
        raise ArtifactError("verification evidence digest mismatch")
    for field, expected in (
        ("artifact_id", plan.candidate["artifact_id"]),
        ("bundle_digest", plan.bundle_digest),
        ("runtime", plan.candidate["runtime"]),
    ):
        if evidence[field] != expected:
            raise ArtifactError(f"verification evidence {field} does not match candidate")
    check_ids = [check["id"] for check in evidence["checks"]]
    if check_ids != [
        syntax_check_id(plan.candidate["language"]),
        "help-output",
        "focused-test",
        "representative-run",
    ]:
        raise ArtifactError("verification evidence checks are incomplete or out of order")
    computed_status = (
        "verified"
        if all(check["status"] == "passed" for check in evidence["checks"])
        else "unverified"
    )
    if evidence["status"] != computed_status:
        raise ArtifactError("verification evidence status does not match check results")


def verify_after_review(
    plan: BundlePlan, review_state: dict[str, Any]
) -> tuple[BundlePlan, dict[str, Any]]:
    validate_against_schema(review_state, REVIEW_STATE_SCHEMA)
    if not review_state["agreement"] or review_state["status"] != "agreement":
        raise ArtifactError("artifact review has not reached agreement")
    if review_state["blockers"] or review_state["missing_lenses"] or review_state["exhausted"]:
        raise ArtifactError("artifact review state is not ready for execution checks")
    for field, expected in (
        ("artifact_id", plan.candidate["artifact_id"]),
        ("bundle_digest", plan.bundle_digest),
    ):
        if review_state[field] != expected:
            raise ArtifactError(f"artifact review {field} does not match candidate")
    verified_plan = replace(plan, verification=execute_artifact_verification(plan))
    return verified_plan, verification_evidence(verified_plan)


def validate_review_and_approval(
    plan: BundlePlan,
    evidence: dict[str, Any],
    review_state: dict[str, Any],
    approval: dict[str, Any],
) -> None:
    validate_against_schema(review_state, REVIEW_STATE_SCHEMA)
    validate_against_schema(approval, APPROVAL_SCHEMA)
    if not review_state["agreement"] or review_state["status"] != "agreement":
        raise ArtifactError("artifact review has not reached agreement")
    if review_state["exhausted"] or review_state["blockers"] or review_state["missing_lenses"]:
        raise ArtifactError("artifact review state is not ready")
    identities = {
        "artifact_id": plan.candidate["artifact_id"],
        "bundle_digest": plan.bundle_digest,
    }
    for field, expected in identities.items():
        if review_state[field] != expected:
            raise ArtifactError(f"artifact review {field} does not match candidate")
        if approval[field] != expected:
            raise ArtifactError(f"human approval {field} does not match candidate")
    if review_state["evidence_digest"] not in ("none", evidence["evidence_digest"]):
        raise ArtifactError("artifact review evidence_digest does not match evidence")
    if approval["evidence_digest"] != evidence["evidence_digest"]:
        raise ArtifactError("human approval evidence_digest does not match evidence")
    if approval["decision"] != "accepted":
        raise ArtifactError("human approval decision is not accepted")
    if approval["review_id"] != review_state["review_id"]:
        raise ArtifactError("human approval review_id does not match review state")
    if approval["base_revision"] != review_state["base_revision"]:
        raise ArtifactError("human approval base_revision does not match review state")


def publish_bundle(
    root: Path,
    plan: BundlePlan,
    evidence: dict[str, Any],
    review_state: dict[str, Any],
    approval: dict[str, Any],
) -> dict[str, Any]:
    validate_evidence(plan, evidence)
    validate_review_and_approval(plan, evidence, review_state, approval)
    if evidence["status"] != "verified":
        raise ArtifactError("candidate is not verified; refusing to publish")
    final_verification = {
        "status": evidence["status"],
        "verified_at": evidence["generated_at"],
        "checks": [
            {"id": check["id"], "status": check["status"]}
            for check in evidence["checks"]
        ],
    }
    final_plan = replace(plan, verification=final_verification)
    manifest_path = root.resolve() / plan.manifest_relative
    payload_path = root.resolve() / plan.payload_relative
    evidence_path = root.resolve() / plan.manifest_relative.with_suffix(".evidence.json")
    review_path = root.resolve() / plan.manifest_relative.with_suffix(".review.json")
    approval_path = root.resolve() / plan.manifest_relative.with_suffix(".approval.json")
    bundle_paths = (manifest_path, payload_path, evidence_path, review_path, approval_path)
    existing = [path.exists() for path in bundle_paths]
    superseded = ""
    if any(existing) and not all(existing):
        raise ArtifactError("artifact target is incomplete; refusing unsafe update")
    if all(existing):
        old_metadata, old_payload_relative, _ = load_valid_manifest(
            root, plan.manifest_relative
        )
        if old_metadata["artifact_id"] != plan.candidate["artifact_id"]:
            raise ArtifactError("existing artifact_id does not match update candidate")
        if old_payload_relative != plan.payload_relative:
            raise ArtifactError("existing payload path does not match update candidate")
        if old_metadata["bundle_digest"] == plan.bundle_digest:
            raise ArtifactError("artifact update does not change bundle identity")
        superseded = superseded_history(manifest_path, old_metadata)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_bytes(plan.payload_bytes)
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    review_path.write_text(
        json.dumps(review_state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    approval_path.write_text(
        json.dumps(approval, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path.write_text(
        render_manifest(
            final_plan,
            evidence,
            review_state,
            approval,
            superseded=superseded,
        ),
        encoding="utf-8",
    )
    result = operation_result(final_plan, "publish", True, evidence)
    validate_against_schema(result, RESULT_SCHEMA)
    return result


def projection_from_manifest(metadata: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in PROJECTION_FIELDS if field not in metadata]
    if missing:
        raise ArtifactError(f"manifest missing artifact field(s): {', '.join(missing)}")
    projection = {field: metadata[field] for field in PROJECTION_FIELDS}
    for field in (
        "artifact_id",
        "artifact_payload",
        "artifact_language",
        "artifact_runtime",
        "artifact_invocation",
        "artifact_working_directory",
        "artifact_safety",
        "artifact_mutation_default",
        "artifact_purpose",
    ):
        if not isinstance(projection[field], str) or not projection[field]:
            raise ArtifactError(f"manifest field {field} must be a non-empty string")
    for field in (
        "artifact_dependencies",
        "artifact_arguments",
        "artifact_environment",
        "artifact_inputs",
        "artifact_outputs",
        "artifact_exit_behavior",
        "artifact_applicability",
        "artifact_focused_test_arguments",
        "artifact_representative_run_arguments",
    ):
        if not isinstance(projection[field], list) or not all(
            isinstance(value, str) and value for value in projection[field]
        ):
            raise ArtifactError(f"manifest field {field} must be a string list")
    for field in (
        "artifact_focused_test_expected_stdout",
        "artifact_representative_run_expected_stdout",
    ):
        if not isinstance(projection[field], str):
            raise ArtifactError(f"manifest field {field} must be a string")
    return projection


def load_valid_manifest(root: Path, manifest: Path) -> tuple[dict[str, Any], Path, bytes]:
    root = root.resolve()
    manifest_relative = confined_relative(root, manifest, "manifest")
    manifest_path = root / manifest_relative
    if not manifest_path.exists():
        raise ArtifactError(f"manifest does not exist: {manifest_relative}")
    metadata = parse(manifest_path).metadata
    projection = projection_from_manifest(metadata)
    payload_relative = confined_relative(root, Path(str(metadata["artifact_payload"])), "payload")
    validate_projection_contract(manifest_relative, payload_relative, projection)
    verification = str(metadata.get("artifact_verification", ""))
    if not re.fullmatch(
        r"(?:verified \d{4}-\d{2}-\d{2} \([a-z0-9,-]+(?: [a-z0-9,-]+)*\)|unverified: .+)",
        verification,
    ):
        raise ArtifactError("manifest field artifact_verification has invalid format")
    payload_path = root / payload_relative
    try:
        payload = payload_path.read_bytes()
    except OSError as exc:
        raise ArtifactError(f"cannot read payload: {payload_relative}: {exc}") from exc
    actual_digest = digest_bundle(projection, payload)
    expected_digest = str(metadata.get("bundle_digest", ""))
    if re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest) is None:
        raise ArtifactError("manifest field bundle_digest has invalid format")
    if actual_digest != expected_digest:
        raise ArtifactError(
            f"bundle digest mismatch for {manifest_relative}: expected {expected_digest or '<missing>'}, got {actual_digest}"
        )
    expected_sidecars = {
        "artifact_evidence": manifest_relative.with_suffix(".evidence.json"),
        "artifact_review": manifest_relative.with_suffix(".review.json"),
        "artifact_approval": manifest_relative.with_suffix(".approval.json"),
    }
    sidecars: dict[str, dict[str, Any]] = {}
    for field, expected in expected_sidecars.items():
        declared = metadata.get(field)
        if declared != expected.as_posix():
            raise ArtifactError(
                f"manifest field {field} must declare {expected.as_posix()}"
            )
        relative = confined_relative(root, Path(str(declared)), field)
        sidecars[field] = load_json(root / relative)
    evidence = sidecars["artifact_evidence"]
    review_state = sidecars["artifact_review"]
    approval = sidecars["artifact_approval"]
    validate_against_schema(evidence, EVIDENCE_SCHEMA)
    validate_against_schema(review_state, REVIEW_STATE_SCHEMA)
    validate_against_schema(approval, APPROVAL_SCHEMA)
    if digest_evidence(evidence) != evidence["evidence_digest"]:
        raise ArtifactError("persisted verification evidence digest mismatch")
    if metadata.get("artifact_evidence_digest") != evidence["evidence_digest"]:
        raise ArtifactError("manifest evidence digest does not match persisted evidence")
    for record_name, record in (
        ("verification evidence", evidence),
        ("human approval", approval),
    ):
        if record["artifact_id"] != metadata["artifact_id"]:
            raise ArtifactError(f"{record_name} artifact_id does not match manifest")
        if record["bundle_digest"] != expected_digest:
            raise ArtifactError(f"{record_name} bundle_digest does not match manifest")
        if record["evidence_digest"] != evidence["evidence_digest"]:
            raise ArtifactError(f"{record_name} evidence_digest does not match evidence")
    if review_state["artifact_id"] != metadata["artifact_id"]:
        raise ArtifactError("artifact review artifact_id does not match manifest")
    if review_state["bundle_digest"] != expected_digest:
        raise ArtifactError("artifact review bundle_digest does not match manifest")
    if review_state["evidence_digest"] not in ("none", evidence["evidence_digest"]):
        raise ArtifactError("artifact review evidence_digest does not match evidence")
    if evidence["status"] == "verified" and not verification.startswith("verified "):
        raise ArtifactError("manifest verification summary does not match evidence")
    if evidence["status"] != "verified" and not verification.startswith("unverified:"):
        raise ArtifactError("manifest verification summary does not match evidence")
    if not review_state["agreement"] or review_state["status"] != "agreement":
        raise ArtifactError("persisted artifact review has not reached agreement")
    if review_state["blockers"] or review_state["missing_lenses"] or review_state["exhausted"]:
        raise ArtifactError("persisted artifact review is not ready")
    if metadata.get("artifact_review_id") != review_state["review_id"]:
        raise ArtifactError("manifest review_id does not match persisted review")
    if str(metadata.get("artifact_review_revision")) != str(review_state["base_revision"]):
        raise ArtifactError("manifest review revision does not match persisted review")
    if approval["decision"] != "accepted":
        raise ArtifactError("persisted human approval is not accepted")
    if approval["review_id"] != review_state["review_id"]:
        raise ArtifactError("persisted approval review_id does not match review")
    if approval["base_revision"] != review_state["base_revision"]:
        raise ArtifactError("persisted approval revision does not match review")
    return metadata, payload_relative, payload


def recall_bundle(
    root: Path,
    manifest: Path,
    show_code: bool = False,
    context_language: str | None = None,
    context_runtime: str | None = None,
    applicability: list[str] | None = None,
) -> bytes:
    metadata, payload_relative, payload = load_valid_manifest(root, manifest)
    mismatch = ""
    if context_language and context_language != metadata["artifact_language"]:
        mismatch = (
            f"language requires {metadata['artifact_language']}, got {context_language}"
        )
    elif context_runtime and context_runtime != metadata["artifact_runtime"]:
        mismatch = f"runtime requires {metadata['artifact_runtime']}, got {context_runtime}"
    else:
        declared = set(metadata["artifact_applicability"])
        missing = sorted(set(applicability or []) - declared)
        if missing:
            mismatch = f"applicability excludes {', '.join(missing)}"
    if mismatch:
        return f"incompatible: {mismatch}; request adaptation separately\n".encode(
            "utf-8"
        )
    if show_code:
        return payload
    output = "\n".join(
        [
            payload_relative.as_posix(),
            str(metadata["artifact_invocation"]),
            str(metadata["artifact_verification"]),
            "Run this stored invocation now? [yes/no]",
        ]
    )
    return f"{output}\n".encode("utf-8")


def validate_shared_tree(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[dict[str, str]] = []
    declared_payloads: set[Path] = set()
    declared_sidecars: set[Path] = set()
    artifact_manifests: dict[str, Path] = {}
    manifest_count = 0

    for folder in sorted(SHARED_FOLDERS):
        base = root / folder
        if not base.exists():
            continue
        for manifest in sorted(base.rglob("*.md")):
            if manifest.name == "index.md":
                continue
            metadata = parse(manifest).metadata
            if "artifact_id" not in metadata and "bundle_digest" not in metadata:
                continue
            manifest_count += 1
            relative = manifest.relative_to(root)
            artifact_id = metadata.get("artifact_id")
            if isinstance(artifact_id, str) and artifact_id:
                previous = artifact_manifests.get(artifact_id)
                if previous is not None:
                    errors.append(
                        {
                            "path": relative.as_posix(),
                            "message": (
                                f"duplicate artifact_id {artifact_id!r}; "
                                f"already declared by {previous.as_posix()}"
                            ),
                        }
                    )
                else:
                    artifact_manifests[artifact_id] = relative
            declared = metadata.get("artifact_payload")
            if declared:
                candidate_path = (root / str(declared)).resolve()
                try:
                    candidate_path.relative_to(root)
                except ValueError:
                    pass
                else:
                    declared_payloads.add(candidate_path)
            for field in ("artifact_evidence", "artifact_review", "artifact_approval"):
                declared_sidecar = metadata.get(field)
                if not declared_sidecar:
                    continue
                candidate_path = (root / str(declared_sidecar)).resolve()
                try:
                    candidate_path.relative_to(root)
                except ValueError:
                    pass
                else:
                    declared_sidecars.add(candidate_path)
            try:
                load_valid_manifest(root, relative)
            except ArtifactError as exc:
                errors.append({"path": relative.as_posix(), "message": str(exc)})

    payload_count = 0
    for folder in sorted(SHARED_FOLDERS):
        base = root / folder
        if not base.exists():
            continue
        for payload in sorted(base.rglob("*.py")):
            payload_count += 1
            if payload.resolve() not in declared_payloads:
                errors.append(
                    {
                        "path": payload.relative_to(root).as_posix(),
                        "message": "orphaned artifact payload has no declaring manifest",
                    }
                )

        for pattern in ("*.evidence.json", "*.review.json", "*.approval.json"):
            for sidecar in sorted(base.rglob(pattern)):
                if sidecar.resolve() not in declared_sidecars:
                    errors.append(
                        {
                            "path": sidecar.relative_to(root).as_posix(),
                            "message": "orphaned artifact attestation has no declaring manifest",
                        }
                    )

    result = {
        "schema_version": 1,
        "kind": "artifact-tree-validation-result",
        "status": "invalid" if errors else "valid",
        "manifests": manifest_count,
        "payloads": payload_count,
        "errors": errors,
    }
    validate_against_schema(result, TREE_RESULT_SCHEMA)
    return result


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    trace = commands.add_parser("trace")
    trace.add_argument("--request", type=Path, required=True)
    match = commands.add_parser("match")
    match.add_argument("--root", type=Path, default=PROJECT_ROOT)
    match.add_argument("--candidate", type=Path, required=True)
    match.add_argument("--manifest", type=Path, required=True)
    match.add_argument("--semantic-candidate", type=Path, action="append", default=[])
    prepare = commands.add_parser("prepare")
    add_common_arguments(prepare)
    prepare.add_argument("--evidence-output", type=Path, required=True)
    verify = commands.add_parser("verify")
    add_common_arguments(verify)
    verify.add_argument("--review-state", type=Path, required=True)
    verify.add_argument("--evidence-output", type=Path, required=True)
    publish = commands.add_parser("publish")
    add_common_arguments(publish)
    publish.add_argument("--evidence", type=Path, required=True)
    publish.add_argument("--review-state", type=Path, required=True)
    publish.add_argument("--approval", type=Path, required=True)
    recall = commands.add_parser("recall")
    recall.add_argument("--root", type=Path, default=PROJECT_ROOT)
    recall.add_argument("--manifest", type=Path, required=True)
    recall.add_argument("--show-code", action="store_true")
    recall.add_argument(
        "--context-language", choices=("python", "javascript", "shell")
    )
    recall.add_argument("--context-runtime")
    recall.add_argument("--applicability", action="append", default=[])
    validate_tree = commands.add_parser("validate-tree")
    validate_tree.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    try:
        if args.command == "trace":
            result = trace_artifact(load_json(args.request))
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "match":
            candidate = load_json(args.candidate)
            result = artifact_match_result(
                args.root,
                candidate,
                args.manifest,
                args.semantic_candidate,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "recall":
            sys.stdout.buffer.write(
                recall_bundle(
                    args.root,
                    args.manifest,
                    args.show_code,
                    args.context_language,
                    args.context_runtime,
                    args.applicability,
                )
            )
            return 0
        if args.command == "validate-tree":
            result = validate_shared_tree(args.root)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["status"] == "valid" else 1
        plan = prepare_bundle(args.root, args.candidate, args.payload, args.manifest)
        if args.command == "prepare":
            evidence = verification_evidence(plan)
            args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
            args.evidence_output.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = operation_result(plan, "prepare", False)
        elif args.command == "verify":
            review_state = load_json(args.review_state)
            verified_plan, evidence = verify_after_review(plan, review_state)
            args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
            args.evidence_output.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = operation_result(verified_plan, "verify", False, evidence)
        else:
            evidence = load_json(args.evidence)
            review_state = load_json(args.review_state)
            approval = load_json(args.approval)
            result = publish_bundle(
                args.root, plan, evidence, review_state, approval
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ArtifactError as exc:
        print(f"artifact error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
