---
name: remember
description: Distill durable knowledge, materialize a reusable safe operation, or save a resumable checkpoint into the cross-repository Brain, with privacy routing and security-gated auto-commit. Use when the user asks to remember, retain, record, or checkpoint something for later.
---

# Remember

Capture knowledge in the Brain checkout containing this skill. Resolve the real
skill path (following symlinks) and walk up to the repository root; do not assume
a username or hardcode a home-directory path.

Before any write, read the complete workflow in
[references/workflow.md](references/workflow.md) and the Brain `README.md`.
Follow its checkpoint branch, keep-worthiness test, duplicate search, privacy
routing, artifact-materialization decision, OKF-lite format, indexing, Security
Baseline, and reporting contract. When the retained knowledge is a stable,
repeatable operation, also read
[references/artifact-materialization.md](references/artifact-materialization.md)
and move generation and verification work into remember rather than recall.

Treat user text following `$remember` as the requested memory. When it is empty,
infer the reusable lesson from the recent conversation. The owner-authorized
commit exception applies only through `scripts/auto-commit.sh`; never push.
