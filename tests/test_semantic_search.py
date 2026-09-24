import csv
import contextlib
import io
import json
import shutil
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path


SEMANTIC_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SEMANTIC_DIR.parent
sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(WORKSPACE_ROOT / "knowledge_base"))

import source_faithful_kb as kb_builder

from theologia_search import (
    build_index,
    build_neighborhoods,
    check_index_sync,
    common,
    discover_from_queries,
    evaluate_search,
    gui,
    periods,
    search,
)


def temp_workspace():
    tmp_root = WORKSPACE_ROOT / "theologia_search" / "generated" / "test_runs"
    tmp_root.mkdir(parents=True, exist_ok=True)
    path = tmp_root / f"run_{uuid.uuid4().hex}"
    path.mkdir()

    @contextlib.contextmanager
    def manager():
        try:
            yield str(path)
        finally:
            resolved_root = tmp_root.resolve()
            resolved_path = path.resolve()
            if resolved_root in resolved_path.parents:
                shutil.rmtree(resolved_path, ignore_errors=True)

    return manager()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_fixture_kb(root: Path) -> Path:
    kb_dir = root / "knowledge_base"
    kb_dir.mkdir()

    evidence_rows = [
        {
            "active_heading": "The Catholic Doctrine of the Trinity and Personal Relations of the Godhead",
            "evidence_id": "TRINITY_EVID_1",
            "outline_path": "Trinity > Personal Relations",
            "page_number": 10,
            "retrieval_layer": "primary",
            "source_id": "SRC_TRINITY",
            "verbatim_text": (
                "The Unity is distributed into a Trinity, placing in their order the three Persons, "
                "the Father, the Son, and the Holy Ghost; not in substance divided, but of one substance."
            ),
            "work_attributed_author": "Tertullian",
        },
        {
            "active_heading": "Of Material Substance",
            "evidence_id": "SUBSTANCE_EVID_1",
            "outline_path": "Philosophy > Substance",
            "page_number": 20,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": "The substance and form of visible objects are discussed without reference to the Trinity.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "On Grace",
            "evidence_id": "GRACE_EVID_1",
            "outline_path": "Grace",
            "page_number": 30,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": "Grace and faith are named here.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "Letter to the Brethren",
            "evidence_id": "LETTER_FAITH_WORKS_EVID_1",
            "outline_path": "Letters > Letter to the Brethren",
            "page_number": 29,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": (
                "I write to remind you that faith and works must be considered together, "
                "for a living faith bears works of mercy."
            ),
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "General Preface",
            "evidence_id": "SOURCE_TITLE_ONLY_EVID_1",
            "outline_path": "Preface",
            "page_number": 100,
            "retrieval_layer": "primary",
            "source_id": "SRC_HOLY_SPIRIT_TITLE",
            "verbatim_text": "This preface discusses a general topic without the searched doctrine.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "Animalis, Composed of Soul",
            "evidence_id": "ANIMAL_SOUL_EVID_1",
            "outline_path": "Soul > Animalis, Composed of Soul",
            "page_number": 40,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": (
                "They alleged that Christ's flesh was animalis, composed of soul. "
                "The argument turns on whether soul and flesh are confused."
            ),
            "work_attributed_author": "Tertullian",
        },
        {
            "active_heading": "The Savior and Saviour",
            "evidence_id": "SAVIOR_EVID_1",
            "outline_path": "Salvation > The Savior and Saviour",
            "page_number": 44,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": "The Savior is named Saviour in older theological writing.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "On the Soul",
            "evidence_id": "GENERIC_SOUL_EVID_1",
            "outline_path": "Soul",
            "page_number": 41,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": "The soul is considered in its nature and operations.",
            "work_attributed_author": "Tertullian",
        },
        {
            "active_heading": "Whether souls are subsistent?",
            "evidence_id": "AQUINAS_SOUL_EVID_1",
            "outline_path": "Soul",
            "page_number": 42,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": "The souls under consideration are discussed in relation to subsistence.",
            "work_attributed_author": "Thomas Aquinas",
        },
        {
            "active_heading": "On the Soul and Life",
            "evidence_id": "CALVIN_SOUL_EVID_1",
            "outline_path": "Soul",
            "page_number": 43,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": "Calvin discusses the soul and the life given by God.",
            "work_attributed_author": "John Calvin",
        },
        {
            "active_heading": "Living Under the Law",
            "evidence_id": "LIVE_LAW_EVID_1",
            "outline_path": "Law > Living Under the Law",
            "page_number": 50,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": "Those living under the law are contrasted with those who live by faith.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "Whether law is something pertaining to reason?",
            "evidence_id": "GENERIC_LAW_EVID_1",
            "outline_path": "Law",
            "page_number": 51,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": "Law is an ordinance of reason for the common good.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "Chapter 29 - Grace Under the Law",
            "evidence_id": "CHAPTER_29_EVID_1",
            "outline_path": "Grace > Chapter 29 - Grace Under the Law",
            "page_number": 60,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "page_start": 60,
            "page_end": 60,
            "printed_page_number": "60",
            "printed_page_numbers": ["60"],
            "reader_text": "Chapter 29 begins with righteous men living under grace.",
            "source_spans": [{"page_number": 60, "reader_char_start": 0, "reader_char_end": 55}],
            "text_role": "body",
            "text_status": "reader_clean_pdfplumber_body_text",
            "verbatim_text": "Chapter 29 begins with righteous men living under grace.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "Chapter 29 - Grace Under the Law",
            "evidence_id": "CHAPTER_29_EVID_2",
            "outline_path": "Grace > Chapter 29 - Grace Under the Law",
            "page_number": 61,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "page_start": 61,
            "page_end": 61,
            "printed_page_number": "61",
            "printed_page_numbers": ["61"],
            "reader_text": "Chapter 29 continues with more evidence about grace and law.",
            "source_spans": [{"page_number": 61, "reader_char_start": 0, "reader_char_end": 58}],
            "text_role": "body",
            "text_status": "reader_clean_pdfplumber_body_text",
            "verbatim_text": "Chapter 29 continues with more evidence about grace and law.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "Chapter 30 - Ancient Saints",
            "evidence_id": "CHAPTER_30_EVID_1",
            "outline_path": "Grace > Chapter 30 - Ancient Saints",
            "page_number": 62,
            "retrieval_layer": "primary",
            "source_id": "SRC_MISC",
            "verbatim_text": "Chapter 30 begins a different discussion.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "Anonymous Ante-Nicene Grace Fragment",
            "evidence_id": "UNKNOWN_ANF_GRACE_EVID_1",
            "outline_path": "Grace",
            "page_number": 70,
            "retrieval_layer": "primary",
            "source_id": "SRC_ANF_UNKNOWN",
            "verbatim_text": "Grace is confessed in this anonymous ante-Nicene fragment.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "Anonymous Nicene Grace Fragment",
            "evidence_id": "UNKNOWN_NPNF_GRACE_EVID_1",
            "outline_path": "Grace",
            "page_number": 71,
            "retrieval_layer": "primary",
            "source_id": "SRC_NPNF_UNKNOWN",
            "verbatim_text": "Grace is confessed in this anonymous Nicene and post-Nicene fragment.",
            "work_attributed_author": "Unknown",
        },
        {
            "active_heading": "Of the Error in Which the Doctrine of Origen is Involved.",
            "evidence_id": "AUGUSTINE_ORIGEN_DISCUSSION_EVID_1",
            "outline_path": "City of God > Book XXI > Of the Error in Which the Doctrine of Origen is Involved.",
            "page_number": 546,
            "retrieval_layer": "primary",
            "source_id": "SRC_NPNF_AUGUSTINE",
            "verbatim_text": "Augustine discusses the doctrine of Origen and the error involved in that teaching.",
            "work_attributed_author": "Augustine of Hippo",
            "mentioned_authors": ["Origen"],
        },
        {
            "active_heading": "Ambrose Most Highly Praised by Pelagius.",
            "evidence_id": "AUGUSTINE_AMBROSE_DISCUSSION_EVID_1",
            "outline_path": "Augustine > Grace > Ambrose Most Highly Praised by Pelagius.",
            "page_number": 547,
            "retrieval_layer": "primary",
            "source_id": "SRC_NPNF_AUGUSTINE",
            "verbatim_text": "Augustine cites Ambrose in a discussion of grace and praise by Pelagius.",
            "work_attributed_author": "Augustine of Hippo",
            "mentioned_authors": ["Ambrose of Milan", "Pelagius"],
        },
        {
            "active_heading": "Cyprian's Testimonies.",
            "evidence_id": "AUGUSTINE_CYPRIAN_TESTIMONIES_EVID_1",
            "outline_path": "Augustine > Grace > Cyprian's Testimonies.",
            "page_number": 548,
            "retrieval_layer": "primary",
            "source_id": "SRC_NPNF_AUGUSTINE",
            "verbatim_text": "Augustine appeals to testimonies associated with Cyprian while arguing about grace.",
            "work_attributed_author": "Augustine of Hippo",
            "mentioned_authors": ["Cyprian of Carthage"],
        },
    ]
    write_jsonl(kb_dir / "evidence.jsonl", evidence_rows)

    source_rows = [
        {
            "source_id": "SRC_TRINITY",
            "display_title": "Trinity Source",
            "pdf_file": "fixture/trinity.pdf",
            "collection": "fixture",
        },
        {
            "source_id": "SRC_MISC",
            "display_title": "Misc Source",
            "pdf_file": "fixture/misc.pdf",
            "collection": "fixture",
        },
        {
            "source_id": "SRC_HOLY_SPIRIT_TITLE",
            "display_title": "Holy Spirit and Church",
            "pdf_file": "fixture/title-only.pdf",
            "collection": "fixture",
        },
        {
            "source_id": "SRC_ANF_UNKNOWN",
            "display_title": "Anonymous Ante-Nicene Source",
            "pdf_file": "fixture/anf.pdf",
            "collection": "Ante-Nicene Fathers",
        },
        {
            "source_id": "SRC_NPNF_UNKNOWN",
            "display_title": "Anonymous Nicene Source",
            "pdf_file": "fixture/npnf.pdf",
            "collection": "Nicene and Post-Nicene Fathers",
        },
        {
            "source_id": "SRC_NPNF_AUGUSTINE",
            "display_title": "NPNF1-02 St. Augustine's City of God and Christian Doctrine",
            "pdf_file": "fixture/NPNF1_02.pdf",
            "collection": "Nicene and Post-Nicene Fathers",
        },
    ]
    write_jsonl(kb_dir / "sources.jsonl", source_rows)
    with (kb_dir / "sources.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["source_id", "display_title", "pdf_file", "collection"])
        writer.writeheader()
        writer.writerows(source_rows)

    term_rows = [
        ("trinity", "TRINITY_EVID_1", 1, 10, "SRC_TRINITY"),
        ("three persons", "TRINITY_EVID_1", 1, 10, "SRC_TRINITY"),
        ("father", "TRINITY_EVID_1", 1, 10, "SRC_TRINITY"),
        ("son", "TRINITY_EVID_1", 1, 10, "SRC_TRINITY"),
        ("holy ghost", "TRINITY_EVID_1", 1, 10, "SRC_TRINITY"),
        ("substance", "TRINITY_EVID_1", 2, 10, "SRC_TRINITY"),
        ("substance", "SUBSTANCE_EVID_1", 1, 20, "SRC_MISC"),
        ("grace", "GRACE_EVID_1", 1, 30, "SRC_MISC"),
        ("faith", "GRACE_EVID_1", 1, 30, "SRC_MISC"),
        ("soul", "ANIMAL_SOUL_EVID_1", 2, 40, "SRC_MISC"),
        ("soul", "GENERIC_SOUL_EVID_1", 1, 41, "SRC_MISC"),
        ("soul", "AQUINAS_SOUL_EVID_1", 2, 42, "SRC_MISC"),
        ("soul", "CALVIN_SOUL_EVID_1", 1, 43, "SRC_MISC"),
        ("law", "LIVE_LAW_EVID_1", 1, 50, "SRC_MISC"),
        ("law", "GENERIC_LAW_EVID_1", 1, 51, "SRC_MISC"),
        ("grace", "UNKNOWN_ANF_GRACE_EVID_1", 1, 70, "SRC_ANF_UNKNOWN"),
        ("grace", "UNKNOWN_NPNF_GRACE_EVID_1", 1, 71, "SRC_NPNF_UNKNOWN"),
        ("doctrine", "AUGUSTINE_ORIGEN_DISCUSSION_EVID_1", 1, 546, "SRC_NPNF_AUGUSTINE"),
        ("grace", "AUGUSTINE_AMBROSE_DISCUSSION_EVID_1", 1, 547, "SRC_NPNF_AUGUSTINE"),
        ("grace", "AUGUSTINE_CYPRIAN_TESTIMONIES_EVID_1", 1, 548, "SRC_NPNF_AUGUSTINE"),
    ]
    concordance = {}
    for term, evidence_id, count, page, source_id in term_rows:
        concordance.setdefault(
            (term, source_id),
            {"lookup_form": term, "source_id": source_id, "occurrence_count": 0, "evidence_locations": []},
        )
        concordance[(term, source_id)]["occurrence_count"] += count
        concordance[(term, source_id)]["evidence_locations"].append(
            {"evidence_id": evidence_id, "occurrence_count": count, "page_number": page, "first_char_start": 0}
        )
    write_jsonl(kb_dir / "terms.jsonl", list(concordance.values()))
    write_jsonl(kb_dir / "scriptures.jsonl", [])

    catalog = []
    for term in sorted({row[0] for row in term_rows}):
        matching = [row for row in term_rows if row[0] == term]
        catalog.append(
            {
                "lookup_form": term,
                "evidence_row_count": len({row[1] for row in matching}),
                "occurrence_count": sum(row[2] for row in matching),
                "source_count": len({row[4] for row in matching}),
            }
        )
    write_jsonl(kb_dir / "catalog.jsonl", catalog)

    manifest = {
        "schema_version": "fixture",
        "builder_version": "fixture",
        "generated_at": "2026-08-27T00:00:00-07:00",
        "files": {
            "core_primary_evidence": ["evidence.jsonl"],
            "extended_evidence": [],
            "archival_evidence": [],
            "source_registry": ["sources.jsonl"],
            "sources": ["sources.csv"],
            "term_concordance": ["terms.jsonl"],
            "scripture_concordance": ["scriptures.jsonl"],
        },
    }
    (kb_dir / "christian_kb_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return kb_dir


def write_fixture_lexicon(root: Path) -> Path:
    path = root / "lexicon.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "concept_id": "saviour_external_alias",
                        "triggers": ["saviour"],
                        "expanded_terms": ["savior"],
                    },
                    {
                        "concept_id": "trinity_personal_relations",
                        "triggers": ["trinity", "three persons", "relationship", "persons"],
                        "expanded_terms": [
                            "Trinity",
                            "three persons",
                            "Father",
                            "Son",
                            "Holy Ghost",
                            "substance",
                            "relation",
                            "person",
                        ],
                    }
                ],
                "aliases": [
                    {"trigger": "relationship", "expanded_terms": ["relation"]},
                    {"trigger": "persons", "expanded_terms": ["person", "three persons"]},
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


class SemanticSearchTests(unittest.TestCase):
    def test_possessive_queries_are_normalized_and_safe_for_fts(self):
        self.assertEqual(common.token_list("Jesus's blood"), ["jesus", "blood"])
        fts_query = common.make_fts_query(["Jesus's", "blood"])
        self.assertEqual(fts_query, '"jesus" OR "blood"')

        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE evidence_fts USING fts5(verbatim_text)")
            con.execute("INSERT INTO evidence_fts(verbatim_text) VALUES (?)", ("The blood of Jesus's sacrifice.",))
            rows = con.execute(
                "SELECT rowid FROM evidence_fts WHERE evidence_fts MATCH ?",
                (fts_query,),
            ).fetchall()
        finally:
            con.close()
        self.assertTrue(rows)

    def test_query_expansion_is_deterministic_and_non_ai(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                expansion = search.expand_query(
                    con,
                    "relationship between three persons in trinity",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                )
            finally:
                con.close()

            self.assertIn("trinity", expansion.direct_terms)
            self.assertIn("three persons", expansion.direct_terms)
            self.assertIn("substance", expansion.expanded_terms)
            self.assertIn("relation", expansion.expanded_terms)

    def test_trinity_concept_ranks_above_unrelated_substance(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                results, _ = search.search_concept(
                    con,
                    "relationship between three persons in trinity",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    cluster_results=True,
                    limit=5,
                )
            finally:
                con.close()

            self.assertGreaterEqual(len(results), 2)
            self.assertEqual(results[0]["evidence_id"], "TRINITY_EVID_1")
            self.assertIn("three persons", results[0]["matched_registered_terms"])
            self.assertTrue(results[0]["cluster_id"])
            self.assertIn("trinity", results[0]["cluster_label"])

    def test_external_lexicon_expansion_returns_savior_evidence(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                results, expansion = search.search_concept(
                    con,
                    "Saviour",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=10,
                )
            finally:
                con.close()

            self.assertEqual(results[0]["evidence_id"], "SAVIOR_EVID_1")
            self.assertIn("savior", expansion.expanded_terms)
            self.assertEqual(expansion.morphology_terms, [])
            self.assertEqual(results[0]["matched_morphology_forms"], {})
            self.assertIn(results[0]["match_quality"], {"strong", "moderate"})
            self.assertIn(results[0]["quality_grade"], {1, 2, 3, 4, 5})
            self.assertIn(results[0]["quality_label"], {"Excellent", "Strong", "Good", "Related", "Weak"})
            self.assertEqual(results[0]["score_version"], search.SCORE_VERSION)
            self.assertGreaterEqual(results[0]["concept_score"], 0.0)
            self.assertLessEqual(results[0]["concept_score"], 100.0)

            self.assertIn("morphology", results[0]["score_breakdown"])

    def test_single_word_heading_match_is_strong_not_automatically_excellent(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                results, _ = search.search_concept(
                    con,
                    "grace",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=10,
                )
            finally:
                con.close()

            row = next(result for result in results if result["evidence_id"] == "GRACE_EVID_1")
            self.assertEqual(row["quality_label"], "Strong")
            self.assertNotEqual(row["quality_label"], "Excellent")
            self.assertAlmostEqual(sum(row["score_breakdown"].values()), row["concept_score"], places=5)

    def test_default_expansion_has_no_bundled_lexicon(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                single_term = search.expand_query(
                    con,
                    "saviour",
                    include_cooccurrence=False,
                )
                family_query = search.expand_query(
                    con,
                    "holy spirit",
                    include_cooccurrence=False,
                )
            finally:
                con.close()

            self.assertEqual(single_term.expanded_terms, [])
            self.assertEqual(single_term.morphology_terms, [])
            self.assertEqual(single_term.morphology_families, {})
            self.assertEqual(family_query.expanded_terms, [])
            self.assertEqual(family_query.morphology_terms, [])
            self.assertEqual(family_query.morphology_families, {})

    def test_external_lexicon_is_not_stored_as_morphology(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                results, expansion = search.search_concept(
                    con,
                    "saviour",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=5,
                )
            finally:
                con.close()

            self.assertIn("savior", expansion.expanded_terms)
            self.assertEqual(expansion.morphology_terms, [])
            self.assertTrue(results)
            self.assertEqual(results[0]["matched_morphology_forms"], {})
            self.assertEqual(results[0]["score_breakdown"]["morphology"], 0.0)

    def test_period_grouped_search_returns_limit_per_historical_section(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                groups, _ = search.search_concept_by_period(
                    con,
                    "soul",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=1,
                )
            finally:
                con.close()

            by_period = {group["period_id"]: group["results"] for group in groups}
            self.assertEqual(len(by_period[periods.PRE_NICENE]), 0)
            self.assertEqual(len(by_period[periods.NICENE_TO_REFORMATION]), 0)
            self.assertEqual(len(by_period[periods.POST_REFORMATION]), 0)
            self.assertEqual(len(by_period[periods.UNCLASSIFIED]), 1)
            self.assertIn(by_period[periods.UNCLASSIFIED][0]["author"], {"Tertullian", "Thomas Aquinas", "John Calvin"})

    def test_unknown_authors_use_anf_and_npnf_collection_fallback(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                groups, _ = search.search_concept_by_period(
                    con,
                    "grace",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=5,
                )
            finally:
                con.close()

            pre_ids = {row["evidence_id"] for group in groups if group["period_id"] == periods.PRE_NICENE for row in group["results"]}
            medieval_ids = {
                row["evidence_id"]
                for group in groups
                if group["period_id"] == periods.NICENE_TO_REFORMATION
                for row in group["results"]
            }
            self.assertIn("UNKNOWN_ANF_GRACE_EVID_1", pre_ids)
            self.assertIn("UNKNOWN_NPNF_GRACE_EVID_1", medieval_ids)

    def test_advanced_concept_period_filter_keeps_period_candidates(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                groups, _ = search.search_advanced_by_period(
                    con,
                    search.AdvancedSearchCriteria(concept="grace", period_id=periods.PRE_NICENE),
                    search.load_lexicon(lexicon_path),
                    limit=5,
                )
            finally:
                con.close()

            by_period = {group["period_id"]: group["results"] for group in groups}
            self.assertEqual(len(by_period[periods.PRE_NICENE]), 1)
            self.assertEqual(by_period[periods.PRE_NICENE][0]["author_period_id"], periods.PRE_NICENE)
            self.assertEqual(by_period[periods.NICENE_TO_REFORMATION], [])
            self.assertEqual(by_period[periods.POST_REFORMATION], [])

    def test_advanced_metadata_only_period_filter_returns_matching_rows(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                groups, _ = search.search_advanced_by_period(
                    con,
                    search.AdvancedSearchCriteria(period_id=periods.PRE_NICENE),
                    search.load_lexicon(lexicon_path),
                    limit=10,
                )
            finally:
                con.close()

            by_period = {group["period_id"]: group["results"] for group in groups}
            self.assertTrue(by_period[periods.PRE_NICENE])

    def test_multi_word_search_requires_all_significant_terms(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                regular, _ = search.search_concept(
                    con,
                    "faith works",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=10,
                )
                partial, _ = search.search_concept(
                    con,
                    "faith qwertytheology",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=10,
                )
                advanced, _ = search.search_advanced(
                    con,
                    search.AdvancedSearchCriteria(concept="faith works"),
                    search.load_lexicon(lexicon_path),
                    limit=10,
                )
            finally:
                con.close()

            self.assertTrue(regular)
            self.assertTrue(advanced)
            for row in (regular[0], advanced[0]):
                self.assertTrue({"faith", "works"}.issubset(set(row["matched_raw_terms"])))
            self.assertFalse(partial)

    def test_heading_only_match_is_visible_in_evidence_snippet(self):
        snippet = search.make_evidence_snippet(
            "Distinctive Grace Heading",
            "The body contains no searched word.",
            ["grace"],
        )
        self.assertIn("[[Grace]]", snippet)

    def test_advanced_unrestricted_search_keeps_each_period_independent(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                groups, _ = search.search_advanced_by_period(
                    con,
                    search.AdvancedSearchCriteria(concept="grace"),
                    search.load_lexicon(lexicon_path),
                    limit=1,
                )
            finally:
                con.close()

            by_period = {group["period_id"]: group["results"] for group in groups}
            self.assertEqual(len(by_period[periods.PRE_NICENE]), 1)
            self.assertEqual(len(by_period[periods.NICENE_TO_REFORMATION]), 1)
            self.assertEqual(by_period[periods.POST_REFORMATION], [])
            for period_id, rows in by_period.items():
                self.assertLessEqual(len(rows), 1)
                self.assertTrue(all(row["author_period_id"] == period_id for row in rows))

    def test_advanced_metadata_filters_keep_only_periods_with_real_matches(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                groups, _ = search.search_advanced_by_period(
                    con,
                    search.AdvancedSearchCriteria(concept="doctrine", mentioned_author="Origen"),
                    search.load_lexicon(lexicon_path),
                    limit=10,
                )
            finally:
                con.close()

            by_period = {group["period_id"]: group["results"] for group in groups}
            self.assertEqual(by_period[periods.PRE_NICENE], [])
            self.assertEqual(len(by_period[periods.NICENE_TO_REFORMATION]), 1)
            self.assertEqual(by_period[periods.POST_REFORMATION], [])
            result = by_period[periods.NICENE_TO_REFORMATION][0]
            self.assertEqual(result["author"], "Augustine of Hippo")
            self.assertIn("Origen", result["mentioned_authors"])

    def test_live_under_law_prefers_phrase_and_mechanical_variants(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                results, expansion = search.search_concept(
                    con,
                    "live under law",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=10,
                )
            finally:
                con.close()

            self.assertIn("living", expansion.mechanical_variants["live"])
            self.assertIn("lived", expansion.mechanical_variants["live"])
            self.assertEqual(results[0]["evidence_id"], "LIVE_LAW_EVID_1")
            self.assertIn("live", results[0]["matched_raw_terms"])
            self.assertTrue(results[0]["raw_phrase_matches"])
            self.assertTrue(results[0]["proximity_matches"])

            by_id = {row["evidence_id"]: row for row in results}
            self.assertEqual(by_id["GENERIC_LAW_EVID_1"]["match_quality"], "weak")
            self.assertLess(
                by_id["GENERIC_LAW_EVID_1"]["concept_score"],
                by_id["LIVE_LAW_EVID_1"]["concept_score"],
            )

    def test_body_only_letter_can_be_exactly_relevant_without_heading_terms(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                results, _ = search.search_concept(
                    con,
                    "faith and works",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=20,
                )
                narrow_results, _ = search.search_concept(
                    con,
                    "faith and works",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=1,
                    candidate_limit=1,
                )
            finally:
                con.close()

            row = next(result for result in results if result["evidence_id"] == "LETTER_FAITH_WORKS_EVID_1")
            self.assertEqual(row["heading"], "Letter to the Brethren")
            self.assertEqual(row["quality_label"], "Excellent")
            self.assertTrue(any(match["location"] == "body" for match in row["raw_phrase_matches"]))
            self.assertIn("faith", row["matched_raw_terms"])
            self.assertIn("works", row["matched_raw_terms"])
            self.assertEqual(narrow_results[0]["evidence_id"], "LETTER_FAITH_WORKS_EVID_1")

    def test_source_title_does_not_count_as_evidence_heading_match(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                results, _ = search.search_concept(
                    con,
                    "Holy Spirit and church",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=50,
                )
            finally:
                con.close()

            row = next(result for result in results if result["evidence_id"] == "SOURCE_TITLE_ONLY_EVID_1")
            self.assertNotEqual(row["quality_label"], "Excellent")
            self.assertNotIn("holy", row["matched_raw_terms"])
            self.assertNotIn("spirit", row["matched_raw_terms"])

    def test_generated_files_stay_under_semantic_generated_folder(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            before = {path.relative_to(kb_dir) for path in kb_dir.rglob("*")}
            generated_dir = root / "theologia_search" / "generated"
            index_path = generated_dir / "semantic_index.sqlite"
            manifest_path = generated_dir / "index_manifest.json"

            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            after = {path.relative_to(kb_dir) for path in kb_dir.rglob("*")}
            self.assertEqual(before, after)
            self.assertTrue(index_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertEqual(index_path.parent, generated_dir)

    def test_check_index_sync_reports_synced_after_build(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            report = check_index_sync.check_index_sync(
                kb_dir=kb_dir,
                index_path=index_path,
                index_manifest_path=manifest_path,
            )

            self.assertTrue(report.synced)
            self.assertEqual(report.messages, [])

    def test_dataset_version_is_written_to_manifest_and_sqlite(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            manifest = build_index.build_semantic_index(
                kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path
            )

            with sqlite3.connect(index_path) as con:
                sqlite_version = con.execute(
                    "SELECT value FROM metadata WHERE key = 'dataset_version'"
                ).fetchone()[0]

            self.assertEqual(manifest["dataset_version"], build_index.DATASET_VERSION)
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["dataset_version"],
                build_index.DATASET_VERSION,
            )
            self.assertEqual(sqlite_version, build_index.DATASET_VERSION)

    def test_check_index_sync_rejects_mismatched_dataset_versions(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dataset_version"] = "9.9.9"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = check_index_sync.check_index_sync(
                kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path
            )
            self.assertFalse(report.synced)
            self.assertTrue(any("dataset_version differs" in message for message in report.messages))

    def test_check_index_sync_rejects_missing_dataset_versions(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("dataset_version")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with sqlite3.connect(index_path) as con:
                con.execute("DELETE FROM metadata WHERE key = 'dataset_version'")
                con.commit()

            report = check_index_sync.check_index_sync(
                kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path
            )
            self.assertFalse(report.synced)
            self.assertIn("manifest missing dataset_version", report.messages)
            self.assertIn("SQLite metadata missing dataset_version", report.messages)

    def test_check_index_sync_detects_stale_kb_manifest(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            kb_manifest_path = kb_dir / "christian_kb_manifest.json"
            kb_manifest = json.loads(kb_manifest_path.read_text(encoding="utf-8"))
            kb_manifest["generated_at"] = "2026-09-04T00:00:00-07:00"
            kb_manifest_path.write_text(json.dumps(kb_manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")

            report = check_index_sync.check_index_sync(
                kb_dir=kb_dir,
                index_path=index_path,
                index_manifest_path=manifest_path,
            )

            self.assertFalse(report.synced)
            self.assertTrue(any("kb_generated_at" in message for message in report.messages))

    def test_check_index_sync_can_rebuild_missing_index(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"

            with contextlib.redirect_stdout(io.StringIO()):
                code = check_index_sync.main(
                    [
                        "--kb-dir",
                        str(kb_dir),
                        "--index",
                        str(index_path),
                        "--index-manifest",
                        str(manifest_path),
                        "--sync",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(index_path.exists())
            self.assertTrue(manifest_path.exists())
            report = check_index_sync.check_index_sync(
                kb_dir=kb_dir,
                index_path=index_path,
                index_manifest_path=manifest_path,
            )
            self.assertTrue(report.synced)

    def test_jsonl_rows_keep_citation_and_semantic_fields(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                results, _ = search.search_concept(
                    con,
                    "relationship between three persons in trinity",
                    search.load_lexicon(lexicon_path),
                    include_cooccurrence=False,
                    limit=1,
                )
            finally:
                con.close()

            row = results[0]
            for key in ["source_id", "source_title", "pdf_file", "author", "page_number", "evidence_id"]:
                self.assertIn(key, row)
            for key in [
                "concept_score",
                "score_version",
                "score_breakdown",
                "expanded_terms",
                "matched_registered_terms",
                "raw_query_terms",
                "mechanical_variants",
                "morphology_terms",
                "morphology_forms",
                "morphology_families",
                "matched_lemmas",
                "matched_term_families",
                "matched_morphology_forms",
                "matched_raw_terms",
                "raw_phrase_matches",
                "proximity_matches",
                "discovered_phrases",
                "match_quality",
                "quality_grade",
                "quality_label",
                "match_reasons",
            ]:
                self.assertIn(key, row)

    def test_semantic_index_omits_morphology_tables_and_keeps_period_data(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                metadata = dict(con.execute("SELECT key, value FROM metadata").fetchall())
                tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                author_period_count = con.execute("SELECT COUNT(*) FROM author_periods").fetchone()[0]
                tertullian = con.execute(
                    "SELECT author_period_id FROM evidence WHERE evidence_id = ?",
                    ("ANIMAL_SOUL_EVID_1",),
                ).fetchone()[0]
            finally:
                con.close()

            self.assertEqual(metadata["semantic_index_schema_version"], build_index.SEMANTIC_INDEX_SCHEMA_VERSION)
            self.assertEqual(metadata["author_period_schema_version"], periods.AUTHOR_PERIOD_SCHEMA_VERSION)
            self.assertNotIn("morphology_forms", tables)
            self.assertNotIn("evidence_morphology", tables)
            self.assertNotIn("morphology_stats", tables)
            self.assertEqual(author_period_count, 0)
            self.assertEqual(tertullian, periods.UNCLASSIFIED)

            report = check_index_sync.check_index_sync(
                kb_dir=kb_dir,
                index_path=index_path,
                index_manifest_path=manifest_path,
            )
            self.assertTrue(report.synced, report.messages)

    def test_author_period_rows_are_migrated_from_existing_sqlite(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            source_path = root / "author_period_source.sqlite"
            source = sqlite3.connect(source_path)
            source.execute(
                """
                CREATE TABLE author_periods(
                    author_norm TEXT PRIMARY KEY, author TEXT NOT NULL,
                    birth_year INTEGER, death_year INTEGER, active_year INTEGER,
                    period_id TEXT NOT NULL, period_label TEXT NOT NULL,
                    confidence TEXT NOT NULL, notes TEXT, source_urls_json TEXT NOT NULL
                )
                """
            )
            source.execute(
                "INSERT INTO author_periods VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "tertullian", "Tertullian", 155, 220, None,
                    periods.PRE_NICENE, periods.PERIOD_LABELS[periods.PRE_NICENE],
                    "high", "migrated fixture row", "[]",
                ),
            )
            source.commit()
            source.close()
            index_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, index_path)

            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)
            with sqlite3.connect(index_path) as con:
                row = con.execute(
                    "SELECT period_id, confidence, notes FROM author_periods WHERE author_norm = ?",
                    ("tertullian",),
                ).fetchone()
                evidence_source = con.execute(
                    "SELECT author_period_source FROM evidence WHERE author = ? LIMIT 1",
                    ("Tertullian",),
                ).fetchone()[0]
            self.assertEqual(row, (periods.PRE_NICENE, "high", "migrated fixture row"))
            self.assertEqual(evidence_source, "author_periods_sqlite")

    def test_result_explanation_lines_include_diagnostic_fields(self):
        row = {
            "concept_score": 12.5,
            "match_quality": "moderate",
            "author_period_label": "Before Council of Nicaea (up to 325 AD)",
            "author_period_source": "author_periods",
            "matched_raw_terms": ["animal"],
            "matched_registered_terms": ["soul"],
            "matched_lemmas": ["soul"],
            "matched_term_families": ["animal soul"],
            "raw_phrase_matches": [{"phrase": "animal soul"}],
            "proximity_matches": [{"distance": 10}],
            "match_reasons": ["matched term family: animal soul"],
            "score_breakdown": {"morphology": 3.0},
        }
        lines = dict(gui.result_explanation_lines(row))
        self.assertEqual(lines["Lemma matches"], "soul")
        self.assertEqual(lines["Term-family matches"], "animal soul")
        self.assertIn("morphology=3.0", lines["Score breakdown"])

    def test_semantic_index_preserves_reader_clean_kb_metadata(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                row = con.execute(
                    """
                    SELECT page_start, page_end, printed_page_number, printed_page_numbers_json,
                           text_role, text_status, source_spans_json, verbatim_text
                    FROM evidence
                    WHERE evidence_id = ?
                    """,
                    ("CHAPTER_29_EVID_1",),
                ).fetchone()
            finally:
                con.close()

            self.assertEqual(row["page_start"], 60)
            self.assertEqual(row["page_end"], 60)
            self.assertEqual(row["printed_page_number"], "60")
            self.assertEqual(json.loads(row["printed_page_numbers_json"]), ["60"])
            self.assertEqual(row["text_role"], "body")
            self.assertEqual(row["text_status"], "reader_clean_pdfplumber_body_text")
            self.assertEqual(json.loads(row["source_spans_json"])[0]["page_number"], 60)
            self.assertEqual(row["verbatim_text"], "Chapter 29 begins with righteous men living under grace.")

    def test_discovery_candidates_are_pending_and_keep_citation(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            before = {path.relative_to(kb_dir) for path in kb_dir.rglob("*")}
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            jsonl_out = root / "theologia_search" / "review" / "term_discovery_candidates.jsonl"
            csv_out = root / "theologia_search" / "review" / "term_discovery_candidates.csv"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                rows = discover_from_queries.discover_candidates(
                    con,
                    ["Saviour"],
                    search.load_lexicon(lexicon_path),
                    limit=5,
                )
            finally:
                con.close()
            discover_from_queries.write_jsonl(jsonl_out, rows)
            discover_from_queries.write_csv(csv_out, rows)

            after = {path.relative_to(kb_dir) for path in kb_dir.rglob("*")}
            self.assertEqual(before, after)
            self.assertTrue(rows)
            self.assertTrue(jsonl_out.exists())
            self.assertTrue(csv_out.exists())
            row = rows[0]
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["query"], "Saviour")
            self.assertIn("candidate_phrase", row)
            self.assertIn("source_id", row)
            self.assertIn("evidence_id", row)
            self.assertGreaterEqual(row["occurrence_count"], 1)

    def test_neighborhoods_connect_terms_and_cluster_deterministically(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            neighborhoods_path = root / "theologia_search" / "generated" / "concept_neighborhoods.jsonl"
            clusters_path = root / "theologia_search" / "generated" / "concept_clusters.jsonl"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            rows, clusters = build_neighborhoods.build_neighborhoods(
                index_path=index_path,
                neighborhoods_path=neighborhoods_path,
                clusters_path=clusters_path,
                min_weight=0.5,
                min_cluster_weight=0.5,
            )

            self.assertTrue(neighborhoods_path.exists())
            self.assertTrue(clusters_path.exists())
            pairs = {(row["anchor"], row["neighbor"]) for row in rows}
            self.assertIn(("three persons", "trinity"), pairs)
            self.assertTrue(any("trinity" in row["members"] and "three persons" in row["members"] for row in clusters))
            self.assertEqual(rows, sorted(rows, key=lambda row: (-row["weight"], row["anchor"], row["neighbor"])))

    def test_evaluation_report_flags_expected_hits(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            queries_path = root / "theologia_search" / "evaluation" / "queries.jsonl"
            json_out = root / "theologia_search" / "generated" / "evaluation_report.json"
            md_out = root / "theologia_search" / "generated" / "evaluation_report.md"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)
            write_jsonl(
                queries_path,
                [
                    {
                        "query_id": "saviour_fixture",
                        "concept": "Saviour",
                        "expected_terms": ["savior"],
                        "expected_evidence_ids": ["SAVIOR_EVID_1"],
                    },
                    {
                        "query_id": "live_law_fixture",
                        "concept": "live under law",
                        "expected_terms": ["law"],
                        "expected_evidence_ids": ["LIVE_LAW_EVID_1"],
                    },
                ],
            )

            report = evaluate_search.evaluate_search(
                index_path=index_path,
                lexicon_path=lexicon_path,
                queries_path=queries_path,
                json_out=json_out,
                markdown_out=md_out,
                limit=5,
            )

            self.assertEqual(report["query_count"], 2)
            self.assertEqual(report["passed_count"], 2)
            self.assertTrue(json_out.exists())
            self.assertTrue(md_out.exists())
            self.assertTrue(all(row["passed"] for row in report["results"]))

    def test_gui_history_helpers_save_load_and_clear(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            history_path = root / "theologia_search" / "generated" / "gui_search_history.json"

            history = gui.add_history_item([], "Saviour")
            history = gui.add_history_item(history, "live under law")
            history = gui.add_history_item(history, "Saviour")
            gui.save_history(history, history_path)

            self.assertEqual(gui.load_history(history_path), ["Saviour", "live under law"])
            gui.clear_history(history_path)
            self.assertEqual(gui.load_history(history_path), [])

    def test_gui_limit_validation(self):
        self.assertEqual(gui.validate_limit(""), 10)
        self.assertEqual(gui.validate_limit("25"), 25)
        with self.assertRaises(ValueError):
            gui.validate_limit("0")
        with self.assertRaises(ValueError):
            gui.validate_limit("abc")
        with self.assertRaises(ValueError):
            gui.validate_limit("101")

    def test_gui_search_adapter_returns_results_and_discovered_terms(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            output = gui.run_search("Saviour", limit=3, index_path=index_path, lexicon_path=lexicon_path)

            self.assertEqual(output.query, "Saviour")
            self.assertEqual(output.limit, 3)
            self.assertTrue(output.results)
            self.assertEqual(output.results[0]["evidence_id"], "SAVIOR_EVID_1")
            self.assertTrue(output.discovered_phrases)

    def test_gui_search_adapter_can_return_period_groups(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            output = gui.run_search(
                "soul",
                limit=1,
                index_path=index_path,
                lexicon_path=lexicon_path,
                period_sections=True,
            )

            self.assertTrue(output.period_groups)
            self.assertGreaterEqual(len(output.results), 1)
            self.assertTrue(all(len(group["results"]) <= 1 for group in output.period_groups))

    def test_gui_result_fields_separate_labels_and_values(self):
        row = {
            "source_id": "SRC_MISC",
            "source_title": "Misc Source",
            "page_number": 40,
            "author": "Tertullian",
            "evidence_id": "ANIMAL_SOUL_EVID_1",
            "concept_score": 64.5,
            "match_quality": "strong",
            "heading": "Animalis, Composed of Soul",
            "matched_registered_terms": ["soul"],
            "matched_raw_terms": ["animal"],
            "match_reasons": ["matched non-registered query term: animal"],
            "snippet": "They alleged that Christ's flesh was animalis, composed of soul.",
        }

        fields = gui.result_fields(1, row)
        labels = {label for kind, label, _value in fields if kind != "title"}

        self.assertIn(("field", "Source", "Misc Source"), fields)
        self.assertIn(("field", "Author", "Tertullian"), fields)
        self.assertIn(("field", "Quality", "strong"), fields)
        self.assertIn(("field", "Heading", "Animalis, Composed of Soul"), fields)
        self.assertNotIn("Page", labels)
        self.assertNotIn("Period", labels)
        self.assertNotIn("Evidence", labels)
        self.assertNotIn("Score", labels)
        self.assertNotIn("Terms", labels)
        self.assertNotIn("Raw matches", labels)
        self.assertNotIn("Lemmas", labels)
        self.assertNotIn("Term families", labels)
        self.assertNotIn("Why", {label for _kind, label, _value in fields})
        self.assertTrue(any(kind == "body" and label == "Snippet" for kind, label, _value in fields))

    def test_result_explanation_lines_include_removed_main_fields(self):
        row = {
            "source_id": "SRC_MISC",
            "source_title": "Misc Source",
            "page_number": 40,
            "author": "Tertullian",
            "author_period_label": "Before Council of Nicaea",
            "author_period_source": "author_periods",
            "evidence_id": "ANIMAL_SOUL_EVID_1",
            "concept_score": 64.5,
            "match_quality": "strong",
            "heading": "Animalis, Composed of Soul",
            "matched_registered_terms": ["soul"],
            "matched_raw_terms": ["animal"],
            "matched_lemmas": ["souls -> soul"],
            "matched_term_families": ["animal soul"],
            "score_breakdown": {"registered_term_score": 12.0},
        }

        lines = dict(gui.result_explanation_lines(row))

        self.assertEqual(lines["Source"], "Misc Source")
        self.assertEqual(lines["Author"], "Tertullian")
        self.assertEqual(lines["Heading"], "Animalis, Composed of Soul")
        self.assertEqual(lines["Page"], "40")
        self.assertEqual(lines["Evidence"], "ANIMAL_SOUL_EVID_1")
        self.assertEqual(lines["Period"], "Before Council of Nicaea")
        self.assertEqual(lines["Score"], "64.5")
        self.assertIn("soul", lines["Registered KB terms"])
        self.assertIn("animal", lines["Exact/raw terms"])
        self.assertIn("souls -> soul", lines["Lemma matches"])
        self.assertIn("animal soul", lines["Term-family matches"])

    def test_gui_result_index_from_tags(self):
        self.assertEqual(gui.result_index_from_tags(("sel", "result_2", "field_value")), 2)
        self.assertEqual(gui.result_index_from_tags(("result_block", "field_value")), None)

    def test_gui_context_retrieval_includes_neighboring_evidence(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            context = gui.fetch_context(
                "ANIMAL_SOUL_EVID_1",
                index_path=index_path,
                before_words=8,
                after_words=8,
            )
            ids = [row["evidence_id"] for row in context.rows]

            self.assertIn("GRACE_EVID_1", ids)
            self.assertIn("ANIMAL_SOUL_EVID_1", ids)
            self.assertIn("GENERIC_SOUL_EVID_1", ids)
            self.assertGreaterEqual(context.before_word_count, 8)
            self.assertGreaterEqual(context.after_word_count, 8)
            self.assertIn("SELECTED EVIDENCE", gui.context_rows_to_text(context))
            self.assertIn("animalis, composed of soul", gui.context_rows_to_text(context).casefold())

    def test_gui_context_retrieval_prefers_complete_chapter(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            context = gui.fetch_context("CHAPTER_29_EVID_1", index_path=index_path)
            ids = [row["evidence_id"] for row in context.rows]
            text = gui.context_rows_to_text(context)

            self.assertEqual(context.mode, "chapter")
            self.assertEqual(context.page_range, "60-61")
            self.assertEqual(ids, ["CHAPTER_29_EVID_1", "CHAPTER_29_EVID_2"])
            self.assertNotIn("CHAPTER_30_EVID_1", ids)
            self.assertIn("[SELECTED EVIDENCE]", text)
            self.assertNotIn("[SELECTED EVIDENCE] CHAPTER_29_EVID_1", text)
            self.assertIn("Chapter 29 continues with more evidence about grace and law.", text)
            self.assertNotIn("grace.\n\nChapter 29 continues", text)
            self.assertNotIn("[CHAPTER CONTINUED] CHAPTER_29_EVID_2", text)

    def test_gui_context_missing_evidence_errors_clearly(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            with self.assertRaises(gui.SemanticSearchError) as raised:
                gui.fetch_context("MISSING_EVIDENCE", index_path=index_path)

            self.assertIn("Evidence id not found", str(raised.exception))

    def test_advanced_search_matches_author_name_parts_and_book(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)
            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                lexicon = search.load_lexicon(lexicon_path)
                for author_query in ("John Calvin", "John", "Calvin"):
                    results, _ = search.search_advanced(
                        con, search.AdvancedSearchCriteria(author=author_query), lexicon, limit=5
                    )
                    self.assertIn("CALVIN_SOUL_EVID_1", [row["evidence_id"] for row in results])
                results, _ = search.search_advanced(
                    con, search.AdvancedSearchCriteria(book="Holy Spirit"), lexicon, limit=5
                )
                self.assertEqual([row["evidence_id"] for row in results], ["SOURCE_TITLE_ONLY_EVID_1"])
            finally:
                con.close()

    def test_discussed_authors_do_not_become_work_authors(self):
        self.assertEqual(
            kb_builder.explicit_author_from_heading("Of the Error in Which the Doctrine of Origen is Involved."),
            "",
        )
        self.assertEqual(
            kb_builder.explicit_author_from_heading("Ambrose Most Highly Praised by Pelagius."),
            "",
        )
        self.assertEqual(kb_builder.explicit_author_from_heading("Cyprian's Testimonies."), "")
        self.assertEqual(kb_builder.explicit_author_from_heading("The Epistles of Cyprian."), "Cyprian of Carthage")
        self.assertEqual(kb_builder.explicit_author_from_heading("The Epistle of Cyprian."), "Cyprian of Carthage")
        self.assertEqual(
            kb_builder.explicit_author_from_heading("In which he treats of what follows in the same epistle of Cyprian to Jubaianus."),
            "",
        )

    def test_advanced_search_separates_work_author_from_mentioned_author(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)
            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                lexicon = search.load_lexicon(lexicon_path)
                indexed = dict(
                    con.execute(
                        "SELECT author, author_period_id, mentioned_authors_json FROM evidence WHERE evidence_id = ?",
                        ("AUGUSTINE_ORIGEN_DISCUSSION_EVID_1",),
                    ).fetchone()
                )
                self.assertEqual(indexed["author"], "Augustine of Hippo")
                self.assertEqual(indexed["author_period_id"], "nicene_to_reformation")
                self.assertEqual(json.loads(indexed["mentioned_authors_json"]), ["Origen"])

                results, _ = search.search_advanced(
                    con,
                    search.AdvancedSearchCriteria(concept="doctrine", author="Origen"),
                    lexicon,
                    limit=10,
                )
                self.assertNotIn("AUGUSTINE_ORIGEN_DISCUSSION_EVID_1", [row["evidence_id"] for row in results])

                results, _ = search.search_advanced(
                    con,
                    search.AdvancedSearchCriteria(concept="doctrine", mentioned_author="Origen"),
                    lexicon,
                    limit=10,
                )
                by_id = {row["evidence_id"]: row for row in results}
                self.assertIn("AUGUSTINE_ORIGEN_DISCUSSION_EVID_1", by_id)
                self.assertEqual(by_id["AUGUSTINE_ORIGEN_DISCUSSION_EVID_1"]["author"], "Augustine of Hippo")
                self.assertEqual(
                    by_id["AUGUSTINE_ORIGEN_DISCUSSION_EVID_1"]["author_period_id"],
                    "nicene_to_reformation",
                )
                self.assertEqual(by_id["AUGUSTINE_ORIGEN_DISCUSSION_EVID_1"]["mentioned_authors"], ["Origen"])

                ambrose_results, _ = search.search_advanced(
                    con,
                    search.AdvancedSearchCriteria(mentioned_author="Ambrose of Milan"),
                    lexicon,
                    limit=10,
                )
                self.assertIn("AUGUSTINE_AMBROSE_DISCUSSION_EVID_1", [row["evidence_id"] for row in ambrose_results])
                author_results, _ = search.search_advanced(
                    con,
                    search.AdvancedSearchCriteria(author="Ambrose of Milan"),
                    lexicon,
                    limit=10,
                )
                self.assertNotIn("AUGUSTINE_AMBROSE_DISCUSSION_EVID_1", [row["evidence_id"] for row in author_results])

                cyprian_results, _ = search.search_advanced(
                    con,
                    search.AdvancedSearchCriteria(mentioned_author="Cyprian of Carthage"),
                    lexicon,
                    limit=10,
                )
                self.assertIn("AUGUSTINE_CYPRIAN_TESTIMONIES_EVID_1", [row["evidence_id"] for row in cyprian_results])
            finally:
                con.close()

    def test_author_option_lists_are_read_from_independent_sqlite_tables(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)

            work_authors = set(gui.registered_author_names(index_path))
            mentioned_authors = set(gui.registered_author_names(index_path, mentioned=True))

            self.assertIn("Augustine of Hippo", work_authors)
            self.assertNotIn("Origen", work_authors)
            self.assertIn("Origen", mentioned_authors)
            self.assertIn("Ambrose of Milan", mentioned_authors)

    def test_advanced_search_chapter_number_and_mixed_connectors(self):
        with temp_workspace() as tmp_name:
            root = Path(tmp_name)
            kb_dir = write_fixture_kb(root)
            index_path = root / "theologia_search" / "generated" / "semantic_index.sqlite"
            manifest_path = root / "theologia_search" / "generated" / "index_manifest.json"
            lexicon_path = write_fixture_lexicon(root)
            build_index.build_semantic_index(kb_dir=kb_dir, index_path=index_path, index_manifest_path=manifest_path)
            con = sqlite3.connect(str(index_path))
            con.row_factory = sqlite3.Row
            try:
                lexicon = search.load_lexicon(lexicon_path)
                results, _ = search.search_advanced(
                    con, search.AdvancedSearchCriteria(chapter="29"), lexicon, limit=10
                )
                ids = [row["evidence_id"] for row in results]
                self.assertEqual(ids, ["CHAPTER_29_EVID_1", "CHAPTER_29_EVID_2"])
                results, _ = search.search_advanced(
                    con,
                    search.AdvancedSearchCriteria(
                        author="Thomas", chapter="29", connectors=("AND", "AND", "AND", "OR")
                    ),
                    lexicon,
                    limit=10,
                )
                ids = [row["evidence_id"] for row in results]
                self.assertIn("AQUINAS_SOUL_EVID_1", ids)
                self.assertIn("CHAPTER_29_EVID_1", ids)
                self.assertNotIn("CHAPTER_30_EVID_1", ids)
            finally:
                con.close()

    def test_advanced_search_rejects_empty_and_reports_metadata_score(self):
        with self.assertRaises(common.SemanticSearchError):
            search.validate_advanced_criteria(search.AdvancedSearchCriteria())
        row = {"author": "John Calvin", "source_title": "A Treatise", "heading": "Chapter 29", "outline_path": ""}
        criteria = search.AdvancedSearchCriteria(author="Calvin", chapter="29")
        matches, exact_fields = search.advanced_metadata_matches(row, criteria)
        self.assertEqual(matches, {"author": True, "chapter": True})
        self.assertEqual(exact_fields, 0)


if __name__ == "__main__":
    unittest.main()

