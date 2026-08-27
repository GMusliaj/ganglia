# Recall workflow

## 0. Episodic shortcut

Run this before topical search when the ask is temporal: "where did we leave
off", "what happened yesterday/last session", "status of <project>", or an
empty query in a repository matching `local/projects/<name>/`.

List by modification time that project's `sessions/` and `checkpoints/`, plus
`local/short-mem/`. Read the project's `_index.md` and the newest relevant
checkpoint or short-memory note. Answer with recent events, open threads, and
next actions, citing `relative/path.md:line`. Do not inline a session transcript;
read its frontmatter and only relevant lines. Continue to topical retrieval only
if this layer cannot answer.

## 1. Semantic ceiling through MCP

Use the QMD MCP server configured as `brain-qmd` when its tools are available.
Do not shell out to `qmd` or `scripts/qmd.sh` during recall. Call its `query`
tool with explicit structured searches, an intent, and the relevant collection:

```json
{
  "searches": [
    {"type": "lex", "query": "<exact query terms>"},
    {"type": "vec", "query": "<semantic restatement>"}
  ],
  "intent": "<what the user is trying to recover>",
  "collections": ["brain"],
  "limit": 8
}
```

Include `codex-sessions` only for temporal, project-resumption, or explicitly
session-related questions. Use `get` for focused lines from a candidate and
`multi_get` only when several known paths are needed. The MCP parameter is the
plural `collections`; never use a singular `collection` field.

Use top paths as semantic candidates. If the MCP server or tool is unavailable,
unhealthy, or errors, fall through silently. Never replace MCP retrieval with a
direct QMD CLI call, and never let QMD failure become the answer.

## 2. Text-search floor

Always search the entire Brain with `rg`, including shared folders and
`local/notes/`, `local/short-mem/`, and `local/projects/` with session
transcripts. Orient first with `MEMORY.md` and `local/MEMORY.local.md`.

Match query terms and obvious stems against `title`, `description`, and `tags`
frontmatter plus bodies. Search hidden/ignored `local/` explicitly when needed;
do not assume a default `rg` traversal includes it.

## 3. Merge and rank

Union QMD and text-search hits and deduplicate by path. Rank:

1. exact title or tag matches;
2. description matches;
3. body matches and confident QMD semantic candidates.

Prefer durable shared patterns, decisions, and concepts over local project or
short-memory hits unless local knowledge is genuinely more relevant, especially
for named projects. A raw `sessions/` transcript is weakest; prefer a distilled
entry expressing the same knowledge.

Label each result `shared` or `local` so the user knows whether a teammate's
clone contains it. Follow file-relative Markdown links one hop when useful.

## 4. Present

Return a tight cited list. For each hit, include relative path, title, and the
relevant lines or a concise paraphrase with line citations. If nothing matches,
say so and suggest the closest registered tags from `meta/tag-taxonomy.md`; do
not guess.

Recall is read-only. Never create files, update indexes, run QMD update/embed,
commit, or otherwise mutate state.
