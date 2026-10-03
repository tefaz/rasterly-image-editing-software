"""Immutable selection geometry in document pixels, independent of the viewport.

Boolean regions retain their original shapes so disjoint areas and holes remain
editable through translation and transforms. Masks are rasterized on demand.
"""
from dataclasses import dataclass
from functools import cached_property
import math
from PIL import Image, ImageDraw, ImageChops

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Selection:
    kind: str
    points: tuple[tuple[float, float], ...]
    parts: tuple["Selection", ...] = ()

    @classmethod
    def rectangle(cls, x1, y1, x2, y2):
        return cls("rectangle", ((min(x1, x2), min(y1, y2)),
                                  (max(x1, x2), max(y1, y2))))

    @cached_property
    def bounds(self) -> Box:
        if self.kind == "union":
            boxes = [part.bounds for part in self.parts if part.valid]
            if not boxes:
                return (0, 0, 0, 0)
            return (min(box[0] for box in boxes), min(box[1] for box in boxes),
                    max(box[2] for box in boxes), max(box[3] for box in boxes))
        if self.kind == "subtract":
            original = self.parts[0].bounds
            remaining = self.mask(original).getbbox()
            if remaining is None:
                return (0, 0, 0, 0)
            a, b, c, d = remaining
            return (a + original[0], b + original[1], c + original[0], d + original[1])
        if not self.points:
            return (0, 0, 0, 0)
        xs, ys = zip(*self.points)
        return (math.floor(min(xs)), math.floor(min(ys)),
                math.ceil(max(xs)), math.ceil(max(ys)))

    @property
    def valid(self):
        x1, y1, x2, y2 = self.bounds
        return x2 > x1 and y2 > y1 and (self.kind in {"rectangle", "union", "subtract"} or len(self.points) >= 3)

    def united(self, other):
        """Add a region without toggling pixels where selections overlap."""
        if not other.valid:
            return self
        if not self.valid:
            return other
        parts = self.parts if self.kind == "union" else (self,)
        return Selection("union", (), parts + (other,))

    def subtracted(self, other):
        """Remove a region, retaining holes and any remaining separate islands."""
        if not other.valid or not self.valid:
            return self
        return Selection("subtract", (), (self, other))

    def clipped_bounds(self, width, height) -> Box:
        x1, y1, x2, y2 = self.bounds
        return max(0, x1), max(0, y1), min(width, x2), min(height, y2)

    def mask(self, box: Box) -> Image.Image:
        """Rasterize only the requested region; rectangles use exclusive end bounds."""
        x1, y1, x2, y2 = box
        if self.kind in {"union", "subtract"}:
            result = self.parts[0].mask(box)
            for part in self.parts[1:]:
                operand = part.mask(box)
                result = ImageChops.lighter(result, operand) if self.kind == "union" else ImageChops.subtract(result, operand)
            return result
        mask = Image.new("L", (max(0, x2 - x1), max(0, y2 - y1)))
        if not mask.width or not mask.height:
            return mask
        draw = ImageDraw.Draw(mask)
        if self.kind == "rectangle":
            a, b, c, d = self.bounds
            if c > a and d > b:
                draw.rectangle((a - x1, b - y1, c - x1 - 1, d - y1 - 1), fill=255)
        elif len(self.points) >= 3:
            draw.polygon([(x - x1, y - y1) for x, y in self.points], fill=255)
        return mask

    def translated(self, dx, dy):
        return Selection(self.kind, tuple((x + dx, y + dy) for x, y in self.points),
                         tuple(part.translated(dx, dy) for part in self.parts))

    def transformed(self, old_box, new_box, flip_x=False, flip_y=False, quarter_turns=0):
        if self.parts:
            return Selection(self.kind, (), tuple(part.transformed(old_box, new_box, flip_x, flip_y, quarter_turns)
                                                  for part in self.parts))
        a, b, c, d = old_box
        x1, y1, x2, y2 = new_box
        result = []
        for x, y in self.points:
            u, v = (x - a) / (c - a), (y - b) / (d - b)
            for _ in range(quarter_turns % 4):
                u, v = 1 - v, u
            if flip_x:
                u = 1 - u
            if flip_y:
                v = 1 - v
            result.append((x1 + u * (x2 - x1), y1 + v * (y2 - y1)))
        return Selection(self.kind, tuple(result))
