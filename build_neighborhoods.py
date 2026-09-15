#!/usr/bin/env python3
"""Build deterministic concept neighborhoods from indexed KB co-occurrence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

try:
    from .common import (
        DEFAULT_CLUSTERS_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_NEIGHBORHOODS_PATH,
        SemanticSearchError,
        configure_output,
        norm_lookup,
        token_list,
    )
except ImportError:  # pragma: no cover - supports direct script execution.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import (
        DEFAULT_CLUSTERS_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_NEIGHBORHOODS_PATH,
        SemanticSearchError,
        configure_output,
        norm_lookup,
        token_list,
    )


class DisjointSet:
    def __init__(self):
        self.parents: dict[str, str] = {}

    def find(self, item: str) -> str:
        if item not in self.parents:
            self.parents[item] = item
        if self.parents[item] != item:
            self.parents[item] = self.find(self.parents[item])
        return self.parents[item]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parents[right_root] = left_root


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def heading_overlap(left: str, right: str, heading: str, outline_path: str) -> bool:
    context_tokens = set(token_list(f"{heading} {outline_path}"))
    return bool(context_tokens & set(token_list(left))) and bool(context_tokens & set(token_list(right)))


def load_evidence_terms(con: sqlite3.Connection, *, max_terms_per_evidence: int) -> dict[str, list[dict]]:
    rows_by_evidence: dict[str, list[dict]] = defaultdict(list)
    for row in con.execute(
        """
        SELECT
            e.evidence_id,
            e.source_id,
            e.heading,
            e.outline_path,
            et.term,
            et.occurrence_count,
            et.idf,
            ts.is_common
        FROM evidence_terms et
        JOIN evidence e ON e.evidence_id = et.evidence_id
        JOIN term_stats ts ON ts.term = et.term
        ORDER BY e.evidence_id, et.idf DESC, et.term
        """
    ):
        if row["is_common"] and " " not in row["term"]:
            continue
        rows_by_evidence[row["evidence_id"]].append(dict(row))

    for evidence_id, rows in list(rows_by_evidence.items()):
        rows_by_evidence[evidence_id] = rows[:max_terms_per_evidence]
    return rows_by_evidence


def build_neighborhood_rows(
    con: sqlite3.Connection,
    *,
    max_terms_per_evidence: int = 24,
    min_weight: float = 1.0,
    sample_limit: int = 5,
) -> list[dict]:
    evidence_terms = load_evidence_terms(con, max_terms_per_evidence=max_terms_per_evidence)
    edge_stats: dict[tuple[str, str], dict] = {}

    for evidence_id, rows in evidence_terms.items():
        by_term = {row["term"]: row for row in rows}
        for left, right in combinations(sorted(by_term), 2):
            left_row = by_term[left]
            right_row = by_term[right]
            key = (left, right)
            stats = edge_stats.setdefault(
                key,
                {
                    "weight": 0.0,
                    "shared_evidence_count": 0,
                    "sources": set(),
                    "sample_evidence_ids": [],
                    "heading_overlap_count": 0,
                },
            )
            left_count = max(1, int(left_row["occurrence_count"] or 1))
            right_count = max(1, int(right_row["occurrence_count"] or 1))
            idf_weight = (float(left_row["idf"]) + float(right_row["idf"])) / 2.0
            count_weight = min(2.0, 0.5 + 0.25 * (left_count + right_count))
            overlap = heading_overlap(left, right, left_row.get("heading") or "", left_row.get("outline_path") or "")
            stats["weight"] += idf_weight * count_weight + (0.75 if overlap else 0.0)
            stats["shared_evidence_count"] += 1
            stats["sources"].add(left_row["source_id"])
            if overlap:
                stats["heading_overlap_count"] += 1
            if len(stats["sample_evidence_ids"]) < sample_limit:
                stats["sample_evidence_ids"].append(evidence_id)

    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    for (left, right), stats in edge_stats.items():
        source_count = len(stats["sources"])
        source_spread_bonus = min(2.0, max(0, source_count - 1) * 0.35)
        weight = stats["weight"] + source_spread_bonus
        if weight < min_weight:
            continue
        basis = "registered_term_cooccurrence"
        if stats["heading_overlap_count"]:
            basis += "+heading_overlap"
        rows.append(
            {
                "anchor": left,
                "neighbor": right,
                "weight": round(weight, 6),
                "shared_evidence_count": stats["shared_evidence_count"],
                "shared_source_count": source_count,
                "sample_evidence_ids": stats["sample_evidence_ids"],
                "basis": basis,
                "generated_at": generated_at,
            }
        )
    rows.sort(key=lambda row: (-row["weight"], row["anchor"], row["neighbor"]))
    return rows


def build_cluster_rows(
    rows: list[dict],
    *,
    min_cluster_weight: float = 40.0,
    max_neighbors: int = 12,
) -> list[dict]:
    neighbor_map: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        anchor = norm_lookup(row["anchor"])
        neighbor = norm_lookup(row["neighbor"])
        if not anchor or not neighbor:
            continue
        weight = float(row["weight"])
        if weight < min_cluster_weight:
            continue
        neighbor_map[anchor].append((neighbor, weight))
        neighbor_map[neighbor].append((anchor, weight))

    cluster_rows = []
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    for index, anchor in enumerate(sorted(neighbor_map), 1):
        ranked_neighbors = sorted(neighbor_map[anchor], key=lambda item: (-item[1], item[0]))[:max_neighbors]
        member_list = [anchor] + [neighbor for neighbor, _ in ranked_neighbors]
        label_terms = member_list[:4]
        cluster_rows.append(
            {
                "cluster_id": f"concept_cluster_{index:04d}",
                "cluster_label": " / ".join(label_terms),
                "member_count": len(member_list),
                "members": member_list,
                "anchor": anchor,
                "generated_at": generated_at,
            }
        )
    return cluster_rows


def build_neighborhoods(
    *,
    index_path: Path = DEFAULT_INDEX_PATH,
    neighborhoods_path: Path = DEFAULT_NEIGHBORHOODS_PATH,
    clusters_path: Path = DEFAULT_CLUSTERS_PATH,
    max_terms_per_evidence: int = 24,
    min_weight: float = 1.0,
    min_cluster_weight: float = 40.0,
) -> tuple[list[dict], list[dict]]:
    if not index_path.exists():
        raise SemanticSearchError(f"missing semantic index: {index_path}")
    con = sqlite3.connect(str(index_path))
    con.row_factory = sqlite3.Row
    try:
        rows = build_neighborhood_rows(
            con,
            max_terms_per_evidence=max_terms_per_evidence,
            min_weight=min_weight,
        )
    finally:
        con.close()
    cluster_rows = build_cluster_rows(rows, min_cluster_weight=min_cluster_weight)
    write_jsonl(neighborhoods_path, rows)
    write_jsonl(clusters_path, cluster_rows)
    return rows, cluster_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build deterministic concept neighborhoods from the semantic index.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH, help="SQLite semantic index path.")
    parser.add_argument("--neighborhoods-out", type=Path, default=DEFAULT_NEIGHBORHOODS_PATH, help="JSONL edge output path.")
    parser.add_argument("--clusters-out", type=Path, default=DEFAULT_CLUSTERS_PATH, help="JSONL cluster output path.")
    parser.add_argument("--max-terms-per-evidence", type=int, default=24, help="Maximum terms retained from each evidence row.")
    parser.add_argument("--min-weight", type=float, default=1.0, help="Minimum edge weight to write.")
    parser.add_argument("--min-cluster-weight", type=float, default=40.0, help="Minimum edge weight used for neighborhood clusters.")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_terms_per_evidence < 2:
        parser.error("--max-terms-per-evidence must be at least 2")
    try:
        rows, clusters = build_neighborhoods(
            index_path=args.index,
            neighborhoods_path=args.neighborhoods_out,
            clusters_path=args.clusters_out,
            max_terms_per_evidence=args.max_terms_per_evidence,
            min_weight=args.min_weight,
            min_cluster_weight=args.min_cluster_weight,
        )
    except SemanticSearchError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2
    print(f"Wrote {len(rows)} concept-neighborhood edges to {args.neighborhoods_out}")
    print(f"Wrote {len(clusters)} concept clusters to {args.clusters_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
