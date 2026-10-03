"""An inline gradient strip with clickable and draggable color stops."""
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QColorDialog, QMenu, QWidget

from ..gradient import sample_gradient


@dataclass(eq=False)
class ColorStop:
    position: float
    color: tuple


class GradientEditor(QWidget):
    stops_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(210, 34)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Gradient color stops")
        self.setToolTip("Click a stop to change its color · Click the strip to add a stop · "
                        "Drag stops to move them · Delete removes the selected stop")
        self._stops = []
        self.selected = None
        self.pressed = None
        self.preset = 0
        self.set_preset(0, QColor("black"))

    @property
    def stops(self):
        return tuple((stop.position, stop.color) for stop in sorted(self._stops, key=lambda stop: stop.position))

    @property
    def bar(self):
        return QRectF(8, 1, self.width() - 16, 17)

    def stop_point(self, stop):
        return QPointF(self.bar.left() + stop.position * self.bar.width(), 28)

    def position_at(self, point):
        return max(0.0, min(1.0, (point.x() - self.bar.left()) / self.bar.width()))

    def stop_at(self, point):
        if not 0 <= point.y() < self.height():
            return None
        # Prefer the selected stop when closely spaced handles overlap.
        candidates = sorted(self._stops, key=lambda stop:
            (abs(self.stop_point(stop).x() - point.x()), stop is not self.selected))
        return candidates[0] if candidates and abs(self.stop_point(candidates[0]).x() - point.x()) <= 7 else None

    def emit_stops(self, custom=True):
        if custom:
            self.preset = None
        self.stops_changed.emit(self.stops)
        self.update()

    def set_preset(self, index, foreground):
        color = foreground.getRgb()
        end = (*color[:3], 0) if index == 1 else (255, 255, 255, 255)
        self.preset = index
        self._stops = [ColorStop(0.0, color), ColorStop(1.0, end)]
        self.selected = self._stops[0]
        self.pressed = None
        self.emit_stops(custom=False)

    def update_foreground(self, color):
        if self.preset is not None and self._stops[0].color != color.getRgb():
            self.set_preset(self.preset, color)

    def choose_color(self, stop):
        color = QColorDialog.getColor(QColor(*stop.color), self, "Gradient stop color",
                                      QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid() and color.getRgb() != stop.color:
            stop.color = color.getRgb()
            self.emit_stops()

    def move_stop(self, stop, position):
        ordered = sorted(self._stops, key=lambda stop: stop.position)
        index = ordered.index(stop)
        left = ordered[index - 1].position + .001 if index else 0.0
        right = ordered[index + 1].position - .001 if index < len(ordered) - 1 else 1.0
        position = max(left, min(right, position))
        if stop.position != position:
            stop.position = position
            self.emit_stops()

    def remove_selected(self):
        if self.selected is not None and len(self._stops) > 2:
            self.pressed = None
            self._stops.remove(self.selected)
            self.selected = self._stops[0]
            self.emit_stops()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        stop = self.stop_at(event.position())
        if stop is None and self.bar.contains(event.position()):
            position = self.position_at(event.position())
            color = tuple(int(channel) for channel in sample_gradient(self.stops, position))
            stop = ColorStop(position, color)
            self._stops.append(stop)
            self.emit_stops()
        if stop is not None:
            self.selected = stop
            self.pressed = (QPointF(event.position()), stop.position, self.preset)
            self.moved = False
            self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        if self.pressed is not None:
            if (event.position() - self.pressed[0]).manhattanLength() >= 3:
                self.moved = True
            if self.moved:
                self.move_stop(self.selected, self.position_at(event.position()))
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.stop_at(event.position())
                           else Qt.CursorShape.CrossCursor if self.bar.contains(event.position())
                           else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.pressed is not None:
            moved = self.moved or (event.position() - self.pressed[0]).manhattanLength() >= 3
            self.pressed = None
            if moved:
                self.move_stop(self.selected, self.position_at(event.position()))
            else:
                self.choose_color(self.selected)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        stop = self.stop_at(QPointF(event.pos()))
        if stop is None:
            return
        self.selected = stop
        self.update()
        menu = QMenu(self)
        menu.addAction("Change Color…", lambda: self.choose_color(stop))
        remove = menu.addAction("Remove Stop", self.remove_selected)
        remove.setEnabled(len(self._stops) > 2)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.pressed is not None:
            _, position, preset = self.pressed
            self.selected.position = position
            self.preset = preset
            self.pressed = None
            self.emit_stops(custom=False)
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_selected()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.choose_color(self.selected)
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            direction = -1 if event.key() == Qt.Key.Key_Left else 1
            step = .001 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else .01
            self.move_stop(self.selected, self.selected.position + direction * step)
        else:
            return super().keyPressEvent(event)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        bar = self.bar
        painter.save()
        painter.setClipRect(bar)
        for y in range(0, 20, 6):
            for x in range(0, self.width(), 6):
                painter.fillRect(x, y, 6, 6, QColor("#777c85" if (x // 6 + y // 6) % 2 else "#b4bac3"))
        gradient = QLinearGradient(bar.topLeft(), bar.topRight())
        gradient.setStops([(position, QColor(*color)) for position, color in self.stops])
        painter.fillRect(bar, gradient)
        painter.restore()
        painter.setPen(QPen(QColor("#737d8e"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(bar)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ordered = [stop for stop in self._stops if stop is not self.selected] + [self.selected]
        for stop in ordered:
            x = self.stop_point(stop).x()
            painter.setPen(QPen(QColor("#dce5ff" if stop is self.selected else "#727e92"), 1))
            painter.setBrush(QColor(*stop.color[:3]))
            painter.drawPolygon(QPolygonF([QPointF(x, 19), QPointF(x - 4, 23), QPointF(x + 4, 23)]))
            painter.drawRect(QRectF(x - 5, 23, 10, 9))
