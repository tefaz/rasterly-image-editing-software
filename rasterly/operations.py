"""Document commands. No viewport state or Qt dependencies."""
from dataclasses import dataclass, replace
from PIL import Image, ImageChops, ImageOps
from .model import Document, Layer, validate_size


def add_layer(doc):
    layer = Layer(f"Layer {len(doc.layers) + 1}",
                  Image.new("RGBA", (doc.width, doc.height), (0, 0, 0, 0)), group_id=doc.active.group_id)
    i = next(i for i, l in enumerate(doc.layers) if l.id == doc.active_id) + 1
    return doc.edited(layers=doc.layers[:i] + (layer,) + doc.layers[i:], active_id=layer.id)


def delete_layer(doc):
    if len(doc.layers) == 1:
        raise ValueError("Keep at least one layer in the document.")
    index = next(i for i, layer in enumerate(doc.layers) if layer.id == doc.active_id)
    layers = tuple(layer for layer in doc.layers if layer.id != doc.active_id)
    return doc.edited(layers=layers, active_id=layers[min(index, len(layers) - 1)].id)


def duplicate_layer(doc):
    original = doc.active
    layer = Layer(original.name + " copy", original.image, original.x, original.y, original.visible,
                  text=original.text, group_id=original.group_id)
    i = doc.layers.index(original) + 1
    return doc.edited(layers=doc.layers[:i] + (layer,) + doc.layers[i:], active_id=layer.id)


def set_text_layer(doc, data, image, position, layer_id=None):
    """Commit pre-rendered text without adding Qt dependencies to commands."""
    if not data.content.strip() and layer_id is None:
        return doc
    validate_size(*image.size)
    if layer_id is not None:
        layer = next(layer for layer in doc.layers if layer.id == layer_id)
        if layer.text == data and (layer.x, layer.y) == position:
            return doc
        return doc.with_layer(replace(layer, image=image, text=data, x=position[0], y=position[1]))
    name = " ".join(data.content.split())[:40]
    layer = Layer(name, image, *position, text=data, group_id=doc.active.group_id)
    i = next(i for i, layer in enumerate(doc.layers) if layer.id == doc.active_id) + 1
    return doc.edited(layers=doc.layers[:i] + (layer,) + doc.layers[i:], active_id=layer.id, selection=None)


def rasterize_text(doc):
    return doc.with_layer(replace(doc.active, text=None)) if doc.active.text else doc


def require_pixels(layer):
    if layer.text is not None:
        raise ValueError("Use Layer → Rasterize Text Layer before editing this layer's pixels.")


def copy_selection(doc):
    """Copy active-layer pixels at full resolution, retaining irregular alpha."""
    if not doc.active.visible:
        raise ValueError("Show the active layer before copying its pixels.")
    x1, y1, x2, y2 = require_selection(doc)
    layer = doc.active
    image = layer.image.crop((x1 - layer.x, y1 - layer.y, x2 - layer.x, y2 - layer.y))
    image.putalpha(ImageChops.multiply(image.getchannel("A"), doc.selection.mask((x1, y1, x2, y2))))
    if image.getbbox() is None:
        raise ValueError("There are no active-layer pixels inside this selection.")
    return image, (x1, y1)


