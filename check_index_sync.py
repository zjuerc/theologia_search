#!/usr/bin/env python3
"""Check whether the Theologia Search SQLite index matches the current KB."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from . import morphology
    from . import periods
    from .build_index import SEMANTIC_INDEX_SCHEMA_VERSION, build_semantic_index
    from .common import (
        DEFAULT_INDEX_MANIFEST_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_KB_DIR,
        EVIDENCE_KEYS,
        SemanticSearchError,
        configure_output,
        iter_jsonl,
        load_manifest,
        read_json,
        selected_evidence_paths,
    )
except ImportError:  # pragma: no cover - supports direct script execution.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import morphology
    import periods
    from build_index import SEMANTIC_INDEX_SCHEMA_VERSION, build_semantic_index
    from common import (
        DEFAULT_INDEX_MANIFEST_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_KB_DIR,
        EVIDENCE_KEYS,
        SemanticSearchError,
        configure_output,
        iter_jsonl,
        load_manifest,
        read_json,
        selected_evidence_paths,
    )


COUNT_KEYS = {
    "primary": "evidence_primary",
    "extended": "evidence_extended",
    "archival": "evidence_archival",
}


@dataclass
class SyncReport:
    synced: bool
    messages: list[str]
    kb_snapshot: dict
    index_manifest: dict | None
    sqlite_metadata: dict | None


def expected_evidence_count(manifest: dict, kb_dir: Path, layer: str) -> int:
    counts = manifest.get("counts", {})
    if layer == "all":
        expected_keys = [COUNT_KEYS[item] for item in ("primary", "extended", "archival")]
        if all(isinstance(counts.get(key), int) for key in expected_keys):
            return sum(int(counts[key]) for key in expected_keys)
    elif isinstance(counts.get(COUNT_KEYS.get(layer, "")), int):
        return int(counts[COUNT_KEYS[layer]])

    total = 0
    for path in selected_evidence_paths(manifest, layer, kb_dir):
        total += sum(1 for _row in iter_jsonl(path))
    return total


def kb_snapshot(kb_dir: Path, layer: str) -> dict:
    manifest = load_manifest(kb_dir)
    if layer not in set(EVIDENCE_KEYS) | {"all"}:
        raise SemanticSearchError(f"unknown evidence layer: {layer}")
    return {
        "kb_dir": str(kb_dir),
        "semantic_index_schema_version": SEMANTIC_INDEX_SCHEMA_VERSION,
        "morphology_schema_version": morphology.MORPHOLOGY_SCHEMA_VERSION,
        "morphology_config_digest": morphology.morphology_digest(),
        "author_period_schema_version": periods.AUTHOR_PERIOD_SCHEMA_VERSION,
        "author_periods_digest": periods.author_periods_digest(),
        "kb_schema_version": manifest.get("schema_version") or "",
        "kb_builder_version": manifest.get("builder_version") or "",
        "kb_generated_at": manifest.get("generated_at") or "",
        "layer": layer,
        "evidence_count": expected_evidence_count(manifest, kb_dir, layer),
    }


def read_index_manifest(path: Path) -> dict | None:
    if not path.exists():
        return None
    return read_json(path)


def read_sqlite_metadata(index_path: Path) -> dict | None:
    if not index_path.exists():
        return None

    try:
        with sqlite3.connect(str(index_path)) as con:
            metadata = dict(con.execute("SELECT key, value FROM metadata").fetchall())
            metadata["actual_evidence_count"] = str(con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])
            metadata["actual_term_count"] = str(con.execute("SELECT COUNT(*) FROM term_stats").fetchone()[0])
            return metadata
    except sqlite3.Error as exc:
        raise SemanticSearchError(f"cannot read SQLite index metadata: {exc}") from exc


def compare_values(label: str, expected: object, actual: object, messages: list[str]) -> None:
    if str(expected) != str(actual):
        messages.append(f"{label} differs: KB/current={expected!r}, index={actual!r}")


def compare_embedded_dataset_version(
    manifest: dict, sqlite_metadata: dict, messages: list[str]
) -> None:
    manifest_version = manifest.get("dataset_version")
    sqlite_version = sqlite_metadata.get("dataset_version")
    if not manifest_version:
        messages.append("manifest missing dataset_version")
    if not sqlite_version:
        messages.append("SQLite metadata missing dataset_version")
    if manifest_version and sqlite_version and manifest_version != sqlite_version:
        messages.append(
            "dataset_version differs: "
            f"manifest={manifest_version!r}, SQLite={sqlite_version!r}"
        )


def check_index_sync(
    *,
    kb_dir: Path = DEFAULT_KB_DIR,
    index_path: Path = DEFAULT_INDEX_PATH,
    index_manifest_path: Path = DEFAULT_INDEX_MANIFEST_PATH,
    layer: str = "primary",
) -> SyncReport:
    snapshot = kb_snapshot(kb_dir, layer)
    manifest = read_index_manifest(index_manifest_path)
    sqlite_metadata = read_sqlite_metadata(index_path)
    messages: list[str] = []

    if manifest is None:
        messages.append(f"missing index manifest: {index_manifest_path}")
    else:
        for key in (
            "semantic_index_schema_version",
            "morphology_schema_version",
            "morphology_config_digest",
            "author_period_schema_version",
            "author_periods_digest",
            "kb_schema_version",
            "kb_builder_version",
            "kb_generated_at",
            "layer",
            "evidence_count",
        ):
            compare_values(key, snapshot[key], manifest.get(key), messages)

    if sqlite_metadata is None:
        messages.append(f"missing SQLite index: {index_path}")
    else:
        for key in (
            "semantic_index_schema_version",
            "morphology_schema_version",
            "morphology_config_digest",
            "author_period_schema_version",
            "author_periods_digest",
            "kb_schema_version",
            "kb_builder_version",
            "kb_generated_at",
            "layer",
            "evidence_count",
        ):
            compare_values(f"SQLite {key}", snapshot[key], sqlite_metadata.get(key), messages)
        compare_values(
            "SQLite actual evidence row count",
            sqlite_metadata.get("evidence_count"),
            sqlite_metadata.get("actual_evidence_count"),
            messages,
        )

    if manifest is not None and sqlite_metadata is not None:
        compare_embedded_dataset_version(manifest, sqlite_metadata, messages)
        for key in (
            "semantic_index_schema_version",
            "morphology_schema_version",
            "morphology_config_digest",
            "author_period_schema_version",
            "author_periods_digest",
            "kb_schema_version",
            "kb_builder_version",
            "kb_generated_at",
            "layer",
            "evidence_count",
            "term_count",
        ):
            compare_values(f"manifest vs SQLite {key}", manifest.get(key), sqlite_metadata.get(key), messages)

    return SyncReport(
        synced=not messages,
        messages=messages,
        kb_snapshot=snapshot,
        index_manifest=manifest,
        sqlite_metadata=sqlite_metadata,
    )


def print_report(report: SyncReport) -> None:
    if report.synced:
        print("OK: SQLite index is synced with the knowledge base.")
    else:
        print("Out of sync: SQLite index does not match the current knowledge base.")
        for message in report.messages:
            print(f"- {message}")

    print(
        "Current KB: "
        f"schema={report.kb_snapshot['kb_schema_version']}, "
        f"builder={report.kb_snapshot['kb_builder_version']}, "
        f"generated_at={report.kb_snapshot['kb_generated_at']}, "
        f"layer={report.kb_snapshot['layer']}, "
        f"evidence_count={report.kb_snapshot['evidence_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check whether Theologia Search SQLite index is synced with the KB.")
    parser.add_argument("--kb-dir", type=Path, default=DEFAULT_KB_DIR, help="Path to knowledge_base.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH, help="SQLite index path.")
    parser.add_argument(
        "--index-manifest",
        type=Path,
        default=DEFAULT_INDEX_MANIFEST_PATH,
        help="Generated index manifest path.",
    )
    parser.add_argument(
        "--layer",
        choices=["primary", "extended", "archival", "all"],
        default="primary",
        help="Evidence layer expected in the index. Default: primary.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Rebuild the SQLite index when it is missing or out of sync.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        report = check_index_sync(
            kb_dir=args.kb_dir,
            index_path=args.index,
            index_manifest_path=args.index_manifest,
            layer=args.layer,
        )
        print_report(report)
        if report.synced:
            return 0
        if not args.sync:
            print("Run with --sync to rebuild the index.")
            return 1

        print("Sync requested: rebuilding SQLite index...")
        manifest = build_semantic_index(
            kb_dir=args.kb_dir,
            index_path=args.index,
            index_manifest_path=args.index_manifest,
            layer=args.layer,
        )
        print(
            "Rebuilt SQLite index: "
            f"{args.index} ({manifest['evidence_count']} evidence rows, "
            f"{manifest['term_count']} indexed terms, layer={manifest['layer']})"
        )
        final_report = check_index_sync(
            kb_dir=args.kb_dir,
            index_path=args.index,
            index_manifest_path=args.index_manifest,
            layer=args.layer,
        )
        print_report(final_report)
        return 0 if final_report.synced else 1
    except SemanticSearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
