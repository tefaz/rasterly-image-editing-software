import math

from PyQt6.QtCore import QPointF, Qt

from .base import Tool
from ..fills import fill_bounds, paint_bucket, linear_gradient


class BucketTool(Tool):
    id = "bucket"
    name = "Paint Bucket"
    hint = "Click to fill connected pixels with the foreground color"

    def __init__(self, canvas):
        super().__init__(canvas)
        self.tolerance = 32

    def press(self, point, event):
        fill_bounds(self.canvas.document)
        color = self.canvas.foreground_color()
        position = (point.x(), point.y())
        tolerance = self.tolerance
        self.canvas.controller.run_background("Paint bucket", lambda doc:
            paint_bucket(doc, position, color, tolerance))


class GradientTool(Tool):
    id = "gradient"
    name = "Gradient"
    hint = "Drag to draw a gradient · Shift: constrain angle · Esc: cancel"

    def __init__(self, canvas):
        super().__init__(canvas)
        self.transparent = False
        self.stops = None
        self.start = None

    def press(self, point, event):
        fill_bounds(self.canvas.document)
        if self.canvas.document.selection and not self.canvas.selection_contains(point):
            return
        self.start = QPointF(round(point.x()), round(point.y()))
        color = self.canvas.foreground_color()
        self.drag_stops = self.stops or ((0.0, color),
            (1.0, (*color[:3], 0) if self.transparent else (255, 255, 255, 255)))
        self.update_preview(point, event)

    def update_preview(self, point, event):
        end = QPointF(round(point.x()), round(point.y()))
        delta = end - self.start
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and not delta.isNull():
            angle = round(math.atan2(delta.y(), delta.x()) / (math.pi / 4)) * math.pi / 4
            length = math.hypot(delta.x(), delta.y())
            end = self.start + QPointF(math.cos(angle) * length, math.sin(angle) * length)
        self.canvas.gradient_preview = (self.start, end, self.drag_stops)
        self.canvas.update()

    def move(self, point, event):
        if self.start is not None:
            self.update_preview(point, event)

    def release(self, point, event):
        if self.start is None:
            return
        self.update_preview(point, event)
        start, end, stops = self.canvas.gradient_preview
        self.cancel()
        if math.hypot(end.x() - start.x(), end.y() - start.y()) < 1:
            return
        a, b = (start.x(), start.y()), (end.x(), end.y())
        self.canvas.controller.run_background("Gradient", lambda doc:
            linear_gradient(doc, a, b, stops=stops))

    def cancel(self):
        self.start = None
        self.canvas.gradient_preview = None
        super().cancel()
