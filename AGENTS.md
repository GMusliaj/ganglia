# Ganglia repository instructions

## What this repository is

Ganglia is a portable, cross-repository second ganglia: plain-Markdown knowledge
entries built on OKF-lite. The knowledge layer is the product and the format is
the contract. Every entry must remain readable, searchable, and editable from a
bare clone without QMD, a model, a database, or a build step.

Repository tooling may have narrowly scoped dependencies, but none may become a
hard dependency of reading or text-searching the knowledge. In particular, QMD
is an optional semantic accelerator and D3 is used only to serve or explicitly
export the canvas.

Codex exposes Ganglia through the installed `remember` and `recall` skills. Treat
them as the implementation of the user-facing `/remember` and `/recall`
operations; do not duplicate their workflows in this file or in sibling
repositories.

## Commands

```text
scripts/setup.sh              one-command local setup, Codex skills, QMD MCP, canvas dependency, verification
scripts/setup-python.sh       create the ignored Python venv and install pinned development dependencies
scripts/auto-commit.sh        reindex, lint, guard, and commit an allowlisted shared-memory change
scripts/guard_shared.py       fail-closed publication and shared/local routing guard
scripts/audit-security.sh     scan Python, Bash, JavaScript, and dependency vulnerabilities
scripts/audit_public.py       read-only working-tree and reachable-history publication audit
scripts/refresh-qmd.sh        best-effort local QMD index maintenance; not a retrieval interface
scripts/install-qmd-mcp.sh    configure the Codex-facing ganglia-qmd MCP server
bin/reindex.py                regenerate shared, folder, and local navigation indexes
bin/lint_ganglia.py             read-only validation of the shared OKF-lite contract
bin/canvas.py                 serve the live knowledge graph or explicitly export a snapshot
bin/sync_codex_sessions.py    build the private, compact session catalog used by QMD and canvas
scripts/verify.sh             run repository tests, guards, reindexing, lint, and shell validation
```

Run `python3 bin/reindex.py` after adding, renaming, moving, or changing the
retrieval metadata of an entry, unless the `remember` workflow runs
`scripts/auto-commit.sh` for you. `MEMORY.md`, shared-folder `index.md` files,
and `local/MEMORY.local.md` are generated; never edit them by hand.

`bin/okf.py` is the single parser imported by indexing and linting. Do not add a
second interpretation of frontmatter or the folder contract: what is indexed
and what is linted must not disagree.

`bin/lint_ganglia.py` is read-only and never scans `local/`. Errors include a
missing `type`, an invalid filename or metadata value, an unknown tag, or a
broken/escaping relative Markdown link. Warnings include missing retrieval
metadata, lifecycle or provenance sections, and inbound links. `--strict`
promotes warnings to errors. Lint is advisory in `scripts/auto-commit.sh`; the
shared-routing guard is the blocking security gate.

## Public repository contract

- Public source includes shared knowledge, generated shared indexes, skills,
  scripts, tests, documentation, assets, package manifests, `.mcp.json`, and
  `.qmd/index.yml`.
- Private or disposable state includes everything under `local/`, QMD databases
  and models, the generated canvas, installed dependencies, virtual
  environments, caches, editor settings, local agent state, environment files,
  and credentials. Keep these ignored and untracked.
- `scripts/guard_shared.py` scans all tracked and non-ignored publication
  candidates, not only shared knowledge. It combines machine-path, email,
  credential-shape, private-denylist, and runtime-identity checks without
  printing the private values it compares.
- Ignore rules prevent accidental staging but do not make the repository a safe
  secret store. Keep credentials outside the checkout whenever possible.
- Before publishing, inspect both the working tree and Git history. Ignore rules
  cannot remove identity or secrets already stored in commits, tags, branches,
  remotes, or commit-author metadata.
- Run `scripts/audit-security.sh` and `python3 scripts/audit_public.py` before
  publication. Both are read-only and fail closed. The security audit covers
  source scanners and live Python/npm advisories; the publication audit scans
  the current candidate set, reachable Git blobs, and commit-author email
  metadata without printing matched private values. History rewriting remains
  a separate destructive action requiring explicit approval.

## Format contract (OKF-lite)

