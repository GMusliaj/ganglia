---
type: pattern
title: Enforce delegated model routing with hooks, scripts, and skills
description: Route bounded I/O-heavy agent work from logical skill roles to explicit local model IDs while keeping safety and context boundaries in executable hooks and wrappers.
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

Keep the published skill and hook interfaces provider-neutral by routing to a
logical role such as `bulk-reader` or `code-writer`, then resolve that role in
the local adapter to an explicit `(provider, model_id)` mapping. Make the
mapping an intentional local-development configuration rather than hiding the
model choice in skill prose. Fail closed when a role has no mapping, the model
ID is stale or unsupported, or the response cannot prove which model ran.
Return the selected role and model in diagnostics so a result is attributable
and testable.

Do not publish credentials, account-specific endpoints, or unstable machine
configuration with the reusable hooks and skills. Publish the portable
contracts and deterministic adapter; inject or separately configure model IDs
when they are environment-specific. If a model ID is intentionally shareable,
still validate it against the local provider before using it.

Keep delegated calls one-shot when replaying the input corpus would defeat the
purpose of delegation. Send the large input to the worker and return only the
summary or generated result to the host agent. Require reference material for
boilerplate generation, and make direct file writes explicit and reviewable.

For Ganglia-oriented custom skills, apply the same shape: define the candidate
work and its hard boundary, enforce the boundary in a hook or validator, map
the logical role to an explicit local model ID, put integration and fail-closed
checks in a deterministic wrapper, and use the skill text to guide selection
and post-delegation review. The model mapping is part of the executable local
configuration, not a promise encoded only in skill prose.

## Source

Reference implementation: [Spotify's `portal-ai-plugins`](https://github.com/spotify/portal-ai-plugins),
especially the `shunt` plugin. Its Claude `PreToolUse` hooks route large reads,
its `bulk-read` and `code-write` scripts call named AiKA modes through the
Portal action registry, and its transport wrapper rejects missing modes, empty
answers, malformed responses, oversized payloads, and stale mode pins. For
Ganglia's local-development adaptation, preserve that hook/script/skill shape
but replace server-side mode resolution with an explicit local
`role -> (provider, model_id)` mapping.
