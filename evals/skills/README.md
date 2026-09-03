# Skill evaluator adapters

Each adapter evaluates a baseline or candidate skill snapshot without changing
the repository or an external system. `bin/skill_evolution.py` invokes an
executable adapter as:

```text
evals/skills/<adapter> <configured arguments> --skill-path <snapshot-directory>
```

Adapters use stable case IDs and deterministic fixtures, write exactly one
closed-schema `skill-eval-result` JSON object to stdout, and exit nonzero when
the evaluation itself is unavailable. The checked-in adapters enforce minimum
instruction contracts; they do not prove runtime agent behavior. Prefer fixed
behavioral cases over wording checks when a stable offline harness is available.
The complete contract and result example are in
`.agents/skills/skill-evolution/references/workflow.md`.
