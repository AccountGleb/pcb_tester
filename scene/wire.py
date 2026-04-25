"""Orthogonal wires on the schematic.

A WireItem is a polyline of alternating horizontal/vertical segments.
It knows which pins (if any) its two endpoints reference, so that the
scene can track pin occupancy and delete wires when a block disappears.

Each endpoint that is attached to a pin on a known side (left/right/top/
bottom) gets a fixed-length **stub** — a mandatory straight segment that
leaves the block perpendicular to its side. The rest of the wire's
orthogonal routing starts from the stub's far end. This keeps visually
distinct pins from having their wires collide or pile up vertically.

The routing convention between two consecutive corners is "horizontal
first": from (x0, y0) to (x1, y1) we go through the elbow (x1, y0).
"""
from typing import Optional, Tuple

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QBrush, QPainterPath, QPainterPathStroker, QPen
from PyQt5.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
)

from shared import WIRE_DRAW_WIDTH, WIRE_HIT_WIDTH, WIRE_STUB_LEN
from theme import Theme


PinRef = Tuple[str, int]   # (block_instance_name, pin_number)


# Kept as a module-level alias so existing call sites that do
# `from wire import STUB_LEN` (if any) keep working.
STUB_LEN = WIRE_STUB_LEN


# ----------------------------------------------------------------------
def side_offset(side: Optional[str], length: float = STUB_LEN) -> QPointF:
    """Unit-ish offset in the outward direction of `side`."""
    if side == "left":
        return QPointF(-length, 0.0)
    if side == "right":
        return QPointF(length, 0.0)
    if side == "top":
        return QPointF(0.0, -length)
    if side == "bottom":
        return QPointF(0.0, length)
    return QPointF(0.0, 0.0)


# ----------------------------------------------------------------------
def build_ortho_path(
    corners: list[QPointF],
    cursor: Optional[QPointF] = None,
    *,
    start_side: Optional[str] = None,
    end_side: Optional[str] = None,
) -> QPainterPath:
    """Build an H-then-V orthogonal path through the committed corners.

    When `start_side` / `end_side` is given, the corresponding endpoint
    of the path is pushed out from the pin position by WIRE_STUB_LEN along
    the perpendicular direction of that side. That matches the end of the
    pin's own arrow-shaft (which the pin renders independently), so the
    wire appears to start/end exactly where the arrow finishes, forming
    a continuous visual line.

    If `cursor` is given, the path is extended to it with the same
    routing convention — used for the live preview while drawing.

    Routing convention between consecutive points: H-first (go through
    the elbow (target.x, prev.y)). For vertical start/end stubs we use
    V-first on the neighbouring segments so the wire continues along
    the stub axis rather than turning right at the tip.
    """
    path = QPainterPath()
    if not corners:
        return path

    pts: list[QPointF] = list(corners)
    if cursor is not None:
        pts.append(cursor)

    # Push endpoints outward so the wire visually attaches to the tip of
    # the pin's arrow rather than overlapping the pin square.
    if start_side is not None:
        pts[0] = pts[0] + side_offset(start_side)
    if end_side is not None and cursor is None:
        pts[-1] = pts[-1] + side_offset(end_side)

    path.moveTo(pts[0])
    prev = pts[0]
    vertical_stub_start = start_side in ("top", "bottom")
    vertical_stub_end   = end_side   in ("top", "bottom")

    last_idx = len(pts) - 1

    for idx, c in enumerate(pts[1:], start=1):
        # Keep the direction aligned with the pin's arrow axis on the
        # segment that leaves the start stub / approaches the end stub.
        use_v_first = False
        if idx == 1 and vertical_stub_start:
            use_v_first = True
        if end_side is not None and cursor is None and idx == last_idx and vertical_stub_end:
            use_v_first = True

        if use_v_first:
            elbow = QPointF(prev.x(), c.y())
        else:
            elbow = QPointF(c.x(), prev.y())

        if elbow != prev:
            path.lineTo(elbow)
        if c != elbow:
            path.lineTo(c)
        prev = c

    return path


