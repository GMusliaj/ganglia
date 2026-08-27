# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Portable OKF-lite knowledge folders with generated shared and private
  navigation indexes.
- Codex `remember` and `recall` skills for privacy-aware capture and tiered,
  read-only retrieval.
- MCP-first QMD semantic retrieval with an always-available plain-text search
  floor.
- Private, excluded-by-default Codex session cataloging for temporal recall.
- Offline interactive knowledge canvas with link, tag, and best-effort semantic
  relationships.
- Repository setup, linting, verification, and allowlisted shared-memory
  auto-commit tooling.
- Apache License 2.0 licensing with project and third-party notices.

### Changed

- Unified indexing and linting on one OKF-lite parser.
- Documented the public source/build boundary separately from private knowledge
  and disposable runtime artifacts.
- Refined the canvas into a responsive graph workspace with collection and
  session navigation, a persistent relationship inspector, accessible visual
  encoding, and reduced-motion support.

### Security

- Expanded the fail-closed publication guard across every tracked or
  non-ignored candidate, including tooling and documentation, with checks for
  machine paths, private identity terms, personal email addresses, and common
  credential shapes.
- Added a read-only pre-publication audit for reachable Git blobs and
  commit-author identity metadata.
- Kept personal, engagement-specific, episodic, generated, and machine-local
  state outside the public Git surface through explicit ignore rules.
