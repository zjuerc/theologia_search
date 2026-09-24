"""Validate a prepared PyInstaller payload before Inno Setup runs."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    payload = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist/TheologiaSearch")
    resources = payload / "_internal" if (payload / "_internal").is_dir() else payload
    required = [
        payload / "TheologiaSearch.exe",
        resources / "README.txt",
        resources / "assets" / "png",
        resources / "assets" / "fonts",
        resources / "license" / "LICENSE.txt",
        resources / "license" / "THIRD-PARTY-NOTICES.txt",
        resources / "license" / "OFL-Cinzel.txt",
        resources / "license" / "OFL-EBGaramond.txt",
        resources / "license" / "CCEL-Copyright-Policy.txt",
        resources / "generated" / "semantic_index.sqlite",
        resources / "generated" / "index_manifest.json",
        resources / "sqlite3.dll",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("Missing packaged files:")
        print("\n".join(missing))
        return 1
    obsolete_resources = [
        resources / "concept_query_lexicon.json",
        resources / "morphology_terms.json",
        resources / "author_periods.json",
    ]
    present_obsolete = [str(path) for path in obsolete_resources if path.exists()]
    if present_obsolete:
        print("Obsolete packaged resources remain:")
        print("\n".join(present_obsolete))
        return 1
    forbidden_names = {
        "morphology.py",
        "morphology_terms.json",
        "concept_query_lexicon.json",
        "author_periods.json",
    }
    packaged_forbidden = sorted(
        str(path.relative_to(payload))
        for path in payload.rglob("*")
        if path.is_file() and path.name in forbidden_names
    )
    if packaged_forbidden:
        print("Obsolete packaged files remain:")
        print("\n".join(packaged_forbidden))
        return 1

    manifest = json.loads((resources / "generated" / "index_manifest.json").read_text(encoding="utf-8"))
    with sqlite3.connect(resources / "generated" / "semantic_index.sqlite") as con:
        metadata = dict(con.execute("SELECT key, value FROM metadata").fetchall())
        evidence_count = con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        source_count = con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        author_count = con.execute("SELECT COUNT(*) FROM author_periods").fetchone()[0]
        con.execute("SELECT author_norm FROM evidence_mentioned_authors LIMIT 1").fetchone()
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        con.execute("SELECT evidence_id FROM evidence LIMIT 1").fetchone()
    manifest_version = manifest.get("dataset_version")
    sqlite_version = metadata.get("dataset_version")
    if not manifest_version:
        print("Manifest missing dataset_version")
        return 1
    if not sqlite_version:
        print("SQLite metadata missing dataset_version")
        return 1
    if manifest_version != sqlite_version:
        print(
            "Dataset version mismatch: "
            f"manifest={manifest_version!r}, SQLite={sqlite_version!r}"
        )
        return 1
    forbidden_tables = {"morphology_forms", "evidence_morphology", "morphology_stats"}
    if tables & forbidden_tables:
        print(f"Obsolete morphology tables remain: {sorted(tables & forbidden_tables)}")
        return 1
    expected = {
        "evidence_count": evidence_count,
        "author_period_count": author_count,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            print(f"Manifest mismatch for {key}: {manifest.get(key)!r} != {value!r}")
            return 1
    print(
        f"Package verified: dataset {manifest_version}, {author_count} authors, "
        f"{source_count} volumes, {evidence_count} evidence records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
