"""Inline type editing; the document changes only when the edit is applied."""
import math
from dataclasses import replace
from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QPalette, QRegion, QTextOption, QPainter
from PyQt6.QtWidgets import QFrame, QTextEdit, QGraphicsScene, QGraphicsView
from .base import Tool
from ..model import TextData
from ..operations import set_text_layer
from ..text import ALIGNMENTS, render_text, text_document, text_font, text_geometry


class TextEditor(QTextEdit):
    def __init__(self, tool):
        super().__init__(tool.canvas)
        self.tool = tool
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QTextEdit { background: transparent; border: 1px dashed #687da6; padding: 0; }")
        self.viewport().setAutoFillBackground(False)
        self.setTabChangesFocus(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.tool.cancel()
        elif (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
              and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.tool.commit()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        canvas = self.tool.canvas
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            point = QPointF(self.pos()) + event.position()
            if self.tool.view is not None:
                point = (QPointF(self.tool.view.mapFromScene(self.tool.proxy.mapToScene(event.position())))
                         + QPointF(self.tool.view.pos()))
            canvas.set_zoom(canvas.zoom * 1.18 ** (event.angleDelta().y() / 120),
                            point)
        else:
            delta = event.pixelDelta()
            if delta.isNull():
                delta = event.angleDelta() / 3
            canvas.pan += QPointF(delta)
            canvas.viewport_changed.emit()
            canvas.update()
        event.accept()


class TextTool(Tool):
    id = "text"
    name = "Type tool"
    hint = "Click to type · Click text to edit · Ctrl+Enter: apply · Esc: cancel"

    def __init__(self, canvas):
        super().__init__(canvas)
        self.defaults = TextData()
        self.editor = None
        self.layer_id = None
        self.view = None
        self.proxy = None
        self.canvas.viewport_changed.connect(self.reposition)
        self.canvas.zoom_changed.connect(lambda _: self.configure_editor())

    @property
    def editing(self):
        return self.editor is not None

    def press(self, point, event):
        if self.editing and not self.commit():
            return
        layer = next((layer for layer in reversed(self.canvas.document.layers)
                      if layer.visible and layer.text is not None
                      and layer.x <= point.x() < layer.bounds[2]
                      and layer.y <= point.y() < layer.bounds[3]), None)
        self.begin(point, layer)

    def begin(self, point=None, layer=None):
        if self.editing or self.canvas.controller.busy or not self.canvas.document:
            return
        if layer:
            if layer.text is None or not layer.visible:
                return
            self.canvas.controller.select_layer(layer.id)
        self.layer_id = layer.id if layer else None
        self.position = (layer.x, layer.y) if layer else (round(point.x()), round(point.y()))
        self.data = layer.text if layer else replace(self.defaults, content="")
        self.editor = TextEditor(self)
        if self.data.box_size is not None or self.data.quarter_turns or self.data.flip_x or self.data.flip_y:
            # A proxy widget keeps native typing and caret interaction through an affine transform.
            self.view = QGraphicsView(self.canvas)
            self.view.setScene(QGraphicsScene(self.view))
            self.view.setFrameShape(QFrame.Shape.NoFrame)
            self.view.setStyleSheet("QGraphicsView { background: transparent; border: 1px dashed #687da6; padding: 0; }")
            self.view.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.view.viewport().setAutoFillBackground(False)
            self.view.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
            self.editor.setStyleSheet("QTextEdit { background: transparent; border: none; padding: 0; }")
            self.editor.setParent(None)
            self.proxy = self.view.scene().addWidget(self.editor)
        self.editor.setPlainText(self.data.content)
        self.configure_editor()
        self.editor.textChanged.connect(self.content_changed)
        self.editor.show()
        if self.view is not None:
            self.view.show()
            self.view.setFocus()
        self.editor.setFocus()
        if layer:
            self.editor.selectAll()
        self.canvas.text_changed.emit(True)
        self.canvas.update()

    def content_changed(self):
        self.reposition()

    def current_data(self):
        return replace(self.data, content=self.editor.toPlainText())

    def set_style(self, data):
        self.defaults = replace(data, content="")
        if self.editing:
            box_size = self.data.box_size
            if box_size is not None and data.size != self.data.size:
                ratio = data.size / self.data.size
                box_size = tuple(max(1, min(32768, round(side * ratio))) for side in box_size)
            try:
                self.data = replace(data, content=self.editor.toPlainText(), box_size=box_size,
                                    quarter_turns=self.data.quarter_turns, flip_x=self.data.flip_x, flip_y=self.data.flip_y)
            except ValueError as error:
                self.canvas.controller.error.emit(str(error))
                self.canvas.text_changed.emit(True)
                return
            self.configure_editor()

    def configure_editor(self):
        if not self.editing:
            return
        editor = self.editor
        scale = 1 if self.view is not None else self.canvas.zoom
        font = text_font(self.data, scale, editor.logicalDpiY())
        editor.setFont(font)
        editor.document().setDefaultFont(font)
        editor.document().setDocumentMargin(2 * scale)
        option = QTextOption(ALIGNMENTS[self.data.alignment])
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        editor.document().setDefaultTextOption(option)
        # Apply style to the whole layer, including existing characters and new typing.
        cursor = editor.textCursor()
        start, end = cursor.anchor(), cursor.position()
        cursor.select(cursor.SelectionType.Document)
        fmt = cursor.charFormat()
        fmt.setFont(font)
        fmt.setForeground(QColor(*self.data.color))
        cursor.mergeCharFormat(fmt)
        block = cursor.blockFormat()
        block.setAlignment(ALIGNMENTS[self.data.alignment])
        cursor.mergeBlockFormat(block)
        cursor.setPosition(start)
        cursor.setPosition(end, cursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        palette = editor.palette()
        palette.setColor(QPalette.ColorRole.Text, QColor(*self.data.color))
        editor.setPalette(palette)
        self.reposition()

    def reposition(self):
        if not self.editing or not self.canvas.document:
            return
        # Layout is measured in document pixels even when the viewport is zoomed.
        content = self.editor.toPlainText()
        try:
            document = text_document(replace(self.data, content=content))
        except ValueError:
            return
        point = self.canvas.to_screen(QPointF(*self.position))
        width = math.ceil(document.size().width() * self.canvas.zoom) + 4
        height = math.ceil(document.size().height() * self.canvas.zoom) + 4
        host = self.editor
        if self.view is not None:
            (fitted_width, fitted_height), mapping = text_geometry(self.data, document)
            self.editor.resize(math.ceil(document.size().width()), math.ceil(document.size().height()))
            self.proxy.setTransform(mapping)
            self.view.setSceneRect(0, 0, fitted_width, fitted_height)
            self.view.resetTransform()
            self.view.scale(self.canvas.zoom, self.canvas.zoom)
            width, height = math.ceil(fitted_width * self.canvas.zoom) + 2, math.ceil(fitted_height * self.canvas.zoom) + 2
            host = self.view
        host.setGeometry(round(point.x()) - 1, round(point.y()) - 1,
                         max(80 if not content and self.view is None else 2, width),
                         max(18 if self.view is None else 2, height))
        origin = self.canvas.origin
        image_rect = QRect(round(origin.x()), round(origin.y()),
                           round(self.canvas.document.width * self.canvas.zoom),
                           round(self.canvas.document.height * self.canvas.zoom))
        visible = image_rect.intersected(self.canvas.rect().adjusted(22, 22, 0, 0))
        visible = visible.translated(-host.pos()).intersected(host.rect())
        # An empty QRegion clears the mask, so use an off-widget region when hidden.
        host.setMask(QRegion(visible if not visible.isEmpty() else QRect(-2, -2, 1, 1)))

    def commit(self):
        if not self.editing:
            return True
        try:
            data = self.current_data()
            if not data.content.strip() and self.layer_id is None:
                self.cancel()
                return True
            image = render_text(data)
            layer_id, position = self.layer_id, self.position
            success = self.canvas.controller.apply("Edit text" if layer_id else "New text layer",
                lambda doc: set_text_layer(doc, data, image, position, layer_id))
            if success:
                self.defaults = replace(data, content="", box_size=None, quarter_turns=0, flip_x=False, flip_y=False)
                self.cancel()
            return success
        except Exception as error:
            self.canvas.controller.error.emit(str(error))
            return False

    def cancel(self):
        if self.editor is not None:
            editor, self.editor = self.editor, None
            self.layer_id = None
            host = self.view if self.view is not None else editor
            self.view = self.proxy = None
            host.hide()
            host.deleteLater()
            self.canvas.text_changed.emit(False)
            self.canvas.setFocus()
        super().cancel()
