from __future__ import annotations

import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import delegation
import delegation_codex
import delegation_hook


ROUTE = delegation.DEFAULTS | {"provider": "codex", "model_id": "fixture-model", "effort": "low"}


def host_accepts(value: dict) -> bool:
    """Independent current Codex hook-output subset, from the host docs.

    Deliberately doesn't import the hook serializer. Legacy forms are excluded
    so a regression to issue #10 cannot be blessed by our own implementation.
    """
    if value == {}:
        return True
    if set(value) != {"hookSpecificOutput"}:
        return False
    specific = value["hookSpecificOutput"]
    if not isinstance(specific, dict) or specific.get("hookEventName") != "PreToolUse":
        return False
    if set(specific) == {"hookEventName", "additionalContext"}:
        return isinstance(specific["additionalContext"], str)
    return (set(specific) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
            and specific["permissionDecision"] == "deny"
            and isinstance(specific["permissionDecisionReason"], str)
            and bool(specific["permissionDecisionReason"]))


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for name, count in {"small.txt": 100, "boundary.txt": 350, "over.txt": 351,
                            "big.txt": 800, "big file.txt": 800, "half.txt": 200,
                            "half2.txt": 200, "AGENTS.md": 900}.items():
            (self.root / name).write_text("line\n" * count)
        (self.root / "minified.js").write_text("x" * 200_000)
        (self.root / "unreadable.txt").write_text("line\n" * 900)
        (self.root / "unreadable.txt").chmod(0)
        (self.root / "nested").mkdir()
        (self.root / "nested" / "big.txt").write_text("line\n" * 800)
        self.config = self.root / "routing.json"
        self.config.write_text(json.dumps({"version": 1, "roles": {role: ROUTE for role in delegation.ROLES}}))


