import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from PIL import Image
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QStyleOptionViewItem, QStyle
from rasterly import groups, operations, files
from rasterly.model import Document, Layer, LayerGroup, TextData, composite
from rasterly.history import History
from rasterly.painting import PaintStroke
from rasterly.ui.window import EditorWindow
from rasterly.ui.layers import GROUP_ROLE, PARENT_ROLE

app = QApplication.instance() or QApplication([])


def document(count=4):
    layers = tuple(Layer(f"Layer {i}", Image.new("RGBA", (20, 10), (i * 40, 20, 30, 100)))
                   for i in range(count))
    return Document(20, 10, layers, layers[-1].id,
                    selected_ids=frozenset(layer.id for layer in layers[-2:]))


class GroupTests(unittest.TestCase):
    def test_group_visibility_preserves_child_flags_and_is_undoable(self):
        doc = groups.group_layers(document())
        doc = doc.with_layer(replace(doc.active, visible=False))
        hidden = groups.set_visible(doc, doc.groups[0].id, False)
        self.assertEqual(hidden.layers, doc.layers)
        self.assertFalse(any(hidden.layer_visible(layer) for layer in hidden.layers if layer.group_id))
        expected = composite(replace(doc, layers=tuple(layer for layer in doc.layers if not layer.group_id)))
        self.assertEqual(composite(hidden).tobytes(), expected.tobytes())
        self.assertIs(groups.set_visible(hidden, hidden.groups[0].id, False), hidden)
        shown = groups.set_visible(hidden, hidden.groups[0].id, True)
        self.assertEqual(composite(shown).tobytes(), composite(doc).tobytes())
        self.assertFalse(shown.active.visible)
        history = History()
        history.push("Group visibility", doc, hidden)
        self.assertIs(history.undo(), doc)
        self.assertIs(history.redo(), hidden)

    def test_hidden_group_duplicate_and_ungroup_remain_hidden(self):
        doc = groups.group_layers(document())
        doc = groups.set_visible(doc, doc.groups[0].id, False)
        copied = groups.duplicate_group(doc, doc.groups[0].id)
        self.assertFalse(copied.groups[-1].visible)
        self.assertEqual(composite(copied).tobytes(), composite(doc).tobytes())
        ungrouped = groups.ungroup(doc, doc.groups[0].id)
        self.assertFalse(ungrouped.groups)
        self.assertEqual(composite(ungrouped).tobytes(), composite(doc).tobytes())

    def test_hidden_group_visibility_survives_save_export_and_old_projects_default_visible(self):
        doc = groups.group_layers(document())
        doc = groups.set_visible(doc, doc.groups[0].id, False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hidden.rasterly"
            files.save_project(doc, path)
            loaded = files.open_document(path)
            self.assertFalse(loaded.groups[0].visible)
            self.assertEqual([layer.visible for layer in loaded.layers], [layer.visible for layer in doc.layers])
            self.assertEqual(composite(loaded).tobytes(), composite(doc).tobytes())
            png = Path(directory) / "hidden.png"
            files.export_image(loaded, png)
            with Image.open(png) as exported:
                self.assertEqual(exported.tobytes(), composite(doc).tobytes())
            with zipfile.ZipFile(path) as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            metadata = json.loads(entries["document.json"])
            del metadata["groups"][0]["visible"]
            entries["document.json"] = json.dumps(metadata).encode()
            with zipfile.ZipFile(path, "w") as archive:
                for name, contents in entries.items():
                    archive.writestr(name, contents)
            self.assertTrue(files.open_document(path).groups[0].visible)

    def test_hidden_group_rejects_brush_and_move_operations(self):
        doc = groups.group_layers(document())
        doc = groups.set_visible(doc, doc.groups[0].id, False)
        self.assertTrue(doc.active.visible)
        with self.assertRaisesRegex(ValueError, "Show"):
            PaintStroke(doc)
        with self.assertRaisesRegex(ValueError, "Show"):
            operations.extract_target(doc)

    def test_merge_preserves_hidden_group_and_excludes_hidden_members_across_folders(self):
        doc = groups.group_layers(document())
        hidden = groups.set_visible(doc, doc.groups[0].id, False)
        merged = operations.merge_layers(hidden)
        self.assertFalse(merged.layer_visible(merged.active))
        self.assertTrue(merged.active.visible)
        self.assertEqual(composite(merged).tobytes(), composite(hidden).tobytes())
        shown = groups.set_visible(merged, merged.groups[0].id, True)
        self.assertEqual(composite(shown).tobytes(), composite(doc).tobytes())
        mixed = hidden.with_layer(replace(hidden.layers[1], visible=False)).edited(
            selected_ids=frozenset({hidden.layers[0].id, hidden.active_id}))
        before = composite(mixed)
        merged = operations.merge_layers(mixed)
        self.assertIsNone(merged.active.group_id)
        self.assertEqual(composite(merged).tobytes(), before.tobytes())

    def test_group_keeps_pixels_order_selection_and_can_be_undone(self):
        before = document()
        after = groups.group_layers(before)
        self.assertEqual([l.id for l in after.layers], [l.id for l in before.layers])
        self.assertEqual(after.selected_ids, before.selected_ids)
        self.assertEqual(after.active_id, before.active_id)
        self.assertEqual([l.group_id for l in after.layers], [None, None] + [after.groups[0].id] * 2)
        self.assertEqual(composite(after).tobytes(), composite(before).tobytes())
        for original, grouped in zip(before.layers, after.layers):
            self.assertIs(grouped.image, original.image)
        history = History()
        history.push("Group layers", before, after)
        self.assertIs(history.undo(), before)
        self.assertIs(history.redo(), after)

    def test_nonadjacent_layers_gather_at_highest_selected_position(self):
        doc = document(5)
        ids = [l.id for l in doc.layers]
        doc = replace(doc, active_id=ids[3], selected_ids=frozenset({ids[0], ids[3]}))
        after = groups.group_layers(doc)
        self.assertEqual([l.id for l in after.layers], [ids[1], ids[2], ids[0], ids[3], ids[4]])
        self.assertIs(after.layers[2].image, doc.layers[0].image)

    def test_regrouping_members_does_not_split_existing_folders(self):
        doc = groups.group_layers(document(5))
        old = doc.groups[0].id
        doc = replace(doc, active_id=doc.layers[-2].id,
                      selected_ids=frozenset({doc.layers[0].id, doc.layers[-2].id}))
        after = groups.group_layers(doc)
        self.assertEqual(len(after.groups), 2)
        self.assertEqual(after.layers[-3].group_id, old)
        self.assertEqual(after.layers[-2].group_id, after.groups[-1].id)
        self.assertEqual(after.layers[-1].group_id, after.groups[-1].id)

    def test_group_names_unique_and_rename_is_undoable(self):
        doc = groups.group_layers(document())
        doc = replace(doc, active_id=doc.layers[1].id,
                      selected_ids=frozenset(l.id for l in doc.layers[:2]))
        after = groups.group_layers(doc)
        self.assertEqual([g.name for g in after.groups], ["Group 1", "Group 2"])
        renamed = groups.rename_group(after, after.groups[0].id, "  Artwork  ")
        self.assertEqual(renamed.groups[0].name, "Artwork")
        self.assertIs(groups.rename_group(renamed, renamed.groups[0].id, " "), renamed)
        history = History()
        history.push("Rename group", after, renamed)
        self.assertEqual(history.undo().groups[0].name, "Group 1")

    def test_collapse_preserves_pixels_visibility_and_revision_without_history(self):
        doc = groups.group_layers(document())
        after = groups.set_collapsed(doc, doc.groups[0].id, True)
        self.assertTrue(after.groups[0].collapsed)
        self.assertEqual(after.revision, doc.revision)
        self.assertEqual(after.layers, doc.layers)
        self.assertEqual(composite(after).tobytes(), composite(doc).tobytes())
        history = History()
        history.push("Collapse", doc, after)
        self.assertFalse(history.undo_stack)

    def test_inserted_duplicated_pasted_and_text_layers_inherit_active_folder(self):
        doc = groups.group_layers(document())
        for operation in (operations.add_layer, operations.duplicate_layer,
                          lambda d: operations.paste_layer(d, Image.new("RGBA", (3, 4))),
                          lambda d: operations.set_text_layer(d, TextData("Hi"), Image.new("RGBA", (3, 4)), (0, 0))):
            with self.subTest(operation=operation):
                after = operation(doc)
                self.assertEqual(after.active.group_id, doc.active.group_id)
                self.assertEqual(len(after.groups), 1)

    def test_deleting_last_member_prunes_empty_group_and_ungroup_preserves_layers(self):
        doc = groups.group_layers(document())
        doc = operations.delete_layer(doc)
        doc = operations.delete_layer(doc)
        self.assertFalse(doc.groups)
        doc = groups.group_layers(document())
        after = groups.ungroup(doc, doc.groups[0].id)
        self.assertFalse(after.groups)
        self.assertTrue(all(layer.group_id is None for layer in after.layers))
        self.assertEqual(composite(after).tobytes(), composite(doc).tobytes())

    def test_group_duplicate_delete_and_whole_group_reordering(self):
        doc = groups.group_layers(document())
        id = doc.groups[0].id
        after = groups.duplicate_group(doc, id)
        copied = after.groups[-1]
        self.assertEqual(copied.name, "Group 1 copy")
        self.assertEqual(after.selected_ids, frozenset(l.id for l in after.layers if l.group_id == copied.id))
        self.assertIs(after.layers[-1].image, doc.layers[-1].image)
        deleted = groups.delete_group(after, copied.id)
        self.assertEqual([l.id for l in deleted.layers], [l.id for l in doc.layers])
        moved = groups.shift_entry(doc, id, -1)
        self.assertEqual([l.id for l in moved.layers], [doc.layers[0].id, doc.layers[2].id,
                                                      doc.layers[3].id, doc.layers[1].id])
        self.assertEqual(groups.shift_entry(moved, id, 1).layers, doc.layers)
        sibling = groups.shift_entry(doc, doc.layers[-1].id, -1)
        self.assertEqual(sibling.layers[-2].id, doc.layers[-1].id)
        self.assertIs(groups.shift_entry(doc, doc.layers[-1].id, 1), doc)

    def test_merging_group_members_preserves_folder_and_merging_across_folders_is_valid(self):
        doc = groups.group_layers(document())
        after = operations.merge_layers(doc)
        self.assertEqual(after.active.group_id, doc.groups[0].id)
        self.assertEqual(len(after.groups), 1)
        doc = replace(doc, active_id=doc.layers[0].id,
                      selected_ids=frozenset({doc.layers[0].id, doc.layers[-1].id}))
        after = operations.merge_layers(doc)
        self.assertEqual(after.active.group_id, doc.groups[0].id)

    def test_invalid_membership_rejected_and_group_requires_multiple_layers(self):
        with self.assertRaises(ValueError):
            groups.group_layers(Document.new(10, 10))
        doc = document()
        with self.assertRaises(ValueError):
            replace(doc, layers=(replace(doc.layers[0], group_id="missing"),) + doc.layers[1:])
        group = LayerGroup()
        with self.assertRaises(ValueError):
            replace(doc, groups=(group,), layers=tuple(replace(l, group_id=group.id) if i % 2 == 0 else l
                                                       for i, l in enumerate(doc.layers)))
        with self.assertRaises(ValueError):
            replace(doc, groups=(group, group))
        all_grouped = groups.group_layers(replace(doc, selected_ids=frozenset(l.id for l in doc.layers)))
        with self.assertRaises(ValueError):
            groups.delete_group(all_grouped, all_grouped.groups[0].id)

    def test_project_round_trip_preserves_groups_names_collapsed_members_and_pixels(self):
        doc = groups.group_layers(document())
        doc = groups.rename_group(doc, doc.groups[0].id, "Photos 🎨")
        doc = groups.set_collapsed(doc, doc.groups[0].id, True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grouped.rasterly"
            files.save_project(doc, path)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(json.loads(archive.read("document.json"))["version"], 2)
            opened = files.open_document(path)
            self.assertEqual(opened.groups, doc.groups)
            self.assertEqual([l.group_id for l in opened.layers], [l.group_id for l in doc.layers])
            self.assertEqual(opened.selected_ids, doc.selected_ids)
            self.assertEqual(composite(opened).tobytes(), composite(doc).tobytes())
            flat = groups.ungroup(doc, doc.groups[0].id)
            files.save_project(flat, path)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(json.loads(archive.read("document.json"))["version"], 1)
            self.assertFalse(files.open_document(path).groups)


class GroupInteractionTests(unittest.TestCase):
    def setUp(self):
        self.window = EditorWindow()
        self.controller = self.window.controller
        self.errors = []
        self.controller.error.disconnect(self.window.show_error)
        self.controller.error.connect(self.errors.append)
        self.window.show()
        self.controller.replace_document(document())
        self.panel = self.window.layers
        app.processEvents()

    def tearDown(self):
        self.assertFalse(self.errors, self.errors)
        for session in self.controller.sessions:
            session.saved_revision = session.document.revision
        self.window.close()
        self.window.deleteLater()
        app.processEvents()

    def header(self):
        return next(self.panel.list.item(i) for i in range(self.panel.list.count())
                    if self.panel.list.item(i).data(GROUP_ROLE))

    def create_group(self):
        self.panel.list.setFocus()
        QTest.keyClick(self.panel.list, Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier)
        app.processEvents()
        self.assertEqual(len(self.controller.document.groups), 1)
        return self.header()

    def test_ctrl_click_then_ctrl_g_creates_selected_folder_and_undo_redo(self):
        self.controller.select_layer(self.controller.document.layers[-1].id)
        for row in (0, 1):
            QTest.mouseClick(self.panel.list.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ControlModifier if row else Qt.KeyboardModifier.NoModifier,
                             pos=self.panel.list.visualItemRect(self.panel.list.item(row)).center())
        self.assertEqual(len(self.controller.document.selected_ids), 2)
        header = self.create_group()
        self.assertTrue(header.isSelected())
        self.assertEqual(self.panel.current_group(), self.controller.document.groups[0].id)
        self.assertEqual(self.panel.list.count(), 5)
        self.controller.undo()
        self.assertEqual(self.panel.list.count(), 4)
        self.assertFalse(self.controller.document.groups)
        self.controller.redo()
        self.assertEqual(self.panel.list.count(), 5)

    def test_arrow_hides_only_child_rows_keeps_canvas_and_selection_then_expands(self):
        header = self.create_group()
        before = self.controller.document
        history_count = len(self.controller.history.undo_stack)
        rect = self.panel.list.visualItemRect(header)
        QTest.mouseClick(self.panel.list.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(10, rect.center().y()))
        after = self.controller.document
        self.assertTrue(after.groups[0].collapsed)
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.selected_ids, before.selected_ids)
        self.assertEqual(composite(after).tobytes(), composite(before).tobytes())
        self.assertEqual(len(self.controller.history.undo_stack), history_count)
        for i in range(self.panel.list.count()):
            item = self.panel.list.item(i)
            self.assertEqual(item.isHidden(), bool(item.data(PARENT_ROLE)))
        QTest.mouseClick(self.panel.list.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(10, rect.center().y()))
        self.assertFalse(self.controller.document.groups[0].collapsed)
        self.assertTrue(all(not self.panel.list.item(i).isHidden() for i in range(self.panel.list.count())))

    def test_double_click_folder_name_edits_inline_and_undo_restores_name(self):
        header = self.create_group()
        rect = self.panel.list.visualItemRect(header)
        point = QPoint(rect.right() - 50, rect.center().y())
        QTest.mouseClick(self.panel.list.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(self.panel.list.viewport(), Qt.MouseButton.LeftButton, pos=point)
        app.processEvents()
        editor = self.panel.list.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.selectAll()
        QTest.keyClicks(editor, "My artwork")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        app.processEvents()
        self.assertEqual(self.controller.document.groups[0].name, "My artwork")
        self.assertEqual(self.header().text(), "My artwork")
        self.controller.undo()
        self.assertEqual(self.header().text(), "Group 1")

    def test_clicking_a_grouped_layer_checkbox_changes_its_visibility(self):
        self.create_group()
        item = self.panel.list.item(1)
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        index = self.panel.list.indexFromItem(item)
        option = QStyleOptionViewItem()
        self.panel.list.initViewItemOption(option)
        option.rect = self.panel.list.visualItemRect(item)
        delegate = self.panel.list.itemDelegate()
        delegate.initStyleOption(option, index)
        option = delegate.indented_option(option, index)
        checkbox = self.panel.list.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, self.panel.list)
        QTest.mouseClick(self.panel.list.viewport(), Qt.MouseButton.LeftButton, pos=checkbox.center())
        layer = next(l for l in self.controller.document.layers if l.id == layer_id)
        self.assertFalse(layer.visible)
        self.assertTrue(all(l.visible for l in self.controller.document.layers if l.id != layer_id))
        self.controller.undo()
        self.assertTrue(all(l.visible for l in self.controller.document.layers))

    def test_group_checkbox_hides_canvas_preserves_children_and_undo_restores(self):
        header = self.create_group()
        before = self.controller.document
        canvas = self.window.canvas
        point = canvas.to_screen(QPointF(10, 5)).toPoint()
        visible_pixel = canvas.grab().toImage().pixelColor(point)
        index = self.panel.list.indexFromItem(header)
        option = QStyleOptionViewItem()
        self.panel.list.initViewItemOption(option)
        option.rect = self.panel.list.visualItemRect(header)
        delegate = self.panel.list.itemDelegate()
        delegate.initStyleOption(option, index)
        adjusted = delegate.indented_option(option, index)
        rect = self.panel.list.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, adjusted, self.panel.list)
        QTest.mouseClick(self.panel.list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        hidden = self.controller.document
        self.assertFalse(hidden.groups[0].visible)
        self.assertEqual(hidden.layers, before.layers)
        self.assertNotEqual(canvas.grab().toImage().pixelColor(point), visible_pixel)
        self.assertEqual(self.header().checkState(), Qt.CheckState.Unchecked)
        self.controller.undo()
        self.assertTrue(self.controller.document.groups[0].visible)
        self.assertEqual(canvas.grab().toImage().pixelColor(point), visible_pixel)
        self.controller.redo()
        self.assertFalse(self.controller.document.groups[0].visible)
        self.panel.toggle_group(hidden.groups[0].id)
        self.assertTrue(self.controller.document.groups[0].collapsed)
        self.panel.select_group(hidden.groups[0].id)
        self.window.actions["layer_visibility"].trigger()
        self.assertTrue(self.controller.document.groups[0].visible)
        self.assertTrue(self.controller.document.groups[0].collapsed)

    def test_collapsed_folder_can_be_selected_from_another_layer(self):
        self.create_group()
        group_id = self.panel.current_group()
        self.panel.toggle_group(group_id)
        self.controller.select_layer(self.controller.document.layers[0].id)
        header = self.header()
        QTest.mouseClick(self.panel.list.viewport(), Qt.MouseButton.LeftButton,
                         pos=self.panel.list.visualItemRect(header).center())
        self.assertEqual(self.panel.current_group(), group_id)
        self.assertEqual(self.controller.document.selected_ids,
                         frozenset(l.id for l in self.controller.document.layers if l.group_id == group_id))
        self.assertTrue(self.header().isSelected())

    def test_empty_inline_name_restores_existing_group_name(self):
        header = self.create_group()
        header.setText("   ")
        self.assertEqual(self.header().text(), "Group 1")
        self.assertEqual(self.controller.document.groups[0].name, "Group 1")

    def test_group_actions_duplicate_move_and_delete_entire_folder(self):
        self.create_group()
        group_id = self.panel.current_group()
        self.window.actions["layer_duplicate"].trigger()
        self.assertEqual(len(self.controller.document.layers), 6)
        self.assertNotEqual(self.panel.current_group(), group_id)
        copied = self.panel.current_group()
        self.window.actions["layer_down"].trigger()
        self.assertEqual([l.group_id for l in self.controller.document.layers][-4:], [copied, copied, group_id, group_id])
        self.window.actions["layer_delete"].trigger()
        self.assertEqual(len(self.controller.document.layers), 4)
        self.assertEqual(len(self.controller.document.groups), 1)

    def test_header_drag_reorders_members_as_one_block(self):
        header = self.create_group()
        group_id = self.panel.current_group()
        self.panel.updating = True
        self.panel.list.takeItem(self.panel.list.row(header))
        self.panel.list.addItem(header)
        self.panel.updating = False
        self.panel.commit_order()
        self.assertEqual([l.group_id for l in self.controller.document.layers], [group_id, group_id, None, None])
        self.assertTrue(self.panel.list.item(2).data(GROUP_ROLE))
        self.assertEqual(self.panel.list.item(3).data(PARENT_ROLE), group_id)

    def test_group_action_disabled_for_single_layer_and_native_name_input(self):
        self.controller.select_layer(self.controller.document.active_id)
        self.assertFalse(self.window.actions["layer_group"].isEnabled())
        self.controller.select_layers({l.id for l in self.controller.document.layers[-2:]})
        self.assertTrue(self.window.actions["layer_group"].isEnabled())
        self.window.colors.hex_input.setFocus()
        app.processEvents()
        self.assertTrue(self.window.actions["layer_group"].shortcut().isEmpty())
        self.panel.list.setFocus()
        app.processEvents()
        self.assertEqual(self.window.actions["layer_group"].shortcut().toString(), "Ctrl+G")

    def test_groups_and_collapsed_rows_restore_across_document_tabs(self):
        self.create_group()
        self.panel.toggle_group(self.panel.current_group())
        self.controller.add_document(Document.new(10, 10))
        self.assertEqual(self.panel.list.count(), 1)
        self.controller.switch_document(0)
        self.assertTrue(self.controller.document.groups[0].collapsed)
        self.assertTrue(self.panel.list.item(1).isHidden())
