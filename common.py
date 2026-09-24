#!/usr/bin/env python3
"""Shared helpers for Theologia Search."""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable


SEMANTIC_DIR = Path(__file__).resolve().parent
# PyInstaller onedir keeps bundled resources beside the executable.  The
# _MEIPASS fallback also keeps this correct for future one-file experiments.
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", SEMANTIC_DIR))
WORKSPACE_ROOT = SEMANTIC_DIR.parent
DEFAULT_KB_DIR = WORKSPACE_ROOT / "knowledge_base"
GENERATED_DIR = RESOURCE_DIR / "generated"
REVIEW_DIR = RESOURCE_DIR / "review"
EVALUATION_DIR = RESOURCE_DIR / "evaluation"
DEFAULT_INDEX_PATH = GENERATED_DIR / "semantic_index.sqlite"
DEFAULT_INDEX_MANIFEST_PATH = GENERATED_DIR / "index_manifest.json"
DEFAULT_DISCOVERY_JSONL_PATH = REVIEW_DIR / "term_discovery_candidates.jsonl"
DEFAULT_DISCOVERY_CSV_PATH = REVIEW_DIR / "term_discovery_candidates.csv"
DEFAULT_EVALUATION_QUERIES_PATH = EVALUATION_DIR / "queries.jsonl"
DEFAULT_EVALUATION_REPORT_JSON_PATH = GENERATED_DIR / "evaluation_report.json"
DEFAULT_EVALUATION_REPORT_MD_PATH = GENERATED_DIR / "evaluation_report.md"
DEFAULT_NEIGHBORHOODS_PATH = GENERATED_DIR / "concept_neighborhoods.jsonl"
DEFAULT_CLUSTERS_PATH = GENERATED_DIR / "concept_clusters.jsonl"

if sys.platform == "win32":
    _LOCAL_DATA_ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
else:
    _LOCAL_DATA_ROOT = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
USER_DATA_DIR = _LOCAL_DATA_ROOT / "Theologia Search"
DEFAULT_GUI_HISTORY_PATH = USER_DATA_DIR / "gui_search_history.json"

EVIDENCE_KEYS = {
    "primary": "core_primary_evidence",
    "extended": "extended_evidence",
    "archival": "archival_evidence",
}

DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "between",
    "by",
    "for",
    "from",
    "he",
    "her",
    "him",
    "his",
    "how",
    "i",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "our",
    "she",
    "that",
    "the",
    "their",
    "them",
    "these",
    "this",
    "those",
    "to",
    "was",
    "were",
    "what",
    "which",
    "who",
    "with",
}


class SemanticSearchError(RuntimeError):
    """Raised when the semantic layer cannot read or build required inputs."""


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass


def die(message: str, exit_code: int = 2) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise SemanticSearchError(f"{path}:{line_number}: invalid JSON: {exc}") from exc


def read_json(path: Path) -> dict:
    if not path.exists():
        raise SemanticSearchError(f"missing required file: {path}")
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def norm_text(value: str | None) -> str:
    if value is None:
        return ""
    value = value.strip().strip("\"'")
    value = value.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).casefold()


def norm_lookup(value: str | None) -> str:
    return norm_text(value).replace("\u2018", "'").replace("\u2019", "'").translate(DASH_TRANSLATION)


def norm_source_path(value: str | None) -> str:
    return norm_text(value).replace("\\", "/")


def display_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


def token_list(value: str | None) -> list[str]:
    normalized = norm_lookup(value)
    tokens = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", normalized)
    return [token[:-2] if token.endswith("'s") and len(token) > 2 else token for token in tokens]


def significant_tokens(value: str | None) -> list[str]:
    return [token for token in token_list(value) if token not in STOPWORDS and len(token) > 1]


def ngrams(tokens: list[str], max_n: int = 5) -> Iterable[str]:
    limit = min(max_n, len(tokens))
    for size in range(limit, 0, -1):
        for index in range(0, len(tokens) - size + 1):
            yield " ".join(tokens[index : index + size])


