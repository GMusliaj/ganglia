# Remember workflow

## 0. Checkpoint branch

Use this branch when the ask is "save a checkpoint", "save where we are", or
the material is clearly mid-flight session state rather than a distilled
lesson.

Write to `local/projects/<project>/checkpoints/YYYY-MM-DD-HHMM.md`. Derive
`<project>` from the repository or engagement discussed in the session. If no
matching directory exists under `local/projects/`, use `local/short-mem/`.

Frontmatter:

```yaml
---
type: checkpoint
title: <short title>
project: <project>
date: YYYY-MM-DD-HHMM
---
```

Use four short sections: `## What happened`, `## Decisions` with rationale,
`## Open threads`, and `## Next actions`. Keep it terse and never paste a
transcript.

Because `local/` is gitignored, do not auto-commit. Run
`scripts/refresh-qmd.sh` best-effort, report only `saved <relative-path>`, and
stop. If the session also produced a reusable lesson, offer to save it as a
separate entry.

## 1. Keep-worthiness

Record only a reusable pattern, a decision with rationale, a durable concept, a
reusable snippet, or a genuinely useful personal note. If the material is
trivial or one-off, say so and do not write.

## 2. Search before writing

Search the whole Brain, including `local/`, for the idea and obvious synonyms.
When the `brain-qmd` MCP tools are available, query the `brain` collection first
with explicit lexical and semantic searches plus an intent. Do not invoke the
QMD CLI directly for retrieval. Read `MEMORY.md` and `local/MEMORY.local.md`,
then always use `rg` across metadata and bodies as the source-of-truth floor.
If an entry exists, update it in place. Move replaced material into
`## Superseded`; never silently delete it. Prefer sharpening an existing entry
to creating a near-duplicate.

## 3. Route on privacy and durability

Shared and shareable:

- `patterns/` for reusable approaches;
- `lessons/` for empirical, non-obvious findings learned through debugging or
  measurement;
- `decisions/` for decisions with rationale;
- `concepts/` for durable explanations;
- `snippets/` for reusable code or procedures;
- `sources/` for source-grounded distillations;
- `infra/` for durable knowledge about Brain's own architecture, security, and
  operating infrastructure.

Local and gitignored:

- `local/notes/` for durable personal or identity-bearing knowledge;
- `local/short-mem/` for scratch and half-formed notes;
- `local/projects/<engagement>/` for every named customer, client, engagement,
  or project-specific lesson, including the name itself.

Read `local/MEMORY.local.md` for the repository's current personal-data rules.
Machine-specific paths, identity, secrets, client-confidential detail, and
engagement knowledge never enter shared folders.

A sanitized reusable version of an engagement lesson is a separate shared
pattern. Promotion is a human-reviewed editorial action: propose it and wait;
never automatically move local material to shared. If a short-memory note has
proven reusable and the user authorizes promotion, create or update the right
durable entry and remove the obsolete scratch note.

## 4. Write OKF-lite

Use `<folder>/<kebab-slug>.md`. Required frontmatter: `type`. Normally also add
`title`, a one-sentence `description`, tags registered in
`meta/tag-taxonomy.md`, and today's date. Register a genuinely needed new tag
before using it.

Use free-form Markdown with structure over prose, an `## Active` section for
durable claims, an optional `## Superseded` section, and a `## Source` section
for provenance. Use file-relative Markdown links to related entries.

Never write credentials, tokens, customer data, or other secret material into
shared content. Use unmistakable placeholders such as `EXAMPLE_NOT_A_SECRET`
when an example is necessary.

## 5. Reindex and commit

For a shared entry, run `scripts/auto-commit.sh`. It regenerates indexes and is
the owner-sanctioned exception allowing commits only for the Brain shared
knowledge allowlist. It never pushes.

Then run `scripts/refresh-qmd.sh` best-effort. This maintenance script may use
the QMD CLI internally because MCP exposes read-only retrieval tools, not index
update/embed operations. Normal Brain retrieval must still go through MCP. QMD
is optional; the grep floor already covers the new file.

If `auto-commit.sh` exits nonzero, stop. Do not bypass, weaken, edit, or retry
around `scripts/guard_shared.py`, hooks, or policy. Report the offending
`file:line` and guard message verbatim. Offer only the legitimate routing fixes:
scrub the private term or machine-specific path, or move engagement-specific
knowledge to `local/`.

## 6. Report

On success, output one line only: `saved <relative-path>`. Do not echo content,
commit hashes, or index churn. On failure, be loud: include exact scanner output
and the relevant routing options.
