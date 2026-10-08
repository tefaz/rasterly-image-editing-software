"""Immutable document snapshots. Pixel buffers are shared until an edit replaces them.

Treat Layer.image as read-only: every operation allocates a new image. This makes
undo exact without copying every layer on each action.
"""
from dataclasses import dataclass, field, replace
from itertools import count
from uuid import uuid4
from PIL import Image
from .selection import Selection

_revisions = count(1)
MAX_SIDE = 32768
MAX_PIXELS = 100_000_000


def validate_size(width, height):
    if not 1 <= width <= MAX_SIDE or not 1 <= height <= MAX_SIDE:
        raise ValueError(f"Dimensions must be between 1 and {MAX_SIDE:,} pixels.")
    if width * height > MAX_PIXELS:
        raise ValueError("This image exceeds the 100 megapixel document limit.")


@dataclass(frozen=True)
class TextData:
    content: str = ""
    family: str = "Sans Serif"
    size: int = 48  # document pixels, independent of display DPI and zoom
    color: tuple[int, int, int, int] = (0, 0, 0, 255)
    bold: bool = False
    italic: bool = False
    alignment: str = "left"
    box_size: tuple[int, int] | None = None  # fit the text layout into a transformed layer
    quarter_turns: int = 0
    flip_x: bool = False
    flip_y: bool = False

    def __post_init__(self):
        if not isinstance(self.content, str) or len(self.content) > 10000:
            raise ValueError("Text is limited to 10,000 characters.")
        if not isinstance(self.family, str) or not self.family or len(self.family) > 256:
            raise ValueError("Invalid font family.")
        if not isinstance(self.size, int) or not 1 <= self.size <= 2048:
            raise ValueError("Font size must be between 1 and 2,048 pixels.")
        if self.alignment not in {"left", "center", "right"}:
            raise ValueError("Invalid text alignment.")
        if len(self.color) != 4 or any(not isinstance(c, int) or not 0 <= c <= 255 for c in self.color):
            raise ValueError("Invalid text color.")
        object.__setattr__(self, "color", tuple(self.color))
        if self.box_size is not None:
            if len(self.box_size) != 2 or any(not isinstance(side, int) for side in self.box_size):
                raise ValueError("Invalid text box size.")
            validate_size(*self.box_size)
            object.__setattr__(self, "box_size", tuple(self.box_size))
        if not isinstance(self.quarter_turns, int) or not 0 <= self.quarter_turns < 4:
            raise ValueError("Invalid text rotation.")


@dataclass(frozen=True)
class Layer:
    name: str
    image: Image.Image = field(repr=False, compare=False)
    x: int = 0
    y: int = 0
    visible: bool = True
    id: str = field(default_factory=lambda: uuid4().hex)
    text: TextData | None = None
    group_id: str | None = None

    @property
    def bounds(self):
        return self.x, self.y, self.x + self.image.width, self.y + self.image.height


@dataclass(frozen=True)
class LayerGroup:
    name: str = "Group"
    id: str = field(default_factory=lambda: uuid4().hex)
    collapsed: bool = False
    visible: bool = True


@dataclass(frozen=True)
class PolygonPath:
    points: tuple[tuple[float, float], ...]
    closed: bool = False
    selection_mode: str = "replace"


@dataclass(frozen=True)
class Document:
    width: int
    height: int
    layers: tuple[Layer, ...]  # bottom to top
    active_id: str
    selection: Selection | None = None
    revision: int = field(default_factory=lambda: next(_revisions))
    selected_ids: frozenset[str] = field(default_factory=frozenset)
    groups: tuple[LayerGroup, ...] = ()
    polygon_path: PolygonPath | None = None  # session state, like selections

    def __post_init__(self):
        ids = {layer.id for layer in self.layers}
        group_ids = {group.id for group in self.groups}
        if len(group_ids) != len(self.groups) or group_ids & ids:
            raise ValueError("Duplicate layer group identifiers.")
        used = {layer.group_id for layer in self.layers if layer.group_id is not None}
        if not used <= group_ids:
            raise ValueError("Invalid layer group membership.")
        for group_id in used:
            positions = [i for i, layer in enumerate(self.layers) if layer.group_id == group_id]
            if positions[-1] - positions[0] + 1 != len(positions):
                raise ValueError("Keep a group's layers together in the stacking order.")
        object.__setattr__(self, "groups", tuple(group for group in self.groups if group.id in used))
        object.__setattr__(self, "selected_ids", frozenset((self.selected_ids & ids) | {self.active_id}))

    @classmethod
    def new(cls, width=1920, height=1080):
        validate_size(width, height)
        layer = Layer("Background", Image.new("RGBA", (width, height), "white"))
        return cls(width, height, (layer,), layer.id)

    @classmethod
    def from_image(cls, image, name="Background"):
        validate_size(*image.size)
        layer = Layer(name, image.convert("RGBA"))
        return cls(image.width, image.height, (layer,), layer.id)

    @property
    def active(self):
        return next(layer for layer in self.layers if layer.id == self.active_id)

    def layer_visible(self, layer):
        return layer.visible and all(group.visible for group in self.groups if group.id == layer.group_id)

    def edited(self, **kwargs):
        kwargs.setdefault("polygon_path", None)
        if "active_id" in kwargs and kwargs["active_id"] != self.active_id and "selected_ids" not in kwargs:
            kwargs["selected_ids"] = frozenset({kwargs["active_id"]})
        return replace(self, revision=next(_revisions), **kwargs)

    def with_layer(self, layer, **kwargs):
        return self.edited(layers=tuple(layer if l.id == layer.id else l for l in self.layers), **kwargs)


def layer_on_canvas(layer, width, height):
    result = Image.new("RGBA", (width, height))
    result.alpha_composite(layer.image, (layer.x, layer.y))
    return result


def composite(document):
    result = Image.new("RGBA", (document.width, document.height))
    for layer in document.layers:
        if document.layer_visible(layer):
            result.alpha_composite(layer.image, (layer.x, layer.y))
    return result
