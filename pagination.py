"""Optional pagination extension: retrieval, display, and metadata-only migration.

This module uses only the standard library and is bundled with the desktop app.
Legacy indexes remain readable; legacy mixed printed-page values are not used
as verified labels. The core evidence/index schema versions do not change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

SCHEMA_VERSION = "1.0.0"
DISPLAY_LABELS = {
    "pdf_page_number": {
        "singular": "PDF file page", "plural": "PDF file pages",
        "description": "The 1-based page position used to navigate the PDF file, including covers and front matter.",
    },
    "pdf_edition_page_number": {
        "singular": "Header/footer page", "plural": "Header/footer pages",
        "description": "The page number printed in the header or footer of the PDF page.",
    },
    "original_book_page_numbers": {
        "singular": "Printed book reference", "plural": "Printed book references",
        "description": "The original printed book page number shown in the PDF margin; it may not pinpoint every quoted word.",
    },
}


def evidence_pages(row):
    if row.get("source_format", "pdf") != "pdf":
        return []
    spans = row.get("source_spans")
    if spans is None:
        spans = json.loads(row.get("source_spans_json") or "[]")
    pages = list(dict.fromkeys(s["page_number"] for s in spans if isinstance(s.get("page_number"), int)))
    if not pages:
        start = row.get("page_start") or row.get("page_number")
        end = row.get("page_end") or start
        if isinstance(start, int) and isinstance(end, int) and 0 < start <= end:
            pages = list(range(start, end + 1))
    return pages


def unavailable_location(source_id, page):
    return {"source_id": source_id, "source_format": "pdf", "pdf_page_number": page,
            "pdf_edition_page_number": None, "pdf_edition_status": "unavailable",
            "original_book_page_numbers": [], "original_book_status": "unavailable", "observations": []}


def attach_page_locations(con, rows):
    """Hydrate final results/context, without participating in search or scoring."""
    if not rows:
        return rows
    # Fetch source spans even when result packaging intentionally omitted them.
    ids = list(dict.fromkeys(row["evidence_id"] for row in rows if row.get("evidence_id")))
    metadata = {}
    for start in range(0, len(ids), 400):
        batch = ids[start:start + 400]
        for record in con.execute(
                "SELECT evidence_id, source_id, page_start, page_end, source_spans_json, "
                "printed_page_number, printed_page_numbers_json FROM evidence WHERE evidence_id IN ("
                + ",".join("?" for _ in batch) + ")", batch):
            item = dict(record)
            metadata[item["evidence_id"]] = item
    has_extension = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='page_locations'").fetchone()
    needed = defaultdict(set)
    for row in rows:
        meta = metadata.get(row.get("evidence_id"), row)
        row.setdefault("page_start", meta.get("page_start"))
        row.setdefault("page_end", meta.get("page_end"))
        row["printed_page_number"] = meta.get("printed_page_number")
        row["printed_page_numbers"] = json.loads(meta.get("printed_page_numbers_json") or "[]")
        needed[row.get("source_id")].update(evidence_pages(meta))
    locations = {}
    if has_extension:
        for source, pages in needed.items():
            ordered = sorted(pages)
            for start in range(0, len(ordered), 400):
                batch = ordered[start:start + 400]
                for record in con.execute(
                        "SELECT pdf_page_number, location_json FROM page_locations WHERE source_id=? AND pdf_page_number IN ("
                        + ",".join("?" for _ in batch) + ")", [source, *batch]):
                    locations[(source, record[0])] = json.loads(record[1])
    for row in rows:
        meta = metadata.get(row.get("evidence_id"), row)
        source = row.get("source_id")
        row["page_locations"] = [locations.get((source, p), unavailable_location(source, p))
                                 for p in evidence_pages(meta)]
    return rows


def compact_labels(labels):
    """Compress only a complete, consecutive Arabic sequence; retain resets/Romans."""
    labels = [str(label) for label in labels]
    if len(labels) > 1 and all(label.isdecimal() and str(int(label)) == label for label in labels):
        numbers = list(map(int, labels))
        if numbers == list(range(numbers[0], numbers[0] + len(numbers))):
            return f"{labels[0]}–{labels[-1]}"
    return ", ".join(labels)


def format_page_locations(row):
    locations = row.get("page_locations") or []
    pages = [item["pdf_page_number"] for item in locations] or evidence_pages(row)
    page_label = DISPLAY_LABELS["pdf_page_number"]["plural" if len(pages) > 1 else "singular"]
    parts = [f"{page_label}: {compact_labels(pages) or 'unavailable'}"]
    for key, status_key in [
        ("pdf_edition_page_number", "pdf_edition_status"),
        ("original_book_page_numbers", "original_book_status"),
    ]:
        values, statuses = [], []
        for item in locations:
            statuses.append(item.get(status_key, "unavailable"))
            if item.get(status_key) != "verified":
                continue
            raw = item.get(key)
            values.extend(raw if isinstance(raw, list) else ([raw] if raw else []))
        label = DISPLAY_LABELS[key]["plural" if max(len(values), len(locations)) > 1 else "singular"]
        if values:
            text = compact_labels(values)
            if any(s != "verified" for s in statuses):
                text = ", ".join(map(str, values)) + " (incomplete)"
            parts.append(f"{label}: {text}")
        else:
            status = "unresolved" if "unresolved" in statuses else (
                "not marked" if statuses and all(s == "not_marked" for s in statuses) else "unavailable")
            parts.append(f"{label}: {status}")
    return " · ".join(parts)


def read_location_rows(kb_dir, manifest):
    extension = manifest.get("pagination")
    if not extension:
        return
    if extension.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported pagination extension schema")
    paths = manifest.get("files", {}).get("page_locations", [])
    if len(paths) != 1:
        raise ValueError("Pagination extension requires one registered JSONL file")
    path = Path(kb_dir) / paths[0]
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != extension["sha256"]:
        raise ValueError("Pagination file digest mismatch")
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                if extension["source_fingerprints"].get(row["source_id"]) != row["pdf_sha256"]:
                    raise ValueError("Pagination source fingerprint mismatch")
                if not isinstance(row["pdf_page_number"], int) or row["pdf_page_number"] < 1:
                    raise ValueError("Invalid PDF file page number")
                yield row


def install_display_labels(con, extension):
    labels = extension.get("display_labels", DISPLAY_LABELS)
    con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)", (
        "pagination_display_labels", json.dumps(labels, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))


def install_page_locations(con, kb_dir, manifest):
    """Transactionally install ONLY the optional pagination table/metadata."""
    extension = manifest.get("pagination")
    if not extension:
        return
    con.execute("SAVEPOINT pagination_extension")
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS page_locations (
            source_id TEXT NOT NULL, pdf_page_number INTEGER NOT NULL,
            location_json TEXT NOT NULL, PRIMARY KEY(source_id, pdf_page_number)
        ) WITHOUT ROWID""")
        con.execute("DELETE FROM page_locations")
        count = 0
        for row in read_location_rows(kb_dir, manifest):
            con.execute("INSERT INTO page_locations VALUES (?, ?, ?)",
                        (row["source_id"], row["pdf_page_number"], json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
            count += 1
        if count != extension["page_count"]:
            raise ValueError("Pagination page count mismatch")
        con.executemany("INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)", [
            ("pagination_schema_version", extension["schema_version"]),
            ("pagination_sha256", extension["sha256"]),
            ("pagination_page_count", str(count)),
        ])
        install_display_labels(con, extension)
        con.execute("RELEASE pagination_extension")
    except Exception:
        con.execute("ROLLBACK TO pagination_extension")
        con.execute("RELEASE pagination_extension")
        raise


def migrate_index(kb_dir, index_path, manifest_path, backup_dir=None, *, labels_only=False):
    """Never builds/rebuilds an index. Refuse a missing or incompatible baseline."""
    kb_dir, index_path, manifest_path = map(Path, (kb_dir, index_path, manifest_path))
    kb = json.loads((kb_dir / "christian_kb_manifest.json").read_text(encoding="utf-8"))
    index_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not index_path.exists() or not kb.get("pagination"):
        raise ValueError("Existing SQLite index and KB pagination extension required")
    with closing(sqlite3.connect(index_path.resolve().as_uri() + "?mode=rw", uri=True)) as con:
        meta = dict(con.execute("SELECT key,value FROM metadata"))
        for key in ("schema_version", "builder_version", "generated_at"):
            if str(kb[key]) != meta.get("kb_" + key) or str(kb[key]) != str(index_manifest.get("kb_" + key)):
                raise ValueError("Core KB/index mismatch; pagination migration will not rebuild: " + key)
        layer = meta.get("layer")
        count_keys = {"primary": "evidence_primary", "extended": "evidence_extended", "archival": "evidence_archival"}
        expected_count = (sum(kb.get("counts", {}).get(k, 0) for k in count_keys.values())
                          if layer == "all" else kb.get("counts", {}).get(count_keys.get(layer)))
        actual_count = con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        if (expected_count is not None and actual_count != expected_count
                or str(actual_count) != meta.get("evidence_count")
                or actual_count != index_manifest.get("evidence_count")
                or index_manifest.get("dataset_version") != meta.get("dataset_version")):
            raise ValueError("Core index count/version mismatch; pagination migration will not rebuild")
        expected = kb["pagination"]
        installed = con.execute("SELECT 1 FROM sqlite_master WHERE name='page_locations' AND type='table'").fetchone()
        data_current = (meta.get("pagination_sha256") == expected["sha256"] and installed
                        and meta.get("pagination_schema_version") == expected["schema_version"]
                        and meta.get("pagination_page_count") == str(expected["page_count"])
                        and con.execute("SELECT COUNT(*) FROM page_locations").fetchone()[0] == expected["page_count"])
        labels_current = json.loads(meta.get("pagination_display_labels") or "null") == expected.get("display_labels", DISPLAY_LABELS)
        if data_current and labels_current and index_manifest.get("pagination") == expected:
            print("Pagination already current; no database changes.")
            return
        if labels_only and not data_current:
            raise ValueError("Label-only refresh requires current pagination data; no pagination rows will be rewritten")
        backup_dir = Path(backup_dir) if backup_dir else index_path.parent / "pagination_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / index_path.name
        if backup.resolve() == index_path.resolve():
            raise ValueError("Backup directory must differ from index directory")
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as dst:
                con.backup(dst, pages=8192)
        backup_manifest = backup_dir / manifest_path.name
        if not backup_manifest.exists():
            shutil.copy2(manifest_path, backup_manifest)
        con.execute("BEGIN IMMEDIATE")
        if data_current:
            install_display_labels(con, expected)
        else:
            install_page_locations(con, kb_dir, kb)
        con.commit()
    index_manifest["pagination"] = kb["pagination"]
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(index_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    if data_current:
        print("Updated pagination label descriptions only; pagination rows, evidence, and FTS tables untouched.")
    else:
        print(f"Added pagination for {expected['page_count']} PDF pages; evidence and FTS tables untouched.")


def main():
    parser = argparse.ArgumentParser(description="Add pagination metadata to an existing index without rebuilding it.")
    root = Path(__file__).resolve().parent
    parser.add_argument("--kb-dir", type=Path, default=root.parent / "knowledge_base")
    parser.add_argument("--index", type=Path, default=root / "generated/semantic_index.sqlite")
    parser.add_argument("--index-manifest", type=Path, default=root / "generated/index_manifest.json")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--labels-only", action="store_true", help="Refresh label descriptions only; refuse pagination-row rewrites.")
    args = parser.parse_args()
    try:
        migrate_index(args.kb_dir, args.index, args.index_manifest, args.backup_dir, labels_only=args.labels_only)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"Pagination migration stopped: {exc}\n")


if __name__ == "__main__":
    main()
