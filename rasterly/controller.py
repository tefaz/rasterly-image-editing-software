"""Document ownership, command dispatch, and background image processing."""
from dataclasses import replace
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from .history import History
from .model import Document
from .session import DocumentSession
from .processing import LocalInpaintingEngine, processing_region, apply_processed


class ProcessingWorker(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result_ready.emit(self.operation())
        except Exception as error:
            self.failed.emit(str(error))


class EditorController(QObject):
    changed = pyqtSignal()
    error = pyqtSignal(str)
    busy_changed = pyqtSignal(bool, str)
    about_to_switch = pyqtSignal()
    session_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sessions = []
        self.active_index = -1
        self.untitled_count = 0
        self.empty_history = History()
        self.engine = LocalInpaintingEngine()
        self.busy = False
        self.worker = None

    @property
    def dirty(self):
        return self.active_session.dirty if self.active_session else False

    @property
    def active_session(self):
        return self.sessions[self.active_index] if self.active_index >= 0 else None

    @property
    def document(self):
        return self.active_session.document if self.active_session else None

    @document.setter
    def document(self, value):
        self.active_session.document = value

    @property
    def history(self):
        return self.active_session.history if self.active_session else self.empty_history

    @property
    def path(self):
        return self.active_session.path if self.active_session else None

    @path.setter
    def path(self, value):
        self.active_session.path = value

    @property
    def saved_revision(self):
        return self.active_session.saved_revision if self.active_session else None

    @saved_revision.setter
    def saved_revision(self, value):
        self.active_session.saved_revision = value

    def add_document(self, document, path=None):
        if self.busy:
            return False
        self.about_to_switch.emit()
        self.untitled_count += 1
        name = f"Untitled {self.untitled_count}"
        session = DocumentSession(document, name, path, document.revision if path else None)
        session.history.clear("Open image" if path else "New image")
        self.sessions.append(session)
        self.active_index = len(self.sessions) - 1
        self.session_changed.emit(self.active_index)
        self.changed.emit()
        return True

    def switch_document(self, index):
        if self.busy or not 0 <= index < len(self.sessions):
            return False
        if index != self.active_index:
            self.about_to_switch.emit()
            self.active_index = index
            self.session_changed.emit(index)
            self.changed.emit()
        return True

    def close_document(self, index):
        """Remove a tab after the window has handled its save prompt."""
        if self.busy or not 0 <= index < len(self.sessions):
            return False
        previous = self.active_session
        removing_active = index == self.active_index
        if removing_active:
            self.about_to_switch.emit()
        self.sessions.pop(index)
        if not self.sessions:
            self.active_index = -1
        elif removing_active:
            self.active_index = min(index, len(self.sessions) - 1)
        else:
            self.active_index = next(i for i, session in enumerate(self.sessions) if session is previous)
        if removing_active:
            self.session_changed.emit(self.active_index)
        self.changed.emit()
        return True

    def replace_document(self, document, path=None):
        if self.busy:
            return
        if not self.active_session:
            self.add_document(document, path)
            return
        self.document, self.path = document, path
        self.saved_revision = document.revision if path else None
        self.history.clear("Open image" if path else "New image")
        self.changed.emit()

    def apply(self, label, operation):
        if self.busy or not self.document:
            return False
        try:
            before = self.document
            after = operation(before)
            self.history.push(label, before, after)
            self.document = after
            self.changed.emit()
            return True
        except Exception as error:
            self.error.emit(str(error))
            return False

    def set_selection(self, selection, label=None):
        """Commit selection state once, sharing pixels and preserving save state."""
        if self.busy or not self.document:
            return False
        selection = selection if selection and selection.valid else None
        if selection == self.document.selection:
            return False
        if label is None:
            label = "Deselect" if selection is None else {
                "rectangle": "Rectangle selection", "lasso": "Lasso selection"
            }.get(selection.kind, "Selection")
        return self.apply(label, lambda doc: replace(doc, selection=selection))

    def select_layer(self, id):
        if not self.busy and self.document and any(l.id == id for l in self.document.layers):
            self.document = replace(self.document, active_id=id, selected_ids=frozenset({id}))
            self.changed.emit()

    def select_layers(self, ids, active_id=None):
        if self.busy or not self.document:
            return
        doc = self.document
        selected = frozenset(ids) & {layer.id for layer in doc.layers}
        if not selected:
            selected = frozenset({doc.active_id})
        if active_id not in selected:
            active_id = doc.active_id if doc.active_id in selected else next(
                layer.id for layer in reversed(doc.layers) if layer.id in selected)
        if selected != doc.selected_ids or active_id != doc.active_id:
            self.document = replace(doc, active_id=active_id, selected_ids=selected)
            self.changed.emit()

    def toggle_undo(self):
        if not self.busy and self.document and self.history.can_toggle:
            self.document = self.history.toggle()
            self.changed.emit()

    def undo(self):
        if not self.busy and self.history.undo_stack:
            self.document = self.history.undo()
            self.changed.emit()

    def redo(self):
        if not self.busy and self.history.redo_stack:
            self.document = self.history.redo()
            self.changed.emit()

    def jump_history(self, position):
        if not self.busy and self.document:
            document = self.history.jump(position)
            if document is not None:
                self.document = document
                self.changed.emit()

    def run_background(self, label, operation):
        if self.busy or not self.document:
            return
        before = self.document
        owner = self.active_session
        self.busy = True
        self.busy_changed.emit(True, label)
        worker = ProcessingWorker(lambda: operation(before), self)
        self.worker = worker

        def complete(after):
            owner.history.push(label, before, after)
            owner.document = after
            self.changed.emit()

        def finished():
            self.busy = False
            self.worker = None
            self.busy_changed.emit(False, "")
            worker.deleteLater()

        worker.result_ready.connect(complete)
        worker.failed.connect(self.error)
        worker.finished.connect(finished)
        worker.start()

    def heal(self, source_offset=None):
        if not self.document:
            return
        if not self.document.active.visible:
            self.error.emit("Show the active layer before healing it.")
            return
        def operation(doc):
            region, image, mask, source = processing_region(doc, source_offset)
            result = self.engine.process(image, mask, source)
            return apply_processed(doc, region, result)
        self.run_background("Patch" if source_offset else "Content-Aware Fill", operation)
