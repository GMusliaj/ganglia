# Ganglia onboarding

This guide installs Ganglia once for cross-repository use, explains how local
skill changes reach Codex globally, and lists the machine-level checks that
keep the integration healthy.

## Installation model

The checked-in skill directories are authoritative:

```text
~/ganglia/.agents/skills/remember/
~/ganglia/.agents/skills/recall/
~/ganglia/.agents/skills/fafo/
~/ganglia/.agents/skills/skill-evolution/
```

Codex discovers user-global skills under `~/.agents/skills`. Ganglia installs
symlinks there:

```text
~/.agents/skills/remember -> ~/ganglia/.agents/skills/remember
~/.agents/skills/recall   -> ~/ganglia/.agents/skills/recall
~/.agents/skills/fafo     -> ~/ganglia/.agents/skills/fafo
~/.agents/skills/skill-evolution -> ~/ganglia/.agents/skills/skill-evolution
```

Codex supports symlinked skill directories. Consequently, there is no second
copy to synchronize: editing or pulling the checked-in skill changes the
user-global skill immediately. Codex normally detects skill changes; start a
new Codex session if updated metadata or behavior does not appear.

Ganglia also installs legacy custom-prompt aliases under `~/.codex/prompts/`.
The supported direct invocations are `$remember`, `$recall`, `$fafo`, and
`$skill-evolution`; only remember and recall have the legacy aliases
`/prompts:remember` and `/prompts:recall`. `/remember` and `/recall` are not
native top-level Codex slash commands.

## First-time setup

From the Ganglia checkout, run:

```sh
scripts/setup.sh
```

This command:

1. creates the ignored repository `.venv/` and installs pinned Python
   development dependencies;
2. initializes local Ganglia state;
3. installs the global skill and legacy-prompt symlinks;
4. configures the `ganglia-qmd` MCP server when the Codex CLI is available;
5. installs the pinned canvas dependency;
6. refreshes QMD best-effort; and
7. runs the complete repository verification gate.

Restart Codex after the first installation so skill discovery, MCP tools, and
global instructions are rebuilt in a new session.

## Verify propagation

Check the live skill targets:

```sh
readlink ~/.agents/skills/remember
readlink ~/.agents/skills/recall
readlink ~/.agents/skills/fafo
readlink ~/.agents/skills/skill-evolution
```

Both paths should resolve into this Ganglia checkout. Confirm that the installed
files are the same bytes as the checked-in files:

```sh
cmp .agents/skills/remember/SKILL.md ~/.agents/skills/remember/SKILL.md
cmp .agents/skills/recall/SKILL.md ~/.agents/skills/recall/SKILL.md
cmp .agents/skills/fafo/SKILL.md ~/.agents/skills/fafo/SKILL.md
cmp .agents/skills/skill-evolution/SKILL.md ~/.agents/skills/skill-evolution/SKILL.md
```

No output and exit status zero means propagation is current.

Validate the remaining machine integration:

```sh
codex mcp get ganglia-qmd
.venv/bin/python -c 'import yaml; print(yaml.__version__)'
scripts/verify.sh
```

The MCP command should be enabled and point to this checkout's
`scripts/qmd.sh mcp`. Verification should run the tests, artifact evaluations,
publication guard, Ganglia lint, and all four official skill validators without a
dependency-skip warning.

## Updating Ganglia

After pulling repository changes, normally run:

```sh
scripts/setup-python.sh
scripts/install-codex-commands.sh
scripts/install-qmd-mcp.sh
scripts/verify.sh
scripts/audit-security.sh
```

`scripts/verify.sh` runs deterministic offline source-security checks. The
separate security audit performs live PyPI, OSV, and npm advisory lookups and
must fail rather than silently skip when a feed is unavailable. The skill
symlinks do not need recreation when only skill contents change.
Rerun the installers to repair missing integration or to onboard a fresh
machine.

The installers intentionally refuse to overwrite unrelated existing paths. If
the checkout moves, first inspect every existing skill or prompt path with
`readlink`. Remove only confirmed Ganglia symlinks, then rerun
`scripts/install-codex-commands.sh`. An existing `ganglia-qmd` entry retains its
old command path; after confirming that the checkout moved, remove that one MCP
entry with `codex mcp remove ganglia-qmd` and rerun
`scripts/install-qmd-mcp.sh`.

QMD is an optional semantic accelerator. If local embedding fails because the
GPU backend cannot initialize, retry the Ganglia-owned maintenance command with
`QMD_FORCE_CPU=1`. `$remember` and `$recall` must still retain their mandatory
plain-text search floor.

## Global AGENTS.md alignment

Codex loads global guidance from `~/.codex/AGENTS.override.md` when that file is
non-empty; otherwise it loads `~/.codex/AGENTS.md`. Repository guidance is then
layered from the repository root toward the current working directory, with
nearer files taking precedence.

For this setup, keep the global file portable and cross-repository, and keep
Ganglia-specific implementation details in this repository's `AGENTS.md`. The
global Ganglia contract should say:

- use `$remember` for explicit retention, durable lessons, and checkpoints;
- use `$recall` for read-only retrieval and project resumption;
- treat `/prompts:remember` and `/prompts:recall` only as legacy aliases;
- keep QMD behind the skills and retain the text-search fallback;
- allow the remember-owned guarded auto-commit, but never an automatic push;
- keep identity, machine-specific paths, engagements, and session material in
  the ignored local layer; and
- refer to the checkout portably as `~/ganglia`, not as one user's absolute home
  path.

Update stale `/remember` and `/recall` spellings in the global file to
`$remember` and `$recall`. Before editing, confirm that no non-empty
`~/.codex/AGENTS.override.md` is shadowing the file.

Codex documentation defines hierarchical `AGENTS.md` discovery, but it does not
document `@path` as an instruction-file import mechanism. Treat lines such as
`@~/ganglia/MEMORY.md` and `@~/ganglia/local/MEMORY.local.md` as plain text unless
the running Codex product explicitly proves otherwise. Do not depend on them
to preload Ganglia content. Keep shared knowledge pull-on-demand through
`$recall`; if a personal rule must always apply, write the small rule directly
in the global AGENTS file rather than importing a generated memory index.

The default combined project-instruction budget is 32 KiB. Keep the global and
repository instruction files concise enough to fit together, or configure a
larger `project_doc_max_bytes` intentionally and restart Codex.

## Current-machine audit checklist

Use this checklist after setup or troubleshooting:

- [ ] The `remember`, `recall`, `fafo`, and `skill-evolution` symlinks under
      `~/.agents/skills/` point into this checkout.
- [ ] No unintended `~/.codex/AGENTS.override.md` shadows global guidance.
- [ ] Global guidance uses `$remember` and `$recall`, not nonexistent top-level
      slash commands.
- [ ] Global guidance does not rely on undocumented `@path` imports.
- [ ] `codex mcp get ganglia-qmd` is enabled and points to the current checkout.
- [ ] `.venv/bin/python` imports the pinned development and security tooling.
- [ ] `scripts/verify.sh` validates all four skills and passes offline Bandit,
      ShellCheck, and ESLint analysis.
- [ ] `scripts/audit-security.sh` passes current PyPI, OSV, and npm advisory
      checks before publication.
- [ ] A new Codex session exposes `$remember`, `$recall`, `$fafo`, and
      `$skill-evolution` through `/skills` or `$` mention completion.

## Official Codex references

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
