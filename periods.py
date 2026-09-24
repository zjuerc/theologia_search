"""Deterministic historical-period assignment for indexed evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

try:
    from .common import display_text, norm_lookup
except ImportError:  # pragma: no cover - supports direct script execution.
    from common import display_text, norm_lookup


AUTHOR_PERIOD_SCHEMA_VERSION = "1.0.0"

PRE_NICENE = "before_nicene"
NICENE_TO_REFORMATION = "nicene_to_reformation"
POST_REFORMATION = "post_reformation"
UNCLASSIFIED = "unclassified"

PERIOD_LABELS = {
    PRE_NICENE: "Before Council of Nicaea (up to 325 AD)",
    NICENE_TO_REFORMATION: "After Council of Nicaea, before Reformation (326-1516 AD)",
    POST_REFORMATION: "After Reformation (1517 AD and later)",
    UNCLASSIFIED: "Unclassified",
}

ORDERED_PERIODS = [PRE_NICENE, NICENE_TO_REFORMATION, POST_REFORMATION, UNCLASSIFIED]


@dataclass(frozen=True)
class PeriodAssignment:
    period_id: str
    period_label: str
    basis_year: int | None
    source: str
    confidence: str
    notes: str


AUTHOR_PERIOD_COLUMNS = (
    "author_norm", "author", "birth_year", "death_year", "active_year",
    "period_id", "period_label", "confidence", "notes", "source_urls_json",
)


def read_author_period_rows(index_path) -> list[dict]:
    """Read the author-period source from an existing SQLite index."""
    if not index_path or not index_path.exists():
        return []
    con = None
    try:
        con = sqlite3.connect(str(index_path))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT " + ", ".join(AUTHOR_PERIOD_COLUMNS) + " FROM author_periods"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        if con is not None:
            con.close()
    return [dict(row) for row in rows]


def author_periods_digest(rows: list[dict] | tuple[dict, ...] | None = None) -> str:
    normalized = []
    for row in rows or []:
        normalized.append({column: row.get(column) for column in AUTHOR_PERIOD_COLUMNS})
    normalized.sort(key=lambda row: (row.get("author_norm") or "", row.get("author") or ""))
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def period_for_year(year: int | None) -> str:
    if year is None:
        return UNCLASSIFIED
    if year <= 325:
        return PRE_NICENE
    if year < 1517:
        return NICENE_TO_REFORMATION
    return POST_REFORMATION


def build_author_lookup(rows: list[dict] | tuple[dict, ...]) -> dict[str, dict]:
    lookup = {}
    for row in rows:
        name = norm_lookup(row.get("author"))
        if name:
            lookup[name] = row
        normalized = norm_lookup(row.get("author_norm"))
        if normalized:
            lookup[normalized] = row
    return lookup


def fallback_assignment(collection: str | None) -> PeriodAssignment:
    collection_text = display_text(collection)
    if collection_text == "Ante-Nicene Fathers":
        period_id = PRE_NICENE
        return PeriodAssignment(period_id, PERIOD_LABELS[period_id], None, "collection_fallback", "medium", collection_text)
    if collection_text == "Nicene and Post-Nicene Fathers":
        period_id = NICENE_TO_REFORMATION
        return PeriodAssignment(period_id, PERIOD_LABELS[period_id], None, "collection_fallback", "medium", collection_text)
    return PeriodAssignment(UNCLASSIFIED, PERIOD_LABELS[UNCLASSIFIED], None, "unclassified", "low", collection_text)


def assign_period(author: str | None, collection: str | None, lookup: dict[str, dict] | None = None) -> PeriodAssignment:
    row = (lookup or {}).get(norm_lookup(author))
    if row:
        basis_year = row.get("active_year") or row.get("death_year") or row.get("birth_year")
        period_id = row.get("period_id") or period_for_year(basis_year)
        return PeriodAssignment(
            period_id=period_id,
            period_label=PERIOD_LABELS.get(period_id, period_id),
            basis_year=basis_year,
            source="author_periods_sqlite",
            confidence=display_text(row.get("confidence") or "medium"),
            notes=display_text(row.get("notes")),
        )
    return fallback_assignment(collection)
