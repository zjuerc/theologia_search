"""Deterministic historical-period assignment for indexed evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

try:
    from .common import display_text, norm_lookup
except ImportError:  # pragma: no cover - supports direct script execution.
    from common import display_text, norm_lookup


AUTHOR_PERIOD_SCHEMA_VERSION = "1.0.0"
DEFAULT_AUTHOR_PERIODS_PATH = Path(__file__).resolve().with_name("author_periods.json")

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


def load_author_periods(path: Path = DEFAULT_AUTHOR_PERIODS_PATH) -> dict:
    if not path.exists():
        return {"schema_version": AUTHOR_PERIOD_SCHEMA_VERSION, "authors": []}
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def registered_author_names(config: dict | None = None, path: Path = DEFAULT_AUTHOR_PERIODS_PATH) -> tuple[str, ...]:
    """Return the curated author names available to metadata search controls."""
    data = config if config is not None else load_author_periods(path)
    names = {
        display_text(row.get("author"))
        for row in data.get("authors", [])
        if display_text(row.get("author"))
    }
    return tuple(sorted(names, key=str.casefold))


def author_periods_digest(config: dict | None = None, path: Path = DEFAULT_AUTHOR_PERIODS_PATH) -> str:
    data = config if config is not None else load_author_periods(path)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def period_for_year(year: int | None) -> str:
    if year is None:
        return UNCLASSIFIED
    if year <= 325:
        return PRE_NICENE
    if year < 1517:
        return NICENE_TO_REFORMATION
    return POST_REFORMATION


def build_author_lookup(config: dict) -> dict[str, dict]:
    lookup = {}
    for row in config.get("authors", []):
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


def assign_period(author: str | None, collection: str | None, config: dict) -> PeriodAssignment:
    row = build_author_lookup(config).get(norm_lookup(author))
    if row:
        basis_year = row.get("active_year") or row.get("death_year") or row.get("birth_year")
        period_id = row.get("period_id") or period_for_year(basis_year)
        return PeriodAssignment(
            period_id=period_id,
            period_label=PERIOD_LABELS.get(period_id, period_id),
            basis_year=basis_year,
            source="author_periods",
            confidence=display_text(row.get("confidence") or "medium"),
            notes=display_text(row.get("notes")),
        )
    return fallback_assignment(collection)
