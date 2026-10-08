import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
from PIL import Image
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, QSettings
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QTabBar, QMenu, QToolButton
from PyQt6.QtGui import QImage, QContextMenuEvent, QPainter, QColor
from rasterly.model import Document
from rasterly.selection import Selection
from rasterly.ui.window import EditorWindow
from rasterly.ui.dialogs import SizeDialog, FillDialog
from rasterly.ui.style import STYLE
from rasterly import files, operations

app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(STYLE)


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.window = EditorWindow()
        self.errors = []
        self.window.controller.error.disconnect(self.window.show_error)
        self.window.controller.error.connect(self.errors.append)
        self.window.show()
        QTest.qWait(2)
        self.window.controller.replace_document(Document.new(200, 120))
        self.window.canvas.set_zoom(2)
        self.canvas = self.window.canvas
        self.controller = self.window.controller
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
        self.assertFalse(self.controller.busy, "Background operation timed out")
        self.assertFalse(self.errors, self.errors)

    def test_rectangular_drag_has_live_pixel_dimensions_and_marching_ants(self):
        self.canvas.set_tool("rectangle")
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(10, 20))
        QTest.mouseMove(self.canvas, self.screen(83, 61))
        self.assertEqual(self.canvas.measurement, "73 × 41 px")
        self.assertIsNone(self.controller.document.selection)
        self.assertEqual(self.canvas.preview_selection.bounds, (10, 20, 83, 61))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(83, 61))
        self.assertEqual(self.controller.document.selection.bounds, (10, 20, 83, 61))
        self.assertIsNone(self.canvas.measurement)

    def test_outside_rectangle_keeps_original_corner_when_drag_enters_through_side(self):
        self.canvas.set_tool("rectangle")
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(210, -20))
        QTest.mouseMove(self.canvas, self.screen(220, 10))
        self.assertIsNone(self.canvas.preview_selection)
        QTest.mouseMove(self.canvas, self.screen(180, 20))
        self.assertEqual(self.canvas.preview_selection.bounds, (180, 0, 200, 20))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(-10, 130))
        self.assertEqual(self.controller.document.selection.bounds, (0, 0, 200, 120))
        self.assertIsNone(self.canvas.measurement)

    def test_outside_rectangle_covers_entire_canvas_from_every_corner_at_different_zooms(self):
        paths = [((210, -20), (-10, 130)), ((-10, -20), (210, 130)),
                 ((210, 140), (-10, -10)), ((-10, 140), (210, -10))]
        self.canvas.set_tool("rectangle")
        for zoom in (.25, .67, 2, 4):
            self.canvas.set_zoom(zoom)
            self.canvas.pan = QPointF(-15, 23)
            for start, end in paths:
                with self.subTest(zoom=zoom, start=start):
                    self.controller.set_selection(None)
                    QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(*start))
                    # A quick drag can arrive at release without an intermediate move event.
                    QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(*end))
                    selection = self.controller.document.selection
                    self.assertIsNotNone(selection)
                    self.assertEqual(selection.bounds, (0, 0, 200, 120))
                    self.assertEqual(selection.mask((0, 0, 200, 120)).getextrema(), (255, 255))

    def test_outside_rectangle_never_entering_or_cancelled_preserves_previous_selection(self):
        self.canvas.set_tool("rectangle")
        self.controller.set_selection(Selection.rectangle(20, 20, 60, 60))
        original = self.controller.document
        count = len(self.controller.history.undo_stack)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(210, -20))
        QTest.mouseMove(self.canvas, self.screen(220, 50))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(210, 130))
        self.assertIs(self.controller.document, original)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(210, -20))
        QTest.mouseMove(self.canvas, self.screen(220, 10))
        QTest.mouseMove(self.canvas, self.screen(20, 100))
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(20, 100))
        self.assertIs(self.controller.document, original)
        self.assertEqual(len(self.controller.history.undo_stack), count)

    def test_outside_lasso_and_patch_trace_actual_entry_edge(self):
        for tool in ("lasso", "patch"):
            with self.subTest(tool=tool):
                self.canvas.set_tool(tool)
                self.controller.set_selection(Selection.rectangle(150, 0, 200, 50))
                QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(210, -20))
                QTest.mouseMove(self.canvas, self.screen(220, 10))
                QTest.mouseMove(self.canvas, self.screen(180, 20))
                self.assertEqual(self.canvas.tools[tool].points[0], (200, 15))
                if tool == "patch":
                    self.assertFalse(self.canvas.tools[tool].sourcing)
                QTest.mouseMove(self.canvas, self.screen(20, 100))
                QTest.mouseMove(self.canvas, self.screen(200, 100))
                QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(200, 15))
                self.assertEqual(self.controller.document.selection.bounds, (20, 15, 200, 100))

    def test_lasso_closes_and_displays_bounding_dimensions_during_drag(self):
        self.canvas.set_tool("lasso")
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(20, 20))
        QTest.mouseMove(self.canvas, self.screen(80, 20))
        QTest.mouseMove(self.canvas, self.screen(45, 70))
        self.assertEqual(self.canvas.measurement, "60 × 50 px")
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(20, 20))
        selection = self.controller.document.selection
        self.assertEqual(selection.kind, "lasso")
        self.assertTrue(self.canvas.selection_contains(QPointF(45, 35)))
        self.assertFalse(self.canvas.selection_contains(QPointF(77, 65)))

    def test_escape_while_drawing_restores_previous_selection(self):
        original = Selection.rectangle(5, 5, 10, 10)
        self.controller.set_selection(original)
        self.canvas.set_tool("rectangle")
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(30, 30))
        QTest.mouseMove(self.canvas, self.screen(80, 80))
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertEqual(self.controller.document.selection, original)
        self.assertFalse(self.canvas.dragging)

    def test_move_drag_previews_without_pixel_mutation_then_undoes(self):
        original = self.controller.document
        self.controller.set_selection(Selection.rectangle(10, 10, 30, 30))
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(15, 15))
        QTest.mouseMove(self.canvas, self.screen(45, 35))
        self.assertIs(self.controller.document.active.image, original.active.image)
        self.assertEqual(self.canvas.move_preview[1:], (30, 20))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(45, 35))
        self.assertEqual(self.controller.document.selection.bounds, (40, 30, 60, 50))
        self.assertEqual(self.controller.document.active.image.getpixel((15, 15))[3], 0)
        self.window.undo()
        self.assertEqual(self.controller.document.active.image.getpixel((15, 15)), (255, 255, 255, 255))

    def test_ctrl_t_enters_transform_and_escape_preserves_original_pixels(self):
        before = self.controller.document
        QTest.keyClick(self.canvas, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
        self.assertIsNotNone(self.canvas.session)
        session = self.canvas.session
        session.start(QPointF(200, 120), "se")
        session.update(QPointF(300, 150), False)
        self.assertEqual((session.box.width(), session.box.height()), (300, 150))
        self.assertIs(self.controller.document.active.image, before.active.image)
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertIsNone(self.canvas.session)
        self.assertEqual(self.controller.document.revision, before.revision)

    def test_transform_shift_locks_original_ratio_and_normal_resize_is_independent(self):
        self.canvas.begin_transform()
        session = self.canvas.session
        session.start(QPointF(200, 120), "se")
        session.update(QPointF(300, 145), True)
        self.assertAlmostEqual(session.box.width() / session.box.height(), 200 / 120)
        session.start(session.box.bottomRight(), "se")
        session.update(session.box.bottomRight() + QPointF(20, 3), False)
        self.assertNotAlmostEqual(session.box.width() / session.box.height(), 200 / 120)

    def test_transform_enter_commits_and_shortcuts_undo_and_redo(self):
        self.canvas.begin_transform()
        self.window.transform_width.setValue(100)
        self.window.transform_height.setValue(60)
        self.canvas.setFocus()
        QTest.keyClick(self.canvas, Qt.Key.Key_Return)
        self.wait_worker()
        self.assertIsNone(self.canvas.session)
        self.assertEqual(self.controller.document.active.image.size, (100, 60))
        QTest.keyClick(self.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.controller.document.active.image.size, (200, 120))
        QTest.keyClick(self.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.controller.document.active.image.size, (100, 60))

    def test_shift_f5_opens_content_aware_fill_dialog(self):
        self.controller.set_selection(Selection.rectangle(10, 10, 30, 30))
        observed = []
        def accept_dialog():
            dialog = app.activeModalWidget()
            observed.append(isinstance(dialog, FillDialog))
            observed.append(dialog.mode.currentText())
            dialog.accept()
        QTimer.singleShot(5, accept_dialog)
        QTest.keyClick(self.canvas, Qt.Key.Key_F5, Qt.KeyboardModifier.ShiftModifier)
        self.wait_worker()
        self.assertEqual(observed, [True, "Content-Aware"])
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Content-Aware Fill")

    def test_patch_workflow_selects_then_drags_source_and_commits_healing(self):
        self.canvas.set_tool("patch")
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(30, 30))
        for point in ((50, 30), (50, 50), (30, 50)):
            QTest.mouseMove(self.canvas, self.screen(*point))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(30, 30))
        original = self.controller.document.active.image
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(40, 40))
        QTest.mouseMove(self.canvas, self.screen(90, 70))
        self.assertEqual(self.canvas.patch_offset, (50, 30))
        self.assertIs(self.controller.document.active.image, original)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=self.screen(90, 70))
        self.wait_worker()
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Patch")
        self.assertEqual(self.controller.document.selection.bounds, (30, 30, 50, 50))

    def test_layers_panel_can_toggle_rename_select_and_reorder(self):
        self.window.actions["layer_new"].trigger()
        self.assertEqual(self.window.layers.list.count(), 2)
        top = self.window.layers.list.item(0)
        top.setText("Retouch")
        self.assertEqual(self.controller.document.active.name, "Retouch")
        # Rebuilding the list replaces item objects.
        self.window.layers.list.item(0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(self.controller.document.active.visible)
        self.window.layers.shift(-1)
        self.assertEqual(self.controller.document.layers[0].name, "Retouch")
        self.window.layers.list.setCurrentRow(0)
        self.assertEqual(self.controller.document.active.name, "Background")

    def test_new_layer_button_creates_fully_transparent_layer(self):
        original = self.controller.document
        button = next(button for button in self.window.layers.findChildren(QToolButton)
                      if button.toolTip() == "Create transparent layer")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        doc = self.controller.document
        self.assertEqual(len(doc.layers), 2)
        self.assertEqual(doc.active.image.size, (200, 120))
        self.assertEqual(doc.active.image.getextrema(), ((0, 0),) * 4)
        self.assertIs(doc.layers[0], original.active)
        self.assertEqual(self.controller.history.undo_stack[-1].label, "New layer")
        self.controller.undo()
        self.assertIs(self.controller.document, original)

    def test_delete_clears_selection_on_active_layer_and_restores_exactly_with_undo(self):
        self.window.actions["layer_new"].trigger()
        self.controller.apply("Paint", lambda doc:
            doc.with_layer(replace(doc.active, image=Image.new("RGBA", (200, 120), "red"))))
        self.controller.set_selection(Selection.rectangle(10, 20, 40, 60))
        self.controller.select_layers({layer.id for layer in self.controller.document.layers},
                                      self.controller.document.active_id)
        original = self.controller.document
        count = len(self.controller.history.undo_stack)
        self.window.layers.list.setFocus()
        QTest.keyClick(self.window.layers.list, Qt.Key.Key_Delete)
        doc = self.controller.document
        self.assertEqual(len(doc.layers), 2)
        self.assertIs(doc.layers[0], original.layers[0])
        self.assertEqual(doc.active.image.getpixel((10, 20)), (0, 0, 0, 0))
        self.assertEqual(doc.active.image.getpixel((39, 59)), (0, 0, 0, 0))
        self.assertEqual(doc.active.image.getpixel((40, 60)), (255, 0, 0, 255))
        self.assertIs(doc.selection, original.selection)
        self.assertEqual(doc.selected_ids, original.selected_ids)
        self.assertEqual(len(self.controller.history.undo_stack), count + 1)
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Clear selection")
        QTest.keyClick(self.window.layers.list, Qt.Key.Key_Delete)
        self.assertEqual(len(self.controller.history.undo_stack), count + 1)
        self.controller.undo()
        self.assertIs(self.controller.document, original)
        self.controller.redo()
        self.assertIs(self.controller.document, doc)

    def test_delete_without_selection_keeps_layer_and_document(self):
        original = self.controller.document
        self.assertFalse(self.window.actions["clear"].isEnabled())
        QTest.keyClick(self.canvas, Qt.Key.Key_Delete)
        self.assertIs(self.controller.document, original)
        self.assertEqual(len(self.controller.history.undo_stack), 0)

    def test_delete_in_hex_field_and_gradient_editor_does_not_clear_image_selection(self):
        self.controller.set_selection(Selection.rectangle(5, 5, 50, 50))
        original = self.controller.document
        field = self.window.colors.hex_input
        field.setFocus()
        field.selectAll()
        QTest.keyClick(field, Qt.Key.Key_Delete)
        self.assertEqual(field.text(), "")
        self.assertIs(self.controller.document, original)
        self.canvas.set_tool("gradient")
        editor = self.window.gradient_editor
        with patch("rasterly.ui.gradient.QColorDialog.getColor", return_value=QColor("#ff0000")):
            QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=editor.bar.center().toPoint())
        self.assertEqual(len(editor.stops), 3)
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key.Key_Delete)
        self.assertEqual(len(editor.stops), 2)
        self.assertIs(self.controller.document, original)
        self.canvas.setFocus()
        QTest.keyClick(self.canvas, Qt.Key.Key_Delete)
        self.assertEqual(self.controller.document.active.image.getpixel((10, 10)), (0, 0, 0, 0))

    def test_zoom_coordinate_mapping_is_independent_of_full_resolution_data(self):
        self.canvas.pan = QPointF(-57, 123)
        self.canvas.set_zoom(0.37)
        point = QPointF(124, 63)
        mapped = self.canvas.to_document(self.canvas.to_screen(point))
        self.assertAlmostEqual(mapped.x(), point.x())
        self.assertAlmostEqual(mapped.y(), point.y())
        self.assertEqual(self.controller.document.active.image.size, (200, 120))

    def test_percentage_resize_and_canvas_anchor_dialog(self):
        dialog = SizeDialog(Document.new(2000, 1000), self.window)
        dialog.units.setCurrentIndex(1)
        dialog.width_input.setValue(50)
        self.assertEqual(dialog.height_input.value(), 50)
        self.assertEqual(dialog.dimensions, (1000, 500))
        dialog.mode.setCurrentIndex(1)
        self.assertEqual(dialog.anchor, (0.5, 0.5))
        dialog.anchor_group.button(8).setChecked(True)
        self.assertEqual(dialog.anchor, (1, 1))
        dialog.height_input.setValue(70)
        self.assertEqual(dialog.dimensions, (1000, 700))
        dialog.deleteLater()

    def test_save_save_as_and_export_keep_correct_path_and_dirty_state(self):
        with tempfile.TemporaryDirectory() as directory:
            first = str(Path(directory) / "first.rasterly")
            second = str(Path(directory) / "second.rasterly")
            exported = str(Path(directory) / "exported.png")
            self.window.choose_output = lambda export=False: first
            self.assertTrue(self.window.save())
            self.assertEqual(self.controller.path, first)
            self.assertFalse(self.controller.dirty)
            self.window.apply("Move layer", lambda doc: operations.move(doc, 10, 5))
            self.assertTrue(self.controller.dirty)
            self.assertTrue(self.window.save())
            self.assertEqual(files.open_document(first).active.x, 10)
            self.assertFalse(self.controller.dirty)
            self.window.choose_output = lambda export=False: second
            self.assertTrue(self.window.save(True))
            self.assertEqual(self.controller.path, second)
            self.window.apply("Move layer", lambda doc: operations.move(doc, 1, 2))
            saved_revision = self.controller.saved_revision
            self.window.choose_output = lambda export=False: exported
            self.window.export()
            self.assertTrue(Path(exported).exists())
            self.assertEqual(self.controller.path, second)
            self.assertEqual(self.controller.saved_revision, saved_revision)
            self.assertTrue(self.controller.dirty)

    def test_cancelled_save_as_keeps_path_and_saved_state(self):
        before = self.controller.document.revision
        self.window.choose_output = lambda export=False: None
        self.assertFalse(self.window.save(True))
        self.assertIsNone(self.controller.path)
        self.assertEqual(self.controller.document.revision, before)

    def test_background_failure_preserves_document_and_restores_actions(self):
        before = self.controller.document
        def fail(doc):
            raise ValueError("deliberate processing failure")
        self.controller.run_background("Failure", fail)
        self.assertFalse(self.window.actions["layer_new"].isEnabled())
        self.assertFalse(self.window.layers.isEnabled())
        deadline = time.monotonic() + 10
        while self.controller.busy and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertEqual(self.errors, ["deliberate processing failure"])
        self.errors.clear()
        self.assertIs(self.controller.document, before)
        self.assertFalse(self.controller.history.undo_stack)
        self.assertTrue(self.window.actions["layer_new"].isEnabled())
        self.assertTrue(self.window.layers.isEnabled())

    def test_multiple_open_images_keep_independent_history_selection_and_viewport(self):
        self.window.actions["layer_new"].trigger()
        self.controller.set_selection(Selection.rectangle(5, 5, 25, 30))
        self.canvas.set_tool("lasso")
        self.canvas.set_zoom(1.37)
        self.canvas.pan = QPointF(-30, 50)
        first = self.controller.active_session
        before = self.controller.document
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "second.png")
            Image.new("RGBA", (80, 60), "red").save(path)
            with patch.object(QMessageBox, "question") as question:
                self.window.open_document(path)
                question.assert_not_called()
            self.assertEqual(self.window.tab_bar.count(), 2)
            self.assertEqual(self.controller.document.active.image.size, (80, 60))
            self.assertEqual(self.controller.history.state_labels, ["Open image"])
            second = self.controller.active_session
            self.assertFalse(second.dirty)
            QTest.mouseClick(self.window.tab_bar, Qt.MouseButton.LeftButton,
                             pos=self.window.tab_bar.tabRect(0).center())
            self.assertIs(self.controller.active_session, first)
            self.assertIs(self.controller.document, before)
            self.assertAlmostEqual(self.canvas.zoom, 1.37)
            self.assertEqual(self.canvas.pan, QPointF(-30, 50))
            self.assertEqual(self.canvas.tool_id, "lasso")
            self.assertEqual(self.controller.history.state_labels,
                             ["New image", "New layer", "Rectangle selection"])
            self.controller.undo()
            self.assertIsNone(self.controller.document.selection)
            self.assertEqual(len(self.controller.document.layers), 2)
            self.controller.undo()
            self.assertEqual(len(self.controller.document.layers), 1)
            self.controller.switch_document(1)
            self.assertIs(self.controller.active_session, second)
            self.assertEqual(self.controller.document.active.image.getpixel((0, 0)), (255, 0, 0, 255))
            self.assertFalse(self.controller.history.undo_stack)

    def test_new_image_dialog_adds_a_tab_without_replacing_the_current_image(self):
        original = self.controller.document
        def accept_new():
            dialog = app.activeModalWidget()
            dialog.width_input.setValue(33)
            dialog.height_input.setValue(22)
            dialog.accept()
        QTimer.singleShot(5, accept_new)
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "preferences.ini"), QSettings.Format.IniFormat)
            with patch("rasterly.ui.dialogs.QSettings", return_value=settings):
                self.window.actions["new"].trigger()
        self.assertEqual(self.window.tab_bar.count(), 2)
        self.assertIs(self.controller.sessions[0].document, original)
        self.assertEqual((self.controller.document.width, self.controller.document.height), (33, 22))

    def test_history_button_opens_overlay_without_resizing_canvas_and_restores_states(self):
        initial = self.controller.document
        self.window.actions["layer_new"].trigger()
        first_edit = self.controller.document
        self.window.actions["layer_duplicate"].trigger()
        final = self.controller.document
        self.controller.saved_revision = final.revision
        canvas_geometry = self.canvas.geometry()
        origin = QPointF(self.canvas.origin)
        QTest.mouseClick(self.window.history_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        overlay = self.window.history_overlay
        self.assertTrue(overlay.isVisible())
        self.assertIs(overlay.parent(), self.window.centralWidget())
        self.assertEqual(self.canvas.geometry(), canvas_geometry)
        self.assertEqual(self.canvas.origin, origin)
        self.assertEqual(self.window.history_button.width(), self.window.history_button.height())
        self.assertEqual(self.window.history_button.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.assertEqual(overlay.list.count(), 3)
        QTest.mouseClick(overlay.list.viewport(), Qt.MouseButton.LeftButton,
                         pos=overlay.list.visualItemRect(overlay.list.item(1)).center())
        self.assertEqual(self.controller.document.revision, first_edit.revision)
        self.assertTrue(self.controller.dirty)
        self.assertEqual(overlay.list.currentRow(), 1)
        self.assertEqual(overlay.list.count(), 3)
        QTest.mouseClick(overlay.list.viewport(), Qt.MouseButton.LeftButton,
                         pos=overlay.list.visualItemRect(overlay.list.item(0)).center())
        self.assertEqual(self.controller.document.revision, initial.revision)
        QTest.mouseClick(overlay.list.viewport(), Qt.MouseButton.LeftButton,
                         pos=overlay.list.visualItemRect(overlay.list.item(2)).center())
        self.assertEqual(self.controller.document.revision, final.revision)
        self.assertFalse(self.controller.dirty)
        QTest.mouseClick(overlay.close_button, Qt.MouseButton.LeftButton)
        self.assertFalse(overlay.isVisible())
        self.assertFalse(self.window.actions["history"].isChecked())

    def test_history_panel_changes_with_active_tab_and_new_edit_replaces_future(self):
        self.window.actions["layer_new"].trigger()
        self.window.actions["layer_duplicate"].trigger()
        self.controller.add_document(Document.new(60, 40))
        self.assertEqual(self.window.history_overlay.list.count(), 1)
        self.controller.switch_document(0)
        self.assertEqual(self.window.history_overlay.list.count(), 3)
        self.window.jump_history(0)
        self.window.apply("Canvas Size", lambda doc: operations.resize_canvas(doc, 250, 130))
        self.assertEqual(self.controller.history.state_labels, ["New image", "Canvas Size"])
        self.assertEqual(self.window.history_overlay.list.count(), 2)
        self.assertFalse(self.controller.history.redo_stack)

    def test_history_overlay_tracks_sidebar_on_resize_and_closes_with_icon_or_escape(self):
        button = self.window.history_button
        overlay = self.window.history_overlay
        self.window.actions["history"].trigger()
        self.assertTrue(overlay.isVisible())
        self.assertTrue(button.isChecked())
        for width, height in ((2560, 1440), (880, 570)):
            self.window.resize(width, height)
            app.processEvents()
            central = self.window.centralWidget()
            anchor = button.mapTo(central, QPoint(0, 0))
            self.assertTrue(central.rect().contains(overlay.geometry()))
            self.assertLess(overlay.geometry().right(), anchor.x())
            self.assertLessEqual(anchor.x() - overlay.geometry().right(), 12)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertFalse(overlay.isVisible())
        self.assertFalse(self.window.actions["history"].isChecked())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        QTest.keyClick(overlay.list, Qt.Key.Key_Escape)
        self.assertFalse(overlay.isVisible())
        self.assertFalse(button.isChecked())

    def test_ctrl_c_ctrl_v_creates_new_layer_in_same_tab_with_full_resolution_lasso_alpha(self):
        original = self.controller.document
        self.controller.set_selection(Selection("lasso", ((10, 10), (40, 10), (10, 40))))
        self.canvas.set_zoom(0.25)
        self.canvas.setFocus()
        QTest.keyClick(self.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.controller.document.revision, original.revision)
        self.assertTrue(self.window.actions["paste"].isEnabled())
        QTest.keyClick(self.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        pasted = self.controller.document
        self.assertEqual(len(pasted.layers), 2)
        self.assertEqual(pasted.active.image.size, (30, 30))
        self.assertEqual((pasted.active.x, pasted.active.y), (10, 10))
        self.assertEqual(pasted.active.image.getpixel((3, 3)), (255, 255, 255, 255))
        self.assertEqual(pasted.active.image.getpixel((28, 28))[3], 0)
        self.assertIs(pasted.layers[0].image, original.layers[0].image)
        self.assertIsNone(pasted.selection)
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Paste selection")
        self.window.undo()
        self.assertEqual(len(self.controller.document.layers), 1)
        self.window.redo()
        self.assertEqual(len(self.controller.document.layers), 2)

    def test_selection_pastes_between_tabs_and_each_paste_is_a_new_layer(self):
        self.controller.set_selection(Selection.rectangle(20, 20, 60, 50))
        self.window.copy_selection()
        source = self.controller.active_session
        self.controller.add_document(Document.new(100, 80))
        self.window.paste_selection()
        self.assertEqual((self.controller.document.active.x, self.controller.document.active.y), (30, 25))
        self.assertEqual(self.controller.document.active.image.size, (40, 30))
        self.window.paste_selection()
        self.assertEqual(len(self.controller.document.layers), 3)
        self.assertNotEqual(self.controller.document.layers[1].id, self.controller.document.layers[2].id)
        self.controller.switch_document(0)
        self.assertIs(self.controller.active_session, source)
        self.assertEqual(len(self.controller.document.layers), 1)
        self.assertEqual(self.controller.document.selection.bounds, (20, 20, 60, 50))
        self.assertEqual(self.controller.history.state_labels, ["New image", "Rectangle selection"])
        self.controller.undo()
        self.assertIsNone(self.controller.document.selection)
        self.assertEqual(len(self.controller.document.layers), 1)

    def test_clipboard_selection_survives_closing_source_tab(self):
        self.controller.set_selection(Selection.rectangle(20, 20, 60, 50))
        self.window.copy_selection()
        self.controller.add_document(Document.new(100, 80))
        self.controller.sessions[0].saved_revision = self.controller.sessions[0].document.revision
        self.assertTrue(self.window.close_tab(0))
        self.window.paste_selection()
        self.assertEqual(len(self.controller.document.layers), 2)
        self.assertEqual(self.controller.document.active.image.size, (40, 30))

    def test_external_clipboard_image_pastes_and_clearing_clipboard_disables_paste(self):
        self.controller.set_selection(Selection.rectangle(20, 20, 60, 50))
        self.window.copy_selection()
        external = QImage(13, 7, QImage.Format.Format_RGBA8888)
        external.fill(Qt.GlobalColor.red)
        QApplication.clipboard().setImage(external)
        self.window.paste_selection()
        self.assertEqual(self.controller.document.active.image.size, (13, 7))
        self.assertEqual(self.controller.document.active.image.getpixel((0, 0)), (255, 0, 0, 255))
        QApplication.clipboard().clear()
        self.assertFalse(self.window.actions["paste"].isEnabled())

    def test_close_tab_x_on_clean_tab_leaves_other_document_active(self):
        self.controller.saved_revision = self.controller.document.revision
        original = self.controller.active_session
        self.controller.add_document(Document.new(50, 40))
        self.controller.saved_revision = self.controller.document.revision
        close = self.window.tab_bar.tabButton(0, QTabBar.ButtonPosition.RightSide)
        if close is None:
            close = self.window.tab_bar.tabButton(0, QTabBar.ButtonPosition.LeftSide)
        self.assertIsNotNone(close)
        active = self.controller.active_session
        with patch.object(QMessageBox, "question") as question:
            QTest.mouseClick(close, Qt.MouseButton.LeftButton)
            question.assert_not_called()
        self.assertEqual(len(self.controller.sessions), 1)
        self.assertIs(self.controller.active_session, active)
        self.assertNotIn(original, self.controller.sessions)

    def test_closing_dirty_background_tab_can_cancel_without_changing_other_tab(self):
        original = self.controller.active_session
        self.window.actions["layer_new"].trigger()
        self.controller.add_document(Document.new(50, 40))
        active = self.controller.active_session
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            self.assertFalse(self.window.close_tab(0))
        self.assertIn(original.title, question.call_args.args[2])
        self.assertEqual(len(self.controller.sessions), 2)
        self.assertIs(self.controller.active_session, active)
        self.assertTrue(original.dirty)

    def test_closing_dirty_background_tab_saves_the_correct_image_before_removing_it(self):
        self.window.actions["layer_new"].trigger()
        target = self.controller.active_session
        self.controller.add_document(Document.new(50, 40))
        active = self.controller.active_session
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "saved-before-close.rasterly")
            self.window.choose_output = lambda export=False: path
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
                self.assertTrue(self.window.close_tab(0))
            saved = files.open_document(path)
            self.assertEqual((saved.width, saved.height), (200, 120))
            self.assertEqual(len(saved.layers), 2)
            self.assertNotIn(target, self.controller.sessions)
            self.assertIs(self.controller.active_session, active)
            self.assertIsNone(active.path)

    def test_cancelled_save_dialog_or_failed_save_keeps_the_tab_open(self):
        self.window.choose_output = lambda export=False: None
        target = self.controller.active_session
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertFalse(self.window.close_tab(0))
        self.assertIs(self.controller.active_session, target)
        self.assertEqual(len(self.controller.sessions), 1)
        self.window.choose_output = lambda export=False: "/tmp/rasterly-failed-save.rasterly"
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save), \
             patch.object(files, "save_project", side_effect=OSError("simulated write failure")), \
             patch.object(self.window, "show_error") as error:
            self.assertFalse(self.window.close_tab(0))
        error.assert_called_once_with("simulated write failure")
        self.assertIs(self.controller.active_session, target)
        self.assertEqual(len(self.controller.sessions), 1)
        self.assertTrue(target.dirty)

    def test_closing_last_tab_leaves_empty_workspace_and_open_can_add_a_document(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.window.close_tab(0))
        app.processEvents()
        self.assertIsNone(self.controller.document)
        self.assertEqual(self.window.tab_bar.count(), 0)
        self.assertEqual(self.window.layers.list.count(), 0)
        self.assertFalse(self.window.actions["paste"].isEnabled())
        self.assertFalse(self.window.actions["save"].isEnabled())
        self.assertTrue(self.window.actions["open"].isEnabled())
        self.assertTrue(self.window.actions["new"].isEnabled())
        self.window.grab()  # Painting an empty workspace must be safe.
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "reopened.png")
            Image.new("RGB", (17, 11), "blue").save(path)
            self.window.open_document(path)
            self.assertEqual(self.window.tab_bar.count(), 1)
            self.assertEqual((self.controller.document.width, self.controller.document.height), (17, 11))

    def test_application_close_checks_all_dirty_tabs_and_cancel_keeps_all_tabs(self):
        original = self.controller.active_session
        self.controller.add_document(Document.new(50, 40))
        self.controller.add_document(Document.new(70, 60))
        active = self.controller.active_session
        responses = [QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Cancel]
        with patch.object(QMessageBox, "question", side_effect=responses) as question:
            self.assertFalse(self.window.close())
        self.assertEqual(question.call_count, 2)
        self.assertIn(original.title, question.call_args_list[0].args[2])
        self.assertIs(self.controller.active_session, active)
        self.assertEqual(len(self.controller.sessions), 3)

    def test_switching_tabs_cancels_uncommitted_transform_without_modifying_pixels(self):
        source = self.controller.active_session
        self.canvas.begin_transform()
        self.canvas.session.box.setWidth(30)
        self.controller.add_document(Document.new(60, 40))
        self.assertIsNone(self.canvas.session)
        self.assertEqual(source.document.active.image.size, (200, 120))
        self.assertFalse(source.history.undo_stack)

    def test_tabs_cannot_switch_or_close_while_background_edit_is_running(self):
        self.controller.add_document(Document.new(60, 40))
        active = self.controller.active_session
        self.controller.run_background("Canvas Size", lambda doc: operations.resize_canvas(doc, 80, 50))
        self.assertFalse(self.controller.switch_document(0))
        self.assertFalse(self.window.close_tab(1))
        self.assertFalse(self.window.tab_bar.isEnabled())
        self.wait_worker()
        self.assertIs(self.controller.active_session, active)
        self.assertEqual((active.document.width, active.document.height), (80, 50))
        self.assertEqual(self.controller.sessions[0].document.width, 200)

    def choose_transform_menu(self, label):
        seen = []
        def choose(menu, point):
            seen.extend(action.text() for action in menu.actions())
            return next(action for action in menu.actions() if action.text() == label)
        point = self.canvas.rect().center()
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, self.canvas.mapToGlobal(point))
        with patch.object(QMenu, "exec", choose):
            self.canvas.contextMenuEvent(event)
        return seen

    def test_transform_context_rotations_keep_center_and_do_not_rewrite_pixels(self):
        before = self.controller.document
        self.canvas.begin_transform()
        session = self.canvas.session
        center = session.box.center()
        labels = self.choose_transform_menu("Rotate 90° Clockwise")
        self.assertIn("Flip Horizontally", labels)
        self.assertIn("Flip Vertically", labels)
        self.assertIn("Rotate 90° Counterclockwise", labels)
        self.assertEqual(session.box.center(), center)
        self.assertEqual((session.box.width(), session.box.height()), (120, 200))
        self.assertEqual((self.window.transform_width.value(), self.window.transform_height.value()), (120, 200))
        self.assertIs(self.controller.document.active.image, before.active.image)
        self.choose_transform_menu("Rotate 90° Counterclockwise")
        self.assertEqual(session.quarter_turns, 0)
        self.assertEqual((session.box.width(), session.box.height()), (200, 120))
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertEqual(self.controller.document.revision, before.revision)

    def test_rotated_transform_keeps_shift_ratio_and_commits_with_undo(self):
        self.canvas.begin_transform()
        self.choose_transform_menu("Rotate 90° Counterclockwise")
        session = self.canvas.session
        session.start(session.box.bottomRight(), "se")
        session.update(session.box.bottomRight() + QPointF(20, 10), True)
        self.assertAlmostEqual(session.box.width() / session.box.height(), 120 / 200)
        expected = (round(session.box.width()), round(session.box.height()))
        self.canvas.commit_transform()
        self.wait_worker()
        self.assertEqual(self.controller.document.active.image.size, expected)
        self.window.undo()
        self.assertEqual(self.controller.document.active.image.size, (200, 120))
        self.window.redo()
        self.assertEqual(self.controller.document.active.image.size, expected)

    def test_rotate_and_flip_order_matches_preview_and_final_pixels(self):
        image = Image.new("RGBA", (4, 2))
        image.putdata([(i * 30, 20, 100, 255) for i in range(8)])
        self.controller.replace_document(Document.from_image(image))
        self.canvas.begin_transform()
        self.choose_transform_menu("Flip Horizontally")
        self.choose_transform_menu("Rotate 90° Clockwise")
        session = self.canvas.session
        self.assertFalse(session.flip_x)
        self.assertTrue(session.flip_y)
        expected = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT).transpose(Image.Transpose.ROTATE_270)
        preview = QImage(2, 4, QImage.Format.Format_RGBA8888)
        preview.fill(Qt.GlobalColor.transparent)
        painter = QPainter(preview)
        self.canvas.draw_target(painter, session.target, QRectF(0, 0, 2, 4),
                                session.flip_x, session.flip_y, session.quarter_turns)
        painter.end()
        for y in range(4):
            for x in range(2):
                self.assertEqual(preview.pixelColor(x, y).getRgb(), expected.getpixel((x, y)))
        self.canvas.commit_transform()
        self.wait_worker()
        self.assertEqual(self.controller.document.active.image.tobytes(), expected.tobytes())

    def test_four_transform_turns_restore_original_orientation_and_dimensions(self):
        self.canvas.begin_transform()
        original = QRectF(self.canvas.session.box)
        for _ in range(4):
            self.choose_transform_menu("Rotate 90° Clockwise")
        self.assertEqual(self.canvas.session.box, original)
        self.assertEqual(self.canvas.session.quarter_turns, 0)

    def test_ctrl_click_selects_and_deselects_multiple_layers_without_dirtying_the_document(self):
        self.window.actions["layer_new"].trigger()
        self.window.actions["layer_new"].trigger()
        self.controller.saved_revision = self.controller.document.revision
        panel = self.window.layers
        def click(row, modifiers=Qt.KeyboardModifier.NoModifier):
            QTest.mouseClick(panel.list.viewport(), Qt.MouseButton.LeftButton, modifiers,
                             pos=panel.list.visualItemRect(panel.list.item(row)).center())
        click(0)
        first_id = panel.list.item(0).data(Qt.ItemDataRole.UserRole)
        second_id = panel.list.item(1).data(Qt.ItemDataRole.UserRole)
        click(1, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.controller.document.selected_ids, frozenset({first_id, second_id}))
        self.assertEqual(self.controller.document.active_id, second_id)
        self.assertEqual(len(panel.list.selectedItems()), 2)
        self.assertTrue(self.window.actions["layer_merge"].isEnabled())
        self.assertFalse(self.controller.dirty)
        click(0, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.controller.document.selected_ids, frozenset({second_id}))
        self.assertFalse(self.window.actions["layer_merge"].isEnabled())
        click(2)
        self.assertEqual(len(self.controller.document.selected_ids), 1)
        self.assertEqual(self.controller.document.active.name, "Background")

    def test_right_click_preserves_selected_layers_and_merge_is_a_single_undoable_action(self):
        self.window.actions["layer_new"].trigger()
        self.window.actions["layer_new"].trigger()
        panel = self.window.layers
        for row in (0, 1):
            QTest.mouseClick(panel.list.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ControlModifier if row else Qt.KeyboardModifier.NoModifier,
                             pos=panel.list.visualItemRect(panel.list.item(row)).center())
        selected = self.controller.document.selected_ids
        point = panel.list.visualItemRect(panel.list.item(0)).center()
        QTest.mousePress(panel.list.viewport(), Qt.MouseButton.RightButton, pos=point)
        self.assertEqual(self.controller.document.selected_ids, selected)
        QTest.mouseRelease(panel.list.viewport(), Qt.MouseButton.RightButton, pos=point)
        before = self.controller.document
        def choose(menu, global_point):
            self.assertEqual(self.controller.document.selected_ids, selected)
            return next(action for action in menu.actions() if action.text() == "Merge Layers")
        with patch.object(QMenu, "exec", choose):
            panel.context_menu(point)
        self.assertEqual(len(self.controller.document.layers), 2)
        self.assertEqual(len(self.controller.document.selected_ids), 1)
        self.assertEqual(self.controller.history.undo_stack[-1].label, "Merge layers")
        self.assertFalse(self.window.actions["layer_merge"].isEnabled())
        self.window.undo()
        self.assertEqual(len(self.controller.document.layers), 3)
        self.assertEqual(self.controller.document.selected_ids, selected)
        self.assertEqual(len(panel.list.selectedItems()), 2)
        self.window.redo()
        self.assertEqual(len(self.controller.document.layers), 2)

    def test_single_layer_context_menu_has_no_merge_and_cancel_does_not_change_document(self):
        panel = self.window.layers
        point = panel.list.visualItemRect(panel.list.item(0)).center()
        before = self.controller.document.revision
        def cancel(menu, global_point):
            self.assertNotIn("Merge Layers", [action.text() for action in menu.actions()])
            return None
        with patch.object(QMenu, "exec", cancel):
            panel.context_menu(point)
        self.assertEqual(self.controller.document.revision, before)
        self.assertFalse(self.controller.history.undo_stack)

    def test_multi_layer_selection_survives_tab_switches_and_new_layer_selects_only_itself(self):
        self.window.actions["layer_new"].trigger()
        selected = frozenset(layer.id for layer in self.controller.document.layers)
        self.controller.select_layers(selected)
        self.controller.add_document(Document.new(50, 30))
        self.assertEqual(len(self.controller.document.selected_ids), 1)
        self.controller.switch_document(0)
        self.assertEqual(self.controller.document.selected_ids, selected)
        self.assertEqual(len(self.window.layers.list.selectedItems()), 2)
        self.window.actions["layer_new"].trigger()
        self.assertEqual(self.controller.document.selected_ids, frozenset({self.controller.document.active_id}))
        self.assertEqual(len(self.window.layers.list.selectedItems()), 1)


if __name__ == "__main__":
    unittest.main()
