"""Constants used only inside the block editor.

Things that affect the editor's own canvas (how big it is, how the grid
looks, handle sizes, preview overlays for the pin-placement tool) — but
would have no meaning on the main scene.
"""
from PyQt5.QtGui import QColor


# ----------------------------------------------------------------------
# Canvas — the fixed-size design surface shown in the editor dialog
# ----------------------------------------------------------------------
CANVAS_HALF_W   = 360      # scene spans [-CANVAS_HALF_W, +CANVAS_HALF_W]
CANVAS_HALF_H   = 240
GRID_SIZE       = 10       # background grid step
GRID_MAJOR      = 5        # every Nth line is drawn brighter
HANDLE_SIZE     = 10.0     # resize handle square side

# Minimum block dimensions the editor will ever allow. Individual pins
# may force a larger dynamic minimum (see dialog._required_minimums).
MIN_BLOCK_W = 60.0
MIN_BLOCK_H = 60.0


# ----------------------------------------------------------------------
# Placement preview — the ghost pin that follows the cursor in Pins mode
# ----------------------------------------------------------------------
PIN_PREVIEW_ALPHA        = 120
PIN_PREVIEW_VALID_TINT   = QColor(120, 220, 150)    # soft green
PIN_PREVIEW_INVALID_TINT = QColor(230,  90,  90)    # soft red

# How far outside the block body a click still counts as "place on that side"
# (and how deep inside the body a click is still treated as edge-seeking
# before it becomes a centre-click). Drives the ring-zone hit test.
CLICK_CAPTURE_MARGIN = 30.0