class RoutingTests(Workspace):
    def hook_result(self, command, *, max_lines=350, max_bytes=50_000):
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.root), "tool_input": {"command": command}}
        process = subprocess.run(
            [sys.executable, str(ROOT / "bin/delegation_hook.py"), "--mode", "enforce",
             "--max-lines", str(max_lines), "--max-bytes", str(max_bytes)],
            input=json.dumps(event), text=True, capture_output=True, timeout=5, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        value = json.loads(process.stdout)
        self.assertTrue(host_accepts(value), value)
        return value.get("hookSpecificOutput", {}).get("permissionDecision")

    def test_quoted_bracket_filename_is_checked(self):
        route = self.root / "app/[id]/page.tsx"
        route.parent.mkdir(parents=True)
        route.write_text("line\n" * 800)
        self.assertEqual(self.hook_result("cat 'app/[id]/page.tsx'"), "deny")

    def test_quoted_escaped_and_unquoted_globs_stay_distinct(self):
        for folder, lines in (("[id]", 800), ("i", 100)):
            route = self.root / "app" / folder / "page.tsx"
            route.parent.mkdir(parents=True)
            route.write_text("line\n" * lines)
        for command, expected in (
            ('cat "app/[id]/page.tsx"', "deny"),
            (r"cat app/\[id\]/page.tsx", "deny"),
            ("cat app/'[id]'/page.tsx", "deny"),
            ("cat 'app/[id]/'*.tsx", "deny"),
            ("cd 'app/[id]' && cat *.tsx", "deny"),
            ("cat app/[id]/page.tsx", None),
            ("head -n 10 'app/[id]/page.tsx'", None),
        ):
            with self.subTest(command=command):
                self.assertEqual(self.hook_result(command), expected)

    def test_quoted_star_and_question_mark_are_literal_filenames(self):
        (self.root / "literal*.txt").write_text("line\n" * 100)
        (self.root / "literal?.txt").write_text("line\n" * 100)
        (self.root / "literalX.txt").write_text("line\n" * 800)
        for command, expected in (
            ("cat 'literal*.txt'", None),
            (r"cat literal\*.txt", None),
            ('cat "literal?.txt"', None),
            ("cat literal*.txt", "deny"),
            ("cat literal?.txt", "deny"),
        ):
            with self.subTest(command=command):
                self.assertEqual(self.hook_result(command), expected)

    def test_byte_count_reads_still_enforce_line_budget(self):
        for command in ("head -c 4000 big.txt", "tail -c 4000 big.txt"):
            with self.subTest(command=command):
                self.assertEqual(self.hook_result(command), "deny")

    def test_byte_slices_respect_exact_line_and_byte_boundaries(self):
        for command, max_bytes, expected in (
            ("head -c 1750 big.txt", 50_000, None),
            ("tail -c 1750 big.txt", 50_000, None),
            ("head -c 1751 big.txt", 50_000, "deny"),
            ("tail -c 1751 big.txt", 50_000, "deny"),
            ("head -c 0 big.txt", 50_000, None),
            ("tail -c 0 big.txt", 50_000, None),
            ("head -c 100 minified.js", 100, None),
            ("tail -c 101 minified.js", 100, "deny"),
            ("cat big.txt | head -c 4000", 50_000, "deny"),
        ):
            with self.subTest(command=command):
                self.assertEqual(self.hook_result(command, max_bytes=max_bytes), expected)

    def test_byte_counts_measure_the_selected_end_of_the_file(self):
        (self.root / "mixed-bytes.txt").write_text("line\n" * 800 + "x" * 4000)
        self.assertEqual(self.hook_result("head -c 4000 mixed-bytes.txt"), "deny")
        self.assertIsNone(self.hook_result("tail -c 4000 mixed-bytes.txt"))

    def test_byte_counts_aggregate_lines_across_files(self):
        self.assertEqual(self.hook_result("head -c 1000 half.txt half2.txt"), "deny")

    def test_schema_rejects_issue10_output(self):
        self.assertFalse(host_accepts({"decision": "allow"}))
        self.assertFalse(host_accepts({"decision": "block", "reason": "test"}))

    def test_observe_never_denies(self):
        output = delegation_hook.hook_output(True, "large read", "observe")
        self.assertTrue(host_accepts(output))
        self.assertNotIn("permissionDecision", output["hookSpecificOutput"])

    def test_read_limits(self):
        for values, expected in [({}, True), ({"offset": 0}, True), ({"limit": 0}, True),
                                 ({"limit": 20}, False), ({"offset": 100, "limit": 20}, False),
                                 ({"limit": 500}, True), ({"limit": False}, True)]:
            with self.subTest(values=values):
                event = {"tool_name": "Read", "cwd": str(self.root), "tool_input": {"file_path": "big.txt", **values}}
                self.assertEqual(delegation_hook.assess(event)[0], expected)

    def test_tool_workdir(self):
        event = {"tool_name": "exec_command", "cwd": "/", "tool_input": {"cmd": "cat big.txt", "workdir": str(self.root)}}
        self.assertTrue(delegation_hook.assess(event)[0])

    def test_big_file_small_slice(self):
        (self.root / "long.txt").write_text("small line\n" * 20_000)
        for command in ("head -n 10 long.txt", "tail -n 10 long.txt", "sed -n '50,60p' long.txt"):
            with self.subTest(command=command):
                self.assertFalse(delegation_hook.assess({"tool_name": "Bash", "cwd": str(self.root), "tool_input": {"command": command}})[0])

    def test_pipeline_does_not_measure_wrong_end_of_file(self):
        (self.root / "mixed.txt").write_text("x" * 100_000 + "\n" + "small\n" * 100)
        event = {"tool_name": "Bash", "cwd": str(self.root), "tool_input": {"command": "head -n 1 mixed.txt | tail -n 1"}}
        self.assertTrue(delegation_hook.assess(event)[0])

    def test_hook_cli_contract(self):
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.root), "tool_input": {"command": "cat big.txt"}}
        process = subprocess.run([sys.executable, str(ROOT / "bin/delegation_hook.py"), "--mode", "enforce"], input=json.dumps(event), text=True, capture_output=True, timeout=5, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        value = json.loads(process.stdout)
        self.assertTrue(host_accepts(value))
        self.assertEqual(value["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_bad_event_blocks(self):
        process = subprocess.run([sys.executable, str(ROOT / "bin/delegation_hook.py")], input="not JSON", text=True, capture_output=True, timeout=5, check=False)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")

    def test_hook_registration(self):
        hook = json.loads((ROOT / "hooks/delegation.json").read_text())["hooks"]["PreToolUse"][0]
        self.assertIn("Bash", hook["matcher"])
        self.assertIn("--mode observe", hook["hooks"][0]["command"])
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", hook["hooks"][0]["command"])


def routing_case(case):
    def test(self):
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.root), "tool_input": {"command": case["command"]}}
        denied, reason = delegation_hook.assess(event)
        self.assertEqual(denied, case["deny"], case["command"])
        self.assertTrue(host_accepts(delegation_hook.hook_output(denied, reason, "enforce")))
    return test


for _case in json.loads((ROOT / "evals/delegation/routing-cases.json").read_text())["cases"]:
    setattr(RoutingTests, "test_case_" + _case["id"].replace("-", "_"), routing_case(_case))


class WrapperTests(Workspace):
    def result(self, **updates):
        return {"provider": "codex", "model_id": ROUTE["model_id"], "role": "bulk-reader",
                "model_evidence": "codex-thread-start-and-no-reroute", "text": "small.txt:1: line",
                "usage": {"input_tokens": 100, "cached_input_tokens": 50, "output_tokens": 20}, **updates}

    def cli(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["delegation", "--config", str(self.config), "--root", str(self.root), *args]), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            status = delegation.main()
        return status, stdout.getvalue(), stderr.getvalue()

    def cli_subprocess(self, args):
        # Only an optional fixture worker is discoverable; never use real Codex.
        return subprocess.run(
            [sys.executable, str(ROOT / "bin/delegation.py"), "--config", str(self.config),
             "--root", str(self.root), *args],
            cwd=self.root, env=os.environ | {"PATH": str(self.root / "worker-bin")},
            text=True, capture_output=True, timeout=8, check=False)

    def test_real_cli_preserves_missing_worker_error(self):
        process = self.cli_subprocess(["--execute", "bulk-read", "--question", "what?", "--paths", "small.txt"])
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, "")
        self.assertEqual(process.stderr, "delegation error: Codex CLI is unavailable\n")

    def test_real_cli_preserves_model_reroute_and_timeout_errors(self):
        worker = self.root / "worker-bin/codex"
        worker.parent.mkdir()
        # Emulate only the external JSONL peer. Both CLI and adapter run normally.
        peer = '''
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if behavior == "timeout" or request["method"] == "initialized":
        continue
    if behavior == "reroute":
        print(json.dumps({"method": "model/rerouted", "params": {}}), flush=True)
        behavior = "timeout"
        continue
    if request["method"] == "initialize":
        result = {}
    elif request["method"] == "model/list":
        result = {"data": [], "nextCursor": None}
    else:
        raise ValueError("unexpected fixture request")
    print(json.dumps({"id": request["id"], "result": result}), flush=True)
'''
        route = ROUTE | {"timeout_seconds": 2}
        self.config.write_text(json.dumps({"version": 1, "roles": {role: route for role in delegation.ROLES}}))
        for behavior, reason in (
            ("missing-model", "configured model is absent from the local provider catalog"),
            ("reroute", "worker reported a reroute, error, or configuration warning; answer discarded"),
            ("timeout", "worker deadline exceeded; no retry was made"),
        ):
            with self.subTest(behavior=behavior):
                worker.write_text(f"#!{sys.executable}\nbehavior = {behavior!r}\n" + peer)
                worker.chmod(0o700)
                process = self.cli_subprocess(["--execute", "code-write", "--spec", "draft", "--reference", "small.txt", "--target", "draft.py"])
                self.assertEqual(process.returncode, 1)
                self.assertEqual(process.stdout, "")
                self.assertEqual(process.stderr, f"delegation error: {reason}\n")
                self.assertFalse((self.root / "draft.py").exists())

    def test_real_cli_keeps_local_filesystem_errors_sanitized(self):
        process = self.cli_subprocess(["bulk-read", "--question", "what?", "--paths", "missing.txt"])
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, "")
        self.assertEqual(process.stderr, "delegation error: local file or configuration operation failed\n")

    def test_preview_makes_no_call(self):
        with patch.object(delegation_codex, "invoke") as worker:
            status, out, _ = self.cli(["bulk-read", "--question", "what?", "--paths", "small.txt"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["calls"], 0)
        worker.assert_not_called()
        self.assertNotIn("line\n", out)

    def test_reader_receives_physical_line_labels_but_writer_receives_source(self):
        raw = b"first\r\n\r\nlast\xe2\x80\xa8part"
        (self.root / "numbered.txt").write_bytes(raw)
        read = delegation.prepare(self.root, "bulk-reader", "cite lines", ["numbered.txt"], ROUTE)
        write = delegation.prepare(self.root, "code-writer", "draft", ["numbered.txt"], ROUTE)
        self.assertEqual(read["payload"]["files"][0]["text"], "1: first\r\n2: \r\n3: last\u2028part")
        self.assertEqual(write["payload"]["files"][0]["text"], raw.decode())
        self.assertEqual(read["source_bytes"], len(raw))
        self.assertEqual(read["payload"]["files"][0]["sha256"], hashlib.sha256(raw).hexdigest())

    def test_line_labels_respect_final_newlines_and_the_serialized_budget(self):
        (self.root / "numbered.txt").write_text("first\n\n")
        request = delegation.prepare(self.root, "bulk-reader", "cite", ["numbered.txt"], ROUTE)
        self.assertEqual(request["payload"]["files"][0]["text"], "1: first\n2: ")
        with self.assertRaisesRegex(delegation.DelegationError, "serialized input"):
            delegation.prepare(self.root, "bulk-reader", "cite", ["numbered.txt"], ROUTE | {"max_payload_bytes": request["payload_bytes"] - 1})

    def test_status_distinguishes_configuration_from_execution(self):
        before = self.config.read_bytes()
        with patch.object(delegation, "shutil") as commands, patch.object(delegation_codex, "invoke") as worker:
            commands.which.return_value = "/example/codex"
            status = delegation.local_status(self.config, self.root, self.root / "skills", self.root / "codex")
        worker.assert_not_called()
        self.assertTrue(status["local_prerequisites_ready"])
        self.assertFalse(status["global_prerequisites_ready"])
        self.assertEqual(status["model_calls"], 0)
        self.assertEqual(status["live_execution"], "unverified")
        self.assertIsNone(status["money_saved"])
        self.assertEqual(status["hook_files_present"], {"project": False, "user": False})
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.root / "skills").exists())
        self.assertFalse((self.root / "codex").exists())

    def test_status_requires_both_routes_and_a_cli(self):
        self.config.write_text(json.dumps({"version": 1, "roles": {"bulk-reader": ROUTE}}))
        with patch.object(delegation.shutil, "which", return_value="/example/codex"):
            status = delegation.local_status(self.config, self.root, self.root / "skills", self.root / "codex")
        self.assertFalse(status["local_prerequisites_ready"])
        self.assertTrue(status["roles"]["bulk-reader"]["configured"])
        self.assertFalse(status["roles"]["code-writer"]["configured"])
        with patch.object(delegation.shutil, "which", return_value=None):
            status = delegation.local_status(self.config, self.root, self.root / "skills", self.root / "codex")
        self.assertFalse(status["codex_cli_available"])
        self.assertFalse(status["local_prerequisites_ready"])

    def test_status_checks_global_link_targets_not_just_presence(self):
        skills = self.root / "skills"
        skills.mkdir()
        for role in delegation.ROLES:
            (skills / role).symlink_to(ROOT / ".agents/skills" / role, target_is_directory=True)
        with patch.object(delegation.shutil, "which", return_value="/example/codex"):
            status = delegation.local_status(self.config, self.root, skills, self.root / "codex")
            self.assertTrue(status["global_prerequisites_ready"])
            (skills / "bulk-reader").unlink()
            (skills / "bulk-reader").symlink_to(self.root / "missing", target_is_directory=True)
            status = delegation.local_status(self.config, self.root, skills, self.root / "codex")
        self.assertFalse(status["global_prerequisites_ready"])
        self.assertEqual(status["roles"]["bulk-reader"]["global_install"], "conflict")

    def test_status_does_not_claim_hook_activation_from_a_file(self):
        (self.root / ".codex").mkdir()
        (self.root / ".codex/hooks.json").write_text("{}")
        status = delegation.local_status(self.config, self.root, self.root / "skills", self.root / "codex")
        self.assertTrue(status["hook_files_present"]["project"])
        self.assertTrue(status["hook_activation"].startswith("unverified"))

    def test_status_real_cli_has_no_model_or_source_dependency(self):
        process = self.cli_subprocess(["status"])
        self.assertEqual(process.returncode, 1)  # Fixture PATH contains no Codex.
        self.assertEqual(process.stderr, "")
        status = json.loads(process.stdout)
        self.assertEqual(status["model_calls"], 0)
        self.assertFalse(status["local_prerequisites_ready"])
        self.assertNotIn("source_bytes", status)

    def test_diagnostic_commands_reject_execute(self):
        with patch.object(delegation_codex, "available_models") as catalog, patch.object(delegation_codex, "invoke") as worker:
            for command in ("status", "models"):
                status, out, _ = self.cli(["--execute", command])
                self.assertEqual(status, 1)
                self.assertEqual(out, "")
        catalog.assert_not_called()
        worker.assert_not_called()

    def test_cli_one_call_and_usage(self):
        with patch.object(delegation_codex, "invoke", return_value=self.result()) as worker:
            status, out, err = self.cli(["--execute", "bulk-read", "--question", "what?", "--paths", "small.txt"])
        self.assertEqual(status, 0, err)
        self.assertEqual(out.strip(), self.result()["text"])
        worker.assert_called_once()
        self.assertEqual(json.loads(err)["money_saved"], None)
        self.assertEqual(json.loads(err)["worker_usage"]["input_tokens"], 100)
        self.assertEqual(set(worker.call_args.args[0]), {"role", "task", "files"})

    def test_no_retry_and_no_target_after_failure(self):
        with patch.object(delegation_codex, "invoke", side_effect=delegation.DelegationError("failed")) as worker:
            status, out, _ = self.cli(["--execute", "code-write", "--spec", "draft", "--reference", "small.txt", "--target", "draft.py"])
        self.assertEqual(status, 1)
        self.assertEqual(out, "")
        self.assertFalse((self.root / "draft.py").exists())
        worker.assert_called_once()

    def test_no_target_clobber_or_call(self):
        original = (self.root / "small.txt").read_bytes()
        with patch.object(delegation_codex, "invoke") as worker:
            status, _, _ = self.cli(["--execute", "code-write", "--spec", "draft", "--reference", "small.txt", "--target", "small.txt"])
        self.assertEqual(status, 1)
        worker.assert_not_called()
        self.assertEqual((self.root / "small.txt").read_bytes(), original)

    def test_new_target_and_internal_fences(self):
        draft = '```python\ntext = """\n```example\nx\n```\n"""\n```'
        with patch.object(delegation_codex, "invoke", return_value=self.result(role="code-writer", text=draft)):
            status, _, err = self.cli(["--execute", "code-write", "--spec", "draft", "--reference", "small.txt", "--target", "draft.py"])
        self.assertEqual(status, 0, err)
        self.assertEqual((self.root / "draft.py").read_text(), 'text = """\n```example\nx\n```\n"""\n')

    def test_source_context_supplied_and_deduplicated(self):
        with patch.object(delegation_codex, "invoke", return_value=self.result(role="code-writer")) as worker:
            status, _, err = self.cli(["--execute", "code-write", "--spec", "draft", "--reference", "small.txt", "--context", "big.txt", "small.txt"])
        self.assertEqual(status, 0, err)
        self.assertEqual(len(worker.call_args.args[0]["files"]), 2)

    def test_missing_or_invalid_route(self):
        for config in ({}, {"version": 1, "roles": {}}, {"version": 1, "roles": {"bulk-reader": ROUTE | {"provider": "unknown"}}}, {"version": 1, "roles": {"bulk-reader": ROUTE | {"model_id": "EXAMPLE_MODEL_ID"}}}, {"version": 1, "roles": {"bulk-reader": ROUTE | {"timeout_seconds": True}}}):
            with self.subTest(config=config):
                self.config.write_text(json.dumps(config))
                with self.assertRaises(delegation.DelegationError):
                    delegation.load_route(self.config, "bulk-reader")

    def test_malformed_route_types_fail_cleanly(self):
        for config in ({"version": True, "roles": {"bulk-reader": ROUTE}},
                       {"version": 1, "roles": {"bulk-reader": ROUTE | {"effort": []}}}):
            with self.subTest(config=config):
                self.config.write_text(json.dumps(config))
                status, _, err = self.cli(["bulk-read", "--question", "what?", "--paths", "small.txt"])
                self.assertEqual(status, 1, err)

    def test_empty_fenced_draft_is_not_written(self):
        with patch.object(delegation_codex, "invoke", return_value=self.result(role="code-writer", text="```python\n```")):
            status, _, _ = self.cli(["--execute", "code-write", "--spec", "draft", "--reference", "small.txt", "--target", "draft.py"])
        self.assertEqual(status, 1)
        self.assertFalse((self.root / "draft.py").exists())

    def test_path_boundaries(self):
        (self.root / "escape.txt").symlink_to(self.root.parent)
        for name in ("../outside", "/absolute/file", "escape.txt/anything", ".env", ".codex/auth.json"):
            with self.subTest(name=name), self.assertRaises(delegation.DelegationError):
                delegation.source_path(self.root, name)

    def test_private_symlink_inside_root(self):
        (self.root / ".codex").mkdir()
        (self.root / ".codex/auth.json").write_text("EXAMPLE_NOT_A_SECRET")
        (self.root / "alias.txt").symlink_to(self.root / ".codex/auth.json")
        with self.assertRaises(delegation.DelegationError):
            delegation.prepare(self.root, "bulk-reader", "what?", ["alias.txt"], ROUTE)

    def test_payload_and_binary_limits(self):
        (self.root / "binary.txt").write_bytes(b"\0")
        for name, route in [("binary.txt", ROUTE), ("small.txt", ROUTE | {"max_payload_bytes": 10}), ("small.txt", ROUTE | {"max_payload_bytes": 510})]:
            with self.subTest(name=name, route=route), self.assertRaises(delegation.DelegationError):
                delegation.prepare(self.root, "bulk-reader", "what?", [name], route)

    def test_digest_binds_question_and_contents(self):
        one = delegation.prepare(self.root, "bulk-reader", "what?", ["small.txt"], ROUTE)
        two = delegation.prepare(self.root, "bulk-reader", "why?", ["small.txt"], ROUTE)
        (self.root / "small.txt").write_text("changed")
        three = delegation.prepare(self.root, "bulk-reader", "what?", ["small.txt"], ROUTE)
        self.assertEqual(len({one["digest"], two["digest"], three["digest"]}), 3)

    def test_invalid_answers(self):
        for updates in ({"model_id": "other-model"}, {"role": "other-role"}, {"provider": "other-provider"}, {"model_evidence": None}, {"text": ""}, {"text": "x" * 13_000}, {"usage": None}, {"usage": {"input_tokens": 1, "cached_input_tokens": 2, "output_tokens": 1}}):
            with self.subTest(updates=updates), self.assertRaises(delegation.DelegationError):
                delegation.validate_result(self.result(**updates), ROUTE, "bulk-reader")

    def test_cost_counts_worker_cached_and_output(self):
        usage = {"input_tokens": 1_000_000, "cached_input_tokens": 500_000, "output_tokens": 100_000}
        self.assertEqual(delegation.estimate_cost(usage, {"input": 2, "cached_input": 1, "output": 5}), 2)
        with self.assertRaises(delegation.DelegationError):
            delegation.estimate_cost(usage, {"input": float("nan"), "cached_input": 1, "output": 5})


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.skills = self.root / "skills"
        self.prompts = self.root / "prompts"

    def install(self):
        return subprocess.run(
            ["/bin/bash", str(ROOT / "scripts/install-codex-commands.sh")],
            cwd=self.root, env=os.environ | {"GANGLIA_SKILL_DIR": str(self.skills),
                                             "GANGLIA_PROMPT_DIR": str(self.prompts)},
            capture_output=True, text=True, timeout=5, check=False)

    def test_all_six_skills_install_without_activating_workers(self):
        process = self.install()
        self.assertEqual(process.returncode, 0, process.stderr)
        roles = {"remember", "recall", "fafo", "skill-evolution", "bulk-reader", "code-writer"}
        self.assertEqual({path.name for path in self.skills.iterdir()}, roles)
        for role in roles:
            self.assertTrue((self.skills / role).is_symlink())
            self.assertEqual((self.skills / role).resolve(), ROOT / ".agents/skills" / role)
        self.assertEqual({path.name for path in self.prompts.iterdir()}, {"remember.md", "recall.md"})
        # No configuration, hooks, or other state is created in the target tree.
        self.assertEqual({path.name for path in self.root.iterdir()}, {"skills", "prompts"})

    def test_reinstallation_preserves_link_identity(self):
        self.assertEqual(self.install().returncode, 0)
        before = {path.name: path.lstat().st_ino for path in self.skills.iterdir()}
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual({path.name: path.lstat().st_ino for path in self.skills.iterdir()}, before)

    def test_conflicting_worker_is_not_overwritten(self):
        self.skills.mkdir()
        existing = self.skills / "bulk-reader"
        existing.mkdir()
        marker = existing / "SKILL.md"
        marker.write_text("Existing skill; preserve this file.\n")
        process = self.install()
        self.assertEqual(process.returncode, 1)
        self.assertEqual(marker.read_text(), "Existing skill; preserve this file.\n")
        self.assertFalse(existing.is_symlink())
        self.assertIn("Refusing to overwrite existing command path", process.stderr)


