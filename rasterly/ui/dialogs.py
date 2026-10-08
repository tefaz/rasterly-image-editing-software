from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
                            QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
                            QDialogButtonBox, QColorDialog, QButtonGroup, QGridLayout,
                            QWidget)
from ..model import validate_size, MAX_SIDE


def buttons(dialog, label="OK"):
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Ok).setText(label)
    box.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class NewDialog(QDialog):
    def __init__(self, parent=None, *, settings=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings("Rasterly", "Rasterly")
        self.setWindowTitle("New image")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        title = QLabel("A fresh canvas")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        subtitle = QLabel("One white background layer. Ready to edit.")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        form = QFormLayout()
        self.preset = QComboBox()
        for name, size in [("Full HD — 1920 × 1080", (1920, 1080)),
                           ("QHD — 2560 × 1440", (2560, 1440)),
                           ("4K UHD — 3840 × 2160", (3840, 2160)),
                           ("Square — 1080 × 1080", (1080, 1080)),
                           ("Custom", None)]:
            self.preset.addItem(name, size)
        self.width_input, self.height_input = QSpinBox(), QSpinBox()
        for spin in (self.width_input, self.height_input):
            spin.setRange(1, MAX_SIDE)
            spin.setSuffix(" px")
        try:
            width = int(self.settings.value("newCanvas/width", 1920))
            height = int(self.settings.value("newCanvas/height", 1080))
            validate_size(width, height)
        except (TypeError, ValueError, OverflowError):
            width, height = 1920, 1080
        self.width_input.setValue(width)
        self.height_input.setValue(height)
        preset = next((index for index in range(self.preset.count())
                       if self.preset.itemData(index) == (width, height)), self.preset.count() - 1)
        self.preset.setCurrentIndex(preset)
        form.addRow("Preset", self.preset)
        form.addRow("Width", self.width_input)
        form.addRow("Height", self.height_input)
        layout.addLayout(form)
        self.warning = QLabel()
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)
        layout.addWidget(buttons(self, "Create"))
        self.preset.currentIndexChanged.connect(self.choose_preset)
        self.width_input.valueChanged.connect(self.custom_size)
        self.height_input.valueChanged.connect(self.custom_size)

    def choose_preset(self):
        size = self.preset.currentData()
        if size:
            self.width_input.blockSignals(True)
            self.height_input.blockSignals(True)
            self.width_input.setValue(size[0])
            self.height_input.setValue(size[1])
            self.width_input.blockSignals(False)
            self.height_input.blockSignals(False)

    def custom_size(self):
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(self.preset.count() - 1)
        self.preset.blockSignals(False)

    @property
    def dimensions(self):
        return self.width_input.value(), self.height_input.value()

    def remember_dimensions(self):
        width, height = self.dimensions
        self.settings.setValue("newCanvas/width", width)
        self.settings.setValue("newCanvas/height", height)
        self.settings.sync()

    def accept(self):
        try:
            validate_size(*self.dimensions)
            super().accept()
        except ValueError as error:
            self.warning.setText(str(error))


