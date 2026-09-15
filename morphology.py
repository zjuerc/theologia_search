"""Deterministic morphology and theological term-family helpers."""

from __future__ import annotations

import json
import re
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from .common import display_text, norm_lookup, singular_candidates, token_list
except ImportError:  # pragma: no cover - supports direct script execution.
    from common import display_text, norm_lookup, singular_candidates, token_list


MORPHOLOGY_SCHEMA_VERSION = "1.0.0"
DEFAULT_MORPHOLOGY_PATH = Path(__file__).resolve().with_name("morphology_terms.json")


@dataclass(frozen=True)
class MorphForm:
    form: str
    canonical: str
    family_id: str
    family_label: str
    kind: str
    weight: float
    source: str


@dataclass(frozen=True)
class MorphMatch:
    form: str
    canonical: str
    family_id: str
    family_label: str
    kind: str
    weight: float
    source: str
    count: int


@lru_cache(maxsize=4)
def load_morphology(path: Path = DEFAULT_MORPHOLOGY_PATH) -> dict:
    if not path.exists():
        return {"schema_version": MORPHOLOGY_SCHEMA_VERSION, "lemmas": [], "families": []}
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def morphology_digest(config: dict | None = None, path: Path = DEFAULT_MORPHOLOGY_PATH) -> str:
    data = config if config is not None else load_morphology(path)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_morphology_config(config: dict) -> list[str]:
    errors: list[str] = []
    lemma_forms: dict[str, str] = {}
    family_ids: set[str] = set()

    for index, entry in enumerate(config.get("lemmas", []), 1):
        canonical = norm_lookup(entry.get("canonical"))
        if not canonical:
            errors.append(f"lemma {index}: canonical term is required")
            continue
        try:
            float(entry.get("weight", 1.0))
        except (TypeError, ValueError):
            errors.append(f"lemma {canonical}: weight must be a number")
        forms = [norm_lookup(form) for form in entry.get("forms", []) if norm_lookup(form)]
        if not forms:
            errors.append(f"lemma {canonical}: at least one form is required")
        for form in forms:
            owner = lemma_forms.get(form)
            if owner and owner != canonical:
                errors.append(f"form {form!r} is assigned to both {owner!r} and {canonical!r}")
            lemma_forms[form] = canonical

    for index, entry in enumerate(config.get("families", []), 1):
        family_id = norm_lookup(entry.get("family_id") or "").replace(" ", "_")
        label = display_text(entry.get("label"))
        if not family_id:
            errors.append(f"family {index}: family_id is required")
            continue
        if family_id in family_ids:
            errors.append(f"family {family_id}: duplicate family_id")
        family_ids.add(family_id)
        if not label:
            errors.append(f"family {family_id}: label is required")
        try:
            float(entry.get("weight", 0.75))
        except (TypeError, ValueError):
            errors.append(f"family {family_id}: weight must be a number")
        canonical_terms = [norm_lookup(term) for term in entry.get("canonical_terms", []) if norm_lookup(term)]
        if len(canonical_terms) < 2:
            errors.append(f"family {family_id}: at least two canonical terms are required")
        form_map = entry.get("forms", {})
        if not isinstance(form_map, dict):
            errors.append(f"family {family_id}: forms must be a term-to-forms object")
            continue
        for term in canonical_terms:
            forms = [norm_lookup(form) for form in form_map.get(term, []) if norm_lookup(form)]
            if not forms:
                errors.append(f"family {family_id}: canonical term {term!r} needs at least one form")
    return errors


def save_morphology(config: dict, path: Path = DEFAULT_MORPHOLOGY_PATH) -> None:
    errors = validate_morphology_config(config)
    if errors:
        raise ValueError("; ".join(errors))
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ordered_add(items: list[str], value: str) -> None:
    normalized = norm_lookup(value)
    if normalized and normalized not in items:
        items.append(normalized)


def mechanical_forms(token: str) -> list[str]:
    normalized = norm_lookup(token)
    forms: list[str] = []
    if not normalized:
        return forms
    _ordered_add(forms, normalized)
    for singular in singular_candidates(normalized):
        _ordered_add(forms, singular)
    if normalized.endswith("y") and len(normalized) > 2:
        _ordered_add(forms, normalized[:-1] + "ies")
    elif normalized.endswith("s") and not normalized.endswith("ss"):
        pass
    else:
        _ordered_add(forms, normalized + "s")
    return forms