- One durable concept, decision, pattern, lesson, snippet, source, or
  Ganglia-infrastructure note belongs in one Markdown file. Its path is its
  identity; its folder determines its knowledge kind.
- Shared, commit-eligible knowledge lives only in `patterns/`, `lessons/`,
  `decisions/`, `concepts/`, `snippets/`, `sources/`, and `infra/`.
- Frontmatter is intentionally simple. `type` is required. Prefer `title`, a
  one-sentence `description`, registered `tags`, and a `date` in `YYYY-MM-DD`
  form because they materially improve retrieval.
- Register new tags in `meta/tag-taxonomy.md` before using them. Do not tag an
  entry merely to repeat the kind already encoded by its folder.
- Use file-relative Markdown links to connect entries. Those links are the
  authoritative knowledge graph; never put machine-specific absolute paths in
  shared knowledge.
- Durable claims live under `## Active`. When a claim is replaced, move the old
  material and its context under `## Superseded`; never silently erase history.
- End sourced knowledge with `## Source`. Keep quotations short and distinguish
  sourced facts from inference.
- Repository operating documentation belongs in `README.md`, `docs/`, and this
  file. Reusable knowledge belongs in a knowledge folder, not tooling docs.

## Shared versus local boundary (important)

Everything under `local/` is gitignored and private. It contains identity,
machine-local configuration, durable personal notes, short-lived memory,
project or engagement knowledge, checkpoints, and episodic session material.

- Never put names, email addresses, handles, home-directory paths, credentials,
  secrets, private hostnames, customer data, or client/engagement names in a
  shared knowledge folder.
- Named project or engagement knowledge belongs in
  `local/projects/<project>/`. Durable personal notes belong in
  `local/notes/`; checkpoints and half-formed material belong in the matching
  project or `local/short-mem/`.
- A reusable lesson stripped of engagement detail may become a separate shared
  entry only through an explicit, human-reviewed editorial decision. Promotion
  is never an automatic move from local to shared.
- `scripts/guard_shared.py` is the fail-closed backstop. It scans the shared
  layer for machine paths and terms from the gitignored
  `local/shared-denylist.txt`. A hit means the content was routed incorrectly,
  not that the guard should be weakened.
- A local QMD index may include gitignored material. Indexing is not publishing:
  the guard and Git boundary enforce privacy, and no local content may appear in
  a generated shared index, staged change, or commit.

## Retrieval tiering (design decision)

QMD is the optional semantic ceiling; plain Markdown plus repository-wide text
search is the mandatory floor. Never make QMD—or any tool—a hard dependency of
reading or searching Ganglia. See
[`decisions/retrieval-tiering-qmd-is-ceiling-not-floor.md`](decisions/retrieval-tiering-qmd-is-ceiling-not-floor.md).

- `/recall <query>` is strictly read-only and must use the installed `recall`
  skill. Temporal resume questions begin with the relevant project index and
  newest checkpoint/session note.
- Normal semantic retrieval goes through the configured `ganglia-qmd` MCP server,
  using its `query`, `get`, `multi_get`, and `status` tools. Do not invoke `qmd`
  or `scripts/qmd.sh` directly during recall.
- Always run the plain-text search floor across shared and explicit gitignored
  local paths, even when QMD succeeds. Merge and deduplicate hits by path; rank
  exact title/tag matches, then description, body, and confident semantic hits.
- Prefer distilled durable entries to scratch notes and raw transcripts unless
  local project context is genuinely more relevant. Label results `shared` or
  `local` and cite file-relative paths with relevant lines.
- The default semantic collection is `ganglia`. Include the private,
  excluded-by-default `codex-sessions` collection only for temporal,
  project-resumption, or explicitly session-related retrieval.
- If the MCP server, collection, model, or query fails, fall through silently to
  text search. Report skill unavailability rather than bypassing the workflow
  with a direct QMD CLI query.
- Direct QMD CLI access is confined to repository-owned setup and maintenance
  scripts because the MCP server exposes retrieval, not update/embed mutations.

## Canvas contract

