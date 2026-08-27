from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "scripts"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reindex_module = load_module("brain_reindex", ROOT / "bin" / "reindex.py")
guard_module = load_module("brain_guard", ROOT / "scripts" / "guard_shared.py")
audit_module = load_module("brain_public_audit", ROOT / "scripts" / "audit_public.py")
lint_module = load_module("brain_lint", ROOT / "bin" / "lint_brain.py")
canvas_module = load_module("brain_canvas", ROOT / "bin" / "canvas.py")
session_module = load_module(
    "brain_session_catalog", ROOT / "bin" / "sync_codex_sessions.py"
)


ENTRY = """---
type: pattern
title: Retrieval floor
description: Plain text search remains available.
tags: [retrieval]
date: 2026-08-27
---

# Retrieval floor

## Active

Use text search.

## Source

Test fixture.
"""


class ReindexTests(unittest.TestCase):
    def test_generates_shared_and_local_indexes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "patterns").mkdir()
            (root / "patterns" / "retrieval-floor.md").write_text(ENTRY)
            (root / "local" / "notes").mkdir(parents=True)
            (root / "local" / "notes" / "preference.md").write_text(
                ENTRY.replace("type: pattern", "type: note")
            )

            changed = reindex_module.reindex(root)

            self.assertEqual(changed, (True, True))
            self.assertIn("patterns/retrieval-floor.md", (root / "MEMORY.md").read_text())
            self.assertIn("retrieval-floor.md", (root / "patterns" / "index.md").read_text())
            self.assertIn("notes/preference.md", (root / "local/MEMORY.local.md").read_text())
            self.assertEqual(reindex_module.reindex(root), (False, False))

    def test_omits_markdown_without_required_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "patterns").mkdir()
            (root / "patterns" / "invalid.md").write_text("# Missing type\n")

            reindex_module.reindex(root)

            self.assertNotIn("invalid.md", (root / "MEMORY.md").read_text())
            self.assertNotIn("invalid.md", (root / "patterns" / "index.md").read_text())


class GuardTests(unittest.TestCase):
    def test_allows_shareable_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "patterns").mkdir()
            (root / "patterns" / "entry.md").write_text(ENTRY)
            self.assertEqual(guard_module.scan(root), [])

    def test_blocks_machine_specific_home_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "snippets").mkdir()
            machine_path = "/" + "Users/private-user/private/tool"
            (root / "snippets" / "bad.md").write_text(f"run {machine_path}\n")
            failures = guard_module.scan(root)
            self.assertTrue(any("machine-specific" in failure for failure in failures))

    def test_blocks_case_insensitive_denylist_terms_without_echoing_term(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "decisions").mkdir()
            (root / "local").mkdir()
            (root / "local" / "shared-denylist.txt").write_text("Example Customer\n")
            (root / "decisions" / "bad.md").write_text("example customer detail\n")
            failures = guard_module.scan(root)
            self.assertEqual(len(failures), 1)
            self.assertIn("local/shared-denylist.txt:1", failures[0])
            self.assertNotIn("Example Customer", failures[0])

    def test_scans_operating_files_not_only_knowledge_folders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "local").mkdir()
            (root / "local" / "shared-denylist.txt").write_text("Private Persona\n")
            readme = root / "README.md"
            readme.write_text("Maintained by Private Persona.\n")

            failures = guard_module.scan(root, [readme])

            self.assertEqual(len(failures), 1)
            self.assertIn("README.md:1", failures[0])
            self.assertNotIn("Private Persona", failures[0])

    def test_blocks_personal_email_but_allows_example_domains(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "README.md"
            document.write_text("Public example: maintainer@example.com\n")
            self.assertEqual(guard_module.scan(root, [document]), [])

            private_email = "person" + "@private.invalid"
            document.write_text(f"Contact: {private_email}\n")
            failures = guard_module.scan(root, [document])

            self.assertEqual(len(failures), 1)
            self.assertIn("personal email address", failures[0])

    def test_runtime_identity_terms_are_checked_without_echoing_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "README.md"
            private_term = "Unique Local Identity"
            document.write_text(f"Maintained by {private_term}.\n")
            original = guard_module.runtime_identity_terms
            guard_module.runtime_identity_terms = lambda _root: [
                ("test identity", private_term)
            ]
            try:
                failures = guard_module.scan(
                    root, [document], include_runtime_identity=True
                )
            finally:
                guard_module.runtime_identity_terms = original

            self.assertEqual(len(failures), 1)
            self.assertIn("test identity", failures[0])
            self.assertNotIn(private_term, failures[0])

    def test_redacts_a_private_publication_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "local").mkdir()
            private_term = "Private Persona"
            (root / "local" / "shared-denylist.txt").write_text(
                f"{private_term}\n"
            )
            document = root / f"notes-by-{private_term}.md"
            document.write_text("Public-looking content.\n")

            failures = guard_module.scan(root, [document])

            self.assertEqual(len(failures), 1)
            self.assertIn("<redacted-path>:1", failures[0])
            self.assertNotIn(private_term, failures[0])


