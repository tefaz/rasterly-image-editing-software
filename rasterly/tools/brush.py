from .base import Tool
from ..painting import PaintStroke


class BrushTool(Tool):
    id = "brush"
    name = "Brush"
    hint = "Drag to paint · [ / ]: brush size · Esc: cancel stroke"
    erase = False

    def __init__(self, canvas):
        super().__init__(canvas)
        self.size, self.opacity, self.hardness = 24, 100, 100
        self.stroke = None
        self.committing = False
        self.canvas.controller.busy_changed.connect(self.commit_finished)

    def commit_finished(self, busy, label):
        if not busy and self.committing:
            self.cancel()

    def press(self, point, event):
        self.stroke = PaintStroke(self.canvas.document, self.size, self.opacity, self.hardness,
                                  self.canvas.foreground_color(), self.erase)
        self.move(point, event)

    def move(self, point, event):
        if self.stroke is None:
            return
        if self.canvas.document is not self.stroke.document:
            self.canvas.cancel_interaction()
            return
        self.stroke.size = self.size
        changed = self.stroke.add((point.x(), point.y()))
        self.canvas.stroke_preview = self.stroke.preview
        if changed:
            self.canvas.update_stroke_image(self.stroke)
        self.canvas.update()

    def release(self, point, event):
        self.move(point, event)
        stroke = self.stroke
        if stroke is not None and stroke.preview is not None:
            self.committing = True
            self.canvas.controller.run_background("Eraser stroke" if self.erase else "Brush stroke",
                                                  lambda doc: stroke.finish(), quiet=True)
        else:
            self.cancel()

    def cancel(self):
        self.stroke = None
        self.committing = False
        self.canvas.stroke_preview = None
        self.canvas.stroke_image = None
        super().cancel()


class EraserTool(BrushTool):
    id = "eraser"
    name = "Eraser"
    hint = "Drag to erase to transparency · [ / ]: size · Esc: cancel stroke"
    erase = True
