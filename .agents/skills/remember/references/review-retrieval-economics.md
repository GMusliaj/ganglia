# Retrieval-economics review lens

Review only the supplied immutable artifact review packet. Do not edit files,
execute the payload, or repair the candidate.

Challenge whether the stored manifest and invocation actually eliminate later
synthesis. Look for missing runtime assumptions, working-directory dependence,
implicit environment inputs, placeholders requiring interpretation,
incomplete applicability constraints, ambiguous outputs or exit behavior, and cases where recall
would need to explain, compare, regenerate, or adapt code before use.

Report only material, grounded findings tied to payload lines or the manifest
path. Return only one JSON object conforming to
`../schemas/review-contribution.schema.json`. Copy every identity field from the
packet exactly, set `producer` to `retrieval-economics`, and use `block` only
with at least one `blocking` finding.