`bin/canvas.py` serves indexed Markdown as a clickable force-directed graph at a
loopback-only URL. The tracked `bin/canvas.html` and `bin/canvas.js` files are
the UI source; the server renders graph data in memory and live-reloads the open
page when either source or QMD's SQLite/WAL state changes. It writes no runtime
HTML by default.

- The default canvas scope is the shared layer. Include `local/` only when the
  user explicitly requests `--scope all`.
- The explicit all-scope view may include the private `codex-sessions`
  collection. `bin/sync_codex_sessions.py` copies only session metadata and
  compact request excerpts into the ignored local catalog; never embed raw
  JSONL wholesale or commit transcript content.
- Keep the default server bound to `127.0.0.1`. Binding to another interface is
  an explicit operator choice because all-scope responses may contain private
  excerpts and machine-local paths.
- Offline HTML is an explicit `--output` export, not the development runtime.
  Keep private or all-scope exports in ignored local storage and never publish
  them.
- Explicit Markdown links and registered tags are authoritative graph edges.
  Semantic edges read QMD's internal vector storage and are best-effort; a
  schema/decode mismatch must warn once and preserve link and tag edges.
- A selected node stays visible in the right inspector with related knowledge
  grouped by kind. The left library supports collection/session navigation.
  Every color encoding must also have a shape or text legend.
- D3 is the sole scoped browser dependency. Keep it pinned in
  `bin/package.json`, installed under ignored `bin/node_modules/`, and inlined
  into live responses and explicit exports so no CDN is required.
- After changing the canvas, run its unit and live-server tests, start it with
  `--no-open`, and inspect the live interface in a browser when that surface is
  available.

## Remember contract

- `/remember [lesson]` is the normal Ganglia write path and must use the installed
  `remember` skill. The skill owns keep-worthiness, duplicate search, privacy
  and durability routing, OKF-lite authoring, index refresh, and reporting.
- A checkpoint is resumable episodic state, not a durable lesson. Save it under
  `local/projects/<project>/checkpoints/` when a project is known, otherwise
  under `local/short-mem/`; never auto-commit it.
- Search before writing. Update a matching entry instead of creating a
  near-duplicate, and preserve replaced material under `## Superseded`.
- Only retain knowledge worth retrieving again: a reusable pattern, settled
  decision and rationale, durable concept, useful snippet, empirical lesson, or
  genuinely useful personal note.
- After a shared write, the skill runs `scripts/auto-commit.sh`. This is the
  sole owner-sanctioned exception to ordinary commit discipline. It stages only
  the shared allowlist and generated shared indexes, derives the message, and
  never pushes. Tooling and operating-document changes still require explicit
  commit authorization.
- If the routing guard fails, stop before staging. Report its exact
  `file:line` and message verbatim; never use `--no-verify`, bypass hooks, edit
  policy, loosen the guard, or retry around it.
- The skill may run `scripts/refresh-qmd.sh` best-effort after a write. That
  maintenance script may use the CLI internally; ordinary Ganglia access remains
  implicit through `/remember` and `/recall`.
- Success is one terse path. Do not echo stored content, index churn, or commit
  hashes unless asked. Failures that need attention are reported verbatim.

## FAFO and skill-evolution contract

- Use the installed `fafo` skill for a bounded, reversible experiment that
  resolves a consequential uncertainty. Reading the relevant contract and
  repository state comes first; FAFO never widens authorization for destructive
  actions, external mutation, publication, policy bypass, or credential use.
- Before a FAFO action, validate an ignored closed-schema plan with the skill's
  `scripts/experiment_contract.py`; repository-local effects require exact
  targets, a non-overlapping dirty-state check, passed preview evidence,
  authorization, rollback, retry reconciliation, an independent postcondition,
  and bounded actions, time, and resources. The validator never executes the
  action and its acceptance does not prove the entered claims are true.
- After the action, validate a receipt bound to the exact plan digest. End in
  `verified`, `falsified`, `inconclusive`, `authorization-blocked`,
  `safety-blocked`, or `superseded`. Reconcile actual state before retrying an
  interrupted or indeterminate action, and route any user-approved durable
  operation through `$remember` rather than a FAFO-specific executor.
- Capture only sanitized structured task evidence. Never retain raw reasoning,
  unrestricted traces, identity, credentials, customer data, private hostnames,
  or engagement details in the evolution store.
