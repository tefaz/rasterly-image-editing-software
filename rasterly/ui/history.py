"""History overlay for the active document's complete retained timeline."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                            QListWidgetItem, QToolButton, QGraphicsDropShadowEffect)
from .icons import icon


class HistoryOverlay(QWidget):
    visibility_changed = pyqtSignal(bool)

    def __init__(self, controller, jump, parent=None):
        super().__init__(parent)
        self.setObjectName("historyOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.controller = controller
        self.jump = jump
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("HISTORY")
        title.setObjectName("historyTitle")
        header.addWidget(title)
        header.addStretch()
        self.close_button = QToolButton()
        self.close_button.setIcon(icon("close", size=16))
        self.close_button.setFixedSize(24, 24)
        self.close_button.setToolTip("Close history")
        self.close_button.setAccessibleName("Close history")
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.document_name = QLabel()
        self.document_name.setObjectName("muted")
        layout.addWidget(self.document_name)
        self.list = QListWidget()
        self.list.setObjectName("historyList")
        self.list.itemClicked.connect(self.choose)
        self.list.itemActivated.connect(self.choose)
        layout.addWidget(self.list, 1)
        hint = QLabel("Choose a state to restore it. Later states remain available until you make another edit.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(-3, 4)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.setGraphicsEffect(shadow)
        self.signature = None
        controller.changed.connect(self.refresh)
        self.refresh()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)

    def refresh(self):
        session = self.controller.active_session
        if not session:
            self.list.clear()
            self.document_name.setText("No image open")
            self.signature = None
            return
        self.document_name.setText(session.title)
        history = session.history
        signature = (session.id, tuple(history.state_labels), history.position)
        if signature == self.signature:
            return
        self.signature = signature
        self.list.clear()
        for index, label in enumerate(history.state_labels):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, index)
            if index > history.position:
                item.setForeground(QColor("#787f8e"))
            if index == history.position:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.list.addItem(item)
        self.list.setCurrentRow(history.position)
        self.list.scrollToItem(self.list.currentItem())

    def choose(self, item):
        self.jump(item.data(Qt.ItemDataRole.UserRole))
        if self.isVisible():
            self.list.setFocus()
