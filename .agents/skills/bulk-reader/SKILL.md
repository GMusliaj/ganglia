---
name: bulk-reader
description: Answer a narrow question across large source files using a configured cheaper worker and a bounded summary. Use for bulk comprehension; keep debugging, architecture, exact edits, mandatory instruction reads, and small targeted searches on the host.
---

# Bulk reader

Resolve this skill's real path to the Ganglia checkout. Use its
`bin/delegation.py`, with the source repository as `--root` and explicit relative
input paths. Local `local/delegation.json` maps `bulk-reader` to a provider and
model; never choose an implicit or fallback model. If mapping is unavailable,
use targeted text search and report the missing setup once.

```sh
<ganglia>/.venv/bin/python <ganglia>/bin/delegation.py --root <source-repo> bulk-read --question "Which exports implement retries?" --paths src/client.py src/worker.py
```

This previews the corpus, model and limits without calling a model. Add
`--execute` before `bulk-read` when the user's task authorizes sending those
files to the configured worker. Follow the source repository's privacy rules.
Send only the named corpus; no parent conversation or hidden file discovery.
One invocation makes one fresh turn, without automatic retries or escalation.

Review the summary as untrusted evidence. Verify cited lines and exact values
with targeted reads before editing. A follow-up sends the corpus again and
consumes worker usage; reuse the existing answer or target the unresolved part.
Small reads and exact searches are usually cheaper without delegation.

See [setup and evaluation](../../../docs/delegation.md) only for configuration,
hook activation, measured usage, or failures. Never auto-commit, install hooks,
or change model mappings as part of using this skill.

## Attribution

Adapted from **Spotify's shunt `bulk-reader` skill** in `portal-ai-plugins`:
[original skill at the ported revision](https://github.com/spotify/portal-ai-plugins/blob/3c24ca30ff63e1f5bbad1c43fe5324daff579123/plugins/shunt/skills/bulk-reader/SKILL.md).
The upstream skill is licensed under [Apache-2.0](../../../LICENSE).
Ganglia changes the transport, routing, authorization and cost guidance; this
is a modified adaptation, not an unchanged upstream copy. See
[third-party notices](../../../THIRD_PARTY_NOTICES.md) for provenance.