- `bin/skill_evolution.py` owns evidence capture, recurrence consolidation,
  proposal snapshots, evaluation, human decisions, application, and rollback.
  Its generated state belongs under ignored `local/skill-evolution/`; operation
  inputs and candidates belong under ignored `.tmp/`.
- A reusable pattern requires the same signal key across at least two distinct
  task IDs. One task or multiple records from one task cannot justify a skill
  proposal.
- Each proposal may change exactly one repository-local
  `.agents/skills/<skill-name>/SKILL.md`. Supporting scripts, schemas,
  references, assets, and evaluator changes use the ordinary repository
  workflow instead of generated application.
- Skill evaluators live under `evals/skills/`, use fixed deterministic cases,
  accept `--skill-path`, return the closed result schema, and perform no
  repository or external mutations. The candidate must score strictly above
  baseline without regressing any baseline-passing case.
- Keep the active skill unchanged until the automated gate accepts and the user
  explicitly accepts the exact candidate digest. Human acceptance cannot
  override a rejected gate. Application never commits or pushes.
- After application, run `scripts/verify.sh`. If the candidate caused a
  verification failure, use the content-bound rollback operation immediately
  and report the verification and rollback results.
- On later real tasks, attribute sanitized outcome evidence only to the proposal
  that is still active, then use the `impact` operation to summarize distinct
  task pass/fail rates and recurrent signals before proposing another change.
  Instruction-contract scores alone are not runtime effectiveness evidence.

## Using a service, API, or external tool

Before the first use in a session of an integration whose current contract has
not been verified, inspect its installed help and current official
documentation, then answer:

1. How is it actually invoked?
2. What are its documented limits and update semantics?
3. What practices does its maintainer recommend?
4. What other services, protocols, or tools is it designed to combine with?

Then use `/recall` because the relevant failure mode or decision may already be
recorded. Do not rely on training-data memory for a changing API and do not use
a call/error/patch/repeat loop as a substitute for reading the contract. That
loop reveals only the first violated constraint and can turn each fact into a
full deployment cycle.

When official documentation does not cover the case or the integration cannot
express a required operation, label the gap `unverified` or a full blocker.
Record an explicit parameter and documented human step when appropriate; never
guess and call the result verified.

### External verification and authorization

Verification belongs in the task that owns the change so a design is not first
tested at the end. Authorization is a separate question:

- Read-only inspection, synthesis, linting, diffs, and previews may run when
  relevant.
- Creating, updating, deleting, deploying, publishing, pushing, sending, or
  otherwise mutating an external system requires authorization for that scope.
- Repository instructions can narrow global or owner policy, never widen it.
- Preview replacement, destruction, access-level, and other irreversible
  effects before asking a human to apply a change. Stop and report unexpected
  destructive behavior.
- Private access is the default for new infrastructure. A proposal to make a
  resource public is a security decision for the user, not a troubleshooting
  shortcut to implement or encode in tests without approval.
- Fix constraint violations at their defining source and across the affected
  class, not by manually patching one deployed instance. Assertions over a
  resource family must fail when they inspected an empty set.

## Repository workflow

- At the start of a modifying session, read `CHANGELOG.md` and inspect
  `git status`. Preserve unrelated worktree changes.
- Default to action on a clearly scoped repository request. Analysis, review,
  planning, proposals, and status requests remain read-only unless the user
  also asks for implementation.
- Keep temporary artifacts in ignored `.tmp/`; never stage them. Do not create
  scratch notes or handoff Markdown files unless requested.
- Update `CHANGELOG.md` for material tooling, schema, routing, security, or UI
  changes. Never attribute pre-existing worktree changes to the current task.
- Create ordinary commits only when explicitly requested. The shared-memory
  auto-commit described above is the one standing exception. Never push unless
  asked.
- Run `scripts/verify.sh` before declaring a material implementation change
  complete. It includes the offline/static security gate. Run the networked
  `scripts/audit-security.sh` before publication or after dependency changes.
  Report command results and material warnings; label anything that could not
  be checked `unverified`.
- Never bypass repository guards or hooks. If a required verifier cannot run,
  report the exact limitation and propose a compliant fix.
