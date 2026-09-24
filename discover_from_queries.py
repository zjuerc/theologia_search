#!/usr/bin/env python3
"""Write human-review phrase candidates discovered by deterministic search."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

try:
    from .common import (
        DEFAULT_DISCOVERY_CSV_PATH,
        DEFAULT_DISCOVERY_JSONL_PATH,
        DEFAULT_EVALUATION_QUERIES_PATH,
        DEFAULT_INDEX_PATH,
        SemanticSearchError,
        configure_output,
        display_text,
        iter_jsonl,
        norm_lookup,
    )
    from .search import load_lexicon, search_concept
except ImportError:  # pragma: no cover - supports direct script execution.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import (
        DEFAULT_DISCOVERY_CSV_PATH,
        DEFAULT_DISCOVERY_JSONL_PATH,
        DEFAULT_EVALUATION_QUERIES_PATH,
        DEFAULT_INDEX_PATH,
        SemanticSearchError,
        configure_output,
        display_text,
        iter_jsonl,
        norm_lookup,
    )
    from search import load_lexicon, search_concept


DISCOVERY_FIELDS = [
    "candidate_phrase",
    "normalized_phrase",
    "query",
    "occurrence_count",
    "source_count",
    "evidence_id",
    "source_id",
    "source_title",
    "author",
    "page_number",
    "heading",
    "matched_raw_terms",
    "matched_registered_terms",
    "proximity_reason",
    "first_seen_at",
    "status",
]


def load_queries(path: Path) -> list[str]:
    queries: list[str] = []
    for row in iter_jsonl(path):
        query = display_text(row.get("concept") or row.get("query"))
        if query:
            queries.append(query)
    return queries


def normalize_query_list(values: list[str]) -> list[str]:
    seen = set()
    queries = []
    for value in values:
        query = display_text(value)
        key = norm_lookup(query)
        if key and key not in seen:
            seen.add(key)
            queries.append(query)
    return queries


def compact_join(values) -> str:
    if not values:
        return ""
    if isinstance(values, dict):
        items = []
        for key in sorted(values):
            variants = values.get(key) or []
            if variants:
                items.append(f"{key}: {'|'.join(variants)}")
            else:
                items.append(str(key))
        return "; ".join(items)
    return "; ".join(str(value) for value in sorted(set(values)))


def proximity_summary(row: dict) -> str:
    pieces = []
    for match in row.get("proximity_matches") or []:
        pieces.append(
            f"{match.get('raw_term')}~{match.get('registered_term')} "
            f"in {match.get('location')} ({match.get('distance')})"
        )
    return "; ".join(pieces[:4])


def discover_candidates(
    con: sqlite3.Connection,
    queries: list[str],
    lexicon: dict,
    *,
    limit: int = 20,
    candidate_limit: int = 100,
) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    grouped: dict[tuple[str, str], dict] = {}
    grouped_sources: dict[tuple[str, str], set[str]] = defaultdict(set)

    for query in normalize_query_list(queries):
        results, _ = search_concept(
            con,
            query,
            lexicon,
            limit=limit,
            candidate_limit=candidate_limit,
            include_cooccurrence=False,
            cluster_results=False,
        )
        for result in results:
            for phrase in result.get("discovered_phrases") or []:
                normalized = norm_lookup(phrase)
                if not normalized:
                    continue
                key = (norm_lookup(query), normalized)
                if key not in grouped:
                    grouped[key] = {
                        "candidate_phrase": phrase,
                        "normalized_phrase": normalized,
                        "query": query,
                        "occurrence_count": 0,
                        "source_count": 0,
                        "evidence_id": result.get("evidence_id") or "",
                        "source_id": result.get("source_id") or "",
                        "source_title": result.get("source_title") or "",
                        "author": result.get("author") or "",
                        "page_number": result.get("page_number") or "",
                        "heading": result.get("heading") or result.get("outline_path") or "",
                        "matched_raw_terms": compact_join(result.get("matched_raw_terms") or []),
                        "matched_registered_terms": compact_join(result.get("matched_registered_terms") or []),
                        "proximity_reason": proximity_summary(result),
                        "first_seen_at": now,
                        "status": "pending",
                    }
                grouped[key]["occurrence_count"] += 1
                source_id = result.get("source_id")
                if source_id:
                    grouped_sources[key].add(source_id)

    rows = []
    for key, row in grouped.items():
        row["source_count"] = len(grouped_sources[key])
        rows.append(row)
    rows.sort(key=lambda row: (-row["occurrence_count"], -row["source_count"], row["query"], row["normalized_phrase"]))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=DISCOVERY_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in DISCOVERY_FIELDS} for row in rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover pending phrase candidates from Theologia Search results.")
    parser.add_argument("--concept", nargs="+", help="One concept query to inspect.")
    parser.add_argument("--queries", type=Path, default=None, help="JSONL file containing concept/query rows.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH, help="SQLite semantic index path.")
    parser.add_argument("--lexicon", type=Path, default=None, help="Optional external lexicon path.")
    parser.add_argument("--limit", type=int, default=20, help="Search results to inspect per query.")
    parser.add_argument("--candidate-limit", type=int, default=100, help="Internal search candidate pool size.")
    parser.add_argument("--jsonl-out", type=Path, default=DEFAULT_DISCOVERY_JSONL_PATH, help="Review JSONL output path.")
    parser.add_argument("--csv-out", type=Path, default=DEFAULT_DISCOVERY_CSV_PATH, help="Review CSV output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.candidate_limit < args.limit:
        parser.error("--candidate-limit must be greater than or equal to --limit")
    if not args.concept and not args.queries:
        args.queries = DEFAULT_EVALUATION_QUERIES_PATH

    try:
        queries = []
        if args.concept:
            queries.append(" ".join(args.concept))
        if args.queries:
            queries.extend(load_queries(args.queries))
        if not queries:
            raise SemanticSearchError("no queries supplied")
        lexicon = load_lexicon(args.lexicon)
        con = sqlite3.connect(str(args.index))
        con.row_factory = sqlite3.Row
        try:
            rows = discover_candidates(
                con,
                queries,
                lexicon,
                limit=args.limit,
                candidate_limit=args.candidate_limit,
            )
        finally:
            con.close()
        write_jsonl(args.jsonl_out, rows)
        write_csv(args.csv_out, rows)
    except SemanticSearchError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2

    print(f"Wrote {len(rows)} discovery candidates to {args.jsonl_out} and {args.csv_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
