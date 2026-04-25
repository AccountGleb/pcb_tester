"""The block editor — a self-contained sub-system for designing blocks.

Only the names re-exported here are considered part of its public API.
Everything else (dialog internals, preview logic, pin-placement widget,
etc.) is implementation detail and may change without notice.

What the block editor owns:
  * the on-disk library of block templates (<n>.json per block)
  * the BlockEditorDialog window (create / edit one template)
  * the data model: BlockTemplate, BlockShape, PinDef, InternalWire,
    SignalType, PinDirection

What the block editor is promised NOT to depend on:
  * anything under ``scene``
  * anything under ``tester``
  * the main window

So the editor can be developed, tested, and reasoned about in isolation.
"""
from .dialog import BlockEditorDialog
from .library import (
    BlockLibrary,
    BlockShape,
    BlockTemplate,
    InternalWire,
    PinDef,
    PinDirection,
    SignalType,
)

__all__ = [
    "BlockEditorDialog",
    "BlockLibrary",
    "BlockTemplate",
    "BlockShape",
    "PinDef",
    "PinDirection",
    "SignalType",
    "InternalWire",
]