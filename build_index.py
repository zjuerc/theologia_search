#!/usr/bin/env python3
"""Build a deterministic local semantic-search index from the source-faithful KB."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

try:
    from . import morphology
    from . import periods
    from .common import (
        DEFAULT_INDEX_MANIFEST_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_KB_DIR,
        SemanticSearchError,
        configure_output,
        display_text,
        iter_jsonl,
        load_manifest,
        load_sources,
        manifest_paths,
        norm_lookup,
        selected_evidence_paths,
        write_json,
    )
except ImportError:  # pragma: no cover - supports direct script execution.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import morphology
    import periods
    from common import (
        DEFAULT_INDEX_MANIFEST_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_KB_DIR,
        SemanticSearchError,
        configure_output,
        display_text,
        iter_jsonl,
        load_manifest,
        load_sources,
        manifest_paths,
        norm_lookup,
        selected_evidence_paths,
        write_json,
    )


SEMANTIC_INDEX_SCHEMA_VERSION = "1.5.0"
DATASET_VERSION = "1.0.0"


SCHEMA_SQL = """
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    display_title TEXT,
    pdf_file TEXT,
    collection TEXT
);

CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    retrieval_layer TEXT NOT NULL,
    page_number INTEGER,
    page_start INTEGER,
    page_end INTEGER,
    printed_page_number TEXT,
    printed_page_numbers_json TEXT,
    text_role TEXT,
    text_status TEXT,
    author TEXT,
    author_norm TEXT,
    mentioned_authors_json TEXT,
    mentioned_authors_text TEXT,
    mentioned_authors_norm TEXT,
    source_title TEXT,
    source_title_norm TEXT,
    source_collection TEXT,
    pdf_file TEXT,
    pdf_file_norm TEXT,
    author_period_id TEXT,
    author_period_label TEXT,
    author_period_year INTEGER,
    author_period_source TEXT,
    author_period_confidence TEXT,
    heading TEXT,
    heading_norm TEXT,
    outline_path TEXT,
    outline_path_norm TEXT,
    verbatim_text TEXT NOT NULL,
    source_spans_json TEXT,
    footnote_refs_json TEXT,
    term_text TEXT,
    scripture_text TEXT
);

