import unittest
from dataclasses import replace
import numpy as np
from PIL import Image, ImageDraw
from rasterly.model import Document
from rasterly.selection import Selection
from rasterly.processing import LocalInpaintingEngine, processing_region, apply_processed


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(100)
        pixels = np.zeros((96, 128, 4), np.uint8)
        pixels[..., :3] = [50, 130, 70]
        pixels[..., :3] += rng.integers(0, 20, (96, 128, 3), dtype=np.uint8)
        pixels[..., 3] = 255
        pixels[30:50, 35:55, :3] = [220, 20, 10]
        self.image = Image.fromarray(pixels)
        self.mask = Image.new("L", self.image.size)
        ImageDraw.Draw(self.mask).polygon([(32, 27), (60, 28), (62, 54), (30, 52)], fill=255)
        self.engine = LocalInpaintingEngine()

    def test_fill_reconstructs_local_color_and_keeps_outside_mask_exact(self):
        result = self.engine.process(self.image, self.mask)
        original, output = np.array(self.image), np.array(result)
        mask = np.array(self.mask) > 0
        self.assertTrue(np.array_equal(original[~mask], output[~mask]))
        color = output[33:47, 38:52, :3].mean((0, 1))
        self.assertLess(np.linalg.norm(color - np.array([60, 140, 80])), 18)
        self.assertTrue(np.array_equal(original[..., 3], output[..., 3]))
        self.assertGreater(output[33:47, 38:52, :3].std(), 5)

    def test_patch_matches_boundary_color_while_retaining_source_texture(self):
        source = np.array(self.image)
        source[..., :3] = [110, 180, 130]
        source[::3, ::3, :3] += 30
        result = self.engine.process(self.image, self.mask, Image.fromarray(source))
        original, output = np.array(self.image), np.array(result)
        mask = np.array(self.mask) > 0
        self.assertTrue(np.array_equal(original[~mask], output[~mask]))
        self.assertFalse(np.array_equal(output[mask], source[mask]))
        self.assertLess(output[33:47, 38:52, 0].mean(), 100)
        self.assertGreater(output[33:47, 38:52, 0].std(), 4)

    def test_patch_rejects_transparent_source(self):
        with self.assertRaisesRegex(ValueError, "source"):
            self.engine.process(self.image, self.mask, Image.new("RGBA", self.image.size))

    def test_full_image_and_empty_selection_are_rejected(self):
        for color in (0, 255):
            with self.assertRaises(ValueError):
                self.engine.process(self.image, Image.new("L", self.image.size, color))

    def test_processing_regions_respect_layer_offset_and_lasso(self):
        doc = Document.from_image(self.image)
        doc = doc.with_layer(replace(doc.active, x=10, y=8))
        doc = replace(doc, selection=Selection("lasso", ((42, 35), (70, 36), (72, 62), (40, 60))))
        region, image, mask, source = processing_region(doc, (30, 0))
        self.assertEqual(image.size, mask.size)
        self.assertEqual(source.size, image.size)
        self.assertEqual(image.getpixel((45 - region[0], 40 - region[1])), self.image.getpixel((35, 32)))
        processed = self.engine.process(image, mask)
        result = apply_processed(doc, region, processed)
        self.assertEqual(doc.active.image.getpixel((40, 35)), (220, 20, 10, 255))
        # Original unselected layer pixels, including those beyond the canvas, survive.
        original = doc.active.image.getpixel((127, 95))
        self.assertEqual(result.active.image.getpixel((137 - result.active.x, 103 - result.active.y)), original)


if __name__ == "__main__":
    unittest.main()
