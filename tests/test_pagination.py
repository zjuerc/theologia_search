"""Pagination changes must never regenerate or alter retrieval evidence."""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "knowledge_base"))
import page_locations as kb_pages
from theologia_search import pagination, search, gui, build_index, check_index_sync
from test_semantic_search import write_fixture_kb, temp_workspace


def write_extension(kb_dir, locations):
    path = kb_dir / kb_pages.FILENAME
    path.write_text("".join(kb_pages.json_line(row) for row in locations), encoding="utf-8")
    manifest_path = kb_dir / "christian_kb_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = [{"source_id": row["source_id"], "pdf_sha256": row["pdf_sha256"]} for row in locations]
    manifest["pagination"] = kb_pages.extension_info(path, sources)
    manifest["files"]["page_locations"] = [path.name]
    kb_pages.write_json(manifest_path, manifest)
    return manifest


def location(page, footer, originals=(), source="SRC_MISC"):
    return {"source_id": source, "source_format": "pdf", "pdf_page_number": page, "pdf_sha256": "fixture",
            "pdf_edition_page_number": footer, "pdf_edition_status": "verified" if footer else "not_marked",
            "original_book_page_numbers": list(originals), "original_book_status": "verified" if originals else "not_marked",
            "observations": []}


class PaginationTests(unittest.TestCase):
    def test_merged_roman_and_footer_are_separate_coordinate_observations(self):
        lines = [{"label": "xx", "bbox": [541.2, 658.9, 547.2, 664.9], "font_size": 6},
                 {"label": "9", "bbox": [498.5, 692.5, 504, 703.5], "font_size": 11}]
        row = kb_pages.classify_page("KUYPER", 18, "hash", 612, 792, lines, "ccel")
        self.assertEqual(row["pdf_edition_page_number"], "9")
        self.assertEqual(row["original_book_page_numbers"], ["xx"])
        self.assertEqual(row["observations"][0]["verification_status"], "verified")

    def test_multiple_original_markers_and_ambiguous_footer(self):
        lines = [{"label": "286", "bbox": [541.2, 195.3, 551.2, 201.3], "font_size": 6},
                 {"label": "287", "bbox": [541.2, 657.3, 551.2, 663.3], "font_size": 6},
                 {"label": "264", "bbox": [487.5, 692.5, 504, 703.5], "font_size": 11}]
        row = kb_pages.classify_page("KUYPER", 273, "hash", 612, 792, list(reversed(lines)), "ccel")
        self.assertEqual(row["original_book_page_numbers"], ["286", "287"])
        self.assertEqual(row["pdf_edition_page_number"], "264")
        lines.append({"label": "265", "bbox": [487.5, 692.5, 504, 703.5], "font_size": 11})
        row = kb_pages.classify_page("KUYPER", 273, "hash", 612, 792, lines, "ccel")
        self.assertEqual(row["pdf_edition_status"], "unresolved")
        self.assertIsNone(row["pdf_edition_page_number"])

    def test_missing_and_unknown_layouts_are_not_inferred(self):
        blank = kb_pages.classify_page("S", 1, "h", 612, 792, [], "ccel", has_text=False)
        self.assertEqual(blank["pdf_edition_status"], "unavailable")
        unnumbered = kb_pages.classify_page("S", 2, "h", 612, 792, [], "ccel")
        self.assertEqual(unnumbered["pdf_edition_status"], "not_marked")
        unknown = kb_pages.classify_page("S", 3, "h", 612, 792,
            [{"label": "12", "bbox": [20, 20, 35, 30], "font_size": 10}], "unrecognized")
        self.assertEqual(unknown["pdf_edition_status"], "unresolved")
        self.assertIsNone(unknown["pdf_edition_page_number"])

    def test_toc_and_footnote_numbers_are_excluded_and_shifted_markers_retained(self):
        lines = [{"label": "107", "bbox": [485.76, 49.6, 501.6, 60.6], "font_size": 11},
                 {"label": "2958", "bbox": [108, 681.71, 125.28, 690.71], "font_size": 9},
                 {"label": "91", "bbox": [532.36, 377.61, 539.04, 383.61], "font_size": 6}]
        row = kb_pages.classify_page("S", 122, "h", 612, 792, lines, "ccel")
        self.assertEqual(row["original_book_page_numbers"], ["91"])
        self.assertEqual(sum(o["verification_status"] == "excluded" for o in row["observations"]), 2)
        self.assertNotEqual(row["pdf_edition_status"], "verified")

    def test_formatters_preserve_romans_resets_gaps_and_unknowns(self):
        self.assertEqual(kb_pages.DISPLAY_LABELS, pagination.DISPLAY_LABELS)
        for footers in [("iii", "iv"), ("100", "1"), ("17", "18"), ("17", None, "19")]:
            row = {"page_locations": [location(i + 22, f) for i, f in enumerate(footers)]}
            self.assertEqual(kb_pages.format_page_locations(row), pagination.format_page_locations(row))
        partial = pagination.format_page_locations({"page_locations": [location(22, "17"), location(23, None), location(24, "19")]})
        self.assertIn("17, 19 (incomplete)", partial)
        self.assertNotIn("17–19", partial)
        self.assertEqual(pagination.compact_labels(["001", "002"]), "001, 002")
        self.assertIn("unavailable", pagination.format_page_locations({"page_number": 5, "printed_page_number": "xx 9"}))

    def test_approved_labels_singular_plural_and_unavailable(self):
        singular = {"page_locations": [location(818, "768", ["358"])]}
        expected = "PDF file page: 818 · Header/footer page: 768 · Printed book reference: 358"
        for formatter in [kb_pages.format_page_locations, pagination.format_page_locations]:
            self.assertEqual(formatter(singular), expected)
            plural = formatter({"page_locations": [location(818, "768", ["358"]), location(819, "769", ["359"])]})
            self.assertEqual(plural, "PDF file pages: 818–819 · Header/footer pages: 768–769 · Printed book references: 358–359")
            self.assertIn("Header/footer page: unavailable", formatter({"page_number": 1}))
            self.assertIn("Printed book reference: iii", formatter({"page_locations": [location(22, "iv", ["iii"])]}))

    def test_label_only_update_never_rewrites_pagination_rows_or_jsonl(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            kb_dir = write_fixture_kb(root)
            write_extension(kb_dir, [location(30, "2", ["i"])])
            db, im = root / "index.sqlite", root / "index.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=db, index_manifest_path=im)
            kb_manifest = kb_dir / "christian_kb_manifest.json"
            # Simulate the existing extension before display descriptions existed.
            for path in [kb_manifest, im]:
                doc = json.loads(path.read_text(encoding="utf-8"))
                doc["pagination"].pop("display_labels")
                kb_pages.write_json(path, doc)
            with closing(sqlite3.connect(db)) as con:
                con.execute("DELETE FROM metadata WHERE key='pagination_display_labels'")
                for verb in ["INSERT", "UPDATE", "DELETE"]:
                    con.execute(f"CREATE TRIGGER forbid_{verb} BEFORE {verb} ON page_locations BEGIN SELECT RAISE(ABORT,'pagination rewrite forbidden'); END")
                con.commit()
                before = con.execute("SELECT * FROM page_locations").fetchall()
                evidence = con.execute("SELECT * FROM evidence").fetchall()
            jsonl = (kb_dir / kb_pages.FILENAME).read_bytes()
            with patch.object(kb_pages, "refresh", side_effect=AssertionError("PDF scan forbidden")), \
                    patch.object(pagination, "install_page_locations", side_effect=AssertionError("row rewrite forbidden")):
                self.assertTrue(kb_pages.refresh_labels(kb_dir))
                pagination.migrate_index(kb_dir, db, im, root / "backup", labels_only=True)
                self.assertEqual(jsonl, (kb_dir / kb_pages.FILENAME).read_bytes())
                with closing(sqlite3.connect(db)) as con:
                    self.assertEqual(before, con.execute("SELECT * FROM page_locations").fetchall())
                    self.assertEqual(evidence, con.execute("SELECT * FROM evidence").fetchall())
                    labels = json.loads(con.execute("SELECT value FROM metadata WHERE key='pagination_display_labels'").fetchone()[0])
                self.assertEqual(labels, kb_pages.DISPLAY_LABELS)
                self.assertEqual(json.loads(im.read_text())["pagination"]["display_labels"], labels)
                self.assertEqual(json.loads(kb_manifest.read_text())["pagination"]["display_labels"], labels)
                self.assertTrue(check_index_sync.check_index_sync(kb_dir=kb_dir, index_path=db, index_manifest_path=im).synced)
                digest = hashlib.sha256(db.read_bytes()).hexdigest()
                manifest_bytes = kb_manifest.read_bytes(), im.read_bytes()
                self.assertFalse(kb_pages.refresh_labels(kb_dir))
                pagination.migrate_index(kb_dir, db, im, root / "backup", labels_only=True)
                self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), digest)
                self.assertEqual((kb_manifest.read_bytes(), im.read_bytes()), manifest_bytes)

    def test_source_spans_control_mapping_not_a_guessed_range(self):
        row = {"page_start": 10, "page_end": 14, "source_spans": [{"page_number": 10}, {"page_number": 14}]}
        self.assertEqual(pagination.evidence_pages(row), [10, 14])
        self.assertEqual(kb_pages.evidence_pages(row), [10, 14])
        self.assertEqual(pagination.evidence_pages({"source_format": "epub", "page_number": 4}), [])

    def test_future_index_build_and_metadata_migration_leave_results_unchanged(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            kb_dir = write_fixture_kb(root)
            db, im = root / "index.sqlite", root / "index.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=db, index_manifest_path=im)
            def snapshot():
                with closing(sqlite3.connect(db)) as con:
                    con.row_factory = sqlite3.Row
                    rows, _ = search.search_concept(con, "grace", limit=8)
                    evidence = list(map(tuple, con.execute("SELECT * FROM evidence")))
                    return evidence, [(r["evidence_id"], r["concept_score"]) for r in rows], rows
            before, ranking, _ = snapshot()
            manifest = write_extension(kb_dir, [location(30, "2")])
            # Migration must not invoke the index builder, including failure paths.
            with patch.object(build_index, "build_semantic_index", side_effect=AssertionError("rebuild forbidden")):
                pagination.migrate_index(kb_dir, db, im, root / "backup")
                after, new_ranking, rows = snapshot()
                self.assertEqual(before, after)
                self.assertEqual(ranking, new_ranking)
                target = next(r for r in rows if r["page_number"] == 30)
                self.assertEqual(target["page_locations"][0]["pdf_edition_page_number"], "2")
                digest = hashlib.sha256(db.read_bytes()).hexdigest()
                pagination.migrate_index(kb_dir, db, im, root / "backup")
                self.assertEqual(digest, hashlib.sha256(db.read_bytes()).hexdigest())
            self.assertTrue((root / "backup/index.sqlite").exists())
            # A subsequent intentional index build also imports the extension.
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=db, index_manifest_path=im)
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM page_locations").fetchone()[0], 1)
                self.assertEqual(json.loads(con.execute("SELECT value FROM metadata WHERE key='pagination_display_labels'").fetchone()[0]), kb_pages.DISPLAY_LABELS)
                con.row_factory = sqlite3.Row
                advanced, _ = search.search_advanced(con, search.AdvancedSearchCriteria(author="Augustine of Hippo"))
                self.assertTrue(all("page_locations" in row for row in advanced))

    def test_bad_digest_rolls_back_extension_without_touching_evidence(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            kb_dir = write_fixture_kb(root)
            db, im = root / "index.sqlite", root / "index.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=db, index_manifest_path=im)
            manifest = write_extension(kb_dir, [location(10, "2")])
            manifest["pagination"]["sha256"] = "bad"
            with closing(sqlite3.connect(db)) as con:
                count = con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
                with self.assertRaisesRegex(ValueError, "digest mismatch"):
                    pagination.install_page_locations(con, kb_dir, manifest)
                self.assertEqual(count, con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])
                self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='page_locations'").fetchone())

    def test_resume_and_future_new_sources_need_no_evidence_cache(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            kb_dir, pdf_root = root / "kb", root / "raw_documents"
            kb_dir.mkdir()
            pdf_root.mkdir()
            pdf = pdf_root / "one.pdf"
            pdf.write_bytes(b"pdf fixture for margin reader")
            registry = kb_dir / "sources.jsonl"
            source = {"source_id": "ONE", "pdf_file": "raw_documents/one.pdf", "registry_status": "active",
                      "pdf_sha256": kb_pages.sha256_file(pdf)}
            registry.write_text(kb_pages.json_line(source), encoding="utf-8")
            kb_pages.write_json(kb_dir / "christian_kb_manifest.json", {"files": {"source_registry": [registry.name]}})
            page = SimpleNamespace(rect=SimpleNamespace(width=612, height=792))
            class Document(list):
                def __enter__(self): return self
                def __exit__(self, *args): pass
            fake_fitz = SimpleNamespace(open=lambda _: Document([page]))
            lines = [{"label": "1", "bbox": [498.5, 692.5, 504, 703.5], "font_size": 11}]
            with patch.dict(sys.modules, {"fitz": fake_fitz}), patch.object(kb_pages, "detect_profile", return_value="ccel"), \
                    patch.object(kb_pages, "margin_lines", return_value=lines) as scan:
                first = kb_pages.refresh(kb_dir, pdf_root)
                current = json.loads((kb_dir / "christian_kb_manifest.json").read_text())
                self.assertEqual(kb_pages.validate_extension(kb_dir, current), [])
                self.assertEqual(scan.call_count, 1)
                digest = kb_pages.sha256_file(kb_dir / kb_pages.FILENAME)
                scan.reset_mock()
                kb_pages.refresh(kb_dir, pdf_root)
                self.assertEqual(scan.call_count, 0)
                self.assertEqual(digest, kb_pages.sha256_file(kb_dir / kb_pages.FILENAME))
                # Simulate a public release without the private pagination cache.
                import shutil
                shutil.rmtree(kb_dir / "_pagination_cache")
                kb_pages.refresh(kb_dir, pdf_root)
                self.assertEqual(scan.call_count, 0)
                # Add another PDF: only the new source's margin is inspected.
                (pdf_root / "two.pdf").write_bytes(b"second pdf fixture")
                source2 = {**source, "source_id": "TWO", "pdf_file": "raw_documents/two.pdf",
                           "pdf_sha256": kb_pages.sha256_file(pdf_root / "two.pdf")}
                registry.write_text(kb_pages.json_line(source) + kb_pages.json_line(source2), encoding="utf-8")
                new = kb_pages.refresh(kb_dir, pdf_root)
                self.assertEqual(scan.call_count, 1)
                self.assertEqual(new["page_count"], 2)
                # Changed fingerprints invalidate only stale metadata.
                source["pdf_sha256"] = "changed"
                registry.write_text(kb_pages.json_line(source) + kb_pages.json_line(source2), encoding="utf-8")
                manifest = json.loads((kb_dir / "christian_kb_manifest.json").read_text())
                kb_pages.preserve_extension(kb_dir, manifest)
                remaining = list(kb_pages.read_rows(kb_dir / kb_pages.FILENAME))
                self.assertEqual([r["source_id"] for r in remaining], ["TWO"])


if __name__ == "__main__":
    unittest.main()
