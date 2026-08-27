---
type: decision
title: QMD is the retrieval ceiling, not the floor
description: Semantic search improves recall, while repository-wide text search remains the required fallback and source of truth.
tags: [knowledge-management, qmd, retrieval]
date: 2026-08-27
---

# QMD is the retrieval ceiling, not the floor

## Active

- The `brain` QMD collection spans the entire repository, including gitignored
  local memory.
- Recall tries QMD first for semantic candidates and always runs repository-wide
  text search as the deterministic floor.
- Results from both layers are deduplicated by path and ranked together.
- QMD absence, model-download failure, or a stale collection must not make
  knowledge unavailable.
- Markdown files, not the QMD database, are canonical.

This preserves local semantic retrieval without turning optional generated
infrastructure into a dependency for memory.

The same boundary applies to the
[knowledge canvas](canvas-semantic-edges-are-best-effort.md): link and tag edges
remain available when semantic vectors cannot be decoded.

## Source

[Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
and the Brain retrieval requirements.
