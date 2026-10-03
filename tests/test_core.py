import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from PIL import Image
from rasterly.model import Document, Layer, composite
from rasterly.selection import Selection
from rasterly.history import History
from rasterly import operations as op, files


class DocumentTests(unittest.TestCase):
    def test_new_layer_is_empty_transparent_and_selected_above_active_layer(self):
        doc = Document.new(37, 19)
        original = doc.active
        added = op.add_layer(doc)
        self.assertEqual(added.active.image.size, (37, 19))
        self.assertEqual(added.active.image.getextrema(), ((0, 0),) * 4)
        self.assertEqual(added.active.bounds, (0, 0, 37, 19))
        self.assertIs(added.layers[0], original)
        self.assertEqual(added.selected_ids, frozenset({added.active_id}))
        self.assertEqual(composite(added).tobytes(), composite(doc).tobytes())

    def test_clear_selection_erases_only_active_layer_and_preserves_source_for_undo(self):
        doc = op.add_layer(Document.new(10, 10))
        top = replace(doc.active, image=Image.new("RGBA", (10, 10), (80, 120, 160, 128)))
        selection = Selection.rectangle(2, 3, 6, 8)
        doc = doc.with_layer(top, selection=selection,
                             selected_ids=frozenset(layer.id for layer in doc.layers))
        cleared = op.clear_selection(doc)
        self.assertEqual(cleared.active.image.getpixel((2, 3)), (0, 0, 0, 0))
        self.assertEqual(cleared.active.image.getpixel((5, 7)), (0, 0, 0, 0))
        self.assertEqual(cleared.active.image.getpixel((6, 7)), (80, 120, 160, 128))
        self.assertEqual(composite(cleared).getpixel((2, 3)), (255, 255, 255, 255))
        self.assertIs(cleared.layers[0], doc.layers[0])
        self.assertIs(cleared.selection, selection)
        self.assertEqual(cleared.selected_ids, doc.selected_ids)
        self.assertEqual(cleared.active.id, doc.active.id)
        self.assertEqual(doc.active.image.getpixel((2, 3)), (80, 120, 160, 128))

    def test_clear_irregular_selection_with_hole_preserves_outside_and_off_canvas_pixels(self):
        layer = Layer("Offset", Image.new("RGBA", (12, 12), "red"), -2, -3)
        selection = Selection("lasso", ((-3, -3), (8, 0), (0, 8))).subtracted(
            Selection.rectangle(1, 1, 3, 3))
        doc = Document(8, 8, (layer,), layer.id, selection)
        cleared = op.clear_selection(doc)
        mask = selection.mask((0, 0, 8, 8))
        self.assertEqual(cleared.active.bounds, layer.bounds)
        for y in range(12):
            for x in range(12):
                dx, dy = x + layer.x, y + layer.y
                erased = 0 <= dx < 8 and 0 <= dy < 8 and mask.getpixel((dx, dy))
                self.assertEqual(cleared.active.image.getpixel((x, y)),
                                 (0, 0, 0, 0) if erased else (255, 0, 0, 255))

    def test_clear_empty_or_nonintersecting_selection_is_noop(self):
        doc = op.add_layer(Document.new(8, 8)).edited(selection=Selection.rectangle(0, 0, 8, 8))
        self.assertIs(op.clear_selection(doc), doc)
        layer = replace(doc.active, image=Image.new("RGBA", (2, 2), "red"), x=10, y=10)
        doc = doc.with_layer(layer)
        self.assertIs(op.clear_selection(doc), doc)
        doc = Document.new(8, 8).edited(selection=Selection.rectangle(2, 2, 5, 5))
        cleared = op.clear_selection(doc)
        self.assertIs(op.clear_selection(cleared), cleared)
        with self.assertRaises(ValueError):
            op.clear_selection(Document.new(8, 8))

    def test_new_image_has_exactly_one_selected_white_visible_layer(self):
        doc = Document.new(37, 19)
        self.assertEqual((doc.width, doc.height), (37, 19))
        self.assertEqual(len(doc.layers), 1)
        self.assertTrue(doc.active.visible)
        self.assertEqual(doc.active.image.size, (37, 19))
        self.assertEqual(doc.active.image.getpixel((36, 18)), (255, 255, 255, 255))

    def test_layer_compositing_uses_stacking_visibility_and_transparency(self):
        doc = op.add_layer(Document.new(10, 10))
        top = replace(doc.active, image=Image.new("RGBA", (2, 2), (255, 0, 0, 128)), x=3, y=4)
        doc = doc.with_layer(top)
        self.assertEqual(composite(doc).getpixel((3, 4)), (255, 127, 127, 255))
        self.assertEqual(composite(doc).getpixel((2, 4)), (255, 255, 255, 255))
        hidden = doc.with_layer(replace(top, visible=False))
        self.assertEqual(composite(hidden).getpixel((3, 4)), (255, 255, 255, 255))

    def test_duplicate_reorder_and_delete_preserve_identifiers_and_buffers(self):
        doc = Document.new(10, 10)
        original = doc.active
        doc = op.duplicate_layer(doc)
        self.assertNotEqual(original.id, doc.active.id)
        self.assertIs(original.image, doc.active.image)
        doc = op.reorder_layers(doc, [doc.layers[1].id, doc.layers[0].id])
        self.assertEqual(doc.layers[-1].id, original.id)
        doc = op.delete_layer(doc)
        self.assertEqual(doc.active_id, original.id)
        with self.assertRaises(ValueError):
            op.delete_layer(doc)

    def test_rectangular_crop_is_not_square_and_aligns_every_layer(self):
        doc = Document.new(800, 600)
        layer = Layer("Top", Image.new("RGBA", (10, 10), "red"), 130, 210)
        doc = doc.edited(layers=doc.layers + (layer,), selection=Selection.rectangle(120, 200, 620, 550))
        cropped = op.crop(doc)
        self.assertEqual((cropped.width, cropped.height), (500, 350))
        self.assertEqual((cropped.layers[1].x, cropped.layers[1].y), (10, 10))
        self.assertIsNone(cropped.selection)
        self.assertEqual(composite(cropped).getpixel((10, 10)), (255, 0, 0, 255))
        self.assertEqual(doc.layers[0].image.size, (800, 600))

    def test_lasso_crop_uses_axis_aligned_bounding_box(self):
        doc = replace(Document.new(800, 600), selection=Selection("lasso", ((120, 200), (620, 300), (200, 550))))
        cropped = op.crop(doc)
        self.assertEqual((cropped.width, cropped.height), (500, 350))

    def test_lasso_fill_respects_irregular_mask_and_only_active_layer(self):
        doc = op.add_layer(Document.new(20, 20))
        original = doc.layers[0].image.tobytes()
        doc = replace(doc, selection=Selection("lasso", ((2, 2), (15, 2), (2, 15))))
        filled = op.solid_fill(doc, (255, 0, 0, 255))
        self.assertEqual(filled.active.image.getpixel((4, 4)), (255, 0, 0, 255))
        self.assertEqual(filled.active.image.getpixel((14, 14)), (0, 0, 0, 0))
        self.assertEqual(filled.layers[0].image.tobytes(), original)
        self.assertEqual(doc.active.image.getpixel((4, 4)), (0, 0, 0, 0))

    def test_selected_move_cuts_only_masked_pixels_and_can_extend_layer(self):
        doc = Document.from_image(Image.new("RGBA", (10, 10), "red"))
        doc = replace(doc, selection=Selection("lasso", ((1, 1), (4, 1), (1, 4))))
        moved = op.move(doc, 10, -3)
        self.assertEqual(composite(moved).getpixel((2, 2))[3], 0)
        self.assertEqual(composite(moved).getpixel((3, 3)), (255, 0, 0, 255))
        self.assertEqual(moved.active.y, -2)
        self.assertGreater(moved.active.image.width, 10)
        self.assertEqual(doc.active.image.getpixel((2, 2)), (255, 0, 0, 255))

    def test_whole_layer_move_changes_position_without_resampling(self):
        doc = Document.new(10, 10)
        moved = op.move(doc, -3, 7)
        self.assertIs(moved.active.image, doc.active.image)
        self.assertEqual((moved.active.x, moved.active.y), (-3, 7))

    def test_canvas_size_keeps_pixels_and_anchor_controls_offset(self):
        doc = Document.new(20, 10)
        centered = op.resize_canvas(doc, 30, 20)
        self.assertEqual((centered.active.x, centered.active.y), (5, 5))
        self.assertIs(centered.active.image, doc.active.image)
        self.assertEqual(composite(centered).getpixel((0, 0))[3], 0)
        for anchor, offset in [((0, 0), (0, 0)), ((1, 1), (10, 10)), ((1, 0), (10, 0))]:
            resized = op.resize_canvas(doc, 30, 20, anchor)
            self.assertEqual((resized.active.x, resized.active.y), offset)

    def test_image_size_resamples_all_layers_offsets_and_selection(self):
        doc = Document.new(200, 100)
        top = Layer("Top", Image.new("RGBA", (40, 20), "red"), 50, 30)
        doc = doc.edited(layers=doc.layers + (top,), selection=Selection.rectangle(20, 20, 60, 40))
        resized = op.resize_image(doc, 100, 50)
        self.assertEqual(resized.layers[0].image.size, (100, 50))
        self.assertEqual(resized.layers[1].image.size, (20, 10))
        self.assertEqual((resized.layers[1].x, resized.layers[1].y), (25, 15))
        self.assertEqual(resized.selection.bounds, (10, 10, 30, 20))

    def test_transform_flips_around_center_and_preserves_original(self):
        image = Image.new("RGBA", (8, 4), "red")
        image.paste("blue", (4, 0, 8, 4))
        doc = Document.from_image(image)
        target = op.extract_target(doc)
        flipped = op.transform(doc, target, (0, 0, 8, 4), True)
        self.assertEqual(flipped.active.image.getpixel((0, 0)), (0, 0, 255, 255))
        self.assertEqual(doc.active.image.getpixel((0, 0)), (255, 0, 0, 255))
        resized = op.transform(doc, target, (2, 3, 18, 7))
        self.assertEqual(resized.active.image.size, (16, 4))
        self.assertEqual((resized.active.x, resized.active.y), (2, 3))

    def test_selected_transform_cuts_source_and_preserves_unselected_pixels(self):
        doc = replace(Document.new(20, 20), selection=Selection.rectangle(2, 2, 6, 8))
        target = op.extract_target(doc)
        resized = op.transform(doc, target, (10, 10, 18, 16))
        self.assertEqual(composite(resized).getpixel((3, 3))[3], 0)
        self.assertEqual(composite(resized).getpixel((1, 1))[3], 255)
        self.assertEqual(resized.selection.bounds, (10, 10, 18, 16))

    def test_command_history_restores_exact_pixels_geometry_and_metadata(self):
        doc = Document.new(20, 10)
        history = History()
        created = op.add_layer(doc)
        history.push("New layer", doc, created)
        selected = replace(created, selection=Selection.rectangle(2, 2, 6, 8))
        filled = op.solid_fill(selected, "red")
        history.push("Fill", selected, filled)
        before = history.undo()
        self.assertEqual(before.active.image.tobytes(), selected.active.image.tobytes())
        self.assertEqual(history.undo().revision, doc.revision)
        self.assertEqual(history.redo().revision, created.revision)
        self.assertEqual(history.redo().active.image.tobytes(), filled.active.image.tobytes())
        history.undo()
        history.push("Crop", selected, op.crop(selected))
        self.assertFalse(history.redo_stack)

    def test_history_memory_limit_counts_shared_buffers_once_and_prunes(self):
        doc = Document.new(10, 10)
        history = History(memory_limit=1000)
        for _ in range(10):
            after = op.duplicate_layer(doc)
            history.push("Duplicate", doc, after)
            doc = after
        self.assertEqual(history.bytes_used, 400)
        for color in ("red", "green", "blue"):
            selected = replace(doc, selection=Selection.rectangle(0, 0, 10, 10))
            after = op.solid_fill(selected, color)
            history.push("Fill", selected, after)
            doc = after
        self.assertLessEqual(len(history.undo_stack), 2)

    def test_invalid_dimensions_and_empty_crop_are_rejected(self):
        for size in [(0, 20), (10, -1), (40000, 10), (12000, 12000)]:
            with self.assertRaises(ValueError):
                Document.new(*size)
        with self.assertRaises(ValueError):
            op.crop(Document.new(20, 10))

    def test_history_jumps_restore_complete_snapshots_and_keep_future_states(self):
        doc = Document.new(30, 20)
        history = History()
        states = [doc]
        for label, operation in [("New layer", op.add_layer), ("Duplicate layer", op.duplicate_layer),
                                 ("Canvas Size", lambda d: op.resize_canvas(d, 50, 40)),
                                 ("Move", lambda d: op.move(d, 12, -4))]:
            after = operation(doc)
            history.push(label, doc, after)
            states.append(after)
            doc = after
        self.assertEqual(history.state_labels, ["New image", "New layer", "Duplicate layer", "Canvas Size", "Move"])
        self.assertIs(history.jump(1), states[1])
        self.assertEqual(history.position, 1)
        self.assertEqual(len(history.redo_stack), 3)
        self.assertIs(history.jump(4), states[4])
        self.assertIs(history.jump(0), states[0])
        self.assertIsNone(history.jump(0))
        with self.assertRaises(ValueError):
            history.jump(5)

    def test_history_jump_then_edit_discards_only_future_branch(self):
        doc = Document.new(20, 10)
        history = History()
        for i in range(3):
            after = op.duplicate_layer(doc)
            history.push("Duplicate", doc, after)
            doc = after
        doc = history.jump(1)
        after = op.resize_canvas(doc, 30, 15)
        history.push("Canvas Size", doc, after)
        self.assertEqual(history.state_labels, ["New image", "Duplicate", "Canvas Size"])
        self.assertFalse(history.redo_stack)

    def test_pruned_history_has_a_reachable_baseline(self):
        doc = Document.new(20, 10)
        history = History(max_commands=2)
        states = [doc]
        for _ in range(5):
            after = op.resize_canvas(doc, doc.width + 1, doc.height + 1)
            history.push("Canvas Size", doc, after)
            states.append(after)
            doc = after
        self.assertEqual(history.state_labels[0], "Earlier state (history limit)")
        self.assertIs(history.jump(0), states[3])
        self.assertIs(history.jump(2), states[5])

    def test_copy_lasso_preserves_alpha_offsets_and_source_pixels(self):
        doc = Document.from_image(Image.new("RGBA", (20, 20), (20, 80, 100, 128)))
        doc = doc.with_layer(replace(doc.active, x=4, y=3))
        doc = replace(doc, selection=Selection("lasso", ((5, 4), (15, 4), (5, 14))))
        original = doc.active.image.tobytes()
        pixels, origin = op.copy_selection(doc)
        self.assertEqual(origin, (5, 4))
        self.assertEqual(pixels.size, (10, 10))
        self.assertEqual(pixels.getpixel((1, 1)), (20, 80, 100, 128))
        self.assertEqual(pixels.getpixel((9, 9))[3], 0)
        self.assertEqual(doc.active.image.tobytes(), original)

    def test_paste_adds_selected_layer_above_active_without_altering_source_or_lower_layers(self):
        doc = Document.new(20, 10)
        pixels = Image.new("RGBA", (8, 4), (50, 100, 150, 80))
        after = op.paste_layer(doc, pixels)
        self.assertEqual(len(after.layers), 2)
        self.assertEqual(after.active_id, after.layers[1].id)
        self.assertEqual((after.active.x, after.active.y), (6, 3))
        self.assertIs(after.layers[0].image, doc.active.image)
        self.assertEqual(after.active.image.tobytes(), pixels.tobytes())
        after = op.paste_layer(after, pixels, (-3, 12))
        self.assertEqual((after.active.x, after.active.y), (-3, 12))
        self.assertEqual(len(after.layers), 3)

    def test_quarter_turns_are_lossless_clockwise_and_counterclockwise(self):
        image = Image.new("RGBA", (4, 2))
        image.putdata([(i * 30, 20, 100, 255) for i in range(8)])
        doc = Document.from_image(image)
        target = op.extract_target(doc)
        clockwise = op.transform(doc, target, (1, -1, 3, 3), quarter_turns=1)
        self.assertEqual(clockwise.active.image.size, (2, 4))
        self.assertEqual(clockwise.active.image.getpixel((0, 0)), image.getpixel((0, 1)))
        self.assertEqual(clockwise.active.image.getpixel((1, 3)), image.getpixel((3, 0)))
        counterclockwise = op.transform(doc, target, (1, -1, 3, 3), quarter_turns=-1)
        self.assertEqual(counterclockwise.active.image.getpixel((0, 0)), image.getpixel((3, 0)))
        unchanged = op.transform(doc, target, (0, 0, 4, 2), quarter_turns=4)
        self.assertEqual(unchanged.active.image.tobytes(), image.tobytes())
        self.assertEqual(doc.active.image.tobytes(), image.tobytes())

    def test_rotated_lasso_geometry_follows_rotated_pixels(self):
        selection = Selection("lasso", ((2, 2), (8, 2), (2, 6)))
        clockwise = selection.transformed((2, 2, 8, 6), (10, 10, 14, 16), quarter_turns=1)
        self.assertEqual(clockwise.points, ((14, 10), (14, 16), (10, 10)))
        counterclockwise = selection.transformed((2, 2, 8, 6), (10, 10, 14, 16), quarter_turns=-1)
        self.assertEqual(counterclockwise.points, ((10, 16), (10, 10), (14, 16)))
        doc = replace(Document.new(20, 20), selection=selection)
        target = op.extract_target(doc)
        rotated = op.transform(doc, target, (10, 10, 14, 16), quarter_turns=1)
        self.assertEqual(rotated.selection.points, clockwise.points)
        self.assertEqual(composite(rotated).getpixel((3, 3))[3], 0)
        self.assertEqual(composite(rotated).getpixel((1, 1))[3], 255)

    def test_merge_preserves_offsets_transparency_and_pixels_outside_canvas(self):
        doc = Document.from_image(Image.new("RGBA", (20, 10)))
        bottom = Layer("Bottom", Image.new("RGBA", (8, 5), (255, 0, 0, 100)), -3, -2)
        top = Layer("Top", Image.new("RGBA", (6, 6), (0, 0, 255, 140)), 1, 1)
        doc = doc.edited(layers=doc.layers + (bottom, top), active_id=top.id,
                         selected_ids=frozenset({bottom.id, top.id}))
        before = composite(doc)
        merged = op.merge_layers(doc)
        self.assertEqual(len(merged.layers), 2)
        self.assertIs(merged.layers[0], doc.layers[0])
        self.assertEqual((merged.active.x, merged.active.y), (-3, -2))
        self.assertEqual(merged.active.image.size, (10, 9))
        self.assertEqual(merged.active.image.getpixel((0, 0)), (255, 0, 0, 100))
        self.assertEqual(composite(merged).tobytes(), before.tobytes())
        self.assertEqual(merged.selected_ids, frozenset({merged.active_id}))
        self.assertEqual(bottom.image.getpixel((0, 0)), (255, 0, 0, 100))

    def test_merge_nonadjacent_layers_retains_unselected_layer_order(self):
        layers = tuple(Layer(str(i), Image.new("RGBA", (3, 3), (i * 30, 0, 0, 255))) for i in range(5))
        doc = Document(3, 3, layers, layers[3].id, selected_ids=frozenset({layers[1].id, layers[3].id}))
        merged = op.merge_layers(doc)
        self.assertEqual([layer.id for layer in merged.layers],
                         [layers[0].id, layers[2].id, merged.active_id, layers[4].id])
        self.assertEqual(merged.active.image.getpixel((0, 0)), layers[3].image.getpixel((0, 0)))

    def test_hidden_layers_do_not_appear_in_visible_merge_and_hidden_group_stays_hidden(self):
        bottom = Layer("Bottom", Image.new("RGBA", (4, 4), "red"))
        top = Layer("Top", Image.new("RGBA", (4, 4), "blue"), visible=False)
        doc = Document(4, 4, (bottom, top), top.id, selected_ids=frozenset({bottom.id, top.id}))
        merged = op.merge_layers(doc)
        self.assertTrue(merged.active.visible)
        self.assertEqual(merged.active.image.getpixel((0, 0)), (255, 0, 0, 255))
        hidden = doc.edited(layers=(replace(bottom, visible=False), top))
        merged = op.merge_layers(hidden)
        self.assertFalse(merged.active.visible)
        self.assertEqual(merged.active.image.getpixel((0, 0)), (0, 0, 255, 255))

    def test_merge_requires_multiple_layers_and_undo_restores_the_selection(self):
        doc = Document.new(10, 10)
        with self.assertRaises(ValueError):
            op.merge_layers(doc)
        doc = op.duplicate_layer(doc)
        doc = replace(doc, selected_ids=frozenset(layer.id for layer in doc.layers))
        merged = op.merge_layers(doc)
        history = History()
        history.push("Merge layers", doc, merged)
        restored = history.undo()
        self.assertEqual(restored.selected_ids, doc.selected_ids)
        self.assertEqual(restored.layers, doc.layers)
        self.assertEqual(history.redo().layers, merged.layers)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_all_raster_formats_open_at_exact_source_dimensions(self):
        for suffix in (".png", ".jpg", ".webp"):
            path = self.directory / ("source" + suffix)
            Image.new("RGB", (67, 31), "red").save(path)
            doc = files.open_document(path)
            self.assertEqual((doc.width, doc.height), (67, 31))
            self.assertEqual(len(doc.layers), 1)
            self.assertEqual(doc.active.image.size, (67, 31))

    def test_project_round_trip_retains_layers_alpha_offsets_visibility_and_active_id(self):
        doc = op.add_layer(Document.new(20, 10))
        doc = doc.with_layer(replace(doc.active, name="半透明 texture", x=-5, y=4,
                                    image=Image.new("RGBA", (8, 6), (30, 40, 50, 100)), visible=False))
        path = self.directory / "test.rasterly"
        files.save_project(doc, path)
        loaded = files.open_document(path)
        self.assertEqual((loaded.width, loaded.height), (20, 10))
        self.assertEqual(loaded.active_id, doc.active_id)
        for before, after in zip(doc.layers, loaded.layers):
            self.assertEqual((before.id, before.name, before.x, before.y, before.visible),
                             (after.id, after.name, after.x, after.y, after.visible))
            self.assertEqual(before.image.tobytes(), after.image.tobytes())

    def test_export_flattens_visibility_and_jpeg_transparency_becomes_white(self):
        doc = Document.from_image(Image.new("RGBA", (20, 10)))
        doc = op.add_layer(doc)
        doc = doc.with_layer(replace(doc.active, image=Image.new("RGBA", (5, 5), "red")))
        for suffix in (".png", ".webp", ".jpg"):
            path = self.directory / ("export" + suffix)
            files.export_image(doc, path)
            reopened = files.open_document(path)
            self.assertEqual(reopened.active.image.size, (20, 10))
            if suffix != ".jpg":
                self.assertEqual(reopened.active.image.getpixel((10, 8))[3], 0)
            else:
                pixel = reopened.active.image.getpixel((18, 8))
                self.assertTrue(all(value > 245 for value in pixel[:3]))

    def test_failed_atomic_save_keeps_existing_file_intact(self):
        path = self.directory / "important.rasterly"
        path.write_bytes(b"original")
        def fail(temporary):
            Path(temporary).write_bytes(b"partial")
            raise OSError("simulated disk error")
        with self.assertRaises(OSError):
            files._atomic_write(path, fail)
        self.assertEqual(path.read_bytes(), b"original")

    def test_project_round_trip_retains_multiple_selected_layers(self):
        doc = op.duplicate_layer(op.add_layer(Document.new(20, 10)))
        selected = frozenset({doc.layers[0].id, doc.layers[2].id})
        doc = replace(doc, selected_ids=selected)
        path = self.directory / "multi-selected.rasterly"
        files.save_project(doc, path)
        loaded = files.open_document(path)
        self.assertEqual(loaded.selected_ids, selected)
        self.assertEqual(loaded.active_id, doc.active_id)


if __name__ == "__main__":
    unittest.main()
