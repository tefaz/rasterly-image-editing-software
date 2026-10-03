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
        previous = self.canvas.stroke_preview
        if previous:
            self.canvas.images.pop(id(previous.image), None)
        self.stroke.size = self.size
        self.stroke.add((point.x(), point.y()))
        self.canvas.stroke_preview = self.stroke.preview
        self.canvas.update()

    def release(self, point, event):
        self.move(point, event)
        stroke = self.stroke
        self.cancel()
        if stroke is not None and stroke.preview is not None:
            self.canvas.controller.run_background("Eraser stroke" if self.erase else "Brush stroke",
                                                  lambda doc: stroke.finish())

    def cancel(self):
        if self.canvas.stroke_preview:
            self.canvas.images.pop(id(self.canvas.stroke_preview.image), None)
        self.stroke = None
        self.canvas.stroke_preview = None
        super().cancel()


class EraserTool(BrushTool):
    id = "eraser"
    name = "Eraser"
    hint = "Drag to erase to transparency · [ / ]: size · Esc: cancel stroke"
    erase = True
