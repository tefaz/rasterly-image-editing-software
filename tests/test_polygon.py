import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QContextMenuEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from rasterly import files, operations
from rasterly.model import Document
from rasterly.selection import Selection
from rasterly.ui.style import STYLE
from rasterly.ui.window import EditorWindow

app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(STYLE)


class PolygonTests(unittest.TestCase):
    def setUp(self):
        self.window = EditorWindow()
        self.controller = self.window.controller
        self.errors = []
        self.controller.error.disconnect(self.window.show_error)
        self.controller.error.connect(self.errors.append)
        self.window.show()
        self.controller.add_document(Document.new(200, 120))
        self.canvas = self.window.canvas
        self.canvas.set_zoom(2)
        self.canvas.set_tool("polygon")
        self.tool = self.canvas.tools["polygon"]
        app.processEvents()

    def tearDown(self):
        for session in self.controller.sessions:
            session.saved_revision = session.document.revision
        self.window.close()
        self.window.deleteLater()
        app.processEvents()
        self.assertFalse(self.errors, self.errors)

    def screen(self, x, y):
        return self.canvas.to_screen(QPointF(x, y)).toPoint()

    def click(self, x, y, modifiers=Qt.KeyboardModifier.NoModifier):
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, modifiers, pos=self.screen(x, y))

    def triangle(self, modifiers=Qt.KeyboardModifier.NoModifier):
        self.click(20, 20, modifiers)
        self.click(160, 20)
        self.click(70, 90)

    def context_menu(self, callback):
        point = self.screen(80, 40)
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, self.canvas.mapToGlobal(point))
        with patch("rasterly.tools.polygon.QMenu.exec", new=callback):
            self.canvas.contextMenuEvent(event)

    def create_selection(self):
        def choose(menu, position):
            action = menu.actions()[0]
            self.assertEqual(action.text(), "Create Selection")
            self.assertTrue(action.isEnabled())
            return action
        self.context_menu(choose)

    def test_click_points_close_then_context_menu_creates_undoable_selection(self):
        before = self.controller.document
        self.controller.saved_revision = before.revision
        self.triangle()
        self.assertEqual(self.tool.points, [(20, 20), (160, 20), (70, 90)])
        self.assertFalse(self.tool.closed)
        self.assertEqual(self.controller.document.revision, before.revision)
        self.assertIs(self.controller.document.active.image, before.active.image)
        self.assertIsNone(self.controller.document.selection)
        self.assertEqual(len(self.controller.history.undo_stack), 3)
        image = self.canvas.grab().toImage()
        self.assertNotEqual(image.pixelColor(self.screen(90, 20)).getRgb(), (255, 255, 255, 255))
        self.assertEqual(image.pixelColor(self.screen(45, 55)).getRgb(), (255, 255, 255, 255))
        self.click(20, 20)
        self.assertTrue(self.tool.closed)
        self.assertEqual(len(self.tool.points), 3)
        self.assertIsNone(self.controller.document.selection)
        self.assertEqual(len(self.controller.history.undo_stack), 4)
        self.create_selection()
        selection = self.controller.document.selection
        self.assertEqual(selection.points, ((20, 20), (160, 20), (70, 90)))
        mask = selection.mask((0, 0, 200, 120))
        self.assertEqual(mask.getpixel((70, 40)), 255)
        self.assertEqual(mask.getpixel((150, 90)), 0)
        self.assertFalse(self.tool.points)
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Polygon selection")
        self.assertFalse(self.controller.dirty)
        self.controller.undo()
        self.assertIsNone(self.controller.document.selection)
        self.controller.redo()
        self.assertEqual(self.controller.document.selection, selection)
        self.window.apply("Fill", lambda doc: operations.solid_fill(doc, (255, 0, 0, 255)))
        image = self.controller.document.active.image
        self.assertEqual(image.getpixel((70, 40)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((150, 90)), (255, 255, 255, 255))

    def test_create_selection_disabled_until_valid_path_is_closed(self):
        def check_disabled(menu, position):
            self.assertFalse(menu.actions()[0].isEnabled())
            return None
        for x, y in ((20, 20), (50, 50), (80, 80)):
            self.click(x, y)
        self.click(20, 20)
        self.assertFalse(self.tool.closed)
        self.context_menu(check_disabled)
        self.click(120, 20)
        self.assertTrue(self.tool.has_area)
        self.context_menu(check_disabled)
        self.click(20, 20)
        self.create_selection()
        self.assertIsNotNone(self.controller.document.selection)

    def test_backspace_removes_vertex_and_escape_or_menu_cancel_preserves_selection(self):
        original = Selection.rectangle(5, 5, 15, 15)
        self.controller.set_selection(original)
        count = len(self.controller.history.undo_stack)
        self.triangle()
        QTest.keyClick(self.canvas, Qt.Key.Key_Backspace)
        self.assertEqual(len(self.tool.points), 2)
        self.click(70, 90)
        self.click(20, 20)
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertFalse(self.tool.points)
        self.assertEqual(self.controller.document.selection, original)
        self.assertGreater(len(self.controller.history.undo_stack), count)
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Cancel polygon path")
        self.triangle()
        self.context_menu(lambda menu, position: menu.actions()[1])
        self.assertFalse(self.tool.points)
        self.assertEqual(self.controller.document.selection, original)

    def test_shift_add_and_alt_subtract_polygon_regions(self):
        original = Selection.rectangle(0, 0, 100, 100)
        for modifier in (Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.AltModifier):
            with self.subTest(modifier=modifier):
                self.controller.set_selection(original)
                self.triangle(modifier)
                self.click(20, 20)
                self.create_selection()
                mask = self.controller.document.selection.mask((0, 0, 200, 120))
                self.assertEqual(mask.getpixel((5, 5)), 255)
                self.assertEqual(mask.getpixel((70, 40)),
                                 255 if modifier == Qt.KeyboardModifier.ShiftModifier else 0)
                self.assertEqual(mask.getpixel((130, 25)),
                                 255 if modifier == Qt.KeyboardModifier.ShiftModifier else 0)

    def test_zoom_pan_and_start_point_hit_target_keep_document_coordinates(self):
        self.triangle()
        original = list(self.tool.points)
        self.canvas.set_zoom(3.5)
        self.canvas.pan += QPointF(40, 20)
        start = self.screen(20, 20) + QPoint(5, 0)
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        self.assertTrue(self.tool.closed)
        self.assertEqual(self.tool.points, original)
        self.create_selection()
        self.assertEqual(self.controller.document.selection.points, tuple(original))

    def test_tool_document_and_tab_changes_discard_uncommitted_path(self):
        self.triangle()
        self.canvas.set_tool("move")
        self.assertFalse(self.tool.points)
        self.canvas.set_tool("polygon")
        self.triangle()
        self.controller.select_layer(self.controller.document.active_id)
        self.assertFalse(self.tool.points)
        self.triangle()
        self.controller.add_document(Document.new(20, 20))
        self.assertFalse(self.tool.points)
        self.controller.switch_document(0)
        self.assertIsNone(self.controller.document.selection)

    def test_toolbar_shortcut_and_text_input_do_not_conflict(self):
        self.assertLess(self.window.tool_buttons["lasso"].y(), self.window.tool_buttons["polygon"].y())
        self.assertLess(self.window.tool_buttons["polygon"].y(), self.window.tool_buttons["patch"].y())
        self.canvas.set_tool("move")
        QTest.keyClick(self.canvas, Qt.Key.Key_P)
        self.assertEqual(self.canvas.tool_id, "polygon")
        self.canvas.set_tool("text")
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(20, 20))
        editor = self.canvas.tools["text"].editor
        QTest.keyClicks(editor, "polygon")
        self.assertEqual(editor.toPlainText(), "polygon")
        self.assertEqual(self.canvas.tool_id, "text")
        self.canvas.tools["text"].cancel()

    def test_alt_click_removes_middle_vertex_and_toggle_undo_restores_it(self):
        self.triangle()
        before = tuple(self.tool.points)
        self.click(160, 20, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.tool.points, [(20, 20), (70, 90)])
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Remove polygon point 2")
        QTest.keyClick(self.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(tuple(self.tool.points), before)
        QTest.keyClick(self.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.tool.points, [(20, 20), (70, 90)])
        self.assertEqual(self.controller.history.position, 4)

    def test_alt_click_removes_first_vertex_of_closed_path_and_reopens_if_too_small(self):
        for x, y in ((20, 20), (160, 20), (160, 90), (20, 90), (20, 20)):
            self.click(x, y)
        self.assertTrue(self.tool.closed)
        self.click(20, 20, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.tool.points, [(160, 20), (160, 90), (20, 90)])
        self.assertTrue(self.tool.closed)
        self.click(160, 90, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.tool.points, [(160, 20), (20, 90)])
        self.assertFalse(self.tool.closed)
        QTest.keyClick(self.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.tool.closed)
        self.assertEqual(len(self.tool.points), 3)

    def test_each_point_has_history_entry_with_toggle_and_continuous_step_back(self):
        before = self.controller.document
        self.controller.saved_revision = before.revision
        self.triangle()
        self.assertEqual(self.controller.history.state_labels,
                         ["New image", "Add polygon point 1", "Add polygon point 2", "Add polygon point 3"])
        self.assertEqual(self.window.history_overlay.list.count(), 4)
        for expected in (2, 3, 2, 3):
            QTest.keyClick(self.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(len(self.tool.points), expected)
            self.assertEqual(self.controller.history.position, expected)
        for expected in (2, 1, 0):
            QTest.keyClick(self.canvas, Qt.Key.Key_Z,
                           Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
            self.assertEqual(len(self.tool.points), expected)
        for expected in (1, 2, 3):
            QTest.keyClick(self.canvas, Qt.Key.Key_Z,
                           Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            self.assertEqual(len(self.tool.points), expected)
        self.assertIs(self.controller.document.active.image, before.active.image)
        self.assertFalse(self.controller.dirty)
        self.assertIsNone(self.controller.document.selection)

    def test_removing_only_vertex_is_undoable_and_hit_target_tracks_zoom_and_pan(self):
        self.click(40, 40)
        self.canvas.set_zoom(3.5)
        self.canvas.pan += QPointF(20, 10)
        point = self.screen(40, 40) + QPoint(5, 0)
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, pos=point)
        self.assertFalse(self.tool.points)
        QTest.keyClick(self.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.tool.points, [(40, 40)])

    def test_new_point_after_history_step_discards_future_points(self):
        self.triangle()
        self.window.undo()
        self.assertEqual(len(self.tool.points), 2)
        self.click(100, 100)
        self.assertEqual(self.tool.points, [(20, 20), (160, 20), (100, 100)])
        self.assertFalse(self.controller.history.redo_stack)
        self.assertFalse(self.window.actions["redo"].isEnabled())

    def test_history_overlay_restores_point_states_and_closed_path_after_selection(self):
        self.triangle()
        self.click(20, 20)
        self.create_selection()
        self.window.jump_history(2)
        self.assertEqual(self.tool.points, [(20, 20), (160, 20)])
        self.assertFalse(self.tool.closed)
        self.assertIsNone(self.controller.document.selection)
        self.window.jump_history(4)
        self.assertTrue(self.tool.closed)
        self.assertEqual(len(self.tool.points), 3)
        self.window.jump_history(5)
        self.assertFalse(self.tool.points)
        self.assertIsNotNone(self.controller.document.selection)

    def test_cancel_history_restores_path_and_project_save_does_not_store_draft(self):
        self.triangle()
        self.canvas.set_tool("move")
        self.assertFalse(self.tool.points)
        self.window.undo()
        self.assertEqual(self.canvas.tool_id, "polygon")
        self.assertEqual(len(self.tool.points), 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "draft.rasterly"
            files.save_project(self.controller.document, path)
            opened = files.open_document(path)
            self.assertIsNone(opened.polygon_path)
            self.assertIsNone(opened.selection)
            self.assertEqual(opened.active.image.tobytes(), self.controller.document.active.image.tobytes())


if __name__ == "__main__":
    unittest.main()