def build_form_catalog(config: dict) -> dict[str, list[MorphForm]]:
    forms: dict[str, list[MorphForm]] = defaultdict(list)

    for entry in config.get("lemmas", []):
        canonical = norm_lookup(entry.get("canonical"))
        if not canonical:
            continue
        family_id = norm_lookup(entry.get("family_id") or canonical).replace(" ", "_")
        family_label = display_text(entry.get("family_label") or canonical)
        source = display_text(entry.get("source") or "curated")
        weight = float(entry.get("weight", 1.0))
        entry_forms: list[str] = []
        for form in entry.get("forms", []):
            _ordered_add(entry_forms, form)
        if entry.get("include_mechanical", True):
            for token in token_list(canonical):
                for form in mechanical_forms(token):
                    _ordered_add(entry_forms, form)
        for form in entry_forms:
            forms[form].append(
                MorphForm(
                    form=form,
                    canonical=canonical,
                    family_id=family_id,
                    family_label=family_label,
                    kind="lemma",
                    weight=weight,
                    source=source,
                )
            )

    for entry in config.get("families", []):
        family_id = norm_lookup(entry.get("family_id") or entry.get("label")).replace(" ", "_")
        family_label = display_text(entry.get("label") or family_id.replace("_", " "))
        source = display_text(entry.get("source") or "curated")
        weight = float(entry.get("weight", 0.75))
        canonical_terms = [norm_lookup(term) for term in entry.get("canonical_terms", []) if norm_lookup(term)]
        for term in canonical_terms:
            entry_forms = []
            _ordered_add(entry_forms, term)
            for form in entry.get("forms", {}).get(term, []):
                _ordered_add(entry_forms, form)
            for token in token_list(term):
                for form in mechanical_forms(token):
                    _ordered_add(entry_forms, form)
            for form in entry_forms:
                forms[form].append(
                    MorphForm(
                        form=form,
                        canonical=term,
                        family_id=family_id,
                        family_label=family_label,
                        kind="family",
                        weight=weight,
                        source=source,
                    )
                )
    return forms


def phrase_count(text_norm: str, phrase: str) -> int:
    if not text_norm or not phrase:
        return 0
    pattern = re.escape(phrase).replace(r"\ ", r"[\s\-]+")
    return len(re.findall(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text_norm))


def match_text(text: str, catalog: dict[str, list[MorphForm]]) -> list[MorphMatch]:
    tokens = token_list(text)
    if not tokens:
        return []
    form_tokens_by_form = {form: tuple(token_list(form)) for form in catalog}
    token_counts = Counter(tokens)
    phrase_counts: Counter[tuple[str, ...]] = Counter()
    multi_lengths = sorted({len(value) for value in form_tokens_by_form.values() if len(value) > 1})
    for size in multi_lengths:
        if len(tokens) < size:
            continue
        for index in range(0, len(tokens) - size + 1):
            phrase_counts[tuple(tokens[index : index + size])] += 1
    matches: list[MorphMatch] = []
    for form, form_values in catalog.items():
        form_tokens = form_tokens_by_form[form]
        if len(form_tokens) == 1:
            count = token_counts.get(form_tokens[0], 0)
        else:
            count = phrase_counts.get(form_tokens, 0)
        if count:
            for values in form_values:
                matches.append(
                    MorphMatch(
                        form=form,
                        canonical=values.canonical,
                        family_id=values.family_id,
                        family_label=values.family_label,
                        kind=values.kind,
                        weight=values.weight,
                        source=values.source,
                        count=count,
                    )
                )
    return matches


def query_matches(concept: str, config: dict) -> list[MorphMatch]:
    return match_text(concept, build_form_catalog(config))


def summarize_matches(matches: list[MorphMatch]) -> tuple[list[str], list[str], dict[str, list[str]]]:
    lemmas: list[str] = []
    families: list[str] = []
    forms_by_canonical: dict[str, list[str]] = defaultdict(list)
    for match in matches:
        if match.kind == "lemma":
            _ordered_add(lemmas, match.canonical)
        else:
            label = match.family_label or match.family_id.replace("_", " ")
            if label not in families:
                families.append(label)
        if match.form != match.canonical and match.form not in forms_by_canonical[match.canonical]:
            forms_by_canonical[match.canonical].append(match.form)
    return lemmas, families, dict(forms_by_canonical)


def aggregate_counts(matches: list[MorphMatch]) -> Counter[tuple[str, str, str]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for match in matches:
        counts[(match.canonical, match.family_id, match.form)] += match.count
    return counts
