#!/usr/bin/env python3
"""PySide6 desktop GUI for Theologia Search."""

from __future__ import annotations

import sys
import json
import html
import re
import sqlite3
from pathlib import Path

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional GUI dependency.
    print(
        "error: PySide6 is required for qt_gui.py. Install it in the development environment with: "
        "python -m pip install PySide6",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

try:
    from . import periods
    from . import gui as core_gui
    from .common import DEFAULT_GUI_HISTORY_PATH, DEFAULT_INDEX_PATH, DEFAULT_LEXICON_PATH, configure_output, display_text
    from .search import AdvancedSearchCriteria, validate_advanced_criteria
except ImportError:  # pragma: no cover - supports direct script execution.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import periods
    import gui as core_gui
    from common import DEFAULT_GUI_HISTORY_PATH, DEFAULT_INDEX_PATH, DEFAULT_LEXICON_PATH, configure_output, display_text
    from search import AdvancedSearchCriteria, validate_advanced_criteria


COLORS = {
    "app_bg": "#efe5d1",
    "paper": "#fbf7ee",
    "paper_alt": "#f4ecd8",
    "paper_deep": "#eadcc0",
    "ink": "#241917",
    "muted": "#6f6257",
    "line": "#c9b98d",
    "line_dark": "#a88745",
    "oxblood": "#4b0f12",
    "oxblood_dark": "#2d080a",
    "gold": "#c79b48",
    "gold_soft": "#ead7aa",
    "success": "#24a148",
    "error": "#9b1c1c",
}

ASSET_DIR = Path(__file__).resolve().parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"

FONT_DISPLAY = '"Cinzel", "Trajan Pro", "Centaur", "Garamond", "Georgia"'
FONT_SERIF = '"EB Garamond", "Garamond", "Book Antiqua", "Georgia"'
FONT_UI = '"EB Garamond", "Garamond", "Book Antiqua", "Segoe UI"'

PNG_DIR = ASSET_DIR / "png"

PNG_ASSETS = {
    "rule": ("divider_flourish.png", 232, 30),
    "sidebar_rule": ("sidebar_rule.png", 292, 26),
    "footer": ("footer_flourish.png", 167, 30),
    "cross": ("header_cross.png", 58, 68),
    "emblem": ("header_book_seal.png", 160, 102),
    "books": ("books_quill.png", 271, 146),
    "search": ("search_icon.png", 40, 40),
    "clock": ("clock_icon.png", 18, 18),
    "tag": ("tag_icon.png", 28, 28),
    "book": ("open_book_icon.png", 40, 34),
    "feather": ("feather_icon.png", 41, 45),
    "ribbon": ("bookmark_ribbon.png", 40, 65),
    "chevron": ("dropdown_chevron.png", 30, 29),
    "corner": ("corner_frame.png", 46, 46),
    "header_texture": ("header_texture.png", 1568, 116),
    "paper_texture": ("paper_texture.png", 900, 900),
    "title_text": ("title_text.png", 521, 63),
    "tagline_text": ("tagline_text.png", 377, 61),
    "search_button": ("search_button.png", 232, 63),
    "advance_button": ("advance_button.png", 232, 63),
}

_PROJECT_FONTS_LOADED = False


def load_project_fonts() -> None:
    global _PROJECT_FONTS_LOADED
    if _PROJECT_FONTS_LOADED:
        return
    if QtWidgets.QApplication.instance() is None:
        return
    for path in sorted(FONT_DIR.glob("*.ttf")) + sorted(FONT_DIR.glob("*.otf")):
        QtGui.QFontDatabase.addApplicationFont(str(path))
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.setFont(QtGui.QFont("EB Garamond", 11))
    _PROJECT_FONTS_LOADED = True


APP_STYLESHEET = f"""
QMainWindow {{
    background: {COLORS['app_bg']};
}}
QFrame#Header {{
    background: {COLORS['oxblood']};
    border-bottom: 1px solid {COLORS['gold']};
}}
QLabel#AppTitle {{
    color: {COLORS['gold_soft']};
    font-family: {FONT_DISPLAY};
    font-size: 48px;
    font-weight: 500;
    letter-spacing: 1px;
}}
QLabel#Tagline {{
    color: #fff0d3;
    font-family: {FONT_SERIF};
    font-size: 24px;
    font-style: italic;
}}
QLabel#StatusBadge {{
    color: #fff8e8;
    background: transparent;
    border: none;
    padding: 0 10px 0 0;
    font-family: {FONT_UI};
    font-size: 14px;
    font-weight: 600;
}}
QFrame#StatusPill {{
    background: {COLORS['oxblood_dark']};
    border: 1px solid {COLORS['gold']};
    border-radius: 16px;
}}
QFrame#StatusDot {{
    background: {COLORS['success']};
    border-radius: 5px;
}}
QFrame#Sidebar {{
    background: {COLORS['paper_alt']};
    border: 1px solid {COLORS['line']};
}}
QFrame#SearchBox, QFrame#LimitBox {{
    background: {COLORS['paper']};
    border: 1px solid {COLORS['gold']};
    border-radius: 5px;
}}
QFrame#ResultsPanel {{
    background: {COLORS['paper']};
    border: 1px solid {COLORS['line']};
}}
QLabel#SectionTitle {{
    color: {COLORS['oxblood']};
    font-family: {FONT_SERIF};
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLineEdit, QSpinBox {{
    color: {COLORS['ink']};
    background: transparent;
    border: none;
    selection-background-color: {COLORS['gold_soft']};
    font-family: {FONT_UI};
    font-size: 22px;
}}
QComboBox {{
    color: {COLORS['ink']};
    background: transparent;
    border: none;
    padding: 0;
    font-family: {FONT_UI};
    font-size: 22px;
}}
QComboBox QAbstractItemView {{
    color: {COLORS['ink']};
    background: {COLORS['paper']};
    border: 1px solid {COLORS['line']};
    selection-background-color: {COLORS['gold_soft']};
    font-family: {FONT_UI};
    font-size: 18px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 0;
    border: none;
}}
QPushButton {{
    color: {COLORS['oxblood']};
    background: {COLORS['paper_deep']};
    border: 1px solid {COLORS['line']};
    border-radius: 5px;
    padding: 8px 14px;
    font-family: {FONT_SERIF};
    font-size: 15px;
}}
QPushButton:hover {{
    background: {COLORS['gold_soft']};
}}
QPushButton:pressed {{
    background: {COLORS['paper_alt']};
}}
QPushButton:disabled {{
    color: {COLORS['muted']};
    background: {COLORS['paper_alt']};
}}
QPushButton#PrimaryButton {{
    color: #fff8e8;
    background: {COLORS['oxblood']};
    border: 1px solid {COLORS['gold']};
    padding: 13px 28px;
    font-size: 25px;
    letter-spacing: 1px;
}}
QPushButton#PrimaryButton:hover {{
    background: {COLORS['oxblood_dark']};
}}
QDialog#AdvancedSearchDialog {{
    background: {COLORS['paper_alt']};
}}
QFrame#AdvancedDialogHeader {{
    background: {COLORS['oxblood']};
    border-bottom: 1px solid {COLORS['gold']};
}}
QLabel#AdvancedDialogTitle {{
    color: {COLORS['gold_soft']};
    font-family: {FONT_DISPLAY};
    font-size: 24px;
    font-weight: 500;
    letter-spacing: 1px;
}}
QLabel#AdvancedDialogSubtitle {{
    color: #fff0d3;
    font-family: {FONT_SERIF};
    font-size: 14px;
    font-style: italic;
}}
QFrame#AdvancedDialogCard {{
    background: {COLORS['paper']};
    border: 1px solid {COLORS['line']};
    border-radius: 6px;
}}
QLabel#AdvancedFieldLabel {{
    color: {COLORS['oxblood']};
    font-family: {FONT_UI};
    font-size: 14px;
    font-weight: 700;
}}
QLineEdit#AdvancedField, QComboBox#AdvancedField {{
    color: {COLORS['ink']};
    background: #fffdf7;
    border: 1px solid {COLORS['line']};
    border-radius: 4px;
    padding: 4px 10px;
    font-family: {FONT_SERIF};
    font-size: 16px;
}}
QLineEdit#AdvancedField:focus, QComboBox#AdvancedField:focus {{
    border: 1px solid {COLORS['gold']};
}}
QComboBox#AdvancedConnector {{
    color: {COLORS['oxblood']};
    background: {COLORS['paper_deep']};
    border: 1px solid {COLORS['line']};
    border-radius: 4px;
    padding: 2px 4px 2px 8px;
    font-family: {FONT_SERIF};
    font-size: 13px;
    font-weight: 600;
}}
QComboBox#AdvancedConnector QAbstractItemView {{
    color: {COLORS['ink']};
    background: {COLORS['paper']};
    font-family: {FONT_SERIF};
    font-size: 13px;
}}
QPushButton#AdvancedCancel, QPushButton#AdvancedStart {{
    min-height: 36px;
    padding: 6px 18px;
    font-family: {FONT_SERIF};
    font-size: 15px;
}}
QPushButton#AdvancedStart {{
    color: #fff8e8;
    background: {COLORS['oxblood']};
    border: 1px solid {COLORS['gold']};
}}
QPushButton#AdvancedStart:hover {{
    background: {COLORS['oxblood_dark']};
}}
QListWidget {{
    color: {COLORS['ink']};
    background: transparent;
    border: none;
    outline: none;
    font-family: {FONT_SERIF};
    font-size: 16px;
}}
QListWidget::item {{
    padding: 9px 10px;
    border-radius: 5px;
}}
QListWidget::item:selected {{
    color: {COLORS['ink']};
    background: {COLORS['gold_soft']};
    border-left: 4px solid {COLORS['oxblood']};
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: {COLORS['paper']};
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['paper_deep']};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLORS['gold_soft']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QFrame#ResultCard {{
    background: #fffdf7;
    border: 1px solid {COLORS['line']};
    border-radius: 6px;
}}
QFrame#ResultCard:hover {{
    border: 1px solid {COLORS['gold']};
    background: #fffaf0;
}}
QFrame#ResultCard[selected="true"] {{
    background: #f4ead3;
    border: 2px solid {COLORS['line_dark']};
}}
QLabel#ResultTitle {{
    color: {COLORS['oxblood']};
    font-family: {FONT_SERIF};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#FieldLabel {{
    color: {COLORS['oxblood']};
    font-family: {FONT_UI};
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#FieldValue {{
    color: {COLORS['ink']};
    font-family: {FONT_UI};
    font-size: 14px;
}}
QLabel#Snippet {{
    color: {COLORS['ink']};
    font-family: {FONT_SERIF};
    font-size: 17px;
    line-height: 140%;
}}
QLabel#Chip {{
    color: {COLORS['ink']};
    background: #f3ead4;
    border: 1px solid {COLORS['line']};
    border-radius: 5px;
    padding: 4px 8px;
    font-family: {FONT_SERIF};
    font-size: 15px;
}}
QLabel#EmptyState {{
    color: {COLORS['muted']};
    font-family: {FONT_SERIF};
    font-size: 18px;
    font-style: italic;
}}
QTextEdit {{
    color: {COLORS['ink']};
    background: {COLORS['paper']};
    border: 1px solid {COLORS['line']};
    border-radius: 5px;
    selection-background-color: {COLORS['gold_soft']};
    font-family: {FONT_SERIF};
    font-size: 16px;
}}
"""


class ImageAsset(QtWidgets.QWidget):
    def __init__(self, name: str, *, width: int | None = None, height: int | None = None, parent=None):
        super().__init__(parent)
        filename, default_width, default_height = PNG_ASSETS[name]
        self.path = PNG_DIR / filename
        self.pixmap = QtGui.QPixmap(str(self.path))
        self.asset_width = width or default_width
        self.asset_height = height or default_height
        self.setFixedSize(self.asset_width, self.asset_height)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override.
        if self.pixmap.isNull():
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self.pixmap, self.pixmap.rect())


