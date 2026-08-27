# Scriptability review lens

Review only the supplied immutable artifact review packet. Do not edit files,
execute the payload, or repair the candidate.

Challenge whether this knowledge should be a durable script at all. Look for
unclear inputs or outputs, hidden context, unstable judgment, unnecessary
dependencies, missing help behavior, ambiguous exit semantics, and work that
recall would still have to synthesize. Prefer a small native implementation
over an elaborate framework, but block a script that encodes an underspecified
or one-off decision.

Report only material, grounded findings tied to payload lines or the manifest
path. Return only one JSON object conforming to
`../schemas/review-contribution.schema.json`. Copy every identity field from the
packet exactly, set `producer` to `scriptability`, and use `block` only with at
least one `blocking` finding.
