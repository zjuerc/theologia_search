#!/usr/bin/env python3
"""Comprehensive search timing and correctness audit."""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from . import gui, search
    from .search import AdvancedSearchCriteria
except ImportError:  # pragma: no cover - supports direct script execution.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gui, search
    from search import AdvancedSearchCriteria


PERIODS = ("before_nicene", "nicene_to_reformation", "post_reformation")
METADATA_VALUES = {
    "author": "Augustine of Hippo",
    "mentioned_author": "Origen",
    "period_id": "before_nicene",
    "book": "City of God",
    "chapter": "Book II",
}


@dataclass(frozen=True)
class AuditCase:
    name: str
    kind: str
    query: str = ""
    criteria: AdvancedSearchCriteria | None = None
    intentional_empty: bool = False


def _metadata_case(name: str, fields: tuple[str, ...], *, concept: str = "") -> AuditCase:
    values = {field: METADATA_VALUES[field] for field in fields}
    return AuditCase(name, "advanced", criteria=AdvancedSearchCriteria(concept=concept, **values))


def audit_cases() -> list[AuditCase]:
    cases = [
        AuditCase("regular_registered_one_grace", "regular", query="grace"),
        AuditCase("regular_registered_one_doctrine", "regular", query="doctrine"),
        AuditCase("regular_registered_multi", "regular", query="doctrine grace"),
        AuditCase("regular_nonregistered_one", "regular", query="eschatological"),
        AuditCase("regular_nonregistered_multi", "regular", query="eschatological qwertytheology"),
        AuditCase("regular_morphology_one", "regular", query="lawful"),
        AuditCase("regular_morphology_multi", "regular", query="live under law"),
        AuditCase("regular_fuzzy_variant", "regular", query="souls"),
        AuditCase("regular_intentional_empty", "regular", query="qwertytheology", intentional_empty=True),
        AuditCase("advanced_registered_one", "advanced", criteria=AdvancedSearchCriteria(concept="grace")),
        AuditCase("advanced_registered_multi", "advanced", criteria=AdvancedSearchCriteria(concept="doctrine grace")),
        AuditCase("advanced_nonregistered_one", "advanced", criteria=AdvancedSearchCriteria(concept="eschatological")),
        AuditCase("advanced_nonregistered_multi", "advanced", criteria=AdvancedSearchCriteria(concept="eschatological qwertytheology")),
        AuditCase("advanced_morphology_one", "advanced", criteria=AdvancedSearchCriteria(concept="lawful")),
        AuditCase("advanced_morphology_multi", "advanced", criteria=AdvancedSearchCriteria(concept="live under law")),
        AuditCase("advanced_fuzzy_variant", "advanced", criteria=AdvancedSearchCriteria(concept="souls")),
        AuditCase("advanced_intentional_empty", "advanced", criteria=AdvancedSearchCriteria(concept="qwertytheology"), intentional_empty=True),
        AuditCase("advanced_explicit_period", "advanced", criteria=AdvancedSearchCriteria(concept="grace", period_id="before_nicene")),
    ]

    fields = tuple(METADATA_VALUES)
    for size in range(1, len(fields) + 1):
        for combination in itertools.combinations(fields, size):
            cases.append(_metadata_case(f"advanced_fields_{'+'.join(combination)}", combination))

    cases.extend(
        [
            _metadata_case("advanced_concept_author", ("author",), concept="doctrine"),
            _metadata_case("advanced_concept_mentioned_author", ("mentioned_author",), concept="doctrine"),
            _metadata_case("advanced_concept_book_chapter", ("book", "chapter"), concept="grace"),
            _metadata_case("advanced_concept_four_fields", ("author", "period_id", "book", "chapter"), concept="grace"),
            AuditCase(
                "advanced_concept_incompatible_and",
                "advanced",
                criteria=AdvancedSearchCriteria(
                    concept="grace", author="Augustine of Hippo", period_id="before_nicene",
                    connectors=("AND", "AND", "AND", "AND", "AND"),
                ),
                intentional_empty=True,
            ),
            AuditCase(
                "advanced_concept_author_or_mentioned",
                "advanced",
                criteria=AdvancedSearchCriteria(
                    concept="doctrine", author="Augustine of Hippo", mentioned_author="Origen",
                    connectors=("AND", "OR", "AND", "AND", "AND"),
                ),
            ),
            AuditCase(
                "advanced_concept_author_and_mentioned",
                "advanced",
                criteria=AdvancedSearchCriteria(
                    concept="doctrine", author="Augustine of Hippo", mentioned_author="Origen",
                    connectors=("AND", "AND", "AND", "AND", "AND"),
                ),
            ),
            AuditCase(
        "advanced_concept_period_or_book",
                "advanced",
                criteria=AdvancedSearchCriteria(
                    concept="grace", period_id="before_nicene", book="City of God",
                    connectors=("AND", "AND", "OR", "AND", "AND"),
                ),
                intentional_empty=True,
            ),
        ]
    )
    return cases


