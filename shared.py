"""Constants shared between the block editor and the schematic scene.

These values determine what a block *looks* like, independent of where
it's being rendered (inside the editor while you design it, or on the
main scene after placement). Keeping them here guarantees that the two
views of the same block match pixel-for-pixel.

Anything that's specific to only one surface (editor canvas size,
scene grid, wire routing widths unique to main scene…) lives next to
that module, not here.
"""
from PyQt5.QtGui import QColor


# ----------------------------------------------------------------------
# Pin geometry
# ----------------------------------------------------------------------
PIN_SIZE         = 28.0    # square marker side length (scene units)
PIN_LABEL_PT     = 11      # font size of the number inside a pin
PIN_PITCH        = 30.0    # slot spacing along a block side + corner margin
PIN_STROKE_WIDTH = 1.0


# ----------------------------------------------------------------------
# Pin arrow (drawn outward from every pin)
#
# INPUT  pin → arrow head sits at the pin square, pointing INTO the block
# OUTPUT pin → arrow head sits at the shaft tip, pointing AWAY from block
#
# The shaft length equals WIRE_STUB_LEN so a wire attached to the pin
# visually continues the arrow without a seam.
# ----------------------------------------------------------------------
WIRE_STUB_LEN         = 18.0
PIN_ARROW_HEAD_SIZE   = 7.0
PIN_ARROW_HEAD_WIDTH  = 6.0
PIN_ARROW_SHAFT_WIDTH = 1.8


# ----------------------------------------------------------------------
# Block body
# ----------------------------------------------------------------------
BLOCK_STROKE_WIDTH = 2.0


# ----------------------------------------------------------------------
# Wire appearance (wires only exist on the main scene, but these are the
# same numbers the editor would show if we ever rendered a preview there)
# ----------------------------------------------------------------------
WIRE_DRAW_WIDTH = 2
WIRE_HIT_WIDTH  = 8         # fattened stroke for click hit-testing