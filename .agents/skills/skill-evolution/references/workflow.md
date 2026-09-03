# Skill-evolution workflow

Run commands from the Ganglia repository root with its intended Python
environment:

```text
.venv/bin/python bin/skill_evolution.py <operation> ...
```

All inputs use closed JSON schemas from `schemas/`; unknown fields fail.
Operations print one JSON result on success and `skill evolution error: ...`
to stderr on failure.

## Prior art and deliberate deviations

This workflow explicitly adapts **WikiSkill: Compiling Agent Experience into
Persistent Knowledge for Skill Evolution** by Liyan Tang, Cyrus Rashtchian,
Chun-Sung Ferng, Andrew Tomkins, Da-Cheng Juan, and Tu Vu
([arXiv:2608.27454v1](https://arxiv.org/html/2608.27454v1)). WikiSkill is the
conceptual source for separating execution experience, persistent accumulated
knowledge, and executable skills, then using consolidated patterns to inform
atomic skill proposals, validation gating, rollback, and an impact history.

Ganglia adopts these ideas:

- separate evidence, persistent pattern/wiki, and active skill layers;
- retain accumulated patterns when a candidate skill is rejected;
- propose one skill change at a time;
- compare candidate and baseline performance before acceptance; and
- preserve proposal outcomes so later evolution can avoid repeating failures.

Ganglia deliberately changes the research design:

| WikiSkill | Ganglia skill evolution |
| --- | --- |
| Immutable, complete execution trajectories, including reasoning and tool interactions | Closed-schema, sanitized evidence summaries; raw reasoning and unrestricted traces are forbidden |
| Autonomous Wiki Maintainer and ReAct Skill Proposer agents | Explicit operator-invoked operations; no autonomous background evolution loop |
| Incremental patch to one targeted skill | Complete candidate for exactly one repo-local `SKILL.md`; supporting files use normal review |
| Validation improvement controls acceptance and rollback | Strict score improvement plus no baseline-case regression, publication checks, and explicit human acceptance of the exact digest |
| Persistent validation impact tracker | Content-bound gate history plus attributed outcomes from later real tasks |

Ganglia does **not** claim to reproduce WikiSkill's benchmark optimizer,
train/validation/test protocol, full skill injection, `PURPOSE.md` convention,
model-transfer results, or reported performance gains. Its checked-in evaluators
enforce local instruction contracts and must not be interpreted as replication
of the paper's experiments. No paper prompt or implementation code is copied by
this workflow.

## 1. Capture sanitized evidence

Create `.tmp/skill-evidence.json`:

```json
{
  "schema_version": 1,
  "kind": "skill-evidence",
  "skill_name": "fafo",
  "task_id": "bounded-parser-check",
  "outcome": "passed",
  "summary": "A minimal parser probe distinguished malformed input from transport failure.",
  "signals": [
    {
      "key": "contract-first-probe",
      "kind": "success",
      "summary": "Reading the input contract before one bounded probe isolated the failure."
    }
  ],
  "checks": [
    {
      "id": "parser-probe",
      "command": "repository parser check with an example fixture",
      "status": "passed",
      "observation": "The documented valid fixture passed and the malformed fixture failed."
    }
  ]
}
```

Use summaries, not raw logs. Use unmistakable placeholders rather than
secret-shaped examples.

For evidence from a real task after a proposal has been applied, add that
active `proposal_id`. Attribution is accepted only while the target still
matches the applied candidate. Pre-proposal evidence omits this field.

```text
.venv/bin/python bin/skill_evolution.py capture \
  --input .tmp/skill-evidence.json
```

The operation sanitizes machine paths, non-example email addresses, and known
credential shapes before writing an immutable, content-addressed record under
`local/skill-evolution/evidence/<skill>/`.

## 2. Consolidate recurrent patterns

```text
.venv/bin/python bin/skill_evolution.py consolidate --skill fafo
```

The default threshold is two distinct task IDs for the same signal key. The
generated local wiki is replaced deterministically from the eligible evidence;
the append-only impact history is separate. A signal observed repeatedly in
one task does not qualify.

## 3. Prepare one atomic proposal

Write the complete candidate to a path such as
`.tmp/skill-candidates/fafo/SKILL.md`. Prepare `.tmp/skill-proposal.json`:

```json
{
  "schema_version": 1,
  "kind": "skill-proposal-input",
  "skill_name": "fafo",
  "target_skill": ".agents/skills/fafo/SKILL.md",
  "candidate_skill": ".tmp/skill-candidates/fafo/SKILL.md",
  "pattern_keys": ["contract-first-probe"],
  "rationale": "The same bounded-probe success recurred across independent tasks.",
  "evaluator": {
    "path": "evals/skills/evaluate_fafo.py",
    "arguments": [],
    "timeout_seconds": 60
  }
}
```

```text
.venv/bin/python bin/skill_evolution.py prepare \
  --input .tmp/skill-proposal.json
```

Preparation validates frontmatter, target confinement, recurrent pattern
support, executable evaluator placement, and the publication guard. It stores
baseline and candidate snapshots. For a new skill the baseline snapshot is an
empty `SKILL.md`; its evaluator must treat that as the no-skill baseline.

Only `SKILL.md` is evolvable. Supporting scripts, schemas, references, assets,
and evaluator changes require an ordinary reviewed repository change. This
keeps each generated proposal atomic and inspectable.

## 4. Evaluator adapter contract

The harness invokes:

```text
evals/skills/<adapter> <configured arguments> --skill-path <snapshot-directory>
```

The adapter must:

- accept the final `--skill-path` argument;
- use fixed cases and deterministic scoring;
- avoid repository or external mutations;
- write exactly one JSON object to stdout;
- use stderr for diagnostics and exit nonzero on evaluator failure;
- return unique, stable case IDs;
- treat unavailable dependencies as evaluator failure, not a passing case.

Required stdout shape:

```json
{
  "schema_version": 1,
  "kind": "skill-eval-result",
  "score": 0.75,
  "cases": [
    {
      "id": "safe-boundary",
      "passed": true,
      "score": 1.0,
      "summary": "The skill forbids irreversible experiments without authorization."
    }
  ]
}
```

Do not score mere phrase presence as task quality. Prefer fixed task fixtures,
recorded non-sensitive outputs, schema checks, and behavioral assertions. The
checked-in FAFO and evolution adapters are minimum instruction-contract checks,
not proof of agent behavior. Add fixed behavioral cases through an ordinary
reviewed evaluator change when a stable offline harness exists. The adapter
itself is content-bound by digest; changing it invalidates the proposal.

## 5. Evaluate and inspect the gate

```text
.venv/bin/python bin/skill_evolution.py evaluate \
  --proposal-id <proposal-id>
```

Both snapshots run through the same evaluator. The gate accepts only when:

```text
candidate.score > baseline.score
and regressions == []
```

A regression is any stable case ID that passed at baseline but is missing or
failed for the candidate. Rejection leaves the active skill untouched.

## 6. Record explicit human decision

Show the user the proposal ID, target, candidate digest, score delta, and
regressions before recording a decision.

```text
.venv/bin/python bin/skill_evolution.py approve \
  --proposal-id <proposal-id> \
  --decision accepted
```

Use `rejected` when the user declines. Acceptance is bound to the candidate and
evaluation digests and cannot override a rejected automated gate.

## 7. Apply and verify

```text
.venv/bin/python bin/skill_evolution.py apply \
  --proposal-id <proposal-id> \
  --confirm-digest sha256:<candidate-digest>
```

Application fails if the active baseline, candidate, evaluator, evaluation, or
approval changed. It writes atomically, runs the full publication guard, and
restores the prior skill if the guard fails. It never commits or pushes.

Run `scripts/verify.sh` immediately after application. If that verification
fails because of the applied candidate:

```text
.venv/bin/python bin/skill_evolution.py rollback \
  --proposal-id <proposal-id>
```

Rollback succeeds only while the active target still matches the applied
candidate digest, preventing it from overwriting later human edits.

## 8. Remeasure post-application impact

After subsequent real tasks, capture their sanitized evidence with the active
`proposal_id`, then aggregate distinct task outcomes:

```text
.venv/bin/python bin/skill_evolution.py impact \
  --proposal-id <proposal-id>
```

The content-addressed impact snapshot records attributed evidence IDs, distinct
passed and failed task counts, pass rate, and success/failure signal counts. It
is accepted only while the proposal remains the active skill. Use this result
and recurrent signals as evidence for or against the next proposal; do not
interpret instruction-contract scores alone as runtime effectiveness.
