from dataclasses import replace
from PyQt6.QtCore import Qt, QTimer, QSize, QItemSelectionModel
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                            QListWidgetItem, QAbstractItemView, QToolButton, QMenu,
                            QInputDialog)
from .icons import icon
from .images import qimage
from .. import operations


class LayerList(QListWidget):
    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.RightButton and item and item.isSelected():
            self.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
            event.accept()
            return
        super().mousePressEvent(event)


class LayersPanel(QWidget):
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
        self.history_button = QToolButton()
        self.history_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.history_button.setToolTip("Open action history")
        heading_layout.addWidget(self.history_button)
        layout.addWidget(heading)
        self.list = LayerList()
        self.list.setObjectName("layerList")
        self.list.setIconSize(QSize(48, 36))
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
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
            ("duplicate", "Duplicate layer", lambda: self.controller.apply("Duplicate layer", operations.duplicate_layer)),
            ("up", "Move layer up", lambda: self.shift(1)),
            ("down", "Move layer down", lambda: self.shift(-1)),
            ("delete", "Delete layer", lambda: self.controller.apply("Delete layer", operations.delete_layer)),
        ]:
            button = QToolButton()
            button.setIcon(icon(name, size=18))
            button.setToolTip(hint)
            button.setFixedSize(32, 30)
            button.clicked.connect(callback)
            footer_layout.addWidget(button)
        footer_layout.addStretch()
        layout.addWidget(footer)
        info = QWidget()
        info.setObjectName("documentInfo")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(16, 18, 16, 18)
        info_layout.addWidget(QLabel("DOCUMENT"))
        self.dimensions = QLabel()
        self.dimensions.setObjectName("infoDimensions")
        info_layout.addWidget(self.dimensions)
        label = QLabel("RGB · 8-bit · transparency supported")
        label.setObjectName("muted")
        label.setWordWrap(True)
        info_layout.addWidget(label)
        self.selection_info = QLabel("No selection")
        self.selection_info.setObjectName("muted")
        info_layout.addSpacing(10)
        info_layout.addWidget(self.selection_info)
        layout.addWidget(info)
        controller.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        doc = self.controller.document
        if doc is None:
            self.updating = True
            self.list.clear()
            self.count.setText("0")
            self.dimensions.setText("No image open")
            self.selection_info.setText("No selection")
            self.fingerprint = None
            self.updating = False
            return
        fingerprint = tuple((l.id, id(l.image), l.x, l.y, l.name, l.visible) for l in doc.layers)
        self.updating = True
        if fingerprint != self.fingerprint:
            self.list.clear()
            for layer in reversed(doc.layers):
                scale = min(48 / layer.image.width, 36 / layer.image.height, 1)
                thumbnail = layer.image.resize((max(1, round(layer.image.width * scale)),
                                                max(1, round(layer.image.height * scale))), reducing_gap=3)
                item = QListWidgetItem(QIcon(QPixmap.fromImage(qimage(thumbnail))), layer.name)
                item.setData(Qt.ItemDataRole.UserRole, layer.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
                item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
                item.setSizeHint(QSize(200, 60))
                item.setToolTip(f"{layer.name}\n{layer.image.width:,} × {layer.image.height:,} px · position {layer.x}, {layer.y}\nDouble-click to rename · Drag to reorder")
                self.list.addItem(item)
            self.fingerprint = fingerprint
        self.list.blockSignals(True)
        self.list.clearSelection()
        for i in range(self.list.count()):
            item = self.list.item(i)
            layer_id = item.data(Qt.ItemDataRole.UserRole)
            item.setSelected(layer_id in doc.selected_ids)
            font = item.font()
            font.setBold(layer_id == doc.active_id)
            item.setFont(font)
            if layer_id == doc.active_id:
                self.list.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.list.blockSignals(False)
        self.count.setText(f"{len(doc.selected_ids)} / {len(doc.layers)}" if len(doc.selected_ids) > 1 else str(len(doc.layers)))
        self.count.setToolTip(f"{len(doc.selected_ids)} selected of {len(doc.layers)} layers")
        self.dimensions.setText(f"{doc.width:,} × {doc.height:,} px")
        if doc.selection:
            a, b, c, d = doc.selection.bounds
            self.selection_info.setText(f"Selection   {c - a:,} × {d - b:,} px")
        else:
            self.selection_info.setText("No selection")
        self.updating = False

    def current_changed(self, current, previous):
        if current and not self.updating:
            self.sync_selection()

    def sync_selection(self):
        if self.updating or not self.controller.document:
            return
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()}
        current = self.list.currentItem()
        active = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.controller.select_layers(selected, active)

    def merge(self):
        self.controller.apply("Merge layers", operations.merge_layers)

    def item_changed(self, item):
        if self.updating:
            return
        id = item.data(Qt.ItemDataRole.UserRole)
        layer = next(l for l in self.controller.document.layers if l.id == id)
        name = item.text().strip() or layer.name
        visible = item.checkState() == Qt.CheckState.Checked
        if layer.name != name or layer.visible != visible:
            updated = replace(layer, name=name, visible=visible)
            self.controller.apply("Rename layer" if layer.name != name else "Layer visibility",
                                  lambda doc: doc.with_layer(updated))

    def commit_order(self):
        if self.updating:
            return
        ids = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in reversed(range(self.list.count()))]
        if ids != [l.id for l in self.controller.document.layers]:
            self.controller.apply("Reorder layers", lambda doc: operations.reorder_layers(doc, ids))

    def shift(self, direction):
        doc = self.controller.document
        ids = [l.id for l in doc.layers]
        index = ids.index(doc.active_id)
        destination = index + direction
        if 0 <= destination < len(ids):
            ids[index], ids[destination] = ids[destination], ids[index]
            self.controller.apply("Reorder layers", lambda doc: operations.reorder_layers(doc, ids))

    def rename(self):
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
        rename = menu.addAction("Rename Layer…")
        duplicate = menu.addAction("Duplicate Layer")
        delete = menu.addAction("Delete Layer")
        delete.setEnabled(len(self.controller.document.layers) > 1)
        merge = None
        if len(self.controller.document.selected_ids) > 1:
            menu.addSeparator()
            merge = menu.addAction("Merge Layers")
        chosen = menu.exec(self.list.mapToGlobal(point))
        if chosen == rename:
            self.rename()
        elif chosen == duplicate:
            self.controller.apply("Duplicate layer", operations.duplicate_layer)
        elif chosen == delete:
            self.controller.apply("Delete layer", operations.delete_layer)
        elif merge is not None and chosen == merge:
            self.merge()
