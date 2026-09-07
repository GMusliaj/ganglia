"""Shared serialization and errors for the delegation CLI and provider adapters."""

from __future__ import annotations

import json


class DelegationError(ValueError):
    """A bounded delegation failed validation; no answer should be accepted."""


def encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
