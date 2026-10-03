"""Each open tab owns its pixels, history, save state, and viewport."""
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4
from .history import History
from .model import Document


@dataclass
class DocumentSession:
    document: Document
    name: str = "Untitled"
    path: str | None = None
    saved_revision: int | None = None
    history: History = field(default_factory=History)
    viewport: tuple[float, float, float, str] | None = None
    id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def title(self):
        return Path(self.path).name if self.path else self.name

    @property
    def dirty(self):
        return self.document.revision != self.saved_revision
