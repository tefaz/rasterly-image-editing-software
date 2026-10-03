"""System clipboard images with lossless selection data shared between tabs."""
from dataclasses import dataclass
from uuid import uuid4
import io
from PIL import Image
from PyQt6.QtCore import QObject, QMimeData, QByteArray, QBuffer, QIODevice, pyqtSignal
from PyQt6.QtWidgets import QApplication
from .operations import copy_selection
from .ui.images import qimage

MIME = "application/x-rasterly-selection-id"


@dataclass(frozen=True)
class CopiedSelection:
    image: Image.Image
    position: tuple[int, int]
    source_id: str
    token: str


class SelectionClipboard(QObject):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.system = QApplication.clipboard()
        self.payload = None
        self.system.dataChanged.connect(self.clipboard_changed)

    def clipboard_changed(self):
        mime = self.system.mimeData()
        if self.payload and (mime is None or bytes(mime.data(MIME)) != self.payload.token.encode()):
            self.payload = None
        self.changed.emit()

    @property
    def has_image(self):
        mime = self.system.mimeData()
        return mime is not None and (mime.hasImage() or mime.hasFormat("image/png"))

    def copy(self, document, source_id):
        image, position = copy_selection(document)
        token = uuid4().hex
        self.payload = CopiedSelection(image, position, source_id, token)
        mime = QMimeData()
        mime.setImageData(qimage(image))
        mime.setData(MIME, token.encode())
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        mime.setData("image/png", buffer.getvalue())
        self.system.setMimeData(mime)

    def read(self, destination_id):
        if self.payload:
            return self.payload.image, self.payload.position if self.payload.source_id == destination_id else None
        mime = self.system.mimeData()
        if mime.hasFormat("image/png"):
            with Image.open(io.BytesIO(bytes(mime.data("image/png")))) as image:
                return image.convert("RGBA"), None
        image = self.system.image()
        if image.isNull():
            raise ValueError("The clipboard does not contain an image.")
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("Could not read the clipboard image.")
        with Image.open(io.BytesIO(bytes(encoded))) as pixels:
            return pixels.convert("RGBA"), None