# These families are intentionally kept in this shared module so every caller
# uses the same inflection rules.  The tables are data, not per-call logic;
# adding a common irregular form does not require changes in search.py or
# Mechanical grammatical variants are centralized here so all callers share the
# same query-time behavior.
_IRREGULAR_VERB_FAMILIES = (
    ("be", ("be", "am", "is", "are", "was", "were", "been", "being")),
    ("have", ("have", "has", "had", "having")),
    ("do", ("do", "does", "did", "done", "doing")),
    ("go", ("go", "goes", "went", "gone", "going")),
    ("come", ("come", "comes", "came", "coming")),
    ("become", ("become", "becomes", "became", "becoming")),
    ("begin", ("begin", "begins", "began", "begun", "beginning")),
    ("bring", ("bring", "brings", "brought", "bringing")),
    ("build", ("build", "builds", "built", "building")),
    ("buy", ("buy", "buys", "bought", "buying")),
    ("catch", ("catch", "catches", "caught", "catching")),
    ("choose", ("choose", "chooses", "chose", "chosen", "choosing")),
    ("cling", ("cling", "clings", "clung", "clinging")),
    ("cost", ("cost", "costs", "costing")),
    ("cut", ("cut", "cuts", "cutting")),
    ("deal", ("deal", "deals", "dealt", "dealing")),
    ("dig", ("dig", "digs", "dug", "digging")),
    ("draw", ("draw", "draws", "drew", "drawn", "drawing")),
    ("die", ("die", "dies", "died", "dying")),
    ("drink", ("drink", "drinks", "drank", "drunk", "drinking")),
    ("drive", ("drive", "drives", "drove", "driven", "driving")),
    ("eat", ("eat", "eats", "ate", "eaten", "eating")),
    ("fall", ("fall", "falls", "fell", "fallen", "falling")),
    ("feed", ("feed", "feeds", "fed", "feeding")),
    ("feel", ("feel", "feels", "felt", "feeling")),
    ("fight", ("fight", "fights", "fought", "fighting")),
    ("find", ("find", "finds", "found", "finding")),
    ("flee", ("flee", "flees", "fled", "fleeing")),
    ("fly", ("fly", "flies", "flew", "flown", "flying")),
    ("forbid", ("forbid", "forbids", "forbade", "forbidden", "forbidding")),
    ("forget", ("forget", "forgets", "forgot", "forgotten", "forgetting")),
    ("forgive", ("forgive", "forgives", "forgave", "forgiven", "forgiving")),
    ("freeze", ("freeze", "freezes", "froze", "frozen", "freezing")),
    ("get", ("get", "gets", "got", "gotten", "getting")),
    ("give", ("give", "gives", "gave", "given", "giving")),
    ("grow", ("grow", "grows", "grew", "grown", "growing")),
    ("hang", ("hang", "hangs", "hung", "hanging")),
    ("hear", ("hear", "hears", "heard", "hearing")),
    ("hide", ("hide", "hides", "hid", "hidden", "hiding")),
    ("hold", ("hold", "holds", "held", "holding")),
    ("hurt", ("hurt", "hurts", "hurting")),
    ("keep", ("keep", "keeps", "kept", "keeping")),
    ("know", ("know", "knows", "knew", "known", "knowing")),
    ("lay", ("lay", "lays", "laid", "laying")),
    ("lead", ("lead", "leads", "led", "leading")),
    ("leave", ("leave", "leaves", "left", "leaving")),
    ("lend", ("lend", "lends", "lent", "lending")),
    ("let", ("let", "lets", "letting")),
    ("lie", ("lie", "lies", "lay", "lain", "lying")),
    ("live", ("live", "lives", "lived", "living")),
    ("lose", ("lose", "loses", "lost", "losing")),
    ("make", ("make", "makes", "made", "making")),
    ("mean", ("mean", "means", "meant", "meaning")),
    ("meet", ("meet", "meets", "met", "meeting")),
    ("pay", ("pay", "pays", "paid", "paying")),
    ("put", ("put", "puts", "putting")),
    ("read", ("read", "reads", "reading")),
    ("ride", ("ride", "rides", "rode", "ridden", "riding")),
    ("ring", ("ring", "rings", "rang", "rung", "ringing")),
    ("rise", ("rise", "rises", "rose", "risen", "rising")),
    ("run", ("run", "runs", "ran", "running")),
    ("say", ("say", "says", "said", "saying")),
    ("see", ("see", "sees", "saw", "seen", "seeing")),
    ("sell", ("sell", "sells", "sold", "selling")),
    ("send", ("send", "sends", "sent", "sending")),
    ("set", ("set", "sets", "setting")),
    ("shake", ("shake", "shakes", "shook", "shaken", "shaking")),
    ("shine", ("shine", "shines", "shone", "shining")),
    ("shoot", ("shoot", "shoots", "shot", "shooting")),
    ("show", ("show", "shows", "showed", "shown", "showing")),
    ("shut", ("shut", "shuts", "shutting")),
    ("sing", ("sing", "sings", "sang", "sung", "singing")),
    ("sink", ("sink", "sinks", "sank", "sunk", "sinking")),
    ("sit", ("sit", "sits", "sat", "sitting")),
    ("sleep", ("sleep", "sleeps", "slept", "sleeping")),
    ("speak", ("speak", "speaks", "spoke", "spoken", "speaking")),
    ("spend", ("spend", "spends", "spent", "spending")),
    ("spin", ("spin", "spins", "spun", "spinning")),
    ("split", ("split", "splits", "splitting")),
    ("spread", ("spread", "spreads", "spreading")),
    ("stand", ("stand", "stands", "stood", "standing")),
    ("steal", ("steal", "steals", "stole", "stolen", "stealing")),
    ("stick", ("stick", "sticks", "stuck", "sticking")),
    ("sting", ("sting", "stings", "stung", "stinging")),
    ("strike", ("strike", "strikes", "struck", "stricken", "striking")),
    ("swear", ("swear", "swears", "swore", "sworn", "swearing")),
    ("sweep", ("sweep", "sweeps", "swept", "sweeping")),
    ("swim", ("swim", "swims", "swam", "swum", "swimming")),
    ("swing", ("swing", "swings", "swung", "swinging")),
    ("take", ("take", "takes", "took", "taken", "taking")),
    ("teach", ("teach", "teaches", "taught", "teaching")),
    ("tear", ("tear", "tears", "tore", "torn", "tearing")),
    ("tell", ("tell", "tells", "told", "telling")),
    ("think", ("think", "thinks", "thought", "thinking")),
    ("throw", ("throw", "throws", "threw", "thrown", "throwing")),
    ("understand", ("understand", "understands", "understood", "understanding")),
    ("wake", ("wake", "wakes", "woke", "woken", "waking")),
    ("wear", ("wear", "wears", "wore", "worn", "wearing")),
    ("win", ("win", "wins", "won", "winning")),
    ("write", ("write", "writes", "wrote", "written", "writing")),
)

