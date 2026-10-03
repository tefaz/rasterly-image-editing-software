"""Full-resolution layer rendering with independent viewport and tool previews."""
import math
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QLinearGradient
from PyQt6.QtWidgets import QWidget, QMenu
from .images import qimage, CHECKER_LIGHT, CHECKER_DARK
from .icons import tool_cursor
from ..tools import make_tools
from ..tools.transform import TransformSession
from ..operations import transform


class Canvas(QWidget):
    zoom_changed = pyqtSignal(float)
    viewport_changed = pyqtSignal()
    measurement_changed = pyqtSignal(str)
    transform_changed = pyqtSignal(bool)
    tool_changed = pyqtSignal(str)
    text_changed = pyqtSignal(bool)
    paint_settings_changed = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(260, 200)
        self.zoom = 0.4
        self.pan = QPointF()
        self.dragging = False
        self.pending_selection = None
        self.panning = False
        self.space_held = False
        self.preview_selection = None
        self.cached_selection = None
        self.cached_selection_path = QPainterPath()
        self.measurement = None
        self.move_preview = None
        self.patch_offset = None
        self.gradient_preview = None
        self.stroke_preview = None
        self.foreground_color = lambda: (0, 0, 0, 255)
        self.session = None
        self.last_mouse = QPointF(100, 100)
        self.images = {}
        self.tools = make_tools(self)
        self.tool_id = "move"
        self.patch_cursor = tool_cursor("patch")
        self.ant_phase = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(90)
        self.controller.changed.connect(self.document_changed)
        self.checker = QPixmap(16, 16)
        self.checker.fill(QColor(CHECKER_DARK))
        painter = QPainter(self.checker)
        painter.fillRect(0, 0, 8, 8, QColor(CHECKER_LIGHT))
        painter.fillRect(8, 8, 8, 8, QColor(CHECKER_LIGHT))
        painter.end()

    @property
    def document(self):
        return self.controller.document

    @property
    def origin(self):
        if not self.document:
            return QPointF()
        return QPointF((self.width() + 22 - self.document.width * self.zoom) / 2,
                       (self.height() + 22 - self.document.height * self.zoom) / 2) + self.pan

    def to_document(self, point):
        return (point - self.origin) / self.zoom

    def to_screen(self, point):
        return self.origin + point * self.zoom

    def clamp(self, point):
        return QPointF(max(0, min(self.document.width, round(point.x()))),
                       max(0, min(self.document.height, round(point.y()))))

    def document_changed(self):
        stroke = getattr(self.tools[self.tool_id], "stroke", None)
        if stroke is not None and stroke.document is not self.document:
            self.tools[self.tool_id].cancel()
            self.dragging = False
        images = {id(layer.image) for layer in self.document.layers} if self.document else set()
        if self.session:
            images.add(id(self.session.target.image))
            if self.session.target.base:
                images.add(id(self.session.target.base.image))
        if self.move_preview:
            target = self.move_preview[0]
            images.add(id(target.image))
            if target.base:
                images.add(id(target.base.image))
        self.images = {key: value for key, value in self.images.items() if key in images}
        self.viewport_changed.emit()
        self.update_tool_cursor()
        self.update()

    def update_tool_cursor(self):
        if self.controller.busy:
            self.setCursor(Qt.CursorShape.BusyCursor)
            return
        if self.session:
            return
        if self.panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self.space_held:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif self.tool_id == "move":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif self.tool_id == "text":
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            ready = False
            if self.tool_id == "patch" and self.document and not self.controller.busy:
                if self.dragging:
                    ready = self.patch_offset is not None
                elif self.document.selection:
                    point = self.to_document(self.last_mouse)
                    ready = (QRectF(0, 0, self.document.width, self.document.height).contains(point)
                             and self.selection_contains(point))
            self.setCursor(self.patch_cursor if ready else Qt.CursorShape.CrossCursor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport_changed.emit()
        self.update_tool_cursor()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def scroll_horizontal(self, offset):
        if not self.document:
            return
        available = self.width() - 22
        overflow = max(0, self.document.width * self.zoom - available)
        self.pan.setX(overflow / 2 - offset)
        self.viewport_changed.emit()
        self.update_tool_cursor()
        self.update()

    def animate(self):
        if self.document and (self.document.selection or self.preview_selection):
            self.ant_phase = (self.ant_phase + 1) % 8
            self.update()

    def set_tool(self, id):
        if self.controller.busy:
            return
        if self.tools["text"].editing and not self.tools["text"].commit():
            return
        if self.session:
            self.cancel_transform()
        self.tools[self.tool_id].cancel()
        self.dragging = False
        self.pending_selection = None
        self.tool_id = id
        self.update_tool_cursor()
        self.tool_changed.emit(id)
        self.setFocus()
        self.update()

    def fit(self):
        if not self.document:
            return
        self.zoom = max(0.01, min(4, (self.width() - 90) / self.document.width,
                                    (self.height() - 90) / self.document.height))
        self.pan = QPointF()
        self.zoom_changed.emit(self.zoom)
        self.viewport_changed.emit()
        self.update_tool_cursor()
        self.update()

    def set_zoom(self, zoom, point=None):
        if not self.document:
            return
        point = point or QPointF((self.width() + 22) / 2, (self.height() + 22) / 2)
        document_point = self.to_document(point)
        self.zoom = max(0.01, min(32, zoom))
        self.pan += point - self.to_screen(document_point)
        self.zoom_changed.emit(self.zoom)
        self.viewport_changed.emit()
        self.update_tool_cursor()
        self.update()

    def path(self, selection):
        if selection is self.cached_selection:
            return self.cached_selection_path
        path = self.build_selection_path(selection)
        self.cached_selection, self.cached_selection_path = selection, path
        return path

    def build_selection_path(self, selection):
        path = QPainterPath()
        if not selection:
            return path
        if selection.kind in {"union", "subtract"}:
            path = self.build_selection_path(selection.parts[0])
            for part in selection.parts[1:]:
                operand = self.build_selection_path(part)
                path = path.united(operand) if selection.kind == "union" else path.subtracted(operand)
            return path
        if not selection.points:
            return path
        if selection.kind == "rectangle":
            a, b, c, d = selection.bounds
            path.addRect(QRectF(a, b, c - a, d - b))
        else:
            path.moveTo(*selection.points[0])
            for point in selection.points[1:]:
                path.lineTo(*point)
            if selection.kind != "trace":
                path.closeSubpath()
        return path

    def selection_contains(self, point):
        return self.path(self.document.selection).contains(point)

    def measure(self, selection):
        a, b, c, d = selection.bounds
        self.measurement = f"{c - a:,} × {d - b:,} px"
        self.measurement_changed.emit(self.measurement)
        self.update()

    def draw_image(self, painter, image, box):
        key = id(image)
        if key not in self.images:
            self.images[key] = qimage(image)
        painter.drawImage(box, self.images[key])

    def draw_layer(self, painter, layer):
        self.draw_image(painter, layer.image, QRectF(layer.x, layer.y, layer.image.width, layer.image.height))

    def draw_target(self, painter, target, box, flip_x=False, flip_y=False, quarter_turns=0):
        painter.save()
        painter.translate(box.center())
        painter.scale(-1 if flip_x else 1, -1 if flip_y else 1)
        painter.rotate(90 * (quarter_turns % 4))
        width, height = (box.height(), box.width()) if quarter_turns % 2 else (box.width(), box.height())
        self.draw_image(painter, target.image, QRectF(-width / 2, -height / 2, width, height))
        painter.restore()

    def outline(self, painter, selection, source=False):
        path = self.path(selection)
        pen = QPen(QColor("#9cdbb0") if source else QColor("white"), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        pen = QPen(QColor("#111316"), 1)
        pen.setCosmetic(True)
        pen.setDashPattern([4, 4])
        pen.setDashOffset(self.ant_phase)
        painter.setPen(pen)
        painter.drawPath(path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 1 or self.session is not None)
        painter.fillRect(self.rect(), QColor("#18191c"))
        if not self.document:
            painter.setPen(QColor("#7e8593"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open an image or create a new canvas")
            return
        painter.setClipRect(QRectF(22, 22, self.width() - 22, self.height() - 22))
        origin = self.origin
        canvas_rect = QRectF(origin.x(), origin.y(), self.document.width * self.zoom, self.document.height * self.zoom)
        painter.fillRect(canvas_rect.adjusted(-5, -5, 6, 6), QColor("#101114"))
        painter.drawTiledPixmap(canvas_rect.toRect(), self.checker)
        painter.save()
        painter.translate(origin)
        painter.scale(self.zoom, self.zoom)
        painter.setClipRect(QRectF(0, 0, self.document.width, self.document.height), Qt.ClipOperation.IntersectClip)
        target = self.session.target if self.session else self.move_preview[0] if self.move_preview else None
        for layer in self.document.layers:
            if not layer.visible:
                continue
            if self.tools["text"].editing and layer.id == self.tools["text"].layer_id:
                continue
            if layer.id == self.document.active_id and self.stroke_preview:
                painter.save()
                unpainted = QPainterPath()
                unpainted.addRect(QRectF(0, 0, self.document.width, self.document.height))
                preview = self.stroke_preview
                unpainted.addRect(QRectF(preview.x, preview.y, preview.image.width, preview.image.height))
                unpainted.setFillRule(Qt.FillRule.OddEvenFill)
                painter.setClipPath(unpainted, Qt.ClipOperation.IntersectClip)
                self.draw_layer(painter, layer)
                painter.restore()
                self.draw_layer(painter, preview)
            elif layer.id == self.document.active_id and target:
                if target.selected:
                    self.draw_layer(painter, target.base)
                if self.session:
                    self.draw_target(painter, target, self.session.box, self.session.flip_x,
                                     self.session.flip_y, self.session.quarter_turns)
                else:
                    _, dx, dy = self.move_preview
                    a, b, c, d = target.bounds
                    self.draw_target(painter, target, QRectF(a + dx, b + dy, c - a, d - b))
            else:
                self.draw_layer(painter, layer)
            if layer.id == self.document.active_id and self.gradient_preview:
                start, end, stops = self.gradient_preview
                if start != end:
                    painter.save()
                    if self.document.selection:
                        painter.setClipPath(self.path(self.document.selection), Qt.ClipOperation.IntersectClip)
                    # Pillow samples integer coordinates; Qt samples pixel centers.
                    gradient = QLinearGradient(start + QPointF(.5, .5), end + QPointF(.5, .5))
                    gradient.setStops([(position, QColor(*color)) for position, color in stops])
                    painter.fillRect(QRectF(0, 0, self.document.width, self.document.height), gradient)
                    painter.restore()
        if self.patch_offset is not None and self.document.selection:
            dx, dy = self.patch_offset
            painter.save()
            painter.setClipPath(self.path(self.document.selection), Qt.ClipOperation.IntersectClip)
            painter.translate(-dx, -dy)
            self.draw_layer(painter, self.document.active)
            painter.restore()
        selection = self.preview_selection or self.document.selection
        if self.move_preview and selection:
            _, dx, dy = self.move_preview
            selection = selection.translated(dx, dy)
        if selection and not self.session:
            self.outline(painter, selection)
        if self.patch_offset is not None and selection:
            dx, dy = self.patch_offset
            self.outline(painter, selection.translated(dx, dy), source=True)
        painter.restore()
        if (self.tool_id in {"brush", "eraser"} and not self.session and not self.controller.busy
                and not self.panning and not self.space_held and (self.underMouse() or self.dragging)):
            radius = self.tools[self.tool_id].size * self.zoom / 2
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#111316"), 3))
            painter.drawEllipse(self.last_mouse, radius, radius)
            painter.setPen(QPen(QColor("white"), 1))
            painter.drawEllipse(self.last_mouse, radius, radius)
        # Handles may lie beyond the image, so they use workspace clipping.
        if self.session:
            painter.save()
            painter.translate(origin)
            painter.scale(self.zoom, self.zoom)
            pen = QPen(QColor("#a7bbff"), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.session.box)
            for point in self.session.handles().values():
                s = 7 / self.zoom
                painter.fillRect(QRectF(point.x() - s / 2, point.y() - s / 2, s, s), QColor("#d9e1ff"))
            painter.restore()
        if self.measurement:
            font = QFont(self.font())
            font.setPointSize(10)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(self.measurement) + 22
            x = max(25, min(self.width() - width - 10, self.last_mouse.x() + 18))
            y = max(25, min(self.height() - 34, self.last_mouse.y() + 18))
            painter.setPen(QColor("#545966"))
            painter.setBrush(QColor("#24272d"))
            painter.drawRoundedRect(QRectF(x, y, width, 28), 4, 4)
            painter.setPen(QColor("#f1f3f7"))
            painter.drawText(QRectF(x, y, width, 28), Qt.AlignmentFlag.AlignCenter, self.measurement)
        painter.setClipping(False)
        self.paint_rulers(painter)

    def paint_rulers(self, painter):
        painter.fillRect(0, 0, self.width(), 22, QColor("#23252a"))
        painter.fillRect(0, 0, 22, self.height(), QColor("#23252a"))
        painter.setFont(QFont("Sans Serif", 7))
        painter.setPen(QColor("#747982"))
        step = 10 ** math.floor(math.log10(max(1, 80 / self.zoom)))
        if step * self.zoom < 35:
            step *= 5
        origin = self.origin
        for vertical in (False, True):
            start = origin.y() if vertical else origin.x()
            extent = self.height() if vertical else self.width()
            first = math.floor((22 - start) / self.zoom / step) * step
            last = math.ceil((extent - start) / self.zoom / step) * step
            for value in range(first, last + step, step):
                coordinate = round(start + value * self.zoom)
                if coordinate < 22:
                    continue
                if vertical:
                    painter.drawLine(17, coordinate, 22, coordinate)
                    painter.save()
                    painter.translate(11, coordinate + 4)
                    painter.rotate(-90)
                    painter.drawText(0, 0, str(value))
                    painter.restore()
                else:
                    painter.drawLine(coordinate, 17, coordinate, 22)
                    painter.drawText(coordinate + 4, 12, str(value))
        painter.fillRect(0, 0, 22, 22, QColor("#292b30"))

    def begin_transform(self):
        if self.controller.busy or self.session or not self.document:
            return
        if self.tools["text"].editing and not self.tools["text"].commit():
            return
        self.cancel_interaction()
        try:
            self.session = TransformSession.begin(self.document)
            self.transform_changed.emit(True)
            self.setFocus()
            self.update()
        except Exception as error:
            self.controller.error.emit(str(error))

    def commit_transform(self):
        if not self.session:
            return
        session = self.session
        from ..text import render_text
        operation = lambda doc: transform(doc, session.target, session.pixel_box, session.flip_x,
                                         session.flip_y, session.quarter_turns, text_renderer=render_text)
        self.session = None
        self.transform_changed.emit(False)
        self.controller.run_background("Free Transform", operation)
        self.document_changed()

    def cancel_transform(self):
        self.session = None
        self.dragging = False
        self.transform_changed.emit(False)
        self.document_changed()

    def cancel_interaction(self):
        self.dragging = False
        self.pending_selection = None
        self.tools[self.tool_id].cancel()
        self.document_changed()

    def start_pending_selection(self, point, event):
        """Wait for image entry, retaining the original rectangle press anchor."""
        if self.pending_selection is None:
            return True
        anchor, start = self.pending_selection
        self.pending_selection = (anchor, QPointF(point))
        first, last = 0.0, 1.0
        for origin, delta, extent in (
            (start.x(), point.x() - start.x(), self.document.width),
            (start.y(), point.y() - start.y(), self.document.height),
        ):
            if delta == 0:
                if not 0 <= origin <= extent:
                    return False
                continue
            near, far = sorted((-origin / delta, (extent - origin) / delta))
            first, last = max(first, near), min(last, far)
            if first > last:
                return False
        entry = start + (point - start) * first
        self.pending_selection = None
        # A rectangle spans the original press and the current pointer. Using
        # its entry point instead can lose a strip when a corner drag crosses
        # a different image edge. Freeform outlines still follow their path.
        self.tools[self.tool_id].enter(anchor if self.tool_id == "rectangle" else entry, event)
        return True

    def mousePressEvent(self, event):
        self.setFocus()
        self.last_mouse = event.position()
        if self.controller.busy or not self.document:
            return
        if event.button() == Qt.MouseButton.MiddleButton or (self.space_held and event.button() == Qt.MouseButton.LeftButton):
            self.panning = True
            self.pan_start, self.original_pan = event.position(), QPointF(self.pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.pending_selection = None
        point = self.to_document(event.position())
        self.dragging = True
        if self.session:
            handle = next((name for name, p in self.session.handles().items()
                           if (p - point).manhattanLength() * self.zoom < 12), None)
            if handle or self.session.box.contains(point):
                self.session.start(point, handle or "move")
            else:
                self.dragging = False
            return
        if (not QRectF(0, 0, self.document.width, self.document.height).contains(point)
                and self.tool_id not in {"brush", "eraser"}):
            if self.tool_id in {"rectangle", "lasso", "patch"}:
                self.pending_selection = (QPointF(point), QPointF(point))
            else:
                self.dragging = False
            return
        try:
            self.tools[self.tool_id].press(point, event)
            self.update_tool_cursor()
        except Exception as error:
            self.cancel_interaction()
            self.controller.error.emit(str(error))

    def mouseMoveEvent(self, event):
        self.last_mouse = event.position()
        if not self.document:
            return
        if self.panning:
            self.pan = self.original_pan + event.position() - self.pan_start
            self.viewport_changed.emit()
            self.update()
            return
        point = self.to_document(event.position())
        if self.session:
            if self.dragging:
                self.session.update(point, bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                self.transform_changed.emit(True)
                self.update()
            else:
                cursors = dict(nw=Qt.CursorShape.SizeFDiagCursor, se=Qt.CursorShape.SizeFDiagCursor,
                               ne=Qt.CursorShape.SizeBDiagCursor, sw=Qt.CursorShape.SizeBDiagCursor,
                               n=Qt.CursorShape.SizeVerCursor, s=Qt.CursorShape.SizeVerCursor,
                               e=Qt.CursorShape.SizeHorCursor, w=Qt.CursorShape.SizeHorCursor)
                handle = next((name for name, p in self.session.handles().items()
                               if (p - point).manhattanLength() * self.zoom < 12), None)
                self.setCursor(cursors[handle] if handle else Qt.CursorShape.SizeAllCursor)
            return
        if self.dragging:
            try:
                if not self.start_pending_selection(point, event):
                    return
                self.tools[self.tool_id].move(point, event)
            except Exception as error:
                self.cancel_interaction()
                self.controller.error.emit(str(error))

        self.update_tool_cursor()
        if self.tool_id in {"brush", "eraser"}:
            self.update()

    def mouseReleaseEvent(self, event):
        if self.panning:
            self.panning = False
            self.update_tool_cursor()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self.dragging:
            return
        point = self.to_document(event.position())
        if self.session:
            self.session.update(point, bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            self.session.handle = None
            self.transform_changed.emit(True)
        else:
            try:
                if not self.start_pending_selection(point, event):
                    self.cancel_interaction()
                    return
                self.tools[self.tool_id].release(point, event)
            except Exception as error:
                self.controller.error.emit(str(error))
                self.tools[self.tool_id].cancel()
        self.dragging = False
        self.measurement_changed.emit("")
        self.document_changed()

    def wheelEvent(self, event):
        if self.controller.busy or not self.document:
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.zoom * 1.18 ** (event.angleDelta().y() / 120), event.position())
        else:
            delta = event.pixelDelta()
            if delta.isNull():
                delta = event.angleDelta() / 3
            self.pan += QPointF(delta)
            self.viewport_changed.emit()
            self.update()

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight)
                and self.tool_id in {"brush", "eraser"} and not self.controller.busy):
            tool = self.tools[self.tool_id]
            growing = event.key() == Qt.Key.Key_BracketRight
            value = max(tool.size + 1, round(tool.size * 1.25)) if growing else min(tool.size - 1, round(tool.size * .8))
            tool.size = max(1, min(2048, value))
            self.paint_settings_changed.emit()
            self.update()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape and self.tools["text"].editing:
            self.tools["text"].cancel()
        elif (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.tools["text"].editing
              and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.tools["text"].commit()
        elif event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_held = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            if self.session:
                self.cancel_transform()
            elif self.dragging:
                self.cancel_interaction()
            else:
                self.controller.set_selection(None)
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.session:
            self.commit_transform()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_held = False
            self.update_tool_cursor()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.space_held = False
        super().focusOutEvent(event)

    def contextMenuEvent(self, event):
        if self.session:
            menu = QMenu(self)
            horizontal = menu.addAction("Flip Horizontally")
            vertical = menu.addAction("Flip Vertically")
            clockwise = menu.addAction("Rotate 90° Clockwise")
            counterclockwise = menu.addAction("Rotate 90° Counterclockwise")
            menu.addSeparator()
            apply = menu.addAction("Apply Transform")
            cancel = menu.addAction("Cancel Transform")
            chosen = menu.exec(event.globalPos())
            if chosen == horizontal:
                self.session.flip_x = not self.session.flip_x
            elif chosen == vertical:
                self.session.flip_y = not self.session.flip_y
            elif chosen == clockwise:
                self.session.rotate(True)
                self.dragging = False
                self.transform_changed.emit(True)
            elif chosen == counterclockwise:
                self.session.rotate(False)
                self.dragging = False
                self.transform_changed.emit(True)
            elif chosen == apply:
                self.commit_transform()
            elif chosen == cancel:
                self.cancel_transform()
            self.update()
