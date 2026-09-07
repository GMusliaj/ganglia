---
name: code-writer
description: Generate predictable boilerplate from explicit reference and source files using a configured cheaper worker. Use for repetitive tests, types, or config drafts; keep novel logic, debugging, architectural decisions, and surgical edits on the host.
---

# Code writer

Resolve this skill's real path to the Ganglia checkout. Call its
`bin/delegation.py` with the active source repository as `--root`. Require a
reference file whose conventions should be followed, plus the implementation
under test or other necessary source via `--context`.

```sh
<ganglia>/.venv/bin/python <ganglia>/bin/delegation.py --root <source-repo> code-write --spec "Draft tests for the parser" --reference tests/test_existing.py --context src/parser.py
```

The default is an offline preview. The local `code-writer` role must resolve to
an explicit provider/model in `local/delegation.json`. Add `--execute` before
`code-write` only within the user's authorized task and data boundary. A call
starts one fresh worker turn; failed or mismatched responses are discarded,
without automatic retry or fallback to a more expensive model.

Output is a draft on stdout. Optional `--target` writes only a NEW file after a
successful validated response; it never overwrites an existing file. For edits,
review the draft and apply the desired patch on the host. The worker receives
only the explicit reference/context corpus. Include source needed for useful
tests: a reference style alone cannot establish behavior.

Review generated code, preserve internal Markdown fences, and run the relevant
source repository tests. Do not accept generated tests solely because they pass
on the implementation they mimic. Repeated generations consume worker usage.
See [setup and evaluation](../../../docs/delegation.md) only as needed.
Never auto-commit, install hooks, or change model mappings during generation.

## Attribution

Adapted from **Spotify's shunt `code-writer` skill** in `portal-ai-plugins`:
[original skill at the ported revision](https://github.com/spotify/portal-ai-plugins/blob/3c24ca30ff63e1f5bbad1c43fe5324daff579123/plugins/shunt/skills/code-writer/SKILL.md).
The upstream skill is licensed under [Apache-2.0](../../../LICENSE).
Ganglia changes the transport, source-context requirements, authorization and
target-write behavior; this is a modified adaptation, not an unchanged upstream
copy. See [third-party notices](../../../THIRD_PARTY_NOTICES.md) for provenance.
