# Third-party notices

## Spotify shunt skills and design adaptation

The delegated worker hooks, wrappers, skills and regression scenarios are
adapted from Spotify's `portal-ai-plugins` shunt design at revision
`3c24ca30ff63e1f5bbad1c43fe5324daff579123`, distributed under Apache-2.0.
Source: <https://github.com/spotify/portal-ai-plugins/tree/3c24ca30ff63e1f5bbad1c43fe5324daff579123/plugins/shunt>

Credit for the original skills belongs to **Spotify**, the author named in
the upstream [plugin manifest](https://github.com/spotify/portal-ai-plugins/blob/3c24ca30ff63e1f5bbad1c43fe5324daff579123/plugins/shunt/.claude-plugin/plugin.json).
The following skill entrypoints are modified adaptations and carry their own
attribution so provenance is visible where the skills are read:

- [bulk-reader](.agents/skills/bulk-reader/SKILL.md), adapted from
  [Spotify's original bulk-reader](https://github.com/spotify/portal-ai-plugins/blob/3c24ca30ff63e1f5bbad1c43fe5324daff579123/plugins/shunt/skills/bulk-reader/SKILL.md).
- [code-writer](.agents/skills/code-writer/SKILL.md), adapted from
  [Spotify's original code-writer](https://github.com/spotify/portal-ai-plugins/blob/3c24ca30ff63e1f5bbad1c43fe5324daff579123/plugins/shunt/skills/code-writer/SKILL.md).

Ganglia replaces the Claude/Portal/AiKA transport with Python and a Codex
adapter, changes the hook/output contract, and adds independently asserted
regressions, bounded configuration, and non-clobber generation. Issue #10
informed the parser, output-schema, target-write and measurement changes.
The Apache-2.0 license text is included in the repository's `LICENSE`.

## D3.js 7.9.0

Copyright 2010-2023 Mike Bostock

Permission to use, copy, modify, and/or distribute this software for any purpose
with or without fee is hereby granted, provided that the above copyright notice
and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
THIS SOFTWARE.

Source: <https://github.com/d3/d3/tree/v7.9.0>
