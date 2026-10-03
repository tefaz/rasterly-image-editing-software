"""Color-stop interpolation shared by the gradient editor and raster renderer."""
import math

import numpy as np


def normalize_stops(stops):
    result = tuple(sorted((float(position), tuple(color)) for position, color in stops))
    if len(result) < 2:
        raise ValueError("A gradient needs at least two color stops.")
    previous = -1.0
    for position, color in result:
        if not math.isfinite(position) or not 0 <= position <= 1 or position <= previous:
            raise ValueError("Gradient stops must have distinct positions between 0 and 1.")
        if len(color) != 4 or any(not 0 <= channel <= 255 for channel in color):
            raise ValueError("Gradient colors must have four channels between 0 and 255.")
        previous = position
    return result


def sample_gradient(stops, positions):
    """Sample RGBA in premultiplied space, padding beyond the outermost stops."""
    stops = normalize_stops(stops)
    locations = np.array([position for position, _ in stops])
    colors = np.array([color for _, color in stops], dtype=np.float32)
    positions = np.asarray(positions)
    alpha = np.interp(positions, locations, colors[:, 3])
    result = np.empty(positions.shape + (4,), dtype=np.uint8)
    for channel in range(3):
        premultiplied = np.interp(positions, locations, colors[:, channel] * colors[:, 3])
        fallback = np.asarray(np.interp(positions, locations, colors[:, channel]))
        value = np.divide(premultiplied, alpha, out=fallback, where=alpha > 0)
        result[..., channel] = np.rint(np.clip(value, 0, 255)).astype(np.uint8)
    result[..., 3] = np.rint(alpha).astype(np.uint8)
    return result
