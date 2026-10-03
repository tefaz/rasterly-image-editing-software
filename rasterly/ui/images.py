from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap

CHECKER_LIGHT = "#c4c8cf"
CHECKER_DARK = "#9298a3"


def qimage(image):
    pixels = image if image.mode == "RGBA" else image.convert("RGBA")
    data = pixels.tobytes()
    return QImage(data, pixels.width, pixels.height, pixels.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


def layer_thumbnail(image, text=False):
    """Render transparency over a checkerboard without changing layer pixels."""
    scale = min(48 / image.width, 36 / image.height)
    thumbnail = image.resize((max(1, round(image.width * scale)),
                              max(1, round(image.height * scale))), reducing_gap=3)
    pixmap = QPixmap(thumbnail.width, thumbnail.height)
    painter = QPainter(pixmap)
    for y in range(0, thumbnail.height, 4):
        for x in range(0, thumbnail.width, 4):
            color = CHECKER_LIGHT if (x // 4 + y // 4) % 2 == 0 else CHECKER_DARK
            painter.fillRect(x, y, 4, 4, QColor(color))
    painter.drawImage(0, 0, qimage(thumbnail))
    if text:
        badge = QRect(max(0, thumbnail.width - 12), max(0, thumbnail.height - 13), 12, 13)
        painter.fillRect(badge, QColor("#24272d"))
        font = QFont("Sans Serif")
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#e1e7f2"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "T")
    painter.end()
    result = QIcon(pixmap)
    # Keep the real colors and checkerboard when Qt highlights the layer row.
    result.addPixmap(pixmap, QIcon.Mode.Selected)
    result.addPixmap(pixmap, QIcon.Mode.Active)
    return result
