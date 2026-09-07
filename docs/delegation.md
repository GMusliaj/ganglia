# Delegated reading and boilerplate drafts

This is a Codex port of the hook/script/skill separation in
[Spotify shunt](https://github.com/spotify/portal-ai-plugins/tree/3c24ca30ff63e1f5bbad1c43fe5324daff579123/plugins/shunt),
informed by [upstream issue #10](https://github.com/spotify/portal-ai-plugins/issues/10).
The source revision is recorded for reproducibility. The implementation uses
Python's standard library and Ganglia's existing verifier. No Portal, AiKA,
new package, account, auto-commit, or automatic hook installation is involved.

## Local setup and review

The shipped files are reviewable source. The hook template defaults to
**observe** and is not active just because this checkout contains it.

1. Review `bin/delegation.py`, `bin/delegation_codex.py`,
   `bin/delegation_common.py`, `bin/delegation_hook.py`, the two skills, and
   the evals below.
2. Create private `local/delegation.json` using
   [`delegation.example.json`](delegation.example.json). Replace each
   `EXAMPLE_MODEL_ID` with the exact model you want for that role. The
   `provider: codex` adapter uses the installed, authenticated Codex CLI and
   its `openai` provider; no model is silently selected. Availability and
   reasoning effort are checked with `model/list` immediately before use.
   Other providers are rejected, not simulated by a generic command runner.
3. Run an offline preview from the Ganglia root:

   ```sh
   .venv/bin/python bin/delegation.py --root . bulk-read --question "What gates does verification run?" --paths scripts/verify.sh
   ```

   Explicit paths are relative to `--root`. A preview reports the selected
   files, digest, limits and model, without printing source or contacting it.
   Add `--execute` before `bulk-read` to send those files to the configured
   worker. Existing task authorization still determines what data may be sent.
4. After reviewing the hook template, merge `hooks/delegation.json` into your
   ignored `.codex/hooks.json`, preserving existing hooks. Start a new Codex
   session and review/trust its definition through `/hooks`. Exercise observe
   mode first; change its command to `--mode enforce` only when satisfied.
   Hook commands resolve from the Git root, so this template is for Ganglia.
   For another repository, use the reviewed absolute Ganglia script path in
   that repository's private hook configuration. Do not copy the runtime.
5. Use `$bulk-reader` or `$code-writer` in a fresh session. Global skill links
   can be added through `scripts/install-codex-commands.sh` after review; this
   installer never activates the hooks. A missing worker mapping falls back
   to ordinary targeted reads, not to an unspecified model.

The port does not change existing remember/recall or FAFO behavior. Knowledge
still works with plain text search when worker models are unavailable.

## Boundaries and differences from upstream

The hook uses Codex's current `hookSpecificOutput` shape. Neutral success is
`{}`, which does not approve a tool on behalf of the user. In enforce mode,
large reads return `permissionDecision: deny`; malformed hook input exits 2.
The fixture contract independently rejects upstream's old top-level `allow`.
Codex still documents legacy `block` support, so the issue's claim that all
blocks are ignored is not treated as proven for Codex.

The default threshold is 350 returned lines or 50,000 bytes, aggregated over
recognized reads. Whitespace, quoted paths, multiple literal files, basic
`cd`/command chains, globs, common `head`/`tail` counts and `sed -n 'N,Mp'`
are covered. Quoted or escaped wildcard characters remain literal, including
paths such as `app/[id]/page.tsx`; unquoted globs still expand. Both line and
byte limits apply to `head -c` and `tail -c` over their selected byte ranges.
Small slices pass even in large files; a huge single line still hits the byte
ceiling. An identity pipe cannot hide a bulk read. A known
numeric `head`/`tail` filter bounds the inspected pipeline. Missing/unreadable
files pass through so the real tool reports their error. Mandatory AGENTS and
SKILL files remain fully readable.

Output redirection is conservatively counted, not exempted: stderr-only
redirections and destinations such as `/dev/stdout` can still expose the entire
read. Filters after an already sliced read do not reduce its measured extent.

This hook is a context guardrail, not an exhaustive shell parser or a security
sandbox. Shell substitutions, scripts/interpreters, arbitrary MCP readers and
hosted tools are outside its coverage. Recognized unsupported shell forms get
an advisory. `write_stdin` does not repeat PreToolUse; an interactive shell is
outside this routing boundary. Unbounded `rg` output also needs host judgment.
Quoted shell operators and complex shell control flow should use explicit
literal paths and small reads. Do not describe arbitrary commands as enforced.

The wrapper rejects missing mappings, placeholder IDs, unknown config fields,
unsupported providers, unavailable models, bad effort choices, escaping paths,
agent/credential files, binary inputs, and oversized serialized requests.
Payloads use JSON on stdin, avoiding argv-size limits and shell interpolation.
The byte and timeout limits are hard local limits. The worker token limit is
checked against backend usage notifications; **it is not a prepaid monetary
cap** and may detect an overspend only after tokens were consumed.

One call creates an ephemeral thread with no selected environment and one
turn. The adapter requests read-only execution, no approval grants, a reduced
tool surface, a pinned model/effort and no provider fallback; it rejects
warnings, tool items, reroutes and incomplete responses. Parent conversation
history is not replayed. Source text is sent only on `--execute`; the provider's
own retention policies still apply. Host hooks, rules, authentication and
managed restrictions are not bypassed. Runtime tools that escape documented
hook/environment coverage cannot be claimed safe by a prompt alone: live
activation needs the integration check below.

Reader responses include references for host spot-checking. Writer requests
require a reference and support additional source context. Drafts default to
stdout. `--target` creates only a new file, after validating a successful
response; existing targets and symlinks are rejected before a model call.
There is no force-overwrite switch. Only one enclosing Markdown fence is
removed; internal examples remain intact. Host review and source-repository
tests remain necessary before applying a draft.

## Evals and cost measurement

Offline evals make zero model calls:

```sh
.venv/bin/python scripts/eval_delegation.py
scripts/verify.sh
```

`tests/test_delegation.py` and `evals/delegation/routing-cases.json` cover the
issue #10 parser regressions, host JSON shape, CLI previews, role/model/effort
validation, single-turn protocol, reroutes, invalid output, deadlines, token
and byte limits, path boundaries, non-clobber writes and internal fences. An
independent fake worker process also exercises a large stdin payload, JSONL
framing, early usage notifications, final-only output and process cleanup.
These tests establish behavior under deterministic fixtures. They do not prove
that a live host loaded the hook or that a model reliably chooses the skill.

After mapping models, this optional command makes two live calls against a
public synthetic corpus, prints usage plus answer/draft for review, and parses
the generated Python without executing it:

```sh
.venv/bin/python scripts/eval_delegation.py --live --config local/delegation.json
```

Then test a real Codex session:

| Scenario | Expected behavior |
| --- | --- |
| Summarize exports in a large source file | Hook observes/denies full read; host uses bulk-reader and spot-checks references |
| Fix a bug at a known line | Host uses a small exact read and edits directly |
| Generate repetitive tests with reference and source | Worker returns a draft; host reviews and runs relevant tests |
| Read a small file or search a symbol | Direct read/search; no worker overhead |
| Mapped model unavailable or rerouted | Clear failure; no retry or expensive model fallback |
| File content asks worker to use tools or change its task | No tool execution; any attempted tool item is rejected; assess answer quality manually |

Do not inherit upstream's 82–94% or 90% savings numbers. Its published monorepo
measurements are not reproducible from its bundled fixtures. The port reports
actual payload/output bytes and backend worker input, cached-input and output
tokens. Repeating the corpus consumes worker usage every time, even when it
never enters the host context. Failed invocations may also consume usage.

For day-to-day savings, start with large comprehension tasks and predictable
boilerplate. Batch related questions into one call, keep answers bounded, reuse
answers, and use exact text search for follow-ups. Benchmark a matched host-only
run against the same task delegated, including host review, cache behavior,
worker usage, latency and correctness. `estimate_cost` in `bin/delegation.py`
supports explicit supplied API rates with cached inputs counted separately;
the live harness leaves money saved unknown. Subscription quota and API bills
are distinct measurements. A smaller host context alone proves neither lower
total tokens nor a dollar saving.

## Verified contracts and remaining live checks

The adapter was implemented against `codex-cli 0.153.4`'s generated v2 schemas
and current [Codex App Server documentation](https://learn.chatgpt.com/docs/app-server).
The hook format and activation steps follow
[Codex hooks](https://learn.chatgpt.com/docs/hooks).
The wrapper uses `model/list`, `config/read`, `thread/start`, `turn/start`,
usage/item notifications, and the `model/rerouted` event. Changes to this
experimental protocol must fail explicitly and be revalidated.

Before declaring live deployment ready, verify the selected models and effort,
effective tool/environment restriction, ephemeral thread behavior, hook trust,
and the exact read/generate scenarios above on the installed client. Offline
tests and generated schemas do not establish these runtime facts. No live
inference or host-hook activation is part of the default verification gate.