class SizeDialog(QDialog):
    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.document = document
        self.updating = False
        self.setWindowTitle("Image Size / Canvas Size")
        self.setMinimumWidth(410)
        layout = QVBoxLayout(self)
        title = QLabel("Image & canvas size")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        label = QLabel(f"Current dimensions   {document.width:,} × {document.height:,} px")
        label.setObjectName("muted")
        layout.addWidget(label)
        layout.addSpacing(12)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Image Size", "Canvas Size"])
        self.units = QComboBox()
        self.units.addItems(["Pixels", "Percentage"])
        self.width_input, self.height_input = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.width_input, self.height_input):
            spin.setRange(1, MAX_SIDE)
            spin.setDecimals(0)
            spin.setSuffix(" px")
        self.width_input.setValue(document.width)
        self.height_input.setValue(document.height)
        self.lock = QCheckBox("Lock original aspect ratio")
        self.lock.setChecked(True)
        form.addRow("Change", self.mode)
        form.addRow("Units", self.units)
        form.addRow("Width", self.width_input)
        form.addRow("Height", self.height_input)
        form.addRow("", self.lock)
        layout.addLayout(form)
        self.anchor_widget = QWidget()
        anchor_layout = QHBoxLayout(self.anchor_widget)
        anchor_layout.setContentsMargins(0, 0, 0, 0)
        anchor_layout.addWidget(QLabel("Keep existing image at"))
        grid = QGridLayout()
        grid.setSpacing(3)
        self.anchor_group = QButtonGroup(self)
        names = ["Top-left", "Top-center", "Top-right", "Center-left", "Center", "Center-right",
                 "Bottom-left", "Bottom-center", "Bottom-right"]
        for i, name in enumerate(names):
            button = QPushButton("●" if i == 4 else "·")
            button.setObjectName("anchor")
            button.setCheckable(True)
            button.setFixedSize(32, 32)
            button.setToolTip(name)
            self.anchor_group.addButton(button, i)
            grid.addWidget(button, i // 3, i % 3)
            button.setChecked(i == 4)
        anchor_layout.addLayout(grid)
        layout.addWidget(self.anchor_widget)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setObjectName("muted")
        layout.addWidget(self.description)
        self.warning = QLabel()
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)
        layout.addWidget(buttons(self, "Apply"))
        self.units.currentIndexChanged.connect(self.change_units)
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.width_input.valueChanged.connect(lambda: self.sync_ratio(True))
        self.height_input.valueChanged.connect(lambda: self.sync_ratio(False))
        self.change_mode()

    def change_mode(self):
        image_mode = self.mode.currentIndex() == 0
        self.lock.setVisible(image_mode)
        self.anchor_widget.setVisible(not image_mode)
        self.description.setText("Resamples all layers using Lanczos interpolation." if image_mode else
                                 "Adds or removes canvas space. Layer pixels keep their original size; extra space is transparent.")

    def change_units(self):
        self.updating = True
        percentage = self.units.currentIndex() == 1
        for spin, original in ((self.width_input, self.document.width), (self.height_input, self.document.height)):
            value = spin.value()
            spin.setDecimals(2 if percentage else 0)
            spin.setRange(0.01 if percentage else 1, 10000 if percentage else MAX_SIDE)
            spin.setSuffix(" %" if percentage else " px")
            spin.setValue(value / original * 100 if percentage else value / 100 * original)
        self.updating = False

    def sync_ratio(self, width_changed):
        if self.updating or not self.lock.isChecked() or self.mode.currentIndex() != 0:
            return
        self.updating = True
        if self.units.currentIndex() == 1:
            if width_changed:
                self.height_input.setValue(self.width_input.value())
            else:
                self.width_input.setValue(self.height_input.value())
        elif width_changed:
            self.height_input.setValue(self.width_input.value() * self.document.height / self.document.width)
        else:
            self.width_input.setValue(self.height_input.value() * self.document.width / self.document.height)
        self.updating = False

    @property
    def dimensions(self):
        if self.units.currentIndex() == 1:
            return (max(1, round(self.document.width * self.width_input.value() / 100)),
                    max(1, round(self.document.height * self.height_input.value() / 100)))
        return round(self.width_input.value()), round(self.height_input.value())

    @property
    def anchor(self):
        index = self.anchor_group.checkedId()
        return (index % 3) / 2, (index // 3) / 2

    def accept(self):
        try:
            validate_size(*self.dimensions)
            super().accept()
        except ValueError as error:
            self.warning.setText(str(error))


class FillDialog(QDialog):
    def __init__(self, parent=None, color=None):
        super().__init__(parent)
        self.setWindowTitle("Fill Selection")
        self.setMinimumWidth(350)
        self.color = QColor(color) if color is not None else QColor("#ffffff")
        layout = QVBoxLayout(self)
        title = QLabel("Fill selection")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Content-Aware", "Solid Color"])
        form.addRow("Fill with", self.mode)
        self.color_button = QPushButton("Choose color…")
        if color is not None:
            self.color_button.setText(self.color.name().upper())
            self.color_button.setStyleSheet(f"border-left: 12px solid {self.color.name()};")
        self.color_button.clicked.connect(self.choose_color)
        form.addRow("", self.color_button)
        layout.addLayout(form)
        self.description = QLabel("Reconstructs the selection using surrounding pixels on the active layer.")
        self.description.setWordWrap(True)
        self.description.setObjectName("muted")
        layout.addWidget(self.description)
        layout.addSpacing(12)
        layout.addWidget(buttons(self))
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.change_mode()

    def change_mode(self):
        self.color_button.setVisible(self.mode.currentIndex() == 1)
        self.description.setText("Reconstructs the selection using surrounding pixels on the active layer."
                                 if self.mode.currentIndex() == 0 else "Fills only the selected area on the active layer.")

    def choose_color(self):
        color = QColorDialog.getColor(self.color, self, "Fill color")
        if color.isValid():
            self.color = color
            self.color_button.setText(color.name().upper())
            self.color_button.setStyleSheet(f"border-left: 12px solid {color.name()};")
