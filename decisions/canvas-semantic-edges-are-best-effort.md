---
type: decision
title: Canvas semantic edges are best-effort
description: The offline knowledge canvas keeps Markdown links and tags authoritative while treating QMD vector similarity as a degradable enhancement.
tags: [knowledge-management, qmd, retrieval, visualization]
date: 2026-08-27
---

# Canvas semantic edges are best-effort

## Active

- `bin/canvas.py` renders a disposable, offline HTML view of Brain knowledge.
- Documents and tags are nodes. File-relative Markdown links, wikilinks, tag
  membership, and semantic similarity are independently visible edge types.
- The default graph is restricted to the shared knowledge layer. Local content
  appears only through an explicit `--scope all` request.
- D3 is the sole browser dependency and is installed under `bin/`; its minified
  runtime is inlined so the generated canvas does not need network access.
- Semantic similarity is read from QMD's internal SQLite vector tables. That
  schema is undocumented, so decode failures emit one warning and the canvas
  still renders link and tag edges.
- Markdown remains canonical and the generated `.tmp/brain-canvas.html` is
  ignored. This follows [QMD's ceiling-not-floor decision](retrieval-tiering-qmd-is-ceiling-not-floor.md).

## Source

The Brain canvas reference implementation and local QMD 2.8.3 schema inspection.
