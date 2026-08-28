# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added a repository-owned Python virtual environment bootstrap with pinned
  development dependencies so skill validation runs reproducibly instead of
  being skipped when the system Python lacks PyYAML.
- Added a deterministic 20-case, schema-valid artifact evaluation gate covering
  materialization, review, verification, privacy, updates, protocol failures,
  and exact offline recall behavior.
- Added deterministic eligibility and language tracing for Python, JavaScript,
  and Bash artifacts, complete invocation/applicability contracts, and
  read-only recall mismatch reporting.
- Added closed-schema artifact matching that combines stable identity,
  applicability, lexical overlap, and optional semantic candidates while
  keeping judgment-heavy matches explicitly ambiguous.
- Added content-bound verification evidence and anonymous human-approval
  records so generated code is reviewed before execution checks and cannot be
  published unless checks pass and the exact bundle, evidence, and review
  revision were accepted.
- Added a closed-schema, content-bound artifact review protocol with independent
  scriptability, execution-risk, and retrieval-economics lenses plus a
  deterministic reducer that preserves blockers and bounds revision attempts.
- Added a schema-backed, content-bound tracer for preparing and explicitly
  accepting safe Python artifact bundles during remember, then returning their
  stored invocation or exact source bytes through read-only recall.
- Added a shared-only canvas preview to the README for the public repository.
- Portable OKF-lite knowledge folders with generated shared and private
  navigation indexes.
- Codex `remember` and `recall` skills for privacy-aware capture and tiered,
  read-only retrieval.
- MCP-first QMD semantic retrieval with an always-available plain-text search
  floor.
- Private, excluded-by-default Codex session cataloging for temporal recall.
- Live localhost knowledge canvas with link, tag, best-effort semantic
  relationships, and an explicit offline export mode.
- Repository setup, linting, verification, and allowlisted shared-memory
  auto-commit tooling.
- Apache License 2.0 licensing with project and third-party notices.

### Changed

- Made authoritative artifact revisions update one bundle in place, preserve
  superseded rationale, and require fresh content-bound review, verification,
  and approval before recall accepts the new bytes.
- Isolated sanctioned shared-memory commits from the caller's real Git index,
  preserving unrelated staged work while validating and committing complete
  artifact bundles through the existing allowlist and publication guard.
- Excluded local task and specification artifacts from version control.
- Refactored the canvas header around a responsive Brain-and-Canvas identity,
  centered search, quieter controls, and a clearer desktop/mobile hierarchy.
- Standardized every canvas control on one reusable outline-icon system and
  added a contract test to prevent mixed interactive icon styles returning.
- Made VS Code the canvas's primary source action through its documented file
  URL handler while retaining a default-application fallback.
- Restored transparent graph hit targets, color-map swatches, and connection
  menu styling after extracting the canvas UI sources.
- Restored accessible keyboard node selection, visible focus states, responsive
  side panels, touch-sized controls, and mobile-safe label placement.
- Reworked canvas discovery around searchable result navigation, knowledge-type
  filters, contextual guidance, explicit map controls, neighborhood emphasis,
  and a focused detail workflow.
- Removed generated navigation indexes from graph nodes while leaving them in
  QMD and plain-text retrieval.
- Fixed the graph background overlay intercepting pointer events, which blocked
  real node clicks from opening the inspector.
- Added the Brain logo as an inline favicon for live canvas responses and
  offline exports.
- Split the canvas presentation and interaction code into maintainable
  `bin/canvas.html` and `bin/canvas.js` source files; `canvas.py` injects graph
  data and runtime assets into that shell in memory.
- Replaced the default `.tmp/brain-canvas.html` build with a stable localhost
  server that automatically reloads for UI-source and QMD SQLite/WAL changes;
  offline single-file generation now requires an explicit `--output` path.
- Unified indexing and linting on one OKF-lite parser.
- Documented the public source/build boundary separately from private knowledge
  and disposable runtime artifacts.
- Refined the canvas into a responsive graph workspace with collection and
  session navigation, a persistent relationship inspector, accessible visual
  encoding, and reduced-motion support.

### Security

- Prevented shared artifact matching from scanning or emitting private local
  candidate metadata, and rejected partial or identity-mismatched updates.
- Made artifact validation fail closed on malformed metadata, missing or
  orphaned payloads, path escape, privacy-layer crossing, incompatible runtime
  or bundle placement, and content-digest mismatch before recall returns code.
- Expanded the fail-closed publication guard across every tracked or
  non-ignored candidate, including tooling and documentation, with checks for
  machine paths, private identity terms, personal email addresses, and common
  credential shapes.
- Added a read-only pre-publication audit for reachable Git blobs and
  commit-author identity metadata.
- Kept personal, engagement-specific, episodic, generated, and machine-local
  state outside the public Git surface through explicit ignore rules.
- Bound the live canvas to loopback by default so private all-scope graph data
  is not exposed on the local network accidentally, and reject non-local Host
  headers in that mode.
