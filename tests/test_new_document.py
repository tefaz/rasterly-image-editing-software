import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication

from rasterly.ui.dialogs import NewDialog
from rasterly.ui.window import EditorWindow

app = QApplication.instance() or QApplication([])


class NewDocumentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "preferences.ini")
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        app.processEvents()
        self.directory.cleanup()

    def dialog(self, parent=None):
        settings = QSettings(self.path, QSettings.Format.IniFormat)
        dialog = NewDialog(parent, settings=settings)
        self.dialogs.append(dialog)
        return dialog

    def test_remembers_preset_with_fresh_settings_instance(self):
        dialog = self.dialog()
        self.assertEqual(dialog.dimensions, (1920, 1080))
        dialog.preset.setCurrentIndex(1)
        dialog.remember_dimensions()
        reopened = self.dialog()
        self.assertEqual(reopened.dimensions, (2560, 1440))
        self.assertEqual(reopened.preset.currentData(), (2560, 1440))

    def test_remembers_custom_size_and_invalid_saved_size_uses_default(self):
        dialog = self.dialog()
        dialog.width_input.setValue(1234)
        dialog.height_input.setValue(567)
        dialog.remember_dimensions()
        reopened = self.dialog()
        self.assertEqual(reopened.dimensions, (1234, 567))
        self.assertIsNone(reopened.preset.currentData())
        for width, height in (("invalid", 567), (0, 100), (32768, 32768)):
            with self.subTest(width=width, height=height):
                reopened.settings.setValue("newCanvas/width", width)
                reopened.settings.setValue("newCanvas/height", height)
                reopened.settings.sync()
                self.assertEqual(self.dialog().dimensions, (1920, 1080))

    def test_file_new_remembers_created_size_and_cancel_keeps_previous_size(self):
        window = EditorWindow()
        window.show()

        def create_dialog(parent):
            dialog = self.dialog(parent)
            QTimer.singleShot(0, lambda: self.create(dialog))
            return dialog

        def cancel_dialog(parent):
            dialog = self.dialog(parent)
            self.assertEqual(dialog.dimensions, (120, 80))
            dialog.width_input.setValue(150)
            QTimer.singleShot(0, dialog.reject)
            return dialog

        try:
            with patch("rasterly.ui.window.NewDialog", side_effect=create_dialog):
                window.actions["new"].trigger()
            self.assertEqual((window.controller.document.width, window.controller.document.height), (120, 80))
            self.assertEqual(self.dialog().dimensions, (120, 80))
            with patch("rasterly.ui.window.NewDialog", side_effect=cancel_dialog):
                window.actions["new"].trigger()
            self.assertEqual(len(window.controller.sessions), 1)
            self.assertEqual(self.dialog().dimensions, (120, 80))
        finally:
            for session in window.controller.sessions:
                session.saved_revision = session.document.revision
            # Dialogs owned by the window are deleted along with it.
            self.dialogs = [dialog for dialog in self.dialogs if dialog.parent() is not window]
            window.close()
            window.deleteLater()
            app.processEvents()

    @staticmethod
    def create(dialog):
        dialog.width_input.setValue(120)
        dialog.height_input.setValue(80)
        dialog.accept()


if __name__ == "__main__":
    unittest.main()