class FakeRpc:
    serial = 0

    def __init__(self):
        self.calls = []
        self.catalog = {"data": [{"model": "fixture-model", "supportedReasoningEfforts": [{"reasoningEffort": "low"}]}], "nextCursor": None}
        self.config = {"config": {}}
        self.thread = {"model": "fixture-model", "modelProvider": "openai", "approvalPolicy": "never", "sandbox": {"type": "readOnly"}, "thread": {"id": "fixture-thread", "ephemeral": True}}
        self.events = [
            {"id": 1, "result": {"turn": {"id": "fixture-turn"}}},
            {"method": "thread/tokenUsage/updated", "params": {"threadId": "fixture-thread", "tokenUsage": {"total": {"totalTokens": 120, "inputTokens": 100, "cachedInputTokens": 0, "outputTokens": 20}}}},
            {"method": "item/completed", "params": {"threadId": "fixture-thread", "item": {"id": "answer", "type": "agentMessage", "text": "small.txt:1: line"}}},
            {"method": "turn/completed", "params": {"threadId": "fixture-thread", "turn": {"id": "fixture-turn", "status": "completed"}}},
        ]

    def call(self, method, params):
        self.calls.append((method, params))
        return {"initialize": {}, "model/list": self.catalog, "config/read": self.config, "thread/start": self.thread}[method]

    def send(self, message):
        self.calls.append((message["method"], message["params"]))

    def receive(self):
        return self.events.pop(0)


