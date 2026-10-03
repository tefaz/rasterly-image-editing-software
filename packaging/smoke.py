"""Exercise the actual frozen runtime, Qt plugins, pixels, history, and files."""
from pathlib import Path
import tempfile


def run():
    import numpy as np
    from PIL import Image
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtSvg import QSvgRenderer
    from rasterly import __version__, files, operations
    from rasterly.model import Document, composite
    from rasterly.selection import Selection
    from rasterly.ui.window import EditorWindow
    from rasterly.ui.style import STYLE
    from rasterly.processing import LocalInpaintingEngine

    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = EditorWindow()
    window.show()
    app.processEvents()
    assert window.controller.document is None, "Startup must have no image tab"
    assert window.actions["new"].isEnabled()
    assert window.actions["open"].isEnabled()
    assert not window.windowIcon().isNull(), "Frozen icon missing"
    import rasterly
    icon = Path(rasterly.__file__).parent / "resources" / "rasterly.svg"
    assert QSvgRenderer(str(icon)).isValid(), "Qt SVG plugin or resource missing"

    first = Document.new(64, 48)
    window.controller.replace_document(first)
    selection = Selection.rectangle(4, 4, 24, 24).united(
        Selection.rectangle(32, 4, 44, 16)).subtracted(
        Selection.rectangle(8, 8, 16, 16))
    assert window.controller.set_selection(selection, "Selection smoke check")
    selected = window.controller.document
    assert window.controller.history.position == 1
    window.controller.toggle_undo()
    assert window.controller.document.selection is None
    window.controller.toggle_undo()
    assert window.controller.document.selection == selection
    filled = operations.solid_fill(selected, (255, 0, 0, 255))
    assert composite(filled).getpixel((5, 5)) == (255, 0, 0, 255)
    assert composite(filled).getpixel((10, 10)) == (255, 255, 255, 255)
    pixels, position = operations.copy_selection(filled)
    assert pixels.getpixel((6, 6))[3] == 0, "Selection hole lost"
    target = operations.extract_target(filled)
    rotated = operations.transform(filled, target, (4, 4, 24, 44), quarter_turns=1)
    assert rotated.selection is not None

    window.controller.add_document(Document.new(80, 60))
    window.apply("Paste smoke check", lambda doc: operations.paste_layer(doc, pixels))
    assert len(window.controller.document.layers) == 2
    assert len(window.controller.sessions) == 2
    window.canvas.set_zoom(32)
    app.processEvents()
    assert window.horizontal_scrollbar.isVisible()
    window.horizontal_scrollbar.setValue(window.horizontal_scrollbar.maximum())
    app.processEvents()
    window.controller.undo()
    assert len(window.controller.document.layers) == 1

    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary) / "smoke.rasterly"
        files.save_project(filled, project)
        reopened = files.open_document(project)
        assert composite(reopened).tobytes() == composite(filled).tobytes()
        for extension in ("png", "jpg", "webp"):
            output = Path(temporary) / f"smoke.{extension}"
            files.export_image(filled, output)
            assert files.open_document(output).width == 64

    image = Image.new("RGBA", (24, 24), (32, 96, 64, 255))
    mask = Image.new("L", image.size)
    mask.paste(255, (10, 10, 14, 14))
    healed = LocalInpaintingEngine().process(image, mask)
    assert healed.size == image.size
    assert np.asarray(healed).shape == (24, 24, 4)

    for session in window.controller.sessions:
        session.saved_revision = session.document.revision
    window.close()
    app.processEvents()
    print(f"Rasterly {__version__}: packaged runtime smoke checks passed", flush=True)
