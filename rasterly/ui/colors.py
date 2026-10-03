"""Foreground color controls: RGB channels and a mirrored saturation/value field."""
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                            QPushButton, QSlider, QSpinBox, QColorDialog, QSizePolicy, QLineEdit)


class ColorField(QWidget):
    color_changed = pyqtSignal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hue, self.saturation, self.value = 0.0, 0.0, 0.0
        self.setMinimumHeight(116)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAccessibleName("Color rectangle")
        self.setToolTip("Drag to choose a color · White at top-right · Black along the bottom")

    @property
    def color(self):
        return QColor.fromHsvF(self.hue, self.saturation, self.value)

    def set_color(self, color):
        hue, self.saturation, self.value, _ = color.getHsvF()
        if hue >= 0:
            self.hue = hue
        self.update()

    def set_hue(self, hue):
        self.hue = hue % 1.0
        self.update()

    def color_at(self, point):
        saturation = 1 - max(0.0, min(1.0, point.x() / max(1, self.width() - 1)))
        value = 1 - max(0.0, min(1.0, point.y() / max(1, self.height() - 1)))
        return QColor.fromHsvF(self.hue, saturation, value)

    def choose(self, point):
        self.set_color(self.color_at(point))
        self.color_changed.emit(self.color)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.choose(event.position())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.choose(event.position())
            event.accept()

    def keyPressEvent(self, event):
        steps = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                 Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if event.key() in steps:
            dx, dy = steps[event.key()]
            self.saturation = max(0.0, min(1.0, self.saturation - dx / 255))
            self.value = max(0.0, min(1.0, self.value - dy / 255))
            self.update()
            self.color_changed.emit(self.color)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        horizontal = QLinearGradient(0.5, 0, max(1.5, self.width() - 0.5), 0)
        horizontal.setColorAt(0, QColor.fromHsvF(self.hue, 1, 1))
        horizontal.setColorAt(1, QColor("white"))
        painter.fillRect(self.rect(), horizontal)
        vertical = QLinearGradient(0, 0.5, 0, max(1.5, self.height() - 0.5))
        vertical.setColorAt(0, QColor(0, 0, 0, 0))
        vertical.setColorAt(1, QColor("black"))
        painter.fillRect(self.rect(), vertical)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        point = QPointF((1 - self.saturation) * (self.width() - 1), (1 - self.value) * (self.height() - 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawEllipse(point, 5, 5)
        painter.setPen(QPen(QColor("#111316"), 1))
        painter.drawEllipse(point, 6, 6)


class HueStrip(QWidget):
    hue_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hue = 0.0
        self.setFixedWidth(16)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Hue")
        self.setToolTip("Choose a hue, then choose its shade in the color rectangle")

    def set_hue(self, hue):
        self.hue = max(0.0, min(359 / 360, hue))
        self.update()

    def choose(self, point):
        self.set_hue(point.y() / max(1, self.height() - 1))
        self.hue_changed.emit(self.hue)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.choose(event.position())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.choose(event.position())
            event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.set_hue(self.hue + (-1 if event.key() == Qt.Key.Key_Up else 1) / 360)
            self.hue_changed.emit(self.hue)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, max(1, self.height() - 1))
        for index in range(7):
            gradient.setColorAt(index / 6, QColor.fromHsvF((index / 6) % 1, 1, 1))
        painter.fillRect(self.rect(), gradient)
        y = self.hue * (self.height() - 1)
        painter.setPen(QPen(QColor("#111316"), 3))
        painter.drawRect(QRectF(0.5, y - 2, self.width() - 1, 4))
        painter.setPen(QPen(QColor("white"), 1))
        painter.drawRect(QRectF(0.5, y - 2, self.width() - 1, 4))


class ChannelSlider(QSlider):
    def __init__(self, color, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 255)
        self.setStyleSheet(
            'QSlider::groove:horizontal { height: 10px; border: 1px solid #697382; border-radius: 3px; '
            f'background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {color}, stop:1 white); }}'
            'QSlider::handle:horizontal { background: #e7edf8; border: 1px solid #17191e; '
            'width: 7px; margin: -4px 0; border-radius: 2px; }')

    def choose(self, event):
        self.setValue(0 if self.width() <= 8 else
                      round(max(0.0, min(1.0, (event.position().x() - 4) / (self.width() - 8))) * 255))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.setSliderDown(True)
            self.choose(event)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.choose(event)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.choose(event)
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ColorPanel(QWidget):
    color_changed = pyqtSignal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor("black")
        self.setObjectName("colorPanel")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        heading = QWidget()
        heading.setObjectName("panelHeader")
        header = QHBoxLayout(heading)
        header.setContentsMargins(16, 10, 14, 10)
        header.addWidget(QLabel("COLOR"))
        layout.addWidget(heading)
        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(14, 12, 14, 14)
        content.setSpacing(12)
        controls = QHBoxLayout()
        controls.setSpacing(12)
        foreground = QVBoxLayout()
        foreground.setSpacing(4)
        label = QLabel("Foreground")
        label.setObjectName("muted")
        foreground.addWidget(label)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(56, 56)
        self.swatch.setAccessibleName("Foreground color")
        self.swatch.clicked.connect(self.choose_color)
        foreground.addWidget(self.swatch)
        self.hex_input = QLineEdit()
        self.hex_input.setFixedSize(76, 24)
        self.hex_input.setStyleSheet("QLineEdit { padding: 2px 4px; font-size: 11px; }")
        self.hex_input.setAccessibleName("Hex color")
        self.hex_input.setToolTip("Copy or paste #RRGGBB or #RGB, with or without # · Enter to apply")
        self.hex_input.editingFinished.connect(self.apply_hex)
        foreground.addWidget(self.hex_input)
        controls.addLayout(foreground)
        channels = QGridLayout()
        channels.setHorizontalSpacing(5)
        channels.setVerticalSpacing(4)
        self.sliders, self.values = [], []
        for index, (name, color) in enumerate(zip("RGB", ("#ff0000", "#00ff00", "#0000ff"))):
            label = QLabel(name)
            label.setStyleSheet(f"color: {color}; font-weight: 600;")
            slider = ChannelSlider(color)
            slider.setAccessibleName({"R": "Red", "G": "Green", "B": "Blue"}[name])
            slider.setToolTip(f"{slider.accessibleName()} channel")
            value = QSpinBox()
            value.setRange(0, 255)
            value.setFixedWidth(43)
            value.setFixedHeight(24)
            value.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            value.setStyleSheet("QSpinBox { padding: 2px; }")
            value.setAccessibleName(f"{slider.accessibleName()} value")
            slider.valueChanged.connect(lambda amount, index=index: self.set_channel(index, amount))
            value.valueChanged.connect(lambda amount, index=index: self.set_channel(index, amount))
            self.sliders.append(slider)
            self.values.append(value)
            channels.addWidget(label, index, 0)
            channels.addWidget(slider, index, 1)
            channels.addWidget(value, index, 2)
        channels.setColumnStretch(1, 1)
        controls.addLayout(channels, 1)
        content.addLayout(controls)
        field = QHBoxLayout()
        field.setSpacing(8)
        self.field = ColorField()
        self.hue = HueStrip()
        field.addWidget(self.field, 1)
        field.addWidget(self.hue)
        content.addLayout(field)
        layout.addWidget(body)
        self.field.color_changed.connect(self.set_color)
        self.hue.hue_changed.connect(self.choose_hue)
        self.set_color(self._color, emit=False)
        self.ensurePolished()
        self.setMinimumHeight(self.minimumSizeHint().height())

    @property
    def color(self):
        return QColor(self._color)

    def set_color(self, color, emit=True):
        if not color.isValid():
            return
        color = QColor(*color.getRgb())
        changed = color != self._color
        self._color = color
        if self.field.color.getRgb() != color.getRgb():
            self.field.set_color(color)
        self.hue.set_hue(self.field.hue)
        for slider, value, amount in zip(self.sliders, self.values, color.getRgb()[:3]):
            for widget in (slider, value):
                widget.blockSignals(True)
                widget.setValue(amount)
                widget.blockSignals(False)
        self.hex_input.setText(color.name().upper())
        self.swatch.setToolTip(f"Foreground: {color.name().upper()} · Click to choose a color")
        self.swatch.setStyleSheet(f"QPushButton {{ background: {color.name()}; border: 2px solid #9aa6b9; border-radius: 3px; padding: 0; }}")
        if changed and emit:
            self.color_changed.emit(QColor(color))

    def set_channel(self, index, amount):
        channels = list(self._color.getRgb())
        channels[index] = amount
        self.set_color(QColor(*channels))

    def apply_hex(self):
        value = self.hex_input.text().strip().removeprefix("#")
        color = QColor("#" + value) if len(value) in (3, 6) else QColor()
        if color.isValid():
            self.set_color(color)
        else:
            self.hex_input.setText(self._color.name().upper())

    def choose_hue(self, hue):
        self.field.set_hue(hue)
        self.set_color(self.field.color)

    def choose_color(self):
        color = QColorDialog.getColor(self._color, self, "Foreground color")
        if color.isValid():
            self.set_color(color)
