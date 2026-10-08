import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from rasterly import files, operations
from rasterly.model import Document, TextData, composite
from rasterly.selection import Selection
from rasterly.text import render_text
from rasterly.ui.style import STYLE
from rasterly.ui.window import EditorWindow

app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(STYLE)


class TextTests(unittest.TestCase):
    def setUp(self):
        self.window = EditorWindow()
        self.window.show()
        self.controller = self.window.controller
        self.controller.add_document(Document.new(640, 400))
        self.canvas = self.window.canvas
        self.canvas.set_zoom(1)
        self.tool = self.canvas.tools["text"]
        self.errors = []
        self.controller.error.disconnect(self.window.show_error)
        self.controller.error.connect(self.errors.append)
        app.processEvents()
        self.canvas.setFocus()

    def tearDown(self):
        self.tool.cancel()
        for session in self.controller.sessions:
            session.saved_revision = session.document.revision
        self.window.close()
        self.window.deleteLater()
        app.processEvents()
        self.assertFalse(self.errors, self.errors)

    def begin(self, x=20, y=30):
        QTest.keyClick(self.canvas, Qt.Key.Key_T)
        self.assertEqual(self.canvas.tool_id, "text")
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton,
                         pos=self.canvas.to_screen(QPointF(x, y)).toPoint())
        self.assertTrue(self.tool.editing)
        return self.tool.editor

    def commit(self):
        QTest.keyClick(self.tool.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(self.tool.editing)
        return self.controller.document.active

    def finish_transform(self):
        QTest.keyClick(self.canvas, Qt.Key.Key_Return)
        deadline = time.monotonic() + 5
        while self.controller.busy and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertFalse(self.controller.busy)
        self.assertFalse(self.errors, self.errors)
        return self.controller.document.active

    def test_ctrl_t_resizes_editable_text_to_box_and_undo_restores_original(self):
        self.begin().setPlainText("Transform me\nSecond line")
        original = self.commit()
        before = self.controller.document
        self.canvas.setFocus()
        QTest.keyClick(self.canvas, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
        self.assertIsNotNone(self.canvas.session)
        self.assertEqual(self.canvas.session.box, QRectF(*original.bounds[:2], *original.image.size))
        box = self.canvas.session.box
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton,
                         pos=self.canvas.to_screen(box.bottomRight()).toPoint())
        QTest.mouseMove(self.canvas, self.canvas.to_screen(box.topLeft() + QPointF(400, 160)).toPoint())
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton,
                           pos=self.canvas.to_screen(box.topLeft() + QPointF(400, 160)).toPoint())
        self.assertEqual(self.canvas.session.pixel_box, (20, 30, 420, 190))
        self.assertIs(self.controller.document, before)
        transformed = self.finish_transform()
        self.assertEqual(transformed.image.size, (400, 160))
        self.assertEqual(transformed.text.box_size, (400, 160))
        self.assertEqual(transformed.text.content, original.text.content)
        self.assertGreater(transformed.text.size, original.text.size)
        self.assertEqual(transformed.id, original.id)
        self.assertEqual(transformed.image.tobytes(), render_text(transformed.text).tobytes())
        self.window.undo()
        self.assertIs(self.controller.document, before)
        self.window.redo()
        self.assertEqual(self.controller.document.active.text, transformed.text)

    def test_transformed_text_remains_fitted_while_editing_and_after_project_reopen(self):
        self.begin().setPlainText("Wide text")
        self.commit()
        self.canvas.begin_transform()
        self.canvas.session.box = QRectF(40, 50, 400, 120)
        self.finish_transform()
        self.window.edit_text_layer()
        self.assertIsNotNone(self.tool.view)
        self.assertIs(self.tool.proxy.widget(), self.tool.editor)
        self.assertEqual(self.tool.proxy.boundingRect().size().toSize(), self.tool.editor.size())
        QTest.keyClicks(self.tool.editor, "New fitted content")
        changed = self.commit()
        self.assertEqual(changed.image.size, (400, 120))
        self.assertEqual(changed.text.content, "New fitted content")
        self.assertEqual((changed.x, changed.y), (40, 50))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transformed.rasterly"
            files.save_project(self.controller.document, path)
            self.controller.replace_document(files.open_document(path), str(path))
        self.assertEqual(self.controller.document.active.text, changed.text)
        self.window.edit_text_layer()
        self.window.text_size.setValue(changed.text.size * 2)
        QTest.keyClick(self.tool.editor, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(self.tool.editing)
        self.assertIsNotNone(self.canvas.session)
        resized = self.controller.document.active
        self.assertEqual(resized.image.size, (800, 240))
        self.canvas.cancel_transform()

    def test_shift_scaling_and_escape_preserve_text_and_exact_original_pixels(self):
        self.begin().setPlainText("Keep the aspect ratio")
        self.commit()
        before = self.controller.document
        self.canvas.begin_transform()
        session = self.canvas.session
        ratio = session.box.width() / session.box.height()
        session.start(session.box.bottomRight(), "se")
        session.update(session.box.bottomRight() + QPointF(120, 50), True)
        self.assertAlmostEqual(session.box.width() / session.box.height(), ratio)
        self.canvas.setFocus()
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertIsNone(self.canvas.session)
        self.assertIs(self.controller.document, before)
        self.assertEqual(len(self.controller.history.undo_stack), 1)

    def test_rotations_and_flips_compose_on_text_and_survive_later_edits(self):
        self.begin().setPlainText("Rotate text")
        self.commit()
        self.canvas.begin_transform()
        self.canvas.session.flip_x = True
        self.canvas.session.rotate(True)
        first = self.finish_transform()
        self.assertEqual(first.text.quarter_turns, 1)
        self.assertTrue(first.text.flip_y)
        self.canvas.begin_transform()
        self.canvas.session.rotate(True)
        second = self.finish_transform()
        self.assertEqual(second.text.quarter_turns, 2)
        self.assertTrue(second.text.flip_x)
        self.assertFalse(second.text.flip_y)
        self.window.edit_text_layer()
        QTest.keyClicks(self.tool.editor, "Still editable")
        edited = self.commit()
        self.assertEqual(edited.text.quarter_turns, 2)
        self.assertTrue(edited.text.flip_x)
        self.assertEqual(edited.image.size, second.image.size)
        self.assertEqual(edited.image.tobytes(), render_text(edited.text).tobytes())

    def test_ctrl_t_applies_active_typing_and_transforms_whole_text_despite_selection(self):
        self.begin().setPlainText("Typing to transform")
        QTest.keyClick(self.tool.editor, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(self.tool.editing)
        self.assertIsNotNone(self.canvas.session)
        original = self.controller.document.active
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertIsNone(self.canvas.session)
        self.assertEqual(self.controller.document.active.text.content, "Typing to transform")
        selection = Selection.rectangle(0, 0, 10, 10)
        self.controller.set_selection(selection)
        self.canvas.begin_transform()
        self.assertFalse(self.canvas.session.target.selected)
        self.canvas.session.box = QRectF(-10, 10, 200, 60)
        transformed = self.finish_transform()
        self.assertEqual(transformed.id, original.id)
        self.assertEqual(transformed.image.size, (200, 60))
        self.assertEqual(self.controller.document.selection, selection)

    def test_inline_typing_creates_separate_layer_with_native_text_shortcuts_and_one_history_step(self):
        before = self.controller.document
        editor = self.begin()
        QTest.keyClicks(editor, "Move V T L J with spaces")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.keyClicks(editor, "Second line")
        self.assertEqual(self.canvas.tool_id, "text")
        self.assertIs(self.controller.document, before)
        self.assertFalse(self.controller.history.undo_stack)
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.textCursor().selectedText(), "Move V T L J with spaces\u2029Second line")
        QTest.keyClick(editor, Qt.Key.Key_End)
        QTest.keyClicks(editor, "!")
        QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(editor.toPlainText().endswith("!"))
        self.assertIs(self.controller.document, before)
        QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertTrue(editor.toPlainText().endswith("!"))
        QTest.keyClick(editor, Qt.Key.Key_Backspace)
        layer = self.commit()
        self.assertEqual(len(self.controller.document.layers), 2)
        self.assertEqual((layer.x, layer.y), (20, 30))
        self.assertEqual(layer.text.content, "Move V T L J with spaces\nSecond line")
        self.assertIs(self.controller.document.layers[0].image, before.active.image)
        self.assertIsNotNone(layer.image.getbbox())
        self.assertEqual(layer.image.getpixel((0, 0))[3], 0)
        self.assertEqual(len(self.controller.history.undo_stack), 1)
        self.assertEqual(self.controller.history.undo_stack[-1].label, "New text layer")
        self.window.undo()
        self.assertIs(self.controller.document, before)
        self.window.redo()
        self.assertEqual(self.controller.document.active.text, layer.text)

    def test_styles_and_multiline_render_at_document_resolution_independent_of_zoom(self):
        self.canvas.set_zoom(0.5)
        editor = self.begin()
        QTest.keyClicks(editor, "First")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.keyClicks(editor, "Second line")
        self.window.text_size.setValue(64)
        self.window.text_bold.setChecked(True)
        self.window.text_italic.setChecked(True)
        self.window.text_alignment.setCurrentText("Center")
        self.window.text_color = QColor("#ff0000")
        self.window.text_style_changed()
        self.canvas.set_zoom(2)
        data = self.tool.current_data()
        expected = render_text(data)
        layer = self.commit()
        self.assertEqual(layer.text.size, 64)
        self.assertTrue(layer.text.bold and layer.text.italic)
        self.assertEqual(layer.text.alignment, "center")
        self.assertEqual(layer.image.tobytes(), expected.tobytes())
        pixels = np.asarray(layer.image)
        colors = pixels[pixels[:, :, 3] > 0]
        self.assertGreater(len(colors), 0)
        self.assertTrue(np.all(colors[:, 0] >= 254))
        self.assertTrue(np.all(colors[:, 1:3] == 0))

    def test_escape_and_empty_apply_leave_document_and_history_untouched(self):
        before = self.controller.document
        editor = self.begin()
        QTest.keyClicks(editor, "Discard me")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.assertIs(self.controller.document, before)
        self.begin()
        self.commit()
        self.assertIs(self.controller.document, before)
        self.assertFalse(self.controller.history.undo_stack)

    def test_apply_and_cancel_are_visible_only_during_text_edits(self):
        self.canvas.set_tool("text")
        self.assertFalse(self.window.text_apply.isVisible())
        self.assertFalse(self.window.text_cancel.isVisible())
        self.begin().setPlainText("Text")
        self.assertTrue(self.window.text_apply.isVisible())
        self.assertTrue(self.window.text_cancel.isVisible())
        QTest.mouseClick(self.window.text_apply, Qt.MouseButton.LeftButton)
        self.assertFalse(self.tool.editing)
        self.assertFalse(self.window.text_apply.isVisible())
        self.assertFalse(self.window.text_cancel.isVisible())
        self.window.edit_text_layer()
        QTest.mouseClick(self.window.text_cancel, Qt.MouseButton.LeftButton)
        self.assertFalse(self.tool.editing)
        self.assertFalse(self.window.text_apply.isVisible())
        self.assertFalse(self.window.text_cancel.isVisible())

    def test_font_size_dropdown_and_custom_entry_apply_to_text(self):
        self.begin().setPlainText("Size options")
        picker = self.window.text_size
        self.assertTrue(picker.isEditable())
        self.assertGreaterEqual(picker.findText("12"), 0)
        self.assertGreaterEqual(picker.findText("24"), 0)
        self.assertGreaterEqual(picker.findText("72"), 0)
        picker.setFocus()
        QTest.keyClick(picker, Qt.Key.Key_Down)
        self.assertEqual(picker.value(), 60)
        self.assertEqual(self.tool.current_data().size, 60)
        picker.lineEdit().selectAll()
        QTest.keyClicks(picker.lineEdit(), "37")
        QTest.keyClick(picker.lineEdit(), Qt.Key.Key_Return)
        self.assertEqual(picker.value(), 37)
        self.assertEqual(self.tool.current_data().size, 37)
        QTest.mouseClick(self.window.text_apply, Qt.MouseButton.LeftButton)
        self.assertEqual(self.controller.document.active.text.size, 37)
        self.assertEqual(picker.findText("37"), -1)

    def test_font_size_focus_loss_commits_custom_size_and_restores_invalid_input(self):
        self.begin().setPlainText("Custom size")
        original = self.commit()
        picker = self.window.text_size
        picker.setFocus()
        picker.lineEdit().selectAll()
        QTest.keyClicks(picker.lineEdit(), "53")
        self.canvas.setFocus()
        self.assertTrue(self.tool.editing)
        self.assertEqual(self.tool.current_data().size, 53)
        self.assertEqual(self.controller.document.active.text.size, original.text.size)
        picker.setFocus()
        picker.lineEdit().selectAll()
        QTest.keyClick(picker.lineEdit(), Qt.Key.Key_Backspace)
        self.canvas.setFocus()
        self.assertEqual(picker.currentText(), "53")
        picker.setFocus()
        picker.lineEdit().selectAll()
        QTest.keyClicks(picker.lineEdit(), "0")
        self.canvas.setFocus()
        self.assertEqual(picker.value(), 53)
        self.assertEqual(picker.currentText(), "53")
        QTest.mouseClick(self.window.text_apply, Qt.MouseButton.LeftButton)
        self.assertEqual(self.controller.document.active.text.size, 53)

    def test_text_controls_stay_compact_on_1440p_monitor(self):
        self.window.resize(2560, 1440)
        self.begin().setPlainText("Compact toolbar")
        app.processEvents()
        widgets = (self.window.text_font, self.window.text_size, self.window.text_bold,
                   self.window.text_italic, self.window.text_color_button,
                   self.window.text_alignment, self.window.text_apply, self.window.text_cancel)
        for previous, following in zip(widgets, widgets[1:]):
            gap = following.x() - (previous.x() + previous.width())
            self.assertLessEqual(gap, 6)
            self.assertGreaterEqual(gap, 0)
        self.assertLessEqual(self.window.text_apply.width(), 70)
        self.assertLessEqual(self.window.text_cancel.width(), 70)
        self.assertLess(widgets[-1].x() + widgets[-1].width(), 650)

    def test_selected_text_style_change_starts_draft_and_apply_updates_same_layer(self):
        self.begin().setPlainText("Selected text")
        original = self.commit()
        before = self.controller.document
        count = len(self.controller.history.undo_stack)
        self.window.text_size.setFocus()
        self.window.text_size.setValue(72)
        self.assertTrue(self.tool.editing)
        self.assertTrue(self.window.text_size.hasFocus())
        self.assertEqual(self.window.text_size.value(), 72)
        self.assertTrue(self.window.text_apply.isVisible())
        self.assertIs(self.controller.document, before)
        self.assertEqual(len(self.controller.history.undo_stack), count)
        self.window.text_bold.setChecked(True)
        self.window.text_italic.setChecked(True)
        self.window.text_alignment.setCurrentText("Right")
        self.window.colors.set_color(QColor("#ff0000"))
        QTest.mouseClick(self.window.text_apply, Qt.MouseButton.LeftButton)
        layer = self.controller.document.active
        self.assertEqual(layer.id, original.id)
        self.assertEqual(layer.text.content, "Selected text")
        self.assertEqual((layer.x, layer.y), (original.x, original.y))
        self.assertEqual(layer.text.size, 72)
        self.assertTrue(layer.text.bold and layer.text.italic)
        self.assertEqual(layer.text.alignment, "right")
        self.assertEqual(layer.text.color, (255, 0, 0, 255))
        self.assertEqual(layer.image.tobytes(), render_text(layer.text).tobytes())
        self.assertEqual(len(self.controller.history.undo_stack), count + 1)
        self.assertFalse(self.window.text_apply.isVisible())
        self.window.undo()
        self.assertIs(self.controller.document, before)
        self.assertEqual(self.window.text_size.value(), original.text.size)
        self.window.redo()
        self.assertEqual(self.window.text_size.value(), 72)

    def test_cancel_selected_text_style_change_restores_controls_and_document(self):
        self.begin().setPlainText("Keep this")
        original = self.commit()
        before = self.controller.document
        count = len(self.controller.history.undo_stack)
        self.window.text_size.setValue(96)
        QTest.mouseClick(self.window.text_cancel, Qt.MouseButton.LeftButton)
        self.assertIs(self.controller.document, before)
        self.assertEqual(len(self.controller.history.undo_stack), count)
        self.assertEqual(self.window.text_size.value(), original.text.size)
        self.assertFalse(self.tool.editing)
        self.assertFalse(self.window.text_apply.isVisible())

    def test_text_controls_follow_selected_layer_and_other_tools_do_not_edit_text(self):
        self.begin().setPlainText("First")
        self.window.text_size.setValue(32)
        first = self.commit()
        self.begin(250, 150).setPlainText("Second")
        self.window.text_size.setValue(64)
        self.window.text_bold.setChecked(True)
        second = self.commit()
        self.controller.select_layer(first.id)
        self.assertEqual(self.window.text_size.value(), 32)
        self.assertFalse(self.window.text_bold.isChecked())
        self.controller.select_layer(second.id)
        self.assertEqual(self.window.text_size.value(), 64)
        self.assertTrue(self.window.text_bold.isChecked())
        before = self.controller.document
        self.canvas.set_tool("brush")
        self.window.colors.set_color(QColor("blue"))
        self.assertFalse(self.tool.editing)
        self.assertIs(self.controller.document, before)
        self.canvas.set_tool("text")
        self.assertEqual(self.window.text_size.value(), 64)
        self.assertEqual(self.window.text_color.getRgb(), second.text.color)

    def test_move_tool_shows_text_controls_only_for_selected_text_layer(self):
        self.begin().setPlainText("Move and style")
        self.window.text_size.setValue(64)
        layer = self.commit()
        self.canvas.set_tool("move")
        self.assertTrue(self.window.text_controls.isVisible())
        self.assertEqual(self.window.text_size.value(), 64)
        self.assertFalse(self.window.text_apply.isVisible())
        self.assertFalse(self.window.quick_controls.isVisible())
        self.controller.select_layer(self.controller.document.layers[0].id)
        self.assertFalse(self.window.text_controls.isVisible())
        self.assertTrue(self.window.quick_controls.isVisible())
        self.controller.select_layer(layer.id)
        self.assertTrue(self.window.text_controls.isVisible())
        self.assertEqual(self.window.text_size.value(), 64)

    def test_move_tool_text_styles_apply_cancel_and_keep_move_tool_active(self):
        self.begin().setPlainText("Style with Move")
        original = self.commit()
        self.canvas.set_tool("move")
        before = self.controller.document
        self.window.text_size.setValue(80)
        self.assertEqual(self.canvas.tool_id, "move")
        self.assertTrue(self.tool.editing)
        self.assertTrue(self.window.text_apply.isVisible())
        self.assertIs(self.controller.document, before)
        QTest.mouseClick(self.window.text_cancel, Qt.MouseButton.LeftButton)
        self.assertIs(self.controller.document, before)
        self.assertEqual(self.window.text_size.value(), original.text.size)
        self.window.text_size.setValue(72)
        QTest.mouseClick(self.window.text_apply, Qt.MouseButton.LeftButton)
        self.assertEqual(self.canvas.tool_id, "move")
        self.assertFalse(self.tool.editing)
        self.assertTrue(self.window.text_controls.isVisible())
        self.assertFalse(self.window.text_apply.isVisible())
        self.assertEqual(self.controller.document.active.id, original.id)
        self.assertEqual(self.controller.document.active.text.size, 72)
        self.window.undo()
        self.assertEqual(self.window.text_size.value(), original.text.size)

    def test_move_drag_after_text_style_draft_commits_then_moves_text(self):
        self.begin().setPlainText("Move this")
        original = self.commit()
        self.canvas.set_tool("move")
        count = len(self.controller.history.undo_stack)
        self.window.text_size.setValue(60)
        start = self.canvas.to_screen(QPointF(400, 300)).toPoint()
        end = self.canvas.to_screen(QPointF(410, 315)).toPoint()
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.canvas, end)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=end)
        layer = self.controller.document.active
        self.assertFalse(self.tool.editing)
        self.assertEqual(self.canvas.tool_id, "move")
        self.assertEqual(layer.text.size, 60)
        self.assertEqual(layer.text.content, original.text.content)
        self.assertEqual((layer.x, layer.y), (original.x + 10, original.y + 15))
        self.assertEqual(len(self.controller.history.undo_stack), count + 2)

    def test_move_text_draft_is_discarded_on_tab_switch_and_transform_controls_take_priority(self):
        self.begin().setPlainText("Original")
        original = self.commit()
        self.canvas.set_tool("move")
        self.window.text_size.setValue(96)
        source = self.controller.active_session
        self.controller.add_document(Document.new(100, 100))
        self.assertFalse(self.tool.editing)
        self.assertEqual(source.document.active.text, original.text)
        self.assertFalse(self.window.text_controls.isVisible())
        self.controller.switch_document(0)
        self.assertEqual(self.canvas.tool_id, "move")
        self.assertTrue(self.window.text_controls.isVisible())
        self.canvas.begin_transform()
        self.assertTrue(self.window.transform_controls.isVisible())
        self.assertFalse(self.window.text_controls.isVisible())
        self.canvas.cancel_transform()
        self.assertTrue(self.window.text_controls.isVisible())
        self.assertFalse(self.window.transform_controls.isVisible())

    def test_selected_transformed_text_style_edit_preserves_transform(self):
        self.begin().setPlainText("Transformed")
        self.commit()
        self.canvas.begin_transform()
        self.canvas.session.box = QRectF(20, 30, 300, 100)
        self.canvas.session.rotate(True)
        self.canvas.session.flip_x = True
        original = self.finish_transform()
        self.canvas.set_tool("text")
        self.window.text_size.setValue(original.text.size * 2)
        QTest.mouseClick(self.window.text_apply, Qt.MouseButton.LeftButton)
        layer = self.controller.document.active
        self.assertEqual(layer.id, original.id)
        self.assertEqual(layer.text.content, original.text.content)
        self.assertEqual(layer.text.quarter_turns, original.text.quarter_turns)
        self.assertEqual(layer.text.flip_x, original.text.flip_x)
        self.assertEqual(layer.text.flip_y, original.text.flip_y)
        self.assertEqual(layer.text.box_size, tuple(side * 2 for side in original.text.box_size))
        self.assertEqual(layer.image.tobytes(), render_text(layer.text).tobytes())

    def test_existing_text_edits_in_place_cancel_restores_pixels_and_move_preserves_editability(self):
        QTest.keyClicks(self.begin(), "Original")
        layer = self.commit()
        self.window.apply("Move layer", lambda doc: operations.move(doc, 50, 40))
        moved = self.controller.document.active
        self.assertEqual(moved.text, layer.text)
        self.window.edit_text_layer()
        QTest.keyClicks(self.tool.editor, "Canceled")
        QTest.keyClick(self.tool.editor, Qt.Key.Key_Escape)
        self.assertIs(self.controller.document.active.image, moved.image)
        self.window.edit_text_layer()
        QTest.keyClicks(self.tool.editor, "Changed")
        edited = self.commit()
        self.assertEqual(len(self.controller.document.layers), 2)
        self.assertEqual(edited.id, layer.id)
        self.assertEqual((edited.x, edited.y), (70, 70))
        self.assertEqual(edited.text.content, "Changed")
        self.window.undo()
        self.assertEqual(self.controller.document.active.text.content, "Original")
        self.window.redo()
        self.assertEqual(self.controller.document.active.text.content, "Changed")

    def test_project_round_trip_preserves_editable_text_and_export_composite(self):
        editor = self.begin()
        editor.setPlainText("Æøå · Unicode\nEditable text")
        original = self.commit()
        self.window.actions["layer_duplicate"].trigger()
        duplicate = self.controller.document.active
        self.assertEqual(duplicate.text, original.text)
        self.assertNotEqual(duplicate.id, original.id)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "text.rasterly"
            files.save_project(self.controller.document, path)
            loaded = files.open_document(path)
            self.assertEqual(loaded.active.text, duplicate.text)
            self.assertEqual(loaded.active.image.tobytes(), duplicate.image.tobytes())
            self.assertEqual(composite(loaded).tobytes(), composite(self.controller.document).tobytes())
            self.controller.replace_document(loaded, str(path))
            self.window.edit_text_layer()
            QTest.keyClicks(self.tool.editor, "Reopened")
            self.assertEqual(self.commit().text.content, "Reopened")

    def test_switching_tool_applies_text_and_switching_tabs_cancels_draft(self):
        QTest.keyClicks(self.begin(), "Keep this")
        self.window.actions["tool_move"].trigger()
        self.assertFalse(self.tool.editing)
        self.assertEqual(self.controller.document.active.text.content, "Keep this")
        self.assertEqual(self.canvas.tool_id, "move")
        self.begin(200, 100).setPlainText("Discard this")
        source = self.controller.active_session
        self.controller.add_document(Document.new(100, 100))
        self.assertFalse(self.tool.editing)
        self.assertEqual(len(source.document.layers), 2)
        self.assertEqual(source.document.active.text.content, "Keep this")

    def test_clicking_existing_text_edits_it_and_blank_edit_erases_its_pixels(self):
        QTest.keyClicks(self.begin(), "Original")
        layer = self.commit()
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton,
                         pos=self.canvas.to_screen(QPointF(25, 35)).toPoint())
        self.assertEqual(self.tool.layer_id, layer.id)
        self.tool.editor.setPlainText("")
        cleared = self.commit()
        self.assertEqual(cleared.text.content, "")
        self.assertIsNone(cleared.image.getbbox())
        self.window.undo()
        self.assertEqual(self.controller.document.active.text.content, "Original")

    def test_rasterization_is_undoable_and_pixel_operations_cannot_leave_stale_text(self):
        QTest.keyClicks(self.begin(), "Editable")
        layer = self.commit()
        with self.assertRaisesRegex(ValueError, "Rasterize"):
            operations.resize_image(self.controller.document, 320, 200)
        selected = replace(self.controller.document, selection=Selection.rectangle(20, 30, 200, 100))
        with self.assertRaisesRegex(ValueError, "Rasterize"):
            operations.solid_fill(selected, (255, 0, 0, 255))
        self.window.actions["layer_rasterize_text"].trigger()
        self.assertIsNone(self.controller.document.active.text)
        self.assertIs(self.controller.document.active.image, layer.image)
        self.window.undo()
        self.assertEqual(self.controller.document.active.text, layer.text)
        cropped = operations.crop(selected)
        self.assertEqual(cropped.active.text, layer.text)
        self.assertIs(cropped.active.image, layer.image)


if __name__ == "__main__":
    unittest.main()
