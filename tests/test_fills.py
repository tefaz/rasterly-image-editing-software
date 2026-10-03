import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
import time
import unittest
from unittest.mock import patch

from PIL import Image
from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QStyle

from rasterly.fills import paint_bucket, linear_gradient
from rasterly.model import Document, Layer, TextData
from rasterly.selection import Selection
from rasterly.ui.style import STYLE
from rasterly.ui.window import EditorWindow

app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(STYLE)


class FillOperationTests(unittest.TestCase):
    def document(self, image, width=None, height=None, x=0, y=0, selection=None):
        layer = Layer("Paint", image, x, y)
        return Document(width or image.width, height or image.height, (layer,), layer.id, selection)

    def test_bucket_fills_connected_region_and_leaves_source_immutable(self):
        image = Image.new("RGBA", (7, 5), "white")
        for y in range(5):
            image.putpixel((3, y), (0, 0, 0, 255))
        doc = self.document(image)
        result = paint_bucket(doc, (1, 2), (255, 0, 0, 255), 0)
        self.assertEqual(result.active.image.getpixel((2, 4)), (255, 0, 0, 255))
        self.assertEqual(result.active.image.getpixel((3, 2)), (0, 0, 0, 255))
        self.assertEqual(result.active.image.getpixel((4, 2)), (255, 255, 255, 255))
        self.assertEqual(image.getpixel((1, 2)), (255, 255, 255, 255))

    def test_tolerance_compares_to_seed_and_diagonals_are_disconnected(self):
        image = Image.new("RGBA", (5, 1))
        image.putdata([(n, n, n, 255) for n in (100, 110, 120, 130, 100)])
        result = paint_bucket(self.document(image), (0, 0), (255, 0, 0, 255), 20)
        self.assertEqual([result.active.image.getpixel((x, 0))[0] for x in range(5)],
                         [255, 255, 255, 130, 100])
        image = Image.new("RGBA", (2, 2), "black")
        image.putpixel((0, 0), (255, 255, 255, 255))
        image.putpixel((1, 1), (255, 255, 255, 255))
        result = paint_bucket(self.document(image), (0, 0), (255, 0, 0, 255), 0)
        self.assertEqual(result.active.image.getpixel((1, 1)), (255, 255, 255, 255))

    def test_selection_holes_block_bucket_connectivity(self):
        selection = Selection.rectangle(1, 0, 6, 5).subtracted(Selection.rectangle(3, 0, 4, 5))
        doc = self.document(Image.new("RGBA", (7, 5), "white"), selection=selection)
        result = paint_bucket(doc, (2, 2), (0, 0, 255, 255), 0)
        self.assertEqual(result.active.image.getpixel((1, 4)), (0, 0, 255, 255))
        for point in ((0, 2), (3, 2), (4, 2), (6, 2)):
            self.assertEqual(result.active.image.getpixel(point), (255, 255, 255, 255))
        self.assertIs(paint_bucket(doc, (3, 2), (255, 0, 0, 255)), doc)

    def test_empty_offset_layer_expands_and_retains_off_canvas_pixels(self):
        image = Image.new("RGBA", (3, 3), (100, 200, 50, 0))
        image.putpixel((0, 0), (1, 2, 3, 255))
        doc = self.document(image, 8, 6, -1, -1)
        result = paint_bucket(doc, (7, 5), (40, 50, 60, 255), 0)
        self.assertEqual(result.active.bounds, (-1, -1, 8, 6))
        self.assertEqual(result.active.image.getpixel((0, 0)), (1, 2, 3, 255))
        self.assertEqual(result.active.image.getpixel((1, 1)), (40, 50, 60, 255))
        self.assertEqual(result.active.image.getpixel((8, 6)), (40, 50, 60, 255))

    def test_same_color_bucket_and_zero_length_gradient_are_noops(self):
        doc = self.document(Image.new("RGBA", (5, 5), "red"))
        self.assertIs(paint_bucket(doc, (0, 0), (255, 0, 0, 255)), doc)
        self.assertIs(paint_bucket(doc, (-1, 0), (0, 0, 0, 255)), doc)
        self.assertIs(linear_gradient(doc, (1, 1), (1, 1), (0, 0, 0, 255)), doc)

    def test_gradient_exact_endpoints_midpoint_reverse_and_diagonal(self):
        doc = self.document(Image.new("RGBA", (5, 5)))
        result = linear_gradient(doc, (0, 0), (4, 0), (255, 0, 0, 255))
        self.assertEqual(result.active.image.getpixel((0, 3)), (255, 0, 0, 255))
        self.assertEqual(result.active.image.getpixel((2, 3)), (255, 128, 128, 255))
        self.assertEqual(result.active.image.getpixel((4, 3)), (255, 255, 255, 255))
        result = linear_gradient(doc, (4, 0), (0, 0), (0, 0, 0, 255))
        self.assertEqual(result.active.image.getpixel((0, 2)), (255, 255, 255, 255))
        self.assertEqual(result.active.image.getpixel((4, 2)), (0, 0, 0, 255))
        result = linear_gradient(doc, (0, 0), (4, 4), (0, 0, 0, 255))
        self.assertEqual(result.active.image.getpixel((0, 4)), (128, 128, 128, 255))

    def test_gradient_respects_irregular_selection_and_other_layers(self):
        selection = Selection("lasso", ((1, 1), (5, 1), (1, 5)))
        doc = self.document(Image.new("RGBA", (7, 7), "blue"), selection=selection)
        other = Layer("Other", Image.new("RGBA", (7, 7), "green"))
        doc = doc.edited(layers=doc.layers + (other,))
        result = linear_gradient(doc, (1, 1), (5, 1), (255, 0, 0, 255))
        self.assertIs(result.layers[1], other)
        mask = selection.mask((0, 0, 7, 7))
        for y in range(7):
            for x in range(7):
                if not mask.getpixel((x, y)):
                    self.assertEqual(result.active.image.getpixel((x, y)), (0, 0, 255, 255))
        self.assertEqual(result.active.image.getpixel((1, 1)), (255, 0, 0, 255))

    def test_transparent_gradient_has_colored_alpha_and_reveals_existing_pixels(self):
        doc = self.document(Image.new("RGBA", (5, 2)))
        result = linear_gradient(doc, (0, 0), (4, 0), (80, 120, 200, 255), True)
        self.assertEqual(result.active.image.getpixel((2, 0)), (80, 120, 200, 128))
        self.assertEqual(result.active.image.getpixel((4, 0))[3], 0)
        doc = self.document(Image.new("RGBA", (5, 2), "blue"))
        result = linear_gradient(doc, (0, 0), (4, 0), (255, 0, 0, 255), True)
        self.assertEqual(result.active.image.getpixel((2, 0)), (128, 0, 127, 255))
        self.assertEqual(result.active.image.getpixel((4, 0)), (0, 0, 255, 255))

    def test_hidden_and_editable_text_layers_reject_pixel_fills(self):
        doc = self.document(Image.new("RGBA", (5, 5)))
        for layer in (replace(doc.active, visible=False), replace(doc.active, text=TextData("Hello"))):
            target = doc.with_layer(layer)
            with self.assertRaises(ValueError):
                paint_bucket(target, (0, 0), (0, 0, 0, 255))
            with self.assertRaises(ValueError):
                linear_gradient(target, (0, 0), (4, 0), (0, 0, 0, 255))

    def test_multiple_stops_use_their_positions_and_pad_moved_endpoints(self):
        doc = self.document(Image.new("RGBA", (9, 2)))
        stops = ((.25, (255, 0, 0, 255)), (.5, (0, 255, 0, 255)), (.75, (0, 0, 255, 255)))
        result = linear_gradient(doc, (0, 0), (8, 0), stops=stops)
        expected = [(255, 0, 0, 255), (255, 0, 0, 255), (255, 0, 0, 255),
                    (128, 128, 0, 255), (0, 255, 0, 255), (0, 128, 128, 255),
                    (0, 0, 255, 255), (0, 0, 255, 255), (0, 0, 255, 255)]
        self.assertEqual([result.active.image.getpixel((x, 1)) for x in range(9)], expected)

    def test_multiple_stops_interpolate_alpha_without_dark_fringes(self):
        doc = self.document(Image.new("RGBA", (9, 1)))
        stops = ((0, (255, 0, 0, 255)), (.5, (0, 255, 0, 0)), (1, (0, 0, 255, 255)))
        result = linear_gradient(doc, (0, 0), (8, 0), stops=stops)
        self.assertEqual(result.active.image.getpixel((2, 0)), (255, 0, 0, 128))
        self.assertEqual(result.active.image.getpixel((4, 0))[3], 0)
        self.assertEqual(result.active.image.getpixel((6, 0)), (0, 0, 255, 128))


