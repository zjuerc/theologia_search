#!/usr/bin/env python3
"""Evaluate Theologia Search against a small benchmark set."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path

try:
    from .common import (
        DEFAULT_EVALUATION_QUERIES_PATH,
        DEFAULT_EVALUATION_REPORT_JSON_PATH,
        DEFAULT_EVALUATION_REPORT_MD_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_LEXICON_PATH,
        SemanticSearchError,
        configure_output,
        display_text,
        iter_jsonl,
        norm_lookup,
        write_json,
    )
    from .search import load_lexicon, search_concept
except ImportError:  # pragma: no cover - supports direct script execution.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import (
        DEFAULT_EVALUATION_QUERIES_PATH,
        DEFAULT_EVALUATION_REPORT_JSON_PATH,
        DEFAULT_EVALUATION_REPORT_MD_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_LEXICON_PATH,
        SemanticSearchError,
        configure_output,
        display_text,
        iter_jsonl,
        norm_lookup,
        write_json,
    )
    from search import load_lexicon, search_concept


def load_evaluation_queries(path: Path) -> list[dict]:
    rows = []
    for row in iter_jsonl(path):
        query = display_text(row.get("concept") or row.get("query"))
        if not query:
            continue
        rows.append(
            {
                "query_id": display_text(row.get("query_id")) or norm_lookup(query).replace(" ", "_"),
                "concept": query,
                "expected_terms": [norm_lookup(term) for term in row.get("expected_terms", []) if norm_lookup(term)],
                "expected_evidence_ids": [
                    display_text(evidence_id) for evidence_id in row.get("expected_evidence_ids", []) if display_text(evidence_id)
                ],
                "must_include_any_source_ids": [
                    display_text(source_id)
                    for source_id in row.get("must_include_any_source_ids", [])
                    if display_text(source_id)
                ],
                "notes": display_text(row.get("notes")),
            }
        )
    return rows


def quality_rank(value: str) -> int:
    return {
        "weak": 1,
        "related": 2,
        "moderate": 3,
        "good": 3,
        "strong": 4,
        "excellent": 5,
    }.get((value or "").casefold(), 0)


def evaluate_query(con: sqlite3.Connection, lexicon: dict, query: dict, *, limit: int, candidate_limit: int) -> dict:
    results, expansion = search_concept(
        con,
        query["concept"],
        lexicon,
        limit=limit,
        candidate_limit=candidate_limit,
        include_cooccurrence=False,
        cluster_results=False,
    )
    expected_evidence_ids = set(query["expected_evidence_ids"])
    expected_terms = set(query["expected_terms"])
    expected_source_ids = set(query["must_include_any_source_ids"])
    top_evidence_ids = [row.get("evidence_id") for row in results]
    top_source_ids = [row.get("source_id") for row in results]
    matched_terms = set()
    for row in results:
        matched_terms.update(norm_lookup(term) for term in row.get("matched_registered_terms") or [])
        matched_terms.update(norm_lookup(term) for term in row.get("matched_raw_terms") or [])

    evidence_hit = not expected_evidence_ids or bool(expected_evidence_ids & set(top_evidence_ids))
    term_hit = not expected_terms or bool(expected_terms & matched_terms)
    source_hit = not expected_source_ids or bool(expected_source_ids & set(top_source_ids))
    weak_result_rate = 0.0
    if results:
        weak_result_rate = sum(
            1 for row in results if quality_rank(row.get("quality_label") or row.get("match_quality")) <= 1
        ) / len(results)
    qualities = sorted(
        (quality_rank(row.get("quality_label") or row.get("match_quality")) for row in results),
        reverse=True,
    )
    median_quality_rank = qualities[len(qualities) // 2] if qualities else 0
    top_score = results[0]["concept_score"] if results else 0.0
    second_score = results[1]["concept_score"] if len(results) > 1 else 0.0

    return {
        "query_id": query["query_id"],
        "concept": query["concept"],
        "passed": bool(results) and evidence_hit and term_hit and source_hit,
        "result_count": len(results),
        "top_evidence_id": top_evidence_ids[0] if top_evidence_ids else "",
        "top_source_id": top_source_ids[0] if top_source_ids else "",
        "top_score": top_score,
        "top_score_gap": round(top_score - second_score, 6),
        "top_match_quality": (
            (results[0].get("quality_label") or results[0].get("match_quality")) if results else ""
        ),
        "median_match_quality_rank": median_quality_rank,
        "weak_result_rate": round(weak_result_rate, 6),
        "expected_evidence_hit": evidence_hit,
        "expected_term_hit": term_hit,
        "expected_source_hit": source_hit,
        "expected_terms": sorted(expected_terms),
        "expected_evidence_ids": sorted(expected_evidence_ids),
        "must_include_any_source_ids": sorted(expected_source_ids),
        "matched_terms": sorted(matched_terms),
        "direct_terms": expansion.direct_terms,
        "raw_query_terms": expansion.raw_query_terms,
        "notes": query.get("notes", ""),
    }


def evaluate_search(
    *,
    index_path: Path = DEFAULT_INDEX_PATH,
    lexicon_path: Path = DEFAULT_LEXICON_PATH,
    queries_path: Path = DEFAULT_EVALUATION_QUERIES_PATH,
    json_out: Path = DEFAULT_EVALUATION_REPORT_JSON_PATH,
    markdown_out: Path = DEFAULT_EVALUATION_REPORT_MD_PATH,
    limit: int = 10,
    candidate_limit: int = 100,
) -> dict:
    if not index_path.exists():
        raise SemanticSearchError(f"missing semantic index: {index_path}")
    queries = load_evaluation_queries(queries_path)
    if not queries:
        raise SemanticSearchError(f"no evaluation queries found in {queries_path}")
    lexicon = load_lexicon(lexicon_path)
    con = sqlite3.connect(str(index_path))
    con.row_factory = sqlite3.Row
    try:
        query_results = [
            evaluate_query(con, lexicon, query, limit=limit, candidate_limit=candidate_limit)
            for query in queries
        ]
    finally:
        con.close()
    passed = sum(1 for row in query_results if row["passed"])
    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "index_path": str(index_path),
        "queries_path": str(queries_path),
        "query_count": len(query_results),
        "passed_count": passed,
        "failed_count": len(query_results) - passed,
        "results": query_results,
    }
    write_json(json_out, report)
    write_markdown_report(markdown_out, report)
    return report


def write_markdown_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Theologia Search Evaluation",
        "",
        f"Generated: {report['generated_at']}",
        f"Passed: {report['passed_count']} / {report['query_count']}",
        "",
        "| Query | Pass | Top Evidence | Quality | Score | Weak Rate |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in report["results"]:
        lines.append(
            "| {query} | {passed} | {evidence} | {quality} | {score:.6f} | {weak:.2f} |".format(
                query=row["concept"].replace("|", "\\|"),
                passed="yes" if row["passed"] else "no",
                evidence=(row["top_evidence_id"] or "").replace("|", "\\|"),
                quality=row["top_match_quality"],
                score=float(row["top_score"]),
                weak=float(row["weak_result_rate"]),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Theologia Search retrieval quality.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH, help="SQLite semantic index path.")
    parser.add_argument("--lexicon", type=Path, default=DEFAULT_LEXICON_PATH, help="Curated query lexicon path.")
    parser.add_argument("--queries", type=Path, default=DEFAULT_EVALUATION_QUERIES_PATH, help="Evaluation JSONL path.")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_EVALUATION_REPORT_JSON_PATH, help="JSON report output path.")
    parser.add_argument("--markdown-out", type=Path, default=DEFAULT_EVALUATION_REPORT_MD_PATH, help="Markdown report output path.")
    parser.add_argument("--limit", type=int, default=10, help="Search results inspected per query.")
    parser.add_argument("--candidate-limit", type=int, default=100, help="Internal search candidate pool size.")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.candidate_limit < args.limit:
        parser.error("--candidate-limit must be greater than or equal to --limit")
    try:
        report = evaluate_search(
            index_path=args.index,
            lexicon_path=args.lexicon,
            queries_path=args.queries,
            json_out=args.json_out,
            markdown_out=args.markdown_out,
            limit=args.limit,
            candidate_limit=args.candidate_limit,
        )
    except SemanticSearchError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2
    print(f"Passed {report['passed_count']} / {report['query_count']} evaluation queries")
    print(f"Wrote {args.json_out} and {args.markdown_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