_IRREGULAR_NOUN_FAMILIES = (
    ("man", ("man", "men")),
    ("woman", ("woman", "women")),
    ("child", ("child", "children")),
    ("person", ("person", "people")),
    ("mouse", ("mouse", "mice")),
    ("goose", ("goose", "geese")),
    ("foot", ("foot", "feet")),
    ("tooth", ("tooth", "teeth")),
    ("ox", ("ox", "oxen")),
    ("louse", ("louse", "lice")),
    ("die", ("die", "dice")),
    ("leaf", ("leaf", "leaves")),
    ("knife", ("knife", "knives")),
    ("life", ("life", "lives")),
    ("analysis", ("analysis", "analyses")),
    ("basis", ("basis", "bases")),
    ("crisis", ("crisis", "crises")),
    ("diagnosis", ("diagnosis", "diagnoses")),
    ("ellipsis", ("ellipsis", "ellipses")),
    ("hypothesis", ("hypothesis", "hypotheses")),
    ("parenthesis", ("parenthesis", "parentheses")),
    ("synthesis", ("synthesis", "syntheses")),
    ("thesis", ("thesis", "theses")),
    ("criterion", ("criterion", "criteria")),
    ("phenomenon", ("phenomenon", "phenomena")),
    ("index", ("index", "indices", "indexes")),
    ("appendix", ("appendix", "appendices", "appendixes")),
    ("matrix", ("matrix", "matrices")),
    ("vertex", ("vertex", "vertices")),
    ("alumnus", ("alumnus", "alumni")),
    ("cactus", ("cactus", "cacti", "cactuses")),
    ("fungus", ("fungus", "fungi", "funguses")),
    ("nucleus", ("nucleus", "nuclei")),
    ("stimulus", ("stimulus", "stimuli")),
    ("sheep", ("sheep",)),
    ("deer", ("deer",)),
    ("fish", ("fish", "fishes")),
    ("series", ("series",)),
    ("species", ("species",)),
    ("means", ("means",)),
    ("news", ("news",)),
)