def paste_layer(doc, image, position=None):
    validate_size(*image.size)
    x, y = position if position is not None else ((doc.width - image.width) // 2, (doc.height - image.height) // 2)
    layer = Layer("Pasted selection", image.convert("RGBA"), x, y, group_id=doc.active.group_id)
    i = next(i for i, l in enumerate(doc.layers) if l.id == doc.active_id) + 1
    return doc.edited(layers=doc.layers[:i] + (layer,) + doc.layers[i:], active_id=layer.id, selection=None)


def reorder_layers(doc, ids):
    if set(ids) != {l.id for l in doc.layers} or len(ids) != len(doc.layers):
        raise ValueError("Invalid layer order.")
    lookup = {layer.id: layer for layer in doc.layers}
    return doc.edited(layers=tuple(lookup[id] for id in ids))


def merge_layers(doc):
    """Flatten selected layers at the highest selected stacking position.

    Preserve full layer extents, including pixels outside the canvas. Hidden
    layers do not contribute to a visible merge; an entirely hidden group is
    composited internally and remains hidden.
    """
    selected = [layer for layer in doc.layers if layer.id in doc.selected_ids]
    if len(selected) < 2:
        raise ValueError("Select at least two layers to merge.")
    left = min(layer.x for layer in selected)
    top = min(layer.y for layer in selected)
    right = max(layer.bounds[2] for layer in selected)
    bottom = max(layer.bounds[3] for layer in selected)
    validate_size(right - left, bottom - top)
    image = Image.new("RGBA", (right - left, bottom - top))
    visible = any(layer.visible for layer in selected)
    for layer in selected:
        if layer.visible or not visible:
            image.alpha_composite(layer.image, (layer.x - left, layer.y - top))
    highest = max(i for i, layer in enumerate(doc.layers) if layer.id in doc.selected_ids)
    merged = Layer(doc.active.name, image, left, top, visible, group_id=doc.layers[highest].group_id)
    layers = tuple(merged if i == highest else layer for i, layer in enumerate(doc.layers)
                   if i == highest or layer.id not in doc.selected_ids)
    return doc.edited(layers=layers, active_id=merged.id, selected_ids=frozenset({merged.id}))


def require_selection(doc):
    if not doc.selection or not doc.selection.valid:
        raise ValueError("Draw a rectangular or lasso selection first.")
    box = doc.selection.clipped_bounds(doc.width, doc.height)
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("The selection is outside the canvas.")
    return box


def crop(doc):
    x1, y1, x2, y2 = require_selection(doc)
    layers = []
    for layer in doc.layers:
        if layer.text is not None:
            layers.append(replace(layer, x=layer.x - x1, y=layer.y - y1))
            continue
        a, b, c, d = layer.bounds
        left, top, right, bottom = max(a, x1), max(b, y1), min(c, x2), min(d, y2)
        if right <= left or bottom <= top:
            layers.append(replace(layer, image=Image.new("RGBA", (1, 1)), x=0, y=0))
        else:
            image = layer.image.crop((left - a, top - b, right - a, bottom - b))
            layers.append(replace(layer, image=image, x=left - x1, y=top - y1))
    return doc.edited(width=x2 - x1, height=y2 - y1, layers=tuple(layers), selection=None)


def resize_image(doc, width, height):
    validate_size(width, height)
    sx, sy = width / doc.width, height / doc.height
    layers = []
    for layer in doc.layers:
        require_pixels(layer)
        size = (max(1, round(layer.image.width * sx)), max(1, round(layer.image.height * sy)))
        validate_size(*size)
        layers.append(replace(layer, image=layer.image.resize(size, Image.Resampling.LANCZOS),
                              x=round(layer.x * sx), y=round(layer.y * sy)))
    selection = doc.selection.transformed((0, 0, doc.width, doc.height), (0, 0, width, height)) if doc.selection else None
    return doc.edited(width=width, height=height, layers=tuple(layers), selection=selection)


def resize_canvas(doc, width, height, anchor=(0.5, 0.5)):
    validate_size(width, height)
    dx, dy = round((width - doc.width) * anchor[0]), round((height - doc.height) * anchor[1])
    return doc.edited(width=width, height=height,
                      layers=tuple(replace(layer, x=layer.x + dx, y=layer.y + dy) for layer in doc.layers),
                      selection=doc.selection.translated(dx, dy) if doc.selection else None)


def paste_expanded(layer, image, x, y):
    """Composite while retaining pixels outside the document and original layer bounds."""
    require_pixels(layer)
    a, b, c, d = layer.bounds
    box = min(a, x), min(b, y), max(c, x + image.width), max(d, y + image.height)
    validate_size(box[2] - box[0], box[3] - box[1])
    result = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]))
    result.alpha_composite(layer.image, (a - box[0], b - box[1]))
    result.alpha_composite(image, (x - box[0], y - box[1]))
    return replace(layer, image=result, x=box[0], y=box[1])


def solid_fill(doc, color):
    box = require_selection(doc)
    mask = doc.selection.mask(box)
    fill = Image.new("RGBA", mask.size, color)
    fill.putalpha(ImageChops.multiply(fill.getchannel("A"), mask))
    return doc.with_layer(paste_expanded(doc.active, fill, box[0], box[1]))


def clear_selection(doc):
    """Erase selected active-layer pixels, retaining layer bounds and the selection."""
    layer = doc.active
    require_pixels(layer)
    x1, y1, x2, y2 = require_selection(doc)
    a, b, c, d = layer.bounds
    box = max(x1, a), max(y1, b), min(x2, c), min(y2, d)
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return doc
    local_box = left - a, top - b, right - a, bottom - b
    region = layer.image.crop(local_box)
    mask = doc.selection.mask(box)
    if ImageChops.multiply(region.getchannel("A"), mask).getbbox() is None:
        return doc
    region.paste((0, 0, 0, 0), mask=mask)
    image = layer.image.copy()
    image.paste(region, (local_box[0], local_box[1]))
    return doc.with_layer(replace(layer, image=image))


