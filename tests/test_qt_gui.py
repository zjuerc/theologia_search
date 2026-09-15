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


if __name__ == "__main__":
    unittest.main()