_IRREGULAR_COMPARISON_FAMILIES = (
    ("good", ("good", "better", "best")),
    ("bad", ("bad", "worse", "worst")),
    ("little", ("little", "less", "least")),
    ("much", ("much", "more", "most")),
    ("many", ("many", "more", "most")),
    ("far", ("far", "farther", "farthest", "further", "furthest")),
    ("old", ("old", "older", "oldest", "elder", "eldest")),
)

# Reverse spelling of a past-tense ``-ed`` form is ambiguous without a
# dictionary: ``created`` could be read mechanically as ``creat + ed`` or
# correctly as ``create + d``.  This small set covers common silent-e verbs;
# the ordinary spelling rules still handle all unambiguous forms.
_COMMON_SILENT_E_VERBS = frozenset(
    {
        "ache",
        "achieve",
        "arrive",
        "bake",
        "believe",
        "blame",
        "breathe",
        "change",
        "close",
        "compare",
        "complete",
        "conceive",
        "create",
        "dance",
        "decide",
        "deceive",
        "define",
        "desire",
        "dine",
        "dive",
        "erase",
        "escape",
        "excuse",
        "face",
        "fade",
        "force",
        "gaze",
        "hate",
        "hope",
        "imagine",
        "improve",
        "include",
        "invite",
        "joke",
        "judge",
        "like",
        "live",
        "love",
        "make",
        "manage",
        "move",
        "name",
        "notice",
        "obey",
        "place",
        "praise",
        "prepare",
        "receive",
        "reduce",
        "refuse",
        "relate",
        "remove",
        "replace",
        "save",
        "serve",
        "share",
        "take",
        "smile",
        "solve",
        "taste",
        "trace",
        "use",
        "value",
        "vote",
        "write",
    }
)


def _ordered_variant_add(items: list[str], value: str) -> None:
    normalized = norm_lookup(value)
    if normalized and normalized not in items:
        items.append(normalized)


def _is_vowel(value: str) -> bool:
    return value.casefold() in "aeiou"


def _is_cvc(value: str) -> bool:
    if len(value) < 3 or not value[-1].isalpha():
        return False
    return not _is_vowel(value[-3]) and _is_vowel(value[-2]) and not _is_vowel(value[-1])


def _regular_plural(base: str) -> str:
    if base.endswith(("s", "x", "z", "ch", "sh")):
        return base + "es"
    if len(base) > 2 and base.endswith("y") and not _is_vowel(base[-2]):
        return base[:-1] + "ies"
    return base + "s"


def _regular_past(base: str) -> str:
    if base.endswith("e"):
        return base + "d"
    if len(base) > 2 and base.endswith("y") and not _is_vowel(base[-2]):
        return base[:-1] + "ied"
    if _is_cvc(base) and not base.endswith(("w", "x", "y")):
        return base + base[-1] + "ed"
    return base + "ed"


def _regular_participle(base: str) -> str:
    if base.endswith("ie"):
        return base[:-2] + "ying"
    if base.endswith("e") and not base.endswith(("ee", "ye")):
        return base[:-1] + "ing"
    if _is_cvc(base) and not base.endswith(("w", "x", "y")):
        return base + base[-1] + "ing"
    return base + "ing"


def _regular_forms(
    base: str,
    *,
    include_verb_forms: bool,
    include_noun_forms: bool,
) -> list[str]:
    forms: list[str] = [base]
    if include_noun_forms or include_verb_forms:
        _ordered_variant_add(forms, _regular_plural(base))
    if include_verb_forms:
        _ordered_variant_add(forms, _regular_past(base))
        _ordered_variant_add(forms, _regular_participle(base))
    return forms


