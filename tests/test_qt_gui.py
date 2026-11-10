import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from PySide6 import QtWidgets
    from theologia_search import qt_gui
except (ModuleNotFoundError, SystemExit):  # pragma: no cover - optional GUI dependency.
    QtWidgets = None
    qt_gui = None


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed")
class QtGuiVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        qt_gui.load_project_fonts()

    def test_main_buttons_use_complete_separate_artwork(self):
        window = qt_gui.TheologiaSearchWindow()
        try:
            self.assertEqual(window.search_button.size(), window.advance_button.size())
            self.assertEqual(window.search_button.text(), "")
            self.assertEqual(window.advance_button.text(), "")
            self.assertEqual(window.search_button.asset_name, "search_button")
            self.assertEqual(window.advance_button.asset_name, "advance_button")
            self.assertFalse(window.search_button.button_pixmap.isNull())
            self.assertFalse(window.advance_button.button_pixmap.isNull())
        finally:
            window.close()

    def test_advanced_dialog_has_matching_shell_and_compact_connectors(self):
        window = qt_gui.TheologiaSearchWindow()
        dialog = qt_gui.AdvancedSearchDialog(window)
        try:
            self.assertEqual(dialog.objectName(), "AdvancedSearchDialog")
            self.assertEqual(dialog.windowModality(), qt_gui.QtCore.Qt.WindowModality.ApplicationModal)
            labels = {label.text() for label in dialog.findChildren(QtWidgets.QLabel)}
            self.assertIn("Concept or phrase", labels)
            author = dialog.fields["author"]
            self.assertIsInstance(author, QtWidgets.QComboBox)
            self.assertEqual(author.currentText(), "All authors")
            self.assertIn("John Calvin", [author.itemText(index) for index in range(author.count())])
            for connector in dialog.connectors.values():
                self.assertEqual(connector.size().width(), 72)
                self.assertEqual(connector.size().height(), 32)
                self.assertEqual(connector.font().pointSize(), 13)
        finally:
            dialog.close()
            window.close()

    def pagination_row(self):
        return {"source_id": "SOURCE", "source_title": "Example book", "author": "Example author",
                "evidence_id": "SOURCE_EVID_00022_BODY_01", "page_number": 22, "heading": "Chapter 1",
                "verbatim_text": "Example evidence.", "quality_label": "strong", "snippet": "Example evidence.",
                "page_locations": [{"pdf_page_number": 22, "pdf_edition_page_number": "17",
                                    "pdf_edition_status": "verified", "original_book_page_numbers": ["iii"],
                                    "original_book_status": "verified"}]}

    def test_result_card_shows_verified_numbering(self):
        row = self.pagination_row()
        card = qt_gui.ResultCard(0, row, 1)
        try:
            card.setStyleSheet(qt_gui.APP_STYLESHEET)
            card.setFixedWidth(350)
            card.show()
            self.app.processEvents()
            self.app.processEvents()
            text = " ".join(label.text() for label in card.findChildren(QtWidgets.QLabel))
            self.assertIn("PDF file page: 22", text)
            self.assertIn("Header/footer page: 17", text)
            self.assertIn("Printed book reference: iii", text)
            value = card.findChild(qt_gui.PageLocationLine).findChild(QtWidgets.QLabel, "FieldValue")
            self.assertGreaterEqual(value.height(), value.heightForWidth(value.width()))
        finally:
            card.close()

    def test_context_copy_citation_includes_page_systems(self):
        row = self.pagination_row()
        context = qt_gui.core_gui.ContextOutput(row, [row], "chapter", "22", "Chapter 1", 0, 0, False, False)
        dialog = qt_gui.ContextDialog(context)
        try:
            button = next(b for b in dialog.findChildren(QtWidgets.QPushButton) if b.text() == "Copy citation")
            button.click()
            text = self.app.clipboard().text()
            self.assertIn("PDF file page: 22", text)
            self.assertIn("Header/footer page: 17", text)
            self.assertIn("Printed book reference: iii", text)
            self.assertIn("SOURCE_EVID_00022_BODY_01", text)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
