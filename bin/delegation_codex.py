"""Bounded stdio adapter for Codex app-server 0.153.4's generated v2 contract.

One new ephemeral thread, one turn, explicit model/effort and no fallback.
Local configuration and managed restrictions still apply; no trust bypass.
"""

from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import tempfile
import time

from delegation_common import DelegationError, encode


class Rpc:
    def __init__(self, command: list[str], cwd: Path, timeout: int):
        self.deadline = time.monotonic() + timeout
        self.process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True)
        self.in_fd = self.process.stdin.fileno()
        self.out_fd = self.process.stdout.fileno()
        self.err_fd = self.process.stderr.fileno()
        for fd in (self.in_fd, self.out_fd, self.err_fd):
            os.set_blocking(fd, False)
        self.readers = [self.out_fd, self.err_fd]
        self.buffer = b""
        self.queue = deque()
        self.bytes_read = 0
        self.serial = 0

    def pump(self, pending: bytes = b"") -> bytes:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DelegationError("worker deadline exceeded; no retry was made")
        ready, writable, _ = select.select(self.readers, [self.in_fd] if pending else [], [], remaining)
        if not ready and not writable:
            raise DelegationError("worker deadline exceeded; no retry was made")
        if writable:
            try:
                pending = pending[os.write(self.in_fd, pending[:16_384]):]
            except BrokenPipeError as exc:
                raise DelegationError("worker closed its input") from exc
        for fd in ready:
            chunk = os.read(fd, 65_536)
            if not chunk:
                self.readers.remove(fd)
                if fd == self.out_fd:
                    raise DelegationError("worker closed before a complete response")
                continue
            self.bytes_read += len(chunk)
            if self.bytes_read > 4_000_000:
                raise DelegationError("worker event stream exceeds the transport budget")
            if fd == self.err_fd:
                continue  # May contain local configuration paths or credentials.
            self.buffer += chunk
            if len(self.buffer) > 1_000_000:
                raise DelegationError("worker event exceeds the transport budget")
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise DelegationError("worker returned malformed protocol JSON") from exc
                if not isinstance(value, dict):
                    raise DelegationError("worker protocol event must be an object")
                self.queue.append(value)
        return pending

    def send(self, message: dict) -> None:
        pending = encode(message) + b"\n"
        while pending:
            pending = self.pump(pending)

    def receive(self) -> dict:
        while not self.queue:
            self.pump()
        event = self.queue.popleft()
        if "method" in event and "id" in event:
            # This client grants no tool, permission, auth or user-input requests.
            raise DelegationError("worker requested an interactive action; answer discarded")
        if event.get("method") in {"model/rerouted", "error", "configWarning", "warning"}:
            raise DelegationError("worker reported a reroute, error, or configuration warning; answer discarded")
        return event

    def call(self, method: str, params: dict) -> dict:
        self.serial += 1
        request_id = self.serial
        self.send({"id": request_id, "method": method, "params": params})
        while True:
            event = self.receive()
            if event.get("id") != request_id:
                continue
            if "error" in event or not isinstance(event.get("result"), dict):
                raise DelegationError(f"Codex {method} failed; no fallback was attempted")
            return event["result"]

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=2)
        finally:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()


def initialize(rpc: Rpc) -> None:
    rpc.call("initialize", {"clientInfo": {"name": "ganglia_delegate", "version": "1"},
                             "capabilities": {"experimentalApi": True}})
    rpc.send({"method": "initialized", "params": {}})


def model_catalog(rpc: Rpc) -> list[dict]:
    """Read a bounded catalog without creating a thread or inference turn."""
    # Inspect all catalog pages under a fixed bound. No assumption that the
    # configured model is visible on the first page, and no alias fallback.
    cursor = None
    entries = []
    for _ in range(10):
        page = rpc.call("model/list", {"limit": 100, "includeHidden": False, "cursor": cursor})
        if not isinstance(page.get("data"), list) or any(not isinstance(entry, dict) for entry in page["data"]):
            raise DelegationError("model catalog is malformed")
        entries.extend(page["data"])
        cursor = page.get("nextCursor")
        if cursor is None:
            return entries
        if not isinstance(cursor, str) or not cursor:
            raise DelegationError("model catalog cursor is malformed")
    raise DelegationError("model catalog exceeds the page budget")


def available_models() -> list[dict]:
    executable = shutil.which("codex")
    if executable is None:
        raise DelegationError("Codex CLI is unavailable")
    with tempfile.TemporaryDirectory(prefix="ganglia-catalog-") as folder:
        rpc = Rpc([executable, "app-server", "--stdio"], Path(folder), 25)
        try:
            initialize(rpc)
            return [{"model_id": entry["model"],
                     "efforts": [value["reasoningEffort"] for value in entry["supportedReasoningEfforts"]]}
                    for entry in model_catalog(rpc)]
        except (KeyError, TypeError, AttributeError) as exc:
            raise DelegationError("model catalog is malformed") from exc
        finally:
            rpc.close()