def _regular_base_candidates(token: str) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = [(token, 100)]

    def add(value: str, priority: int) -> None:
        normalized = norm_lookup(value)
        if normalized and normalized != token and all(existing != normalized for existing, _ in candidates):
            candidates.append((normalized, priority))

    if token.endswith("ies") and len(token) > 4:
        add(token[:-3] + "y", 95)
    if token.endswith("ied") and len(token) > 4:
        add(token[:-3] + "y", 95)
    if token.endswith("ves") and len(token) > 4:
        add(token[:-3] + "f", 88)
        add(token[:-3] + "fe", 87)
    if token.endswith("es") and len(token) > 3:
        add(token[:-2], 84)
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        add(token[:-1], 83)
    if token.endswith("ing") and len(token) > 4:
        stem = token[:-3]
        add(stem, 82)
        if len(stem) > 2 and stem[-1] == stem[-2]:
            add(stem[:-1], 90)
        if stem in {"ly", "ty", "dy", "vy"}:
            add(stem[:-1] + "ie", 88)
        elif stem + "e" in _COMMON_SILENT_E_VERBS:
            add(stem + "e", 96)
        else:
            add(stem + "e", 81)
    if token.endswith("ed") and len(token) > 4:
        stem = token[:-2]
        add(stem, 82)
        if len(stem) > 2 and stem[-1] == stem[-2]:
            add(stem[:-1], 90)
        if stem.endswith("i"):
            add(stem[:-1] + "y", 88)
        if stem + "e" in _COMMON_SILENT_E_VERBS:
            add(stem + "e", 96)
        elif _is_cvc(stem) and not stem.endswith("y"):
            add(stem + "e", 89)
        else:
            add(stem + "e", 80)
    return candidates


def _regular_variant_family(
    token: str,
    *,
    include_verb_forms: bool,
    include_noun_forms: bool,
) -> list[str]:
    candidates = _regular_base_candidates(token)
    matching: list[tuple[int, list[str]]] = []
    # The input itself is a valid base candidate by construction.  When the
    # input is already inflected, however, treating it as a new base would
    # manufacture forms such as ``cleaninged``.  Prefer a derived base when
    # one explains the input; fall back to the input only when no reverse
    # spelling rule applies.
    for base, priority in candidates[1:]:
        forms = _regular_forms(
            base,
            include_verb_forms=include_verb_forms,
            include_noun_forms=include_noun_forms,
        )
        if token in forms:
            matching.append((priority, forms))
    if not matching:
        return _regular_forms(
            token,
            include_verb_forms=include_verb_forms,
            include_noun_forms=include_noun_forms,
        )
    return max(matching, key=lambda item: item[0])[1]


def _irregular_variant_family(
    token: str,
    *,
    include_verb_forms: bool,
    include_noun_forms: bool,
    include_comparison_forms: bool,
) -> list[str] | None:
    available: list[tuple[str, ...]] = []
    if include_verb_forms:
        available.extend(forms for _canonical, forms in _IRREGULAR_VERB_FAMILIES)
    if include_noun_forms:
        available.extend(forms for _canonical, forms in _IRREGULAR_NOUN_FAMILIES)
    if include_comparison_forms:
        available.extend(forms for _canonical, forms in _IRREGULAR_COMPARISON_FAMILIES)

    families = [family for family in available if token in family]
    if not families:
        return None

    # Some spellings belong to more than one grammatical role.  For example,
    # ``die`` is both a verb and a noun, while ``dies`` is only a verb and
    # ``dice`` is only a noun.  Join families that share a form so every
    # member resolves to the same union instead of making the result depend
    # on which member was queried.
    changed = True
    while changed:
        changed = False
        for family in available:
            if family in families:
                continue
            if any(set(family).intersection(existing) for existing in families):
                families.append(family)
                changed = True

    result: list[str] = []
    for family in families:
        for form in family:
            _ordered_variant_add(result, form)
    return result


def grammatical_variants(
    token: str,
    *,
    include_verb_forms: bool = True,
    include_noun_forms: bool = True,
    include_comparison_forms: bool = True,
) -> tuple[str, ...]:
    """Return one symmetric family of common English grammatical variants.

    The function intentionally handles lexical forms, not semantic synonyms or
    multi-word tense constructions.  Irregular families are table-driven;
    regular families use conservative spelling rules.
    """
    normalized = norm_lookup(token)
    if not normalized:
        return ()
    irregular = _irregular_variant_family(
        normalized,
        include_verb_forms=include_verb_forms,
        include_noun_forms=include_noun_forms,
        include_comparison_forms=include_comparison_forms,
    )
    if irregular is not None:
        return tuple(irregular)
    return tuple(
        _regular_variant_family(
            normalized,
            include_verb_forms=include_verb_forms,
            include_noun_forms=include_noun_forms,
        )
    )


