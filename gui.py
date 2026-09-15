#!/usr/bin/env python3
"""Tkinter desktop GUI for Theologia Search."""

from __future__ import annotations

import json
import queue
import re
import sqlite3
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

try:
    from . import periods
    from .common import (
        DEFAULT_GUI_HISTORY_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_LEXICON_PATH,
        SemanticSearchError,
        configure_output,
        display_text,
        write_json,
    )
    from .search import (
        AdvancedSearchCriteria,
        aggregate_discovered_phrases,
        load_lexicon,
        row_mentioned_authors,
        search_advanced,
        search_advanced_by_period,
        search_concept,
        search_concept_by_period,
        configure_search_connection,
        validate_advanced_criteria,
    )
except ImportError:  # pragma: no cover - supports direct script execution.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import periods
    from common import (
        DEFAULT_GUI_HISTORY_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_LEXICON_PATH,
        SemanticSearchError,
        configure_output,
        display_text,
        write_json,
    )
    from search import (
        AdvancedSearchCriteria,
        aggregate_discovered_phrases,
        load_lexicon,
        row_mentioned_authors,
        search_advanced,
        search_advanced_by_period,
        search_concept,
        search_concept_by_period,
        configure_search_connection,
        validate_advanced_criteria,
    )


DEFAULT_LIMIT = 10
MAX_HISTORY_ITEMS = 100


def registered_author_names() -> tuple[str, ...]:
    return periods.registered_author_names()


@dataclass
class SearchOutput:
    query: str
    limit: int
    results: list[dict]
    discovered_phrases: list[str]
    period_groups: list[dict] | None = None
    advanced: bool = False


@dataclass
class ContextOutput:
    selected: dict
    rows: list[dict]
    mode: str
    page_range: str
    heading: str
    before_word_count: int
    after_word_count: int
    before_truncated: bool
    after_truncated: bool


def validate_limit(value: str, *, default: int = DEFAULT_LIMIT) -> int:
    text = display_text(value)
    if not text:
        return default
    try:
        limit = int(text)
    except ValueError as exc:
        raise ValueError("Search limit must be a whole number.") from exc
    if limit < 1:
        raise ValueError("Search limit must be at least 1.")
    if limit > 100:
        raise ValueError("Search limit must be 100 or less.")
    return limit


def load_history(path: Path = DEFAULT_GUI_HISTORY_PATH) -> list[str]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    items = payload.get("queries")
    if not isinstance(items, list):
        return []
    history: list[str] = []
    seen = set()
    for item in items:
        query = display_text(str(item))
        key = query.casefold()
        if query and key not in seen:
            seen.add(key)
            history.append(query)
    return history[:MAX_HISTORY_ITEMS]


def save_history(history: list[str], path: Path = DEFAULT_GUI_HISTORY_PATH) -> None:
    cleaned: list[str] = []
    seen = set()
    for item in history:
        query = display_text(item)
        key = query.casefold()
        if query and key not in seen:
            seen.add(key)
            cleaned.append(query)
    write_json(path, {"queries": cleaned[:MAX_HISTORY_ITEMS]})


def add_history_item(history: list[str], query: str) -> list[str]:
    cleaned_query = display_text(query)
    if not cleaned_query:
        return history
    remaining = [item for item in history if item.casefold() != cleaned_query.casefold()]
    return [cleaned_query] + remaining[: MAX_HISTORY_ITEMS - 1]


def clear_history(path: Path = DEFAULT_GUI_HISTORY_PATH) -> None:
    save_history([], path)


def clean_display_text(value: str | None) -> str:
    text = (value or "").replace("\u0000", "").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def snippet_segments(value: str | None, max_chars: int = 220) -> list[tuple[str, bool]]:
    """Convert [[matched terms]] into plain/bold display segments."""
    text = clean_display_text(value)
    if not text:
        return []
    marker = re.compile(r"\[\[(.*?)\]\]")
    segments: list[tuple[str, bool]] = []
    position = 0
    for match in marker.finditer(text):
        if match.start() > position:
            segments.append((text[position:match.start()], False))
        if match.group(1):
            segments.append((match.group(1), True))
        position = match.end()
    if position < len(text):
        segments.append((text[position:], False))

    clipped: list[tuple[str, bool]] = []
    remaining = max_chars
    was_clipped = False
    for segment, is_match in segments:
        if remaining <= 0:
            was_clipped = True
            break
        if len(segment) <= remaining:
            clipped.append((segment, is_match))
            remaining -= len(segment)
        else:
            clipped.append((segment[:remaining].rstrip(), is_match))
            was_clipped = True
            break
    if was_clipped:
        clipped.append(("...", False))
    return [(segment, is_match) for segment, is_match in clipped if segment]


def word_count(value: str | None) -> int:
    return len(re.findall(r"\S+", value or ""))


def context_key(row: dict) -> tuple[str, str]:
    heading = display_value(row.get("heading"))
    if heading:
        return ("heading", heading.casefold())
    outline_path = display_value(row.get("outline_path"))
    if outline_path:
        return ("outline_path", outline_path.casefold())
    return ("", "")


