import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QPoint, QPointF, Qt, QMimeData
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QColorDialog, QDialog
from rasterly.model import Document
from rasterly.selection import Selection
from rasterly.ui.dialogs import FillDialog
from rasterly.ui.style import STYLE
from rasterly.ui.window import EditorWindow

app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(STYLE)


class ColorTests(unittest.TestCase):
    def setUp(self):
        self.window = EditorWindow()
        self.window.show()
        self.controller = self.window.controller
        self.controller.add_document(Document.new(320, 200))
        self.controller.saved_revision = self.controller.document.revision
        self.panel = self.window.colors
        app.processEvents()

    def tearDown(self):
        self.window.canvas.tools["text"].cancel()
        for session in self.controller.sessions:
            session.saved_revision = session.document.revision
        self.window.close()
        self.window.deleteLater()
        app.processEvents()

    def test_rectangle_has_pure_white_top_right_and_black_bottom_and_selects_them(self):
        field = self.panel.field
        image = field.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() - 1, 0).getRgb(), (255, 255, 255, 255))
        for x in range(image.width() - 8):  # The selection ring occupies the bottom-right corner.
            self.assertEqual(image.pixelColor(x, image.height() - 1).getRgb(), (0, 0, 0, 255))
        before = self.controller.document
        QTest.mouseClick(field, Qt.MouseButton.LeftButton, pos=QPoint(field.width() - 1, 0))
        self.assertEqual(self.panel.color, QColor("white"))
        self.assertEqual([slider.value() for slider in self.panel.sliders], [255, 255, 255])
        self.assertEqual(self.panel.hex_input.text(), "#FFFFFF")
        QTest.mouseClick(field, Qt.MouseButton.LeftButton, pos=QPoint(0, field.height() - 1))
        self.assertEqual(self.panel.color, QColor("black"))
        self.assertEqual(field.saturation, 1)
        # QTest treats a null (0, 0) point as the widget center; click one pixel below it.
        QTest.mouseClick(field, Qt.MouseButton.LeftButton, pos=QPoint(0, 1))
        self.assertGreater(self.panel.color.red(), 250)
        self.assertEqual(self.panel.color.green(), 0)
        self.assertEqual(self.panel.color.blue(), 0)
        self.assertIs(self.controller.document, before)
        self.assertFalse(self.controller.dirty)
        self.assertFalse(self.controller.history.undo_stack)

    def test_rgb_slider_drag_numeric_values_and_keyboard_stay_synchronized(self):
        red = self.panel.sliders[0]
        QTest.mousePress(red, Qt.MouseButton.LeftButton, pos=QPoint(0, red.height() // 2))
        QTest.mouseMove(red, QPoint(red.width() - 1, red.height() // 2))
        QTest.mouseRelease(red, Qt.MouseButton.LeftButton, pos=QPoint(red.width() - 1, red.height() // 2))
        self.assertEqual(self.panel.color, QColor("red"))
        self.panel.values[1].setValue(80)
        self.panel.values[2].setValue(120)
        QTest.keyClick(self.panel.sliders[1], Qt.Key.Key_Right)
        self.assertEqual(self.panel.color.getRgb(), (255, 81, 120, 255))
        self.assertEqual([slider.value() for slider in self.panel.sliders], [255, 81, 120])
        self.assertEqual([value.value() for value in self.panel.values], [255, 81, 120])
        self.assertEqual(self.window.text_color, self.panel.color)
        self.assertEqual(self.window.canvas.tools["text"].defaults.color, (255, 81, 120, 255))
        swatch = self.panel.swatch.grab().toImage()
        self.assertEqual(swatch.pixelColor(swatch.width() // 2, swatch.height() // 2), self.panel.color)

    def test_hue_strip_reaches_green_and_blue_and_preserves_hue_when_picking_white(self):
        self.panel.set_color(QColor("red"))
        hue = self.panel.hue
        QTest.mouseClick(hue, Qt.MouseButton.LeftButton, pos=QPoint(8, round((hue.height() - 1) / 3)))
        green = self.panel.color
        self.assertEqual(green.green(), 255)
        self.assertLess(green.red(), 10)
        self.assertLess(green.blue(), 10)
        field = self.panel.field
        QTest.mouseClick(field, Qt.MouseButton.LeftButton, pos=QPoint(field.width() - 1, 0))
        self.assertEqual(self.panel.color, QColor("white"))
        QTest.mouseClick(hue, Qt.MouseButton.LeftButton, pos=QPoint(8, round((hue.height() - 1) * 2 / 3)))
        self.assertEqual(self.panel.color, QColor("white"))
        QTest.mouseClick(field, Qt.MouseButton.LeftButton, pos=QPoint(0, 1))
        blue = self.panel.color
        self.assertGreater(blue.blue(), 250)
        self.assertLess(blue.red(), 10)
        self.assertLess(blue.green(), 10)

    def test_foreground_controls_work_during_typing_without_changing_document_until_apply(self):
        self.panel.set_color(QColor(30, 80, 140))
        self.window.canvas.set_tool("text")
        tool = self.window.canvas.tools["text"]
        tool.begin(QPointF(20, 30))
        tool.editor.setPlainText("Foreground color")
        before = self.controller.document
        self.assertTrue(self.panel.isEnabled())
        self.assertFalse(self.window.layers.isEnabled())
        self.panel.values[0].setValue(90)
        self.assertEqual(tool.current_data().color, (90, 80, 140, 255))
        self.assertIs(self.controller.document, before)
        self.assertFalse(self.controller.history.undo_stack)
        tool.cancel()
        self.assertIs(self.controller.document, before)
        self.assertEqual(self.panel.color.getRgb(), (90, 80, 140, 255))
        tool.begin(QPointF(20, 30))
        tool.editor.setPlainText("New foreground text")
        self.assertTrue(tool.commit())
        self.assertEqual(self.controller.document.active.text.color, (90, 80, 140, 255))
        self.assertEqual(len(self.controller.history.undo_stack), 1)

    def test_text_color_dialog_and_foreground_swatch_share_the_same_color(self):
        with patch.object(QColorDialog, "getColor", return_value=QColor("cyan")):
            self.window.choose_text_color()
        self.assertEqual(self.panel.color, QColor("cyan"))
        with patch.object(QColorDialog, "getColor", return_value=QColor("magenta")):
            QTest.mouseClick(self.panel.swatch, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.text_color, QColor("magenta"))
        self.assertEqual(self.window.canvas.tools["text"].defaults.color, (255, 0, 255, 255))

    def test_solid_fill_defaults_to_foreground_and_commits_only_selected_pixels(self):
        self.panel.set_color(QColor(12, 34, 56))
        self.controller.set_selection(Selection.rectangle(10, 10, 30, 30))
        def accept(dialog):
            self.assertIsInstance(dialog, FillDialog)
            self.assertEqual(dialog.color, self.panel.color)
            dialog.mode.setCurrentIndex(1)
            return QDialog.DialogCode.Accepted
        with patch.object(FillDialog, "exec", accept):
            self.window.fill()
        image = self.controller.document.active.image
        self.assertEqual(image.getpixel((15, 15)), (12, 34, 56, 255))
        self.assertEqual(image.getpixel((5, 5)), (255, 255, 255, 255))
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Solid Color Fill")

    def test_small_window_keeps_the_entire_color_field_and_layer_controls_visible(self):
        self.window.resize(880, 570)
        app.processEvents()
        field = self.panel.field
        bottom = field.mapTo(self.panel, QPoint(field.width() // 2, field.height() - 1))
        self.assertTrue(self.panel.rect().contains(bottom))
        self.assertLess(self.panel.geometry().bottom(), self.window.layers.geometry().top())
        layers = self.window.layers
        list_bottom = layers.list.mapTo(layers, QPoint(0, layers.list.height() - 1))
        self.assertTrue(layers.rect().contains(list_bottom))

    def test_hex_copy_and_paste_work_with_canvas_clipboard_shortcuts_enabled(self):
        self.panel.set_color(QColor("#123456"))
        self.controller.set_selection(Selection.rectangle(10, 10, 30, 30))
        before = self.controller.document
        field = self.panel.hex_input
        field.setFocus()
        QTest.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(field, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), "#123456")
        self.assertIs(self.controller.document, before)
        # Mixed clipboard data must paste text into the input, even when image paste is enabled.
        clipboard = QMimeData()
        clipboard.setText("#aBcDef")
        image = QImage(2, 2, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.red)
        clipboard.setImageData(image)
        QApplication.clipboard().setMimeData(clipboard)
        self.assertTrue(self.window.actions["paste"].isEnabled())
        QTest.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(field, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(field.text(), "#aBcDef")
        QTest.keyClick(field, Qt.Key.Key_Return)
        self.assertEqual(field.text(), "#ABCDEF")
        self.assertEqual(self.panel.color, QColor("#abcdef"))
        self.assertEqual([slider.value() for slider in self.panel.sliders], [171, 205, 239])
        self.assertEqual(self.window.canvas.tools["text"].defaults.color, (171, 205, 239, 255))
        self.assertIs(self.controller.document, before)

    def test_hex_accepts_short_codes_and_whitespace_and_rejects_invalid_values(self):
        field = self.panel.hex_input
        before = self.controller.document
        for value, expected in [("abc", "#AABBCC"), ("#0f8", "#00FF88"),
                                (" 123456 ", "#123456"), ("#12GG56", "#123456"),
                                ("#12", "#123456"), ("red", "#123456")]:
            with self.subTest(value=value):
                field.setFocus()
                QApplication.clipboard().setText(value)
                QTest.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                QTest.keyClick(field, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
                self.window.canvas.setFocus()
                app.processEvents()
                self.assertEqual(field.text(), expected)
                self.assertEqual(self.panel.color.name().upper(), expected)
        self.assertIs(self.controller.document, before)
        self.assertFalse(self.controller.dirty)
        self.assertFalse(self.controller.history.undo_stack)


if __name__ == "__main__":
    unittest.main()
