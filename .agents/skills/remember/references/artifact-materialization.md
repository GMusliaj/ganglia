# Artifact materialization

Use this branch only after keep-worthiness, duplicate search, and privacy
routing establish that the operation should be retained and where it belongs.
The current tracer accepts only a new, read-only Python CLI artifact. It does
not update existing bundles or authorize mutation.

## 1. Generate into ignored staging

Create both of these under the repository's ignored `.tmp/` directory:

- a Python script that implements the operation, supports `--help`, has
  deterministic exit behavior, and performs no mutation merely to show help;
- an artifact-candidate JSON object that validates against
  `schemas/artifact-candidate.schema.json`, including explicit arguments and
  expected stdout for one focused test and one representative run.

Use safe placeholders rather than credentials, identity, private hosts, or
machine-specific paths. The candidate's invocation must be repository-relative
and use `brain-root` as its working-directory contract. The payload filename
must share its stem and directory with the intended Markdown manifest.

## 2. Prepare without writing the bundle

From the Brain root, run:

```sh
python3 bin/artifact_bundle.py prepare \
  --candidate .tmp/<candidate>.json \
  --payload .tmp/<payload>.py \
  --manifest <routed-folder>/<artifact>.md \
  --evidence-output .tmp/<preliminary-evidence>.json
```

The command validates the candidate schema, computes the content-bound bundle
digest, and compiles the Python source in memory. It does not execute generated
code or write the manifest or payload into the knowledge layer. Help, focused,
and representative execution checks are recorded as `authorization-blocked`
until source review agrees.

If syntax inspection fails, do not review or publish the bundle. Keep or refine
the prose memory, or repair the staged candidate and prepare a new digest.

## 3. Run content-bound challenge review

Before asking for acceptance, create one immutable review-packet JSON object in
`.tmp/` that validates against `schemas/review-packet.schema.json`. Set
`base_revision` to `0`, `max_revisions` to `3`, and include the exact prepared
bundle digest, the full payload source, stored invocation, safety contract, and
prepare-time verification status. Use `evidence_digest: none` because execution
evidence does not exist until source review agrees; reviewer agreement must not
promote verification.

Spawn three independent subagents against that same packet:

- the scriptability reviewer reads
  [review-scriptability.md](review-scriptability.md);
- the execution-risk reviewer reads
  [review-execution-risk.md](review-execution-risk.md);
- the retrieval-economics reviewer reads
  [review-retrieval-economics.md](review-retrieval-economics.md).

Each reviewer is read-only and returns only one JSON object validating against
`schemas/review-contribution.schema.json`. Save the contributions separately in
`.tmp/`; never let reviewers mutate the packet or each other's output.

Reduce them deterministically:

```sh
python3 scripts/reduce_artifact_review.py \
  --packet .tmp/<review-packet>.json \
  --contribution .tmp/<scriptability>.json \
  --contribution .tmp/<execution-risk>.json \
  --contribution .tmp/<retrieval-economics>.json
```

The reducer rejects schema drift, stale revisions, wrong review or artifact
identities, duplicate producers, and bundle or evidence mismatches. Continue
only when the schema-valid state reports `agreement: true` and preserves no
blockers.

When blocked, repair the staged candidate only if the finding is grounded and
actionable, prepare a new bundle digest, increment `base_revision`, and run
three fresh reviews. Never reuse contributions across a digest change. Stop
after three revisions; an exhausted candidate is not ready.

## 4. Run empirical verification

Only after clean review agreement, run the declared non-mutating checks:

```sh
python3 bin/artifact_bundle.py verify \
  --candidate .tmp/<candidate>.json \
  --payload .tmp/<payload>.py \
  --manifest <routed-folder>/<artifact>.md \
  --review-state .tmp/<review-state>.json \
  --evidence-output .tmp/<evidence>.json
```

The command reruns in-memory syntax validation, then executes `--help`, the
declared focused test, and the declared representative run from ignored staging.
It emits schema-valid evidence bound to the exact bundle. Failed, unavailable,
or authorization-blocked checks remain `unverified`; agreement cannot change
their status.

## 5. Obtain explicit acceptance

Show the user the staged script, exact invocation, verification evidence,
routed destination, bundle digest, evidence digest, and agreed review revision.
Ask whether to accept those exact identities. Do not publish or auto-commit
executable knowledge before an explicit yes.

After an explicit yes, record the decision without identity or personal data:

```sh
python3 scripts/record_artifact_approval.py \
  --evidence .tmp/<evidence>.json \
  --review-state .tmp/<review-state>.json \
  --decision accepted \
  --output .tmp/<approval>.json
```

Any source or candidate change after review creates a new digest and requires a
new preparation result and new acceptance.

## 6. Publish the accepted bytes

After explicit acceptance, run the same inputs through:

```sh
python3 bin/artifact_bundle.py publish \
  --candidate .tmp/<candidate>.json \
  --payload .tmp/<payload>.py \
  --manifest <routed-folder>/<artifact>.md \
  --evidence .tmp/<evidence>.json \
  --review-state .tmp/<review-state>.json \
  --approval .tmp/<approval>.json
```

The command revalidates the candidate, evidence, review agreement, and human
approval; refuses any identity mismatch, unverified evidence, rejection, or
existing target; then writes the canonical Markdown manifest, exact payload,
sanitized evidence, agreed review state, and approval record. Its JSON result
must validate against `schemas/artifact-operation-result.schema.json`.

Continue with the normal shared or local indexing path. For shared knowledge,
only `scripts/auto-commit.sh` owns the commit exception. It validates shared
bundle closure before committing and uses an isolated Git index so unrelated
staged work cannot enter the memory commit. Never push.
