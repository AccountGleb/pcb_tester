"""The schematic scene — places block instances and draws wires.

Only the names re-exported here are the public API for this package.
Everything else (individual graphics items, wire-mode state machine,
internal dialogs) is implementation detail.

What the scene owns:
  * SchematicScene — the QGraphicsScene subclass holding blocks & wires
  * SchematicView  — the QGraphicsView with wheel-zoom and LMB-pan
  * BlockSelectionDialog + ask_unique_instance_name — UI for placing a
    block from the library onto the scene
  * The JSON save/load format for a whole schematic
    (see SchematicScene.to_dict / load_from_dict)

What the scene depends on:
  * ``editor`` — only through its public API (BlockLibrary, BlockTemplate,
    BlockEditorDialog). The scene never imports from editor internals.
  * ``theme`` and ``shared`` — plain constants, no behaviour.

What the scene is promised NOT to depend on:
  * anything under ``tester``
  * the main window
"""
from .dialogs import BlockSelectionDialog, ask_unique_instance_name
from .scene import SchematicScene
from .view import SchematicView

__all__ = [
    "SchematicScene",
    "SchematicView",
    "BlockSelectionDialog",
    "ask_unique_instance_name",
]