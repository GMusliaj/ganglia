"""Raw source boundary and provenance regression tests, with synthetic inputs only."""
import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest

SPEC = importlib.util.spec_from_file_location("raw_sources", Path(__file__).resolve().parents[1] / "bin/raw_sources.py")
raw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(raw)


class RawSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def capture(self, **changes):
        values = dict(origin="example-notes", source_id="example-id", privacy="private",
                      payload=b"Synthetic original", allow_plaintext=True)
        values.update(changes)
        return raw.capture(self.root, **values)

    def test_preview_no_write(self):
        result = self.capture()
        self.assertEqual(result["state"], "preview")
        self.assertFalse((self.root / "local").exists())

    def test_identity_revisions_and_bytes(self):
        first = self.capture(apply=True)
        self.assertEqual(first, self.capture(apply=True))
        second = self.capture(payload=b"Changed original", apply=True)
        self.assertEqual(first["source"], second["source"])
        self.assertNotEqual(first["revision"], second["revision"])
        for capture, expected in [(first, b"Synthetic original"), (second, b"Changed original")]:
            raw.inspect(self.root, capture["source"], capture["revision"])
            path = self.root / capture["manifest"]
            self.assertEqual(path.with_suffix(".bin").read_bytes(), expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_restricted_and_missing_consent_rejected(self):
        for changes in [dict(privacy="restricted"), dict(allow_plaintext=False), dict(privacy="public")]:
            with self.assertRaises(ValueError):
                self.capture(**changes, apply=True)
        self.assertFalse((self.root / "local").exists())

    def test_external_reference_does_not_read_or_copy(self):
        result = self.capture(payload=None, privacy="restricted", locator="vault://example/opaque-id",
                              external_revision="example-revision", apply=True)
        record = raw.inspect(self.root, result["source"], result["revision"])
        self.assertEqual(record["content"]["availability"], "unverified")
        self.assertFalse((self.root / result["manifest"]).with_suffix(".bin").exists())
        self.assertFalse(list((self.root / "local").rglob("*.md")))

    def test_tampering_and_escape(self):
        result = self.capture(apply=True)
        path = self.root / result["manifest"]
        path.with_suffix(".bin").write_bytes(b"Tampered")
        with self.assertRaises(ValueError):
            raw.inspect(self.root, result["source"], result["revision"])
        with self.assertRaises(ValueError):
            raw.store_path(self.root, "../outside", result["revision"])

    def test_symlink_boundary(self):
        target = self.root / "elsewhere"
        target.mkdir()
        (self.root / "local").symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.capture(apply=True)

    def test_raw_markdown_is_excluded_from_generated_index(self):
        # Even accidental Markdown in the raw archive must not become knowledge.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
        import reindex
        raw_note = self.root / "local/raw/example.md"
        raw_note.parent.mkdir(parents=True)
        raw_note.write_text("---\ntype: note\ntitle: Raw source\n---\n")
        compiled = self.root / "local/notes/example.md"
        compiled.parent.mkdir()
        compiled.write_text("---\ntype: note\ntitle: Compiled knowledge\n---\n")
        entries = reindex.collect(self.root, [self.root / "local"])
        self.assertEqual([str(entry.path) for entry in entries], ["local/notes/example.md"])

    def test_receipt_requires_existing_private_outputs(self):
        result = self.capture(apply=True)
        note = self.root / "local/notes/example.md"
        note.parent.mkdir()
        note.write_text("---\ntype: note\n---\n\nSynthetic knowledge\n")
        receipt = raw.receipt(self.root, result["source"], result["revision"], "compiled", ["local/notes/example.md"], True)
        self.assertTrue((self.root / receipt["receipt"]).exists())
        for entries in [[], ["sources/public.md"], ["local/notes/../../public.md"], ["local/notes/missing.md"]]:
            with self.assertRaises((ValueError, OSError)):
                raw.receipt(self.root, result["source"], result["revision"], "compiled", entries, True)
        raw.receipt(self.root, result["source"], result["revision"], "no-knowledge", [], True)


if __name__ == "__main__":
    unittest.main()
