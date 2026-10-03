"""Installed-font dropdown with a bounded list below its control."""
from pathlib import Path
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QFontComboBox


class FontPicker(QFontComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(False)
        self.setMaxVisibleItems(18)
        self.view().setMinimumWidth(280)
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        arrow = Path(__file__).resolve().parents[1] / "resources" / "chevron-down.svg"
        self.setStyleSheet(
            'QComboBox { combobox-popup: 0; }'
            f'QComboBox::down-arrow {{ image: url("{arrow.as_posix()}"); width: 10px; height: 6px; }}')
        self.setToolTip("Choose from fonts installed on this system")
        self.setAccessibleName("Installed fonts")

    def showPopup(self):
        anchor = self.mapToGlobal(QPoint(0, self.height()))
        screen = self.screen().availableGeometry()
        available_height = screen.bottom() - anchor.y() + 1
        if available_height <= 0:
            return
        view = self.view()
        minimum_width = view.minimumWidth()
        view.setMaximumHeight(available_height)
        super().showPopup()
        # Qt may otherwise align the selected font with the control or flip the
        # popup upward near a screen edge. Keep the list below and scroll instead.
        popup = view.window()
        width = min(screen.width(), max(self.width(), minimum_width, popup.width()))
        left = max(screen.left(), min(anchor.x(), screen.right() - width + 1))
        popup.setFixedWidth(width)
        popup.setGeometry(left, anchor.y(), width, min(popup.height(), available_height))
