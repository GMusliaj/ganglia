---
name: skill-evolution
description: Turn recurrent sanitized task evidence into one atomic repo-local Codex skill proposal, evaluate it against a deterministic baseline, and apply it only after strict score improvement, no regressions, publication checks, and explicit human approval. Use when asked to evolve, improve, or learn changes to a skill from repeated evidence. Do not use for one-off fixes, ungated self-modification, or global skill installation.
---

# Skill Evolution

Evolve one Ganglia-managed skill through a private evidence layer and a
content-bound human gate. Run operations from the Ganglia checkout at `~/ganglia`
and read [the workflow reference](references/workflow.md) before preparing or
applying a proposal.

The outer-loop architecture explicitly adapts Tang et al.'s
[WikiSkill](https://arxiv.org/html/2608.27454v1) framework. Read the workflow
reference's [prior-art section](references/workflow.md#prior-art-and-deliberate-deviations)
for what Ganglia adopts, changes, and does not claim to implement.

## Non-negotiable boundaries

- The target is exactly one repository-local
  `.agents/skills/<skill-name>/SKILL.md` file.
- Evidence, generated patterns, snapshots, evaluations, approvals, impact
  history, and rollback records stay in ignored `local/skill-evolution/`.
- Candidate files and operation inputs stay in ignored `.tmp/` until applied.
- Never retain raw reasoning, unrestricted transcripts, identity, credentials,
  customer data, private hostnames, or unsanitized command output.
- One task cannot establish a recurrent pattern. Require the same signal key
  across at least two distinct task IDs.
- Evaluators must be deterministic, executable adapters under `evals/skills/`.
  They must not mutate the repository or an external system.
- Never edit the active skill while preparing or evaluating a proposal.
- A human acceptance cannot override a rejected score gate.
- Applying does not commit or push.

## Workflow

1. Capture sanitized evidence after a real task, then consolidate the relevant
   skill. Stop if the supporting pattern is not recurrent.
2. Inspect the active skill, recurrent pattern files, and evaluator. Create one
   complete candidate `SKILL.md` under `.tmp/`; do not patch the live skill.
3. Prepare the proposal. This snapshots the baseline, candidate, and evaluator
   by digest.
4. Evaluate the proposal. Acceptable means candidate score is strictly greater
   than baseline and no case that passed at baseline regresses.
5. Present the proposal ID, baseline and candidate scores, delta, regressions,
   target path, and exact candidate digest. Ask for explicit human acceptance
   of that digest. Stop without recording acceptance unless the answer is
   affirmative.
6. Record the human decision. Apply only an accepted proposal using the exact
   candidate digest.
7. Run `scripts/verify.sh`. If verification fails because of the applied skill,
   immediately run the proposal rollback operation and report both outputs.
8. On subsequent real tasks, attribute sanitized outcome evidence to the active
   proposal and remeasure its impact before preparing another proposal.
9. Update `CHANGELOG.md` for an applied material skill change. Do not commit
   unless the user separately requested a commit.

## Result reporting

For a proposal, lead with `accepted` or `rejected` and the score comparison.
For an application, state the target path, candidate digest, verification
result, and that the change is uncommitted. For rollback, state the restored
digest and why rollback was required.
