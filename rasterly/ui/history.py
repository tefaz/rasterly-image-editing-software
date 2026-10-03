"""Attached history window for the active document's complete retained timeline."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem


class HistoryDock(QDockWidget):
    def __init__(self, controller, jump, parent=None):
        super().__init__("History", parent)
        self.setObjectName("historyDock")
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.setMinimumWidth(235)
        self.setMaximumWidth(340)
        self.controller = controller
        self.jump = jump
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 12, 10, 10)
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
        self.setWidget(content)
        self.signature = None
        controller.changed.connect(self.refresh)
        self.refresh()

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
