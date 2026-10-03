"""Raster import/export and versioned, lossless layered .rasterly ZIP documents."""
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
from PIL import Image
from dataclasses import asdict
from .model import Document, Layer, LayerGroup, TextData, composite, validate_size

PROJECT_SUFFIX = ".rasterly"
RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def open_document(path):
    path = Path(path)
    if path.suffix.lower() == PROJECT_SUFFIX:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("document.json")
            if info.file_size > 1_000_000:
                raise ValueError("Invalid project manifest.")
            metadata = json.loads(archive.read(info))
            if metadata.get("format") != "rasterly" or metadata.get("version") not in (1, 2):
                raise ValueError("Unsupported Rasterly project version.")
            width, height = int(metadata["width"]), int(metadata["height"])
            validate_size(width, height)
            entries = metadata["layers"]
            if not 1 <= len(entries) <= 500:
                raise ValueError("Invalid number of layers.")
            layers, ids = [], set()
            for entry in entries:
                info = archive.getinfo(entry["file"])
                if info.file_size > 450_000_000:
                    raise ValueError("Layer file is too large.")
                with Image.open(io.BytesIO(archive.read(info))) as image:
                    validate_size(*image.size)
                    pixels = image.convert("RGBA")
                id = str(entry["id"])
                if id in ids:
                    raise ValueError("Duplicate layer identifiers.")
                ids.add(id)
                layers.append(Layer(str(entry["name"]), pixels, int(entry["x"]), int(entry["y"]),
                                    bool(entry["visible"]), id,
                                    TextData(**entry["text"]) if entry.get("text") is not None else None,
                                    str(entry["group_id"]) if entry.get("group_id") is not None else None))
            active = metadata.get("active_id", layers[-1].id)
            if active not in ids:
                active = layers[-1].id
            selected = frozenset(metadata.get("selected_ids", [active]))
            group_entries = metadata.get("groups", [])
            if len(group_entries) > 500:
                raise ValueError("Invalid number of layer groups.")
            groups = tuple(LayerGroup(str(entry["name"]), str(entry["id"]), bool(entry.get("collapsed", False)))
                           for entry in group_entries)
            return Document(width, height, tuple(layers), active, selected_ids=selected, groups=groups)
    if path.suffix.lower() not in RASTER_SUFFIXES:
        raise ValueError("Open a PNG, JPEG, WebP, or Rasterly document.")
    with Image.open(path) as image:
        validate_size(*image.size)
        # Keep decoded source dimensions and pixels exactly as stored.
        return Document.from_image(image, path.stem)


def _atomic_write(path, writer):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    os.close(descriptor)
    try:
        writer(temporary)
        with open(temporary, "rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_project(document, path):
    def writer(temporary):
        entries = []
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for index, layer in enumerate(document.layers):
                filename = f"layers/{index}.png"
                buffer = io.BytesIO()
                layer.image.save(buffer, format="PNG")
                archive.writestr(filename, buffer.getvalue())
                entries.append(dict(id=layer.id, name=layer.name, x=layer.x, y=layer.y,
                                    visible=layer.visible, file=filename))
                if layer.text is not None:
                    entries[-1]["text"] = asdict(layer.text)
                if layer.group_id is not None:
                    entries[-1]["group_id"] = layer.group_id
            metadata = dict(format="rasterly", version=2 if document.groups else 1,
                            width=document.width, height=document.height,
                            active_id=document.active_id, selected_ids=sorted(document.selected_ids), layers=entries)
            if document.groups:
                metadata["groups"] = [asdict(group) for group in document.groups]
            archive.writestr("document.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    _atomic_write(path, writer)


def export_image(document, path):
    suffix = Path(path).suffix.lower()
    if suffix not in RASTER_SUFFIXES:
        raise ValueError("Choose a PNG, JPEG, or WebP filename.")
    image = composite(document)
    format = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}[suffix]
    options = {}
    if format == "JPEG":
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        image = background
        options = dict(quality=95, subsampling=0)
    elif format == "WEBP":
        options = dict(lossless=True)
    _atomic_write(path, lambda temporary: image.save(temporary, format=format, **options))