@dataclass(frozen=True)
class PixelTarget:
    """Original extraction and hole retained throughout a move/transform preview."""
    image: Image.Image
    base: Layer | None
    bounds: tuple[int, int, int, int]
    selected: bool


def extract_target(doc, whole_text=False):
    layer = doc.active
    if not layer.visible:
        raise ValueError("Show the active layer before moving or transforming it.")
    if layer.text is not None and (whole_text or not doc.selection):
        # Type transforms apply to the whole editable layer, including its layout margins.
        return PixelTarget(layer.image, None, layer.bounds, False)
    if doc.selection:
        require_pixels(layer)
        box = require_selection(doc)
        x1, y1, x2, y2 = box
        image = layer.image.crop((x1 - layer.x, y1 - layer.y, x2 - layer.x, y2 - layer.y))
        mask = doc.selection.mask(box)
        image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
        if image.getbbox() is None:
            raise ValueError("There are no active-layer pixels inside this selection.")
        base_image = layer.image.copy()
        overlap = (max(x1, layer.x), max(y1, layer.y), min(x2, layer.bounds[2]), min(y2, layer.bounds[3]))
        a, b, c, d = overlap
        if c > a and d > b:
            local = (a - layer.x, b - layer.y, c - layer.x, d - layer.y)
            alpha = base_image.getchannel("A")
            cut = ImageChops.multiply(alpha.crop(local), ImageChops.invert(doc.selection.mask(overlap)))
            alpha.paste(cut, local)
            base_image.putalpha(alpha)
        return PixelTarget(image, replace(layer, image=base_image), box, True)
    bbox = layer.image.getbbox()
    if bbox is None:
        raise ValueError("The active layer is empty.")
    x1, y1, x2, y2 = bbox
    return PixelTarget(layer.image.crop(bbox), None,
                       (x1 + layer.x, y1 + layer.y, x2 + layer.x, y2 + layer.y), False)


def move(doc, dx, dy, target=None):
    if dx == 0 and dy == 0:
        return doc
    if doc.selection:
        target = target or extract_target(doc)
        layer = paste_expanded(target.base, target.image, target.bounds[0] + dx, target.bounds[1] + dy)
        return doc.with_layer(layer, selection=doc.selection.translated(dx, dy))
    return doc.with_layer(replace(doc.active, x=doc.active.x + dx, y=doc.active.y + dy))


def transform(doc, target, box, flip_x=False, flip_y=False, quarter_turns=0, text_renderer=None):
    x1, y1, x2, y2 = map(round, box)
    validate_size(x2 - x1, y2 - y1)
    if doc.active.text is not None:
        data = doc.active.text
        old_flip_x, old_flip_y = data.flip_x, data.flip_y
        if quarter_turns % 2:
            old_flip_x, old_flip_y = old_flip_y, old_flip_x
        rotation = (data.quarter_turns + quarter_turns) % 4
        old_height = doc.active.image.width if data.quarter_turns % 2 else doc.active.image.height
        new_height = x2 - x1 if rotation % 2 else y2 - y1
        data = replace(data, box_size=(x2 - x1, y2 - y1),
                       size=max(1, min(2048, round(data.size * new_height / old_height))),
                       quarter_turns=rotation,
                       flip_x=old_flip_x ^ flip_x, flip_y=old_flip_y ^ flip_y)
        if text_renderer is not None:
            return doc.with_layer(replace(doc.active, text=data, image=text_renderer(data), x=x1, y=y1))
        # Non-Qt callers can transform the cached pixels while retaining editable geometry.
        target = replace(target, selected=False)
        layer = replace(doc.active, text=data)
    else:
        layer = doc.active
    image = target.image
    rotation = quarter_turns % 4
    if rotation:
        image = image.transpose({1: Image.Transpose.ROTATE_270, 2: Image.Transpose.ROTATE_180,
                                 3: Image.Transpose.ROTATE_90}[rotation])
    if flip_x:
        image = ImageOps.mirror(image)
    if flip_y:
        image = ImageOps.flip(image)
    if image.size != (x2 - x1, y2 - y1):
        image = image.resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
    if target.selected:
        layer = paste_expanded(target.base, image, x1, y1)
        selection = doc.selection.transformed(target.bounds, (x1, y1, x2, y2), flip_x, flip_y, rotation)
    else:
        layer = replace(layer, image=image, x=x1, y=y1)
        selection = doc.selection if layer.text is not None else None
    return doc.with_layer(layer, selection=selection)