class AdapterTests(unittest.TestCase):
    def run_fake(self, rpc):
        return delegation_codex.run_turn(rpc, {"role": "bulk-reader", "task": "what?", "files": []}, ROUTE, "Read only", Path(tempfile.gettempdir()))

    def test_single_ephemeral_pinned_turn(self):
        rpc = FakeRpc()
        result = self.run_fake(rpc)
        self.assertEqual(result["model_id"], ROUTE["model_id"])
        self.assertEqual(len([c for c in rpc.calls if c[0] == "turn/start"]), 1)
        start = next(c[1] for c in rpc.calls if c[0] == "thread/start")
        self.assertFalse(start["allowProviderModelFallback"])
        self.assertEqual(start["environments"], [])
        self.assertTrue(start["ephemeral"])

    def test_missing_model_stops_before_turn(self):
        rpc = FakeRpc()
        rpc.catalog["data"] = []
        with self.assertRaises(delegation.DelegationError):
            self.run_fake(rpc)
        self.assertNotIn("turn/start", [c[0] for c in rpc.calls])

    def test_catalog_probe_never_starts_a_thread_or_turn(self):
        rpc = FakeRpc()
        with patch.object(delegation_codex.shutil, "which", return_value="/example/codex"), patch.object(delegation_codex, "Rpc", return_value=rpc), patch.object(rpc, "close", create=True) as close:
            models = delegation_codex.available_models()
        self.assertEqual(models, [{"model_id": "fixture-model", "efforts": ["low"]}])
        self.assertEqual([method for method, _ in rpc.calls], ["initialize", "initialized", "model/list"])
        close.assert_called_once()

    def test_catalog_pagination_is_complete_and_bounded(self):
        rpc = FakeRpc()
        with patch.object(rpc, "call", side_effect=[
            {"data": [{"model": "first"}], "nextCursor": "page-two"},
            {"data": [{"model": "second"}], "nextCursor": None},
        ]) as call:
            self.assertEqual(delegation_codex.model_catalog(rpc), [{"model": "first"}, {"model": "second"}])
            self.assertEqual(call.call_args.args[1]["cursor"], "page-two")
        with patch.object(rpc, "call", return_value={"data": [], "nextCursor": "loop"}) as call:
            with self.assertRaisesRegex(delegation.DelegationError, "page budget"):
                delegation_codex.model_catalog(rpc)
            self.assertEqual(call.call_count, 10)

    def test_malformed_catalog_is_not_reported_as_available(self):
        for page in ({"data": [None]}, {"data": [] , "nextCursor": 1}, {"data": {}}):
            with self.subTest(page=page), patch.object(FakeRpc, "call", return_value=page):
                with self.assertRaises(delegation.DelegationError):
                    delegation_codex.model_catalog(FakeRpc())

    def test_configured_tools_disabled_without_persistent_mutation(self):
        rpc = FakeRpc()
        rpc.config = {"config": {"mcp_servers": {"fixture.server": {"command": "fixture-worker", "tool_timeout_sec": None, "enabled": True}}, "plugins": {"fixture@market": {"enabled": True}}}}
        before = json.loads(json.dumps(rpc.config))
        self.run_fake(rpc)
        config = next(params["config"] for method, params in rpc.calls if method == "thread/start")
        self.assertEqual(config["mcp_servers"], {"fixture.server": {"enabled": False}})
        self.assertEqual(config["plugins"], {"fixture@market": {"enabled": False}})
        self.assertEqual(rpc.config, before)
        self.assertFalse(config["features.shell_tool"])
        self.assertEqual(config["web_search"], "disabled")
        self.assertFalse(any(method.startswith("config/") and method != "config/read" for method, _ in rpc.calls))

    def test_missing_config_stops_before_turn(self):
        rpc = FakeRpc()
        rpc.config = {}
        with self.assertRaises(delegation.DelegationError):
            self.run_fake(rpc)
        self.assertNotIn("turn/start", [c[0] for c in rpc.calls])

    def test_commentary_is_not_prepended_to_code(self):
        rpc = FakeRpc()
        rpc.events.insert(2, {"method": "item/completed", "params": {"threadId": "fixture-thread", "item": {"id": "progress", "type": "agentMessage", "phase": "commentary", "text": "I will inspect this."}}})
        rpc.events[3]["params"]["item"].update(phase="final_answer", text="print(1)")
        self.assertEqual(self.run_fake(rpc)["text"], "print(1)")

    def test_other_turn_usage_discarded(self):
        rpc = FakeRpc()
        rpc.events[1]["params"]["turnId"] = "other-turn"
        with self.assertRaises(delegation.DelegationError):
            self.run_fake(rpc)

    def test_mismatched_model_stops_before_turn(self):
        rpc = FakeRpc()
        rpc.thread["model"] = "wrong-model"
        with self.assertRaises(delegation.DelegationError):
            self.run_fake(rpc)
        self.assertNotIn("turn/start", [c[0] for c in rpc.calls])

    def test_tools_and_failed_turns_rejected(self):
        for kind in ("commandExecution", "fileChange", "mcpToolCall", "collabToolCall"):
            rpc = FakeRpc()
            rpc.events[2]["params"]["item"]["type"] = kind
            with self.subTest(kind=kind), self.assertRaises(delegation.DelegationError):
                self.run_fake(rpc)
        rpc = FakeRpc()
        rpc.events[-1]["params"]["turn"]["status"] = "failed"
        with self.assertRaises(delegation.DelegationError):
            self.run_fake(rpc)

    def test_usage_budget(self):
        rpc = FakeRpc()
        rpc.events[1]["params"]["tokenUsage"]["total"]["totalTokens"] = 999_999
        with self.assertRaisesRegex(delegation.DelegationError, "observed 999999, limit 80000"):
            self.run_fake(rpc)

    def test_missing_usage_is_not_reported_as_a_budget_overrun(self):
        rpc = FakeRpc()
        del rpc.events[1]["params"]["tokenUsage"]["total"]["totalTokens"]
        with self.assertRaisesRegex(delegation.DelegationError, "missing an integer totalTokens"):
            self.run_fake(rpc)

    def test_real_stdio_roundtrip_without_inference(self):
        # An independent executable peer exercises framing, large stdin writes,
        # notification races and process cleanup, not just mocked method calls.
        server = r'''
import json
import sys

def send(value):
    print(json.dumps(value), flush=True)

initialized = False
turns = 0
for line in sys.stdin:
    message = json.loads(line)
    method = message["method"]
    params = message.get("params", {})
    if method == "initialized":
        initialized = True
        continue
    if method == "initialize":
        result = {}
    elif method == "model/list":
        assert initialized
        result = {"data": [{"model": "fixture-model", "supportedReasoningEfforts": [{"reasoningEffort": "low"}]}]}
    elif method == "config/read":
        result = {"config": {}}
    elif method == "thread/start":
        assert params["model"] == "fixture-model"
        assert params["modelProvider"] == "openai"
        assert params["allowProviderModelFallback"] is False
        assert params["ephemeral"] is True
        assert params["approvalPolicy"] == "never"
        assert params["sandbox"] == "read-only"
        assert params["environments"] == []
        assert params["config"]["features.shell_tool"] is False
        result = {"model": "fixture-model", "modelProvider": "openai", "approvalPolicy": "never", "sandbox": {"type": "readOnly"}, "thread": {"id": "fixture-thread", "ephemeral": True}}
    elif method == "turn/start":
        turns += 1
        assert turns == 1
        payload = json.loads(params["input"][0]["text"])
        assert set(payload) == {"role", "task", "files"}
        assert len(payload["files"][0]["text"]) == 100_000
        # Deliver usage before the request result, a permitted notification race.
        send({"method": "thread/tokenUsage/updated", "params": {"threadId": "fixture-thread", "turnId": "fixture-turn", "tokenUsage": {"total": {"totalTokens": 110, "inputTokens": 100, "cachedInputTokens": 0, "outputTokens": 10}}}})
        send({"id": message["id"], "result": {"turn": {"id": "fixture-turn"}}})
        send({"method": "item/completed", "params": {"threadId": "fixture-thread", "turnId": "fixture-turn", "item": {"id": "answer", "type": "agentMessage", "phase": "final_answer", "text": "fixture.txt:1: result"}}})
        send({"method": "turn/completed", "params": {"threadId": "fixture-thread", "turn": {"id": "fixture-turn", "status": "completed"}}})
        continue
    else:
        raise ValueError("unexpected method")
    send({"id": message["id"], "result": result})
'''
        rpc = delegation_codex.Rpc([sys.executable, "-u", "-c", server], Path(tempfile.gettempdir()), 5)
        try:
            payload = {"role": "bulk-reader", "task": "summarize", "files": [{"path": "fixture.txt", "text": "x" * 100_000}]}
            result = delegation_codex.run_turn(rpc, payload, ROUTE, "Read only", Path(tempfile.gettempdir()))
            self.assertEqual(delegation.validate_result(result, ROUTE, "bulk-reader"), "fixture.txt:1: result")
            self.assertEqual(result["usage"]["output_tokens"], 10)
        finally:
            rpc.close()
        self.assertIsNotNone(rpc.process.poll())

    def test_protocol_error_reroute_and_timeout(self):
        messages = ["not json", json.dumps({"method": "model/rerouted", "params": {}}), json.dumps({"id": 1, "method": "tool/requestUserInput"}), json.dumps({"method": "warning"})]
        for message in messages:
            with self.subTest(message=message):
                command = [sys.executable, "-u", "-c", "import sys,time; print(sys.argv[1],flush=True); time.sleep(2)", message]
                rpc = delegation_codex.Rpc(command, Path(tempfile.gettempdir()), 1)
                try:
                    with self.assertRaises(delegation.DelegationError):
                        rpc.receive()
                finally:
                    rpc.close()
        rpc = delegation_codex.Rpc([sys.executable, "-c", "import time; time.sleep(5)"], Path(tempfile.gettempdir()), 1)
        try:
            with self.assertRaises(delegation.DelegationError):
                rpc.receive()
        finally:
            rpc.close()
        self.assertIsNotNone(rpc.process.poll())


if __name__ == "__main__":
    unittest.main()