def _normalized_text(row: dict) -> str:
    return search.norm_lookup(" ".join(str(row.get(field) or "") for field in ("heading", "outline_path", "verbatim_text")))


def _fts_ids(con: sqlite3.Connection, expansion: search.QueryExpansion) -> set[str]:
    query = search.make_fts_query(expansion.searchable_terms, max_terms=32)
    if not query:
        return set()
    return {row[0] for row in con.execute("SELECT evidence_id FROM evidence_fts WHERE evidence_fts MATCH ?", (query,))}


def _load_metadata_rows(con: sqlite3.Connection) -> dict[str, dict]:
    columns = (
        "evidence_id, source_id, source_title, author, mentioned_authors_json, "
        "mentioned_authors_text, author_period_id, heading, outline_path, source_collection"
    )
    return {row["evidence_id"]: dict(row) for row in con.execute(f"SELECT {columns} FROM evidence")}


def _load_evidence_texts(con: sqlite3.Connection) -> dict[str, dict]:
    return {
        row["evidence_id"]: dict(row)
        for row in con.execute("SELECT evidence_id, heading, outline_path, verbatim_text FROM evidence")
    }


def _expected_period_counts(con: sqlite3.Connection, case: AuditCase, lexicon: dict, metadata_rows: dict[str, dict]) -> dict[str, int]:
    if case.kind == "regular":
        expansion = search.expand_query(con, case.query, lexicon, include_cooccurrence=False)
        if search.query_has_unmatchable_term(con, expansion, search.term_stats(con)):
            return {period: 0 for period in PERIODS}
        matching_ids = _fts_ids(con, expansion)
        return {
            period: sum(1 for evidence_id in matching_ids if (row := metadata_rows.get(evidence_id)) and row.get("author_period_id") == period)
            for period in PERIODS
        }

    criteria = search.validate_advanced_criteria(case.criteria)
    concept_ids = None
    if criteria.concept:
        expansion = search.expand_query(con, criteria.concept, lexicon, include_cooccurrence=False)
        if search.query_has_unmatchable_term(con, expansion, search.term_stats(con)):
            concept_ids = set()
        else:
            concept_ids = _fts_ids(con, expansion)
    counts = {period: 0 for period in PERIODS}
    for evidence_id, row in metadata_rows.items():
        if criteria.period_id and row.get("author_period_id") != criteria.period_id:
            continue
        matches = {"concept": evidence_id in concept_ids} if concept_ids is not None else {}
        metadata_matches, _ = search.advanced_metadata_matches(row, criteria)
        matches.update(metadata_matches)
        if search.evaluate_advanced_fields(criteria, matches) and row.get("author_period_id") in counts:
            counts[row["author_period_id"]] += 1
    return counts


def _highlight_is_consistent(result: dict) -> bool:
    snippet = result.get("snippet") or ""
    if "[[" not in snippet or "]]" not in snippet:
        return True
    evidence = search.norm_lookup(result.get("verbatim_text") or "")
    highlighted = re.findall(r"\[\[(.*?)\]\]", snippet, flags=re.DOTALL)
    return all(search.norm_lookup(value) in evidence for value in highlighted if value.strip())


def _review_result(case: AuditCase, result: dict, group_period: str, evidence_texts: dict[str, dict]) -> list[str]:
    result = {**result, **evidence_texts.get(result.get("evidence_id"), {})}
    issues = []
    if result.get("author_period_id") != group_period:
        issues.append("period mismatch")
    if not _highlight_is_consistent(result):
        issues.append("snippet highlight absent from evidence text")
    if case.kind == "regular":
        evidence = _normalized_text(result)
        query_terms = search.raw_query_terms(case.query)
        morphology_terms = [search.norm_lookup(term) for term in (result.get("matched_morphology_forms") or {})]
        morphology_terms.extend(search.norm_lookup(term) for term in (result.get("matched_lemmas") or []))
        matched_terms = [term for term in query_terms + morphology_terms if term and term in evidence]
        if not matched_terms:
            issues.append("query not visibly supported by evidence text")
        elif len(query_terms) > 1 and not all(term in matched_terms for term in query_terms):
            issues.append("weak relevance: multi-term query only partially matched")
    else:
        criteria = search.validate_advanced_criteria(case.criteria)
        matches, _ = search.advanced_metadata_matches(result, criteria)
        if criteria.concept:
            matches["concept"] = bool(result.get("advanced_concept_match", True))
            evidence = _normalized_text(result)
            query_terms = search.raw_query_terms(criteria.concept)
            morphology_terms = [search.norm_lookup(term) for term in (result.get("matched_morphology_forms") or {})]
            morphology_terms.extend(search.norm_lookup(term) for term in (result.get("matched_lemmas") or []))
            matched_terms = [term for term in query_terms + morphology_terms if term and term in evidence]
            if not matched_terms:
                issues.append("concept not visibly supported by evidence text")
            elif len(query_terms) > 1 and not all(term in matched_terms for term in query_terms):
                issues.append("weak relevance: multi-term concept only partially matched")
        if not search.evaluate_advanced_fields(criteria, matches):
            issues.append("advanced boolean fields do not match")
    return issues


