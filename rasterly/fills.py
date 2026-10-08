"""Selection-aware paint bucket and linear gradient commands."""
import math

import numpy as np
from PIL import Image, ImageChops

from .operations import paste_expanded, require_pixels, require_selection
from .gradient import normalize_stops, sample_gradient


def fill_bounds(doc):
    require_pixels(doc.active)
    if not doc.layer_visible(doc.active):
        raise ValueError("Show the active layer before filling it.")
    return require_selection(doc) if doc.selection else (0, 0, doc.width, doc.height)


def composite_fill(doc, overlay, bounds):
    if doc.selection:
        overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), doc.selection.mask(bounds)))
    box = overlay.getbbox()
    if box is None:
        return doc
    layer = paste_expanded(doc.active, overlay.crop(box), bounds[0] + box[0], bounds[1] + box[1])
    if layer.bounds == doc.active.bounds and all(
            lo == hi == 0 for lo, hi in ImageChops.difference(layer.image, doc.active.image).getextrema()):
        return doc
    return doc.with_layer(layer)


def connected_mask(eligible, seed):
    """Consume matching pixels in horizontal spans, avoiding a per-pixel queue."""
    height, width = eligible.shape
    result = np.zeros((height, width), dtype=np.uint8)
    pending = [seed]
    while pending:
        x, y = pending.pop()
        if not eligible[y, x]:
            continue
        row = eligible[y]
        stops = np.flatnonzero(~row[:x])
        left = int(stops[-1]) + 1 if stops.size else 0
        stops = np.flatnonzero(~row[x + 1:])
        right = x + 1 + int(stops[0]) if stops.size else width
        row[left:right] = False
        result[y, left:right] = 255
        for neighbor in (y - 1, y + 1):
            if 0 <= neighbor < height:
                candidates = eligible[neighbor, left:right]
                starts = candidates.copy()
                starts[1:] &= ~candidates[:-1]
                pending.extend((left + int(offset), neighbor) for offset in np.flatnonzero(starts))
    return Image.fromarray(result)


def paint_bucket(doc, point, color, tolerance=32):
    bounds = fill_bounds(doc)
    x, y = math.floor(point[0]), math.floor(point[1])
    left, top, right, bottom = bounds
    if not (left <= x < right and top <= y < bottom):
        return doc
    layer = doc.active
    pixels = np.asarray(layer.image.crop((left - layer.x, top - layer.y,
                                          right - layer.x, bottom - layer.y)))
    seed = pixels[y - top, x - left].astype(np.int16)
    tolerance = max(0, min(255, int(tolerance)))
    eligible = np.abs(pixels[:, :, 3].astype(np.int16) - seed[3]) <= tolerance
    # Invisible RGB values are irrelevant when filling a transparent region.
    if seed[3] != 0:
        for channel in range(3):
            eligible &= np.abs(pixels[:, :, channel].astype(np.int16) - seed[channel]) <= tolerance
    if doc.selection:
        eligible &= np.asarray(doc.selection.mask(bounds)) > 0
    mask = connected_mask(eligible, (x - left, y - top))
    overlay = Image.new("RGBA", mask.size, color)
    overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))
    return composite_fill(doc, overlay, bounds)


def linear_gradient(doc, start, end, color=None, transparent=False, *, stops=None):
    bounds = fill_bounds(doc)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared < 1e-8:
        return doc
    left, top, right, bottom = bounds
    width, height = right - left, bottom - top
    overlay = Image.new("RGBA", (width, height))
    if stops is None:
        destination = (*color[:3], 0) if transparent else (255, 255, 255, 255)
        stops = ((0.0, color), (1.0, destination))
    stops = normalize_stops(stops)
    # Bound temporary allocations independently of the document's height.
    rows = max(1, 1_000_000 // width)
    xs = np.arange(left, right, dtype=np.float32)[None, :]
    for offset in range(0, height, rows):
        count = min(rows, height - offset)
        ys = np.arange(top + offset, top + offset + count, dtype=np.float32)[:, None]
        t = np.clip(((xs - start[0]) * dx + (ys - start[1]) * dy) / length_squared, 0, 1)
        rgba = sample_gradient(stops, t)
        overlay.paste(Image.fromarray(rgba), (0, offset))
    return composite_fill(doc, overlay, bounds)
