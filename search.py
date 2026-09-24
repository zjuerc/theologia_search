#!/usr/bin/env python3
"""Concept search over the deterministic semantic-search index."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import product
from pathlib import Path

try:
    from . import periods
    from .build_index import build_semantic_index
    from .common import (
        DEFAULT_INDEX_MANIFEST_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_KB_DIR,
        SemanticSearchError,
        author_matches,
        configure_output,
        display_text,
        grammatical_variants,
        make_fts_query,
        ngrams,
        norm_lookup,
        read_json,
        resolve_source_ids,
        section_matches,
        significant_tokens,
        token_list,
    )
except ImportError:  # pragma: no cover - supports direct script execution.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import periods
    from build_index import build_semantic_index
    from common import (
        DEFAULT_INDEX_MANIFEST_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_KB_DIR,
        SemanticSearchError,
        author_matches,
        configure_output,
        display_text,
        grammatical_variants,
        make_fts_query,
        ngrams,
        norm_lookup,
        read_json,
        resolve_source_ids,
        section_matches,
        significant_tokens,
        token_list,
    )


SNIPPET_RADIUS = 220
BROAD_TERMS = {
    "angels",
    "apostles",
    "baptism",
    "baptized",
    "being",
    "body",
    "church",
    "created",
    "creation",
    "faith",
    "father",
    "god",
    "jesus",
    "lord",
    "person",
    "persons",
    "relation",
    "relations",
    "resurrection",
    "spirit",
    "three",
    "virgin",
    "word",
}
LOW_SIGNAL_RAW_TERMS = {
    "above",
    "after",
    "against",
    "among",
    "around",
    "before",
    "below",
    "through",
    "under",
    "within",
    "without",
}
PROXIMITY_CHAR_WINDOW = 180
SCORE_VERSION = "2.1"

ADVANCED_FIELDS = ("concept", "author", "mentioned_author", "period_id", "book", "chapter")
ADVANCED_CONNECTOR_FIELDS = ("author", "mentioned_author", "period_id", "book", "chapter")
VALID_ADVANCED_CONNECTORS = {"AND", "OR"}


def configure_search_connection(con: sqlite3.Connection) -> sqlite3.Connection:
    """Tune a read-mostly search connection without changing search semantics."""
    con.execute("PRAGMA cache_size = -65536")
    con.execute("PRAGMA temp_store = MEMORY")
    con.execute("PRAGMA mmap_size = 268435456")
    return con


@dataclass
class QueryExpansion:
    concept: str
    direct_terms: list[str]
    expanded_terms: list[str]
    raw_query_terms: list[str]
    mechanical_variants: dict[str, list[str]]
    raw_phrases: list[str]
    variant_phrases: list[str]
    fts_terms: list[str]
    expansion_sources: dict[str, list[str]]
    morphology_terms: list[str]
    morphology_forms: dict[str, list[str]]
    morphology_families: dict[str, str]

    @property
    def all_terms(self) -> list[str]:
        terms = []
        seen = set()
        for term in self.direct_terms + self.expanded_terms:
            normalized = norm_lookup(term)
            if normalized and normalized not in seen:
                seen.add(normalized)
                terms.append(normalized)
        return terms

    @property
    def raw_search_terms(self) -> list[str]:
        terms: list[str] = []
        for term in self.raw_query_terms:
            ordered_add(terms, term)
            for variant in self.mechanical_variants.get(term, []):
                ordered_add(terms, variant)
        return terms

    @property
    def searchable_terms(self) -> list[str]:
        terms: list[str] = []
        for term in self.raw_phrases + self.variant_phrases + self.all_terms + self.raw_search_terms + self.morphology_terms:
            ordered_add(terms, term)
        return terms


@dataclass(frozen=True)
class AdvancedSearchCriteria:
    """User-entered advanced filters in their displayed evaluation order.

    Connectors are stored in the same order as the fields after concept:
    author, mentioned author, period, book, and chapter.  A connector is applied to the last
    populated field on its left, so empty fields do not change the expression.
    """

    concept: str = ""
    author: str = ""
    mentioned_author: str = ""
    period_id: str = ""
    book: str = ""
    chapter: str = ""
    connectors: tuple[str, ...] = ("AND", "AND", "AND", "AND", "AND")

    def connector_for(self, field: str) -> str:
        if field not in ADVANCED_CONNECTOR_FIELDS:
            raise ValueError(f"no connector is defined before {field}")
        return self.connectors[ADVANCED_CONNECTOR_FIELDS.index(field)]


def validate_advanced_criteria(criteria: AdvancedSearchCriteria) -> AdvancedSearchCriteria:
    if not isinstance(criteria, AdvancedSearchCriteria):
        raise SemanticSearchError("Advanced search criteria are invalid.")
    values = {
        "concept": display_text(criteria.concept),
        "author": display_text(criteria.author),
        "mentioned_author": display_text(criteria.mentioned_author),
        "period_id": display_text(criteria.period_id),
        "book": display_text(criteria.book),
        "chapter": display_text(criteria.chapter),
    }
    connectors = tuple(str(value).upper() for value in criteria.connectors)
    if len(connectors) == 4:
        connectors = (connectors[0], "AND", *connectors[1:])
    if len(connectors) != len(ADVANCED_CONNECTOR_FIELDS) or any(
        connector not in VALID_ADVANCED_CONNECTORS for connector in connectors
    ):
        raise SemanticSearchError("Advanced search connectors must be AND or OR.")
    valid_periods = {"", "all", *periods.ORDERED_PERIODS}
    if values["period_id"].casefold() == "all":
        values["period_id"] = ""
    if values["period_id"] not in valid_periods:
        raise SemanticSearchError(f"Unknown author time period: {values['period_id']}")
    if not any(values[field] for field in ADVANCED_FIELDS):
        raise SemanticSearchError("Enter at least one advanced-search field.")
    return AdvancedSearchCriteria(connectors=connectors, **values)


def _metadata_search_text(row: dict, field: str) -> str:
    if field == "author":
        return norm_lookup(row.get("author"))
    if field == "mentioned_author":
        return norm_lookup(row.get("mentioned_authors_text") or " ".join(row_mentioned_authors(row)))
    if field == "book":
        return norm_lookup(row.get("source_title"))
    if field == "chapter":
        return " ".join(
            value for value in (norm_lookup(row.get("heading")), norm_lookup(row.get("outline_path"))) if value
        )
    return ""


def row_mentioned_authors(row: dict) -> list[str]:
    value = row.get("mentioned_authors_json")
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            loaded = []
        if isinstance(loaded, list):
            return [display_text(item) for item in loaded if display_text(item)]
    value = row.get("mentioned_authors")
    if isinstance(value, list):
        return [display_text(item) for item in value if display_text(item)]
    value = row.get("mentioned_authors_text")
    if isinstance(value, str) and value:
        return [display_text(item) for item in value.split(" | ") if display_text(item)]
    return []


def mentioned_author_matches(row: dict, authors: list[str]) -> bool:
    if not authors:
        return True
    actual = {norm_lookup(author) for author in row_mentioned_authors(row)}
    return any(norm_lookup(author) in actual for author in authors)


def _metadata_token_matches(text: str, token: str) -> bool:
    if not text or not token:
        return False
    # Numeric chapter queries must match a complete token: 29 is not 129.
    if token.isdigit():
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text))
    return token in text


def advanced_metadata_matches(row: dict, criteria: AdvancedSearchCriteria) -> tuple[dict[str, bool], int]:
    """Return per-field metadata matches and exact full-field tie-break count."""
    matches: dict[str, bool] = {}
    exact_fields = 0
    for field in ("author", "mentioned_author", "book", "chapter"):
        value = getattr(criteria, field)
        if not value:
            continue
        query_tokens = token_list(value)
        text = _metadata_search_text(row, field)
        matches[field] = bool(query_tokens) and all(_metadata_token_matches(text, token) for token in query_tokens)
        if matches[field]:
            exact_candidates = [row.get("author"), row.get("source_title"), row.get("heading")]
            if field == "mentioned_author":
                exact_candidates = row_mentioned_authors(row)
            if any(norm_lookup(value) == norm_lookup(candidate) for candidate in exact_candidates):
                exact_fields += 1
    if criteria.period_id:
        matches["period_id"] = row.get("author_period_id") == criteria.period_id
        if matches["period_id"]:
            exact_fields += 1
    return matches, exact_fields


def metadata_candidate_ids(
    con: sqlite3.Connection,
    criteria: AdvancedSearchCriteria,
    *,
    period_filter_id: str | None = None,
) -> set[str]:
    """Use SQLite to narrow metadata candidates before Python verifies semantics."""
    candidates: set[str] = set()
    base_filters = []
    base_params: list[object] = []
    if period_filter_id:
        base_filters.append("author_period_id = ?")
        base_params.append(period_filter_id)

    def collect(where: str, params: list[object]) -> None:
        filters = [*base_filters, where] if where else list(base_filters)
        if not filters:
            return
        rows = con.execute(
            f"SELECT evidence_id FROM evidence WHERE {' AND '.join(filters)}",
            [*base_params, *params],
        )
        candidates.update(row[0] for row in rows)

    def collect_fts(field: str, tokens: list[str]) -> bool:
        normalized = [norm_lookup(token) for token in tokens]
        if not normalized or not all(re.fullmatch(r"[a-z0-9]+", token) for token in normalized):
            return False
        if field == "chapter":
            pieces = [
                f'(heading : "{token}" OR outline_path : "{token}")'
                for token in normalized
            ]
        else:
            pieces = [f'{field} : "{token}"' for token in normalized]
        filters = ["evidence_fts MATCH ?", *base_filters]
        rows = con.execute(
            f"""
            SELECT evidence_fts.evidence_id
            FROM evidence_fts
            JOIN evidence ON evidence.evidence_id = evidence_fts.evidence_id
            WHERE {' AND '.join(filters)}
            """,
            [" AND ".join(pieces), *base_params],
        )
        candidates.update(row[0] for row in rows)
        return True

    field_tokens = {
        "author": token_list(criteria.author),
        "book": token_list(criteria.book),
        "chapter": token_list(criteria.chapter),
    }
    for field, tokens in field_tokens.items():
        if not tokens:
            continue
        if collect_fts(
            {"author": "author", "book": "source_title", "chapter": "chapter"}[field],
            tokens,
        ):
            continue
        if field == "author":
            column = "author_norm"
        elif field == "book":
            column = "source_title_norm"
        else:
            clauses = ["(heading_norm LIKE ? OR outline_path_norm LIKE ?)"] * len(tokens)
            collect(" AND ".join(clauses), [value for token in tokens for value in (f"%{norm_lookup(token)}%", f"%{norm_lookup(token)}%")])
            continue
        collect(
            " AND ".join(f"{column} LIKE ?" for _ in tokens),
            [f"%{norm_lookup(token)}%" for token in tokens],
        )

    if criteria.mentioned_author:
        tokens = token_list(criteria.mentioned_author)
        normalized = norm_lookup(criteria.mentioned_author)
        if normalized:
            exact_rows = con.execute(
                f"SELECT evidence_id FROM evidence_mentioned_authors WHERE author_norm = ?"
                + (" AND evidence_id IN (SELECT evidence_id FROM evidence WHERE author_period_id = ?)" if period_filter_id else ""),
                [normalized, *([period_filter_id] if period_filter_id else [])],
            )
            candidates.update(row[0] for row in exact_rows)
        if tokens:
            collect(
                " AND ".join("mentioned_authors_norm LIKE ?" for _ in tokens),
                [f"%{norm_lookup(token)}%" for token in tokens],
            )

    if criteria.period_id:
        collect("author_period_id = ?", [criteria.period_id])
    return candidates


def evaluate_advanced_fields(
    criteria: AdvancedSearchCriteria,
    field_matches: dict[str, bool],
) -> bool:
    populated = [
        field
        for field in ADVANCED_FIELDS
        if getattr(criteria, field) and (field != "period_id" or criteria.period_id)
    ]
    if not populated:
        return False
    value = bool(field_matches.get(populated[0], False))
    for field in populated[1:]:
        matched = bool(field_matches.get(field, False))
        connector = criteria.connector_for(field)
        value = (value and matched) if connector == "AND" else (value or matched)
    return value


def ordered_add(items: list[str], item: str) -> None:
    normalized = norm_lookup(item)
    if normalized and normalized not in {norm_lookup(existing) for existing in items}:
        items.append(normalized)


@lru_cache(maxsize=4)
def load_lexicon(path: Path | None = None) -> dict:
    """Load an explicitly supplied lexicon, or return the empty default."""
    if path is None:
        return {"schema_version": "1.0.0", "entries": [], "aliases": []}
    return read_json(path)


def lexicon_entries(lexicon: dict | None) -> list[dict]:
    lexicon = lexicon or {}
    return list(lexicon.get("entries", [])) + list(lexicon.get("aliases", []))


def registered_terms(con: sqlite3.Connection) -> set[str]:
    return {row[0] for row in con.execute("SELECT term FROM term_stats")}


def term_stats(con: sqlite3.Connection) -> dict[str, dict]:
    return {
        row["term"]: {
            "evidence_count": row["evidence_count"],
            "occurrence_count": row["occurrence_count"],
            "source_count": row["source_count"],
            "idf": row["idf"],
            "is_common": bool(row["is_common"]),
        }
        for row in con.execute("SELECT * FROM term_stats")
    }


def extract_direct_terms(concept: str, registered: set[str]) -> list[str]:
    tokens = token_list(concept)
    direct: list[str] = []
    for phrase in ngrams(tokens, max_n=5):
        if phrase in registered:
            ordered_add(direct, phrase)
    for token in tokens:
        for variant in grammatical_variants(token):
            if variant in registered:
                ordered_add(direct, variant)
    return direct


def raw_query_terms(concept: str) -> list[str]:
    terms: list[str] = []
    for token in significant_tokens(concept):
        if token in LOW_SIGNAL_RAW_TERMS:
            continue
        ordered_add(terms, token)
    return terms


def mechanical_variants_for_token(token: str) -> list[str]:
    normalized = norm_lookup(token)
    if not normalized or normalized in LOW_SIGNAL_RAW_TERMS:
        return []
    return [variant for variant in grammatical_variants(normalized) if variant != normalized]


def mechanical_variants_for_terms(terms: list[str]) -> dict[str, list[str]]:
    return {term: mechanical_variants_for_token(term) for term in terms}


def query_phrases(concept: str) -> list[str]:
    tokens = token_list(concept)
    phrases: list[str] = []
    for size in range(min(5, len(tokens)), 1, -1):
        for index in range(0, len(tokens) - size + 1):
            phrase_tokens = tokens[index : index + size]
            if all(token in LOW_SIGNAL_RAW_TERMS for token in phrase_tokens):
                continue
            if not any(token not in LOW_SIGNAL_RAW_TERMS for token in phrase_tokens):
                continue
            ordered_add(phrases, " ".join(phrase_tokens))
    return phrases


def variant_query_phrases(phrases: list[str], variants_by_term: dict[str, list[str]]) -> list[str]:
    variant_phrases: list[str] = []
    for phrase in phrases:
        tokens = token_list(phrase)
        choices = []
        for token in tokens:
            token_choices = [token]
            token_choices.extend(variants_by_term.get(token, []))
            choices.append(token_choices[:4])
        for combination in product(*choices):
            variant = " ".join(combination)
            if variant != phrase:
                ordered_add(variant_phrases, variant)
            if len(variant_phrases) >= 80:
                return variant_phrases
    return variant_phrases


def query_has_trigger(concept_norm: str, direct_terms: list[str], triggers: list[str]) -> bool:
    direct = set(direct_terms)
    query_phrases = set(ngrams(token_list(concept_norm), max_n=5))
    for trigger in triggers:
        normalized = norm_lookup(trigger)
        if not normalized:
            continue
        if normalized in direct or normalized in query_phrases:
            return True
        if re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", concept_norm):
            return True
    return False


def cooccurring_terms(
    con: sqlite3.Connection,
    seed_terms: list[str],
    stats: dict[str, dict],
    max_terms: int = 12,
) -> list[str]:
    seeds = [term for term in seed_terms if term in stats and not stats[term]["is_common"]]
    if not seeds:
        return []
    placeholders = ", ".join("?" for _ in seeds)
    min_shared_seeds = min(2, len(seeds))
    rows = con.execute(
        f"""
        SELECT et2.term,
               SUM(et2.idf * et2.occurrence_count) AS score,
               COUNT(DISTINCT et1.term) AS shared_seed_terms
        FROM evidence_terms et1
        JOIN evidence_terms et2 ON et1.evidence_id = et2.evidence_id
        WHERE et1.term IN ({placeholders})
          AND et2.term NOT IN ({placeholders})
        GROUP BY et2.term
        HAVING shared_seed_terms >= ?
        ORDER BY score DESC, et2.term ASC
        LIMIT 80
        """,
        seeds + seeds + [min_shared_seeds],
    )
    results = []
    for row in rows:
        term = row[0]
        values = stats.get(term)
        if not values or values["is_common"] or term in BROAD_TERMS:
            continue
        if values["evidence_count"] > 3500 and " " not in term:
            continue
        results.append(term)
        if len(results) >= max_terms:
            break
    return results


def expand_query(
    con: sqlite3.Connection,
    concept: str,
    lexicon: dict | None = None,
    *,
    include_cooccurrence: bool = True,
    stats: dict[str, dict] | None = None,
) -> QueryExpansion:
    stats = stats if stats is not None else term_stats(con)
    registered = set(stats)
    concept_norm = norm_lookup(concept)
    direct = extract_direct_terms(concept, registered)
    raw_terms = raw_query_terms(concept)
    variants_by_term = mechanical_variants_for_terms(raw_terms)
    raw_phrases = query_phrases(concept)
    variant_phrases = variant_query_phrases(raw_phrases, variants_by_term)
    # Kept as empty compatibility fields. Mechanical variants are handled
    # centrally above and are not persisted as morphology data.
    morphology_terms: list[str] = []
    morphology_forms: dict[str, list[str]] = {}
    morphology_families: dict[str, str] = {}
    expanded: list[str] = []
    sources: dict[str, list[str]] = defaultdict(list)

    for entry in lexicon_entries(lexicon):
        triggers = entry.get("triggers") or [entry.get("trigger")]
        triggers = [trigger for trigger in triggers if trigger]
        if not query_has_trigger(concept_norm, direct, triggers):
            continue
        source_name = entry.get("concept_id") or f"alias:{entry.get('trigger')}"
        for term in entry.get("expanded_terms", []):
            normalized = norm_lookup(term)
            if not normalized:
                continue
            ordered_add(expanded, normalized)
            sources[normalized].append(source_name)

    if include_cooccurrence:
        seeds = []
        seed_source = direct if direct else expanded[:8]
        for term in seed_source:
            if term in registered:
                ordered_add(seeds, term)
        for term in cooccurring_terms(con, seeds, stats):
            ordered_add(expanded, term)
            sources[term].append("corpus_cooccurrence")

    fts_terms: list[str] = []
    for term in raw_phrases + variant_phrases + direct + expanded + morphology_terms:
        normalized = norm_lookup(term)
        values = stats.get(normalized)
        if values and values["is_common"] and " " not in normalized:
            continue
        if normalized in BROAD_TERMS:
            continue
        ordered_add(fts_terms, normalized)
    for term in raw_terms:
        values = stats.get(term)
        if not (values and values["is_common"] and term in direct):
            ordered_add(fts_terms, term)
        for variant in variants_by_term.get(term, []):
            variant_values = stats.get(variant)
            if variant not in BROAD_TERMS and not (variant_values and variant_values["is_common"]):
                ordered_add(fts_terms, variant)

    if not fts_terms:
        for token in raw_terms:
            ordered_add(fts_terms, token)

    return QueryExpansion(
        concept=concept,
        direct_terms=direct,
        expanded_terms=expanded,
        raw_query_terms=raw_terms,
        mechanical_variants=variants_by_term,
        raw_phrases=raw_phrases,
        variant_phrases=variant_phrases,
        fts_terms=fts_terms,
        expansion_sources={term: sorted(set(values)) for term, values in sources.items()},
        morphology_terms=morphology_terms,
        morphology_forms=morphology_forms,
        morphology_families=morphology_families,
    )


def load_metadata(con: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in con.execute("SELECT key, value FROM metadata")}


def load_sources_from_index(con: sqlite3.Connection) -> dict[str, dict]:
    return {
        row["source_id"]: {
            "source_id": row["source_id"],
            "display_title": row["display_title"],
            "pdf_file": row["pdf_file"],
            "collection": row["collection"],
        }
        for row in con.execute("SELECT * FROM sources")
    }


def requested_authors(args: argparse.Namespace) -> list[str]:
    authors = []
    if args.author:
        authors.extend(arg_values(args.author))
    if args.authors:
        authors.extend(arg_values(args.authors))
    seen = set()
    result = []
    for author in authors:
        key = norm_lookup(author)
        if key and key not in seen:
            seen.add(key)
            result.append(author)
    return result


def arg_values(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [item for item in value if item]


def requested_mentioned_authors(args: argparse.Namespace) -> list[str]:
    authors = []
    if getattr(args, "mentioned_author", None):
        authors.extend(arg_values(args.mentioned_author))
    if getattr(args, "mentioned_authors", None):
        authors.extend(arg_values(args.mentioned_authors))
    seen = set()
    result = []
    for author in authors:
        key = norm_lookup(author)
        if key and key not in seen:
            seen.add(key)
            result.append(author)
    return result


def candidate_filter_sql(
    *,
    source_ids: set[str] | None,
    authors: list[str],
    section: str | None,
    mentioned_authors: list[str] | None = None,
    mentioned_authors_exact: bool = False,
    period_ids: list[str] | None = None,
    scope_table: str | None = None,
) -> tuple[list[str], list[object]]:
    filters = []
    params: list[object] = []
    if source_ids:
        placeholders = ", ".join("?" for _ in source_ids)
        filters.append(f"e.source_id IN ({placeholders})")
        params.extend(sorted(source_ids))
    if authors:
        placeholders = ", ".join("?" for _ in authors)
        filters.append(f"e.author_norm IN ({placeholders})")
        params.extend(norm_lookup(author) for author in authors)
    if mentioned_authors:
        if mentioned_authors_exact:
            placeholders = ", ".join("?" for _ in mentioned_authors)
            filters.append(
                "e.evidence_id IN (SELECT evidence_id FROM evidence_mentioned_authors "
                f"WHERE author_norm IN ({placeholders}))"
            )
            params.extend(norm_lookup(author) for author in mentioned_authors)
        else:
            for author in mentioned_authors:
                filters.append("e.mentioned_authors_norm LIKE ?")
                params.append(f"%{norm_lookup(author)}%")
    if section:
        filters.append("(e.heading_norm LIKE ? OR e.outline_path_norm LIKE ?)")
        section_like = f"%{norm_lookup(section)}%"
        params.extend([section_like, section_like])
    if period_ids:
        placeholders = ", ".join("?" for _ in period_ids)
        filters.append(f"e.author_period_id IN ({placeholders})")
        params.extend(period_ids)
    if scope_table:
        filters.append(f"e.evidence_id IN (SELECT evidence_id FROM {scope_table})")
    return filters, params


def fetch_candidate_ids(
    con: sqlite3.Connection,
    expansion: QueryExpansion,
    *,
    source_ids: set[str] | None,
    authors: list[str],
    mentioned_authors: list[str] | None = None,
    mentioned_authors_exact: bool = False,
    section: str | None,
    candidate_limit: int,
    period_ids: list[str] | None = None,
    scope_table: str | None = None,
    stats: dict[str, dict] | None = None,
) -> list[tuple[str, float]]:
    stats = stats if stats is not None else term_stats(con)
    registered_query_terms = [
        term
        for term in expansion.all_terms
        if term in stats and (term in expansion.direct_terms or (term not in BROAD_TERMS and not stats[term]["is_common"]))
    ]
    seen_terms = set()
    registered_query_terms = [
        term for term in registered_query_terms if not (term in seen_terms or seen_terms.add(term))
    ]

    candidate_scores: dict[str, float] = {}
    candidate_bm25: dict[str, float] = {}
    filters, filter_params = candidate_filter_sql(
        source_ids=source_ids,
        authors=authors,
        mentioned_authors=mentioned_authors,
        mentioned_authors_exact=mentioned_authors_exact,
        section=section,
        period_ids=period_ids,
        scope_table=scope_table,
    )

    if registered_query_terms:
        term_placeholders = ", ".join("?" for _ in registered_query_terms)
        direct_terms = [term for term in expansion.direct_terms if term in registered_query_terms]
        if direct_terms:
            direct_placeholders = ", ".join("?" for _ in direct_terms)
            multiplier_sql = f"CASE WHEN et.term IN ({direct_placeholders}) THEN 3.0 ELSE 1.0 END"
            params: list[object] = direct_terms + registered_query_terms
        else:
            multiplier_sql = "1.0"
            params = list(registered_query_terms)
        where = [f"et.term IN ({term_placeholders})"] + filters
        params.extend(filter_params)
        params.append(candidate_limit)
        if len(period_ids or []) > 1:
            query = f"""
                SELECT evidence_id, term_rank
                FROM (
                    SELECT evidence_id, period_id, term_rank,
                           ROW_NUMBER() OVER (
                               PARTITION BY period_id
                               ORDER BY term_rank DESC, evidence_id ASC
                           ) AS period_row_number
                    FROM (
                        SELECT et.evidence_id,
                               e.author_period_id AS period_id,
                               SUM(et.idf * et.occurrence_count * {multiplier_sql}) AS term_rank
                        FROM evidence_terms et
                        JOIN evidence e ON e.evidence_id = et.evidence_id
                        WHERE {" AND ".join(where)}
                        GROUP BY et.evidence_id, e.author_period_id
                    )
                )
                WHERE period_row_number <= ?
            """
        else:
            query = f"""
                SELECT et.evidence_id,
                       SUM(et.idf * et.occurrence_count * {multiplier_sql}) AS term_rank
                FROM evidence_terms et
                JOIN evidence e ON e.evidence_id = et.evidence_id
                WHERE {" AND ".join(where)}
                GROUP BY et.evidence_id
                ORDER BY term_rank DESC, et.evidence_id ASC
                LIMIT ?
            """
        rows = con.execute(query, params)
        for row in rows:
            candidate_scores[row["evidence_id"]] = max(candidate_scores.get(row["evidence_id"], 0.0), float(row["term_rank"]))
            candidate_bm25.setdefault(row["evidence_id"], 0.0)

    fts_query = make_fts_query(expansion.fts_terms, max_terms=32)
    raw_terms_registered = all(term in stats for term in expansion.raw_query_terms)
    use_fts_pass = bool(fts_query) and (not registered_query_terms or not raw_terms_registered)
    if use_fts_pass:
        fts_limit = candidate_limit
        filters, filter_params = candidate_filter_sql(
            source_ids=source_ids,
            authors=authors,
            mentioned_authors=mentioned_authors,
            mentioned_authors_exact=mentioned_authors_exact,
            section=section,
            period_ids=period_ids,
            scope_table=scope_table,
        )
        where = ["evidence_fts MATCH ?"] + filters
        params = [fts_query] + filter_params + [fts_limit]
        if len(period_ids or []) > 1:
            query = f"""
                SELECT evidence_id, bm25_rank
                FROM (
                    SELECT evidence_id, period_id, bm25_rank,
                           ROW_NUMBER() OVER (
                               PARTITION BY period_id
                               ORDER BY bm25_rank ASC, evidence_id ASC
                           ) AS period_row_number
                    FROM (
                        SELECT evidence_fts.evidence_id AS evidence_id,
                               e.author_period_id AS period_id,
                               bm25(evidence_fts, 0.0, 0.0, 2.5, 1.0, 1.0, 5.0, 3.0, 1.0, 4.0, 1.0) AS bm25_rank
                        FROM evidence_fts
                        JOIN evidence e ON e.evidence_id = evidence_fts.evidence_id
                        WHERE {" AND ".join(where)}
                    )
                )
                WHERE period_row_number <= ?
            """
        else:
            query = f"""
                SELECT evidence_fts.evidence_id AS evidence_id,
                       bm25(evidence_fts, 0.0, 0.0, 2.5, 1.0, 1.0, 5.0, 3.0, 1.0, 4.0, 1.0) AS bm25_rank
                FROM evidence_fts
                JOIN evidence e ON e.evidence_id = evidence_fts.evidence_id
                WHERE {" AND ".join(where)}
                ORDER BY bm25_rank ASC
                LIMIT ?
            """
        rows = con.execute(query, params)
        for row in rows:
            evidence_id = row["evidence_id"]
            bm25_rank = float(row["bm25_rank"])
            fts_strength = max(0.0, -bm25_rank)
            candidate_scores[evidence_id] = max(candidate_scores.get(evidence_id, 0.0), fts_strength)
            candidate_bm25[evidence_id] = min(candidate_bm25.get(evidence_id, 0.0), bm25_rank)

    # The broad OR pass preserves recall. A separate AND pass protects
    # body-only evidence containing every literal query term from being
    # displaced by rows matching only one common word.
    if 2 <= len(expansion.raw_query_terms) <= 8:
        and_pieces = []
        for term in expansion.raw_query_terms:
            piece = make_fts_query([term], max_terms=1)
            if piece and piece not in and_pieces:
                and_pieces.append(piece)
        and_query = " AND ".join(and_pieces)
        if len(and_pieces) >= 2:
            filters, filter_params = candidate_filter_sql(
                source_ids=source_ids,
                authors=authors,
                mentioned_authors=mentioned_authors,
                mentioned_authors_exact=mentioned_authors_exact,
                section=section,
                period_ids=period_ids,
                scope_table=scope_table,
            )
            where = ["evidence_fts MATCH ?"] + filters
            params = [and_query] + filter_params + [candidate_limit]
            rows = con.execute(
                f"""
                SELECT evidence_fts.evidence_id AS evidence_id,
                       bm25(evidence_fts, 0.0, 0.0, 2.5, 1.0, 1.0, 5.0, 3.0, 1.0, 4.0, 1.0) AS bm25_rank
                FROM evidence_fts
                JOIN evidence e ON e.evidence_id = evidence_fts.evidence_id
                WHERE {" AND ".join(where)}
                ORDER BY bm25_rank ASC
                LIMIT ?
                """,
                params,
            )
            for row in rows:
                evidence_id = row["evidence_id"]
                bm25_rank = float(row["bm25_rank"])
                # Reserve room for candidates containing every literal term.
                candidate_scores[evidence_id] = max(
                    candidate_scores.get(evidence_id, 0.0),
                    100.0 + max(0.0, -bm25_rank),
                )
                candidate_bm25[evidence_id] = min(candidate_bm25.get(evidence_id, 0.0), bm25_rank)

    if not candidate_scores:
        fallback_query = make_fts_query(expansion.searchable_terms, max_terms=32)
        if not fallback_query:
            raise SemanticSearchError("concept query did not produce searchable terms")
        filters, filter_params = candidate_filter_sql(
            source_ids=source_ids,
            authors=authors,
            mentioned_authors=mentioned_authors,
            mentioned_authors_exact=mentioned_authors_exact,
            section=section,
            period_ids=period_ids,
            scope_table=scope_table,
        )
        where = ["evidence_fts MATCH ?"] + filters
        params = [fallback_query] + filter_params + [candidate_limit]
        rows = con.execute(
            f"""
            SELECT evidence_fts.evidence_id AS evidence_id,
                   bm25(evidence_fts, 0.0, 0.0, 2.5, 1.0, 1.0, 5.0, 3.0, 1.0, 4.0, 1.0) AS bm25_rank
            FROM evidence_fts
            JOIN evidence e ON e.evidence_id = evidence_fts.evidence_id
            WHERE {" AND ".join(where)}
            ORDER BY bm25_rank ASC
            LIMIT ?
            """,
            params,
        )
        return [(row["evidence_id"], float(row["bm25_rank"])) for row in rows]

    if len(period_ids or []) > 1:
        candidate_ids = list(candidate_scores)
        placeholders = ", ".join("?" for _ in candidate_ids)
        period_by_id = {
            row["evidence_id"]: row["author_period_id"]
            for row in con.execute(
                f"SELECT evidence_id, author_period_id FROM evidence WHERE evidence_id IN ({placeholders})",
                candidate_ids,
            )
        }
        grouped_candidates: dict[str | None, list[str]] = defaultdict(list)
        for evidence_id in candidate_ids:
            grouped_candidates[period_by_id.get(evidence_id)].append(evidence_id)
        selected_ids = []
        for period_id in period_ids:
            selected_ids.extend(
                sorted(
                    grouped_candidates.get(period_id, []),
                    key=lambda evidence_id: (-candidate_scores[evidence_id], evidence_id),
                )[: candidate_limit]
            )
        selected_ids.extend(
            sorted(
                grouped_candidates.get(None, []),
                key=lambda evidence_id: (-candidate_scores[evidence_id], evidence_id),
            )[: candidate_limit]
        )
        return [(evidence_id, candidate_bm25.get(evidence_id, 0.0)) for evidence_id in selected_ids]
    return [
        (evidence_id, candidate_bm25.get(evidence_id, 0.0))
        for evidence_id, _ in sorted(candidate_scores.items(), key=lambda item: (-item[1], item[0]))[: candidate_limit * 2]
    ]


def fetch_evidence(con: sqlite3.Connection, evidence_ids: list[str]) -> dict[str, dict]:
    if not evidence_ids:
        return {}
    placeholders = ", ".join("?" for _ in evidence_ids)
    columns = """
        evidence_id, source_id, retrieval_layer, page_number, page_start, page_end,
        author, mentioned_authors_json, source_title, source_collection, pdf_file,
        author_period_id, author_period_label, author_period_year,
        author_period_source, author_period_confidence, heading, outline_path,
        verbatim_text
    """
    return {
        row["evidence_id"]: dict(row)
        for row in con.execute(
            f"SELECT {columns} FROM evidence WHERE evidence_id IN ({placeholders})",
            evidence_ids,
        )
    }


def fetch_evidence_terms(con: sqlite3.Connection, evidence_ids: list[str]) -> dict[str, dict[str, dict]]:
    if not evidence_ids:
        return {}
    placeholders = ", ".join("?" for _ in evidence_ids)
    terms: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in con.execute(
        f"SELECT evidence_id, term, occurrence_count, idf FROM evidence_terms WHERE evidence_id IN ({placeholders})",
        evidence_ids,
    ):
        terms[row["evidence_id"]][row["term"]] = {
            "occurrence_count": row["occurrence_count"],
            "idf": row["idf"],
        }
    return terms


def compile_snippet_regex(terms: list[str]) -> re.Pattern | None:
    pieces = []
    for term in sorted({display_text(term) for term in terms if term}, key=len, reverse=True):
        escaped = re.escape(term)
        escaped = escaped.replace(r"\ ", r"[\s\-]+")
        pieces.append(escaped)
    if not pieces:
        return None
    return re.compile(r"(?i)(?<![A-Za-z0-9])(" + "|".join(pieces) + r")(?![A-Za-z0-9])")


def make_snippet(text: str, terms: list[str]) -> str:
    text = text.replace("\u0000", "").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    regex = compile_snippet_regex(terms)
    match = regex.search(text) if regex else None
    if match:
        start = max(0, match.start() - SNIPPET_RADIUS)
        end = min(len(text), match.end() + SNIPPET_RADIUS)
        snippet = text[start:end].strip()
        snippet = regex.sub(lambda found: f"[[{found.group(0)}]]", snippet, count=1)
    else:
        start = 0
        end = min(len(text), SNIPPET_RADIUS * 2)
        snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def make_evidence_snippet(heading: str, body: str, terms: list[str]) -> str:
    """Prefer body context, but expose a matching heading when body lacks it."""
    heading = heading or ""
    body = body or ""
    regex = compile_snippet_regex(terms)
    if regex and regex.search(heading) and not regex.search(body):
        return make_snippet(f"{heading}\n{body}", terms)
    return make_snippet(body or heading, terms)


@lru_cache(maxsize=4096)
def _phrase_regex(phrase: str) -> re.Pattern:
    pattern = re.escape(phrase)
    pattern = pattern.replace(r"\ ", r"[\s\-]+")
    return re.compile(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])")


def _text_contains_normalized(normalized_text: str, phrase: str) -> bool:
    if not normalized_text or not phrase:
        return False
    return bool(_phrase_regex(norm_lookup(phrase)).search(normalized_text))


def text_contains_phrase(text: str, phrase: str) -> bool:
    return _text_contains_normalized(norm_lookup(text), phrase)


def phrase_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    if not text or not phrase:
        return []
    return phrase_spans_normalized(norm_lookup(text), phrase)


def phrase_spans_normalized(normalized_text: str, phrase: str) -> list[tuple[int, int]]:
    if not normalized_text or not phrase:
        return []
    return [(match.start(), match.end()) for match in _phrase_regex(norm_lookup(phrase)).finditer(normalized_text)]


def raw_term_variants(expansion: QueryExpansion, raw_term: str) -> list[str]:
    variants: list[str] = []
    ordered_add(variants, raw_term)
    for variant in expansion.mechanical_variants.get(raw_term, []):
        ordered_add(variants, variant)
    return variants


def matched_raw_variants(
    expansion: QueryExpansion,
    heading_text: str,
    body_text: str,
) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}
    combined_text = norm_lookup(f"{heading_text} {body_text}")
    for raw_term in expansion.raw_query_terms:
        for variant in raw_term_variants(expansion, raw_term):
            if _text_contains_normalized(combined_text, variant):
                matches.setdefault(raw_term, [])
                ordered_add(matches[raw_term], variant)
    return matches


def raw_phrase_matches(
    expansion: QueryExpansion,
    heading_text: str,
    body_text: str,
) -> list[dict]:
    matches = []
    heading_text = norm_lookup(heading_text)
    body_text = norm_lookup(body_text)
    for phrase in expansion.raw_phrases + expansion.variant_phrases:
        if _text_contains_normalized(heading_text, phrase):
            matches.append({"phrase": phrase, "location": "heading"})
        if _text_contains_normalized(body_text, phrase):
            matches.append({"phrase": phrase, "location": "body"})
        if len(matches) >= 12:
            break
    return matches


def proximity_matches(
    expansion: QueryExpansion,
    matched_registered: list[str],
    heading_text: str,
    body_text: str,
) -> list[dict]:
    matches = []
    direct_registered = set(expansion.direct_terms)
    registered_terms = [term for term in matched_registered if term in direct_registered] or matched_registered
    normalized_texts = {
        "heading": norm_lookup(heading_text),
        "body": norm_lookup(body_text),
    }
    for location, text, window in (
        ("heading", normalized_texts["heading"], PROXIMITY_CHAR_WINDOW * 2),
        ("body", normalized_texts["body"], PROXIMITY_CHAR_WINDOW),
    ):
        for raw_term in expansion.raw_query_terms:
            raw_spans = []
            for variant in raw_term_variants(expansion, raw_term):
                raw_spans.extend((variant, span) for span in phrase_spans_normalized(text, variant))
            if not raw_spans:
                continue
            for registered in registered_terms:
                if registered == raw_term:
                    continue
                registered_spans = phrase_spans_normalized(text, registered)
                if not registered_spans:
                    continue
                best: tuple[str, int] | None = None
                for variant, raw_span in raw_spans:
                    for registered_span in registered_spans:
                        distance = max(
                            0,
                            max(raw_span[0], registered_span[0]) - min(raw_span[1], registered_span[1]),
                        )
                        if distance <= window and (best is None or distance < best[1]):
                            best = (variant, distance)
                if best is not None:
                    matches.append(
                        {
                            "raw_term": raw_term,
                            "raw_variant": best[0],
                            "registered_term": registered,
                            "location": location,
                            "distance": best[1],
                        }
                    )
                if len(matches) >= 12:
                    return matches
    return matches


def phrase_is_reportable(tokens: list[str], anchor_tokens: set[str]) -> bool:
    content_tokens = [
        token for token in tokens if token not in LOW_SIGNAL_RAW_TERMS and token not in {"and", "or", "the", "a", "an", "of", "to"}
    ]
    if len(content_tokens) < 2:
        return False
    return any(token in anchor_tokens for token in tokens)


def collect_discovered_phrases_from_text(
    text: str,
    anchor_tokens: set[str],
    *,
    weight: int,
    counter: Counter,
) -> None:
    tokens = token_list(text)
    if not tokens:
        return
    for index, token in enumerate(tokens):
        if token not in anchor_tokens:
            continue
        start_min = max(0, index - 3)
        end_max = min(len(tokens), index + 4)
        for start in range(start_min, index + 1):
            for end in range(index + 1, end_max + 1):
                if end - start < 2 or end - start > 5:
                    continue
                phrase_tokens = tokens[start:end]
                if phrase_is_reportable(phrase_tokens, anchor_tokens):
                    counter[" ".join(phrase_tokens)] += weight


def discovered_phrases_for_row(
    heading_text: str,
    body_text: str,
    expansion: QueryExpansion,
    matched_registered: list[str],
    raw_variant_matches: dict[str, list[str]],
) -> list[str]:
    anchor_tokens = set()
    for term in matched_registered:
        anchor_tokens.update(token_list(term))
    for variants in raw_variant_matches.values():
        for variant in variants:
            anchor_tokens.update(token_list(variant))
    if not anchor_tokens:
        return []
    counter: Counter = Counter()
    collect_discovered_phrases_from_text(heading_text, anchor_tokens, weight=3, counter=counter)
    collect_discovered_phrases_from_text(body_text, anchor_tokens, weight=1, counter=counter)
    exact_query = set(expansion.raw_phrases + expansion.variant_phrases + expansion.raw_search_terms + expansion.all_terms)
    phrases = []
    for phrase, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        if phrase in exact_query:
            continue
        phrases.append(phrase)
        if len(phrases) >= 8:
            break
    return phrases


def match_quality_and_reasons(
    *,
    matched_registered: list[str],
    raw_variant_matches: dict[str, list[str]],
    phrase_matches: list[dict],
    proximity: list[dict],
    matched_lemmas: list[str],
    matched_term_families: list[str],
    expansion: QueryExpansion,
) -> tuple[str, list[str]]:
    reasons = []
    important_raw_terms = [term for term in expansion.raw_query_terms if term not in set(expansion.direct_terms)]
    matched_raw_terms = sorted(raw_variant_matches)
    matched_important_raw = [term for term in important_raw_terms if term in raw_variant_matches]

    if any(match["location"] == "heading" for match in phrase_matches):
        reasons.append("matched exact query phrase in heading")
    elif phrase_matches:
        reasons.append("matched exact query phrase in body")

    if any(match["location"] == "heading" for match in proximity):
        reasons.append("raw query term near registered term in heading")
    elif proximity:
        reasons.append("raw query term near registered term in body")

    if matched_important_raw:
        reasons.append("matched non-registered query term: " + ", ".join(matched_important_raw[:4]))
    if len(matched_registered) >= 2:
        reasons.append("matched multiple registered terms")
    elif matched_registered:
        reasons.append("matched registered term: " + matched_registered[0])
    if matched_lemmas:
        reasons.append("matched lemma: " + ", ".join(matched_lemmas[:4]))
    if matched_term_families:
        reasons.append("matched term family: " + ", ".join(matched_term_families[:3]))

    missing_important = [term for term in important_raw_terms if term not in raw_variant_matches]
    if missing_important:
        reasons.append("missing non-registered query term: " + ", ".join(missing_important[:4]))

    if phrase_matches and any(match["location"] == "heading" for match in phrase_matches):
        return "strong", reasons
    if matched_important_raw and proximity and matched_registered:
        return "strong", reasons
    if matched_important_raw and matched_registered:
        return "moderate", reasons
    if matched_term_families and (matched_registered or matched_important_raw):
        return "moderate", reasons
    if len(matched_registered) >= 2 and (phrase_matches or proximity):
        return "moderate", reasons
    if len(matched_registered) <= 1 and not matched_important_raw:
        if not reasons:
            reasons.append("only matched broad registered term")
        return "weak", reasons
    return "moderate" if matched_raw_terms or matched_registered else "weak", reasons


def quality_assessment(
    *,
    expansion: QueryExpansion,
    heading_text: str,
    body_text: str,
    raw_variant_matches: dict[str, list[str]],
    phrase_matches: list[dict],
    proximity: list[dict],
    matched_registered: list[str],
    matched_lemmas: list[str],
    matched_term_families: list[str],
    normalized_heading_text: str | None = None,
    normalized_body_text: str | None = None,
) -> tuple[int, str, list[str]]:
    """Assess literal relevance separately from broad concept expansion."""
    raw_terms = expansion.raw_query_terms
    matched_raw_terms = set(raw_variant_matches)
    matched_count = len(matched_raw_terms)
    raw_count = len(raw_terms)
    coverage = matched_count / raw_count if raw_count else 0.0
    heading_raw_count = 0
    body_raw_count = 0
    normalized_heading_text = normalized_heading_text if normalized_heading_text is not None else norm_lookup(heading_text)
    normalized_body_text = normalized_body_text if normalized_body_text is not None else norm_lookup(body_text)
    for raw_term in raw_terms:
        variants = raw_term_variants(expansion, raw_term)
        if any(_text_contains_normalized(normalized_heading_text, variant) for variant in variants):
            heading_raw_count += 1
        if any(_text_contains_normalized(normalized_body_text, variant) for variant in variants):
            body_raw_count += 1

    full_query_phrase = " ".join(token_list(expansion.concept))
    has_full_heading_phrase = any(
        match["location"] == "heading" and norm_lookup(match.get("phrase")) == norm_lookup(full_query_phrase)
        for match in phrase_matches
    )
    has_full_body_phrase = any(
        match["location"] == "body" and norm_lookup(match.get("phrase")) == norm_lookup(full_query_phrase)
        for match in phrase_matches
    )
    has_body_phrase = any(match["location"] == "body" for match in phrase_matches)
    has_heading_proximity = any(match["location"] == "heading" for match in proximity)
    has_body_proximity = any(match["location"] == "body" for match in proximity)

    if coverage == 1.0 and (
        has_full_heading_phrase or (has_full_body_phrase and raw_count >= 2)
    ):
        grade, label = 5, "Excellent"
        basis = "complete literal phrase match in heading or body"
    elif coverage == 1.0 and raw_count == 1 and heading_raw_count == 1:
        grade, label = 4, "Strong"
        basis = "literal query term present in heading"
    elif coverage == 1.0 and (
        heading_raw_count == raw_count or has_heading_proximity or has_body_proximity
    ):
        grade, label = 4, "Strong"
        basis = "complete literal query match with structural or proximity support"
    elif coverage == 1.0 and body_raw_count:
        grade, label = 3, "Good"
        basis = "complete literal query terms found in body"
    elif coverage >= 0.5 and (body_raw_count or matched_registered):
        grade, label = 3, "Good"
        basis = "literal query terms found in the evidence"
    elif matched_lemmas or matched_term_families or matched_registered:
        grade, label = 2, "Related"
        basis = "related registered, lemma, or family terms found"
    else:
        grade, label = 1, "Weak"
        basis = "limited direct or related evidence"

    legacy_quality, reasons = match_quality_and_reasons(
        matched_registered=matched_registered,
        raw_variant_matches=raw_variant_matches,
        phrase_matches=phrase_matches,
        proximity=proximity,
        matched_lemmas=matched_lemmas,
        matched_term_families=matched_term_families,
        expansion=expansion,
    )
    del legacy_quality
    if raw_count:
        reasons.append(f"literal query coverage: {matched_count}/{raw_count}")
    reasons.append(f"quality basis: {basis}")
    return grade, label, reasons


def score_candidate(
    row: dict,
    bm25_rank: float,
    terms: dict[str, dict],
    expansion: QueryExpansion,
    stats: dict[str, dict],
) -> dict:
    query_terms = expansion.all_terms
    direct_terms = set(expansion.direct_terms)
    expanded_terms = set(expansion.expanded_terms)
    matched_registered = [term for term in query_terms if term in terms]
    matched_registered.sort(key=lambda term: (-terms[term]["idf"], term))

    term_score = 0.0
    score_breakdown = Counter()
    for term in matched_registered:
        values = terms[term]
        multiplier = 3.0 if term in direct_terms else 1.65 if term in expanded_terms else 1.0
        occurrence_factor = min(3.0, 1.0 + 0.35 * math.log1p(max(0, values["occurrence_count"])))
        contribution = values["idf"] * multiplier * occurrence_factor
        term_score += contribution
        if term in direct_terms:
            score_breakdown["direct_term"] += contribution
        else:
            score_breakdown["expanded_term"] += contribution

    expanded_term_raw = score_breakdown["expanded_term"]
    score_breakdown["expanded_term"] = min(24.0, expanded_term_raw * 0.35)

    # Source titles are useful metadata for retrieval, but they are not the
    # evidence heading. Keep them out of heading quality signals so a work
    # titled around a doctrine cannot make every chapter look like an exact
    # heading match.
    heading_text = " ".join([row.get("heading") or "", row.get("outline_path") or ""])
    body_text = row.get("verbatim_text") or ""
    normalized_heading_text = norm_lookup(heading_text)
    normalized_body_text = norm_lookup(body_text)
    raw_variant_matches = matched_raw_variants(expansion, heading_text, body_text)
    phrase_matches = raw_phrase_matches(expansion, heading_text, body_text)
    proximity = proximity_matches(expansion, matched_registered, heading_text, body_text)
    matched_lemmas: list[str] = []
    matched_term_families: list[str] = []

    heading_direct_bonus = 0.0
    heading_expanded_bonus = 0.0
    body_direct_bonus = 0.0
    body_expanded_bonus = 0.0
    for term in query_terms:
        idf = stats.get(term, {}).get("idf", 1.0)
        if _text_contains_normalized(normalized_heading_text, term):
            if term in direct_terms:
                heading_direct_bonus += min(8.0, idf * 1.6)
            else:
                heading_expanded_bonus += min(8.0, idf * 1.6)
        if _text_contains_normalized(normalized_body_text, term):
            if term in direct_terms:
                body_direct_bonus += min(4.0, idf * 0.45)
            else:
                body_expanded_bonus += min(4.0, idf * 0.45)
    score_breakdown["heading"] = heading_direct_bonus + min(8.0, heading_expanded_bonus * 0.35)
    score_breakdown["body_phrase"] = body_direct_bonus + min(8.0, body_expanded_bonus * 0.35)

    raw_bonus = 0.0
    for raw_term, variants in raw_variant_matches.items():
        multiplier = 0.35 if raw_term in direct_terms else 1.0
        for variant in variants:
            if _text_contains_normalized(normalized_heading_text, variant):
                raw_bonus += 9.0 * multiplier
            if _text_contains_normalized(normalized_body_text, variant):
                raw_bonus += 3.0 * multiplier
    score_breakdown["raw_query"] = raw_bonus

    raw_phrase_bonus = 0.0
    for match in phrase_matches:
        raw_phrase_bonus += 20.0 if match["location"] == "heading" else 9.0
    score_breakdown["raw_phrase"] = min(36.0, raw_phrase_bonus)

    proximity_bonus = 0.0
    for match in proximity:
        window = PROXIMITY_CHAR_WINDOW * 2 if match["location"] == "heading" else PROXIMITY_CHAR_WINDOW
        closeness = 1.0 - min(1.0, match["distance"] / max(1, window))
        proximity_bonus += (14.0 if match["location"] == "heading" else 8.0) * closeness
    score_breakdown["proximity"] = min(32.0, proximity_bonus)

    matched_morphology_forms: dict[str, list[str]] = {}
    score_breakdown["morphology"] = 0.0

    matched_direct_terms = [term for term in matched_registered if term in direct_terms]
    distinct = len(matched_direct_terms)
    cooccurrence_bonus = 0.0
    if distinct >= 2:
        cooccurrence_bonus = min(12.0, 1.5 * distinct + 0.15 * term_score)
    score_breakdown["cooccurrence"] = cooccurrence_bonus

    fts_bonus = max(0.0, -bm25_rank) * 0.15
    score_breakdown["fts"] = fts_bonus

    common_only_penalty = 0.0
    if matched_direct_terms and all(stats.get(term, {}).get("is_common") for term in matched_direct_terms):
        common_only_penalty = -5.0
    important_raw_terms = [term for term in expansion.raw_query_terms if term not in direct_terms]
    missing_important_raw = [term for term in important_raw_terms if term not in raw_variant_matches]
    if matched_registered and missing_important_raw and not phrase_matches and not proximity:
        common_only_penalty -= 6.0
    if len(matched_registered) == 1 and not any(term in raw_variant_matches for term in important_raw_terms):
        common_only_penalty -= 3.0
    score_breakdown["common_only_penalty"] = common_only_penalty

    raw_terms = expansion.raw_query_terms
    matched_raw_count = len(raw_variant_matches)
    raw_count = len(raw_terms)
    literal_coverage = matched_raw_count / raw_count if raw_count else 0.0

    # Normalize the heterogeneous retrieval signals into a bounded, query-independent
    # relevance score. Literal query coverage is primary; expansion remains secondary.
    score_breakdown = Counter(
        {
            "literal_coverage": 25.0 * literal_coverage,
            "direct_term": min(20.0, score_breakdown["direct_term"]),
            "expanded_term": min(8.0, expanded_term_raw * 0.10),
            "heading": min(8.0, heading_direct_bonus + heading_expanded_bonus * 0.15),
            "body_phrase": min(8.0, body_direct_bonus + body_expanded_bonus * 0.15),
            "raw_query": min(5.0, raw_bonus * 0.5),
            "raw_phrase": min(10.0, raw_phrase_bonus * 0.5),
            "proximity": min(8.0, proximity_bonus * 0.5),
            "morphology": 0.0,
            "cooccurrence": min(2.0, cooccurrence_bonus * (2.0 / 12.0)),
            "fts": min(1.0, fts_bonus * 0.1),
            "common_only_penalty": common_only_penalty,
        }
    )
    concept_score = max(0.0, min(100.0, sum(score_breakdown.values())))
    discovered_phrases = discovered_phrases_for_row(
        heading_text,
        body_text,
        expansion,
        matched_registered,
        raw_variant_matches,
    )
    legacy_quality, _legacy_reasons = match_quality_and_reasons(
        matched_registered=matched_registered,
        raw_variant_matches=raw_variant_matches,
        phrase_matches=phrase_matches,
        proximity=proximity,
        matched_lemmas=matched_lemmas,
        matched_term_families=matched_term_families,
        expansion=expansion,
    )
    quality_grade, quality_label, match_reasons = quality_assessment(
        expansion=expansion,
        heading_text=heading_text,
        body_text=body_text,
        raw_variant_matches=raw_variant_matches,
        phrase_matches=phrase_matches,
        proximity=proximity,
        matched_registered=matched_registered,
        matched_lemmas=matched_lemmas,
        matched_term_families=matched_term_families,
        normalized_heading_text=normalized_heading_text,
        normalized_body_text=normalized_body_text,
    )
    highlight_terms = []
    for match in phrase_matches:
        ordered_add(highlight_terms, match["phrase"])
    for variants in raw_variant_matches.values():
        for variant in variants:
            ordered_add(highlight_terms, variant)
    for term in matched_registered or query_terms:
        ordered_add(highlight_terms, term)
    return {
        "source_id": row.get("source_id"),
        "source_title": row.get("source_title"),
        "pdf_file": row.get("pdf_file"),
        "author": row.get("author"),
        "mentioned_authors": row_mentioned_authors(row),
        "source_collection": row.get("source_collection"),
        "author_period_id": row.get("author_period_id"),
        "author_period_label": row.get("author_period_label"),
        "author_period_year": row.get("author_period_year"),
        "author_period_source": row.get("author_period_source"),
        "author_period_confidence": row.get("author_period_confidence"),
        "page_number": row.get("page_number"),
        "evidence_id": row.get("evidence_id"),
        "heading": row.get("heading"),
        "outline_path": row.get("outline_path"),
        "retrieval_layer": row.get("retrieval_layer"),
        "concept_query": expansion.concept,
        "score_version": SCORE_VERSION,
        "concept_score": round(concept_score, 6),
        "score_breakdown": {key: round(value, 6) for key, value in sorted(score_breakdown.items())},
        "matched_query_terms": [
            term
            for term in query_terms
            if _text_contains_normalized(normalized_heading_text, term)
            or _text_contains_normalized(normalized_body_text, term)
        ],
        "direct_query_terms": sorted(direct_terms),
        "expanded_terms": expansion.expanded_terms,
        "raw_query_terms": expansion.raw_query_terms,
        "mechanical_variants": expansion.mechanical_variants,
        "matched_raw_terms": sorted(raw_variant_matches),
        "matched_mechanical_variants": raw_variant_matches,
        "morphology_terms": expansion.morphology_terms,
        "morphology_forms": expansion.morphology_forms,
        "morphology_families": expansion.morphology_families,
        "matched_lemmas": matched_lemmas,
        "matched_term_families": matched_term_families,
        "matched_morphology_forms": dict(matched_morphology_forms),
        "raw_phrase_matches": phrase_matches,
        "proximity_matches": proximity,
        "discovered_phrases": discovered_phrases,
        "match_quality": legacy_quality,
        "quality_grade": quality_grade,
        "quality_label": quality_label,
        "match_reasons": match_reasons,
        "matched_registered_terms": matched_registered,
        "matched_term_idf": {term: round(terms[term]["idf"], 6) for term in matched_registered},
        "cluster_id": "",
        "cluster_label": "",
        "snippet": make_evidence_snippet(
            heading_text,
            body_text,
            highlight_terms or matched_registered or query_terms,
        ),
    }


def query_terms_fully_covered(result: dict, expansion: QueryExpansion) -> bool:
    """Require every significant query term or a valid equivalent to match."""
    if len(expansion.raw_query_terms) <= 1:
        return True
    matched_raw = set(result.get("matched_raw_terms") or [])
    matched_variants = result.get("matched_mechanical_variants") or {}
    matched_lemmas = set(result.get("matched_lemmas") or [])
    for raw_term in expansion.raw_query_terms:
        if raw_term in matched_raw or matched_variants.get(raw_term):
            continue
        if raw_term not in matched_lemmas:
            return False
    return True


def query_has_unmatchable_term(
    con: sqlite3.Connection,
    expansion: QueryExpansion,
    stats: dict[str, dict],
) -> bool:
    """Detect a multi-word query containing a term absent from the corpus."""
    if len(expansion.raw_query_terms) <= 1:
        return False
    for raw_term in expansion.raw_query_terms:
        supported_terms = [raw_term]
        supported_terms.extend(expansion.mechanical_variants.get(raw_term, []))
        if any(term in stats for term in supported_terms):
            continue
        # A semantic lexicon entry may intentionally map a natural-language
        # phrase to registered concepts even when one surface word is absent
        # from the evidence vocabulary (for example, "relationship ...").
        if any(term in stats for term in expansion.expanded_terms):
            continue
        fts_query = make_fts_query(supported_terms, max_terms=16)
        if fts_query and con.execute(
            "SELECT 1 FROM evidence_fts WHERE evidence_fts MATCH ? LIMIT 1",
            (fts_query,),
        ).fetchone():
            continue
        return True
    return False


class DisjointSet:
    def __init__(self, size: int):
        self.parents = list(range(size))

    def find(self, item: int) -> int:
        parent = self.parents[item]
        if parent != item:
            self.parents[item] = self.find(parent)
        return self.parents[item]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parents[right_root] = left_root


def apply_clusters(results: list[dict]) -> None:
    if not results:
        return
    dsu = DisjointSet(len(results))
    term_sets = [set(row.get("matched_registered_terms") or []) for row in results]
    idf_maps = [row.get("matched_term_idf") or {} for row in results]

    for left in range(len(results)):
        for right in range(left + 1, len(results)):
            shared = term_sets[left] & term_sets[right]
            if not shared:
                continue
            shared_weight = sum(max(idf_maps[left].get(term, 0), idf_maps[right].get(term, 0)) for term in shared)
            if len(shared) >= 2 or shared_weight >= 4.0:
                dsu.union(left, right)

    grouped: dict[int, list[int]] = defaultdict(list)
    for index in range(len(results)):
        grouped[dsu.find(index)].append(index)

    ordered_groups = sorted(grouped.values(), key=lambda indexes: min(indexes))
    for cluster_number, indexes in enumerate(ordered_groups, 1):
        aggregate = Counter()
        for index in indexes:
            direct_terms = set(results[index].get("direct_query_terms") or [])
            for term, idf in (results[index].get("matched_term_idf") or {}).items():
                aggregate[term] += float(idf)
                if term in direct_terms:
                    aggregate[term] += float(idf) * 2.5
        label_terms = [term for term, _ in sorted(aggregate.items(), key=lambda item: (-item[1], item[0]))[:3]]
        label = " / ".join(label_terms) if label_terms else "unclustered"
        cluster_id = f"cluster_{cluster_number:02d}"
        for index in indexes:
            results[index]["cluster_id"] = cluster_id
            results[index]["cluster_label"] = label


def search_concept(
    con: sqlite3.Connection,
    concept: str,
    lexicon: dict | None = None,
    *,
    source_ids: set[str] | None = None,
    authors: list[str] | None = None,
    mentioned_authors: list[str] | None = None,
    mentioned_authors_exact: bool = False,
    section: str | None = None,
    period_ids: list[str] | None = None,
    limit: int = 20,
    candidate_limit: int = 100,
    include_cooccurrence: bool = False,
    cluster_results: bool = False,
    scope_table: str | None = None,
    stats: dict[str, dict] | None = None,
    expansion: QueryExpansion | None = None,
) -> tuple[list[dict], QueryExpansion]:
    authors = authors or []
    mentioned_authors = mentioned_authors or []
    stats = stats if stats is not None else term_stats(con)
    expansion = expansion or expand_query(
        con,
        concept,
        lexicon,
        include_cooccurrence=include_cooccurrence,
        stats=stats,
    )
    if query_has_unmatchable_term(con, expansion, stats):
        return [], expansion
    candidates = fetch_candidate_ids(
        con,
        expansion,
        source_ids=source_ids,
        authors=authors,
        mentioned_authors=mentioned_authors,
        mentioned_authors_exact=mentioned_authors_exact,
        section=section,
        period_ids=period_ids,
        candidate_limit=candidate_limit,
        scope_table=scope_table,
        stats=stats,
    )
    evidence_ids = [evidence_id for evidence_id, _ in candidates]
    evidence_by_id = fetch_evidence(con, evidence_ids)
    terms_by_id = fetch_evidence_terms(con, evidence_ids)
    results = []
    for evidence_id, bm25_rank in candidates:
        row = evidence_by_id.get(evidence_id)
        if not row:
            continue
        if source_ids is not None and row.get("source_id") not in source_ids:
            continue
        if not author_matches(row.get("author"), authors):
            continue
        if not mentioned_author_matches(row, mentioned_authors):
            continue
        if not section_matches(row, section):
            continue
        if period_ids and row.get("author_period_id") not in period_ids:
            continue
        result = score_candidate(
            row,
            bm25_rank,
            terms_by_id.get(evidence_id, {}),
            expansion,
            stats,
        )
        if result["concept_score"] <= 0:
            continue
        results.append(result)

    results.sort(
        key=lambda row: (
            not query_terms_fully_covered(row, expansion),
            -row["concept_score"],
            row.get("source_id") or "",
            row.get("page_number") or 0,
            row.get("evidence_id") or "",
        )
    )
    results = results[:limit]
    if cluster_results:
        apply_clusters(results)
    return results, expansion


def _advanced_reason(field: str, criteria: AdvancedSearchCriteria, row: dict) -> str:
    labels = {
        "author": "author",
        "mentioned_author": "mentioned author",
        "period_id": "period",
        "book": "book",
        "chapter": "chapter",
    }
    value = getattr(criteria, field)
    if field == "period_id":
        value = periods.PERIOD_LABELS.get(value, value)
    return f"matched {labels[field]}: {value}"


def _metadata_only_result(row: dict, criteria: AdvancedSearchCriteria, field_matches: dict[str, bool], exact_fields: int) -> dict:
    populated = [
        field for field in ADVANCED_FIELDS
        if getattr(criteria, field) and (field != "period_id" or criteria.period_id)
    ]
    matched_fields = [field for field in populated if field_matches.get(field)]
    metadata_score = 100.0 * len(matched_fields) / len(populated) if populated else 0.0
    if metadata_score >= 100:
        quality_grade, quality_label = 5, "Excellent"
    elif metadata_score >= 66.67:
        quality_grade, quality_label = 4, "Strong"
    elif metadata_score > 0:
        quality_grade, quality_label = 3, "Good"
    else:
        quality_grade, quality_label = 1, "Weak"
    reasons = [_advanced_reason(field, criteria, row) for field in matched_fields]
    return {
        "source_id": row.get("source_id"),
        "source_title": row.get("source_title"),
        "pdf_file": row.get("pdf_file"),
        "author": row.get("author"),
        "mentioned_authors": row_mentioned_authors(row),
        "source_collection": row.get("source_collection"),
        "author_period_id": row.get("author_period_id"),
        "author_period_label": row.get("author_period_label"),
        "author_period_year": row.get("author_period_year"),
        "author_period_source": row.get("author_period_source"),
        "author_period_confidence": row.get("author_period_confidence"),
        "page_number": row.get("page_number"),
        "page_start": row.get("page_start"),
        "page_end": row.get("page_end"),
        "evidence_id": row.get("evidence_id"),
        "heading": row.get("heading"),
        "outline_path": row.get("outline_path"),
        "verbatim_text": row.get("verbatim_text"),
        "retrieval_layer": "advanced_metadata",
        "concept_query": criteria.concept,
        "score_version": "metadata-1.0",
        "concept_score": round(metadata_score, 6),
        "score_breakdown": {"metadata_match": round(metadata_score, 6)},
        "advanced_query_mode": "metadata",
        "advanced_filter_matches": field_matches,
        "advanced_exact_field_matches": exact_fields,
        "advanced_filter_reasons": reasons,
        "matched_query_terms": [],
        "direct_query_terms": [],
        "expanded_terms": [],
        "raw_query_terms": [],
        "mechanical_variants": {},
        "matched_raw_terms": [],
        "matched_mechanical_variants": {},
        "morphology_terms": [],
        "morphology_forms": {},
        "morphology_families": {},
        "matched_lemmas": [],
        "matched_term_families": [],
        "matched_morphology_forms": {},
        "raw_phrase_matches": [],
        "proximity_matches": [],
        "discovered_phrases": [],
        "match_quality": quality_label.casefold(),
        "quality_grade": quality_grade,
        "quality_label": quality_label,
        "match_reasons": reasons,
        "matched_registered_terms": [],
        "matched_term_idf": {},
        "cluster_id": "",
        "cluster_label": "",
        "snippet": make_snippet(row.get("verbatim_text") or "", []),
    }


def search_advanced(
    con: sqlite3.Connection,
    criteria: AdvancedSearchCriteria,
    lexicon: dict | None = None,
    *,
    limit: int = 20,
    candidate_limit: int = 100,
    period_filter_id: str | None = None,
    metadata_per_period_limit: int | None = None,
    stats: dict[str, dict] | None = None,
    expansion: QueryExpansion | None = None,
) -> tuple[list[dict], QueryExpansion | None]:
    """Search concept and indexed metadata with deterministic boolean filters."""
    criteria = validate_advanced_criteria(criteria)
    metadata_populated = [
        field for field in ("author", "mentioned_author", "period_id", "book", "chapter")
        if getattr(criteria, field)
    ]

    # A concept-only advanced search is equivalent to the ordinary search and
    # should retain its bounded candidate behavior.
    if criteria.concept and not metadata_populated:
        stats = stats if stats is not None else term_stats(con)
        results, expansion = search_concept(
            con,
            criteria.concept,
            lexicon,
            period_ids=[period_filter_id] if period_filter_id else None,
            limit=limit,
            candidate_limit=candidate_limit,
            stats=stats,
            expansion=expansion,
        )
        for result in results:
            result["advanced_query_mode"] = "concept"
            result["advanced_filter_matches"] = {"concept": True}
            result["advanced_exact_field_matches"] = 0
            result["advanced_filter_reasons"] = []
        return results, expansion

    scope_table = "_advanced_scope"
    con.execute(f"DROP TABLE IF EXISTS temp.{scope_table}")
    con.execute(f"CREATE TEMP TABLE {scope_table} (evidence_id TEXT PRIMARY KEY)")
    scope_ids: list[str] = []
    match_cache: dict[str, tuple[dict[str, bool], int]] = {}
    metadata_scope_criteria = replace(criteria, concept="") if criteria.concept else criteria
    metadata_fields = [field for field in ADVANCED_CONNECTOR_FIELDS if getattr(metadata_scope_criteria, field)]
    metadata_requires_concept_scope = bool(metadata_fields) and all(
        criteria.connector_for(field) == "AND" for field in metadata_fields
    ) if criteria.concept else False
    exact_single_metadata = False
    if len(metadata_fields) == 1:
        field = metadata_fields[0]
        if field == "period_id":
            exact_single_metadata = True
        elif field == "author":
            exact_single_metadata = bool(
                con.execute(
                    "SELECT 1 FROM evidence WHERE author_norm = ? LIMIT 1",
                    (norm_lookup(metadata_scope_criteria.author),),
                ).fetchone()
            )
        elif field == "book":
            exact_single_metadata = bool(
                con.execute(
                    "SELECT 1 FROM evidence WHERE source_title_norm = ? LIMIT 1",
                    (norm_lookup(metadata_scope_criteria.book),),
                ).fetchone()
            )
        elif field == "mentioned_author":
            exact_single_metadata = bool(
                con.execute(
                    "SELECT 1 FROM evidence_mentioned_authors WHERE author_norm = ? LIMIT 1",
                    (norm_lookup(metadata_scope_criteria.mentioned_author),),
                ).fetchone()
            )
    direct_metadata_filter = bool(criteria.concept and metadata_requires_concept_scope and exact_single_metadata)
    metadata_ids = (
        set()
        if direct_metadata_filter
        else metadata_candidate_ids(con, metadata_scope_criteria, period_filter_id=period_filter_id)
    )
    if direct_metadata_filter:
        scope_ids = []
        match_cache = {}
        metadata_rows = ()
    elif exact_single_metadata:
        scope_ids = list(metadata_ids)
        matched = {metadata_fields[0]: True}
        match_cache = {evidence_id: (matched, 1) for evidence_id in scope_ids}
        metadata_rows = ()
    elif metadata_ids:
        placeholders = ", ".join("?" for _ in metadata_ids)
        metadata_rows = con.execute(
            f"""
            SELECT evidence_id, source_id, source_title, author, mentioned_authors_json,
                   mentioned_authors_text, author_period_id,
                   heading, outline_path, source_collection
            FROM evidence WHERE evidence_id IN ({placeholders})
            """,
            list(metadata_ids),
        )
    else:
        metadata_rows = ()
    for sqlite_row in metadata_rows:
        row = dict(sqlite_row)
        matches, exact_fields = advanced_metadata_matches(row, criteria)
        if evaluate_advanced_fields(metadata_scope_criteria, matches):
            evidence_id = row.get("evidence_id")
            if evidence_id:
                scope_ids.append(evidence_id)
                match_cache[evidence_id] = (matches, exact_fields)
    con.executemany(f"INSERT INTO {scope_table}(evidence_id) VALUES (?)", ((value,) for value in scope_ids))

    concept_results_by_id: dict[str, dict] = {}
    expansion = expansion
    if criteria.concept:
        stats = stats if stats is not None else term_stats(con)
        if not metadata_requires_concept_scope:
            concept_results, expansion = search_concept(
                con,
                criteria.concept,
                lexicon,
                period_ids=[period_filter_id] if period_filter_id else None,
                limit=max(limit, candidate_limit),
                candidate_limit=candidate_limit,
                stats=stats,
                expansion=expansion,
            )
            concept_results_by_id = {result["evidence_id"]: result for result in concept_results}
        if scope_ids or direct_metadata_filter:
            scoped_authors = []
            if metadata_requires_concept_scope and criteria.author:
                scoped_authors = [criteria.author]
            scoped_mentioned_authors = []
            if metadata_requires_concept_scope and criteria.mentioned_author:
                scoped_mentioned_authors = [criteria.mentioned_author]
            scoped_results, scoped_expansion = search_concept(
                con,
                criteria.concept,
                lexicon,
                authors=scoped_authors,
                mentioned_authors=scoped_mentioned_authors,
                mentioned_authors_exact=bool(scoped_mentioned_authors and direct_metadata_filter),
                period_ids=[period_filter_id] if period_filter_id else None,
                candidate_limit=candidate_limit,
                limit=candidate_limit,
                scope_table=None if direct_metadata_filter else scope_table,
                stats=stats,
                expansion=expansion,
            )
            expansion = expansion or scoped_expansion
            for result in scoped_results:
                concept_results_by_id[result["evidence_id"]] = result

    # The boolean expression includes concept itself.  Evaluate it after the
    # concept pass so OR expressions can retain metadata-only rows as well.
    candidate_ids = set(scope_ids) | set(concept_results_by_id)
    missing_metadata_ids = candidate_ids - set(match_cache)
    if missing_metadata_ids:
        placeholders = ", ".join("?" for _ in missing_metadata_ids)
        for sqlite_row in con.execute(
            f"""
            SELECT evidence_id, source_id, source_title, author, mentioned_authors_json,
                   mentioned_authors_text, author_period_id,
                   heading, outline_path, source_collection
            FROM evidence WHERE evidence_id IN ({placeholders})
            """,
            list(missing_metadata_ids),
        ):
            row = dict(sqlite_row)
            match_cache[row["evidence_id"]] = advanced_metadata_matches(row, criteria)
    final_scope_ids: list[str] = []
    for evidence_id in candidate_ids:
        matches, exact_fields = match_cache[evidence_id]
        matches = dict(matches)
        if criteria.concept:
            matches["concept"] = evidence_id in concept_results_by_id
        if evaluate_advanced_fields(criteria, matches):
            final_scope_ids.append(evidence_id)
            match_cache[evidence_id] = (matches, exact_fields)
        else:
            match_cache.pop(evidence_id, None)
    con.execute(f"DELETE FROM {scope_table}")
    con.executemany(f"INSERT INTO {scope_table}(evidence_id) VALUES (?)", ((value,) for value in final_scope_ids))

    if criteria.concept:
        rows_by_id = {
            row["evidence_id"]: dict(row)
            for row in con.execute(f"SELECT e.* FROM evidence e JOIN {scope_table} s ON s.evidence_id = e.evidence_id")
        }
        results = []
        for evidence_id, row in rows_by_id.items():
            matches, exact_fields = match_cache[evidence_id]
            result = concept_results_by_id.get(evidence_id)
            if result is None:
                # An OR expression can intentionally include a row matched
                # only by metadata.  Keep it visible but rank it after rows
                # carrying the normal concept score.
                result = _metadata_only_result(row, criteria, matches, exact_fields)
                metadata_score = result["concept_score"]
                result["concept_score"] = 0.0
                result["score_breakdown"] = {"concept_match": 0.0, "metadata_match": metadata_score}
            result["advanced_query_mode"] = "concept"
            result["advanced_filter_matches"] = matches
            result["advanced_exact_field_matches"] = exact_fields
            result["advanced_filter_reasons"] = [
                _advanced_reason(field, criteria, result)
                for field, matched in matches.items()
                if matched and field != "concept"
            ]
            result["match_reasons"] = list(result.get("match_reasons") or []) + result["advanced_filter_reasons"]
            result["advanced_concept_match"] = bool(matches.get("concept"))
            results.append(result)
        results.sort(
            key=lambda row: (
                -int(bool(row.get("advanced_concept_match"))),
                -float(row.get("concept_score") or 0),
                -int(row.get("advanced_exact_field_matches") or 0),
                row.get("source_id") or "",
                row.get("page_number") or 0,
                row.get("evidence_id") or "",
            )
        )
        return results[:limit], expansion

    rows = [
        dict(row) for row in (
            con.execute(
                f"""
                SELECT * FROM (
                    SELECT e.*, ROW_NUMBER() OVER (
                        PARTITION BY e.author_period_id
                        ORDER BY e.source_id, e.page_number, e.evidence_id
                    ) AS period_row_number
                    FROM evidence e JOIN {scope_table} s ON s.evidence_id = e.evidence_id
                ) WHERE period_row_number <= ?
                """,
                (metadata_per_period_limit,),
            )
            if metadata_per_period_limit
            else con.execute(f"SELECT e.* FROM evidence e JOIN {scope_table} s ON s.evidence_id = e.evidence_id")
        )
    ]
    results = []
    for row in rows:
        matches, exact_fields = match_cache[row["evidence_id"]]
        results.append(_metadata_only_result(row, criteria, matches, exact_fields))
    results.sort(
        key=lambda row: (
            -float(row.get("concept_score") or 0),
            -int(row.get("advanced_exact_field_matches") or 0),
            row.get("source_id") or "",
            row.get("page_number") or 0,
            row.get("evidence_id") or "",
        )
    )
    return results[:limit], None


def search_advanced_by_period(
    con: sqlite3.Connection,
    criteria: AdvancedSearchCriteria,
    lexicon: dict | None = None,
    *,
    limit: int = 20,
    candidate_limit: int = 100,
    include_unclassified: bool = True,
) -> tuple[list[dict], QueryExpansion | None]:
    criteria = validate_advanced_criteria(criteria)
    period_ids = periods.ORDERED_PERIODS if include_unclassified else periods.ORDERED_PERIODS[:-1]
    per_period_candidates = max(candidate_limit, limit * 4)
    scoped_period_ids = [criteria.period_id] if criteria.period_id else period_ids
    stats = term_stats(con) if criteria.concept else None
    expansion = None
    grouped = defaultdict(list)
    for period_id in scoped_period_ids:
        period_results, period_expansion = search_advanced(
            con,
            criteria,
            lexicon,
            limit=per_period_candidates,
            candidate_limit=per_period_candidates,
            period_filter_id=period_id,
            metadata_per_period_limit=limit if not criteria.concept else None,
            stats=stats,
            expansion=expansion,
        )
        expansion = expansion or period_expansion
        grouped[period_id].extend(period_results)
    groups = []
    for period_id in period_ids:
        period_results = grouped.get(period_id, [])[:limit]
        if period_results or period_id != periods.UNCLASSIFIED:
            groups.append(
                {
                    "period_id": period_id,
                    "period_label": periods.PERIOD_LABELS[period_id],
                    "results": period_results,
                }
            )
    return groups, expansion


def search_concept_by_period(
    con: sqlite3.Connection,
    concept: str,
    lexicon: dict | None = None,
    *,
    source_ids: set[str] | None = None,
    authors: list[str] | None = None,
    mentioned_authors: list[str] | None = None,
    section: str | None = None,
    limit: int = 20,
    candidate_limit: int = 100,
    include_cooccurrence: bool = False,
    cluster_results: bool = False,
    include_unclassified: bool = True,
) -> tuple[list[dict], QueryExpansion]:
    period_ids = periods.ORDERED_PERIODS if include_unclassified else periods.ORDERED_PERIODS[:-1]
    per_period_candidates = max(candidate_limit, limit * 4)
    stats = term_stats(con)
    expansion = expand_query(
        con,
        concept,
        lexicon,
        include_cooccurrence=include_cooccurrence,
        stats=stats,
    )
    results, _ = search_concept(
        con,
        concept,
        lexicon,
        source_ids=source_ids,
        authors=authors,
        mentioned_authors=mentioned_authors,
        section=section,
        period_ids=period_ids,
        limit=per_period_candidates * len(period_ids),
        candidate_limit=per_period_candidates,
        include_cooccurrence=include_cooccurrence,
        cluster_results=cluster_results,
        stats=stats,
        expansion=expansion,
    )
    grouped = defaultdict(list)
    for result in results:
        grouped[result.get("author_period_id") or periods.UNCLASSIFIED].append(result)
    groups = []
    for period_id in period_ids:
        period_results = grouped.get(period_id, [])[:limit]
        if period_results or period_id != periods.UNCLASSIFIED:
            groups.append(
                {
                    "period_id": period_id,
                    "period_label": periods.PERIOD_LABELS[period_id],
                    "results": period_results,
                }
            )
    return groups, expansion


def print_expansion(expansion: QueryExpansion) -> None:
    print("Expansion:")
    print(f"  direct_terms: {', '.join(expansion.direct_terms) or '(none)'}")
    print(f"  expanded_terms: {', '.join(expansion.expanded_terms) or '(none)'}")
    print(f"  fts_terms: {', '.join(expansion.fts_terms) or '(none)'}")


def print_query_plan(expansion: QueryExpansion) -> None:
    print("Query plan:")
    print(f"  raw_query_terms: {', '.join(expansion.raw_query_terms) or '(none)'}")
    if expansion.mechanical_variants:
        variant_bits = [
            f"{term}: {', '.join(variants) or '(none)'}"
            for term, variants in expansion.mechanical_variants.items()
        ]
        print(f"  mechanical_variants: {'; '.join(variant_bits)}")
    print(f"  raw_phrases: {', '.join(expansion.raw_phrases) or '(none)'}")
    print(f"  variant_phrases: {', '.join(expansion.variant_phrases[:16]) or '(none)'}")
    if len(expansion.variant_phrases) > 16:
        print(f"  variant_phrases_more: {len(expansion.variant_phrases) - 16}")
    print(f"  direct_terms: {', '.join(expansion.direct_terms) or '(none)'}")
    print(f"  expanded_terms: {', '.join(expansion.expanded_terms) or '(none)'}")
    print(f"  fts_terms: {', '.join(expansion.fts_terms) or '(none)'}")


def aggregate_discovered_phrases(results: list[dict], limit: int = 12) -> list[str]:
    counter: Counter = Counter()
    for row in results:
        for phrase in row.get("discovered_phrases") or []:
            counter[phrase] += 1
    return [phrase for phrase, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def print_discovered_phrases(results: list[dict]) -> None:
    phrases = aggregate_discovered_phrases(results)
    print("Discovered phrases:")
    if not phrases:
        print("  (none)")
        return
    for phrase in phrases:
        print(f"  {phrase}")


def print_jsonl(
    results: list[dict],
    expansion: QueryExpansion,
    *,
    show_expansion: bool,
    show_query_plan: bool,
    show_discovered_phrases: bool,
) -> None:
    if show_expansion:
        print(
            json.dumps(
                {
                    "type": "expansion",
                    "concept": expansion.concept,
                    "direct_terms": expansion.direct_terms,
                    "expanded_terms": expansion.expanded_terms,
                    "raw_query_terms": expansion.raw_query_terms,
                    "mechanical_variants": expansion.mechanical_variants,
                    "morphology_terms": expansion.morphology_terms,
                    "morphology_forms": expansion.morphology_forms,
                    "morphology_families": expansion.morphology_families,
                    "raw_phrases": expansion.raw_phrases,
                    "variant_phrases": expansion.variant_phrases,
                    "fts_terms": expansion.fts_terms,
                    "expansion_sources": expansion.expansion_sources,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    if show_query_plan:
        print(
            json.dumps(
                {
                    "type": "query_plan",
                    "concept": expansion.concept,
                    "raw_query_terms": expansion.raw_query_terms,
                    "mechanical_variants": expansion.mechanical_variants,
                    "morphology_terms": expansion.morphology_terms,
                    "morphology_forms": expansion.morphology_forms,
                    "morphology_families": expansion.morphology_families,
                    "raw_phrases": expansion.raw_phrases,
                    "variant_phrases": expansion.variant_phrases,
                    "direct_terms": expansion.direct_terms,
                    "expanded_terms": expansion.expanded_terms,
                    "fts_terms": expansion.fts_terms,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    if show_discovered_phrases:
        print(
            json.dumps(
                {
                    "type": "discovered_phrases",
                    "concept": expansion.concept,
                    "phrases": aggregate_discovered_phrases(results),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    for row in results:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))


def print_period_jsonl(
    groups: list[dict],
    expansion: QueryExpansion,
    *,
    show_expansion: bool,
    show_query_plan: bool,
    show_discovered_phrases: bool,
) -> None:
    if show_expansion or show_query_plan:
        print_jsonl(
            [],
            expansion,
            show_expansion=show_expansion,
            show_query_plan=show_query_plan,
            show_discovered_phrases=False,
        )
    if show_discovered_phrases:
        all_results = [row for group in groups for row in group["results"]]
        print(
            json.dumps(
                {
                    "type": "discovered_phrases",
                    "concept": expansion.concept,
                    "phrases": aggregate_discovered_phrases(all_results),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    for group in groups:
        print(
            json.dumps(
                {
                    "type": "period_group",
                    "period_id": group["period_id"],
                    "period_label": group["period_label"],
                    "result_count": len(group["results"]),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        for row in group["results"]:
            output = dict(row)
            output["period_group_id"] = group["period_id"]
            output["period_group_label"] = group["period_label"]
            print(json.dumps(output, ensure_ascii=False, sort_keys=True))


def print_readable_row(index: int, row: dict, args: argparse.Namespace) -> None:
    print()
    author = row.get("author") or "Unknown"
    page = row.get("page_number")
    score = row.get("concept_score")
    quality = row.get("quality_label") or row.get("match_quality") or "unknown"
    print(f"{index}. {row.get('source_id')} p.{page} | {author} | {row.get('evidence_id')} | score: {score} | quality: {quality}")
    if row.get("source_title"):
        print(f"   {row['source_title']}")
    if row.get("author_period_label"):
        print(f"   Period: {row['author_period_label']}")
    if row.get("mentioned_authors"):
        print(f"   Mentioned authors: {', '.join(row['mentioned_authors'])}")
    if row.get("heading"):
        print(f"   Heading: {row['heading']}")
    elif row.get("outline_path"):
        print(f"   Path: {row['outline_path']}")
    if row.get("cluster_id"):
        print(f"   Cluster: {row['cluster_id']} ({row['cluster_label']})")
    if row.get("matched_registered_terms"):
        print(f"   Terms: {', '.join(row['matched_registered_terms'][:12])}")
    if row.get("matched_raw_terms"):
        print(f"   Raw: {', '.join(row['matched_raw_terms'][:12])}")
    if row.get("matched_lemmas"):
        print(f"   Lemmas: {', '.join(row['matched_lemmas'][:12])}")
    if row.get("matched_term_families"):
        print(f"   Term families: {', '.join(row['matched_term_families'][:8])}")
    if args.show_query_plan and row.get("match_reasons"):
        print(f"   Reasons: {'; '.join(row['match_reasons'][:4])}")
    if args.show_discovered_phrases and row.get("discovered_phrases"):
        print(f"   Discovered: {', '.join(row['discovered_phrases'][:6])}")
    if not args.no_snippet and row.get("snippet"):
        wrapped = textwrap.fill(row["snippet"], width=100, subsequent_indent="   ")
        print(f"   {wrapped}")


def print_readable(results: list[dict], expansion: QueryExpansion, args: argparse.Namespace) -> None:
    print(f'Query: concept="{args.concept}", layer={args.layer}')
    print(f"Matches: {len(results)}; displaying: {len(results)}")
    if args.show_expansion:
        print_expansion(expansion)
    if args.show_query_plan:
        print_query_plan(expansion)
    if args.show_discovered_phrases:
        print_discovered_phrases(results)
    for index, row in enumerate(results, 1):
        print_readable_row(index, row, args)


def print_period_sections(groups: list[dict], expansion: QueryExpansion, args: argparse.Namespace) -> None:
    total = sum(len(group["results"]) for group in groups)
    print(f'Query: concept="{args.concept}", layer={args.layer}')
    print(f"Matches: {total}; displaying up to {args.limit} per historical section")
    if args.show_expansion:
        print_expansion(expansion)
    if args.show_query_plan:
        print_query_plan(expansion)
    if args.show_discovered_phrases:
        all_results = [row for group in groups for row in group["results"]]
        print_discovered_phrases(all_results)
    for group in groups:
        print()
        print(f"== {group['period_label']} ==")
        if not group["results"]:
            print("   No results.")
            continue
        for index, row in enumerate(group["results"], 1):
            print_readable_row(index, row, args)


def ensure_index(args: argparse.Namespace) -> None:
    if args.rebuild_index:
        build_semantic_index(
            kb_dir=args.kb_dir,
            index_path=args.index,
            index_manifest_path=args.index_manifest,
            layer=args.layer,
        )
        return
    if not args.index.exists():
        raise SemanticSearchError(
            f"missing semantic index: {args.index}. Run theologia_search/build_index.py first, "
            "or pass --rebuild-index."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic concept search over the local KB.")
    parser.add_argument("--concept", nargs="+", required=True, help="Concept query text.")
    parser.add_argument("--kb-dir", type=Path, default=DEFAULT_KB_DIR, help="Path to knowledge_base.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH, help="SQLite semantic index path.")
    parser.add_argument(
        "--index-manifest",
        type=Path,
        default=DEFAULT_INDEX_MANIFEST_PATH,
        help="Generated index manifest path.",
    )
    parser.add_argument("--lexicon", type=Path, default=None, help="Optional external lexicon path.")
    parser.add_argument(
        "--layer",
        choices=["primary", "extended", "archival", "all"],
        default="primary",
        help="Expected indexed evidence layer. Default: primary.",
    )
    parser.add_argument("--source", nargs="+", help="Source id, title, PDF path, or unique substring.")
    parser.add_argument("--author", nargs="+", help='Evidence author filter, e.g. "Augustine of Hippo".')
    parser.add_argument("--authors", nargs="+", help="Multiple exact evidence author filters.")
    parser.add_argument("--mentioned-author", nargs="+", help='Mentioned/discussed author filter, e.g. "Origen".')
    parser.add_argument("--mentioned-authors", nargs="+", help="Multiple exact mentioned/discussed author filters.")
    parser.add_argument("--section", nargs="+", help="Heading or outline-path substring filter.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum displayed results. Default: 20.")
    parser.add_argument("--candidate-limit", type=int, default=100, help="Internal candidate pool size. Default: 100.")
    parser.add_argument("--cluster-results", action="store_true", help="Cluster returned evidence chunks.")
    parser.add_argument(
        "--period-sections",
        action="store_true",
        help="Return up to --limit results for each historical section.",
    )
    parser.add_argument("--show-expansion", action="store_true", help="Show deterministic query expansion.")
    parser.add_argument("--show-query-plan", action="store_true", help="Show raw terms, mechanical variants, phrases, and FTS terms.")
    parser.add_argument("--show-discovered-phrases", action="store_true", help="Show corpus phrases discovered in returned results.")
    parser.add_argument(
        "--cooccurrence-expansion",
        action="store_true",
        help="Add corpus-derived co-occurring terms to the query expansion.",
    )
    parser.add_argument(
        "--no-cooccurrence-expansion",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild the semantic index before searching.")
    parser.add_argument("--jsonl", action="store_true", help="Emit machine-readable JSON Lines.")
    parser.add_argument("--no-snippet", action="store_true", help="Omit snippets from readable output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    args.concept = " ".join(args.concept)
    for name in ("source", "author", "mentioned_author", "section"):
        value = getattr(args, name)
        if isinstance(value, list):
            setattr(args, name, " ".join(value))
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.candidate_limit < args.limit:
        parser.error("--candidate-limit must be greater than or equal to --limit")

    try:
        ensure_index(args)
        lexicon = load_lexicon(args.lexicon)
        con = sqlite3.connect(str(args.index))
        configure_search_connection(con)
        con.row_factory = sqlite3.Row
        try:
            metadata = load_metadata(con)
            indexed_layer = metadata.get("layer")
            if indexed_layer != args.layer:
                raise SemanticSearchError(
                    f"index layer is {indexed_layer!r}, but --layer is {args.layer!r}; rebuild the index for this layer"
                )
            sources = load_sources_from_index(con)
            source_ids = resolve_source_ids(args.source, sources)
            if args.period_sections:
                results, expansion = search_concept_by_period(
                    con,
                    args.concept,
                    lexicon,
                    source_ids=source_ids,
                    authors=requested_authors(args),
                    mentioned_authors=requested_mentioned_authors(args),
                    section=args.section,
                    limit=args.limit,
                    candidate_limit=args.candidate_limit,
                    include_cooccurrence=args.cooccurrence_expansion and not args.no_cooccurrence_expansion,
                    cluster_results=args.cluster_results,
                )
            else:
                results, expansion = search_concept(
                    con,
                    args.concept,
                    lexicon,
                    source_ids=source_ids,
                    authors=requested_authors(args),
                    mentioned_authors=requested_mentioned_authors(args),
                    section=args.section,
                    limit=args.limit,
                    candidate_limit=args.candidate_limit,
                    include_cooccurrence=args.cooccurrence_expansion and not args.no_cooccurrence_expansion,
                    cluster_results=args.cluster_results,
                )
        finally:
            con.close()
    except SemanticSearchError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2

    if args.jsonl:
        if args.period_sections:
            print_period_jsonl(
                results,
                expansion,
                show_expansion=args.show_expansion,
                show_query_plan=args.show_query_plan,
                show_discovered_phrases=args.show_discovered_phrases,
            )
        else:
            print_jsonl(
                results,
                expansion,
                show_expansion=args.show_expansion,
                show_query_plan=args.show_query_plan,
                show_discovered_phrases=args.show_discovered_phrases,
            )
    else:
        if args.period_sections:
            print_period_sections(results, expansion, args)
        else:
            print_readable(results, expansion, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