# ----------------------------------------------------------------------
class WireItem(QGraphicsPathItem):
    """A finalised orthogonal wire on the scene.

    `corners[0]` is always the start-pin's scene position.
    `corners[-1]` is either the end-pin's scene position or a free point.

    `start_side` / `end_side` are set when the matching endpoint is attached
    to a pin whose side is known; in that case the renderer inserts a
    mandatory perpendicular stub at that end.
    """

    HIT_WIDTH = WIRE_HIT_WIDTH
    DRAW_WIDTH = WIRE_DRAW_WIDTH

    def __init__(
        self,
        corners: list[QPointF],
        start_pin: PinRef,
        end_pin: Optional[PinRef],
        theme: Theme,
        *,
        start_side: Optional[str] = None,
        end_side: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.setZValue(-1)                                   # behind blocks
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self._corners: list[QPointF] = list(corners)
        self.start_pin: PinRef = start_pin
        self.end_pin: Optional[PinRef] = end_pin
        self.start_side: Optional[str] = start_side
        self.end_side: Optional[str] = end_side
        self._theme = theme
        self._dangling_marker: Optional[QGraphicsEllipseItem] = None

        self.apply_theme(theme)

    # ..................................................................
    @property
    def corners(self) -> list[QPointF]:
        return list(self._corners)

    @property
    def is_dangling(self) -> bool:
        return self.end_pin is None

    # ..................................................................
    def update_corner(self, index: int, new_pos: QPointF) -> None:
        """Replace one corner (typically index 0 or -1) and rebuild.

        Used by the scene when a connected block moves so that the wire
        endpoint stays glued to its pin.
        """
        if not self._corners:
            return
        self._corners[index] = QPointF(new_pos)
        self._rebuild_geometry()

    # ..................................................................
    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setPen(QPen(theme.wire, self.DRAW_WIDTH,
                         Qt.SolidLine, Qt.SquareCap, Qt.RoundJoin))
        self._rebuild_geometry()

    # ..................................................................
    def _rebuild_geometry(self) -> None:
        self.setPath(build_ortho_path(
            self._corners,
            start_side=self.start_side,
            end_side=self.end_side,
        ))

        # dangling marker — small filled circle at the free endpoint
        if self._dangling_marker is not None:
            self._dangling_marker.setParentItem(None)
            if self.scene() is not None:
                self.scene().removeItem(self._dangling_marker)
            self._dangling_marker = None

        if self.is_dangling and self._corners:
            end = self._corners[-1]
            r = 2.8
            m = QGraphicsEllipseItem(end.x() - r, end.y() - r, 2 * r, 2 * r, self)
            m.setBrush(QBrush(self._theme.wire))
            m.setPen(QPen(self._theme.wire, 1))
            self._dangling_marker = m

    # ..................................................................
    def shape(self) -> QPainterPath:
        """Widened shape so thin paths are still clickable for selection."""
        stroker = QPainterPathStroker()
        stroker.setWidth(self.HIT_WIDTH)
        stroker.setCapStyle(Qt.SquareCap)
        return stroker.createStroke(self.path())

    # ..................................................................
    def to_dict(self) -> dict:
        """Serialise the wire — enough to reconstruct it on load.

        start_pin/end_pin are (block_instance_name, pin_number) tuples;
        encoded as dicts in JSON for clarity. Corners are saved so that
        any user-added waypoints survive a round-trip.
        """
        def pin_ref_to(p):
            if p is None:
                return None
            return {"block": p[0], "pin": p[1]}

        return {
            "start_pin": pin_ref_to(self.start_pin),
            "end_pin":   pin_ref_to(self.end_pin),
            "start_side": self.start_side,
            "end_side":   self.end_side,
            "corners": [{"x": c.x(), "y": c.y()} for c in self._corners],
        }