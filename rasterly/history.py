"""Named before/after commands, exact undo, and a bounded shared-buffer history."""
from dataclasses import dataclass
from .model import Document


@dataclass
class Command:
    label: str
    before: Document
    after: Document


class History:
    def __init__(self, memory_limit=512 * 1024 * 1024, max_commands=80):
        self.undo_stack: list[Command] = []
        self.redo_stack: list[Command] = []
        self.memory_limit = memory_limit
        self.max_commands = max_commands
        self.initial_label = "New image"
        self.pruned = False
        self.toggle_command = None

    def clear(self, initial_label="New image"):
        self.toggle_command = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.initial_label = initial_label
        self.pruned = False

    def push(self, label, before, after):
        # Selections and draft paths are session state: they have history entries but
        # retain the pixel revision so selecting does not dirty a saved image.
        if (before.revision == after.revision and before.selection == after.selection
                and before.polygon_path == after.polygon_path):
            return
        self.toggle_command = None
        self.undo_stack.append(Command(label, before, after))
        self.redo_stack.clear()
        while len(self.undo_stack) > 1 and (
            len(self.undo_stack) > self.max_commands or self.bytes_used > self.memory_limit
        ):
            self.undo_stack.pop(0)
            self.pruned = True

    @property
    def state_labels(self):
        initial = "Earlier state (history limit)" if self.pruned else self.initial_label
        commands = self.undo_stack + list(reversed(self.redo_stack))
        return [initial] + [command.label for command in commands]

    @property
    def position(self):
        return len(self.undo_stack)

    def jump(self, position):
        """Move the history cursor without discarding later states."""
        if not 0 <= position < len(self.state_labels):
            raise ValueError("This history state is no longer available.")
        self.toggle_command = None
        document = None
        while self.position > position:
            document = self.undo()
        while self.position < position:
            document = self.redo()
        return document

    @property
    def bytes_used(self):
        buffers = {}
        for command in self.undo_stack + self.redo_stack:
            for doc in (command.before, command.after):
                for layer in doc.layers:
                    buffers[id(layer.image)] = layer.image.width * layer.image.height * 4
        return sum(buffers.values())

    @property
    def toggle_redo(self):
        return bool(self.redo_stack and self.redo_stack[-1] is self.toggle_command)

    @property
    def can_toggle(self):
        return bool(self.undo_stack) or self.toggle_redo

    def toggle(self):
        """Alternate between a state and its predecessor until another action."""
        if self.toggle_redo:
            return self.redo()
        if self.undo_stack:
            command = self.undo_stack[-1]
            document = self.undo()
            self.toggle_command = command
            return document
        return None

    def undo(self):
        self.toggle_command = None
        command = self.undo_stack.pop()
        self.redo_stack.append(command)
        return command.before

    def redo(self):
        self.toggle_command = None
        command = self.redo_stack.pop()
        self.undo_stack.append(command)
        return command.after
