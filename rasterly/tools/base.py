from PyQt6.QtCore import Qt
from ..selection import Selection


class Tool:
    id = ""
    name = ""
    hint = ""

    def __init__(self, canvas):
        self.canvas = canvas

    def press(self, point, event):
        pass

    def enter(self, point, event):
        """Begin a drag that first reaches the image after an outside press."""
        self.press(point, event)

    def move(self, point, event):
        pass

    def release(self, point, event):
        pass

    def begin_selection(self, event):
        self.previous_selection = self.canvas.document.selection
        self.drawing_selection = True
        self.selection_mode = "replace"
        if self.id in {"rectangle", "lasso"}:
            modifiers = event.modifiers()
            if modifiers & Qt.KeyboardModifier.AltModifier:
                self.selection_mode = "subtract"
            elif modifiers & Qt.KeyboardModifier.ShiftModifier:
                self.selection_mode = "add"
        if self.selection_mode == "replace":
            # Hide the old outline without changing the document or its history.
            self.canvas.preview_selection = Selection("empty", ())
            self.canvas.update()

    def preview_shape(self, shape):
        original = self.previous_selection
        if self.selection_mode == "add":
            preview = original.united(shape) if original else shape
        elif self.selection_mode == "subtract":
            preview = original.subtracted(shape) if original else Selection("empty", ())
        else:
            preview = shape
        self.canvas.preview_selection = preview
        self.canvas.measure(shape)

    def finish_selection(self, selection):
        self.drawing_selection = False
        label = {"add": "Add to selection", "subtract": "Subtract from selection"}.get(
            self.selection_mode, {
                "rectangle": "Rectangle selection", "lasso": "Lasso selection",
                "patch": "Patch selection"
            }.get(self.id, "Selection"))
        self.canvas.controller.set_selection(selection, label)

    def cancel(self):
        if getattr(self, "drawing_selection", False):
            self.drawing_selection = False
        self.canvas.preview_selection = None
        self.canvas.measurement = None
        self.previous_selection = None
        self.canvas.update()
