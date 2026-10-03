"""Modular interaction tools. Mouse motion only changes preview state."""
from .selection import RectangleTool, LassoTool, PatchTool
from .move import MoveTool
from .text import TextTool
from .fill import BucketTool, GradientTool
from .brush import BrushTool, EraserTool


def make_tools(canvas):
    return {tool.id: tool(canvas) for tool in (
        MoveTool, RectangleTool, LassoTool, PatchTool, BrushTool, EraserTool,
        TextTool, BucketTool, GradientTool)}
