"""Modular interaction tools. Mouse motion only changes preview state."""
from .selection import RectangleTool, LassoTool, PatchTool
from .move import MoveTool


def make_tools(canvas):
    return {tool.id: tool(canvas) for tool in (MoveTool, RectangleTool, LassoTool, PatchTool)}