class FillInteractionTests(unittest.TestCase):
    def setUp(self):
        self.window = EditorWindow()
        self.errors = []
        self.controller = self.window.controller
        self.controller.error.disconnect(self.window.show_error)
        self.controller.error.connect(self.errors.append)
        self.window.show()
        self.controller.replace_document(Document.from_image(Image.new("RGBA", (100, 80))))
        self.canvas = self.window.canvas
        self.canvas.set_zoom(3)
        self.canvas.setFocus()
        app.processEvents()

    def tearDown(self):
        self.wait_worker()
        self.window.fill_tool_menu.close()
        for session in self.controller.sessions:
            session.saved_revision = session.document.revision
        self.window.close()
        self.window.deleteLater()
        app.processEvents()

    def screen(self, x, y):
        return self.canvas.to_screen(QPointF(x, y)).toPoint()

    def wait_worker(self):
        deadline = time.monotonic() + 10
        while self.controller.busy and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertFalse(self.controller.busy)
        self.assertFalse(self.errors, self.errors)

    def test_bucket_uses_hex_foreground_with_one_undo_step(self):
        self.window.colors.set_color(QColor("#123456"))
        original = self.controller.document
        self.canvas.set_tool("bucket")
        self.window.bucket_tolerance.setValue(0)
        self.assertEqual(self.canvas.tools["bucket"].tolerance, 0)
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(40, 40))
        self.wait_worker()
        self.assertEqual(self.controller.document.active.image.getpixel((99, 79)), (18, 52, 86, 255))
        self.assertEqual(len(self.controller.history.undo_stack), 1)
        self.controller.undo()
        self.assertIs(self.controller.document, original)
        self.controller.redo()
        self.assertEqual(self.controller.document.active.image.getpixel((0, 0)), (18, 52, 86, 255))

    def test_gradient_drag_previews_without_edits_and_commits_once(self):
        self.window.colors.set_color(QColor("#ff0000"))
        self.canvas.set_tool("gradient")
        original = self.controller.document
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(10, 30))
        QTest.mouseMove(self.canvas, self.screen(90, 30))
        self.assertIs(self.controller.document, original)
        self.assertIsNotNone(self.canvas.gradient_preview)
        self.assertEqual(len(self.controller.history.undo_stack), 0)
        preview = self.canvas.grab().toImage()
        pixel = preview.pixelColor(self.screen(50, 30))
        self.assertEqual(pixel.red(), 255)
        self.assertAlmostEqual(pixel.green(), 128, delta=2)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(90, 30))
        self.wait_worker()
        self.assertIsNone(self.canvas.gradient_preview)
        self.assertEqual(self.controller.document.active.image.getpixel((50, 30)), (255, 128, 128, 255))
        self.assertEqual(len(self.controller.history.undo_stack), 1)
        self.controller.undo()
        self.assertIs(self.controller.document, original)

    def test_gradient_escape_and_tool_switch_cancel_without_history(self):
        self.canvas.set_tool("gradient")
        original = self.controller.document
        for cancel in (lambda: QTest.keyClick(self.canvas, Qt.Key.Key_Escape),
                       lambda: self.canvas.set_tool("move")):
            QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(10, 10))
            QTest.mouseMove(self.canvas, self.screen(70, 60))
            cancel()
            QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(70, 60))
            self.assertIsNone(self.canvas.gradient_preview)
            self.assertIs(self.controller.document, original)
            self.assertEqual(len(self.controller.history.undo_stack), 0)

    def test_gradient_mode_and_shift_constrain_preview_and_final_result(self):
        self.window.colors.set_color(QColor("#ff0000"))
        self.canvas.set_tool("gradient")
        self.window.gradient_mode.setCurrentIndex(1)
        self.assertTrue(self.canvas.tools["gradient"].transparent)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(10, 10))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                           pos=self.screen(70, 20))
        self.wait_worker()
        image = self.controller.document.active.image
        self.assertEqual(image.getpixel((30, 20)), image.getpixel((30, 60)))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((99, 79))[3], 0)

    def test_shared_toolbar_short_click_and_shortcuts(self):
        button = self.window.fill_tool_button
        self.assertIs(self.window.tool_buttons["bucket"], self.window.tool_buttons["gradient"])
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.canvas.tool_id, "bucket")
        self.assertFalse(self.window.fill_tool_menu.isVisible())
        QTest.keyClick(self.canvas, Qt.Key.Key_G, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.canvas.tool_id, "gradient")
        self.assertIs(button.defaultAction(), self.window.actions["tool_gradient"])
        self.canvas.set_tool("move")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.canvas.tool_id, "gradient")
        self.assertTrue(button.isChecked())
        self.canvas.set_tool("move")
        self.assertFalse(button.isChecked())

    def test_hold_flyout_selects_hovered_tool_only_on_release(self):
        button, menu = self.window.fill_tool_button, self.window.fill_tool_menu
        self.assertEqual(button.style().styleHint(QStyle.StyleHint.SH_ToolButton_PopupDelay, None, button), 400)
        observed = []
        def release_over_gradient():
            observed.append((menu.isVisible(), self.canvas.tool_id))
            position = menu.actionGeometry(self.window.actions["tool_gradient"]).center()
            QTest.mouseMove(menu, position)
            observed.append(self.canvas.tool_id)
            QTest.mouseRelease(menu, Qt.MouseButton.LeftButton, pos=position)
            menu.close()
        QTimer.singleShot(550, release_over_gradient)
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        QTest.qWait(150)
        self.assertFalse(menu.isVisible())
        QTest.qWait(500)
        self.assertEqual(observed, [(True, "move"), "move"])
        self.assertEqual(self.canvas.tool_id, "gradient")
        self.assertFalse(menu.isVisible())
        self.assertIs(button.defaultAction(), self.window.actions["tool_gradient"])

    def test_hold_flyout_escape_preserves_active_tool(self):
        button, menu = self.window.fill_tool_button, self.window.fill_tool_menu
        observed = []
        def cancel():
            observed.append(menu.isVisible())
            QTest.keyClick(menu, Qt.Key.Key_Escape)
            QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
            menu.close()
        QTimer.singleShot(550, cancel)
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        QTest.qWait(650)
        self.assertEqual(observed, [True])
        self.assertEqual(self.canvas.tool_id, "move")
        self.assertFalse(menu.isVisible())

    def test_gradient_stop_click_changes_either_endpoint_without_document_edits(self):
        self.canvas.set_tool("gradient")
        editor = self.window.gradient_editor
        original = self.controller.document
        self.assertTrue(editor.isVisible())
        for index, color in ((0, "#ff0000"), (1, "#0000ff")):
            position = editor.stop_point(editor._stops[index]).toPoint()
            with patch("rasterly.ui.gradient.QColorDialog.getColor", return_value=QColor(color)) as picker:
                QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=position)
            picker.assert_called_once()
            self.assertEqual(editor.stops[index][1], QColor(color).getRgb())
        self.assertEqual(self.window.gradient_mode.currentText(), "Custom")
        self.window.colors.set_color(QColor("#00ff00"))
        self.assertEqual(editor.stops[0][1], (255, 0, 0, 255))
        self.assertIs(self.controller.document, original)
        self.assertEqual(len(self.controller.history.undo_stack), 0)

    def test_add_drag_remove_multiple_stops_and_apply_matches_preview(self):
        self.canvas.set_tool("gradient")
        editor = self.window.gradient_editor
        original = self.controller.document
        for position, color in ((.5, "#ff0000"), (.75, "#0000ff")):
            point = QPointF(editor.bar.left() + position * editor.bar.width(), editor.bar.center().y()).toPoint()
            with patch("rasterly.ui.gradient.QColorDialog.getColor", return_value=QColor(color)):
                QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(len(editor.stops), 4)
        red = next(stop for stop in editor._stops if stop.color == (255, 0, 0, 255))
        initial = editor.stop_point(red).toPoint()
        target = QPointF(editor.bar.left() + .25 * editor.bar.width(), 28).toPoint()
        with patch("rasterly.ui.gradient.QColorDialog.getColor") as picker:
            QTest.mousePress(editor, Qt.MouseButton.LeftButton, pos=initial)
            QTest.mouseMove(editor, target)
            QTest.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=target)
            picker.assert_not_called()
        self.assertAlmostEqual(red.position, .25, delta=.004)
        self.assertIs(self.controller.document, original)
        self.assertEqual(self.canvas.tools["gradient"].stops, editor.stops)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(10, 40))
        QTest.mouseMove(self.canvas, self.screen(90, 40))
        preview = self.canvas.grab().toImage().pixelColor(self.screen(30, 40))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(90, 40))
        self.wait_worker()
        pixel = self.controller.document.active.image.getpixel((30, 40))
        for actual, wanted in zip(preview.getRgb(), pixel):
            self.assertAlmostEqual(actual, wanted, delta=3)
        self.assertGreater(pixel[0], 250)
        self.assertLess(pixel[1], 5)
        self.assertLess(pixel[2], 5)
        self.assertEqual(len(self.controller.history.undo_stack), 1)
        self.controller.undo()
        self.assertIs(self.controller.document, original)
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key.Key_Delete)
        self.assertEqual(len(editor.stops), 3)
        QTest.keyClick(editor, Qt.Key.Key_Delete)
        self.assertEqual(len(editor.stops), 2)
        QTest.keyClick(editor, Qt.Key.Key_Delete)
        self.assertEqual(len(editor.stops), 2)

    def test_dragging_end_stops_and_escape_restores_stop_position(self):
        self.canvas.set_tool("gradient")
        editor = self.window.gradient_editor
        stop = editor._stops[0]
        initial = editor.stop_point(stop).toPoint()
        target = QPointF(editor.bar.left() + .3 * editor.bar.width(), 28).toPoint()
        QTest.mousePress(editor, Qt.MouseButton.LeftButton, pos=initial)
        QTest.mouseMove(editor, target)
        self.assertAlmostEqual(stop.position, .3, delta=.004)
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        with patch("rasterly.ui.gradient.QColorDialog.getColor") as picker:
            QTest.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=target)
            picker.assert_not_called()
        self.assertEqual(stop.position, 0)
        self.assertEqual(self.window.gradient_mode.currentIndex(), 0)
        QTest.mousePress(editor, Qt.MouseButton.LeftButton, pos=initial)
        QTest.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=target)
        self.assertAlmostEqual(stop.position, .3, delta=.004)
        self.assertEqual(self.window.gradient_mode.currentIndex(), 2)

    def test_presets_reset_stops_and_follow_foreground_only_until_customized(self):
        self.canvas.set_tool("gradient")
        editor = self.window.gradient_editor
        self.window.colors.set_color(QColor("#123456"))
        self.assertEqual(editor.stops, ((0, (18, 52, 86, 255)), (1, (255, 255, 255, 255))))
        with patch("rasterly.ui.gradient.QColorDialog.getColor", return_value=QColor("#ff0000")):
            point = QPointF(editor.bar.center()).toPoint()
            QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(len(editor.stops), 3)
        self.canvas.set_tool("bucket")
        self.canvas.set_tool("gradient")
        self.assertEqual(len(editor.stops), 3)
        self.window.gradient_mode.setCurrentIndex(1)
        self.assertEqual(editor.stops, ((0, (18, 52, 86, 255)), (1, (18, 52, 86, 0))))
        self.window.colors.set_color(QColor("#abcdef"))
        self.assertEqual(editor.stops, ((0, (171, 205, 239, 255)), (1, (171, 205, 239, 0))))
        with patch("rasterly.ui.gradient.QColorDialog.getColor", return_value=QColor()):
            QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=editor.stop_point(editor._stops[0]).toPoint())
        self.assertEqual(editor.preset, 1)


if __name__ == "__main__":
    unittest.main()
