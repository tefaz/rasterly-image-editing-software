"""Installed-font dropdown with a bounded list below its control."""
from pathlib import Path
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import QComboBox, QFontComboBox


class FontSizePicker(QComboBox):
    """Common pixel sizes, with custom integers committed on Enter or focus loss."""
    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 48
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.addItems([str(size) for size in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24,
                                            28, 32, 36, 48, 60, 64, 72, 96, 120, 144)])
        self.setMaxVisibleItems(12)
        self.lineEdit().setValidator(QIntValidator(1, 2048, self))
        self.lineEdit().editingFinished.connect(self.commit_size)
        self.activated.connect(self.commit_size)
        self.setValue(self._value)
        self.setToolTip("Font size in pixels · Choose a size or type any value from 1 to 2048")
        self.setAccessibleName("Font size in pixels")
        arrow = Path(__file__).resolve().parents[1] / "resources" / "chevron-down.svg"
        self.setStyleSheet(
            'QComboBox { combobox-popup: 0; }'
            f'QComboBox::down-arrow {{ image: url("{arrow.as_posix()}"); width: 10px; height: 6px; }}')

    def value(self):
        return self._value

    def setValue(self, value):
        value = max(1, min(2048, int(value)))
        changed = value != self._value
        self._value = value
        self.setCurrentIndex(self.findText(str(value)))
        self.setEditText(str(value))
        if changed:
            self.valueChanged.emit(value)

    def commit_size(self, *args):
        text = self.currentText().strip()
        self.setValue(int(text) if text.isdigit() and 1 <= int(text) <= 2048 else self._value)

    def focusOutEvent(self, event):
        self.commit_size()
        super().focusOutEvent(event)


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
