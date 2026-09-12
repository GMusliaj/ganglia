#!/usr/bin/env python3
"""Private source preservation for the canonical remember workflow; preview by default."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

MAX_BYTES = 32 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()


def confined(root: Path, relative: str) -> Path:
    path = root / relative
    if path.resolve() != path.absolute() or not path.is_relative_to(root):
        raise ValueError("symlinks and escaping paths are not allowed")
    return path


def validate_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("invalid source or revision identifier")
    return value


def store_path(root: Path, source: str, revision: str) -> Path:
    return confined(root, f"local/raw/{validate_id(source)}/{validate_id(revision)}.json")


def immutable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("immutable source conflict")
        return
    # Publish a complete file atomically without replacing a concurrent writer.
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError("immutable source conflict") from None
    finally:
        temporary.unlink()


def capture(root: Path, *, origin: str, source_id: str, privacy: str,
            payload: bytes | None = None, locator: str | None = None,
            external_revision: str | None = None, allow_plaintext: bool = False,
            apply: bool = False) -> dict:
    if not origin.strip() or not source_id.strip():
        raise ValueError("origin and source identity are required")
    if privacy not in {"private", "restricted"}:
        raise ValueError("raw sources are always private or restricted")
    if payload is not None:
        if locator is not None or external_revision is not None:
            raise ValueError("choose payload or external reference, not both")
        if privacy == "restricted" or not allow_plaintext:
            raise ValueError("plaintext storage requires private classification and explicit consent; restricted originals stay in their protected source")
        if len(payload) > MAX_BYTES:
            raise ValueError("source exceeds 32 MiB limit")
        content = {"mode": "local-bytes", "sha256": digest(payload), "bytes": len(payload)}
    else:
        if not locator or not external_revision:
            raise ValueError("external sources require locator and immutable revision")
        content = {"mode": "external-reference", "locator": locator,
                   "external_revision": external_revision, "availability": "unverified"}
    source = digest(encoded([origin, source_id]))
    record = {"schema_version": 1, "origin": origin, "source_id": source_id,
              "privacy": privacy, "content": content}
    revision = digest(encoded(record))
    path = store_path(root, source, revision)
    data = encoded(record)
    if apply:
        if payload is not None:
            immutable_write(path.with_suffix(".bin"), payload)
        immutable_write(path, data)
    return {"source": source, "revision": revision,
            "manifest": path.relative_to(root).as_posix(),
            "state": "captured" if apply else "preview", "mode": content["mode"]}


def inspect(root: Path, source: str, revision: str) -> dict:
    path = store_path(root, source, revision)
    record = json.loads(path.read_bytes())
    if digest(encoded(record)) != revision or digest(encoded([record["origin"], record["source_id"]])) != source:
        raise ValueError("source manifest integrity failed")
    content = record["content"]
    if content["mode"] == "local-bytes":
        data = confined(root, path.with_suffix(".bin").relative_to(root).as_posix()).read_bytes()
        if digest(data) != content["sha256"] or len(data) != content["bytes"]:
            raise ValueError("source payload integrity failed")
    elif content["mode"] != "external-reference":
        raise ValueError("unknown storage mode")
    return record


def receipt(root: Path, source: str, revision: str, outcome: str,
            entries: list[str], apply: bool = False) -> dict:
    inspect(root, source, revision)
    if outcome not in {"compiled", "no-knowledge"}:
        raise ValueError("unknown processing outcome")
    if (outcome == "compiled") != bool(entries):
        raise ValueError("compiled requires entries; no-knowledge requires none")
    outputs = []
    for relative in sorted(set(entries)):
        parts = Path(relative).parts
        if len(parts) < 3 or parts[0] != "local" or parts[1] not in {"notes", "projects"} or Path(relative).suffix != ".md" or ".." in parts:
            raise ValueError("raw-source compilation outputs must be private local knowledge")
        path = confined(root, relative)
        outputs.append({"path": relative, "sha256": digest(path.read_bytes())})
    record = {"schema_version": 1, "source": source, "revision": revision,
              "outcome": outcome, "outputs": outputs}
    receipt_id = digest(encoded(record))
    path = confined(root, f"local/raw/receipts/{receipt_id}.json")
    if apply:
        immutable_write(path, encoded(record))
    return {"receipt": path.relative_to(root).as_posix(), "state": "recorded" if apply else "preview"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("capture")
    add.add_argument("--origin", required=True)
    add.add_argument("--source-id", required=True)
    add.add_argument("--privacy", choices=["private", "restricted"], default="restricted")
    add.add_argument("--input", type=Path)
    add.add_argument("--locator")
    add.add_argument("--external-revision")
    add.add_argument("--allow-plaintext", action="store_true")
    add.add_argument("--apply", action="store_true")
    show = commands.add_parser("inspect")
    done = commands.add_parser("receipt")
    for command in (show, done):
        command.add_argument("--source", required=True)
        command.add_argument("--revision", required=True)
    done.add_argument("--outcome", choices=["compiled", "no-knowledge"], required=True)
    done.add_argument("--entry", action="append", default=[])
    done.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "capture":
            payload = None
            if args.input:
                if args.privacy != "private" or not args.allow_plaintext:
                    raise ValueError("restricted input must remain external; plaintext consent is required before reading")
                with args.input.open("rb") as stream:
                    payload = stream.read(MAX_BYTES + 1)
            result = capture(root, origin=args.origin, source_id=args.source_id,
                             privacy=args.privacy, payload=payload, locator=args.locator,
                             external_revision=args.external_revision,
                             allow_plaintext=args.allow_plaintext, apply=args.apply)
        elif args.command == "inspect":
            record = inspect(root, args.source, args.revision)
            result = {"source": args.source, "revision": args.revision,
                      "privacy": record["privacy"], "mode": record["content"]["mode"],
                      "integrity": "verified" if record["content"]["mode"] == "local-bytes" else "manifest-only"}
        else:
            result = receipt(root, args.source, args.revision, args.outcome, args.entry, args.apply)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        # Do not echo paths, raw content, or arbitrary metadata on errors.
        parser.exit(2, "error: source operation rejected; check privacy consent, identifiers, integrity, and local paths\n")


if __name__ == "__main__":
    raise SystemExit(main())