class PublicAuditTests(unittest.TestCase):
    def test_accepts_noreply_authors_and_rejects_personal_email(self):
        self.assertTrue(
            audit_module.safe_author_email("contributor@users.noreply.github.com")
        )
        private_email = "person" + "@private.invalid"
        self.assertFalse(audit_module.safe_author_email(private_email))

    def test_rejects_a_runtime_identity_as_commit_author_name(self):
        private_name = "Private Persona"
        self.assertFalse(
            audit_module.safe_author_name(
                private_name, [("test identity", private_name)]
            )
        )
        self.assertTrue(
            audit_module.safe_author_name(
                "Public Maintainer", [("test identity", private_name)]
            )
        )


class LintTests(unittest.TestCase):
    def test_accepts_valid_entry_and_rejects_unknown_tag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder in lint_module.SHARED_FOLDERS:
                (root / folder).mkdir()
            (root / "meta").mkdir()
            (root / "meta" / "tag-taxonomy.md").write_text(
                "- `retrieval` — search and ranking.\n"
            )
            entry = root / "patterns" / "retrieval-floor.md"
            entry.write_text(ENTRY)

            errors, _ = lint_module.lint(root)
            self.assertEqual(errors, [])

            entry.write_text(ENTRY.replace("[retrieval]", "[unknown-tag]"))
            errors, _ = lint_module.lint(root)
            self.assertTrue(any("unregistered tag" in error for error in errors))

    def test_lifecycle_provenance_and_orphan_checks_are_advisory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder in lint_module.SHARED_FOLDERS:
                (root / folder).mkdir()
            (root / "meta").mkdir()
            (root / "meta" / "tag-taxonomy.md").write_text(
                "- `retrieval` — search and ranking.\n"
            )
            (root / "patterns" / "advisory.md").write_text(
                ENTRY.replace(
                    "## Active\n\nUse text search.\n\n## Source\n\nTest fixture.\n",
                    "A useful claim.\n",
                )
            )

            errors, warnings = lint_module.lint(root)

            self.assertEqual(errors, [])
            self.assertTrue(any("missing lifecycle" in warning for warning in warnings))
            self.assertTrue(any("missing provenance" in warning for warning in warnings))
            self.assertTrue(any("no inbound links" in warning for warning in warnings))