def singular_candidates(token: str) -> list[str]:
    """Return registered-compatible singular/base candidates for a token."""
    normalized = norm_lookup(token)
    if not normalized:
        return []

    for canonical, forms in _IRREGULAR_NOUN_FAMILIES:
        if normalized in forms and normalized != canonical:
            return [canonical]

    candidates: list[str] = []
    for base, _priority in _regular_base_candidates(normalized)[1:]:
        forms = _regular_forms(base, include_verb_forms=False, include_noun_forms=True)
        if normalized in forms:
            _ordered_variant_add(candidates, base)
    return candidates


def manifest_paths(manifest: dict, key: str, kb_dir: Path) -> list[Path]:
    return [kb_dir / name for name in manifest.get("files", {}).get(key, [])]


def load_manifest(kb_dir: Path = DEFAULT_KB_DIR) -> dict:
    return read_json(kb_dir / "christian_kb_manifest.json")


def selected_evidence_paths(manifest: dict, layer: str, kb_dir: Path) -> list[Path]:
    if layer == "all":
        paths: list[Path] = []
        for item in ("primary", "extended", "archival"):
            paths.extend(manifest_paths(manifest, EVIDENCE_KEYS[item], kb_dir))
        return paths
    if layer not in EVIDENCE_KEYS:
        raise SemanticSearchError(f"unknown evidence layer: {layer}")
    return manifest_paths(manifest, EVIDENCE_KEYS[layer], kb_dir)


def load_sources(manifest: dict, kb_dir: Path) -> dict[str, dict]:
    sources: dict[str, dict] = {}
    for path in manifest_paths(manifest, "source_registry", kb_dir):
        for row in iter_jsonl(path):
            source_id = row.get("source_id")
            if source_id:
                sources[source_id] = dict(row)

    for path in manifest_paths(manifest, "sources", kb_dir):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                source_id = row.get("source_id")
                if source_id:
                    sources.setdefault(source_id, {}).update(row)
    return sources


def resolve_source_ids(source_arg: str | None, sources: dict[str, dict]) -> set[str] | None:
    if not source_arg:
        return None

    query = source_arg.strip().strip("\"'")
    query_norm = norm_text(query)
    query_path_norm = norm_source_path(query)

    exact_ids = {source_id for source_id in sources if norm_text(source_id) == query_norm}
    if exact_ids:
        return exact_ids

    exact_titles = {
        source_id
        for source_id, source in sources.items()
        if norm_text(source.get("display_title")) == query_norm
    }
    if exact_titles:
        return exact_titles

    exact_paths = {
        source_id
        for source_id, source in sources.items()
        if norm_source_path(source.get("pdf_file")) == query_path_norm
        or norm_text(Path(source.get("pdf_file", "")).stem) == query_norm
    }
    if exact_paths:
        return exact_paths

    partials = {
        source_id
        for source_id, source in sources.items()
        if query_norm in norm_text(source.get("display_title"))
        or query_path_norm in norm_source_path(source.get("pdf_file"))
    }
    if len(partials) == 1:
        return partials
    if len(partials) > 1:
        sample = [
            f"{source_id}: {sources[source_id].get('display_title', '')}"
            for source_id in sorted(partials)[:12]
        ]
        suffix = "" if len(partials) <= 12 else f"\n...and {len(partials) - 12} more"
        raise SemanticSearchError(
            "ambiguous --source; use a source id or a more specific title.\n"
            + "\n".join(sample)
            + suffix
        )

    raise SemanticSearchError(f"unknown --source: {source_arg!r}")


def author_matches(author: str | None, requested: list[str]) -> bool:
    if not requested:
        return True
    actual = norm_text(author)
    return any(actual == norm_text(item) for item in requested)


def section_matches(evidence: dict, section: str | None) -> bool:
    if not section:
        return True
    query = norm_lookup(section)
    values = [
        evidence.get("heading"),
        evidence.get("active_heading"),
        evidence.get("outline_path"),
    ]
    return any(query in norm_lookup(value) for value in values if value)


def fts_phrase(value: str) -> str:
    tokens = token_list(value)
    if not tokens:
        return ""
    return '"' + " ".join(tokens).replace('"', '""') + '"'


def make_fts_query(terms: list[str], max_terms: int = 32) -> str:
    pieces = []
    seen = set()
    for term in terms:
        piece = fts_phrase(term)
        if not piece or piece in seen:
            continue
        seen.add(piece)
        pieces.append(piece)
        if len(pieces) >= max_terms:
            break
    return " OR ".join(pieces)
