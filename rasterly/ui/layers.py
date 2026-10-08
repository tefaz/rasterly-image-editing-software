from dataclasses import replace
from PyQt6.QtCore import Qt, QTimer, QSize, QItemSelectionModel, pyqtSignal, QPoint
from PyQt6.QtGui import QColor, QPolygon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                            QListWidgetItem, QAbstractItemView, QToolButton, QMenu,
                            QInputDialog, QStyledItemDelegate, QStyleOptionViewItem)
from .icons import icon
from .images import layer_thumbnail
from .. import operations, groups

GROUP_ROLE = Qt.ItemDataRole.UserRole + 1
PARENT_ROLE = Qt.ItemDataRole.UserRole + 2
COLLAPSED_ROLE = Qt.ItemDataRole.UserRole + 3


class LayerDelegate(QStyledItemDelegate):
    @staticmethod
    def indented_option(option, index):
        adjusted = QStyleOptionViewItem(option)
        if index.data(GROUP_ROLE) or index.data(PARENT_ROLE):
            adjusted.rect.adjust(20, 0, 0, 0)
        return adjusted

    def paint(self, painter, option, index):
        adjusted = self.indented_option(option, index)
        super().paint(painter, adjusted, index)
        if index.data(GROUP_ROLE):
            x, y = option.rect.left() + 10, option.rect.center().y()
            points = ([QPoint(x - 3, y - 5), QPoint(x + 3, y), QPoint(x - 3, y + 5)]
                      if index.data(COLLAPSED_ROLE) else
                      [QPoint(x - 5, y - 3), QPoint(x + 5, y - 3), QPoint(x, y + 3)])
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#c4c8cf"))
            painter.drawPolygon(QPolygon(points))
            painter.restore()

    def editorEvent(self, event, model, option, index):
        return super().editorEvent(event, model, self.indented_option(option, index), index)

    def updateEditorGeometry(self, editor, option, index):
        super().updateEditorGeometry(editor, self.indented_option(option, index), index)


class LayerList(QListWidget):
    collapse_requested = pyqtSignal(str)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and item.data(GROUP_ROLE) and event.button() == Qt.MouseButton.LeftButton:
            if event.position().x() < self.visualItemRect(item).left() + 22:
                self.collapse_requested.emit(item.data(Qt.ItemDataRole.UserRole))
                event.accept()
                return
        if event.button() == Qt.MouseButton.RightButton and item and item.isSelected():
            self.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
            event.accept()
            return
        super().mousePressEvent(event)


