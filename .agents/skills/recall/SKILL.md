---
name: recall
description: Search the cross-repository Ganglia for relevant shared, personal, project, and episodic knowledge using QMD plus a mandatory text-search fallback. Use when the user asks to recall, retrieve, find, or resume prior knowledge. This skill is strictly read-only.
---

# Recall

Search the Ganglia checkout containing this skill. Resolve the real skill path
(following symlinks) and walk up to the repository root; never assume a username
or hardcode a home-directory path.

Read and follow [references/workflow.md](references/workflow.md). Treat user text
following `$recall` as the query. Do not write, reindex, commit, or change files;
recall is strictly read-only.
