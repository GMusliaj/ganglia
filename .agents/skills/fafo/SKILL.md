---
name: fafo
description: Resolve a consequential repository uncertainty with one bounded local experiment and an evidence-backed terminal result. Use for explicit FAFO requests or when competing explanations block progress and a small reversible probe can decide between them. Do not use for design prototyping, test-first implementation, review, destructive actions, external mutations, or an operation already available through recall.
---

# FAFO

Turn one consequential uncertainty into the smallest authorized local
experiment that can settle it. FAFO is an evidence loop, not a generic command
runner and not permission to mutate anything outside the user's request.

## Route before experimenting

Use FAFO only when all of these are true:

- a concrete empirical uncertainty blocks the task;
- an observable local intervention can distinguish the competing explanations;
- the intervention is bounded, reversible, and inside the current
  authorization; and
- reading the relevant repository state and documented contract did not
  already answer the question.

Route design exploration to `prototype`, requested test-first implementation to
`tdd`, confidence challenges to `adversarial-review`, unsettled decision trees
to `grilling`, and exact stored operations to `recall`. Read current official
documentation before probing a changing API. Do not use FAFO for deployment,
publication, purchase, deletion, credential use, policy bypass, destructive
work, or external mutation.

## Mandatory experiment contract

Before executing the probe, create an ignored
`.tmp/fafo/<experiment-id>.plan.json` and validate it with
the schema beside this skill:

```text
python3 <fafo-skill-dir>/scripts/experiment_contract.py validate-plan \
  --plan .tmp/fafo/<experiment-id>.plan.json
```

Resolve the script relative to this `SKILL.md`; do not assume a username or
copy it into the target repository.

The closed plan contract requires:

- the uncertainty, documented contracts, baseline, and independent success and
  failure conditions;
- an effect class limited to `read-only`, `temporary-local`, or
  `repository-local`, with the exact working directory and targets;
- ownership and dirty-state checks proving that unrelated changes do not
  overlap the targets;
- preview evidence for repository mutations and the precise authorization
  basis;
- rollback or compensation, retry semantics, state reconciliation, and an
  independent postcondition; and
- no more than five actions, an elapsed-time limit, a resource limit, and a
  stop condition.

If the intended intervention cannot pass the plan validator, do not run it.
Record the inspected scope in a valid no-action plan and terminate as
`safety-blocked`. Do not run first and fill in the contract afterward. The
validator proves only that required fields and fail-closed states are present;
use repository evidence and judgment to verify that their contents are true.

## Execute and reconcile

1. Run the smallest action allowed by the validated plan. Each retry consumes
   another action from the budget.
2. Stop at the first decisive result or stop condition. Never widen the scope
   because a probe was inconclusive.
3. After a timeout, interruption, indeterminate command, or failed rollback,
   inspect the actual target state before any retry or adaptation. Do not infer
   failure from missing output or success from exit status alone.
4. Preserve requested repository changes. Restore temporary experimental state
   and never overwrite unrelated work.
5. Check the independent postcondition and separate direct observations from
   inference.

## Mandatory terminal receipt

Every invocation ends in exactly one state: `verified`, `falsified`,
`inconclusive`, `authorization-blocked`, `safety-blocked`, or `superseded`.

Write an ignored `.tmp/fafo/<experiment-id>.result.json`, bind it to the exact
plan digest, and validate it with:

```text
python3 <fafo-skill-dir>/scripts/experiment_contract.py validate-result \
  --plan .tmp/fafo/<experiment-id>.plan.json \
  --result .tmp/fafo/<experiment-id>.result.json
```

The result records sanitized action summaries, observations, postcondition
evidence, reconciliation state, rollback status, the conclusion, and remaining
uncertainty. Never retain raw reasoning, unrestricted traces, identity,
credentials, customer data, private hostnames, or engagement details.

## Durable handoffs

The receipt is task evidence, not a second knowledge or execution system.

- If the user explicitly asks to retain a stable repeatable operation, hand it
  to `remember`; do not create a FAFO-specific executor or silently store it.
- If the result reveals a reusable success or failure pattern for a skill,
  capture only sanitized structured evidence through `skill-evolution`.
  Recurrence requires the same signal across at least two distinct task IDs;
  one result cannot justify a skill change.

## Output

Lead with the terminal state and answer the uncertain claim. Include the plan
digest, experiment performed, decisive observations, postcondition, scope and
budget used, reconciliation, rollback status, and remaining uncertainty. If no
safe decisive probe exists, report the smallest missing authorization or
evidence instead of improvising.
