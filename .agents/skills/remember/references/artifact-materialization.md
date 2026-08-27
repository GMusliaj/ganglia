# Artifact materialization

Use this branch only after keep-worthiness and privacy routing establish that
the operation should be retained and where it belongs. The tracer accepts
Python, JavaScript, and Bash CLI artifacts, can enforce a preview default for
mutating operations, and can update an authoritative bundle in place. It never
authorizes external mutation.

## 1. Trace eligibility and language

Create a closed-schema request describing stability, repeatability,
completeness, operational versus conceptual nature, defined contract fields,
the natural ecosystem, and locally available languages. Run:

```sh
python3 bin/artifact_bundle.py trace --request .tmp/<trace-request>.json
```

Only continue when the schema-valid result says `eligible: true`. Unstable,
one-off, conceptual, checkpoint, or incomplete knowledge remains prose. Use
the returned language: the native ecosystem wins when available; a generic
operation prefers Python, then JavaScript, then Bash for portability. Do not
substitute a non-native runtime when the requested ecosystem is unavailable.

## 2. Generate into ignored staging

Create both of these under the repository's ignored `.tmp/` directory:

- a `.py`, `.mjs`, or `.sh` script matching the traced language that implements
  the operation, supports `--help`, has deterministic exit behavior, and
  performs no mutation merely to show help;
- an artifact-candidate JSON object that validates against
  `schemas/artifact-candidate.schema.json`, including explicit arguments and
  expected stdout for one focused test and one representative run. Record
  declared arguments, safe environment placeholders, output and exit
  behavior, applicability constraints, dependencies, and mutation default.

Prefer the target ecosystem's normal language and a standard-library-only
implementation when that does not compromise correctness. A mutating artifact
must default to preview, and its stored invocation plus both executable checks
must explicitly select `--preview`. Artifact existence never grants execution
authority.

Use safe placeholders rather than credentials, identity, private hosts, or
machine-specific paths. The candidate's invocation must be repository-relative
and use `brain-root` as its working-directory contract. The payload filename
must share its stem and directory with the intended Markdown manifest.

## 3. Find the authoritative target

Ask QMD through the configured MCP server for semantic candidates when it is
available, and always retain the normal text-search floor. Pass the
repository-relative semantic candidate paths, if any, to the deterministic
matcher:

```sh
python3 bin/artifact_bundle.py match \
  --candidate .tmp/<candidate>.json \
  --manifest <routed-folder>/<artifact>.md \
  --semantic-candidate <candidate-manifest>
```

The closed-schema result combines stable artifact identity, applicability
metadata, lexical overlap, and supplied semantic candidates. Only one valid
bundle with the exact `artifact_id` is `authoritative`. A lexical,
applicability, or semantic candidate is `ambiguous` even when it is the only
candidate; do not let a model silently merge it. Stop and ask the user to pick
the authoritative operation or retain a distinct artifact.

A shared destination searches and emits shared candidates only. It ignores
local semantic paths so private paths or metadata cannot enter shared output.
A local destination may search both local and shared knowledge.

For `authoritative`, use `selected_manifest` as the manifest for every
remaining command. For `no-match`, keep the routed new destination.

## 4. Prepare without writing the bundle

From the Brain root, run:

```sh
python3 bin/artifact_bundle.py prepare \
  --candidate .tmp/<candidate>.json \
  --payload .tmp/<payload>.<py|mjs|sh> \
  --manifest <routed-folder>/<artifact>.md \
  --evidence-output .tmp/<preliminary-evidence>.json
```

The command validates the candidate schema, computes the content-bound bundle
digest, and performs the language's non-executing syntax check. It does not run
the payload or write the manifest or payload into the knowledge layer. Help, focused,
and representative execution checks are recorded as `authorization-blocked`
until source review agrees.

If syntax inspection fails, do not review or publish the bundle. Keep or refine
the prose memory, or repair the staged candidate and prepare a new digest.

## 5. Run content-bound challenge review

Before asking for acceptance, create one immutable review-packet JSON object in
`.tmp/` that validates against `schemas/review-packet.schema.json`. Set
`base_revision` to `0`, `max_revisions` to `3`, and include the exact prepared
bundle digest, the full payload source, language/runtime, dependencies,
arguments, environment placeholders, outputs, exit behavior, applicability,
stored invocation, safety and mutation-default contracts, and prepare-time
verification status. Use `evidence_digest: none` because execution
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

## 6. Run empirical verification

Only after clean review agreement, run the declared non-mutating checks:

```sh
python3 bin/artifact_bundle.py verify \
  --candidate .tmp/<candidate>.json \
  --payload .tmp/<payload>.<py|mjs|sh> \
  --manifest <routed-folder>/<artifact>.md \
  --review-state .tmp/<review-state>.json \
  --evidence-output .tmp/<evidence>.json
```

The command reruns syntax validation, then executes `--help`, the
declared focused test, and the declared representative run from ignored staging.
It emits schema-valid evidence bound to the exact bundle. Failed, unavailable,
or authorization-blocked checks remain `unverified`; agreement cannot change
their status.

## 7. Obtain explicit acceptance

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

## 8. Publish the accepted bytes

After explicit acceptance, run the same inputs through:

```sh
python3 bin/artifact_bundle.py publish \
  --candidate .tmp/<candidate>.json \
  --payload .tmp/<payload>.<py|mjs|sh> \
  --manifest <routed-folder>/<artifact>.md \
  --evidence .tmp/<evidence>.json \
  --review-state .tmp/<review-state>.json \
  --approval .tmp/<approval>.json
```

The command revalidates the candidate, evidence, review agreement, and human
approval; refuses any identity mismatch, unverified evidence, rejection,
partial existing bundle, or unchanged update. A new artifact writes the whole
bundle. An authoritative update replaces that same bundle in place, records
the prior digest and rationale under `## Superseded`, and keeps one current
ready manifest for recall. Because every candidate or payload change creates a
new bundle digest, old review, evidence, and approval records fail identity
validation and cannot authorize the update. The JSON result must validate
against `schemas/artifact-operation-result.schema.json`.

Continue with the normal shared or local indexing path. For shared knowledge,
only `scripts/auto-commit.sh` owns the commit exception. It validates shared
bundle closure before committing and uses an isolated Git index so unrelated
staged work cannot enter the memory commit. Never push.

Repository acceptance also runs `python3 scripts/eval_artifacts.py`. Its
schema-valid corpus and result check materialization decisions, language and
manifest quality, update and protocol safety, and exact read-only recall
without relying on prompt wording.
