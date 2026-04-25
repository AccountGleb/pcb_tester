"""Graphics items for blocks on the main schematic scene.

Coordinate system:
    Block origin (0, 0) is at the centre of the block body.
    The body is a rectangle from (-w/2, -h/2) to (+w/2, +h/2).
    Pin coordinates in `PinDef` are in this same local space.

A `BlockItem` is a QGraphicsItemGroup composed of:
    - a `QGraphicsRectItem` for the body (sized by the template's shape)
    - one `PinItem` per pin (square markers)
    - a text label showing the instance name
    - dashed lines for internal wires (from the template)
"""
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QFont, QPen
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)

from editor.library import BlockTemplate, PinDef
from editor.pin_arrow import build_pin_arrow_path
from shared import (
    BLOCK_STROKE_WIDTH,
    PIN_ARROW_SHAFT_WIDTH,
    PIN_LABEL_PT,
    PIN_SIZE,
    PIN_STROKE_WIDTH,
)
from theme import DARK, Theme


NAME_LABEL_PT  = 8


def _contrast_text_colour(fill):
    from PyQt5.QtGui import QColor
    y = 0.299 * fill.red() + 0.587 * fill.green() + 0.114 * fill.blue()
    return QColor(20, 22, 28) if y > 140 else QColor(240, 242, 250)


