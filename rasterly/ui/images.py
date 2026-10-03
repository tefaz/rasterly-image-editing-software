from PyQt6.QtGui import QImage


def qimage(image):
    pixels = image if image.mode == "RGBA" else image.convert("RGBA")
    data = pixels.tobytes()
    return QImage(data, pixels.width, pixels.height, pixels.width * 4,
                  QImage.Format.Format_RGBA8888).copy()
