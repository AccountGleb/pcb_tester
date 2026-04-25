"""Small helper that builds the arrow path attached to a pin.

Every pin has a short arrow-shaft pointing outward from the block.
For INPUT pins, the arrow-head sits at the pin's square (pointing INTO
the block). For OUTPUT pins, the arrow-head sits at the shaft's tip,
pointing AWAY from the block.

Coordinates are in the pin's local space: the origin (0, 0) is the pin's
anchor point on the block wall, which is exactly where the pin's square
is centred. "Outward" is defined by `side`.
"""
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QPainterPath

from shared import (
    PIN_ARROW_HEAD_SIZE,
    PIN_ARROW_HEAD_WIDTH,
    WIRE_STUB_LEN,
)

from .library import PinDirection


# Unit outward vector for each side.
_OUTWARD = {
    "left":   (-1, 0),
    "right":  (+1, 0),
    "top":    (0, -1),
    "bottom": (0, +1),
}


def pin_stub_tip(side: str) -> QPointF:
    """Where the shaft ends (i.e. where a connected wire should attach)."""
    ox, oy = _OUTWARD.get(side, (1, 0))
    return QPointF(ox * WIRE_STUB_LEN, oy * WIRE_STUB_LEN)


def build_pin_arrow_path(side: str, direction: PinDirection) -> QPainterPath:
    """Return the drawable path for this pin's shaft + arrow head.

    The path consists of:
        - a shaft line from (0, 0) to stub tip
        - a filled triangular head either at the origin (for INPUT — points
          toward the block) or at the tip (for OUTPUT — points outward).
    """
    ox, oy = _OUTWARD.get(side, (1, 0))
    tip = pin_stub_tip(side)

    path = QPainterPath()
    # Shaft: from the square out to the stub tip.
    path.moveTo(0.0, 0.0)
    path.lineTo(tip)

    # Arrow head — a filled triangle.
    # Unit outward vector (ox, oy); perpendicular is (-oy, ox).
    hs = PIN_ARROW_HEAD_SIZE
    hw = PIN_ARROW_HEAD_WIDTH / 2.0
    # Perpendicular unit vector.
    px, py = -oy, ox

    if direction == PinDirection.INPUT:
        # Head sits at the pin square, pointing INTO the block
        # (i.e. the arrow tip is at the origin, pointing in the -outward
        # direction; the base of the triangle is further outward).
        head_tip = QPointF(0.0, 0.0)
        base_centre = QPointF(ox * hs, oy * hs)
    else:  # OUTPUT
        # Head sits at the stub's tip, pointing outward.
        head_tip = tip
        base_centre = QPointF(tip.x() - ox * hs, tip.y() - oy * hs)

    base_a = QPointF(base_centre.x() + px * hw, base_centre.y() + py * hw)
    base_b = QPointF(base_centre.x() - px * hw, base_centre.y() - py * hw)

    path.moveTo(head_tip)
    path.lineTo(base_a)
    path.lineTo(base_b)
    path.lineTo(head_tip)
    return path