def _representative(result: dict) -> dict:
    return {
        "evidence_id": result.get("evidence_id"),
        "author": result.get("author"),
        "source_title": result.get("source_title"),
        "heading": result.get("heading"),
        "snippet": result.get("snippet"),
        "matched_query_terms": result.get("matched_query_terms"),
        "matched_lemmas": result.get("matched_lemmas"),
        "matched_morphology_forms": result.get("matched_morphology_forms"),
        "advanced_filter_matches": result.get("advanced_filter_matches"),
        "advanced_filter_reasons": result.get("advanced_filter_reasons"),
    }


def run_audit(
    index_path: Path,
    lexicon_path: Path,
    *,
    limit: int = 10,
    repeats: int = 2,
    selected_names: set[str] | None = None,
) -> list[dict]:
    lexicon = search.load_lexicon(lexicon_path)
    con = sqlite3.connect(str(index_path))
    con.row_factory = sqlite3.Row
    try:
        metadata_rows = _load_metadata_rows(con)
        evidence_texts = _load_evidence_texts(con)
        reports = []
        cases = [case for case in audit_cases() if selected_names is None or case.name in selected_names]
        for case in cases:
            timings, outputs = [], []
            for _ in range(repeats):
                started = time.perf_counter()
                if case.kind == "regular":
                    groups, _ = search.search_concept_by_period(
                        con,
                        case.query,
                        lexicon,
                        limit=limit,
                        candidate_limit=max(20, limit * 2),
                        include_cooccurrence=False,
                    )
                else:
                    groups, _ = search.search_advanced_by_period(
                        con,
                        case.criteria,
                        lexicon,
                        limit=limit,
                        candidate_limit=max(20, limit * 2),
                    )
                timings.append(time.perf_counter() - started)
                outputs.append(groups)
            observed = {group["period_id"]: list(group.get("results") or []) for group in outputs[-1]}
            expected = _expected_period_counts(con, case, lexicon, metadata_rows)
            issues = []
            for period in PERIODS:
                rows = observed.get(period, [])
                if len(rows) > limit:
                    issues.append(f"{period}: exceeds limit")
                for row in rows:
                    issues.extend(f"{period}: {issue}" for issue in _review_result(case, row, period, evidence_texts))
                if expected[period] > 0 and not rows:
                    issues.append(f"{period}: missing results despite indexed evidence")
                if case.intentional_empty and rows:
                    issues.append(f"{period}: returned results for intentional-empty case")
            hard_issues = [issue for issue in issues if ": weak relevance:" not in issue]
            has_weak_relevance = any(": weak relevance:" in issue for issue in issues)
            if hard_issues:
                classification = "Needs investigation"
            elif case.intentional_empty and not any(observed.values()):
                classification = "Correct intentional empty result"
            elif not any(expected.values()):
                classification = "Correct genuine empty result"
            elif has_weak_relevance:
                classification = "Correct but weak relevance"
            else:
                classification = "Correct and meaningful"
            reports.append({
                "name": case.name,
                "kind": case.kind,
                "query": case.query,
                "criteria": vars(case.criteria) if case.criteria else None,
                "intentional_empty": case.intentional_empty,
                "median_seconds": statistics.median(timings),
                "min_seconds": min(timings),
                "max_seconds": max(timings),
                "expected_period_counts": expected,
                "observed_period_counts": {period: len(observed.get(period, [])) for period in PERIODS},
                "classification": classification,
                "issues": sorted(set(issues)),
                "representatives": {period: _representative(rows[0]) for period, rows in observed.items() if rows},
            })
        return reports
    finally:
        con.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the comprehensive Theologia search audit.")
    parser.add_argument("--index", type=Path, default=Path("generated/semantic_index.sqlite"))
    parser.add_argument("--lexicon", type=Path, default=Path("concept_query_lexicon.json"))
    parser.add_argument("--limit", type=int, default=10, help="Results per historical period.")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--case", action="append", dest="case_names", help="Run only this case name; repeat for multiple cases.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    reports = run_audit(
        args.index,
        args.lexicon,
        limit=args.limit,
        repeats=args.repeats,
        selected_names=set(args.case_names) if args.case_names else None,
    )
    if args.as_json:
        print(json.dumps(reports, indent=2, ensure_ascii=False))
        return 0
    print(f"Search audit: {len(reports)} cases, limit={args.limit} per period, repeats={args.repeats}")
    for report in reports:
        counts = ", ".join(f"{period}={report['observed_period_counts'][period]}/{report['expected_period_counts'][period]}" for period in PERIODS)
        print(f"{report['name']}: {report['classification']}; median={report['median_seconds']:.3f}s; {counts}")
        if report["issues"]:
            print(f"  issues: {'; '.join(report['issues'])}")
        for period, representative in report["representatives"].items():
            print(f"  {period}: {representative['evidence_id']} | {representative['author']} | {representative['heading']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
