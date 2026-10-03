from dataclasses import replace
import math
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, QSize, QPointF
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence, QIcon
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                            QToolButton, QSplitter, QFileDialog, QMessageBox, QDialog,
                            QDoubleSpinBox, QPushButton, QProgressBar, QComboBox,
                            QLineEdit, QAbstractSpinBox, QApplication, QSizePolicy, QTabBar, QScrollBar)
from .canvas import Canvas
from .layers import LayersPanel
from .history import HistoryDock
from .dialogs import NewDialog, SizeDialog, FillDialog
from .icons import icon
from ..controller import EditorController
from ..clipboard import SelectionClipboard
from ..model import Document
from ..selection import Selection
from .. import operations, files

OPEN_FILTER = "Images and Rasterly projects (*.png *.jpg *.jpeg *.webp *.rasterly);;Rasterly project (*.rasterly);;PNG (*.png);;JPEG (*.jpg *.jpeg);;WebP (*.webp)"
SAVE_FILTER = "Rasterly project (*.rasterly);;PNG image (*.png);;JPEG image (*.jpg);;WebP image (*.webp)"
EXPORT_FILTER = "PNG image (*.png);;JPEG image (*.jpg);;WebP image (*.webp)"


class EditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1360, 900)
        self.setMinimumSize(880, 570)
        self.setWindowTitle("Rasterly")
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[1] / "resources" / "rasterly.svg")))
        self.setAcceptDrops(True)
        self.controller = EditorController(self)
        self.actions = {}
        self.tool_buttons = {}
        self.canvas = Canvas(self.controller)
        self.layers = LayersPanel(self.controller)
        self.clipboard = SelectionClipboard(self)
        self.history_dock = HistoryDock(self.controller, self.jump_history, self)
        self.create_actions()
        self.create_menus()
        self.create_layout()
        self.create_statusbar()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.history_dock)
        self.history_dock.hide()
        self.controller.changed.connect(self.refresh)
        self.controller.error.connect(self.show_error)
        self.controller.busy_changed.connect(self.busy_changed)
        self.controller.about_to_switch.connect(self.store_viewport)
        self.controller.session_changed.connect(self.restore_viewport)
        self.clipboard.changed.connect(self.refresh)
        self.canvas.tool_changed.connect(self.tool_changed)
        self.canvas.transform_changed.connect(self.transform_changed)
        self.canvas.zoom_changed.connect(self.zoom_changed)
        self.canvas.viewport_changed.connect(self.sync_horizontal_scrollbar)
        self.canvas.measurement_changed.connect(lambda text: self.statusBar().showMessage(text, 1500))
        QApplication.instance().focusChanged.connect(self.focus_changed)
        self.refresh()
        self.tool_changed("move")
        QTimer.singleShot(0, self.canvas.fit)

    def action(self, id, text, callback, shortcut=None, icon_name=None):
        action = QAction(icon(icon_name) if icon_name else self.windowIcon(), text, self)
        if not icon_name:
            action.setIconVisibleInMenu(False)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda checked=False: callback())
        self.actions[id] = action
        self.addAction(action)
        return action

    def apply(self, label, operation):
        self.canvas.cancel_interaction()
        return self.controller.apply(label, operation)

    def create_actions(self):
        self.action("new", "New…", self.new_document, "Ctrl+N", "new")
        self.action("open", "Open…", self.open_document, "Ctrl+O", "open")
        self.action("save", "Save", self.save, "Ctrl+S", "save")
        self.action("save_as", "Save As…", lambda: self.save(True), "Ctrl+Shift+S")
        self.action("export", "Export Image…", self.export, "Ctrl+Alt+S")
        self.action("close_tab", "Close Tab", lambda: self.close_tab(self.controller.active_index), "Ctrl+W")
        self.action("quit", "Quit", self.close, "Ctrl+Q")
        self.action("undo", "Undo", self.toggle_undo, "Ctrl+Z")
        self.action("step_backward", "Step Backward", self.undo, "Ctrl+Alt+Z")
        self.action("redo", "Redo", self.redo, "Ctrl+Shift+Z")
        self.action("copy", "Copy Selection", self.copy_selection, "Ctrl+C")
        self.action("paste", "Paste as New Layer", self.paste_selection, "Ctrl+V")
        self.action("fill", "Fill Selection…", self.fill, "Shift+F5", "fill")
        self.action("transform", "Free Transform", self.canvas.begin_transform, "Ctrl+T", "transform")
        self.action("crop", "Crop to Selection", lambda: self.apply("Crop", operations.crop), None, "crop")
        self.action("size", "Image Size / Canvas Size…", self.resize_document, "Ctrl+Alt+I", "size")
        self.action("layer_new", "New Layer", lambda: self.apply("New layer", operations.add_layer), "Ctrl+Shift+N")
        self.action("layer_duplicate", "Duplicate Layer", lambda: self.apply("Duplicate layer", operations.duplicate_layer), "Ctrl+J")
        self.action("layer_delete", "Delete Layer", lambda: self.apply("Delete layer", operations.delete_layer))
        self.action("layer_rename", "Rename Layer…", self.layers.rename)
        self.action("layer_merge", "Merge Layers", lambda: self.apply("Merge layers", operations.merge_layers), "Ctrl+E")
        self.action("layer_up", "Move Layer Up", lambda: self.layers.shift(1))
        self.action("layer_down", "Move Layer Down", lambda: self.layers.shift(-1))
        self.action("layer_visibility", "Show / Hide Layer", lambda: self.apply("Layer visibility", lambda doc:
                    doc.with_layer(replace(doc.active, visible=not doc.active.visible))))
        self.action("select_all", "Select All", lambda: self.change_selection(
            Selection.rectangle(0, 0, self.controller.document.width, self.controller.document.height),
            "Select all"), "Ctrl+A")
        self.action("deselect", "Deselect", lambda: self.change_selection(None, "Deselect"), "Ctrl+D")
        self.action("fit", "Fit on Screen", self.canvas.fit, "Ctrl+0", "fit")
        self.action("actual", "Actual Pixels", lambda: self.canvas.set_zoom(1), "Ctrl+1")
        self.action("zoom_in", "Zoom In", lambda: self.canvas.set_zoom(self.canvas.zoom * 1.25), "Ctrl++")
        self.action("zoom_out", "Zoom Out", lambda: self.canvas.set_zoom(self.canvas.zoom / 1.25), "Ctrl+-")
        self.action("shortcuts", "Keyboard Shortcuts", self.show_shortcuts)
        self.actions["history"] = self.history_dock.toggleViewAction()
        self.actions["history"].setText("History")
        self.layers.history_button.setDefaultAction(self.actions["history"])
        self.action("about", "About Rasterly", lambda: QMessageBox.about(self, "Rasterly",
                    "<b>Rasterly 0.1</b><br>A focused desktop raster image editor.<br><br>"
                    "Full-resolution layers, local healing, and a little more room for your image."))
        self.tool_group = QActionGroup(self)
        for id, shortcut in [("move", "V"), ("rectangle", "M"), ("lasso", "L"), ("patch", "J")]:
            tool = self.canvas.tools[id]
            action = self.action("tool_" + id, tool.name, lambda id=id: self.canvas.set_tool(id), shortcut, id)
            action.setCheckable(True)
            action.setToolTip(f"{tool.name} ({shortcut})")
            self.tool_group.addAction(action)
        self.actions["tool_move"].setChecked(True)

    def create_menus(self):
        groups = [
            ("File", ["new", "open", None, "save", "save_as", "export", None, "close_tab", "quit"]),
            ("Edit", ["undo", "step_backward", "redo", None, "copy", "paste", None, "fill", "transform"]),
            ("Image", ["crop", "size"]),
            ("Layer", ["layer_new", "layer_duplicate", "layer_delete", "layer_rename", "layer_merge", None,
                       "layer_up", "layer_down", "layer_visibility"]),
            ("Select", ["tool_rectangle", "tool_lasso", None, "select_all", "deselect"]),
            ("View", ["fit", "actual", "zoom_in", "zoom_out", None, "history"]),
            ("Help", ["shortcuts", "about"]),
        ]
        for name, ids in groups:
            menu = self.menuBar().addMenu(name)
            for id in ids:
                menu.addAction(self.actions[id]) if id else menu.addSeparator()

    def create_layout(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.options = QWidget()
        self.options.setObjectName("optionsBar")
        self.options.setFixedHeight(48)
        options = QHBoxLayout(self.options)
        options.setContentsMargins(14, 7, 14, 7)
        options.setSpacing(12)
        brand = QLabel("rasterly")
        brand.setObjectName("brand")
        brand.setFixedWidth(96)
        options.addWidget(brand)
        self.tool_label = QLabel()
        self.tool_label.setMinimumWidth(128)
        options.addWidget(self.tool_label)
        self.hint_label = QLabel()
        self.hint_label.setObjectName("muted")
        self.hint_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        options.addWidget(self.hint_label, 1)
        self.transform_controls = QWidget()
        controls = QHBoxLayout(self.transform_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        self.transform_width, self.transform_height = QDoubleSpinBox(), QDoubleSpinBox()
        for label, spin in [("W", self.transform_width), ("H", self.transform_height)]:
            spin.setRange(1, 32768)
            spin.setDecimals(0)
            spin.setSuffix(" px")
            spin.setFixedWidth(96)
            spin.valueChanged.connect(self.transform_dimensions)
            controls.addWidget(QLabel(label))
            controls.addWidget(spin)
        apply_button = QPushButton("Apply")
        apply_button.setObjectName("primary")
        apply_button.clicked.connect(self.canvas.commit_transform)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.canvas.cancel_transform)
        controls.addWidget(apply_button)
        controls.addWidget(cancel)
        options.addWidget(self.transform_controls)
        self.transform_controls.hide()
        self.quick_controls = QWidget()
        quick = QHBoxLayout(self.quick_controls)
        quick.setContentsMargins(0, 0, 0, 0)
        quick.setSpacing(5)
        for id in ("crop", "fill", "size"):
            button = QToolButton()
            button.setDefaultAction(self.actions[id])
            button.setFixedSize(32, 32)
            quick.addWidget(button)
        options.addWidget(self.quick_controls)
        root.addWidget(self.options)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.toolbar = QWidget()
        self.toolbar.setObjectName("toolsBar")
        self.toolbar.setFixedWidth(50)
        toolbar = QVBoxLayout(self.toolbar)
        toolbar.setContentsMargins(6, 12, 6, 12)
        toolbar.setSpacing(7)
        for id in ("move", "rectangle", "lasso", "patch"):
            button = QToolButton()
            button.setDefaultAction(self.actions["tool_" + id])
            button.setIconSize(QSize(22, 22))
            button.setFixedSize(38, 38)
            toolbar.addWidget(button)
            self.tool_buttons[id] = button
        toolbar.addSpacing(12)
        for id in ("crop", "transform"):
            button = QToolButton()
            button.setDefaultAction(self.actions[id])
            button.setIconSize(QSize(22, 22))
            button.setFixedSize(38, 38)
            toolbar.addWidget(button)
        toolbar.addStretch()
        fit = QToolButton()
        fit.setDefaultAction(self.actions["fit"])
        fit.setFixedSize(38, 38)
        toolbar.addWidget(fit)
        body.addWidget(self.toolbar)
        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        tabbar = QWidget()
        tabbar.setObjectName("documentBar")
        tabbar.setFixedHeight(38)
        tab_layout = QHBoxLayout(tabbar)
        tab_layout.setContentsMargins(0, 0, 8, 0)
        self.tab_bar = QTabBar()
        self.tab_bar.setObjectName("documentTabs")
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDrawBase(False)
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tab_bar.currentChanged.connect(self.switch_tab)
        self.tab_bar.tabCloseRequested.connect(self.close_tab)
        tab_layout.addWidget(self.tab_bar, 1)
        self.processing_label = QLabel()
        self.processing_label.setObjectName("muted")
        tab_layout.addWidget(self.processing_label)
        workspace_layout.addWidget(tabbar)
        workspace_layout.addWidget(self.canvas, 1)
        self.horizontal_scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.horizontal_scrollbar.setObjectName("canvasHorizontalScrollbar")
        self.horizontal_scrollbar.setToolTip("Scroll image horizontally")
        self.horizontal_scrollbar.hide()
        self.horizontal_scrollbar.valueChanged.connect(self.canvas.scroll_horizontal)
        workspace_layout.addWidget(self.horizontal_scrollbar)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(workspace)
        splitter.addWidget(self.layers)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1050, 260])
        splitter.setChildrenCollapsible(False)
        body.addWidget(splitter, 1)
        root.addLayout(body, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)
        self.setCentralWidget(central)

    def create_statusbar(self):
        self.zoom_control = QComboBox()
        self.zoom_control.setEditable(True)
        self.zoom_control.setFixedWidth(92)
        self.zoom_control.setFixedHeight(26)
        self.zoom_control.addItems(["25%", "50%", "100%", "200%", "400%"])
        self.zoom_control.activated.connect(self.enter_zoom)
        self.zoom_control.lineEdit().returnPressed.connect(self.enter_zoom)
        self.statusBar().addWidget(self.zoom_control)
        self.status_dimensions = QLabel()
        self.status_dimensions.setObjectName("muted")
        self.statusBar().addWidget(self.status_dimensions)
        hint = QLabel("Space: pan     Ctrl+scroll: zoom")
        hint.setObjectName("muted")
        self.statusBar().addPermanentWidget(hint)

    def sync_horizontal_scrollbar(self):
        doc = self.controller.document
        available = max(1, self.canvas.width() - 22)
        overflow = doc.width * self.canvas.zoom - available if doc else 0
        self.horizontal_scrollbar.setVisible(overflow > 0)
        if overflow <= 0:
            return
        # Both ends align with the image frame; preserve vertical wheel panning.
        pan_x = min(overflow / 2, max(-overflow / 2, self.canvas.pan.x()))
        if pan_x != self.canvas.pan.x():
            self.canvas.pan.setX(pan_x)
            self.canvas.update()
        self.horizontal_scrollbar.blockSignals(True)
        self.horizontal_scrollbar.setRange(0, math.ceil(overflow))
        self.horizontal_scrollbar.setPageStep(available)
        self.horizontal_scrollbar.setSingleStep(40)
        self.horizontal_scrollbar.setValue(round(overflow / 2 - pan_x))
        self.horizontal_scrollbar.blockSignals(False)

    def refresh(self):
        self.sync_horizontal_scrollbar()
        doc = self.controller.document
        name = self.controller.active_session.title if doc else "Rasterly"
        dirty = " •" if self.controller.dirty else ""
        self.setWindowTitle(f"{name}{dirty} — Rasterly" if doc else "Rasterly")
        self.tab_bar.blockSignals(True)
        while self.tab_bar.count() > len(self.controller.sessions):
            self.tab_bar.removeTab(self.tab_bar.count() - 1)
        while self.tab_bar.count() < len(self.controller.sessions):
            index = self.tab_bar.addTab("")
            close = QToolButton()
            close.setIcon(icon("close", "#aeb7c8", 14))
            close.setFixedSize(20, 20)
            close.setToolTip("Close tab")
            close.clicked.connect(self.request_tab_close)
            self.tab_bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        for i, session in enumerate(self.controller.sessions):
            zoom = self.canvas.zoom if i == self.controller.active_index else session.viewport[0] if session.viewport else 1
            self.tab_bar.setTabText(i, f"{session.title}{' •' if session.dirty else ''}  @ {zoom * 100:.0f}%")
            self.tab_bar.setTabToolTip(i, session.path or session.title)
            self.tab_bar.setTabData(i, session.id)
        self.tab_bar.setCurrentIndex(self.controller.active_index)
        self.tab_bar.blockSignals(False)
        self.tab_bar.setEnabled(not self.controller.busy)
        self.status_dimensions.setText(f"  {doc.width:,} × {doc.height:,} px" if doc else "")
        free = doc is not None and not self.controller.busy and not self.canvas.session
        always = {"about", "shortcuts", "quit", "history"}
        opening = {"new", "open"}
        view = {"fit", "actual", "zoom_in", "zoom_out"}
        for id, action in self.actions.items():
            action.setEnabled(id in always or free or (id in opening and not self.controller.busy and not self.canvas.session)
                              or (doc is not None and id in view and not self.controller.busy))
        selected = bool(doc and doc.selection and doc.selection.valid)
        for id in ("crop", "fill", "deselect", "copy"):
            self.actions[id].setEnabled(free and selected)
        self.actions["paste"].setEnabled(free and self.clipboard.has_image)
        self.actions["close_tab"].setEnabled(doc is not None and not self.controller.busy)
        self.actions["undo"].setEnabled(free and self.controller.history.can_toggle)
        self.actions["step_backward"].setEnabled(free and bool(self.controller.history.undo_stack))
        self.actions["redo"].setEnabled(free and bool(self.controller.history.redo_stack))
        self.actions["undo"].setText("Undo " + self.controller.history.undo_stack[-1].label if self.controller.history.undo_stack else "Undo")
        if self.controller.history.toggle_redo:
            self.actions["undo"].setText("Redo " + self.controller.history.redo_stack[-1].label)
        self.actions["redo"].setText("Redo " + self.controller.history.redo_stack[-1].label if self.controller.history.redo_stack else "Redo")
        self.actions["layer_delete"].setEnabled(free and len(doc.layers) > 1 if doc else False)
        self.actions["layer_merge"].setEnabled(free and len(doc.selected_ids) > 1 if doc else False)
        self.layers.setEnabled(free)
        self.layers.history_button.setEnabled(True)
        self.history_dock.list.setEnabled(free)
        self.toolbar.setEnabled(doc is not None and not self.controller.busy)
        self.zoom_control.setEnabled(doc is not None and not self.controller.busy)

    def store_viewport(self):
        self.canvas.cancel_interaction()
        if self.canvas.session:
            self.canvas.cancel_transform()
        self.canvas.panning = False
        self.canvas.space_held = False
        if self.controller.active_session:
            self.controller.active_session.viewport = (self.canvas.zoom, self.canvas.pan.x(),
                                                        self.canvas.pan.y(), self.canvas.tool_id)

    def restore_viewport(self, index):
        self.canvas.images.clear()
        session = self.controller.active_session
        if session:
            if session.viewport:
                zoom, x, y, tool = session.viewport
                self.canvas.zoom, self.canvas.pan = zoom, QPointF(x, y)
                self.canvas.set_tool(tool)
                self.zoom_changed(zoom)
            else:
                self.canvas.set_tool("move")
                self.canvas.fit()
        self.canvas.setFocus()
        self.sync_horizontal_scrollbar()
        self.canvas.update()

    def switch_tab(self, index):
        if not self.controller.switch_document(index):
            self.refresh()

    def request_tab_close(self):
        button = self.sender()
        for index in range(self.tab_bar.count()):
            if self.tab_bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is button:
                self.close_tab(index)
                break

    def close_tab(self, index):
        if self.controller.busy or not 0 <= index < len(self.controller.sessions):
            return False
        original = self.controller.active_session
        target = self.controller.sessions[index]
        # Save uses the active document, so focus the tab named in the prompt.
        if target.dirty:
            self.controller.switch_document(index)
            self.canvas.cancel_interaction()
            if self.canvas.session:
                self.canvas.cancel_transform()
            if not self.confirm_unsaved():
                self.controller.switch_document(self.controller.sessions.index(original))
                return False
        self.controller.close_document(index)
        if original is not target:
            self.controller.switch_document(next(i for i, session in enumerate(self.controller.sessions) if session is original))
        return True

    def change_selection(self, selection, label):
        self.canvas.cancel_interaction()
        self.controller.set_selection(selection, label)

    def jump_history(self, position):
        if self.controller.busy or self.canvas.session:
            return
        self.canvas.cancel_interaction()
        self.controller.jump_history(position)
        self.canvas.setFocus()

    def copy_selection(self):
        if not self.controller.document:
            return
        self.canvas.cancel_interaction()
        try:
            self.clipboard.copy(self.controller.document, self.controller.active_session.id)
            self.statusBar().showMessage("Copied selection", 2500)
        except Exception as error:
            self.show_error(str(error))

    def paste_selection(self):
        if not self.controller.document:
            return
        try:
            image, position = self.clipboard.read(self.controller.active_session.id)
            self.apply("Paste selection", lambda doc: operations.paste_layer(doc, image, position))
            self.canvas.setFocus()
        except Exception as error:
            self.show_error(str(error))

    def tool_changed(self, id):
        tool = self.canvas.tools[id]
        self.tool_label.setText(tool.name)
        self.hint_label.setText(tool.hint)
        self.actions["tool_" + id].setChecked(True)

    def transform_changed(self, active):
        self.transform_controls.setVisible(active)
        self.quick_controls.setVisible(not active)
        if active:
            self.tool_label.setText("Free Transform")
            self.hint_label.setText("Shift: lock ratio · Right-click: flip / rotate · Enter / Esc")
            for spin, value in [(self.transform_width, self.canvas.session.box.width()),
                                (self.transform_height, self.canvas.session.box.height())]:
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
        else:
            self.tool_changed(self.canvas.tool_id)
        self.refresh()

    def transform_dimensions(self):
        if self.canvas.session:
            box = self.canvas.session.box
            center = box.center()
            box.setWidth(self.transform_width.value())
            box.setHeight(self.transform_height.value())
            box.moveCenter(center)
            self.canvas.update()

    def zoom_changed(self, zoom):
        self.zoom_control.blockSignals(True)
        self.zoom_control.setEditText(f"{zoom * 100:.1f}%" if zoom < 1 else f"{zoom * 100:.0f}%")
        self.zoom_control.blockSignals(False)
        self.refresh()

    def enter_zoom(self):
        try:
            value = float(self.zoom_control.currentText().replace("%", "").strip())
            if not 1 <= value <= 3200:
                raise ValueError()
            self.canvas.set_zoom(value / 100)
            self.canvas.setFocus()
        except ValueError:
            self.zoom_changed(self.canvas.zoom)

    def focus_changed(self, old, new):
        typing = isinstance(new, (QLineEdit, QAbstractSpinBox, QComboBox))
        for id, shortcut in [("move", "V"), ("rectangle", "M"), ("lasso", "L"), ("patch", "J")]:
            self.actions["tool_" + id].setShortcut(QKeySequence() if typing else QKeySequence(shortcut))

    def busy_changed(self, busy, label):
        self.processing_label.setText(label + "…" if busy else "")
        self.progress.setVisible(busy)
        self.options.setEnabled(not busy)
        self.canvas.setCursor(Qt.CursorShape.BusyCursor if busy else
                              Qt.CursorShape.SizeAllCursor if self.canvas.tool_id == "move" else Qt.CursorShape.CrossCursor)
        self.refresh()

    def show_error(self, message):
        QMessageBox.warning(self, "Rasterly", message)

    def confirm_unsaved(self):
        if not self.controller.dirty:
            return True
        answer = QMessageBox.question(self, "Save changes?", f'Save changes to "{self.controller.active_session.title}" before closing?',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def new_document(self):
        dialog = NewDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.add_document(Document.new(*dialog.dimensions))

    def open_document(self, path=None):
        if self.controller.busy or self.canvas.session:
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open image", "", OPEN_FILTER)
        if not path:
            return
        try:
            # Opening another image retains all existing documents and histories.
            document = files.open_document(path)
            self.controller.add_document(document, str(Path(path).resolve()))
        except Exception as error:
            self.show_error(str(error))

    def choose_output(self, export=False):
        path = Path(self.controller.path) if self.controller.path else Path("Untitled.rasterly")
        default = str(path.with_suffix(".png" if export else ".rasterly"))
        chosen, filter = QFileDialog.getSaveFileName(self, "Export image" if export else "Save As", default,
                                                    EXPORT_FILTER if export else SAVE_FILTER)
        if not chosen:
            return None
        if Path(chosen).suffix.lower() not in files.RASTER_SUFFIXES | {files.PROJECT_SUFFIX}:
            suffix = {"Rasterly": ".rasterly", "PNG": ".png", "JPEG": ".jpg", "WebP": ".webp"}
            chosen += next(value for key, value in suffix.items() if filter.startswith(key))
        return chosen

    def save(self, save_as=False):
        if self.controller.busy or self.canvas.session or not self.controller.document:
            return False
        path = self.controller.path
        doc = self.controller.document
        if save_as or not path or (len(doc.layers) > 1 and Path(path).suffix.lower() != files.PROJECT_SUFFIX):
            path = self.choose_output()
        if not path:
            return False
        layered_raster = len(doc.layers) > 1 and Path(path).suffix.lower() != files.PROJECT_SUFFIX
        if layered_raster:
            answer = QMessageBox.question(self, "Save flattened image?",
                    "PNG, JPEG and WebP store the visible composite. Layers are kept in this session, "
                    "but reopening this file creates a single layer. Use .rasterly to preserve editable layers.\n\nSave the flattened image?",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Save:
                return False
        try:
            if Path(path).suffix.lower() == files.PROJECT_SUFFIX:
                files.save_project(doc, path)
            else:
                files.export_image(doc, path)
            self.controller.path = str(Path(path).resolve())
            self.controller.saved_revision = doc.revision
            self.history_dock.refresh()
            self.refresh()
            self.statusBar().showMessage("Saved " + Path(path).name, 4000)
            return True
        except Exception as error:
            self.show_error(str(error))
            return False

    def export(self):
        path = self.choose_output(True)
        if path:
            try:
                files.export_image(self.controller.document, path)
                self.statusBar().showMessage("Exported " + Path(path).name, 4000)
            except Exception as error:
                self.show_error(str(error))

    def fill(self):
        self.canvas.cancel_interaction()
        dialog = FillDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.mode.currentIndex() == 0:
                self.controller.heal()
            else:
                color = dialog.color.getRgb()
                self.apply("Solid Color Fill", lambda doc: operations.solid_fill(doc, color))

    def resize_document(self):
        self.canvas.cancel_interaction()
        dialog = SizeDialog(self.controller.document, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height = dialog.dimensions
        if dialog.mode.currentIndex() == 0:
            self.controller.run_background("Image Size", lambda doc: operations.resize_image(doc, width, height))
        else:
            self.apply("Canvas Size", lambda doc: operations.resize_canvas(doc, width, height, dialog.anchor))

    def toggle_undo(self):
        self.canvas.cancel_interaction()
        self.controller.toggle_undo()

    def undo(self):
        self.canvas.cancel_interaction()
        self.controller.undo()

    def redo(self):
        self.canvas.cancel_interaction()
        self.controller.redo()

    def show_shortcuts(self):
        QMessageBox.information(self, "Keyboard shortcuts",
            "V — Move\nM — Rectangle selection\nL — Lasso\nJ — Patch\n\n"
            "Rectangle / Lasso: Shift + drag — Add to selection\n"
            "Rectangle / Lasso: Left Alt + drag — Subtract from selection\n\n"
            "Ctrl+N — New image\nCtrl+O — Open\nCtrl+S — Save\nCtrl+Shift+S — Save As\n"
            "Ctrl+Alt+S — Export\n\nCtrl+T — Free Transform\nShift+F5 — Fill selection\n"
            "Ctrl+W — Close tab\nCtrl+C — Copy selection\nCtrl+V — Paste as new layer\n\n"
            "Ctrl+D — Deselect\nCtrl+A — Select all\nCtrl+Alt+I — Image / Canvas Size\n"
            "Ctrl+Shift+N — New layer\nCtrl+J — Duplicate layer\nCtrl+E — Merge selected layers\n\n"
            "Ctrl+Z — Toggle last history step\nCtrl+Alt+Z — Step backward\n"
            "Ctrl+Shift+Z — Redo\nCtrl+0 — Fit image\nCtrl+1 — Actual pixels\n"
            "Space + drag / middle mouse — Pan\nCtrl + scroll — Zoom\n\n"
            "In Free Transform: Shift — Lock aspect ratio\nRight-click — Flip / Rotate 90°\nEnter — Apply\nEscape — Cancel")

    def dragEnterEvent(self, event):
        if not self.controller.busy and not self.canvas.session and event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).suffix.lower() in files.RASTER_SUFFIXES | {files.PROJECT_SUFFIX}:
                event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.open_document(urls[0].toLocalFile())

    def closeEvent(self, event):
        if self.controller.busy:
            self.statusBar().showMessage("Wait for the current image operation to finish before closing.", 4000)
            event.ignore()
            return
        self.canvas.cancel_interaction()
        if self.canvas.session:
            self.canvas.cancel_transform()
        original = self.controller.active_session
        for i, session in enumerate(self.controller.sessions):
            if session.dirty:
                self.controller.switch_document(i)
                if not self.confirm_unsaved():
                    if original:
                        self.controller.switch_document(next(i for i, s in enumerate(self.controller.sessions) if s is original))
                    event.ignore()
                    return
        event.accept()
