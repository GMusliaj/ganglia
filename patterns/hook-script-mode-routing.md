---
type: pattern
title: Enforce delegated model routing with hooks, scripts, and skills
description: Route bounded I/O-heavy agent work to named worker modes while keeping safety and context boundaries in executable hooks and wrappers.
tags: [codex, workflow, security]
date: 2026-09-06
---

# Enforce delegated model routing with hooks, scripts, and skills

## Active

Use three complementary layers when a host agent should delegate a narrow class
of work to another model or worker mode:

1. **Hooks are the hard gate.** Intercept the host tool calls that would create
   unwanted context load, such as full reads of large files. Allow targeted
   reads, small inputs, and unrelated commands. Return an actionable reason so
   the host agent can select the delegation path.
2. **Scripts are the transport boundary.** Give the agent small commands with
   named arguments. The wrapper validates inputs, assembles the payload,
   invokes the backend action, enforces payload and timeout limits, validates
   the response, and normalizes output. Do not require the model to assemble
   shell pipelines or transport JSON from prose.
3. **Skills are the soft routing layer.** Describe when delegation is useful,
   which script to call, and what the host agent must review afterward. Keep
   judgment-heavy work such as debugging, architecture, and exact edits on the
   host agent.

Route to a **named mode**, not directly to a model identifier, when the backend
owns worker configuration. Resolve the mode server-side with an explicit
precedence rule (for example, private, group, then public), fail on missing or
ambiguous names, and offer an explicit ID override only for intentional
pinning. Verify the response reports the expected applied mode; discard a
generic answer when a stale pin caused the turn to run without the mode.

Keep delegated calls one-shot when replaying the input corpus would defeat the
purpose of delegation. Send the large input to the worker and return only the
summary or generated result to the host agent. Require reference material for
boilerplate generation, and make direct file writes explicit and reviewable.

For Ganglia-oriented custom skills, apply the same shape: define the candidate
work and its hard boundary, enforce the boundary in a hook or validator, put
integration and fail-closed checks in a deterministic wrapper, and use the
skill text to guide selection and post-delegation review. Treat the underlying
model choice as backend configuration rather than a promise encoded only in
skill prose.

## Source

Observed in the `portal-ai-plugins` `shunt` plugin: its Claude `PreToolUse`
hooks route large reads, its `bulk-read` and `code-write` scripts call named
AiKA modes through the Portal action registry, and its transport wrapper
rejects missing modes, empty answers, malformed responses, oversized payloads,
and stale mode pins.
