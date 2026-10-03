import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
import time
import unittest

from PIL import Image
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from rasterly.model import Document, Layer, TextData
from rasterly.painting import PaintStroke
from rasterly.selection import Selection
from rasterly.ui.style import STYLE
from rasterly.ui.window import EditorWindow

app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(STYLE)


class PaintStrokeTests(unittest.TestCase):
    def test_click_paints_round_dab_and_fast_drag_is_continuous(self):
        doc = Document.from_image(Image.new("RGBA", (100, 60)))
        stroke = PaintStroke(doc, size=6, color=(255, 0, 0, 255))
        stroke.add((10.5, 30.5))
        self.assertEqual(stroke.preview.image.getpixel((10, 30)), (255, 0, 0, 255))
        stroke.add((90.5, 30.5))
        result = stroke.finish()
        for x in range(10, 91):
            self.assertEqual(result.active.image.getpixel((x, 30)), (255, 0, 0, 255))
        self.assertEqual(result.active.image.getpixel((50, 40)), (0, 0, 0, 0))
        self.assertEqual(doc.active.image.getbbox(), None)

    def test_opacity_does_not_accumulate_where_one_stroke_overlaps_itself(self):
        doc = Document.from_image(Image.new("RGBA", (100, 60)))
        stroke = PaintStroke(doc, size=12, opacity=50, color=(10, 20, 30, 255))
        for point in ((10.5, 30.5), (90.5, 30.5), (10.5, 30.5), (90.5, 30.5)):
            stroke.add(point)
        painted = stroke.finish()
        self.assertEqual(painted.active.image.getpixel((50, 30)), (10, 20, 30, 128))
        second = PaintStroke(painted, size=12, opacity=50, color=(10, 20, 30, 255))
        second.add((50.5, 30.5))
        result = second.finish()
        self.assertEqual(result.active.image.getpixel((50, 30))[3], 192)
        self.assertEqual(result.active.image.getpixel((20, 30))[3], 128)

    def test_eraser_removes_alpha_without_affecting_other_layers_or_original(self):
        bottom = Layer("Bottom", Image.new("RGBA", (100, 60), "green"))
        top = Layer("Top", Image.new("RGBA", (100, 60), "red"))
        doc = Document(100, 60, (bottom, top), top.id)
        stroke = PaintStroke(doc, size=10, erase=True)
        stroke.add((10.5, 30.5))
        stroke.add((90.5, 30.5))
        erased = stroke.finish()
        self.assertEqual(erased.active.image.getpixel((50, 30))[3], 0)
        self.assertEqual(erased.active.image.getpixel((50, 50)), (255, 0, 0, 255))
        self.assertIs(erased.layers[0], bottom)
        self.assertEqual(top.image.getpixel((50, 30)), (255, 0, 0, 255))

    def test_brush_and_eraser_respect_irregular_selection_with_hole(self):
        selection = Selection("lasso", ((5, 5), (55, 5), (5, 55))).subtracted(
            Selection.rectangle(10, 10, 20, 20))
        for erase in (False, True):
            with self.subTest(erase=erase):
                doc = Document.from_image(Image.new("RGBA", (60, 60), "blue")).edited(selection=selection)
                stroke = PaintStroke(doc, size=60, color=(255, 0, 0, 255), erase=erase)
                stroke.add((25.5, 25.5))
                result = stroke.finish()
                mask = selection.mask((0, 0, 60, 60))
                for y in range(60):
                    for x in range(60):
                        if not mask.getpixel((x, y)):
                            self.assertEqual(result.active.image.getpixel((x, y)), (0, 0, 255, 255))
                pixel = result.active.image.getpixel((25, 15))
                self.assertEqual(pixel[3], 0 if erase else 255)
                if not erase:
                    self.assertEqual(pixel[:3], (255, 0, 0))
                self.assertIs(result.selection, selection)

    def test_soft_brush_has_gradual_edges(self):
        doc = Document.from_image(Image.new("RGBA", (60, 60)))
        stroke = PaintStroke(doc, size=20, hardness=0, color=(255, 0, 0, 255))
        stroke.add((30.5, 30.5))
        image = stroke.finish().active.image
        self.assertEqual(image.getpixel((30, 30))[3], 255)
        self.assertGreater(image.getpixel((34, 30))[3], image.getpixel((38, 30))[3])
        self.assertGreater(image.getpixel((38, 30))[3], 0)
        self.assertEqual(image.getpixel((42, 30))[3], 0)

    def test_partial_eraser_opacity_is_applied_once_per_stroke(self):
        doc = Document.from_image(Image.new("RGBA", (100, 60), (80, 120, 160, 128)))
        stroke = PaintStroke(doc, size=12, opacity=50, erase=True)
        for point in ((10.5, 30.5), (90.5, 30.5), (10.5, 30.5)):
            stroke.add(point)
        result = stroke.finish()
        pixel = result.active.image.getpixel((50, 30))
        self.assertEqual(pixel[:3], (80, 120, 160))
        self.assertAlmostEqual(pixel[3], 64, delta=1)
        self.assertEqual(result.active.image.getpixel((50, 50)), (80, 120, 160, 128))

    def test_paint_expands_offset_layer_and_keeps_pixels_outside_canvas(self):
        layer = Layer("Offset", Image.new("RGBA", (5, 5), "blue"), -2, -2)
        doc = Document(100, 60, (layer,), layer.id)
        stroke = PaintStroke(doc, size=12, color=(255, 0, 0, 255))
        stroke.add((90.5, 50.5))
        result = stroke.finish()
        self.assertEqual((result.active.x, result.active.y), (-2, -2))
        self.assertEqual(result.active.image.getpixel((0, 0)), (0, 0, 255, 255))
        self.assertEqual(result.active.image.getpixel((92, 52)), (255, 0, 0, 255))
        self.assertEqual(layer.image.size, (5, 5))

    def test_crossing_canvas_from_outside_clips_stroke_to_document(self):
        layer = Layer("Offset", Image.new("RGBA", (104, 64), "blue"), -2, -2)
        doc = Document(100, 60, (layer,), layer.id)
        stroke = PaintStroke(doc, size=10, erase=True)
        stroke.add((-20, 30.5))
        stroke.add((120, 30.5))
        image = stroke.finish().active.image
        self.assertEqual(image.getpixel((2, 32))[3], 0)
        self.assertEqual(image.getpixel((101, 32))[3], 0)
        self.assertEqual(image.getpixel((0, 32)), (0, 0, 255, 255))
        self.assertEqual(image.getpixel((103, 32)), (0, 0, 255, 255))

    def test_noop_strokes_return_original_document(self):
        doc = Document.from_image(Image.new("RGBA", (60, 60)))
        for options, points in (({"erase": True}, [(10, 10)]),
                                ({"opacity": 0}, [(10, 10)]),
                                ({"color": (255, 0, 0, 0)}, [(10, 10)]),
                                ({}, [(-50, -50), (-40, -40)])):
            stroke = PaintStroke(doc, **options)
            for point in points:
                stroke.add(point)
            self.assertIs(stroke.finish(), doc)

    def test_hidden_and_editable_text_layers_reject_painting(self):
        doc = Document.new(30, 30)
        for layer in (replace(doc.active, visible=False), replace(doc.active, text=TextData("Hello"))):
            with self.assertRaises(ValueError):
                PaintStroke(doc.with_layer(layer))