class CanvasTests(unittest.TestCase):
    def test_live_server_accepts_only_local_host_headers_in_loopback_mode(self):
        for value in ("localhost:8765", "localhost.", "127.0.0.1:8765", "[::1]:8765"):
            self.assertTrue(canvas_module.is_local_host_header(value))
        self.assertFalse(canvas_module.is_local_host_header("example.invalid:8765"))

    def test_canvas_omits_generated_navigation_but_keeps_sessions(self):
        self.assertFalse(canvas_module.is_canvas_content("MEMORY.md"))
        self.assertFalse(canvas_module.is_canvas_content("concepts/index.md"))
        self.assertFalse(canvas_module.is_canvas_content("local/projects/example/_index.md"))
        self.assertFalse(canvas_module.is_canvas_content("local/MEMORY.local.md"))
        self.assertFalse(canvas_module.is_canvas_content("README.md"))
        self.assertTrue(canvas_module.is_canvas_content("concepts/retrieval.md"))
        self.assertTrue(canvas_module.is_canvas_content("local/notes/retrieval.md"))
        self.assertTrue(canvas_module.is_canvas_content("session.jsonl", is_session=True))

    def test_normalizes_relative_markdown_and_wikilinks(self):
        self.assertEqual(
            canvas_module.normalize_target(
                "patterns/retrieval-floor.md", "../concepts/search.md#active"
            ),
            "concepts/search.md",
        )
        self.assertEqual(
            canvas_module.normalize_target("patterns/retrieval-floor.md", "related-note"),
            "patterns/related-note.md",
        )
        self.assertIsNone(
            canvas_module.normalize_target(
                "patterns/retrieval-floor.md", "https://example.com/source.md"
            )
        )

    def test_semantic_edges_are_thresholded_and_neighbor_limited(self):
        edges = canvas_module.semantic_edges(
            {
                "doc:a": [1.0, 0.0],
                "doc:b": [0.9, 0.1],
                "doc:c": [0.0, 1.0],
            },
            threshold=0.8,
            neighbors=1,
        )

        self.assertEqual(len(edges), 1)
        self.assertEqual({edges[0].source, edges[0].target}, {"doc:a", "doc:b"})
        self.assertEqual(edges[0].kind, "semantic")

    def test_render_is_offline_and_contains_layer_controls(self):
        graph = {
            "nodes": [
                {
                    "id": "doc:brain:patterns/example.md",
                    "label": "Example",
                    "kind": "document",
                    "category": "pattern",
                    "collection": "brain",
                    "path": "patterns/example.md",
                    "title": "Example",
                    "description": "Example entry.",
                    "tags": [],
                    "url": "",
                    "editor_url": "",
                    "date": "2026-08-27",
                    "project": "",
                    "is_session": False,
                }
            ],
            "links": [],
            "meta": {"collections": ["brain"], "scope": "shared"},
        }

        rendered = canvas_module.render_html(graph, "window.d3 = {};")

        self.assertIn('id="layer-link"', rendered)
        self.assertIn('id="layer-tag"', rendered)
        self.assertIn('id="layer-semantic"', rendered)
        self.assertIn('id="inspector" aria-label="Node details"', rendered)
        self.assertIn('id="relations"', rendered)
        self.assertIn('id="detail-editor"', rendered)
        self.assertIn("Open in VS Code", rendered)
        self.assertIn("Linked knowledge", rendered)
        self.assertIn("Map key", rendered)
        self.assertIn('id="search-results"', rendered)
        self.assertIn('id="zoom-in"', rendered)
        self.assertIn('id="zoom-out"', rendered)
        self.assertIn('data-category="pattern"', rendered)
        self.assertIn('placeholder="Search knowledge and sessions"', rendered)
        self.assertIn("prefers-reduced-motion:reduce", rendered)
        self.assertIn("pointer-events: none", rendered)
        self.assertIn('event.key === "Enter"', rendered)
        self.assertIn('role="status" aria-live="polite"', rendered)
        self.assertIn('class="identity-logo"', rendered)
        self.assertIn("Double link brackets surround one durable knowledge unit", rendered)
        self.assertNotIn("__BRAIN_LOGO__", rendered)
        self.assertIn("1 documents · 0 tags · 0 visible edges", rendered)
        self.assertIn("window.d3 = {};", rendered)
        self.assertNotIn("<script src=", rendered)
        self.assertNotIn('"liveReload"', rendered)

        live = canvas_module.render_html(graph, "window.d3 = {};", live_version=7)
        self.assertIn('"liveReload":{"version":7,"url":"/api/version"}', live)

    def test_vscode_url_uses_the_documented_file_scheme_and_escapes_spaces(self):
        path = ROOT / "concepts" / "example note.md"

        self.assertEqual(
            canvas_module.vscode_url(path),
            f"vscode://file{path.as_posix().replace(' ', '%20')}",
        )

    def test_canvas_interactive_icons_use_the_shared_icon_contract(self):
        template = (ROOT / "bin" / "canvas.html").read_text(encoding="utf-8")
        interactive_icons = re.findall(
            r'<(?:button|summary|a)\b[^>]*>\s*<svg\b([^>]*)>', template
        )

        self.assertGreaterEqual(len(interactive_icons), 12)
        for attributes in interactive_icons:
            self.assertIn('class="ui-icon"', attributes)

    def test_live_state_version_changes_when_a_watched_source_changes(self):
        graph = {"nodes": [], "links": [], "meta": {"collections": ["brain"], "scope": "shared"}}
        with tempfile.TemporaryDirectory() as temporary:
            watched = Path(temporary) / "canvas.js"
            watched.write_text("initial")
            state = canvas_module.CanvasState(graph, "window.d3 = {};", [watched], lambda: (graph, []))
            _, _, initial_version = state.snapshot()
            watched.write_text("changed")
            state.refresh_if_changed()
            _, _, changed_version = state.snapshot()

            self.assertEqual(initial_version, 1)
            self.assertEqual(changed_version, 2)

    def test_render_preserves_inlined_d3_license_notice(self):
        graph = {"nodes": [], "links": [], "meta": {"collections": [], "scope": "shared"}}
        d3_source = "/* D3.js license: example notice */\nwindow.d3 = {};"

        rendered = canvas_module.render_html(graph, d3_source)

        self.assertIn("D3.js license: example notice", rendered)
        self.assertIn("window.d3 = {};", rendered)

    def test_private_scope_adds_codex_sessions_to_brain(self):
        available = {
            "brain": canvas_module.Collection("brain", ".", True),
            "codex-sessions": canvas_module.Collection(
                "codex-sessions", "local/session-catalog", False
            ),
        }

        shared = canvas_module.choose_collections(available, [], False)
        private = canvas_module.choose_collections(
            available, [], False, include_private=True
        )

        self.assertEqual([item.name for item in shared], ["brain"])
        self.assertEqual(
            [item.name for item in private], ["brain", "codex-sessions"]
        )

    def test_extracts_private_codex_session_catalog_metadata(self):
        records = [
            {
                "type": "session_meta",
                "payload": {
                    "timestamp": "2026-08-27T15:03:28Z",
                    "cwd": "/private/example-project",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "# AGENTS.md instructions for a repository",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Map sessions into the knowledge canvas and explain their links.",
                        }
                    ],
                },
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "rollout.jsonl"
            session.write_text("\n".join(json.dumps(record) for record in records))

            title, description, timestamp, project = (
                canvas_module.codex_session_metadata(session)
            )

        self.assertEqual(
            title, "Map sessions into the knowledge canvas and explain their links."
        )
        self.assertEqual(description, "Codex session · example-project")
        self.assertEqual(timestamp, "2026-08-27T15:03:28Z")
        self.assertEqual(project, "example-project")


class SessionCatalogTests(unittest.TestCase):
    def test_syncs_compact_private_markdown_from_jsonl(self):
        records = [
            {
                "type": "session_meta",
                "payload": {
                    "timestamp": "2026-08-27T15:03:28Z",
                    "cwd": "/private/example-project",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Connect sessions to concepts in the canvas.",
                        }
                    ],
                },
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sessions"
            output = root / "catalog"
            session = source / "2026" / "08" / "27" / "rollout.jsonl"
            session.parent.mkdir(parents=True)
            session.write_text("\n".join(json.dumps(record) for record in records))

            changed = session_module.sync(source, output)
            catalog = output / "2026" / "08" / "27" / "rollout.md"
            parsed = canvas_module.parse(catalog).metadata

        self.assertEqual(changed, (1, 0))
        self.assertEqual(parsed["type"], "session")
        self.assertEqual(parsed["project"], "example-project")
        self.assertEqual(parsed["timestamp"], "2026-08-27T15:03:28Z")
        self.assertIn("Connect sessions to concepts", parsed["title"])


if __name__ == "__main__":
    unittest.main()
