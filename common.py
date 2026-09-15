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
DEFAULT_LEXICON_PATH = RESOURCE_DIR / "concept_query_lexicon.json"
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


def singular_candidates(token: str) -> list[str]:
    candidates = []
    if len(token) > 4 and token.endswith("ies"):
        candidates.append(token[:-3] + "y")
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        candidates.append(token[:-1])
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