class LayersPanel(QWidget):
    edit_text_requested = pyqtSignal()
    selection_changed = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.updating = False
        self.fingerprint = None
        self.setObjectName("layersPanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        heading = QWidget()
        heading.setObjectName("panelHeader")
        heading_layout = QHBoxLayout(heading)
        heading_layout.setContentsMargins(16, 14, 14, 14)
        heading_layout.addWidget(QLabel("LAYERS"))
        self.count = QLabel()
        self.count.setObjectName("muted")
        heading_layout.addStretch()
        heading_layout.addWidget(self.count)
        layout.addWidget(heading)
        self.list = LayerList()
        self.list.setObjectName("layerList")
        self.list.setItemDelegate(LayerDelegate(self.list))
        self.list.setIconSize(QSize(48, 36))
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        self.list.collapse_requested.connect(self.toggle_group)
        self.list.itemChanged.connect(self.item_changed)
        self.list.currentItemChanged.connect(self.current_changed)
        self.list.itemSelectionChanged.connect(self.sync_selection)
        self.list.model().rowsMoved.connect(lambda: QTimer.singleShot(0, self.commit_order))
        layout.addWidget(self.list, 1)
        footer = QWidget()
        footer.setObjectName("panelFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 8, 10, 8)
        for name, hint, callback in [
            ("new", "Create transparent layer", lambda: self.controller.apply("New layer", operations.add_layer)),
            ("duplicate", "Duplicate layer or group", self.duplicate),
            ("up", "Move layer or group up", lambda: self.shift(1)),
            ("down", "Move layer or group down", lambda: self.shift(-1)),
            ("delete", "Delete layer or group", self.delete),
        ]:
            button = QToolButton()
            button.setIcon(icon(name, size=18))
            button.setToolTip(hint)
            button.setFixedSize(32, 30)
            button.clicked.connect(callback)
            footer_layout.addWidget(button)
        footer_layout.addStretch()
        layout.addWidget(footer)
        controller.changed.connect(self.refresh)
        self.refresh()

    def current_group(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item and item.data(GROUP_ROLE) else None

    def refresh(self):
        doc = self.controller.document
        current = self.list.currentItem()
        current_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        selected_groups = {item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()
                           if item.data(GROUP_ROLE)}
        if doc:
            selected_groups = {entry_id for entry_id in selected_groups
                               if any(layer.group_id == entry_id for layer in doc.layers)
                               and all(layer.id in doc.selected_ids for layer in doc.layers if layer.group_id == entry_id)}
        self.updating = True
        self.list.blockSignals(True)
        if doc is None:
            self.list.clear()
            self.count.setText("0")
            self.fingerprint = None
        else:
            fingerprint = (tuple((l.id, id(l.image), l.x, l.y, l.name, l.visible, l.group_id, l.text is not None)
                                 for l in doc.layers), doc.groups)
            if fingerprint != self.fingerprint:
                self.list.clear()
                folders = {group.id: group for group in doc.groups}
                added = set()
                for layer in reversed(doc.layers):
                    if layer.group_id and layer.group_id not in added:
                        group = folders[layer.group_id]
                        header = QListWidgetItem(icon("folder"), group.name)
                        header.setData(Qt.ItemDataRole.UserRole, group.id)
                        header.setData(GROUP_ROLE, True)
                        header.setData(COLLAPSED_ROLE, group.collapsed)
                        header.setFlags(header.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
                        header.setCheckState(Qt.CheckState.Checked if group.visible else Qt.CheckState.Unchecked)
                        header.setSizeHint(QSize(200, 38))
                        header.setToolTip("Uncheck to hide the entire group\nClick the arrow to expand / collapse\nDouble-click the name to rename · Drag to reorder the group")
                        self.list.addItem(header)
                        added.add(group.id)
                    item = QListWidgetItem(layer_thumbnail(layer.image, text=layer.text is not None), layer.name)
                    item.setData(Qt.ItemDataRole.UserRole, layer.id)
                    item.setData(PARENT_ROLE, layer.group_id)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
                    item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
                    item.setSizeHint(QSize(200, 60))
                    item.setToolTip(f"{layer.name}\n{layer.image.width:,} × {layer.image.height:,} px · position {layer.x}, {layer.y}\nDouble-click to rename · Drag to reorder")
                    if layer.text is not None:
                        item.setToolTip(item.toolTip() + "\nText layer · Right-click to edit text")
                    self.list.addItem(item)
                    item.setHidden(bool(layer.group_id and folders[layer.group_id].collapsed))
                self.fingerprint = fingerprint
            self.list.clearSelection()
            for i in range(self.list.count()):
                item = self.list.item(i)
                entry_id = item.data(Qt.ItemDataRole.UserRole)
                header = bool(item.data(GROUP_ROLE))
                item.setSelected(entry_id in selected_groups if header else
                                 entry_id in doc.selected_ids and item.data(PARENT_ROLE) not in selected_groups)
                font = item.font()
                font.setBold(header or entry_id == doc.active_id)
                item.setFont(font)
                if (entry_id == current_id and entry_id in selected_groups) or (entry_id == doc.active_id and current_id not in selected_groups):
                    self.list.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.count.setText(f"{len(doc.selected_ids)} / {len(doc.layers)}" if len(doc.selected_ids) > 1 else str(len(doc.layers)))
            self.count.setToolTip(f"{len(doc.selected_ids)} selected of {len(doc.layers)} layers")
        self.list.blockSignals(False)
        self.updating = False

    def current_changed(self, current, previous):
        if current and not self.updating:
            self.sync_selection()

    def sync_selection(self):
        doc = self.controller.document
        if self.updating or not doc:
            return
        selected = set()
        for item in self.list.selectedItems():
            entry_id = item.data(Qt.ItemDataRole.UserRole)
            if item.data(GROUP_ROLE):
                selected.update(layer.id for layer in doc.layers if layer.group_id == entry_id)
            else:
                selected.add(entry_id)
        current = self.list.currentItem()
        active = current.data(Qt.ItemDataRole.UserRole) if current and not current.data(GROUP_ROLE) else None
        self.controller.select_layers(selected, active)
        self.selection_changed.emit()

    def select_group(self, group_id):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == group_id:
                self.list.setCurrentItem(item, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.sync_selection()
                return

    def group_selected(self):
        existing = {group.id for group in self.controller.document.groups}
        if self.controller.apply("Group layers", groups.group_layers):
            created = next(group.id for group in self.controller.document.groups if group.id not in existing)
            self.select_group(created)

    def toggle_group(self, group_id):
        group = next(group for group in self.controller.document.groups if group.id == group_id)
        self.controller.apply("Collapse group" if not group.collapsed else "Expand group",
                              lambda doc: groups.set_collapsed(doc, group_id, not group.collapsed))

    def merge(self):
        self.controller.apply("Merge layers", operations.merge_layers)

    def toggle_visibility(self):
        doc = self.controller.document
        if doc is None:
            return
        group_id = self.current_group()
        if group_id:
            group = next(group for group in doc.groups if group.id == group_id)
            self.controller.apply("Group visibility", lambda doc: groups.set_visible(doc, group_id, not group.visible))
        else:
            self.controller.apply("Layer visibility", lambda doc:
                                  doc.with_layer(replace(doc.active, visible=not doc.active.visible)))

    def item_changed(self, item):
        if self.updating:
            return
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        if item.data(GROUP_ROLE):
            group = next(group for group in self.controller.document.groups if group.id == entry_id)
            name = item.text().strip()
            if not name:
                self.list.blockSignals(True)
                item.setText(group.name)
                self.list.blockSignals(False)
            elif name != group.name:
                self.controller.apply("Rename group", lambda doc: groups.rename_group(doc, entry_id, name))
            elif (visible := item.checkState() == Qt.CheckState.Checked) != group.visible:
                self.controller.apply("Group visibility", lambda doc: groups.set_visible(doc, entry_id, visible))
            return
        layer = next(l for l in self.controller.document.layers if l.id == entry_id)
        name = item.text().strip() or layer.name
        visible = item.checkState() == Qt.CheckState.Checked
        if layer.name != name or layer.visible != visible:
            updated = replace(layer, name=name, visible=visible)
            self.controller.apply("Rename layer" if layer.name != name else "Layer visibility",
                                  lambda doc: doc.with_layer(updated))

    def commit_order(self):
        doc = self.controller.document
        if self.updating or not doc:
            return
        rows = [self.list.item(i) for i in range(self.list.count())]
        ids = []
        for item in rows:
            entry_id = item.data(Qt.ItemDataRole.UserRole)
            if item.data(GROUP_ROLE):
                ids.extend(child.data(Qt.ItemDataRole.UserRole) for child in rows if child.data(PARENT_ROLE) == entry_id)
            elif not item.data(PARENT_ROLE):
                ids.append(entry_id)
        ids.reverse()
        if ids != [l.id for l in doc.layers]:
            self.controller.apply("Reorder layers", lambda doc: operations.reorder_layers(doc, ids))
        # Normalize the displayed rows after dragging a header or a child.
        self.fingerprint = None
        self.refresh()

    def shift(self, direction):
        entry_id = self.current_group() or self.controller.document.active_id
        self.controller.apply("Reorder layers", lambda doc: groups.shift_entry(doc, entry_id, direction))

    def duplicate(self):
        group_id = self.current_group()
        if group_id:
            if self.controller.apply("Duplicate group", lambda doc: groups.duplicate_group(doc, group_id)):
                self.select_group(self.controller.document.active.group_id)
        else:
            self.controller.apply("Duplicate layer", operations.duplicate_layer)

    def can_delete(self):
        doc = self.controller.document
        group_id = self.current_group()
        return bool(doc and (any(layer.group_id != group_id for layer in doc.layers) if group_id else len(doc.layers) > 1))

    def delete(self):
        group_id = self.current_group()
        if group_id:
            self.controller.apply("Delete group", lambda doc: groups.delete_group(doc, group_id))
        else:
            self.controller.apply("Delete layer", operations.delete_layer)

    def rename(self):
        group_id = self.current_group()
        if group_id:
            group = next(group for group in self.controller.document.groups if group.id == group_id)
            name, accepted = QInputDialog.getText(self, "Rename group", "Name", text=group.name)
            if accepted:
                self.controller.apply("Rename group", lambda doc: groups.rename_group(doc, group_id, name))
        else:
            layer = self.controller.document.active
            name, accepted = QInputDialog.getText(self, "Rename layer", "Name", text=layer.name)
            if accepted and name.strip():
                self.controller.apply("Rename layer", lambda doc: doc.with_layer(replace(layer, name=name.strip())))

    def context_menu(self, point):
        item = self.list.itemAt(point)
        if item:
            flag = QItemSelectionModel.SelectionFlag.NoUpdate if item.isSelected() else QItemSelectionModel.SelectionFlag.ClearAndSelect
            self.list.setCurrentItem(item, flag)
        self.sync_selection()
        menu = QMenu(self)
        group_id = self.current_group()
        edit_text = rasterize = ungroup = None
        if not group_id and self.controller.document.active.text is not None:
            edit_text = menu.addAction("Edit Text Layer")
            edit_text.setEnabled(self.controller.document.layer_visible(self.controller.document.active))
            rasterize = menu.addAction("Rasterize Text Layer")
            menu.addSeparator()
        kind = "Group" if group_id else "Layer"
        doc = self.controller.document
        visible = next(group.visible for group in doc.groups if group.id == group_id) if group_id else doc.active.visible
        visibility = menu.addAction(f"{'Hide' if visible else 'Show'} {kind}")
        rename = menu.addAction(f"Rename {kind}…")
        duplicate = menu.addAction(f"Duplicate {kind}")
        delete = menu.addAction(f"Delete {kind}")
        delete.setEnabled(self.can_delete())
        if group_id:
            ungroup = menu.addAction("Ungroup Layers")
        merge = group = None
        if len(self.controller.document.selected_ids) > 1:
            menu.addSeparator()
            group = menu.addAction("Group Layers")
            merge = menu.addAction("Merge Layers")
        chosen = menu.exec(self.list.mapToGlobal(point))
        if chosen == visibility:
            self.toggle_visibility()
        elif edit_text is not None and chosen == edit_text:
            self.edit_text_requested.emit()
        elif rasterize is not None and chosen == rasterize:
            self.controller.apply("Rasterize text", operations.rasterize_text)
        elif chosen == rename:
            self.rename()
        elif chosen == duplicate:
            self.duplicate()
        elif chosen == delete:
            self.delete()
        elif ungroup is not None and chosen == ungroup:
            self.controller.apply("Ungroup layers", lambda doc: groups.ungroup(doc, group_id))
        elif group is not None and chosen == group:
            self.group_selected()
        elif merge is not None and chosen == merge:
            self.merge()