class ImageButton(QtWidgets.QToolButton):
    def __init__(self, name: str, tooltip: str, parent=None):
        super().__init__(parent)
        filename, width, height = PNG_ASSETS[name]
        self.setIcon(QtGui.QIcon(str(PNG_DIR / filename)))
        self.setIconSize(QtCore.QSize(width, height))
        self.setFixedSize(width + 8, height + 8)
        self.setToolTip(tooltip)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            "QToolButton { background: transparent; border: none; padding: 0; }"
            f"QToolButton:hover {{ background: {COLORS['gold_soft']}; border-radius: 4px; }}"
        )


class HeaderFrame(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.texture_pixmap = QtGui.QPixmap(str(PNG_DIR / PNG_ASSETS["header_texture"][0]))

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt override.
        super().paintEvent(event)
        if not self.texture_pixmap.isNull():
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(self.rect(), self.texture_pixmap, self.texture_pixmap.rect())


class CornerPanel(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.paper_pixmap = QtGui.QPixmap(str(PNG_DIR / PNG_ASSETS["paper_texture"][0]))
        self.corner_pixmap = QtGui.QPixmap(str(PNG_DIR / PNG_ASSETS["corner"][0]))

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt override.
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        if not self.paper_pixmap.isNull():
            painter.drawPixmap(self.rect(), self.paper_pixmap, self.paper_pixmap.rect())
        if self.corner_pixmap.isNull():
            return
        size = PNG_ASSETS["corner"][1]
        target = QtCore.QRect(8, 8, size, size)
        painter.drawPixmap(target, self.corner_pixmap, self.corner_pixmap.rect())
        painter.save()
        painter.translate(self.width() - 8, 8)
        painter.scale(-1, 1)
        painter.drawPixmap(QtCore.QRect(0, 0, size, size), self.corner_pixmap, self.corner_pixmap.rect())
        painter.restore()
        painter.save()
        painter.translate(8, self.height() - 8)
        painter.scale(1, -1)
        painter.drawPixmap(QtCore.QRect(0, 0, size, size), self.corner_pixmap, self.corner_pixmap.rect())
        painter.restore()
        painter.save()
        painter.translate(self.width() - 8, self.height() - 8)
        painter.scale(-1, -1)
        painter.drawPixmap(QtCore.QRect(0, 0, size, size), self.corner_pixmap, self.corner_pixmap.rect())
        painter.restore()


class DecoratedButton(QtWidgets.QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        asset_name = "advance_button" if text.casefold() == "advance" else "search_button"
        self.asset_name = asset_name
        self.button_pixmap = QtGui.QPixmap(str(PNG_DIR / PNG_ASSETS[asset_name][0]))
        self.setText("")
        self.setToolTip(text.title())
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt override.
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        if not self.button_pixmap.isNull():
            painter.drawPixmap(self.rect(), self.button_pixmap, self.button_pixmap.rect())
        if not self.isEnabled():
            painter.fillRect(self.rect(), QtGui.QColor(239, 229, 207, 120))


class BookmarkRibbon(QtWidgets.QWidget):
    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self.number = number
        self.pixmap = QtGui.QPixmap(str(PNG_DIR / PNG_ASSETS["ribbon"][0]))
        self.setFixedSize(PNG_ASSETS["ribbon"][1], PNG_ASSETS["ribbon"][2])

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override.
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        if not self.pixmap.isNull():
            painter.drawPixmap(self.rect(), self.pixmap, self.pixmap.rect())
        painter.setPen(QtGui.QColor("#fff8e8"))
        font = QtGui.QFont("EB Garamond", 15)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QtCore.QRectF(0, 7, self.width(), 32), QtCore.Qt.AlignmentFlag.AlignCenter, str(self.number))


class IconListRow(QtWidgets.QWidget):
    def __init__(self, icon_name: str, text: str, count: int | None = None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)
        if icon_name == "clock":
            layout.addWidget(ImageAsset(icon_name, width=18, height=18))
        else:
            layout.addWidget(ImageAsset(icon_name))
        label = QtWidgets.QLabel(text)
        label.setObjectName("FieldValue")
        label.setStyleSheet(f"font-family: {FONT_SERIF}; font-size: 16px;")
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        layout.addWidget(label, 1)
        if count is not None:
            count_label = QtWidgets.QLabel(str(count))
            count_label.setStyleSheet(f"color: {COLORS['line_dark']}; font-family: {FONT_SERIF}; font-size: 16px;")
            layout.addWidget(count_label)


class ChipRow(QtWidgets.QWidget):
    def __init__(self, values: list[str], parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for value in values[:6]:
            chip = QtWidgets.QLabel(display_text(value))
            chip.setObjectName("Chip")
            layout.addWidget(chip)
        layout.addStretch(1)


class FieldLine(QtWidgets.QWidget):
    def __init__(
        self,
        label: str,
        value: str | QtWidgets.QWidget,
        *,
        label_width: int = 106,
        max_value_height: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(0)
        key = QtWidgets.QLabel(f"{label.upper()}:")
        key.setObjectName("FieldLabel")
        key.setFixedWidth(label_width)
        layout.addWidget(key, 0, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        if isinstance(value, QtWidgets.QWidget):
            layout.addWidget(value, 0, 1)
        else:
            val = QtWidgets.QLabel(value)
            val.setObjectName("FieldValue")
            val.setWordWrap(True)
            if max_value_height is not None:
                val.setMaximumHeight(max_value_height)
            layout.addWidget(val, 0, 1)


def result_field_map(row: dict) -> dict[str, str]:
    values = {}
    for kind, label, value in core_gui.result_fields(1, row):
        if kind != "title" and label:
            values[label] = value
    return values


def clipped_text(value: str, max_chars: int) -> str:
    normalized = " ".join(display_text(value).split())
    if len(normalized) <= max_chars:
        return normalized
    clipped = normalized[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{clipped}..."


def snippet_html(value: str, max_chars: int = 180) -> str:
    parts = []
    for segment, is_match in core_gui.snippet_segments(value, max_chars):
        escaped = html.escape(segment)
        parts.append(f"<b>{escaped}</b>" if is_match else escaped)
    return "".join(parts)


class AdvancedSearchDialog(QtWidgets.QDialog):
    PERIOD_OPTIONS = (
        ("All periods", ""),
        ("Before Council of Nicaea", "before_nicene"),
        ("After Nicene but before Reformation", "nicene_to_reformation"),
        ("After Reformation", "post_reformation"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.criteria: AdvancedSearchCriteria | None = None
        self.setObjectName("AdvancedSearchDialog")
        self.setWindowTitle("Advanced Search")
        self.setModal(True)
        self.resize(700, 520)
        self.setMinimumSize(620, 460)
        self.setStyleSheet(APP_STYLESHEET)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = HeaderFrame()
        header.setObjectName("AdvancedDialogHeader")
        header.setFixedHeight(78)
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(24, 8, 24, 8)
        header_layout.setSpacing(14)
        header_layout.addWidget(ImageAsset("cross", width=34, height=40))
        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(0)
        title = QtWidgets.QLabel("ADVANCED SEARCH")
        title.setObjectName("AdvancedDialogTitle")
        subtitle = QtWidgets.QLabel("Search the indexed collection by concept and citation metadata")
        subtitle.setObjectName("AdvancedDialogSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(ImageAsset("rule", width=160, height=22))
        layout.addWidget(header)

        card = CornerPanel()
        card.setObjectName("AdvancedDialogCard")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 18)
        card_layout.setSpacing(12)
        intro = QtWidgets.QLabel("Combine any fields with the compact AND / OR selectors.")
        intro.setObjectName("AdvancedDialogSubtitle")
        intro.setStyleSheet(f"color: {COLORS['muted']};")
        card_layout.addWidget(intro)

        form = QtWidgets.QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        card_layout.addLayout(form)
        self.fields: dict[str, QtWidgets.QWidget] = {}
        self.connectors: dict[str, QtWidgets.QComboBox] = {}
        field_rows = (
            ("concept", "Concept or phrase"),
            ("author", "Author name"),
            ("mentioned_author", "Mentioned author"),
            ("period_id", "Author time period"),
            ("book", "Book name"),
            ("chapter", "Chapter"),
        )
        for row_index, (field, label_text) in enumerate(field_rows):
            if row_index:
                connector = QtWidgets.QComboBox()
                connector.addItems(["AND", "OR"])
                connector.setObjectName("AdvancedConnector")
                connector.setFixedSize(72, 32)
                connector.setFont(QtGui.QFont("EB Garamond", 13))
                self.connectors[field] = connector
                form.addWidget(connector, row_index, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            label = QtWidgets.QLabel(label_text)
            label.setObjectName("AdvancedFieldLabel")
            form.addWidget(label, row_index, 1)
            if field == "period_id":
                widget = QtWidgets.QComboBox()
                for visible, value in self.PERIOD_OPTIONS:
                    widget.addItem(visible, value)
            elif field in {"author", "mentioned_author"}:
                widget = QtWidgets.QComboBox()
                widget.addItem("All authors", "")
                for author_name in periods.registered_author_names():
                    widget.addItem(author_name, author_name)
            else:
                widget = QtWidgets.QLineEdit()
                if field == "concept":
                    widget.setPlaceholderText("Concept, phrase, place, person, or doctrine")
            widget.setObjectName("AdvancedField")
            widget.setFixedHeight(36)
            widget.setFont(QtGui.QFont("EB Garamond", 16))
            form.addWidget(widget, row_index, 2)
            self.fields[field] = widget
        form.setColumnMinimumWidth(0, 72)
        form.setColumnMinimumWidth(1, 150)
        form.setColumnStretch(2, 1)

        card_layout.addWidget(ImageAsset("sidebar_rule", width=300, height=20), 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.setObjectName("AdvancedCancel")
        cancel.setFixedSize(110, 38)
        start = QtWidgets.QPushButton("Start Advanced Search")
        start.setObjectName("AdvancedStart")
        start.setFixedSize(190, 38)
        cancel.clicked.connect(self.reject)
        start.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(start)
        card_layout.addLayout(buttons)
        layout.addWidget(card, 1)

    def _submit(self) -> None:
        def field_text(field: str) -> str:
            widget = self.fields[field]
            if isinstance(widget, QtWidgets.QComboBox):
                return str(widget.currentData() or "")
            return widget.text()  # type: ignore[union-attr]

        period_combo = self.fields["period_id"]
        assert isinstance(period_combo, QtWidgets.QComboBox)
        criteria = AdvancedSearchCriteria(
            concept=field_text("concept"),
            author=field_text("author"),
            mentioned_author=field_text("mentioned_author"),
            period_id=str(period_combo.currentData() or ""),
            book=field_text("book"),
            chapter=field_text("chapter"),
            connectors=tuple(self.connectors[field].currentText() for field in ("author", "mentioned_author", "period_id", "book", "chapter")),
        )
        try:
            self.criteria = validate_advanced_criteria(criteria)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Advanced Search", str(exc))
            return
        self.accept()


class SearchWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        query: str = "",
        limit: int = 10,
        index_path: Path | None = None,
        lexicon_path: Path | None = None,
        *,
        criteria: AdvancedSearchCriteria | None = None,
        period_sections: bool = True,
    ):
        super().__init__()
        self.query = query
        self.criteria = criteria
        self.limit = limit
        self.index_path = index_path or DEFAULT_INDEX_PATH
        self.lexicon_path = lexicon_path or DEFAULT_LEXICON_PATH
        self.period_sections = period_sections

    @QtCore.Slot()
    def run(self) -> None:
        try:
            if self.criteria is not None:
                output = core_gui.run_advanced_search(
                    self.criteria,
                    limit=self.limit,
                    index_path=self.index_path,
                    lexicon_path=self.lexicon_path,
                    period_sections=self.period_sections,
                )
            else:
                output = core_gui.run_search(
                    self.query,
                    limit=self.limit,
                    index_path=self.index_path,
                    lexicon_path=self.lexicon_path,
                    period_sections=self.period_sections,
                )
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(output)


class PeriodHeader(QtWidgets.QFrame):
    def __init__(self, title: str, count: int):
        super().__init__()
        self.setObjectName("PeriodHeader")
        # Keep all period result bodies aligned even when heading font sizes differ.
        self.setFixedHeight(64)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        if title.startswith("After Council of Nicaea, before Reformation"):
            title = title.replace(", before Reformation", ",\nbefore Reformation", 1)
        title_font_size = 17 if title.startswith("After Council of Nicaea,") else 20
        if " (" in title and "\n" not in title:
            title = title.replace(" (", "\n(", 1)
        label = QtWidgets.QLabel(title)
        label.setWordWrap(True)
        label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        label.setStyleSheet(f"color: {COLORS['oxblood']}; font-family: {FONT_SERIF}; font-size: {title_font_size}px; font-weight: 600;")
        layout.addWidget(label)
        layout.addStretch(1)
        count_label = QtWidgets.QLabel(f"{count} result{'s' if count != 1 else ''}")
        count_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignRight)
        count_label.setStyleSheet(f"color: {COLORS['muted']}; font-family: {FONT_UI}; font-size: 13px;")
        layout.addWidget(count_label)


class PeriodColumn(QtWidgets.QFrame):
    def __init__(self, title: str, count: int):
        super().__init__()
        self.setObjectName("PeriodColumn")
        # Keep each historical column at the reference width so text changes do
        # not resize cards or move the neighboring columns.
        self.setFixedWidth(350)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Expanding)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(PeriodHeader(title, count))

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setStyleSheet(f"background: {COLORS['paper']};")
        host = QtWidgets.QWidget()
        host.setStyleSheet(f"background: {COLORS['paper']};")
        self.body_layout = QtWidgets.QVBoxLayout(host)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(12)
        self.body_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)


class ResultCard(QtWidgets.QFrame):
    selected = QtCore.Signal(int)
    double_clicked = QtCore.Signal(int)
    read_clicked = QtCore.Signal(int)

    def __init__(self, index: int, row: dict, display_number: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("ResultCard")
        self.setProperty("selected", False)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)

        self.setMinimumHeight(280)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QtGui.QColor(70, 47, 20, 45))
        self.setGraphicsEffect(shadow)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 14, 14)
        outer.setSpacing(10)

        values = result_field_map(row)
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(8)
        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(8)
        read_button = QtWidgets.QPushButton("READ FULL TEXT")
        read_button.setToolTip("Open this result's full chapter")
        read_button.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        read_button.clicked.connect(lambda _checked=False, idx=index: self.read_clicked.emit(idx))
        actions.addWidget(read_button)
        top_row.addLayout(actions, 1)
        top_row.addWidget(BookmarkRibbon(display_number), 0, QtCore.Qt.AlignmentFlag.AlignTop)
        outer.addLayout(top_row)

        details = QtWidgets.QVBoxLayout()
        details.setSpacing(7)
        if values.get("Source"):
            details.addWidget(FieldLine("Source", clipped_text(values["Source"], 72), label_width=74, max_value_height=42))
        if values.get("Author"):
            details.addWidget(FieldLine("Author", clipped_text(values["Author"], 58), label_width=74, max_value_height=28))
        if values.get("Mentioned"):
            details.addWidget(FieldLine("Mentioned", clipped_text(values["Mentioned"], 58), label_width=74, max_value_height=28))
        if values.get("Heading"):
            details.addWidget(FieldLine("Heading", clipped_text(values["Heading"], 76), label_width=74, max_value_height=44))
        details.addWidget(FieldLine("Quality", self._quality_widget(values.get("Quality", "")), label_width=74))
        outer.addLayout(details)

        if values.get("Snippet"):
            snippet_label = QtWidgets.QLabel("SNIPPET:")
            snippet_label.setObjectName("FieldLabel")
            outer.addWidget(snippet_label)
            snippet = QtWidgets.QLabel()
            snippet.setObjectName("Snippet")
            snippet.setTextFormat(QtCore.Qt.TextFormat.RichText)
            snippet.setText(snippet_html(values["Snippet"], 180))
            snippet.setWordWrap(True)
            snippet.setMaximumHeight(96)
            outer.addWidget(snippet)
        outer.addStretch(1)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _quality_widget(self, quality: str) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        normalized = quality.casefold()
        if normalized in {"excellent", "5"}:
            stars = "★★★★★"
        elif normalized in {"strong", "4"}:
            stars = "★★★★☆"
        elif normalized in {"good", "moderate", "3"}:
            stars = "★★★☆☆"
        elif normalized in {"related", "2"}:
            stars = "★★☆☆☆"
        elif normalized in {"weak", "1"}:
            stars = "★☆☆☆☆"
        else:
            stars = quality
        star_label = QtWidgets.QLabel(stars)
        star_label.setStyleSheet(f"color: {COLORS['line_dark']}; font-family: {FONT_SERIF}; font-size: 17px;")
        layout.addWidget(star_label)
        detail = QtWidgets.QLabel(quality)
        detail.setObjectName("FieldValue")
        layout.addWidget(detail, 1)
        return widget

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802 - Qt override.
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.selected.emit(self.index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802 - Qt override.
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.selected.emit(self.index)
            self.double_clicked.emit(self.index)
        super().mouseDoubleClickEvent(event)


class ContextDialog(QtWidgets.QDialog):
    def __init__(self, context: core_gui.ContextOutput, parent=None, *, match_row: dict | None = None):
        super().__init__(parent)
        selected = context.selected
        source_id = core_gui.display_value(selected.get("source_id"), "unknown source")
        evidence_id = core_gui.display_value(selected.get("evidence_id"), "unknown evidence")
        self.setWindowTitle(f"{source_id} p.{context.page_range} | {evidence_id} | {context.heading}")
        self.resize(980, 720)
        self.setMinimumSize(720, 500)
        self.setStyleSheet(APP_STYLESHEET)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        meta = QtWidgets.QFrame()
        meta.setObjectName("ResultCard")
        meta_layout = QtWidgets.QGridLayout(meta)
        meta_layout.setContentsMargins(18, 14, 18, 14)
        meta_layout.setHorizontalSpacing(16)
        meta_layout.setVerticalSpacing(6)
        rows = [
            ("Source", source_id),
            ("Title", core_gui.display_value(selected.get("source_title"), "unknown")),
            ("Author", core_gui.display_value(selected.get("author"), "Unknown")),
            ("Mentioned authors", ", ".join(selected.get("mentioned_authors") or []) or "none"),
            ("Page range", context.page_range),
            ("Evidence", evidence_id),
            ("Heading", context.heading),
            (
                "Context",
                f"Complete chapter across {len(context.rows)} indexed row(s)"
                if context.mode == "chapter"
                else f"Nearby fallback: {context.before_word_count} words before, {context.after_word_count} words after",
            ),
        ]
        for row_index, (label, value) in enumerate(rows):
            key = QtWidgets.QLabel(f"{label.upper()}:")
            key.setObjectName("FieldLabel")
            val = QtWidgets.QLabel(value)
            val.setObjectName("FieldValue")
            val.setWordWrap(True)
            meta_layout.addWidget(key, row_index, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            meta_layout.addWidget(val, row_index, 1)
        layout.addWidget(meta)

        body = QtWidgets.QTextEdit()
        body.setReadOnly(True)
        self._populate_context_body(body, context, match_row or selected)
        self.body = body
        self.body_font_size = 16
        QtCore.QTimer.singleShot(0, self._scroll_to_selected_evidence)

        font_controls = QtWidgets.QHBoxLayout()
        font_controls.addStretch(1)
        smaller = QtWidgets.QPushButton("A-")
        smaller.setToolTip("Decrease full-text font size")
        smaller.clicked.connect(lambda: self._change_body_font_size(-1))
        larger = QtWidgets.QPushButton("A+")
        larger.setToolTip("Increase full-text font size")
        larger.clicked.connect(lambda: self._change_body_font_size(1))
        font_controls.addWidget(smaller)
        font_controls.addWidget(larger)
        layout.addLayout(font_controls)
        layout.addWidget(body, 1)

    def _scroll_to_selected_evidence(self) -> None:
        """Open the context viewer with the selected evidence line at the top."""
        cursor = self.body.document().find("SELECTED EVIDENCE")
        if cursor.isNull():
            return
        cursor.setPosition(cursor.selectionStart())
        self.body.setTextCursor(cursor)
        self.body.ensureCursorVisible()
        cursor_top = self.body.cursorRect(cursor).top()
        scroll_bar = self.body.verticalScrollBar()
        scroll_bar.setValue(max(0, scroll_bar.value() + cursor_top - 8))

    def _change_body_font_size(self, delta: int) -> None:
        self.body_font_size = max(10, min(30, self.body_font_size + delta))
        cursor = self.body.textCursor()
        cursor.select(QtGui.QTextCursor.SelectionType.Document)
        char_format = QtGui.QTextCharFormat()
        char_format.setFontPointSize(self.body_font_size)
        cursor.mergeCharFormat(char_format)
        cursor.clearSelection()
        self.body.setTextCursor(cursor)

    def _populate_context_body(
        self,
        body: QtWidgets.QTextEdit,
        context: core_gui.ContextOutput,
        match_row: dict,
    ) -> None:
        cursor = body.textCursor()
        keywords = core_gui.context_keywords(match_row)
        keyword_pattern = re.compile(
            "|".join(re.escape(term) for term in keywords),
            re.IGNORECASE,
        ) if keywords else None

        normal_format = QtGui.QTextCharFormat()
        keyword_format = QtGui.QTextCharFormat()
        keyword_format.setFontWeight(QtGui.QFont.Weight.Bold)
        selected_format = QtGui.QTextCharFormat()
        selected_format.setForeground(QtGui.QColor("#2e7d32"))
        selected_format.setFontWeight(QtGui.QFont.Weight.Bold)
        nearby_format = QtGui.QTextCharFormat()
        nearby_format.setForeground(QtGui.QColor("#9a7800"))
        nearby_format.setFontWeight(QtGui.QFont.Weight.Bold)

        def insert_text(value: str) -> None:
            if keyword_pattern is None:
                cursor.insertText(value, normal_format)
                return
            start = 0
            for match in keyword_pattern.finditer(value):
                cursor.insertText(value[start:match.start()], normal_format)
                cursor.insertText(match.group(0), keyword_format)
                start = match.end()
            cursor.insertText(value[start:], normal_format)

        selected_id = context.selected.get("evidence_id")
        for context_row in context.rows:
            is_selected = context_row.get("evidence_id") == selected_id
            if is_selected:
                heading = core_gui.display_value(context_row.get("heading") or context_row.get("outline_path"), "no heading")
                page = core_gui.display_value(context_row.get("page_number"), "unknown")
                header = f"SELECTED EVIDENCE | {context_row.get('evidence_id')} | p.{page} | {heading}\n"
                cursor.insertText(header, selected_format)
                insert_text(core_gui.clean_display_text(context_row.get("verbatim_text")) + "\n")
                continue
            if context.mode == "chapter":
                insert_text(core_gui.clean_display_text(context_row.get("verbatim_text")) + "\n")
                continue
            heading = core_gui.display_value(context_row.get("heading") or context_row.get("outline_path"), "no heading")
            page = core_gui.display_value(context_row.get("page_number"), "unknown")
            header = f"NEARBY EVIDENCE | {context_row.get('evidence_id')} | p.{page} | {heading}\n"
            cursor.insertText(header, nearby_format)
            insert_text(core_gui.clean_display_text(context_row.get("verbatim_text")) + "\n\n")


class ExplanationDialog(QtWidgets.QDialog):
    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Why this result?")
        self.resize(720, 540)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        title = QtWidgets.QLabel(core_gui.display_value(row.get("evidence_id"), "Result explanation"))
        title.setStyleSheet(f"color: {COLORS['oxblood']}; font-family: {FONT_SERIF}; font-size: 24px; font-weight: 600;")
        layout.addWidget(title)

        text = QtWidgets.QTextEdit()
        text.setReadOnly(True)
        lines = []
        for label, value in core_gui.result_explanation_lines(row):
            lines.append(f"{label}: {value}")
        text.setPlainText("\n\n".join(lines))
        layout.addWidget(text, 1)

        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, QtCore.Qt.AlignmentFlag.AlignRight)


class TheologiaSearchWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        *,
        history_path: Path = DEFAULT_GUI_HISTORY_PATH,
        index_path: Path = DEFAULT_INDEX_PATH,
        lexicon_path: Path = DEFAULT_LEXICON_PATH,
    ):
        super().__init__()
        self.history_path = history_path
        self.index_path = index_path
        self.lexicon_path = lexicon_path
        self.history = core_gui.load_history(history_path)
        self.current_results: list[dict] = []
        self.result_cards: list[ResultCard] = []
        self.selected_result_index: int | None = None
        self.thread: QtCore.QThread | None = None
        self.worker: SearchWorker | None = None
        self.current_advanced_criteria: AdvancedSearchCriteria | None = None

        load_project_fonts()
        self.setWindowTitle("Theologia Search")
        self.resize(1568, 1003)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        self._refresh_history()
        self._set_status("Ready")

    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        root_layout = QtWidgets.QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 8)
        root_layout.setSpacing(0)

        header = HeaderFrame()
        header.setObjectName("Header")
        header.setFixedHeight(116)
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(40, 4, 36, 4)
        header_layout.setSpacing(24)

        header_layout.addWidget(ImageAsset("title_text"))

        divider = QtWidgets.QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background: {COLORS['gold']};")
        header_layout.addWidget(divider)

        header_layout.addWidget(ImageAsset("cross"))

        header_layout.addWidget(ImageAsset("tagline_text"), 1)
        header_layout.addWidget(ImageAsset("emblem"))

        status_pill = QtWidgets.QFrame()
        status_pill.setObjectName("StatusPill")
        status_pill.setFixedSize(146, 40)
        status_layout = QtWidgets.QHBoxLayout(status_pill)
        status_layout.setContentsMargins(12, 7, 14, 7)
        status_layout.setSpacing(8)
        self.status_dot = QtWidgets.QFrame()
        self.status_dot.setObjectName("StatusDot")
        self.status_dot.setFixedSize(10, 10)
        status_layout.addWidget(self.status_dot)
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setObjectName("StatusBadge")
        self.status_label.setFixedWidth(100)
        status_layout.addWidget(self.status_label)
        header_layout.addWidget(status_pill, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        root_layout.addWidget(header)

        main = QtWidgets.QHBoxLayout()
        main.setContentsMargins(4, 0, 4, 0)
        main.setSpacing(0)
        root_layout.addLayout(main, 1)

        sidebar = CornerPanel()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(363)
        sidebar.setMaximumWidth(363)
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 18, 18, 18)
        sidebar_layout.setSpacing(8)
        main.addWidget(sidebar)

        history_header = QtWidgets.QHBoxLayout()
        history_header.addWidget(self._section_title("SEARCH HISTORY"), 1)
        clear_history = ImageButton("feather", "Clear search history")
        clear_history.clicked.connect(self.clear_search_history)
        history_header.addWidget(clear_history)
        sidebar_layout.addLayout(history_header)
        sidebar_layout.addWidget(ImageAsset("sidebar_rule"), 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.history_list = QtWidgets.QListWidget()
        self.history_list.setSpacing(6)
        self.history_list.itemClicked.connect(self._search_history_item)
        sidebar_layout.addWidget(self.history_list, 1)
        sidebar_layout.addWidget(ImageAsset("books"), 0, QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignBottom)

        content = QtWidgets.QVBoxLayout()
        content.setContentsMargins(38, 36, 28, 0)
        content.setSpacing(14)
        main.addLayout(content, 1)

        search_row = QtWidgets.QHBoxLayout()
        search_row.setSpacing(14)
        content.addLayout(search_row)

        search_box = QtWidgets.QFrame()
        search_box.setObjectName("SearchBox")
        search_box.setFixedHeight(63)
        search_box.setFixedWidth(678)
        search_box_layout = QtWidgets.QHBoxLayout(search_box)
        search_box_layout.setContentsMargins(16, 6, 16, 6)
        search_box_layout.setSpacing(12)
        search_box_layout.addWidget(ImageAsset("search"))
        self.query_entry = QtWidgets.QLineEdit()
        self.query_entry.setPlaceholderText("Search a concept, phrase, place, person, or doctrine")
        self.query_entry.returnPressed.connect(self.start_search)
        search_box_layout.addWidget(self.query_entry)
        search_row.addWidget(search_box, 1)

        limit_box = QtWidgets.QFrame()
        limit_box.setObjectName("LimitBox")
        limit_box.setFixedHeight(63)
        limit_box.setFixedWidth(140)
        limit_layout = QtWidgets.QHBoxLayout(limit_box)
        limit_layout.setContentsMargins(12, 4, 8, 4)
        limit_layout.setSpacing(6)
        limit_label = QtWidgets.QLabel("LIMIT")
        limit_label.setObjectName("FieldLabel")
        limit_layout.addWidget(limit_label)
        self.limit_combo = QtWidgets.QComboBox()
        self.limit_combo.addItems(["5", "10", "15", "20", "25"])
        default_limit = str(core_gui.DEFAULT_LIMIT)
        default_index = self.limit_combo.findText(default_limit)
        self.limit_combo.setCurrentIndex(default_index if default_index >= 0 else 1)
        limit_layout.addWidget(self.limit_combo, 1)
        search_row.addWidget(limit_box)

        self.search_button = DecoratedButton("SEARCH")
        self.search_button.setObjectName("PrimaryButton")
        self.search_button.setFixedSize(180, 52)
        self.search_button.clicked.connect(self.start_search)
        search_row.addWidget(self.search_button)

        self.advance_button = DecoratedButton("ADVANCE")
        self.advance_button.setObjectName("PrimaryButton")
        self.advance_button.setFixedSize(180, 52)
        self.advance_button.clicked.connect(self.open_advanced_search)
        search_row.addWidget(self.advance_button)

        results_panel = CornerPanel()
        results_panel.setObjectName("ResultsPanel")
        results_panel_layout = QtWidgets.QVBoxLayout(results_panel)
        results_panel_layout.setContentsMargins(18, 16, 18, 16)
        results_panel_layout.setSpacing(12)
        content.addWidget(results_panel, 1)

        results_header = QtWidgets.QHBoxLayout()
        self.results_count_label = QtWidgets.QLabel("Results")
        self.results_count_label.setStyleSheet(f"color: {COLORS['oxblood']}; font-family: {FONT_SERIF}; font-size: 26px;")
        results_header.addWidget(self.results_count_label)
        results_header.addWidget(ImageAsset("rule"), 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        results_header.addStretch(1)
        hint = QtWidgets.QLabel("Select a result, then read full text")
        hint.setStyleSheet(f"color: {COLORS['muted']}; font-family: {FONT_UI}; font-size: 13px;")
        results_header.addWidget(hint)
        results_panel_layout.addLayout(results_header)

        self.results_scroll = QtWidgets.QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_host = QtWidgets.QWidget()
        self.results_host.setStyleSheet(f"background: {COLORS['paper']};")
        self.results_layout = QtWidgets.QHBoxLayout(self.results_host)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(12)
        self.results_host.setFixedWidth(3 * 350 + 24)
        self.results_scroll.setWidget(self.results_host)
        self.results_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.results_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_scroll.viewport().setStyleSheet(f"background: {COLORS['paper']};")
        results_panel_layout.addWidget(self.results_scroll, 1)

        footer_row = QtWidgets.QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(14)
        footer_row.addStretch(1)
        footer_row.addWidget(ImageAsset("footer"))
        footer = QtWidgets.QLabel("Scripture is primary. Theology is derived. Soli Deo Gloria.")
        footer.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(f"color: {COLORS['muted']}; font-family: {FONT_SERIF}; font-size: 17px; font-style: italic;")
        footer_row.addWidget(footer)
        footer_row.addWidget(ImageAsset("footer"))
        footer_row.addStretch(1)
        root_layout.addLayout(footer_row)

        self._render_empty_results("Type a query above to begin.")

    def _section_title(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.setText(text)
        color = COLORS["error"] if error else COLORS["success"]
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 5px;")

    def _set_search_status(self) -> None:
        if self.current_results:
            self._set_status(f"{len(self.current_results)} results")
        else:
            self._set_status("Ready")

    def _refresh_history(self) -> None:
        self.history_list.clear()
        self.history_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.history_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for query in self.history:
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.ItemDataRole.UserRole, query)
            item.setSizeHint(QtCore.QSize(0, 40))
            self.history_list.addItem(item)
            self.history_list.setItemWidget(item, IconListRow("clock", query))

    def _clear_results_layout(self) -> None:
        self.result_cards = []
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_empty_results(self, message: str) -> None:
        self._clear_results_layout()
        self.selected_result_index = None
        self.results_count_label.setText("Results")
        label = QtWidgets.QLabel(message)
        label.setObjectName("EmptyState")
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.results_layout.addWidget(label, 1)

    def _add_result_card(
        self,
        layout: QtWidgets.QVBoxLayout,
        result_index: int,
        row: dict,
        display_number: int,
    ) -> None:
        card = ResultCard(result_index, row, display_number)
        card.selected.connect(self.select_result)
        card.double_clicked.connect(self.open_result)
        card.read_clicked.connect(self.open_result)
        stretch = layout.takeAt(layout.count() - 1)
        layout.addWidget(card)
        if stretch is not None:
            layout.addItem(stretch)
        self.result_cards.append(card)

    def _render_results(self, results: list[dict], period_groups: list[dict] | None = None) -> None:
        self._clear_results_layout()
        self.selected_result_index = None
        if not results:
            self._render_empty_results("No results found.")
            return
        self.results_count_label.setText(f"{len(results)} results")
        if period_groups:
            groups_by_period = {group.get("period_id"): group for group in period_groups}
            columns: dict[str, PeriodColumn] = {}
            for period_id in (periods.PRE_NICENE, periods.NICENE_TO_REFORMATION, periods.POST_REFORMATION):
                group = groups_by_period.get(period_id, {})
                group_results = group.get("results") or []
                column = PeriodColumn(periods.PERIOD_LABELS[period_id], len(group_results))
                columns[period_id] = column
                self.results_layout.addWidget(column, 1)

            result_index = 0
            column_numbers = {period_id: 0 for period_id in columns}
            for group in period_groups:
                period_id = group.get("period_id")
                group_results = group.get("results") or []
                if period_id in columns:
                    target_layout = columns[period_id].body_layout
                else:
                    target_layout = columns[periods.POST_REFORMATION].body_layout
                    if group_results:
                        stretch = target_layout.takeAt(target_layout.count() - 1)
                        target_layout.addWidget(PeriodHeader(group.get("period_label", "Unclassified"), len(group_results)))
                        if stretch is not None:
                            target_layout.addItem(stretch)
                if not group_results:
                    continue
                for row in group_results:
                    target_period = period_id if period_id in columns else periods.POST_REFORMATION
                    column_numbers[target_period] += 1
                    self._add_result_card(target_layout, result_index, row, column_numbers[target_period])
                    result_index += 1
            for column in columns.values():
                if column.body_layout.count() == 1:
                    empty = QtWidgets.QLabel("No results in this section.")
                    empty.setObjectName("EmptyState")
                    empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                    stretch = column.body_layout.takeAt(column.body_layout.count() - 1)
                    column.body_layout.addWidget(empty, 1)
                    if stretch is not None:
                        column.body_layout.addItem(stretch)
        else:
            column = PeriodColumn("Results", len(results))
            self.results_layout.addWidget(column, 1)
            for index, row in enumerate(results):
                self._add_result_card(column.body_layout, index, row, index + 1)

    def select_result(self, result_index: int) -> None:
        if result_index < 0 or result_index >= len(self.current_results):
            return
        self.selected_result_index = result_index
        for card in self.result_cards:
            card.set_selected(card.index == result_index)
        row = self.current_results[result_index]
        self._set_status(f"Selected {core_gui.display_value(row.get('evidence_id'), 'result')}")

    @QtCore.Slot()
    def start_search(self) -> None:
        if self.thread is not None:
            return
        query = display_text(self.query_entry.text())
        if not query:
            self._set_status("Type a query first", error=True)
            return

        self.search_button.setEnabled(False)
        self.advance_button.setEnabled(False)
        self.selected_result_index = None
        self._set_status("Searching...")
        self._render_empty_results("Searching...")

        self.thread = QtCore.QThread(self)
        self.current_advanced_criteria = None
        self.worker = SearchWorker(query, int(self.limit_combo.currentText()), self.index_path, self.lexicon_path, period_sections=True)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._search_finished)
        self.worker.failed.connect(self._search_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._search_thread_finished)
        self.thread.start()

    @QtCore.Slot()
    def open_advanced_search(self) -> None:
        if self.thread is not None:
            return
        dialog = AdvancedSearchDialog(self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or dialog.criteria is None:
            return
        self.start_advanced_search(dialog.criteria)

    def start_advanced_search(self, criteria: AdvancedSearchCriteria) -> None:
        if self.thread is not None:
            return
        self.search_button.setEnabled(False)
        self.advance_button.setEnabled(False)
        self.current_advanced_criteria = criteria
        self.selected_result_index = None
        self._set_status("Running advanced search...")
        self._render_empty_results("Running advanced search...")
        self.thread = QtCore.QThread(self)
        self.worker = SearchWorker(
            limit=int(self.limit_combo.currentText()),
            index_path=self.index_path,
            lexicon_path=self.lexicon_path,
            criteria=criteria,
            period_sections=True,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._search_finished)
        self.worker.failed.connect(self._search_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._search_thread_finished)
        self.thread.start()

    @QtCore.Slot(object)
    def _search_finished(self, output: core_gui.SearchOutput) -> None:
        self.current_results = output.results
        self._render_results(output.results, output.period_groups)
        if not output.advanced:
            self.history = core_gui.add_history_item(self.history, output.query)
            core_gui.save_history(self.history, self.history_path)
            self._refresh_history()
        self._set_status(f"{len(output.results)} results")

    @QtCore.Slot(str)
    def _search_failed(self, message: str) -> None:
        self._render_empty_results("Search failed.")
        self._set_status(f"Error: {message}", error=True)

    @QtCore.Slot()
    def _search_thread_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None
        self.search_button.setEnabled(True)
        self.advance_button.setEnabled(True)

    def _search_history_item(self, item: QtWidgets.QListWidgetItem) -> None:
        query = item.data(QtCore.Qt.ItemDataRole.UserRole) or ""
        self.query_entry.setText(str(query))
        self.start_search()

    def clear_search_history(self) -> None:
        self.history = []
        core_gui.clear_history(self.history_path)
        self._refresh_history()
        self._set_status("History cleared")

    def clear_search(self) -> None:
        self.query_entry.clear()
        self.current_results = []
        self.selected_result_index = None
        self._render_empty_results("Type a query above to begin.")
        self._set_status("Ready")

    def open_explanation(self, result_index: int) -> None:
        if result_index < 0 or result_index >= len(self.current_results):
            self._set_status("Select a result", error=True)
            return
        self.select_result(result_index)
        dialog = ExplanationDialog(self.current_results[result_index], self)
        dialog.exec()
        self._set_search_status()

    def open_selected_result(self) -> None:
        if self.selected_result_index is None:
            self._set_status("Select a result first", error=True)
            return
        self.open_result(self.selected_result_index)

    def open_result(self, result_index: int) -> None:
        if result_index < 0 or result_index >= len(self.current_results):
            self._set_status("Select a result first", error=True)
            return
        self.select_result(result_index)
        row = self.current_results[result_index]
        try:
            context = core_gui.fetch_context(row.get("evidence_id"), index_path=self.index_path)
        except Exception as exc:
            self._set_status(f"Context error: {exc}", error=True)
            QtWidgets.QMessageBox.critical(self, "Context error", str(exc))
            return
        dialog = ContextDialog(context, self, match_row=row)
        dialog.exec()
        self._set_search_status()

def main(argv: list[str] | None = None) -> int:
    configure_output()
    arguments = argv or sys.argv
    self_test = "--self-test" in arguments
    app = QtWidgets.QApplication(arguments)
    try:
        if not DEFAULT_INDEX_PATH.exists():
            raise RuntimeError(f"The search database is missing:\n{DEFAULT_INDEX_PATH}")
        if not DEFAULT_LEXICON_PATH.exists():
            raise RuntimeError(f"The search configuration is missing:\n{DEFAULT_LEXICON_PATH}")
        with sqlite3.connect(str(DEFAULT_INDEX_PATH)) as con:
            con.execute("SELECT evidence_id FROM evidence LIMIT 1").fetchone()
    except (OSError, sqlite3.DatabaseError, RuntimeError) as exc:
        QtWidgets.QMessageBox.critical(
            None,
            "Theologia Search could not start",
            f"The installation appears incomplete or damaged.\n\n{exc}",
        )
        return 1
    if self_test:
        return 0
    load_project_fonts()
    app.setApplicationName("Theologia Search")
    window = TheologiaSearchWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
