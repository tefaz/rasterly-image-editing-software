"""A click-built straight-edged path, converted to a selection on request."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPen
from PyQt6.QtWidgets import QMenu

from .base import Tool
from ..model import PolygonPath
from ..selection import Selection


class PolygonTool(Tool):
    id = "polygon"
    name = "Polygon path tool"
    hint = "Click points · Alt-click: remove point · Click first point to close · Right-click: Create Selection · Ctrl+Z: toggle undo · Esc: cancel"

    def __init__(self, canvas):
        super().__init__(canvas)
        self.points = []
        self.closed = False
        self.document = None
        self.selection_mode = "replace"

    @property
    def has_area(self):
        if len(self.points) < 3:
            return False
        ax, ay = self.points[0]
        bx, by = self.points[1]
        return any((bx - ax) * (y - ay) != (by - ay) * (x - ax)
                   for x, y in self.points[2:])

    def near_start(self, point):
        if not self.points:
            return False
        x, y = self.points[0]
        return ((point.x() - x) ** 2 + (point.y() - y) ** 2) * self.canvas.zoom ** 2 <= 8 ** 2

    def vertex_at(self, point):
        if not self.points:
            return None
        index = min(range(len(self.points)), key=lambda index:
                    (self.points[index][0] - point.x()) ** 2 + (self.points[index][1] - point.y()) ** 2)
        x, y = self.points[index]
        if ((point.x() - x) ** 2 + (point.y() - y) ** 2) * self.canvas.zoom ** 2 <= 8 ** 2:
            return index
        return None

    def sync_document(self):
        doc = self.canvas.document
        path = doc.polygon_path if doc else None
        self.points = list(path.points) if path else []
        self.closed = path.closed if path else False
        self.selection_mode = path.selection_mode if path else "replace"
        self.document = doc if path else None

    def record(self, label):
        path = PolygonPath(tuple(self.points), self.closed, self.selection_mode) if self.points else None
        self.canvas.controller.set_polygon_path(path, label)

    def remove_point(self, index):
        self.points.pop(index)
        self.closed = self.closed and self.has_area
        self.record(f"Remove polygon point {index + 1}")

    def press(self, point, event):
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            index = self.vertex_at(point)
            if index is not None:
                self.remove_point(index)
                return
        if self.closed:
            return
        point = self.canvas.clamp(point)
        if self.points and self.has_area and self.near_start(point):
            self.closed = True
            self.record("Close polygon path")
        else:
            if not self.points:
                self.document = self.canvas.document
                modifiers = event.modifiers()
                self.selection_mode = ("subtract" if modifiers & Qt.KeyboardModifier.AltModifier else
                                       "add" if modifiers & Qt.KeyboardModifier.ShiftModifier else "replace")
            vertex = point.x(), point.y()
            if vertex not in (self.points[:1] + self.points[-1:]):
                self.points.append(vertex)
                self.record(f"Add polygon point {len(self.points)}")
        self.canvas.update()

    def paint(self, painter):
        if not self.points:
            return
        vertices = [self.canvas.to_screen(QPointF(x, y)) for x, y in self.points]
        path = QPainterPath(vertices[0])
        for vertex in vertices[1:]:
            path.lineTo(vertex)
        hover = self.canvas.to_document(self.canvas.last_mouse)
        closing = not self.closed and self.has_area and self.near_start(hover)
        if self.closed:
            path.closeSubpath()
        elif self.canvas.underMouse() or self.canvas.dragging:
            path.lineTo(vertices[0] if closing else self.canvas.to_screen(self.canvas.clamp(hover)))
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#111316"), 3))
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#a7bbf7"), 1))
        painter.drawPath(path)
        for index, vertex in enumerate(vertices):
            painter.setPen(QPen(QColor("#111316"), 1))
            painter.setBrush(QColor("#9cdbb0") if index == 0 and closing else QColor("#d9e1ff"))
            radius = 4 if index == 0 else 3
            painter.drawRect(QRectF(vertex.x() - radius, vertex.y() - radius, radius * 2, radius * 2))
        painter.restore()

    def create_selection(self):
        if (not self.closed or not self.has_area or self.canvas.controller.busy
                or self.document is not self.canvas.document):
            return
        selection = Selection("lasso", tuple(self.points))
        original = self.document.selection
        mode = self.selection_mode
        if mode == "add" and original:
            selection = original.united(selection)
        elif mode == "subtract":
            selection = original.subtracted(selection) if original else None
        label = {"replace": "Polygon selection", "add": "Add to selection", "subtract": "Subtract from selection"}[mode]
        self.canvas.controller.set_selection(selection, label)

    def context_menu(self, event):
        if not self.points:
            return
        menu = QMenu(self.canvas)
        create = menu.addAction("Create Selection")
        create.setEnabled(self.closed and self.has_area and not self.canvas.controller.busy)
        cancel = menu.addAction("Cancel Path")
        chosen = menu.exec(event.globalPos())
        if chosen == create:
            self.create_selection()
        elif chosen == cancel:
            self.canvas.cancel_interaction()
        event.accept()

    def key_press(self, event):
        if not self.points:
            return False
        if event.key() == Qt.Key.Key_Escape:
            self.canvas.cancel_interaction()
        elif event.key() == Qt.Key.Key_Backspace:
            self.remove_point(len(self.points) - 1)
        else:
            return False
        return True

    def cancel(self):
        if self.canvas.document and self.canvas.document.polygon_path is not None:
            self.canvas.controller.set_polygon_path(None, "Cancel polygon path")
        self.sync_document()
        super().cancel()