def run_turn(rpc: Rpc, payload: dict, route: dict, instructions: str, cwd: Path) -> dict:
    initialize(rpc)
    selected = next((entry for entry in model_catalog(rpc) if entry.get("model") == route["model_id"]), None)
    if selected is None:
        raise DelegationError("configured model is absent from the local provider catalog")
    efforts = {value.get("reasoningEffort") for value in selected.get("supportedReasoningEfforts", []) if isinstance(value, dict)}
    if route["effort"] not in efforts:
        raise DelegationError("configured effort is not supported by the selected model")
    # Reduce the tool surface in-memory only. Keep hooks, rules, auth and
    # managed policy intact. environments=[] is the app-server contract for a
    # turn without environment access. MCP/plugin tools also need excluding.
    current = rpc.call("config/read", {"includeLayers": False}).get("config")
    if not isinstance(current, dict):
        raise DelegationError("effective Codex configuration is unavailable")
    config = {"features.shell_tool": False, "features.multi_agent": False,
              "features.apps": False, "web_search": "disabled",
              "model_reasoning_effort": route["effort"]}
    for section in ("mcp_servers", "plugins"):
        entries = current.get(section, {})
        if not isinstance(entries, dict):
            raise DelegationError("effective Codex tool configuration is malformed")
        # Thread config is JSON, not CLI TOML key syntax. Quoting a dotted
        # segment creates a different server ID and loses its transport.
        # Preserve literal IDs in nested objects and overlay only the flag.
        # config/read's normalized null/default values are not round-trippable.
        if any(not isinstance(settings, dict) for settings in entries.values()):
            raise DelegationError("effective Codex tool configuration is malformed")
        config[section] = {name: {"enabled": False} for name in entries}
    thread = rpc.call("thread/start", {"model": route["model_id"], "modelProvider": "openai",
        "allowProviderModelFallback": False, "ephemeral": True, "cwd": str(cwd),
        "sandbox": "read-only", "approvalPolicy": "never", "environments": [],
        "dynamicTools": [], "config": config, "baseInstructions": instructions})
    if thread.get("model") != route["model_id"] or thread.get("modelProvider") != "openai":
        raise DelegationError("thread selected a different model/provider; turn was not sent")
    if thread.get("sandbox", {}).get("type") != "readOnly" or thread.get("approvalPolicy") != "never" or thread.get("thread", {}).get("ephemeral") is not True:
        raise DelegationError("thread did not confirm read-only ephemeral execution")
    thread_id = thread["thread"].get("id")
    if not isinstance(thread_id, str) or not thread_id:
        raise DelegationError("thread identity is missing")
    # Send turn/start without waiting through call(): usage/item notifications
    # may race the turn/start result and must not be dropped.
    rpc.serial += 1
    start_id = rpc.serial
    rpc.send({"id": start_id, "method": "turn/start", "params": {"threadId": thread_id,
        "input": [{"type": "text", "text": encode(payload).decode()}],
        "model": route["model_id"], "effort": route["effort"], "environments": [],
        "serviceTierForTurn": "default"}})
    usage = None
    texts: dict[str, tuple[str | None, str]] = {}
    turn_id = None
    observed_turn_ids = set()
    delta_bytes = 0
    while True:
        event = rpc.receive()
        if event.get("id") == start_id:
            if "error" in event:
                raise DelegationError("turn failed to start")
            turn_id = event.get("result", {}).get("turn", {}).get("id")
            continue
        method = event.get("method")
        params = event.get("params", {})
        if params.get("threadId") not in {None, thread_id}:
            raise DelegationError("worker event belongs to another thread")
        if params.get("turnId") is not None:
            observed_turn_ids.add(params["turnId"])
        if method == "thread/tokenUsage/updated":
            total = params.get("tokenUsage", {}).get("total", {})
            if type(total.get("totalTokens")) is not int:
                raise DelegationError("worker usage notification is missing an integer totalTokens")
            if total["totalTokens"] > route["max_worker_tokens"]:
                raise DelegationError(f"worker token budget exceeded: observed {total['totalTokens']}, limit {route['max_worker_tokens']}; no retry was made")
            usage = {"input_tokens": total.get("inputTokens"), "cached_input_tokens": total.get("cachedInputTokens"), "output_tokens": total.get("outputTokens")}
        elif method == "item/agentMessage/delta":
            delta_bytes += len(params.get("delta", "").encode())
            if delta_bytes > route["max_output_bytes"]:
                raise DelegationError("worker output byte budget exceeded")
        elif method in {"item/started", "item/completed"}:
            item = params.get("item", {})
            if item.get("type") not in {"agentMessage", "reasoning", "userMessage"}:
                raise DelegationError("worker attempted a tool or extra workflow; answer discarded")
            if method == "item/completed" and item.get("type") == "agentMessage":
                text = item.get("text", "")
                if not isinstance(text, str) or len(text.encode()) > route["max_output_bytes"]:
                    raise DelegationError("worker text is invalid or oversized")
                texts[item.get("id", "answer")] = (item.get("phase"), text)
        elif method == "turn/completed":
            turn = params.get("turn", {})
            if not turn_id or turn.get("id") != turn_id or turn.get("status") != "completed" or observed_turn_ids - {turn_id}:
                raise DelegationError("worker turn did not complete successfully")
            break
    # Do not prepend progress commentary to generated code. Legacy models may
    # omit phase, so retain unclassified messages only when no final exists.
    final = [text for phase, text in texts.values() if phase == "final_answer"]
    answer = final or [text for phase, text in texts.values() if phase is None]
    return {"provider": "codex", "model_id": thread["model"], "role": payload["role"],
            "model_evidence": "codex-thread-start-and-no-reroute", "text": "\n".join(answer), "usage": usage}


def invoke(payload: dict, route: dict, instructions: str) -> dict:
    executable = shutil.which("codex")
    if executable is None:
        raise DelegationError("Codex CLI is unavailable")
    # This wrapper does not put the corpus in argv or write it to disk, and
    # requests ephemeral history. Provider/runtime retention still applies.
    with tempfile.TemporaryDirectory(prefix="ganglia-worker-") as folder:
        rpc = Rpc([executable, "app-server", "--stdio"], Path(folder), route["timeout_seconds"])
        try:
            return run_turn(rpc, payload, route, instructions, Path(folder))
        except (KeyError, TypeError, AttributeError) as exc:
            raise DelegationError("worker returned an incompatible protocol shape") from exc
        finally:
            rpc.close()
