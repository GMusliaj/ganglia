from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import delegation


LIMITS = {
    "max_payload_bytes": 1_000_000,
    "max_output_bytes": 100_000,
    "timeout_seconds": 300,
    "max_worker_tokens": 200_000,
}
ROLES = ("bulk-reader", "code-writer")


def write_config(path: Path, role: str, **overrides: object) -> None:
    route = {
        "provider": "codex",
        "model_id": "fixture-model",
        "effort": "low",
        **overrides,
    }
    path.write_text(
        json.dumps({"version": 1, "roles": {role: route}}),
        encoding="utf-8",
    )


class DelegationRouteLimitTests(unittest.TestCase):
    def test_numeric_limit_boundaries_for_both_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "delegation.json"
            for role in ROLES:
                for field, ceiling in LIMITS.items():
                    for value in (1, ceiling):
                        with self.subTest(role=role, field=field, value=value):
                            write_config(config, role, **{field: value})
                            self.assertEqual(delegation.load_route(config, role)[field], value)
                    for value in (0, -1, ceiling + 1, True, 1.5):
                        with self.subTest(role=role, field=field, value=value):
                            write_config(config, role, **{field: value})
                            with self.assertRaises(delegation.DelegationError):
                                delegation.load_route(config, role)


if __name__ == "__main__":
    unittest.main()
