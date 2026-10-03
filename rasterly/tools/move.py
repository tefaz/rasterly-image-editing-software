from .base import Tool
from ..operations import extract_target, move


class MoveTool(Tool):
    id = "move"
    name = "Move tool"
    hint = "Drag the active layer · A selection moves only its pixels · Space to pan"

    def press(self, point, event):
        self.start = point
        self.original = self.canvas.document
        self.target = extract_target(self.original)
        self.canvas.move_preview = (self.target, 0, 0)

    def move(self, point, event):
        if not self.canvas.dragging or getattr(self, "target", None) is None:
            return
        dx, dy = round(point.x() - self.start.x()), round(point.y() - self.start.y())
        self.canvas.move_preview = self.target, dx, dy
        self.canvas.update()

    def release(self, point, event):
        self.move(point, event)
        if self.canvas.move_preview:
            target, dx, dy = self.canvas.move_preview
            self.canvas.move_preview = None
            self.canvas.controller.apply("Move selection" if target.selected else "Move layer",
                                         lambda doc: move(doc, dx, dy, target))
        self.target = self.original = None
        self.canvas.update()

    def cancel(self):
        self.target = self.original = None
        self.canvas.move_preview = None
        super().cancel()