class BrushInteractionTests(unittest.TestCase):
    def setUp(self):
        self.window = EditorWindow()
        self.controller = self.window.controller
        self.errors = []
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

    def test_toolbar_order_shortcuts_and_independent_tool_settings(self):
        buttons = self.window.tool_buttons
        self.assertLess(buttons["patch"].y(), buttons["brush"].y())
        self.assertLess(buttons["brush"].y(), buttons["eraser"].y())
        self.assertLess(buttons["eraser"].y(), buttons["text"].y())
        QTest.keyClick(self.canvas, Qt.Key.Key_B)
        self.assertEqual(self.canvas.tool_id, "brush")
        self.assertTrue(self.window.paint_controls.isVisible())
        self.window.paint_spins["size"].setValue(12)
        self.window.paint_spins["hardness"].setValue(40)
        self.canvas.setFocus()
        QTest.keyClick(self.canvas, Qt.Key.Key_E)
        self.assertEqual(self.canvas.tool_id, "eraser")
        self.assertEqual(self.window.paint_spins["size"].value(), 24)
        self.canvas.set_tool("brush")
        self.assertEqual(self.window.paint_spins["size"].value(), 12)
        self.assertEqual(self.window.paint_spins["hardness"].value(), 40)
        QTest.keyClick(self.canvas, Qt.Key.Key_BracketRight)
        self.assertEqual(self.window.paint_spins["size"].value(), 15)
        QTest.keyClick(self.canvas, Qt.Key.Key_BracketLeft)
        self.assertEqual(self.window.paint_spins["size"].value(), 12)

    def test_fast_brush_drag_previews_foreground_color_and_creates_one_undo_step(self):
        self.window.colors.set_color(QColor("#ff0000"))
        self.canvas.set_tool("brush")
        self.window.paint_spins["size"].setValue(10)
        original = self.controller.document
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(10, 40))
        QTest.mouseMove(self.canvas, self.screen(90, 40))
        self.assertIs(self.controller.document, original)
        self.assertEqual(len(self.controller.history.undo_stack), 0)
        pixel = self.canvas.grab().toImage().pixelColor(self.screen(50, 40))
        self.assertEqual(pixel.getRgb(), (255, 0, 0, 255))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(90, 40))
        self.wait_worker()
        for x in range(12, 89):
            self.assertEqual(self.controller.document.active.image.getpixel((x, 40)), (255, 0, 0, 255))
        self.assertIsNone(self.canvas.stroke_preview)
        self.assertEqual(len(self.controller.history.undo_stack), 1)
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Brush stroke")
        self.controller.undo()
        self.assertIs(self.controller.document, original)
        self.controller.redo()
        self.assertEqual(self.controller.document.active.image.getpixel((50, 40)), (255, 0, 0, 255))

    def test_eraser_preview_reveals_lower_layer_and_commit_matches(self):
        bottom = Layer("Bottom", Image.new("RGBA", (100, 80), "green"))
        top = Layer("Top", Image.new("RGBA", (100, 80), "red"))
        self.controller.replace_document(Document(100, 80, (bottom, top), top.id))
        self.canvas.set_zoom(3)
        self.canvas.set_tool("eraser")
        self.window.paint_spins["size"].setValue(12)
        original = self.controller.document
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(10, 40))
        QTest.mouseMove(self.canvas, self.screen(90, 40))
        preview = self.canvas.grab().toImage()
        self.assertEqual(preview.pixelColor(self.screen(50, 40)).getRgb(), (0, 128, 0, 255))
        self.assertEqual(preview.pixelColor(self.screen(50, 65)).getRgb(), (255, 0, 0, 255))
        self.assertIs(self.controller.document, original)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(90, 40))
        self.wait_worker()
        self.assertEqual(self.controller.document.active.image.getpixel((50, 40))[3], 0)
        self.assertIs(self.controller.document.layers[0], bottom)
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Eraser stroke")
        self.controller.undo()
        self.assertIs(self.controller.document, original)

    def test_click_dab_escape_and_tool_switch_cancel_preview_without_editing(self):
        self.canvas.set_tool("brush")
        original = self.controller.document
        for cancel in (lambda: QTest.keyClick(self.canvas, Qt.Key.Key_Escape),
                       lambda: self.canvas.set_tool("eraser")):
            QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(40, 40))
            self.assertIsNotNone(self.canvas.stroke_preview)
            cancel()
            QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(50, 40))
            self.assertIsNone(self.canvas.stroke_preview)
            self.assertIs(self.controller.document, original)
        self.assertEqual(len(self.controller.history.undo_stack), 0)
        self.canvas.set_tool("brush")
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(40, 40))
        self.wait_worker()
        self.assertEqual(self.controller.document.active.image.getpixel((40, 40)), (0, 0, 0, 255))

    def test_brush_shortcuts_do_not_intercept_color_input_and_canvas_edges_clip_paint(self):
        field = self.window.colors.hex_input
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "#beefee")
        self.assertEqual(self.canvas.tool_id, "move")
        QTest.keyClick(field, Qt.Key.Key_Return)
        self.canvas.set_tool("brush")
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(-20, 40))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(120, 40))
        self.wait_worker()
        self.assertEqual(self.controller.document.active.bounds, (0, 0, 100, 80))
        self.assertEqual(self.controller.document.active.image.getpixel((0, 40)), (190, 239, 238, 255))

    def test_changing_layer_during_stroke_discards_preview(self):
        self.controller.apply("New layer", lambda doc:
            doc.with_layer(replace(doc.active, image=Image.new("RGBA", (100, 80), "red"))))
        self.window.actions["layer_new"].trigger()
        original = self.controller.document
        count = len(self.controller.history.undo_stack)
        self.canvas.set_tool("brush")
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(20, 40))
        self.assertIsNotNone(self.canvas.stroke_preview)
        self.controller.select_layer(original.layers[0].id)
        self.assertIsNone(self.canvas.stroke_preview)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(80, 40))
        self.assertEqual(len(self.controller.history.undo_stack), count)
        self.assertEqual(self.controller.document.layers[1].image.getbbox(), None)
        self.assertIs(self.controller.document.layers[0], original.layers[0])


if __name__ == "__main__":
    unittest.main()