def page_range(rows: list[dict]) -> str:
    pages = []
    for row in rows:
        for key in ("page_start", "page_end", "page_number"):
            value = row.get(key)
            if value is not None and str(value).isdigit():
                pages.append(int(value))
    if not pages:
        return "unknown"
    first = min(pages)
    last = max(pages)
    return str(first) if first == last else f"{first}-{last}"


def result_tag(index: int) -> str:
    return f"result_{index}"


def result_index_from_tags(tags) -> int | None:
    for tag in tags:
        match = re.fullmatch(r"result_(\d+)", str(tag))
        if match:
            return int(match.group(1))
    return None


def display_value(value, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = display_text(str(value))
    return text if text else fallback


def result_fields(index: int, row: dict) -> list[tuple[str, str, str]]:
    page = display_value(row.get("page_number"), "unknown")
    quality = display_value(row.get("quality_label") or row.get("match_quality"), "unknown")
    title = f"{index}. {display_value(row.get('source_id'), 'unknown source')} p.{page}"
    heading = display_value(row.get("heading") or row.get("outline_path"))
    fields = [
        ("title", "", title),
        ("field", "Source", display_value(row.get("source_title") or row.get("source_id"), "unknown")),
        ("field", "Author", display_value(row.get("author"), "Unknown")),
    ]
    if row.get("mentioned_authors"):
        fields.append(("field", "Mentioned", ", ".join(row["mentioned_authors"])))
    if heading:
        fields.append(("field", "Heading", heading))
    fields.append(("field", "Quality", quality))
    if row.get("snippet"):
        fields.append(("body", "Snippet", clean_display_text(row["snippet"])))
    return fields


def result_explanation_lines(row: dict) -> list[tuple[str, str]]:
    score_breakdown = row.get("score_breakdown") or {}
    page = display_value(row.get("page_number"), "unknown")
    lines = [
        ("Source", display_value(row.get("source_title") or row.get("source_id"), "unknown")),
        ("Author", display_value(row.get("author"), "Unknown")),
        ("Mentioned authors", ", ".join(row.get("mentioned_authors") or []) or "none"),
        ("Heading", display_value(row.get("heading") or row.get("outline_path"), "unknown")),
        ("Page", page),
        ("Evidence", display_value(row.get("evidence_id"), "unknown")),
        ("Period", display_value(row.get("author_period_label"), "unknown")),
        ("Period basis", display_value(row.get("author_period_source"), "unknown")),
        ("Quality", display_value(row.get("quality_label") or row.get("match_quality"), "unknown")),
        ("Quality grade", display_value(row.get("quality_grade"), "unknown")),
        ("Score", display_value(row.get("concept_score"), "unknown")),
        ("Exact/raw terms", ", ".join(row.get("matched_raw_terms") or []) or "none"),
        ("Registered KB terms", ", ".join(row.get("matched_registered_terms") or []) or "none"),
        ("Lemma matches", ", ".join(row.get("matched_lemmas") or []) or "none"),
        ("Term-family matches", ", ".join(row.get("matched_term_families") or []) or "none"),
        ("Phrase matches", ", ".join(match.get("phrase", "") for match in row.get("raw_phrase_matches") or []) or "none"),
        ("Proximity matches", str(len(row.get("proximity_matches") or []))),
        ("Reasons", "; ".join(row.get("match_reasons") or []) or "none"),
        (
            "Score breakdown",
            ", ".join(f"{key}={value}" for key, value in sorted(score_breakdown.items())) or "none",
        ),
    ]
    if row.get("advanced_query_mode"):
        lines.extend(
            [
                ("Advanced mode", display_value(row.get("advanced_query_mode"), "none")),
                (
                    "Advanced field matches",
                    ", ".join(
                        field for field, matched in (row.get("advanced_filter_matches") or {}).items() if matched
                    ) or "none",
                ),
                ("Advanced exact fields", str(row.get("advanced_exact_field_matches") or 0)),
                (
                    "Advanced reasons",
                    "; ".join(row.get("advanced_filter_reasons") or []) or "none",
                ),
            ]
        )
    return lines


def format_result(index: int, row: dict) -> str:
    parts = []
    for kind, label, value in result_fields(index, row):
        if kind == "title":
            parts.append(value)
        elif kind == "body":
            parts.append(f"{label}: {value}")
        else:
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


def format_results(results: list[dict]) -> str:
    if not results:
        return "No results found."
    return "\n\n".join(format_result(index, row) for index, row in enumerate(results, 1))


def run_search(
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    index_path: Path = DEFAULT_INDEX_PATH,
    lexicon_path: Path = DEFAULT_LEXICON_PATH,
    period_sections: bool = False,
) -> SearchOutput:
    concept = display_text(query)
    if not concept:
        raise SemanticSearchError("Type a search query first.")
    if not index_path.exists():
        raise SemanticSearchError(f"Missing semantic index: {index_path}")
    lexicon = load_lexicon(lexicon_path)
    con = sqlite3.connect(str(index_path))
    con.row_factory = sqlite3.Row
    try:
        if period_sections:
            period_groups, _ = search_concept_by_period(
                con,
                concept,
                lexicon,
                limit=limit,
                candidate_limit=max(20, limit * 2),
                include_cooccurrence=False,
                cluster_results=False,
            )
            results = [row for group in period_groups for row in group["results"]]
        else:
            period_groups = None
            results, _ = search_concept(
                con,
                concept,
                lexicon,
                limit=limit,
                candidate_limit=max(20, limit * 2),
                include_cooccurrence=False,
                cluster_results=False,
            )
    finally:
        con.close()
    return SearchOutput(
        query=concept,
        limit=limit,
        results=results,
        discovered_phrases=aggregate_discovered_phrases(results),
        period_groups=period_groups,
    )


def advanced_query_label(criteria: AdvancedSearchCriteria) -> str:
    """Build a compact display label without changing the user's criteria."""
    parts = [criteria.concept, criteria.author, criteria.mentioned_author, criteria.period_id, criteria.book, criteria.chapter]
    return "Advanced search: " + " | ".join(part for part in parts if part)


def run_advanced_search(
    criteria: AdvancedSearchCriteria,
    *,
    limit: int = DEFAULT_LIMIT,
    index_path: Path = DEFAULT_INDEX_PATH,
    lexicon_path: Path = DEFAULT_LEXICON_PATH,
    period_sections: bool = True,
) -> SearchOutput:
    criteria = validate_advanced_criteria(criteria)
    if not index_path.exists():
        raise SemanticSearchError(f"Missing semantic index: {index_path}")
    lexicon = load_lexicon(lexicon_path)
    con = sqlite3.connect(str(index_path))
    configure_search_connection(con)
    con.row_factory = sqlite3.Row
    try:
        if period_sections:
            period_groups, _ = search_advanced_by_period(
                con,
                criteria,
                lexicon,
                limit=limit,
                candidate_limit=max(20, limit * 2),
            )
            results = [row for group in period_groups for row in group["results"]]
        else:
            results, _ = search_advanced(
                con,
                criteria,
                lexicon,
                limit=limit,
                candidate_limit=max(20, limit * 2),
            )
            period_groups = None
    finally:
        con.close()
    return SearchOutput(
        query=advanced_query_label(criteria),
        limit=limit,
        results=results,
        discovered_phrases=aggregate_discovered_phrases(results),
        period_groups=period_groups,
        advanced=True,
    )


def fetch_context(
    evidence_id: str,
    *,
    index_path: Path = DEFAULT_INDEX_PATH,
    before_words: int = 1000,
    after_words: int = 1000,
) -> ContextOutput:
    evidence_id = display_value(evidence_id)
    if not evidence_id:
        raise SemanticSearchError("Missing evidence id.")
    if not index_path.exists():
        raise SemanticSearchError(f"Missing semantic index: {index_path}")

    con = sqlite3.connect(str(index_path))
    configure_search_connection(con)
    con.row_factory = sqlite3.Row
    try:
        selected = con.execute("SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)).fetchone()
        if selected is None:
            raise SemanticSearchError(f"Evidence id not found: {evidence_id}")
        source_id = selected["source_id"]
        source_rows = [
            dict(row)
            for row in con.execute(
                """
                SELECT * FROM evidence
                WHERE source_id = ?
                ORDER BY COALESCE(page_start, page_number, 0), COALESCE(page_end, page_number, 0), evidence_id
                """,
                (source_id,),
            )
        ]
    finally:
        con.close()

    selected_index = next(
        (index for index, row in enumerate(source_rows) if row.get("evidence_id") == evidence_id),
        None,
    )
    if selected_index is None:
        raise SemanticSearchError(f"Evidence id not found in source order: {evidence_id}")

    selected_dict = dict(selected)
    selected_dict["mentioned_authors"] = row_mentioned_authors(selected_dict)
    selected_context_key = context_key(selected_dict)
    if selected_context_key[0]:
        chapter_rows = [selected_dict]
        left = selected_index - 1
        while left >= 0 and context_key(source_rows[left]) == selected_context_key:
            chapter_rows.insert(0, source_rows[left])
            left -= 1
        right = selected_index + 1
        while right < len(source_rows) and context_key(source_rows[right]) == selected_context_key:
            chapter_rows.append(source_rows[right])
            right += 1
        if len(chapter_rows) > 1:
            selected_position = next(
                index for index, row in enumerate(chapter_rows) if row.get("evidence_id") == evidence_id
            )
            return ContextOutput(
                selected=selected_dict,
                rows=chapter_rows,
                mode="chapter",
                page_range=page_range(chapter_rows),
                heading=display_value(selected_dict.get("heading") or selected_dict.get("outline_path"), "no heading"),
                before_word_count=sum(word_count(row.get("verbatim_text")) for row in chapter_rows[:selected_position]),
                after_word_count=sum(word_count(row.get("verbatim_text")) for row in chapter_rows[selected_position + 1 :]),
                before_truncated=left >= 0,
                after_truncated=right < len(source_rows),
            )

    before_rows = []
    before_total = 0
    for row in reversed(source_rows[:selected_index]):
        before_total += word_count(row.get("verbatim_text"))
        before_rows.append(row)
        if before_total >= before_words:
            break
    before_rows.reverse()

    after_rows = []
    after_total = 0
    for row in source_rows[selected_index + 1 :]:
        after_total += word_count(row.get("verbatim_text"))
        after_rows.append(row)
        if after_total >= after_words:
            break

    return ContextOutput(
        selected=selected_dict,
        rows=before_rows + [dict(selected)] + after_rows,
        mode="nearby",
        page_range=page_range(before_rows + [dict(selected)] + after_rows),
        heading=display_value(selected_dict.get("heading") or selected_dict.get("outline_path"), "no heading"),
        before_word_count=before_total,
        after_word_count=after_total,
        before_truncated=selected_index > len(before_rows),
        after_truncated=(len(source_rows) - selected_index - 1) > len(after_rows),
    )


def context_rows_to_text(context: ContextOutput) -> str:
    if context.mode == "chapter":
        parts = []
        selected_id = context.selected.get("evidence_id")
        for row in context.rows:
            if row.get("evidence_id") == selected_id:
                parts.append("[SELECTED EVIDENCE]")
            parts.append(clean_display_text(row.get("verbatim_text")))
        return "\n".join(parts)

    parts = []
    selected_id = context.selected.get("evidence_id")
    for row in context.rows:
        if row.get("evidence_id") == selected_id:
            marker = "SELECTED EVIDENCE"
        else:
            marker = "NEARBY EVIDENCE"
        heading = display_value(row.get("heading") or row.get("outline_path"), "no heading")
        page = display_value(row.get("page_number"), "unknown")
        parts.append(f"[{marker}] {row.get('evidence_id')} | p.{page} | {heading}")
        parts.append(clean_display_text(row.get("verbatim_text")))
    return "\n\n".join(parts)


def context_keywords(row: dict | None) -> list[str]:
    """Return literal query terms and confirmed morphology forms for highlighting."""
    if not row:
        return []
    values: set[str] = set()
    for value in row.get("raw_query_terms") or []:
        term = display_value(value).strip()
        if term:
            values.add(term)
    for value in row.get("matched_lemmas") or []:
        for term in re.split(r"\s*->\s*", display_value(value)):
            term = term.strip()
            if term:
                values.add(term)
    for forms in (row.get("matched_morphology_forms") or {}).values():
        for value in forms or []:
            term = display_value(value).strip()
            if term:
                values.add(term)
    return sorted(values, key=lambda value: (-len(value), value.casefold()))


class AdvancedSearchDialog(tk.Toplevel):
    """Small modal form shared by the Tk fallback workflow."""

    PERIOD_OPTIONS = (
        ("All periods", ""),
        ("Before Council of Nicaea", "before_nicene"),
        ("After Nicene but before Reformation", "nicene_to_reformation"),
        ("After Reformation", "post_reformation"),
    )

    def __init__(self, parent: tk.Misc, on_submit) -> None:
        super().__init__(parent)
        self.on_submit = on_submit
        self.title("Advanced Search")
        self.geometry("620x390")
        self.minsize(520, 330)
        self.transient(parent)
        self.grab_set()
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        form = ttk.Frame(self, padding=18)
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Search indexed knowledge").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        self.entries: dict[str, tk.StringVar] = {}
        self.connector_vars: dict[str, tk.StringVar] = {}
        fields = (
            ("concept", "Things to search"),
            ("author", "Author name"),
            ("mentioned_author", "Mentioned author"),
            ("period_id", "Author time period"),
            ("book", "Book name"),
            ("chapter", "Chapter"),
        )
        for row_index, (field, label) in enumerate(fields, 1):
            connector_column = 0
            if row_index > 1:
                connector_field = field
                variable = tk.StringVar(value="AND")
                self.connector_vars[connector_field] = variable
                ttk.Combobox(form, textvariable=variable, values=("AND", "OR"), state="readonly", width=7).grid(
                    row=row_index, column=connector_column, padx=(0, 8), sticky="w"
                )
            ttk.Label(form, text=label).grid(row=row_index, column=1, sticky="w", padx=(0, 10))
            variable = tk.StringVar()
            self.entries[field] = variable
            if field == "period_id":
                period = ttk.Combobox(
                    form,
                    textvariable=variable,
                    values=tuple(label for label, _value in self.PERIOD_OPTIONS),
                    state="readonly",
                )
                period.current(0)
                period.grid(row=row_index, column=2, sticky="ew")
            elif field in {"author", "mentioned_author"}:
                author = ttk.Combobox(
                    form,
                    textvariable=variable,
                    values=("All authors",) + registered_author_names(),
                    state="readonly",
                )
                author.current(0)
                author.grid(row=row_index, column=2, sticky="ew")
            else:
                ttk.Entry(form, textvariable=variable).grid(row=row_index, column=2, sticky="ew")

        buttons = ttk.Frame(form)
        buttons.grid(row=len(fields) + 1, column=0, columnspan=3, sticky="e", pady=(20, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(buttons, text="Start Advanced Search", command=self.submit).pack(side=tk.RIGHT)

    def submit(self) -> None:
        period_label = self.entries["period_id"].get()
        period_id = dict(self.PERIOD_OPTIONS).get(period_label, "")
        author_value = self.entries["author"].get()
        if author_value == "All authors":
            author_value = ""
        mentioned_author_value = self.entries["mentioned_author"].get()
        if mentioned_author_value == "All authors":
            mentioned_author_value = ""
        criteria = AdvancedSearchCriteria(
            concept=self.entries["concept"].get(),
            author=author_value,
            mentioned_author=mentioned_author_value,
            period_id=period_id,
            book=self.entries["book"].get(),
            chapter=self.entries["chapter"].get(),
            connectors=tuple(self.connector_vars[field].get() for field in ("author", "mentioned_author", "period_id", "book", "chapter")),
        )
        try:
            criteria = validate_advanced_criteria(criteria)
        except SemanticSearchError as exc:
            messagebox.showerror("Advanced Search", str(exc), parent=self)
            return
        self.destroy()
        self.on_submit(criteria)


class SemanticSearchApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        history_path: Path = DEFAULT_GUI_HISTORY_PATH,
        index_path: Path = DEFAULT_INDEX_PATH,
        lexicon_path: Path = DEFAULT_LEXICON_PATH,
    ):
        self.root = root
        self.history_path = history_path
        self.index_path = index_path
        self.lexicon_path = lexicon_path
        self.result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.history = load_history(history_path)
        self.search_running = False
        self.current_results: list[dict] = []
        self.result_ranges: dict[int, tuple[str, str]] = {}
        self._selected_result_index: int | None = None

        self.query_var = tk.StringVar()
        self.limit_var = tk.StringVar(value=str(DEFAULT_LIMIT))
        self.status_var = tk.StringVar(value="Ready")

        self.root.title("Theologia Search")
        self.root.geometry("1100x720")
        self.root.minsize(800, 520)
        self._build_widgets()
        self._refresh_history()
        self.root.after(100, self._poll_results)

    def _build_widgets(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=(10, 10, 10, 6))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)

        query_entry = ttk.Entry(top, textvariable=self.query_var)
        query_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        query_entry.bind("<Return>", lambda _event: self.start_search())
        query_entry.focus_set()

        ttk.Label(top, text="Limit").grid(row=0, column=1, padx=(0, 4))
        limit_entry = ttk.Combobox(top, textvariable=self.limit_var, values=("5", "10", "15", "20", "25"), state="readonly", width=6)
        limit_entry.grid(row=0, column=2, padx=(0, 8))
        limit_entry.bind("<Return>", lambda _event: self.start_search())

        self.search_button = ttk.Button(top, text="Search", command=self.start_search, width=12)
        self.search_button.grid(row=0, column=3, padx=(0, 8))
        self.advance_button = ttk.Button(top, text="ADVANCE", command=self.open_advanced_search, width=12)
        self.advance_button.grid(row=0, column=4, padx=(0, 8))
        ttk.Button(top, text="Read Full Text", command=self.open_selected_context).grid(row=0, column=5)
        ttk.Button(top, text="Why Result", command=self.open_selected_explanation).grid(row=0, column=6, padx=(8, 0))

        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        history_frame = ttk.Frame(main, padding=(0, 0, 8, 0))
        history_frame.rowconfigure(1, weight=1)
        history_frame.columnconfigure(0, weight=1)
        ttk.Label(history_frame, text="Search History").grid(row=0, column=0, sticky="w")
        self.history_list = tk.Listbox(history_frame, exportselection=False)
        self.history_list.grid(row=1, column=0, sticky="nsew", pady=(4, 6))
        history_scroll = ttk.Scrollbar(history_frame, orient=tk.VERTICAL, command=self.history_list.yview)
        history_scroll.grid(row=1, column=1, sticky="ns", pady=(4, 6))
        self.history_list.configure(yscrollcommand=history_scroll.set)
        self.history_list.bind("<<ListboxSelect>>", self.search_selected_history)
        ttk.Button(history_frame, text="Clear History", command=self.clear_search_history).grid(row=2, column=0, sticky="ew")
        main.add(history_frame, weight=1)

        results_frame = ttk.Frame(main)
        results_frame.rowconfigure(1, weight=1)
        results_frame.columnconfigure(0, weight=1)
        ttk.Label(results_frame, text="Results").grid(row=0, column=0, sticky="w")
        self.results_text = tk.Text(results_frame, wrap="word", height=18)
        self.results_text.tag_configure("separator", foreground="#777777")
        self.results_text.tag_configure("result_title", font=("TkDefaultFont", 10, "bold"))
        self.results_text.tag_configure("field_label", font=("TkDefaultFont", 10, "bold"))
        self.results_text.tag_configure("field_value", font=("TkDefaultFont", 10, "normal"))
        self.results_text.tag_configure("period_header", font=("TkDefaultFont", 11, "bold"), spacing1=10, spacing3=4)
        self.results_text.tag_configure("snippet_label", font=("TkDefaultFont", 10, "bold"))
        self.results_text.tag_configure("snippet_value", lmargin1=18, lmargin2=18, spacing3=8)
        self.results_text.tag_configure("snippet_match", font=("TkDefaultFont", 10, "bold"))
        self.results_text.tag_configure("result_block", spacing1=6, spacing3=10)
        self.results_text.tag_configure("selected_result", background="#f4ead3")
        self.results_text.bind("<Button-1>", self.select_result_at_event)
        self.results_text.bind("<Double-Button-1>", self.open_result_at_event)
        results_scroll = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=results_scroll.set)
        self.results_text.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        results_scroll.grid(row=1, column=1, sticky="ns", pady=(4, 0))
        main.add(results_frame, weight=4)

        status = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _insert_result_block(self, result_index: int, row: dict, display_number: int) -> None:
        block_tag = result_tag(result_index)
        start = self.results_text.index(tk.END)
        self.results_text.insert(tk.END, "-" * 72 + "\n", ("separator", block_tag, "result_block"))
        for kind, label, value in result_fields(display_number, row):
            if kind == "title":
                self.results_text.insert(tk.END, value + "\n", ("result_title", block_tag, "result_block"))
            elif kind == "body":
                self.results_text.insert(tk.END, f"{label}: ", ("snippet_label", block_tag, "result_block"))
                for segment, is_match in snippet_segments(value):
                    tags = ["snippet_value", block_tag, "result_block"]
                    if is_match:
                        tags.append("snippet_match")
                    self.results_text.insert(tk.END, segment, tuple(tags))
                self.results_text.insert(tk.END, "\n", ("snippet_value", block_tag, "result_block"))
            else:
                self.results_text.insert(tk.END, f"{label}: ", ("field_label", block_tag, "result_block"))
                self.results_text.insert(tk.END, value + "\n", ("field_value", block_tag, "result_block"))
        end = self.results_text.index(tk.END)
        self.result_ranges[result_index] = (start, end)

    def _render_results(self, results: list[dict], period_groups: list[dict] | None = None) -> None:
        self.results_text.configure(state="normal")
        self.results_text.delete("1.0", tk.END)
        self.result_ranges = {}
        self._selected_result_index = None
        if not results:
            self.results_text.insert("1.0", "No results found.")
            self.results_text.configure(state="disabled")
            return

        if period_groups:
            result_index = 0
            for group in period_groups:
                self.results_text.insert(tk.END, f"\n{group.get('period_label', 'Historical period')} ({len(group.get('results') or [])})\n", ("period_header",))
                if not group.get("results"):
                    self.results_text.insert(tk.END, "No results in this section.\n")
                    continue
                for display_number, row in enumerate(group["results"], 1):
                    self._insert_result_block(result_index, row, display_number)
                    self.results_text.insert(tk.END, "\n")
                    result_index += 1
        else:
            for index, row in enumerate(results):
                if index:
                    self.results_text.insert(tk.END, "\n")
                self._insert_result_block(index, row, index + 1)
        self.results_text.configure(state="disabled")

    def _refresh_history(self) -> None:
        self.history_list.delete(0, tk.END)
        for query in self.history:
            self.history_list.insert(tk.END, query)

    def start_search(self) -> None:
        if self.search_running:
            return
        query = display_text(self.query_var.get())
        try:
            limit = validate_limit(self.limit_var.get())
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        if not query:
            self.status_var.set("Type a search query first.")
            return

        self.search_running = True
        self.search_button.configure(state="disabled")
        self.advance_button.configure(state="disabled")
        self._selected_result_index = None
        self.status_var.set("Searching...")
        self._set_text(self.results_text, "")

        thread = threading.Thread(target=self._search_worker, args=(query, limit), daemon=True)
        thread.start()

    def open_advanced_search(self) -> None:
        if self.search_running:
            return
        AdvancedSearchDialog(self.root, self.start_advanced_search)

    def start_advanced_search(self, criteria: AdvancedSearchCriteria) -> None:
        if self.search_running:
            return
        try:
            limit = validate_limit(self.limit_var.get())
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        self.search_running = True
        self.search_button.configure(state="disabled")
        self.advance_button.configure(state="disabled")
        self._selected_result_index = None
        self.status_var.set("Running advanced search...")
        self._set_text(self.results_text, "")
        thread = threading.Thread(target=self._advanced_search_worker, args=(criteria, limit), daemon=True)
        thread.start()

    def _advanced_search_worker(self, criteria: AdvancedSearchCriteria, limit: int) -> None:
        try:
            output = run_advanced_search(
                criteria,
                limit=limit,
                index_path=self.index_path,
                lexicon_path=self.lexicon_path,
                period_sections=True,
            )
        except Exception as exc:
            self.result_queue.put(("error", exc))
        else:
            self.result_queue.put(("success", output))

    def _search_worker(self, query: str, limit: int) -> None:
        try:
            output = run_search(
                query,
                limit=limit,
                index_path=self.index_path,
                lexicon_path=self.lexicon_path,
                period_sections=True,
            )
        except Exception as exc:  # The GUI should report errors without closing.
            self.result_queue.put(("error", exc))
        else:
            self.result_queue.put(("success", output))

    def _poll_results(self) -> None:
        try:
            kind, payload = self.result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_results)
            return

        self.search_running = False
        self.search_button.configure(state="normal")
        self.advance_button.configure(state="normal")
        if kind == "error":
            self.status_var.set(f"Error: {payload}")
        else:
            output: SearchOutput = payload  # type: ignore[assignment]
            self.current_results = output.results
            self._render_results(output.results, output.period_groups)
            self.status_var.set(f"Found {len(output.results)} results")
            if not output.advanced:
                self.history = add_history_item(self.history, output.query)
                save_history(self.history, self.history_path)
                self._refresh_history()
        self.root.after(100, self._poll_results)

    def search_selected_history(self, _event=None) -> None:
        selection = self.history_list.curselection()
        if not selection:
            return
        query = self.history_list.get(selection[0])
        self.query_var.set(query)
        self.start_search()

    def clear_search_history(self) -> None:
        self.history = []
        clear_history(self.history_path)
        self._refresh_history()
        self.status_var.set("History cleared")

    def clear_search(self) -> None:
        self.query_var.set("")
        self.current_results = []
        self.result_ranges = {}
        self._selected_result_index = None
        self._set_text(self.results_text, "")
        self.status_var.set("Ready")

    def selected_result_index(self) -> int | None:
        return self._selected_result_index

    def _select_result(self, result_index: int) -> None:
        if result_index < 0 or result_index >= len(self.current_results):
            return
        self._selected_result_index = result_index
        self.results_text.tag_remove("selected_result", "1.0", tk.END)
        result_range = self.result_ranges.get(result_index)
        if result_range:
            self.results_text.tag_add("selected_result", result_range[0], result_range[1])
        self.status_var.set(f"Selected {display_value(self.current_results[result_index].get('evidence_id'), 'result')}")

    def select_result_at_event(self, event) -> None:
        tags = self.results_text.tag_names(f"@{event.x},{event.y}")
        result_index = result_index_from_tags(tags)
        if result_index is not None:
            self._select_result(result_index)

    def open_selected_explanation(self) -> None:
        result_index = self.selected_result_index()
        if result_index is None or result_index >= len(self.current_results):
            self.status_var.set("Select a result first.")
            return
        self._show_explanation_popup(self.current_results[result_index])

    def _show_explanation_popup(self, row: dict) -> None:
        popup = tk.Toplevel(self.root)
        popup.title(f"Why this result? {display_value(row.get('evidence_id'), 'selected result')}")
        popup.geometry("760x560")
        popup.minsize(560, 360)
        popup.columnconfigure(0, weight=1)
        popup.rowconfigure(0, weight=1)
        text = tk.Text(popup, wrap="word")
        text.tag_configure("explain_label", font=("TkDefaultFont", 10, "bold"))
        text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        scroll = ttk.Scrollbar(popup, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns", pady=10)
        for label, value in result_explanation_lines(row):
            text.insert(tk.END, f"{label}: ", ("explain_label",))
            text.insert(tk.END, value + "\n\n")
        text.configure(state="disabled")

    def open_result_at_event(self, event) -> None:
        tags = self.results_text.tag_names(f"@{event.x},{event.y}")
        result_index = result_index_from_tags(tags)
        if result_index is None or result_index >= len(self.current_results):
            self.status_var.set("Select a result first.")
            return
        self._select_result(result_index)
        self.open_selected_context()

    def open_selected_context(self) -> None:
        result_index = self.selected_result_index()
        if result_index is None or result_index >= len(self.current_results):
            self.status_var.set("Select a result first.")
            return
        row = self.current_results[result_index]
        try:
            context = fetch_context(row.get("evidence_id"), index_path=self.index_path)
        except Exception as exc:
            self.status_var.set(f"Context error: {exc}")
            self._show_error_popup("Context error", str(exc))
            return
        self._show_context_popup(context, match_row=row)
        self.status_var.set(f"{len(self.current_results)} results" if self.current_results else "Ready")

    def _show_error_popup(self, title: str, message: str) -> None:
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.geometry("520x180")
        popup.minsize(420, 140)
        popup.columnconfigure(0, weight=1)
        popup.rowconfigure(0, weight=1)
        text = tk.Text(popup, wrap="word", height=6)
        text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        text.insert("1.0", message)
        text.configure(state="disabled")

    def _insert_popup_field(self, widget: tk.Text, label: str, value: str) -> None:
        widget.insert(tk.END, f"{label}: ", ("popup_label",))
        widget.insert(tk.END, value + "\n", ("popup_value",))

    def _show_context_popup(self, context: ContextOutput, *, match_row: dict | None = None) -> None:
        selected = context.selected
        source_id = display_value(selected.get("source_id"), "unknown source")
        evidence_id = display_value(selected.get("evidence_id"), "unknown evidence")

        popup = tk.Toplevel(self.root)
        popup.title(f"{source_id} p.{context.page_range} | {evidence_id} | {context.heading}")
        popup.geometry("960x720")
        popup.minsize(700, 480)
        popup.columnconfigure(0, weight=1)
        popup.rowconfigure(2, weight=1)

        meta = tk.Text(popup, wrap="word", height=8)
        meta.tag_configure("popup_label", font=("TkDefaultFont", 10, "bold"))
        meta.tag_configure("popup_value", font=("TkDefaultFont", 10, "normal"))
        meta.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        self._insert_popup_field(meta, "Source", source_id)
        self._insert_popup_field(meta, "Title", display_value(selected.get("source_title"), "unknown"))
        self._insert_popup_field(meta, "Author", display_value(selected.get("author"), "Unknown"))
        self._insert_popup_field(meta, "Page range", context.page_range)
        self._insert_popup_field(meta, "Evidence", evidence_id)
        self._insert_popup_field(meta, "Heading", context.heading)
        if context.mode == "chapter":
            context_label = f"Complete chapter across {len(context.rows)} indexed row(s)"
        else:
            context_label = f"Nearby fallback: {context.before_word_count} words before, {context.after_word_count} words after"
        self._insert_popup_field(meta, "Context", context_label)
        meta.configure(state="disabled")

        font_controls = ttk.Frame(popup)
        font_controls.grid(row=1, column=0, sticky="e", padx=10, pady=(0, 6))

        body_frame = ttk.Frame(popup)
        body_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        body_frame.rowconfigure(0, weight=1)
        body_frame.columnconfigure(0, weight=1)
        body = tk.Text(body_frame, wrap="word")
        body_font_size = 10

        def apply_body_font_size() -> None:
            body.configure(font=("TkDefaultFont", body_font_size, "normal"))
            body.tag_configure("selected_context", foreground="#2e7d32", font=("TkDefaultFont", body_font_size, "bold"))
            body.tag_configure("nearby_context", foreground="#9a7800", font=("TkDefaultFont", body_font_size, "bold"))
            body.tag_configure("keyword_context", font=("TkDefaultFont", body_font_size, "bold"))

        def change_body_font_size(delta: int) -> None:
            nonlocal body_font_size
            body_font_size = max(8, min(24, body_font_size + delta))
            apply_body_font_size()

        ttk.Button(font_controls, text="A-", command=lambda: change_body_font_size(-1)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(font_controls, text="A+", command=lambda: change_body_font_size(1)).pack(side=tk.LEFT)
        apply_body_font_size()
        body_scroll = ttk.Scrollbar(body_frame, orient=tk.VERTICAL, command=body.yview)
        body.configure(yscrollcommand=body_scroll.set)
        body.grid(row=0, column=0, sticky="nsew")
        body_scroll.grid(row=0, column=1, sticky="ns")
        keywords = context_keywords(match_row or context.selected)
        keyword_pattern = re.compile(
            "|".join(re.escape(term) for term in keywords),
            re.IGNORECASE,
        ) if keywords else None

        def insert_body_text(value: str) -> None:
            if keyword_pattern is None:
                body.insert(tk.END, value)
                return
            start = 0
            for match in keyword_pattern.finditer(value):
                body.insert(tk.END, value[start:match.start()])
                body.insert(tk.END, match.group(0), ("keyword_context",))
                start = match.end()
            body.insert(tk.END, value[start:])

        for context_row in context.rows:
            is_selected = context_row.get("evidence_id") == selected.get("evidence_id")
            if is_selected:
                if context.mode == "chapter":
                    heading = display_value(context_row.get("heading") or context_row.get("outline_path"), "no heading")
                    row_page = display_value(context_row.get("page_number"), "unknown")
                    header = f"SELECTED EVIDENCE | {context_row.get('evidence_id')} | p.{row_page} | {heading}\n"
                    body.insert(tk.END, header, ("selected_context",))
                    insert_body_text(clean_display_text(context_row.get("verbatim_text")) + "\n")
                    continue
                marker = "SELECTED EVIDENCE"
            elif context.mode == "chapter":
                insert_body_text(clean_display_text(context_row.get("verbatim_text")) + "\n")
                continue
            else:
                marker = "NEARBY EVIDENCE"
            heading = display_value(context_row.get("heading") or context_row.get("outline_path"), "no heading")
            row_page = display_value(context_row.get("page_number"), "unknown")
            header = f"{marker} | {context_row.get('evidence_id')} | p.{row_page} | {heading}\n"
            body.insert(tk.END, header, ("selected_context",) if is_selected else ("nearby_context",))
            insert_body_text(clean_display_text(context_row.get("verbatim_text")) + "\n\n")
        body.configure(state="disabled")


def main() -> int:
    configure_output()
    root = tk.Tk()
    SemanticSearchApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
