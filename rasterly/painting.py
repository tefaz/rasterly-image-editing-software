"""Continuous round strokes, rendered into a temporary patch until committed."""
from dataclasses import replace
import math

import numpy as np
from PIL import Image, ImageChops

from .model import validate_size
from .operations import require_pixels, require_selection


class PaintStroke:
    def __init__(self, document, size=24, opacity=100, hardness=100,
                 color=(0, 0, 0, 255), erase=False):
        require_pixels(document.active)
        if not document.layer_visible(document.active):
            raise ValueError("Show the active layer before painting on it.")
        if not 1 <= size <= 2048 or not 0 <= opacity <= 100 or not 0 <= hardness <= 100:
            raise ValueError("Invalid brush size, opacity, or hardness.")
        self.document = document
        self.size, self.opacity, self.hardness = size, opacity, hardness
        self.color, self.erase = color, erase
        self.clip = require_selection(document) if document.selection else (
            0, 0, document.width, document.height)
        self.bounds = self.coverage = self.preview = self.previous = None

    def segment_mask(self, start, end, box):
        left, top, right, bottom = box
        width, height = right - left, bottom - top
        radius = self.size / 2
        falloff = max(1.0, radius * (1 - self.hardness / 100) + .5)
        ax, ay = start
        dx, dy = end[0] - ax, end[1] - ay
        length = dx * dx + dy * dy
        result = np.empty((height, width), dtype=np.uint8)
        xs = np.arange(left, right, dtype=np.float32)[None, :] + .5
        rows = max(1, 262_144 // width)
        for offset in range(0, height, rows):
            count = min(rows, height - offset)
            ys = np.arange(top + offset, top + offset + count, dtype=np.float32)[:, None] + .5
            t = np.clip(((xs - ax) * dx + (ys - ay) * dy) / length, 0, 1) if length else 0
            distance = np.hypot(xs - (ax + t * dx), ys - (ay + t * dy))
            coverage = np.clip((radius + .5 - distance) / falloff, 0, 1)
            result[offset:offset + count] = np.rint(coverage * 255).astype(np.uint8)
        mask = Image.fromarray(result)
        if self.document.selection:
            mask = ImageChops.multiply(mask, self.document.selection.mask(box))
        return mask

    def original_region(self, box):
        layer = self.document.active
        return layer.image.crop((box[0] - layer.x, box[1] - layer.y,
                                 box[2] - layer.x, box[3] - layer.y))

    def expand_patch(self, box):
        # Expand by tiles, rather than reallocating the patch for every pixel.
        left = max(self.clip[0], box[0] // 64 * 64)
        top = max(self.clip[1], box[1] // 64 * 64)
        right = min(self.clip[2], math.ceil(box[2] / 64) * 64)
        bottom = min(self.clip[3], math.ceil(box[3] / 64) * 64)
        if self.bounds:
            a, b, c, d = self.bounds
            left, top, right, bottom = min(left, a), min(top, b), max(right, c), max(bottom, d)
        bounds = left, top, right, bottom
        if bounds == self.bounds:
            return
        image = self.original_region(bounds)
        coverage = Image.new("L", image.size)
        if self.bounds:
            position = self.bounds[0] - left, self.bounds[1] - top
            image.paste(self.preview.image, position)
            coverage.paste(self.coverage, position)
        self.bounds, self.coverage = bounds, coverage
        self.preview = replace(self.document.active, image=image, x=left, y=top)

    def add(self, point):
        start, end = self.previous or point, point
        self.previous = point
        if self.opacity == 0 or (not self.erase and self.color[3] == 0):
            return False
        radius = self.size / 2 + .5
        a, b, c, d = self.clip
        box = (max(a, math.floor(min(start[0], end[0]) - radius)),
               max(b, math.floor(min(start[1], end[1]) - radius)),
               min(c, math.ceil(max(start[0], end[0]) + radius)),
               min(d, math.ceil(max(start[1], end[1]) + radius)))
        if box[2] <= box[0] or box[3] <= box[1]:
            return False
        mask = self.segment_mask(start, end, box)
        if mask.getbbox() is None:
            return False
        self.expand_patch(box)
        local_box = (box[0] - self.bounds[0], box[1] - self.bounds[1],
                     box[2] - self.bounds[0], box[3] - self.bounds[1])
        old = self.coverage.crop(local_box)
        mask = ImageChops.lighter(old, mask)
        if ImageChops.difference(old, mask).getbbox() is None:
            return False
        self.coverage.paste(mask, local_box[:2])
        strength = self.opacity / 100 * (1 if self.erase else self.color[3] / 255)
        mask = mask.point([round(value * strength) for value in range(256)])
        region = self.original_region(box)
        if self.erase:
            region.putalpha(ImageChops.multiply(region.getchannel("A"), ImageChops.invert(mask)))
        else:
            paint = Image.new("RGBA", region.size, self.color)
            paint.putalpha(mask)
            region = Image.alpha_composite(region, paint)
        self.preview.image.paste(region, local_box[:2])
        return True

    def finish(self):
        doc = self.document
        if self.preview is None:
            return doc
        original = self.original_region(self.bounds)
        if all(lo == hi == 0 for lo, hi in ImageChops.difference(original, self.preview.image).getextrema()):
            return doc
        layer = doc.active
        a, b, c, d = layer.bounds
        x1, y1, x2, y2 = self.bounds
        left, top, right, bottom = min(a, x1), min(b, y1), max(c, x2), max(d, y2)
        validate_size(right - left, bottom - top)
        image = Image.new("RGBA", (right - left, bottom - top))
        image.paste(layer.image, (a - left, b - top))
        # Replace the patch, including erased alpha, rather than compositing it twice.
        image.paste(self.preview.image, (x1 - left, y1 - top))
        return doc.with_layer(replace(layer, image=image, x=left, y=top))
