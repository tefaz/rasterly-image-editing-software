import argparse
import sys
from . import __version__
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication
from .ui.style import STYLE
from .ui.window import EditorWindow


def main():
    parser = argparse.ArgumentParser(description="Rasterly desktop image editor")
    parser.add_argument("--version", action="version", version=f"Rasterly {__version__}")
    parser.add_argument("image", nargs="?", help="PNG, JPEG, WebP or .rasterly file to open")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Rasterly")
    app.setOrganizationName("Rasterly")
    app.setDesktopFileName("Rasterly")
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, "#292c33"),
                        (QPalette.ColorRole.WindowText, "#d2d5dc"),
                        (QPalette.ColorRole.Base, "#20232a"),
                        (QPalette.ColorRole.Text, "#e1e5ed"),
                        (QPalette.ColorRole.Button, "#363b45"),
                        (QPalette.ColorRole.ButtonText, "#d2d5dc"),
                        (QPalette.ColorRole.Highlight, "#536c9e"),
                        (QPalette.ColorRole.HighlightedText, "#ffffff")]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    window = EditorWindow()
    window.show()
    if args.image:
        window.open_document(args.image)
    return app.exec()
