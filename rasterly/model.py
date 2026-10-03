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
class Layer:
    name: str
    image: Image.Image = field(repr=False, compare=False)
    x: int = 0
    y: int = 0
    visible: bool = True
    id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def bounds(self):
        return self.x, self.y, self.x + self.image.width, self.y + self.image.height


@dataclass(frozen=True)
class Document:
    width: int
    height: int
    layers: tuple[Layer, ...]  # bottom to top
    active_id: str
    selection: Selection | None = None
    revision: int = field(default_factory=lambda: next(_revisions))
    selected_ids: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self):
        ids = {layer.id for layer in self.layers}
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

    def edited(self, **kwargs):
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
        if layer.visible:
            result.alpha_composite(layer.image, (layer.x, layer.y))
    return result
