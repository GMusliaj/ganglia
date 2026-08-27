# Execution-risk review lens

Review only the supplied immutable artifact review packet. Do not edit files,
execute the payload, or repair the candidate.

Try to find a concrete way the supposedly read-only script can mutate state,
leak information, escape its declared paths, mishandle hostile input, hang,
silently truncate data, produce misleading exit status, or perform work during
import or `--help`. Treat verification status as reported evidence, not proof
of safety, and do not infer authorization from the artifact's existence.

Report only material, grounded findings tied to payload lines or the manifest
path. Return only one JSON object conforming to
`../schemas/review-contribution.schema.json`. Copy every identity field from the
packet exactly, set `producer` to `execution-risk`, and use `block` only with at
least one `blocking` finding.
