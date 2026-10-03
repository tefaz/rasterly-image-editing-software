"""Editable transform geometry; resampling occurs only on commit."""
from dataclasses import dataclass
from PyQt6.QtCore import QPointF, QRectF
from ..operations import extract_target


@dataclass
class TransformSession:
    target: object
    box: QRectF
    flip_x: bool = False
    flip_y: bool = False
    quarter_turns: int = 0
    handle: str | None = None
    drag_start: QPointF | None = None
    drag_box: QRectF | None = None

    @classmethod
    def begin(cls, document):
        target = extract_target(document)
        a, b, c, d = target.bounds
        return cls(target, QRectF(a, b, c - a, d - b))

    def handles(self):
        b = self.box
        return dict(nw=b.topLeft(), n=QPointF(b.center().x(), b.top()), ne=b.topRight(),
                    e=QPointF(b.right(), b.center().y()), se=b.bottomRight(),
                    s=QPointF(b.center().x(), b.bottom()), sw=b.bottomLeft(),
                    w=QPointF(b.left(), b.center().y()))

    def rotate(self, clockwise=True):
        center = self.box.center()
        width, height = self.box.height(), self.box.width()
        self.box = QRectF(center.x() - width / 2, center.y() - height / 2, width, height)
        self.quarter_turns = (self.quarter_turns + (1 if clockwise else -1)) % 4
        # Rotation acts on the current preview; flip axes rotate with it.
        self.flip_x, self.flip_y = self.flip_y, self.flip_x
        self.handle = self.drag_start = self.drag_box = None

    def start(self, point, handle):
        self.handle, self.drag_start, self.drag_box = handle, point, QRectF(self.box)

    def update(self, point, lock_aspect):
        if not self.handle:
            return
        box = QRectF(self.drag_box)
        delta = point - self.drag_start
        if self.handle == "move":
            self.box = box.translated(delta)
            return
        if "w" in self.handle:
            box.setLeft(min(box.right() - 1, box.left() + delta.x()))
        if "e" in self.handle:
            box.setRight(max(box.left() + 1, box.right() + delta.x()))
        if "n" in self.handle:
            box.setTop(min(box.bottom() - 1, box.top() + delta.y()))
        if "s" in self.handle:
            box.setBottom(max(box.top() + 1, box.bottom() + delta.y()))
        if lock_aspect:
            original = self.target.bounds
            ratio = (original[2] - original[0]) / (original[3] - original[1])
            if self.quarter_turns % 2:
                ratio = 1 / ratio
            horizontal = "e" in self.handle or "w" in self.handle
            vertical = "n" in self.handle or "s" in self.handle
            width, height = box.width(), box.height()
            if horizontal and (not vertical or abs(delta.x()) >= abs(delta.y()) * ratio):
                height = width / ratio
            else:
                width = height * ratio
            if "w" in self.handle:
                box.setLeft(box.right() - width)
            elif "e" in self.handle:
                box.setRight(box.left() + width)
            else:
                box.setLeft(self.drag_box.center().x() - width / 2)
                box.setRight(self.drag_box.center().x() + width / 2)
            if "n" in self.handle:
                box.setTop(box.bottom() - height)
            elif "s" in self.handle:
                box.setBottom(box.top() + height)
            else:
                box.setTop(self.drag_box.center().y() - height / 2)
                box.setBottom(self.drag_box.center().y() + height / 2)
        self.box = box

    @property
    def pixel_box(self):
        b = self.box
        x, y = round(b.left()), round(b.top())
        return x, y, x + max(1, round(b.width())), y + max(1, round(b.height()))
