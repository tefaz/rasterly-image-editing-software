"""Replaceable, local image processing with no UI dependencies or cloud services.

The engine accepts an RGBA region, a same-size L mask and optionally a source
region aligned with the target. It returns RGBA pixels with identical dimensions.
Only masked pixels may change. OpenCV accelerates Poisson cloning when available;
the NumPy solver and exemplar texture synthesis work without it.
"""
from abc import ABC, abstractmethod
import numpy as np
from PIL import Image

try:
    import cv2
except ImportError:
    cv2 = None


class InpaintingEngine(ABC):
    @abstractmethod
    def process(self, image: Image.Image, mask: Image.Image,
                source: Image.Image | None = None) -> Image.Image:
        """Fill a mask, or heal it using an already aligned source image."""


def _neighbors(array):
    result = np.zeros_like(array)
    result[1:] += array[:-1]
    result[:-1] += array[1:]
    result[:, 1:] += array[:, :-1]
    result[:, :-1] += array[:, 1:]
    return result


def poisson_blend(source, destination, mask):
    """Solve the discrete Poisson equation with destination Dirichlet boundaries.

    Conjugate gradient retains source texture gradients while matching the
    surrounding destination color. Padding also supports canvas-edge patches.
    """
    src = np.pad(source.astype(np.float32), ((1, 1), (1, 1), (0, 0)), mode="edge")
    dst = np.pad(destination.astype(np.float32), ((1, 1), (1, 1), (0, 0)), mode="edge")
    inside = np.pad(mask.astype(bool), 1)[..., None]
    laplacian = 4 * src - _neighbors(src)
    rhs = (laplacian + _neighbors(dst * ~inside)) * inside

    def apply(value):
        return (4 * value - _neighbors(value)) * inside

    boundary = (_neighbors(inside[..., 0].astype(np.uint8)) > 0) & ~inside[..., 0]
    if boundary.any():
        correction = dst[boundary].mean(0) - src[boundary].mean(0)
    else:
        correction = np.zeros(3)
    solution = (src + correction) * inside
    residual = rhs - apply(solution)
    direction = residual.copy()
    norm = float(np.sum(residual * residual))
    initial_norm = max(norm, 1)
    for _ in range(350):
        if norm < max(initial_norm * 1e-7, 0.02):
            break
        product = apply(direction)
        denominator = float(np.sum(direction * product))
        if denominator <= 1e-12:
            break
        step = norm / denominator
        solution += step * direction
        residual -= step * product
        next_norm = float(np.sum(residual * residual))
        direction = residual + (next_norm / max(norm, 1e-12)) * direction
        norm = next_norm
    result = np.where(inside, solution, dst)[1:-1, 1:-1]
    return np.clip(result, 0, 255).astype(np.uint8)


