# Brain architecture

Brain separates knowledge by sharing boundary and durability while keeping
Markdown canonical.

```text
session or explicit memory
          |
          v
     $remember
          |
     search/dedupe
          |
   +------+-------------------+
   |                          |
   v                          v
shared OKF-lite            local/
patterns, lessons,         notes, projects,
decisions, concepts,       checkpoints, short-mem
snippets, sources, infra      (gitignored)
   |                          |
   +------------+-------------+
                v
          generated indexes
                |
       +--------+--------+
       |                 |
       v                 v
   rg floor          QMD ceiling
       |                 |
       +--------+--------+
                v
             $recall

QMD index + Markdown
        |
        v
  offline canvas
 links / tags / semantic
```

Shared writes pass the repository-owned routing guard before the allowlisted
auto-commit script stages anything. Local writes never auto-commit. QMD indexes
both layers locally, but recall always uses text search too.

The Git publication boundary is broader than the shared knowledge layer. The
repository guard inspects every tracked and non-ignored candidate—including
tooling, configuration, documentation, and generated public indexes—against
machine-path, identity, email, and credential-shape rules. Private `local/`
content and disposable build/runtime artifacts are excluded before candidate
selection; `.qmd/index.yml` is the intentional public configuration exception
inside the otherwise ignored QMD state directory.

The canvas is a local projection, not another knowledge store. It reads
documents from QMD, resolves authoritative links and tags from Markdown, and
adds semantic edges when QMD's vector layout is readable. The generated HTML
and QMD database are disposable and ignored.