# ------------------------------------------------------------------------
class PinItem(QGraphicsItemGroup):
    """Square numbered marker at a pin position.

    The group's local origin is the pin's hit point (on the block's edge).
    The square is centred on that origin (half inside, half outside the
    block body); the number label is rendered INSIDE the square.
    """

    def __init__(self, pin: PinDef, parent: QGraphicsItem, theme: Theme) -> None:
        super().__init__(parent)
        self._pin = pin
        self._occupied = False
        self._theme = theme

        # Arrow first (lowest z inside the group) so the square overlaps
        # the arrow's base — the arrow looks like it emerges from under
        # the pin rather than being welded to the side of the square.
        self._arrow = QGraphicsPathItem(
            build_pin_arrow_path(pin.side, pin.direction), self,
        )
        self._arrow.setZValue(-1)

        s = PIN_SIZE
        self._square = QGraphicsRectItem(-s / 2, -s / 2, s, s, self)

        self._label = QGraphicsSimpleTextItem(str(pin.number), self)
        font = QFont()
        font.setPointSize(PIN_LABEL_PT)
        font.setBold(True)
        self._label.setFont(font)
        lbr = self._label.boundingRect()
        # Number printed inside the square, horizontally & vertically centred.
        self._label.setPos(-lbr.width() / 2, -lbr.height() / 2)

        self.setPos(pin.x, pin.y)
        self.setToolTip(
            f"Pin {pin.number} — {pin.signal.value}, {pin.direction.value}"
        )
        self.setAcceptHoverEvents(True)
        self.apply_theme(theme)

    # ..................................................................
    @property
    def number(self) -> int:
        return self._pin.number

    @property
    def pin_def(self) -> PinDef:
        return self._pin

    @property
    def is_occupied(self) -> bool:
        return self._occupied

    def set_occupied(self, occupied: bool) -> None:
        self._occupied = occupied
        self._refresh_fill()

    # ..................................................................
    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._square.setPen(QPen(theme.pin_stroke, PIN_STROKE_WIDTH))
        # label colour is picked per-fill in _refresh_fill for contrast
        self._refresh_fill()

    def _refresh_fill(self) -> None:
        # Pin fill is always based on its signal type. Occupancy is tracked
        # internally to enforce wiring rules but no longer shown as a colour
        # change — the user asked for a calmer visual since the wire itself
        # is the evidence that the pin is used.
        colour = self._theme.pin_fill_for(self._pin.signal)
        self._square.setBrush(QBrush(colour))
        self._label.setBrush(QBrush(_contrast_text_colour(colour)))
        # Arrow matches the pin colour so it reads as "part of this pin".
        self._arrow.setPen(QPen(colour, PIN_ARROW_SHAFT_WIDTH,
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self._arrow.setBrush(QBrush(colour))


# ------------------------------------------------------------------------
class BlockItem(QGraphicsItemGroup):
    """A placed instance of a BlockTemplate on the main scene."""

    def __init__(self, template: BlockTemplate, instance_name: str,
                 theme: Theme = DARK) -> None:
        super().__init__()
        self.template = template
        self._instance_name = instance_name
        self._theme = theme

        # --- Body rectangle -------------------------------------------
        w, h = template.shape.width, template.shape.height
        self._body = QGraphicsRectItem(-w / 2, -h / 2, w, h, self)

        # --- Pins -----------------------------------------------------
        self.pin_items: list[PinItem] = [PinItem(p, self, theme) for p in template.pins]

        # --- Internal wires (from the template config) ---------------
        self._internal_wire_items: list[QGraphicsLineItem] = []
        self._build_internal_wires()

        # --- Instance name under the block ----------------------------
        self._name_label = QGraphicsSimpleTextItem(instance_name, self)
        font = QFont()
        font.setPointSize(NAME_LABEL_PT)
        font.setBold(True)
        self._name_label.setFont(font)
        self._reposition_label()

        # --- Interaction ---------------------------------------------
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        # Needed for on_block_moved notifications so wires follow.
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        # Only the group itself should be selectable — not individual pins
        # or the body rect.
        for child in self.childItems():
            child.setFlag(QGraphicsItem.ItemIsSelectable, False)

        self.apply_theme(theme)

    # ==================================================================
    # Public API
    # ==================================================================
    @property
    def instance_name(self) -> str:
        return self._instance_name

    def set_instance_name(self, new_name: str) -> None:
        self._instance_name = new_name
        self._name_label.setText(new_name)
        self._reposition_label()

    def pin_by_number(self, number: int) -> Optional[PinItem]:
        for p in self.pin_items:
            if p.number == number:
                return p
        return None

    def set_pin_occupied(self, number: int, occupied: bool) -> None:
        pin = self.pin_by_number(number)
        if pin is not None:
            pin.set_occupied(occupied)

    # ==================================================================
    # Theme
    # ==================================================================
    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._body.setBrush(QBrush(theme.block_fill))
        self._body.setPen(QPen(theme.block_stroke, BLOCK_STROKE_WIDTH))
        self._name_label.setBrush(QBrush(theme.name_label))
        for p in self.pin_items:
            p.apply_theme(theme)
        self._apply_internal_wire_theme()

    # ==================================================================
    # Internal wires
    # ==================================================================
    def _build_internal_wires(self) -> None:
        pin_pos = {p.number: (p.x, p.y) for p in self.template.pins}
        for w in self.template.internal_wires:
            if w.source not in pin_pos or w.target not in pin_pos:
                continue
            sx, sy = pin_pos[w.source]
            tx, ty = pin_pos[w.target]
            line = QGraphicsLineItem(sx, sy, tx, ty, self)
            line.setZValue(-0.5)
            self._internal_wire_items.append(line)

    def _apply_internal_wire_theme(self) -> None:
        pen = QPen(self._theme.internal_wire, 1.2,
                   Qt.DashLine, Qt.RoundCap, Qt.RoundJoin)
        for line in self._internal_wire_items:
            line.setPen(pen)

    # ==================================================================
    # Label positioning
    # ==================================================================
    def _reposition_label(self) -> None:
        body_rect = self._body.rect()
        lbr = self._name_label.boundingRect()
        self._name_label.setPos(
            body_rect.center().x() - lbr.width() / 2,
            body_rect.bottom() + 4,
        )

    # ==================================================================
    # Scene interaction
    # ==================================================================
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None and hasattr(scene, "on_block_moved"):
                scene.on_block_moved(self)
        return super().itemChange(change, value)

    # ==================================================================
    # Serialisation hook (future save/load of the schematic)
    # ==================================================================
    def to_dict(self) -> dict:
        pos = self.pos()
        return {
            "template": self.template.name,
            "instance_name": self._instance_name,
            "x": pos.x(),
            "y": pos.y(),
        }