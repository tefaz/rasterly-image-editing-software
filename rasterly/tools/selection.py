from .base import Tool
from ..selection import Selection


class RectangleTool(Tool):
    id = "rectangle"
    name = "Rectangular selection"
    hint = "Drag to select · Shift: add · Alt: subtract · Ctrl+D: deselect"

    def press(self, point, event):
        self.start = self.canvas.clamp(point)
        self.begin_selection(event)
        self.move(point, event)

    def move(self, point, event):
        if not self.canvas.dragging:
            return
        end = self.canvas.clamp(point)
        selection = Selection.rectangle(self.start.x(), self.start.y(), end.x(), end.y())
        self.preview_shape(selection)

    def release(self, point, event):
        self.move(point, event)
        selection = self.canvas.preview_selection
        self.finish_selection(selection)
        self.cancel()


class LassoTool(Tool):
    id = "lasso"
    name = "Lasso selection"
    hint = "Draw to select · Shift: add · Alt: subtract · Release to close"
    preview_kind = "lasso"

    def press(self, point, event):
        point = self.canvas.clamp(point)
        self.points = [(point.x(), point.y())]
        self.begin_selection(event)

    def move(self, point, event):
        if not self.canvas.dragging:
            return
        point = self.canvas.clamp(point)
        previous = self.points[-1]
        if (point.x() - previous[0]) ** 2 + (point.y() - previous[1]) ** 2 >= 0.5:
            self.points.append((point.x(), point.y()))
        if len(self.points) > 1:
            self.preview_shape(Selection(self.preview_kind, tuple(self.points)))

    def release(self, point, event):
        self.move(point, event)
        selection = Selection("lasso", tuple(self.points))
        self.preview_shape(selection)
        self.finish_selection(self.canvas.preview_selection)
        self.cancel()


class PatchTool(LassoTool):
    id = "patch"
    name = "Patch tool"
    hint = "Lasso an area, then drag inside the selection onto clean source texture"
    preview_kind = "trace"

    def enter(self, point, event):
        # An outside drag draws a fresh outline even if the entry touches an
        # existing selection; source positioning starts with an inside press.
        self.sourcing = False
        super().press(point, event)

    def press(self, point, event):
        selection = self.canvas.document.selection
        self.sourcing = bool(selection and self.canvas.selection_contains(point))
        if self.sourcing:
            self.start = point
            self.canvas.patch_offset = (0, 0)
        else:
            super().press(point, event)

    def move(self, point, event):
        if not self.canvas.dragging:
            return
        if self.sourcing:
            doc = self.canvas.document
            x1, y1, x2, y2 = doc.selection.clipped_bounds(doc.width, doc.height)
            dx = min(doc.width - x2, max(-x1, round(point.x() - self.start.x())))
            dy = min(doc.height - y2, max(-y1, round(point.y() - self.start.y())))
            self.canvas.patch_offset = dx, dy
            self.canvas.update()
        else:
            super().move(point, event)

    def release(self, point, event):
        if self.sourcing:
            self.move(point, event)
            offset = self.canvas.patch_offset
            self.canvas.patch_offset = None
            self.canvas.update()
            if offset != (0, 0):
                self.canvas.controller.heal(offset)
        else:
            super().release(point, event)

    def cancel(self):
        self.canvas.patch_offset = None
        super().cancel()
