"""Layer folder commands. Groups organize consecutive layers without flattening."""
from dataclasses import replace
from uuid import uuid4

from .model import LayerGroup


def group_layers(doc):
    selected = [layer for layer in doc.layers if layer.id in doc.selected_ids]
    if len(selected) < 2:
        raise ValueError("Select at least two layers to group.")
    names = {group.name for group in doc.groups}
    number = 1
    while f"Group {number}" in names:
        number += 1
    group = LayerGroup(f"Group {number}")
    highest = max(i for i, layer in enumerate(doc.layers) if layer.id in doc.selected_ids)
    parent = doc.layers[highest].group_id
    if parent is not None:
        highest = max(i for i, layer in enumerate(doc.layers) if layer.group_id == parent)
    members = tuple(replace(layer, group_id=group.id) for layer in selected)
    layers = []
    for index, layer in enumerate(doc.layers):
        if layer.id not in doc.selected_ids:
            layers.append(layer)
        if index == highest:
            layers.extend(members)
    return doc.edited(layers=tuple(layers), groups=doc.groups + (group,))


def rename_group(doc, group_id, name):
    name = name.strip()
    if not name:
        return doc
    group = next(group for group in doc.groups if group.id == group_id)
    if group.name == name:
        return doc
    return doc.edited(groups=tuple(replace(item, name=name) if item.id == group_id else item
                                   for item in doc.groups))


def set_collapsed(doc, group_id, collapsed):
    # Folder expansion is view state: saving retains it without adding an undo
    # command or marking pixels/document metadata as edited.
    return replace(doc, groups=tuple(replace(group, collapsed=collapsed) if group.id == group_id else group
                                     for group in doc.groups))


def ungroup(doc, group_id):
    return doc.edited(layers=tuple(replace(layer, group_id=None) if layer.group_id == group_id else layer
                                   for layer in doc.layers))


def duplicate_group(doc, group_id):
    group = next(group for group in doc.groups if group.id == group_id)
    copied = LayerGroup(group.name + " copy", collapsed=group.collapsed)
    members = [layer for layer in doc.layers if layer.group_id == group_id]
    clones = tuple(replace(layer, id=uuid4().hex, group_id=copied.id) for layer in members)
    index = max(i for i, layer in enumerate(doc.layers) if layer.group_id == group_id) + 1
    active = clones[members.index(doc.active)] if doc.active in members else clones[-1]
    return doc.edited(layers=doc.layers[:index] + clones + doc.layers[index:],
                      groups=doc.groups + (copied,), active_id=active.id,
                      selected_ids=frozenset(layer.id for layer in clones))


def delete_group(doc, group_id):
    layers = tuple(layer for layer in doc.layers if layer.group_id != group_id)
    if not layers:
        raise ValueError("Keep at least one layer in the document.")
    active = doc.active_id if any(layer.id == doc.active_id for layer in layers) else layers[-1].id
    return doc.edited(layers=layers, active_id=active)


def shift_entry(doc, entry_id, direction):
    layer = next((layer for layer in doc.layers if layer.id == entry_id), None)
    if layer is not None and layer.group_id is not None:
        members = [item for item in doc.layers if item.group_id == layer.group_id]
        index = members.index(layer)
        destination = index + direction
        if not 0 <= destination < len(members):
            return doc
        members[index], members[destination] = members[destination], members[index]
        replacements = iter(members)
        return doc.edited(layers=tuple(next(replacements) if item.group_id == layer.group_id else item
                                       for item in doc.layers))
    entries = []
    for item in doc.layers:
        id = item.group_id or item.id
        if entries and entries[-1][0] == id:
            entries[-1][1].append(item)
        else:
            entries.append((id, [item]))
    index = next(i for i, entry in enumerate(entries) if entry[0] == entry_id)
    destination = index + direction
    if not 0 <= destination < len(entries):
        return doc
    entries[index], entries[destination] = entries[destination], entries[index]
    return doc.edited(layers=tuple(item for _, members in entries for item in members))
