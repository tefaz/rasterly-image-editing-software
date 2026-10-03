"""Qt text layout and full-resolution RGBA rendering for editable type layers."""
import math
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QTextDocument, QTextOption, QTransform
from .model import validate_size

ALIGNMENTS = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
              "right": Qt.AlignmentFlag.AlignRight}


def text_font(data, scale=1.0, dpi=96):
    font = QFont(data.family)
    # Fractional point sizes let the inline editor follow any viewport zoom.
    font.setPointSizeF(data.size * scale * 72 / dpi)
    font.setBold(data.bold)
    font.setItalic(data.italic)
    return font


def text_document(data):
    document = QTextDocument()
    document.setDocumentMargin(2)
    font = text_font(data)
    font.setPixelSize(data.size)
    document.setDefaultFont(font)
    option = QTextOption(ALIGNMENTS[data.alignment])
    option.setWrapMode(QTextOption.WrapMode.NoWrap)
    document.setDefaultTextOption(option)
    document.setPlainText(data.content)
    document.adjustSize()
    return document


def text_geometry(data, document):
    """Map a natural text layout into its fitted, rotated and flipped layer box."""
    natural_width = max(1, math.ceil(document.size().width()))
    natural_height = max(1, math.ceil(document.size().height()))
    width, height = data.box_size or ((natural_height, natural_width) if data.quarter_turns % 2 else
                                      (natural_width, natural_height))
    validate_size(width, height)
    unrotated_width, unrotated_height = (height, width) if data.quarter_turns % 2 else (width, height)
    mapping = QTransform()
    mapping.translate(width / 2, height / 2)
    mapping.scale(-1 if data.flip_x else 1, -1 if data.flip_y else 1)
    mapping.rotate(90 * data.quarter_turns)
    mapping.scale(unrotated_width / natural_width, unrotated_height / natural_height)
    mapping.translate(-natural_width / 2, -natural_height / 2)
    return (width, height), mapping


def render_text(data):
    document = text_document(data)
    (width, height), mapping = text_geometry(data, document)
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setTransform(mapping)
    context = document.documentLayout().PaintContext()
    context.palette.setColor(context.palette.ColorRole.Text, QColor(*data.color))
    document.documentLayout().draw(painter, context)
    painter.end()
    pixels = image.constBits()
    pixels.setsize(image.sizeInBytes())
    return Image.frombytes("RGBA", (width, height), bytes(pixels), "raw", "RGBA", image.bytesPerLine())
