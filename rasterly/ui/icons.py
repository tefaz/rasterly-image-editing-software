from PyQt6.QtCore import QByteArray, Qt, QRectF
from PyQt6.QtGui import QCursor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

PATHS = {
    "folder": '<path d="M3 7V4h7l3 3h8v13H3V7zM3 9h18"/>',
    "brush": '<path d="M10 14L18 4c2-2 4 0 2 2l-8 10M10 14l2 2M10 14c-5-2-3 7-8 6 6 2 12-2 10-6"/>',
    "eraser": '<path d="M3 14l10-11 9 8-10 11H7l-4-4c-1-1-1-3 0-4zM8 9l9 8M12 22h10"/>',
    "bucket": '<path d="M5 3l10 10M4 10l6-6 9 9-8 8-9-9zM3 13h15M20 14s3 4 3 6a3 3 0 0 1-6 0c0-2 3-6 3-6z"/>',
    "gradient": '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="M6 5v14M9 5v14M12 5v14M15 5v14"/><path d="M4 5v14M5 5v14M7 5v14M8 5v14" opacity=".55"/>',
    "text": '<path d="M5 5h14M12 5v15M8 20h8M5 5v3M19 5v3"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "move": '<path d="M12 3v18M3 12h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/>',
    "rectangle": '<rect x="4" y="5" width="16" height="14" stroke-dasharray="3 2"/>',
    "lasso": '<path d="M8 17C1 16 2 6 10 4s14 6 9 10-10 4-12 1 1-5 4-3 2 6-2 9"/>',
    "patch": '<g transform="rotate(-42 12 12)"><rect x="3" y="7" width="18" height="10" rx="3"/><path d="M9 7v10M15 7v10M11 10h2M11 14h2"/></g>',
    "crop": '<path d="M7 2v15h15M2 7h15v15M10 3h11v11"/>',
    "transform": '<rect x="5" y="5" width="14" height="14"/><rect x="3" y="3" width="4" height="4" fill="#c3c7cf"/><rect x="17" y="17" width="4" height="4" fill="#c3c7cf"/>',
    "new": '<path d="M12 5v14M5 12h14"/>',
    "delete": '<path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7"/>',
    "duplicate": '<rect x="8" y="8" width="12" height="12" rx="1"/><path d="M15 8V4H4v11h4"/>',
    "up": '<path d="M6 15l6-6 6 6"/>',
    "down": '<path d="M6 9l6 6 6-6"/>',
    "fit": '<path d="M3 9V3h6M15 3h6v6M21 15v6h-6M9 21H3v-6"/>',
    "size": '<rect x="4" y="5" width="16" height="14"/><path d="M8 15l8-6M11 9h5v5"/>',
    "fill": '<path d="M4 11l8-8 8 8-8 8-8-8M4 11h16M9 2l7 7M19 17s4 4 0 5-3-3 0-5"/>',
    "save": '<path d="M4 3h14l3 3v15H3V3h1M7 3v7h10V3M7 21v-7h10v7"/>',
    "open": '<path d="M3 19V5h7l2 3h9v3M3 19l3-8h16l-3 8H3"/>',
}


def icon(name, color="#c3c7cf", size=24):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</g></svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)


def tool_cursor(name, size=28):
    """Reuse tool artwork with a dark halo for visibility over image pixels."""
    artwork = PATHS[name]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<g fill="none" stroke="#111316" stroke-width="3.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{artwork}</g>'
        f'<g fill="none" stroke="#ffffff" stroke-width="1.45" '
        f'stroke-linecap="round" stroke-linejoin="round">{artwork}</g></svg>'
    )
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QCursor(pixmap, size // 2, size // 2)