def synthesize_texture(rgb, mask, valid):
    """Boundary-first exemplar inpainting using unselected local texture patches.

    Candidate patches always come from the pristine known region. Matching uses
    only known target pixels, then fills unknown pixels from the best candidate.
    The seed is fixed so an identical operation produces an identical result.
    """
    height, width = mask.shape
    radius = min(4, (min(width, height) - 1) // 2)
    if radius < 1:
        raise ValueError("The image is too small to reconstruct this selection.")
    size = radius * 2 + 1
    unknown = mask.copy()
    known = ~mask & valid
    if not known.any():
        raise ValueError("Content-Aware needs surrounding pixels on the active layer.")
    # Integral image identifies fully known candidate patches in constant time.
    integral = np.pad(known.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    sums = (integral[size:, size:] - integral[:-size, size:]
            - integral[size:, :-size] + integral[:-size, :-size])
    candidates = np.argwhere(sums == size * size)
    if not len(candidates):
        if cv2 is not None and np.all(valid):
            return cv2.inpaint(rgb, mask.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)
        # Smaller patches allow narrow borders to supply source material.
        if radius > 1:
            return _propagate(rgb, unknown, known)
        raise ValueError("Select a smaller area with more surrounding image pixels.")
    rng = np.random.default_rng(1742)
    if len(candidates) > 256:
        candidates = candidates[rng.choice(len(candidates), 256, replace=False)]
    patches = np.stack([rgb[y:y + size, x:x + size] for y, x in candidates]).astype(np.float32)
    output = rgb.copy()
    padded = np.pad(output, ((radius, radius), (radius, radius), (0, 0)), mode="edge")
    steps = 0
    while unknown.any():
        adjacent = _neighbors(known.astype(np.uint8))
        frontier = unknown & (adjacent > 0)
        if not frontier.any():
            raise ValueError("The selection has no connected source pixels.")
        # More known neighbors give a more constrained, reliable first patch.
        score = adjacent.astype(np.int16) * 10
        score += _neighbors(adjacent).astype(np.int16)
        y, x = np.unravel_index(np.argmax(np.where(frontier, score, -1)), mask.shape)
        y1, x1 = max(0, y - radius), max(0, x - radius)
        y2, x2 = min(height, y + radius + 1), min(width, x + radius + 1)
        window = padded[y:y + size, x:x + size].astype(np.float32)
        matching = np.zeros((size, size), bool)
        a, b = y1 - y + radius, x1 - x + radius
        matching[a:a + y2 - y1, b:b + x2 - x1] = known[y1:y2, x1:x2]
        differences = (patches[:, matching] - window[matching]) / 255
        errors = np.mean(differences * differences, axis=(1, 2))
        best = patches[int(np.argmin(errors))].astype(np.uint8)
        target_unknown = unknown[y1:y2, x1:x2]
        chunk = output[y1:y2, x1:x2]
        chunk[target_unknown] = best[a:a + y2 - y1, b:b + x2 - x1][target_unknown]
        known[y1:y2, x1:x2] |= target_unknown
        unknown[y1:y2, x1:x2] = False
        padded[y1 + radius:y2 + radius, x1 + radius:x2 + radius] = chunk
        steps += 1
        if steps > 20000:
            raise ValueError("This selection is too large for local texture reconstruction; use the Patch Tool.")
    return output


def _propagate(rgb, unknown, known):
    output = rgb.astype(np.float32)
    unknown = unknown.copy()
    known = known.copy()
    while unknown.any():
        counts = _neighbors(known.astype(np.float32))
        frontier = unknown & (counts > 0)
        if not frontier.any():
            raise ValueError("The selection has no surrounding image information.")
        colors = _neighbors(output * known[..., None])
        output[frontier] = colors[frontier] / counts[frontier, None]
        known[frontier] = True
        unknown[frontier] = False
    return np.clip(output, 0, 255).astype(np.uint8)


class LocalInpaintingEngine(InpaintingEngine):
    name = "Local texture synthesis + Poisson healing"

    def process(self, image, mask, source=None):
        if image.size != mask.size or (source is not None and source.size != image.size):
            raise ValueError("Processing images and mask must have matching dimensions.")
        original = np.array(image.convert("RGBA"))
        selected = np.array(mask) > 0
        if not selected.any():
            raise ValueError("The selection contains no pixels.")
        if selected.all():
            raise ValueError("Keep some unselected surrounding pixels for healing.")
        rgb = original[..., :3].copy()
        valid = original[..., 3] > 0
        if source is None:
            replacement = synthesize_texture(rgb, selected, valid)
        else:
            source_pixels = np.array(source.convert("RGBA"))
            if np.any(source_pixels[..., 3][selected] == 0):
                raise ValueError("Choose a patch source entirely inside visible pixels on the active layer.")
            replacement = source_pixels[..., :3].copy()
        if cv2 is not None:
            # Padding guarantees room around a mask touching an image edge.
            border = 2
            src = np.pad(replacement[..., ::-1], ((border, border), (border, border), (0, 0)), mode="edge")
            dst = np.pad(rgb[..., ::-1], ((border, border), (border, border), (0, 0)), mode="edge")
            padded_mask = np.pad(selected.astype(np.uint8) * 255, border)
            x, y, w, h = cv2.boundingRect(padded_mask)
            try:
                healed = cv2.seamlessClone(src, dst, padded_mask, (x + w // 2, y + h // 2), cv2.NORMAL_CLONE)
                healed = healed[border:-border, border:-border, ::-1]
            except cv2.error:
                healed = poisson_blend(replacement, rgb, selected)
        else:
            healed = poisson_blend(replacement, rgb, selected)
        result = original.copy()
        result[..., :3][selected] = healed[selected]
        if source is None:
            result[..., 3][selected & ~valid] = 255
        return Image.fromarray(result)


def processing_region(doc, source_offset=None):
    """Extract local full-resolution context, not a screen preview."""
    from .operations import require_selection
    box = require_selection(doc)
    pad = max(24, min(128, max(box[2] - box[0], box[3] - box[1]) // 2))
    region = (max(0, box[0] - pad), max(0, box[1] - pad),
              min(doc.width, box[2] + pad), min(doc.height, box[3] + pad))
    layer = doc.active
    a, b, c, d = region
    image = layer.image.crop((a - layer.x, b - layer.y, c - layer.x, d - layer.y))
    mask = doc.selection.mask(region)
    source = None
    if source_offset is not None:
        dx, dy = source_offset
        source = layer.image.crop((a + dx - layer.x, b + dy - layer.y,
                                   c + dx - layer.x, d + dy - layer.y))
    return region, image, mask, source


def apply_processed(doc, region, result):
    from dataclasses import replace
    from .model import validate_size
    from .operations import require_pixels
    layer = doc.active
    require_pixels(layer)
    a, b, c, d = layer.bounds
    x1, y1, x2, y2 = region
    left, top, right, bottom = min(a, x1), min(b, y1), max(c, x2), max(d, y2)
    validate_size(right - left, bottom - top)
    image = Image.new("RGBA", (right - left, bottom - top))
    image.paste(layer.image, (a - left, b - top))
    image.paste(result, (x1 - left, y1 - top), doc.selection.mask(region))
    return doc.with_layer(replace(layer, image=image, x=left, y=top))