CREATE VIRTUAL TABLE evidence_fts USING fts5(
    evidence_id UNINDEXED,
    source_id UNINDEXED,
    source_title,
    author,
    mentioned_authors,
    heading,
    outline_path,
    verbatim_text,
    term_text,
    scripture_text,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE evidence_terms (
    evidence_id TEXT NOT NULL,
    term TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL,
    idf REAL NOT NULL,
    PRIMARY KEY (evidence_id, term)
);

CREATE TABLE term_stats (
    term TEXT PRIMARY KEY,
    evidence_count INTEGER NOT NULL,
    occurrence_count INTEGER NOT NULL,
    source_count INTEGER NOT NULL,
    idf REAL NOT NULL,
    is_common INTEGER NOT NULL
);

CREATE TABLE morphology_forms (
    form TEXT NOT NULL,
    canonical TEXT NOT NULL,
    family_id TEXT NOT NULL,
    family_label TEXT NOT NULL,
    kind TEXT NOT NULL,
    weight REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (form, canonical, family_id, kind)
);

CREATE TABLE evidence_morphology (
    evidence_id TEXT NOT NULL,
    canonical TEXT NOT NULL,
    family_id TEXT NOT NULL,
    family_label TEXT NOT NULL,
    kind TEXT NOT NULL,
    form TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (evidence_id, canonical, family_id, kind, form)
);

CREATE TABLE morphology_stats (
    canonical TEXT NOT NULL,
    family_id TEXT NOT NULL,
    family_label TEXT NOT NULL,
    kind TEXT NOT NULL,
    evidence_count INTEGER NOT NULL,
    occurrence_count INTEGER NOT NULL,
    source_count INTEGER NOT NULL,
    idf REAL NOT NULL,
    PRIMARY KEY (canonical, family_id, kind)
);

CREATE TABLE author_periods (
    author_norm TEXT PRIMARY KEY,
    author TEXT NOT NULL,
    birth_year INTEGER,
    death_year INTEGER,
    active_year INTEGER,
    period_id TEXT NOT NULL,
    period_label TEXT NOT NULL,
    confidence TEXT NOT NULL,
    notes TEXT,
    source_urls_json TEXT NOT NULL
);

CREATE TABLE evidence_mentioned_authors (
    evidence_id TEXT NOT NULL,
    author_norm TEXT NOT NULL,
    author TEXT NOT NULL,
    PRIMARY KEY (author_norm, evidence_id)
);

CREATE INDEX idx_evidence_source ON evidence(source_id);
CREATE INDEX idx_evidence_author_norm ON evidence(author_norm);
CREATE INDEX idx_evidence_mentioned_authors_norm ON evidence(mentioned_authors_norm);
CREATE INDEX idx_evidence_period ON evidence(author_period_id);
CREATE INDEX idx_evidence_source_page ON evidence(source_id, page_start, page_number, evidence_id);
CREATE INDEX idx_evidence_heading_norm ON evidence(source_id, heading_norm);
CREATE INDEX idx_evidence_terms_term ON evidence_terms(term);
CREATE INDEX idx_evidence_terms_evidence ON evidence_terms(evidence_id);
CREATE INDEX idx_evidence_morphology_key ON evidence_morphology(canonical, family_id, kind);
CREATE INDEX idx_evidence_morphology_evidence ON evidence_morphology(evidence_id);
CREATE INDEX idx_mentioned_author_evidence ON evidence_mentioned_authors(author_norm, evidence_id);
CREATE INDEX idx_mentioned_author_id ON evidence_mentioned_authors(evidence_id);
"""


def remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def load_evidence_rows(manifest: dict, kb_dir: Path, layer: str) -> list[dict]:
    rows = []
    for path in selected_evidence_paths(manifest, layer, kb_dir):
        for row in iter_jsonl(path):
            evidence_id = row.get("evidence_id")
            if not evidence_id:
                continue
            rows.append(row)
    return rows


def load_evidence_terms(manifest: dict, kb_dir: Path, evidence_ids: set[str]) -> dict[str, Counter]:
    evidence_terms: dict[str, Counter] = defaultdict(Counter)
    if not evidence_ids:
        return evidence_terms

    for path in manifest_paths(manifest, "term_concordance", kb_dir):
        for row in iter_jsonl(path):
            term = norm_lookup(row.get("lookup_form"))
            if not term:
                continue
            for location in row.get("evidence_locations", []):
                evidence_id = location.get("evidence_id")
                if evidence_id not in evidence_ids:
                    continue
                count = int(location.get("occurrence_count") or 1)
                evidence_terms[evidence_id][term] += count
    return evidence_terms


def load_evidence_scriptures(manifest: dict, kb_dir: Path, evidence_ids: set[str]) -> dict[str, set[str]]:
    evidence_scriptures: dict[str, set[str]] = defaultdict(set)
    if not evidence_ids:
        return evidence_scriptures

    for path in manifest_paths(manifest, "scripture_concordance", kb_dir):
        for row in iter_jsonl(path):
            key = display_text(row.get("canonical_or_unresolved_key") or row.get("shared_value"))
            printed_forms = row.get("printed_forms")
            forms = {key} if key else set()
            if isinstance(printed_forms, dict):
                forms.update(display_text(form) for form in printed_forms if display_text(form))
            if not forms:
                continue
            for location in row.get("evidence_locations", []):
                evidence_id = location.get("evidence_id")
                if evidence_id in evidence_ids:
                    evidence_scriptures[evidence_id].update(forms)
    return evidence_scriptures


def compute_term_stats(
    evidence_rows: list[dict],
    evidence_terms: dict[str, Counter],
) -> dict[str, dict]:
    evidence_by_id = {row.get("evidence_id"): row for row in evidence_rows}
    evidence_total = max(1, len(evidence_rows))
    stats: dict[str, dict] = {}
    by_term: dict[str, dict] = defaultdict(lambda: {"evidence": set(), "sources": set(), "occurrences": 0})

    for evidence_id, terms in evidence_terms.items():
        source_id = evidence_by_id.get(evidence_id, {}).get("source_id")
        for term, count in terms.items():
            by_term[term]["evidence"].add(evidence_id)
            if source_id:
                by_term[term]["sources"].add(source_id)
            by_term[term]["occurrences"] += count

    for term, values in by_term.items():
        evidence_count = len(values["evidence"])
        idf = math.log((1 + evidence_total) / (1 + evidence_count)) + 1.0
        stats[term] = {
            "evidence_count": evidence_count,
            "occurrence_count": values["occurrences"],
            "source_count": len(values["sources"]),
            "idf": idf,
            "is_common": evidence_count >= 100 and evidence_count / evidence_total >= 0.08,
        }
    return stats


def compute_morphology_rows(evidence_rows: list[dict]) -> tuple[list[tuple], dict[tuple[str, str, str], dict]]:
    config = morphology.load_morphology()
    catalog = morphology.build_form_catalog(config)
    evidence_by_id = {row.get("evidence_id"): row for row in evidence_rows}
    evidence_total = max(1, len(evidence_rows))
    evidence_morphology_rows: list[tuple] = []
    by_key: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {"evidence": set(), "sources": set(), "occurrences": 0, "family_label": ""}
    )

    for row in evidence_rows:
        evidence_id = row.get("evidence_id")
        if not evidence_id:
            continue
        text = " ".join(
            [
                display_text(row.get("active_heading") or row.get("heading")),
                display_text(row.get("outline_path")),
                display_text(row.get("reader_text") or row.get("verbatim_text")),
            ]
        )
        matches = morphology.match_text(text, catalog)
        counts = morphology.aggregate_counts(matches)
        match_lookup = {(match.canonical, match.family_id, match.form): match for match in matches}
        for (canonical, family_id, form), count in sorted(counts.items()):
            match = match_lookup[(canonical, family_id, form)]
            key = (canonical, family_id, match.kind)
            source_id = evidence_by_id.get(evidence_id, {}).get("source_id")
            by_key[key]["family_label"] = match.family_label
            by_key[key]["evidence"].add(evidence_id)
            if source_id:
                by_key[key]["sources"].add(source_id)
            by_key[key]["occurrences"] += count
            evidence_morphology_rows.append(
                (
                    evidence_id,
                    canonical,
                    family_id,
                    match.family_label,
                    match.kind,
                    form,
                    count,
                    match.weight,
                )
            )

    stats: dict[tuple[str, str, str], dict] = {}
    for key, values in by_key.items():
        evidence_count = len(values["evidence"])
        stats[key] = {
            "family_label": values["family_label"],
            "evidence_count": evidence_count,
            "occurrence_count": values["occurrences"],
            "source_count": len(values["sources"]),
            "idf": math.log((1 + evidence_total) / (1 + evidence_count)) + 1.0,
        }
    return evidence_morphology_rows, stats


def create_connection(index_path: Path) -> sqlite3.Connection:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    remove_sqlite_sidecars(index_path)
    con = sqlite3.connect(str(index_path))
    con.executescript(SCHEMA_SQL)
    return con


def source_value(sources: dict[str, dict], source_id: str | None, key: str) -> str:
    return display_text(sources.get(source_id or "", {}).get(key))


def insert_metadata(
    con: sqlite3.Connection,
    *,
    layer: str,
    kb_dir: Path,
    manifest: dict,
    evidence_count: int,
    term_count: int,
) -> None:
    metadata = {
        "dataset_version": DATASET_VERSION,
        "semantic_index_schema_version": SEMANTIC_INDEX_SCHEMA_VERSION,
        "morphology_schema_version": morphology.MORPHOLOGY_SCHEMA_VERSION,
        "morphology_config_digest": morphology.morphology_digest(),
        "author_period_schema_version": periods.AUTHOR_PERIOD_SCHEMA_VERSION,
        "author_periods_digest": periods.author_periods_digest(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "kb_dir": str(kb_dir),
        "kb_schema_version": display_text(manifest.get("schema_version")),
        "kb_builder_version": display_text(manifest.get("builder_version")),
        "kb_generated_at": display_text(manifest.get("generated_at")),
        "layer": layer,
        "evidence_count": str(evidence_count),
        "term_count": str(term_count),
        "policy": json.dumps(
            {
                "ai_models_used": False,
                "embeddings_used": False,
                "generated_theological_conclusions": False,
                "source_faithful_kb_modified": False,
            },
            sort_keys=True,
        ),
    }
    con.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items())


def build_semantic_index(
    *,
    kb_dir: Path = DEFAULT_KB_DIR,
    index_path: Path = DEFAULT_INDEX_PATH,
    index_manifest_path: Path = DEFAULT_INDEX_MANIFEST_PATH,
    layer: str = "primary",
) -> dict:
    manifest = load_manifest(kb_dir)
    sources = load_sources(manifest, kb_dir)
    evidence_rows = load_evidence_rows(manifest, kb_dir, layer)
    evidence_ids = {row["evidence_id"] for row in evidence_rows}
    evidence_terms = load_evidence_terms(manifest, kb_dir, evidence_ids)
    evidence_scriptures = load_evidence_scriptures(manifest, kb_dir, evidence_ids)
    term_stats = compute_term_stats(evidence_rows, evidence_terms)
    morphology_config = morphology.load_morphology()
    morphology_catalog = morphology.build_form_catalog(morphology_config)
    evidence_morphology_rows, morphology_stats = compute_morphology_rows(evidence_rows)
    author_periods_config = periods.load_author_periods()

    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = index_path.with_name(index_path.name + ".tmp")
    remove_sqlite_sidecars(temp_path)

    con = create_connection(temp_path)
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("BEGIN")

        insert_metadata(
            con,
            layer=layer,
            kb_dir=kb_dir,
            manifest=manifest,
            evidence_count=len(evidence_rows),
            term_count=len(term_stats),
        )

        con.executemany(
            "INSERT INTO sources(source_id, display_title, pdf_file, collection) VALUES (?, ?, ?, ?)",
            [
                (
                    source_id,
                    display_text(source.get("display_title")),
                    display_text(source.get("pdf_file")),
                    display_text(source.get("collection")),
                )
                for source_id, source in sorted(sources.items())
            ],
        )
        con.executemany(
            """
            INSERT INTO author_periods(
                author_norm, author, birth_year, death_year, active_year, period_id,
                period_label, confidence, notes, source_urls_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    norm_lookup(row.get("author_norm") or row.get("author")),
                    display_text(row.get("author")),
                    row.get("birth_year"),
                    row.get("death_year"),
                    row.get("active_year"),
                    row.get("period_id"),
                    periods.PERIOD_LABELS.get(row.get("period_id"), row.get("period_id")),
                    display_text(row.get("confidence") or "medium"),
                    display_text(row.get("notes")),
                    json.dumps(row.get("source_urls") or [], ensure_ascii=False, sort_keys=True),
                )
                for row in author_periods_config.get("authors", [])
                if norm_lookup(row.get("author_norm") or row.get("author")) and row.get("period_id")
            ],
        )

        evidence_insert_rows = []
        fts_insert_rows = []
        evidence_term_rows = []

        for row in evidence_rows:
            evidence_id = row["evidence_id"]
            source_id = row.get("source_id")
            title = source_value(sources, source_id, "display_title")
            pdf_file = source_value(sources, source_id, "pdf_file")
            collection = source_value(sources, source_id, "collection")
            author = display_text(row.get("work_attributed_author"))
            mentioned_authors = sorted(
                {
                    display_text(author)
                    for author in row.get("mentioned_authors", [])
                    if display_text(author)
                },
                key=str.casefold,
            )
            mentioned_authors_text = " ".join(mentioned_authors)
            period = periods.assign_period(author, collection, author_periods_config)
            heading = display_text(row.get("active_heading") or row.get("heading"))
            outline_path = display_text(row.get("outline_path"))
            text = row.get("reader_text") or row.get("verbatim_text") or ""
            term_counter = evidence_terms.get(evidence_id, Counter())
            term_text = " ".join(sorted(term_counter))
            scripture_text = " ".join(sorted(evidence_scriptures.get(evidence_id, set())))

            evidence_insert_rows.append(
                (
                    evidence_id,
                    source_id,
                    row.get("retrieval_layer") or layer,
                    row.get("page_number"),
                    row.get("page_start") or row.get("page_number"),
                    row.get("page_end") or row.get("page_number"),
                    display_text(row.get("printed_page_number")),
                    json.dumps(row.get("printed_page_numbers") or [], ensure_ascii=False, sort_keys=True),
                    display_text(row.get("text_role") or row.get("content_role")),
                    display_text(row.get("text_status")),
                    author,
                    norm_lookup(author),
                    json.dumps(mentioned_authors, ensure_ascii=False, sort_keys=True),
                    mentioned_authors_text,
                    norm_lookup(" | ".join(mentioned_authors)),
                    title,
                    norm_lookup(title),
                    collection,
                    pdf_file,
                    norm_lookup(pdf_file).replace("\\", "/"),
                    period.period_id,
                    period.period_label,
                    period.basis_year,
                    period.source,
                    period.confidence,
                    heading,
                    norm_lookup(heading),
                    outline_path,
                    norm_lookup(outline_path),
                    text,
                    json.dumps(row.get("source_spans") or [], ensure_ascii=False, sort_keys=True),
                    json.dumps(row.get("footnote_refs") or [], ensure_ascii=False, sort_keys=True),
                    term_text,
                    scripture_text,
                )
            )
            fts_insert_rows.append(
                (
                    evidence_id,
                    source_id,
                    title,
                    author,
                    mentioned_authors_text,
                    heading,
                    outline_path,
                    text,
                    term_text,
                    scripture_text,
                )
            )
            for term, count in sorted(term_counter.items()):
                evidence_term_rows.append((evidence_id, term, count, term_stats[term]["idf"]))

        con.executemany(
            """
            INSERT INTO evidence(
                evidence_id, source_id, retrieval_layer, page_number,
                page_start, page_end, printed_page_number, printed_page_numbers_json,
                text_role, text_status,
                author, author_norm, mentioned_authors_json,
                mentioned_authors_text, mentioned_authors_norm,
                source_title, source_title_norm,
                source_collection, pdf_file, pdf_file_norm,
                author_period_id, author_period_label, author_period_year,
                author_period_source, author_period_confidence,
                heading, heading_norm,
                outline_path, outline_path_norm, verbatim_text,
                source_spans_json, footnote_refs_json, term_text, scripture_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            evidence_insert_rows,
        )
        con.executemany(
            """
            INSERT INTO evidence_fts(
                evidence_id, source_id, source_title, author, mentioned_authors, heading,
                outline_path, verbatim_text, term_text, scripture_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fts_insert_rows,
        )
        con.executemany(
            "INSERT INTO evidence_terms(evidence_id, term, occurrence_count, idf) VALUES (?, ?, ?, ?)",
            evidence_term_rows,
        )
        con.executemany(
            "INSERT INTO evidence_mentioned_authors(evidence_id, author_norm, author) VALUES (?, ?, ?)",
            [
                (evidence_id, norm_lookup(author), author)
                for row in evidence_rows
                for evidence_id in [row["evidence_id"]]
                for author in sorted(
                    {
                        display_text(value)
                        for value in row.get("mentioned_authors", [])
                        if display_text(value) and norm_lookup(value)
                    },
                    key=str.casefold,
                )
            ],
        )
        con.executemany(
            """
            INSERT INTO term_stats(term, evidence_count, occurrence_count, source_count, idf, is_common)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    term,
                    values["evidence_count"],
                    values["occurrence_count"],
                    values["source_count"],
                    values["idf"],
                    1 if values["is_common"] else 0,
                )
                for term, values in sorted(term_stats.items())
            ],
        )
        morphology_form_rows = []
        seen_forms = set()
        for form, values in sorted(morphology_catalog.items()):
            for value in values:
                key = (form, value.canonical, value.family_id, value.kind)
                if key in seen_forms:
                    continue
                seen_forms.add(key)
                morphology_form_rows.append(
                    (
                        form,
                        value.canonical,
                        value.family_id,
                        value.family_label,
                        value.kind,
                        value.weight,
                        value.source,
                    )
                )
        con.executemany(
            """
            INSERT INTO morphology_forms(form, canonical, family_id, family_label, kind, weight, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            morphology_form_rows,
        )
        con.executemany(
            """
            INSERT INTO evidence_morphology(
                evidence_id, canonical, family_id, family_label, kind, form, occurrence_count, weight
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            evidence_morphology_rows,
        )
        con.executemany(
            """
            INSERT INTO morphology_stats(
                canonical, family_id, family_label, kind, evidence_count, occurrence_count, source_count, idf
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    canonical,
                    family_id,
                    values["family_label"],
                    kind,
                    values["evidence_count"],
                    values["occurrence_count"],
                    values["source_count"],
                    values["idf"],
                )
                for (canonical, family_id, kind), values in sorted(morphology_stats.items())
            ],
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    remove_sqlite_sidecars(index_path)
    os.replace(temp_path, index_path)

    index_manifest = {
        "dataset_version": DATASET_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "index_path": str(index_path),
        "semantic_index_schema_version": SEMANTIC_INDEX_SCHEMA_VERSION,
        "morphology_schema_version": morphology.MORPHOLOGY_SCHEMA_VERSION,
        "kb_dir": str(kb_dir),
        "kb_schema_version": manifest.get("schema_version"),
        "kb_builder_version": manifest.get("builder_version"),
        "kb_generated_at": manifest.get("generated_at"),
        "layer": layer,
        "evidence_count": len(evidence_rows),
        "term_count": len(term_stats),
        "morphology_form_count": sum(len(values) for values in morphology_catalog.values()),
        "morphology_match_count": len(evidence_morphology_rows),
        "author_period_schema_version": periods.AUTHOR_PERIOD_SCHEMA_VERSION,
        "author_period_count": len(author_periods_config.get("authors", [])),
        "author_periods_digest": periods.author_periods_digest(author_periods_config),
        "morphology_config_digest": morphology.morphology_digest(morphology_config),
        "policy": {
            "ai_models_used": False,
            "embeddings_used": False,
            "generated_theological_conclusions": False,
            "source_faithful_kb_modified": False,
        },
    }
    write_json(index_manifest_path, index_manifest)
    return index_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the deterministic semantic-search index outside the factual KB bundle."
    )
    parser.add_argument("--kb-dir", type=Path, default=DEFAULT_KB_DIR, help="Path to knowledge_base.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH, help="Output SQLite index path.")
    parser.add_argument(
        "--index-manifest",
        type=Path,
        default=DEFAULT_INDEX_MANIFEST_PATH,
        help="Output index manifest path.",
    )
    parser.add_argument(
        "--layer",
        choices=["primary", "extended", "archival", "all"],
        default="primary",
        help="Evidence layer to index. Default: primary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = build_semantic_index(
            kb_dir=args.kb_dir,
            index_path=args.index,
            index_manifest_path=args.index_manifest,
            layer=args.layer,
        )
    except SemanticSearchError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2
    print(
        "Built semantic index: "
        f"{args.index} ({manifest['evidence_count']} evidence rows, "
        f"{manifest['term_count']} indexed terms, layer={manifest['layer']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
