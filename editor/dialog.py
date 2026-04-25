"""BlockEditorDialog — a full window for designing or editing one block.

Layout:
    +--------------------------------------------------------------+
    |  Name: [_________]   Mode: (o) Select  ( ) Pins  ( ) Connect|
    |  Signal: [combo]   Direction: [combo]   Marker: [swatch]    |
    |  Shape W: [____]  H: [____]   Pins: 0   Wires: 0            |
    +--------------------------------------------------------------+
    |                                                              |
    |          Fixed-viewport design surface (no pan; wheel zoom)  |
    |          - grid background                                   |
    |          - block rectangle centred at (0, 0) with 8 handles  |
    |          - pins as squares attached to the sides             |
    |          - internal wires drawn between connected pins       |
    |                                                              |
    +--------------------------------------------------------------+
    |  Status: <hint>                            [OK]  [Cancel]    |
    +--------------------------------------------------------------+

The dialog has three mutually-exclusive modes, selected by radio buttons:

    * Select   — the 8 resize handles are visible; drag to change size.
                 Signal/Direction combos are disabled; clicking inside
                 the body does nothing.
    * Pins     — a ghost pin follows the cursor. Click inside the
                 capture ring to place a pin on the nearest side, using
                 the currently-selected signal & direction.
    * Connect  — click one pin, then another, to add an internal wire
                 (output → input).

========================================================================
Architecture of this file — four distinct classes that talk via signals
========================================================================

1. _EditorScene (subclass of QGraphicsScene)
       The canvas. Owns the body rectangle, 8 resize handles, all pin
       graphics, internal-wire lines, and the ghost-pin preview. It's
       intentionally "dumb" about the data model: it just holds graphic
       items and fires signals when the user clicks or drags. The dialog
       subscribes to those signals and mutates the data model (the
       self._pins list, etc) accordingly.

       Why this split: the scene is the only place that deals with Qt
       coordinates and item Z-order; the dialog is the only place that
       enforces business rules (fan-in = 1, minimum body size, etc).

2. _ResizeHandle (subclass of QGraphicsRectItem)
       One of the 8 drag handles around the body. It computes how the
       body's width/height would change as the user drags, and emits
       scene.body_resized with the new (w, h). The scene forwards that
       to the dialog, which applies minimum-size rules and updates
       everything that depends on body size.

3. _EditorView (subclass of QGraphicsView)
       Wheel zoom + no pan. Also forwards hover events (via a callback
       set by the dialog) so the ghost-pin preview follows the cursor
       in Pins mode.

4. BlockEditorDialog (subclass of QDialog) — the public class.
       Holds the in-progress data: self._shape, self._pins, self._wires.
       Builds the UI, routes scene signals into data mutations, handles
       OK (persist via BlockLibrary.commit) and Cancel.

========================================================================
Key data invariants
========================================================================

- (0, 0) is the centre of the body. Pin coordinates are absolute within
  that frame. BlockShape's width and height are full (not half) extents.

- Every pin has a `side` ∈ {left, right, top, bottom}. The perpendicular
  coordinate of a pin always equals ±halfW or ±halfH — i.e. pins live
  exactly on the wall. When the block is resized, pins on LEFT/RIGHT
  slide with the left/right wall (p.x = ±halfW) but keep their y
  position (the "along-side" coordinate). Analogous for TOP/BOTTOM.

- Minimum width/height are computed dynamically so pins can't slip off
  their wall — a LEFT pin with |y|=40 forces halfH ≥ 40 + PIN_PITCH/2.
  See _required_minimums().

- Pin slots are snapped to PIN_PITCH along each side and clamped away
  from corners by PIN_PITCH/2.

- Internal wires reference pins by number only (not by geometry) so they
  survive resize and grow/shrink.

========================================================================
Extending the editor
========================================================================

- New shape primitive (circle, polygon): extend BlockShape's `kind`
  field in library.py and add a rendering branch in _EditorScene.
  Keep the coordinate system (origin at centre) consistent so pins
  keep working.

- Text labels on the block body: store a list of {text, x, y, font} in
  BlockTemplate, render in _EditorScene (and in scene/block_item.py so
  the label appears on the main scene too).

- SVG / PNG import for a background raster: store a path in
  BlockTemplate, add a QGraphicsPixmapItem or QGraphicsSvgItem under
  the body rect with a lower Z. The rectangle stays as the pin anchor
  — the image is a visual skin only.

Callers of this module should only touch BlockEditorDialog's public
methods (__init__ and accepted_template()). The three helper classes
are private.
"""
from typing import Optional

from PyQt5.QtCore import QLineF, QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from shared import (
    BLOCK_STROKE_WIDTH,
    PIN_ARROW_SHAFT_WIDTH,
    PIN_LABEL_PT,
    PIN_PITCH,
    PIN_SIZE,
    PIN_STROKE_WIDTH,
)
from theme import DARK

from .config import (
    CANVAS_HALF_H as CANVAS_HALF_H,
    CANVAS_HALF_W as CANVAS_HALF_W,
    CLICK_CAPTURE_MARGIN,
    GRID_MAJOR,
    GRID_SIZE,
    HANDLE_SIZE,
    MIN_BLOCK_H,
    MIN_BLOCK_W,
    PIN_PREVIEW_ALPHA,
    PIN_PREVIEW_INVALID_TINT,
    PIN_PREVIEW_VALID_TINT,
)
from .library import (
    BlockLibrary,
    BlockShape,
    BlockTemplate,
    InternalWire,
    PinDef,
    PinDirection,
    SignalType,
)


# ------------------------------------------------------------------------
# Mode enum
# ------------------------------------------------------------------------
MODE_SELECT  = "select"
MODE_PINS    = "pins"
MODE_CONNECT = "connect"


# ------------------------------------------------------------------------
# Side names — where on the block's perimeter a pin is anchored.
# ------------------------------------------------------------------------
SIDE_LEFT   = "left"
SIDE_RIGHT  = "right"
SIDE_TOP    = "top"
SIDE_BOTTOM = "bottom"


# ------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------
def snap(v: float, step: float = PIN_PITCH) -> float:
    return round(v / step) * step


def _nearest_side(px: float, py: float, w: float, h: float) -> str:
    """Which edge of the w×h block (centred at origin) is the point closest to?"""
    dl = abs(px - (-w / 2))
    dr = abs(px -  (w / 2))
    dt = abs(py - (-h / 2))
    db = abs(py -  (h / 2))
    best = min(dl, dr, dt, db)
    if best == dl:
        return SIDE_LEFT
    if best == dr:
        return SIDE_RIGHT
    if best == dt:
        return SIDE_TOP
    return SIDE_BOTTOM


def _side_of_pin(pin_x: float, pin_y: float, w: float, h: float,
                 tolerance: float = 0.5) -> Optional[str]:
    """Which side does a pin currently sit on, or None if somehow interior.

    A pin is 'on' a side when its centre lies exactly on that edge line
    (within a small tolerance to forgive float rounding).
    """
    if abs(pin_x - (-w / 2)) <= tolerance:
        return SIDE_LEFT
    if abs(pin_x -  (w / 2)) <= tolerance:
        return SIDE_RIGHT
    if abs(pin_y - (-h / 2)) <= tolerance:
        return SIDE_TOP
    if abs(pin_y -  (h / 2)) <= tolerance:
        return SIDE_BOTTOM
    return None


def _snap_to_side(click_x: float, click_y: float,
                  w: float, h: float) -> tuple[str, float, float]:
    """Project a click onto the nearest side, snap the along-axis to PIN_PITCH,
    and clamp it into the valid placement range for that side.

    Returns (side, x, y) where (x, y) is the pin position in block-local
    coordinates — always lying exactly on one edge line.
    """
    side = _nearest_side(click_x, click_y, w, h)
    if side == SIDE_LEFT:
        x = -w / 2
        y = _clamp_along(snap(click_y, PIN_PITCH), h)
    elif side == SIDE_RIGHT:
        x = w / 2
        y = _clamp_along(snap(click_y, PIN_PITCH), h)
    elif side == SIDE_TOP:
        y = -h / 2
        x = _clamp_along(snap(click_x, PIN_PITCH), w)
    else:  # bottom
        y = h / 2
        x = _clamp_along(snap(click_x, PIN_PITCH), w)
    return side, x, y


def _clamp_along(value: float, axis_extent: float) -> float:
    """Keep a pin away from the corners by at least PIN_PITCH/2."""
    half = axis_extent / 2 - PIN_PITCH / 2
    if half < 0:
        return 0.0
    return max(-half, min(half, value))


def _contrast_text_colour(fill: QColor) -> QColor:
    """Pick black or white text for best legibility on the given fill."""
    # standard perceived-luminance formula
    y = 0.299 * fill.red() + 0.587 * fill.green() + 0.114 * fill.blue()
    return QColor(20, 22, 28) if y > 140 else QColor(240, 242, 250)


# ========================================================================
# Editor scene
# ========================================================================
class _EditorScene(QGraphicsScene):
    """Holds the body, handles, pins and internal wires.

    The scene talks back to the dialog via signals — the dialog owns the
    data model and the mode state. This keeps the scene itself mostly
    dumb: it just re-lays out its children when told.
    """
    body_resized  = pyqtSignal(float, float)       # new width, height
    pin_clicked   = pyqtSignal(int)                # pin number that was clicked
    body_clicked  = pyqtSignal(QPointF)            # local point (already in body coords)
    empty_clicked = pyqtSignal()                   # clicked anywhere else

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSceneRect(QRectF(
            -CANVAS_HALF_W, -CANVAS_HALF_H,
            2 * CANVAS_HALF_W, 2 * CANVAS_HALF_H,
        ))

        # Body (initial size will be overwritten by set_body_size before display)
        self._body = QGraphicsRectItem()
        self._body.setZValue(0)
        self.addItem(self._body)

        # 8 resize handles — indexed by (dx, dy) where dx,dy ∈ {-1, 0, +1}
        # (0, 0) is excluded (it's the body itself). These are direct scene
        # children so they can be clicked individually.
        self._handles: dict[tuple[int, int], _ResizeHandle] = {}
        for dx in (-1, 0, +1):
            for dy in (-1, 0, +1):
                if dx == 0 and dy == 0:
                    continue
                h = _ResizeHandle(dx, dy, self)
                self.addItem(h)
                self._handles[(dx, dy)] = h

        # Pin items and their label lookups — we render them ourselves rather
        # than reusing block_item.PinItem so that the editor can attach a
        # clickable square without the "occupied" colour logic.
        self._pin_squares: dict[int, QGraphicsRectItem] = {}
        self._pin_labels: dict[int, QGraphicsSimpleTextItem] = {}
        self._pin_arrows: dict[int, QGraphicsPathItem] = {}
        # editor internal-wire lines keyed by (source, target)
        self._wire_lines: dict[tuple[int, int], QGraphicsLineItem] = {}

        # Selected pin highlight ring (used in connect mode)
        self._pending_ring: Optional[QGraphicsEllipseItem] = None

        # Ghost pin under the cursor in Pins mode (shown, moved, tinted by
        # mouse move; hidden otherwise).
        self._pin_preview: Optional[QGraphicsRectItem] = None
        self._placement_mode: bool = False    # True iff Pins mode is active

        self._body_size = (120.0, 80.0)
        self._handles_visible = True

        self._apply_body_theme()
        self.setStickyFocus(False)
        # Enable mouse tracking via views' hoverMove to drive the preview.
        # See _EditorView below — we forward hover events into the scene.

    # ------------------------------------------------------------------
    # Body
    # ------------------------------------------------------------------
    def set_body_size(self, width: float, height: float) -> None:
        width  = max(MIN_BLOCK_W, width)
        height = max(MIN_BLOCK_H, height)
        self._body_size = (width, height)
        self._body.setRect(-width / 2, -height / 2, width, height)
        self._layout_handles()

    def body_size(self) -> tuple[float, float]:
        return self._body_size

    def body_rect(self) -> QRectF:
        return self._body.rect()

    def set_handles_visible(self, visible: bool) -> None:
        self._handles_visible = visible
        for h in self._handles.values():
            h.setVisible(visible)

    def _layout_handles(self) -> None:
        w, h = self._body_size
        for (dx, dy), handle in self._handles.items():
            x = dx * w / 2
            y = dy * h / 2
            handle.setPos(x, y)

    # ------------------------------------------------------------------
    # Placement-mode preview (the ghost pin that follows the cursor
    # while the Pins mode is active).
    # ------------------------------------------------------------------
    def set_placement_mode(self, on: bool) -> None:
        self._placement_mode = on
        if not on:
            self._hide_pin_preview()

    def body_rect_inflated(self) -> QRectF:
        """The outer rect of the placement capture zone."""
        w, h = self._body_size
        m = CLICK_CAPTURE_MARGIN
        return QRectF(-w / 2 - m, -h / 2 - m, w + 2 * m, h + 2 * m)

    def body_rect_deflated(self) -> QRectF:
        """The inner rect — interior more than CLICK_CAPTURE_MARGIN away
        from any edge. Clicks landing strictly inside this rect are NOT
        considered valid placements because the user is clearly aiming at
        the middle of the block, not a side.
        """
        w, h = self._body_size
        m = CLICK_CAPTURE_MARGIN
        inner_w = max(0.0, w - 2 * m)
        inner_h = max(0.0, h - 2 * m)
        return QRectF(-inner_w / 2, -inner_h / 2, inner_w, inner_h)

    def _in_snap_ring(self, scene_pos: QPointF) -> bool:
        """Is this point in the valid pin-placement region?

        The region is a ring around the block's perimeter: from
        CLICK_CAPTURE_MARGIN outside the body to CLICK_CAPTURE_MARGIN
        inside. Clicks in the middle of the block are REJECTED — the user
        was clearly not aiming at a side.

        This ring was introduced because:
          - Clicks strictly inside the body left the perimeter too small
            a target (especially for thin blocks).
          - Clicks outside the body used to do nothing, which meant you
            couldn't just "overshoot" a side without backing up.
          - Clicks in the middle, if they'd been honoured, would snap to
            an arbitrary side and confuse the user.

        The ring fixes all three.
        """
        return (
            self.body_rect_inflated().contains(scene_pos)
            and not self.body_rect_deflated().contains(scene_pos)
        )

    def update_pin_preview(self, scene_pos: QPointF, base_colour: QColor,
                           slot_occupied: bool) -> None:
        """Move/recolour the ghost pin to reflect where a click would land.

        Ghost follows the cursor everywhere, colour shows validity:
          * in the snap ring, slot free    → GREEN, snapped to edge
          * in the snap ring, slot taken   → RED,   snapped to edge
          * outside the snap ring (far outside OR in the middle of the
            block)                         → RED,   under the raw cursor
        """
        if not self._placement_mode:
            return

        in_ring = self._in_snap_ring(scene_pos)

        if in_ring:
            w, h = self._body_size
            _side, x, y = _snap_to_side(scene_pos.x(), scene_pos.y(), w, h)
            is_valid = not slot_occupied
            pos = QPointF(x, y)
        else:
            is_valid = False
            pos = scene_pos

        if self._pin_preview is None:
            s = PIN_SIZE
            self._pin_preview = QGraphicsRectItem(-s / 2, -s / 2, s, s)
            self._pin_preview.setZValue(20)
            self.addItem(self._pin_preview)

        tint = PIN_PREVIEW_VALID_TINT if is_valid else PIN_PREVIEW_INVALID_TINT
        fill = QColor(tint)
        fill.setAlpha(PIN_PREVIEW_ALPHA)
        self._pin_preview.setBrush(QBrush(fill))
        self._pin_preview.setPen(QPen(base_colour, PIN_STROKE_WIDTH))
        self._pin_preview.setPos(pos)

    def _hide_pin_preview(self) -> None:
        if self._pin_preview is not None:
            self.removeItem(self._pin_preview)
            self._pin_preview = None

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def _apply_body_theme(self) -> None:
        self._body.setBrush(QBrush(DARK.block_fill))
        self._body.setPen(QPen(DARK.block_stroke, BLOCK_STROKE_WIDTH))

    # ------------------------------------------------------------------
    # Background — grid only inside canvas, darker outside
    # ------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor(30, 32, 36))
        # canvas area
        cr = self.sceneRect()
        painter.fillRect(cr, DARK.bg)

        # grid
        left = int(cr.left())
        right = int(cr.right())
        top = int(cr.top())
        bottom = int(cr.bottom())
        minor_pen = QPen(DARK.grid_minor, 0)
        major_pen = QPen(DARK.grid_major, 0)

        x = left
        while x <= right:
            pen = major_pen if (x % (GRID_SIZE * GRID_MAJOR) == 0) else minor_pen
            painter.setPen(pen)
            painter.drawLine(x, top, x, bottom)
            x += GRID_SIZE
        y = top
        while y <= bottom:
            pen = major_pen if (y % (GRID_SIZE * GRID_MAJOR) == 0) else minor_pen
            painter.setPen(pen)
            painter.drawLine(left, y, right, y)
            y += GRID_SIZE

        # origin cross
        painter.setPen(QPen(QColor(120, 160, 200, 180), 0))
        painter.drawLine(-6, 0, 6, 0)
        painter.drawLine(0, -6, 0, 6)

    # ------------------------------------------------------------------
    # Pin rendering
    # ------------------------------------------------------------------
    def rebuild_pins(self, pins: list[PinDef]) -> None:
        # remove old
        for sq in self._pin_squares.values():
            self.removeItem(sq)
        for lb in self._pin_labels.values():
            self.removeItem(lb)
        for ar in self._pin_arrows.values():
            self.removeItem(ar)
        self._pin_squares.clear()
        self._pin_labels.clear()
        self._pin_arrows.clear()

        for pin in pins:
            self._add_pin_graphic(pin)

    def _add_pin_graphic(self, pin: PinDef) -> None:
        from .pin_arrow import build_pin_arrow_path

        s = PIN_SIZE
        fill = DARK.pin_fill_for(pin.signal)

        # Arrow first — lower z so the square overlaps its base.
        ar = QGraphicsPathItem(build_pin_arrow_path(pin.side, pin.direction))
        ar.setPos(pin.x, pin.y)
        ar.setZValue(1)
        ar.setPen(QPen(fill, PIN_ARROW_SHAFT_WIDTH, Qt.SolidLine,
                       Qt.RoundCap, Qt.RoundJoin))
        ar.setBrush(QBrush(fill))
        self.addItem(ar)

        sq = QGraphicsRectItem(-s / 2, -s / 2, s, s)
        sq.setPos(pin.x, pin.y)
        sq.setZValue(2)
        sq.setBrush(QBrush(fill))
        sq.setPen(QPen(DARK.pin_stroke, PIN_STROKE_WIDTH))
        sq.setToolTip(f"Pin {pin.number} — {pin.signal.value}, {pin.direction.value}")
        self.addItem(sq)

        lb = QGraphicsSimpleTextItem(str(pin.number))
        font = QFont()
        font.setPointSize(PIN_LABEL_PT)
        font.setBold(True)
        lb.setFont(font)
        lb.setBrush(QBrush(_contrast_text_colour(fill)))
        lbr = lb.boundingRect()
        lb.setPos(pin.x - lbr.width() / 2, pin.y - lbr.height() / 2)
        lb.setZValue(3)
        self.addItem(lb)

        self._pin_squares[pin.number] = sq
        self._pin_labels[pin.number] = lb
        self._pin_arrows[pin.number] = ar

    # ------------------------------------------------------------------
    # Internal wire rendering
    # ------------------------------------------------------------------
    def rebuild_wires(self, wires: list[InternalWire], pins: list[PinDef]) -> None:
        for ln in self._wire_lines.values():
            self.removeItem(ln)
        self._wire_lines.clear()

        pin_by = {p.number: p for p in pins}
        for w in wires:
            s = pin_by.get(w.source); t = pin_by.get(w.target)
            if s is None or t is None:
                continue
            ln = QGraphicsLineItem(s.x, s.y, t.x, t.y)
            ln.setPen(QPen(DARK.internal_wire, 1.5,
                           Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
            ln.setZValue(1)
            self.addItem(ln)
            self._wire_lines[(w.source, w.target)] = ln

    # ------------------------------------------------------------------
    # Pending-pin highlight ring (connect mode)
    # ------------------------------------------------------------------
    def set_pending_pin(self, pin: Optional[PinDef]) -> None:
        if self._pending_ring is not None:
            self.removeItem(self._pending_ring)
            self._pending_ring = None
        if pin is None:
            return
        r = PIN_SIZE / 2 + 3
        ring = QGraphicsEllipseItem(pin.x - r, pin.y - r, 2 * r, 2 * r)
        ring.setBrush(QBrush(Qt.NoBrush))
        ring.setPen(QPen(QColor(120, 220, 150), 2))
        ring.setZValue(4)
        self.addItem(ring)
        self._pending_ring = ring

    # ------------------------------------------------------------------
    # Click routing
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.scenePos()
            # Pin hit test (highest priority)
            for num, sq in self._pin_squares.items():
                if sq.sceneBoundingRect().contains(pos):
                    self.pin_clicked.emit(num)
                    event.accept()
                    return
            # Handles handle their own press events via QGraphicsItem — don't
            # pre-empt them.
            item = self.itemAt(pos, self.views()[0].transform() if self.views() else
                               self.views()[0].transform())
            if isinstance(item, _ResizeHandle):
                super().mousePressEvent(event)
                return
            # Body hit? In placement mode the hit zone is the perimeter
            # ring (body + margin on the outside, minus a margin on the
            # inside). In other modes, the raw body rect.
            if self._placement_mode:
                valid = self._in_snap_ring(pos)
            else:
                valid = self._body.sceneBoundingRect().contains(pos)
            if valid:
                self.body_clicked.emit(pos)
                event.accept()
                return
            # empty area
            self.empty_clicked.emit()
        super().mousePressEvent(event)


# ========================================================================
# Resize handle
# ========================================================================
class _ResizeHandle(QGraphicsRectItem):
    """A draggable square at one of the 8 points around the body.

    (dx, dy) encodes position: -1 means left/top, +1 means right/bottom,
    0 means the axis-centre side handle.
    """

    def __init__(self, dx: int, dy: int, scene: "_EditorScene") -> None:
        s = HANDLE_SIZE
        super().__init__(-s / 2, -s / 2, s, s)
        self._dx = dx
        self._dy = dy
        self._scene_ref = scene
        self.setBrush(QBrush(QColor(220, 220, 230)))
        self.setPen(QPen(QColor(30, 30, 40), 1))
        self.setZValue(5)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
        self.setCursor(self._cursor_for())
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self._dragging = False
        self._drag_start_size = (0.0, 0.0)
        self._drag_start_scene = QPointF()

    def _cursor_for(self):
        if self._dx == 0:
            return Qt.SizeVerCursor
        if self._dy == 0:
            return Qt.SizeHorCursor
        if self._dx * self._dy > 0:
            return Qt.SizeFDiagCursor
        return Qt.SizeBDiagCursor

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        self._dragging = True
        self._drag_start_size = self._scene_ref.body_size()
        self._drag_start_scene = event.scenePos()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        start_w, start_h = self._drag_start_size
        delta = event.scenePos() - self._drag_start_scene
        # Each handle extends the body symmetrically around the origin:
        # moving a right handle by +d increases width by 2d, similarly for
        # left handle by -d increases width by 2d. This keeps (0, 0) centred.
        new_w = start_w
        new_h = start_h
        if self._dx != 0:
            new_w = start_w + 2 * self._dx * delta.x()
        if self._dy != 0:
            new_h = start_h + 2 * self._dy * delta.y()
        new_w = max(MIN_BLOCK_W, snap(new_w))
        new_h = max(MIN_BLOCK_H, snap(new_h))
        self._scene_ref.body_resized.emit(new_w, new_h)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        event.accept()


# ========================================================================
# Editor view — fixed, no zoom/pan
# ========================================================================
class _EditorView(QGraphicsView):
    def __init__(self, scene: _EditorScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        # No interactive drag; we do our own click handling via the scene.
        self.setDragMode(QGraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(720, 480)
        # needed so mouseMoveEvent fires without a button pressed — that's
        # how we drive the placement-preview ghost pin.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        # Callback installed by the dialog; receives (scene_pos).
        self._on_hover = None

    def set_hover_callback(self, cb) -> None:
        self._on_hover = cb

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if self._on_hover is not None:
            self._on_hover(self.mapToScene(event.pos()))

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._on_hover is not None:
            self._on_hover(None)   # None → hide preview

    def wheelEvent(self, event) -> None:
        # Wheel zoom with anchor-under-cursor. No panning in this view —
        # the canvas is a fixed design surface, but zoom lets the user
        # work comfortably on fine pin placement.
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        new_scale = self.transform().m11() * factor
        # Bound zoom so the user can't disappear into either extreme.
        if 0.25 <= new_scale <= 5.0:
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            self.scale(factor, factor)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # On window resize, frame the whole canvas 1:1 (this also resets
        # any zoom the user applied — acceptable trade-off for a fixed
        # design surface).
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)


# ========================================================================
# Main editor dialog
# ========================================================================
class BlockEditorDialog(QDialog):
    """Create or edit one block template. Returns the finalised template
    through `accepted_template()` after accept()."""

    def __init__(
        self,
        library: BlockLibrary,
        template: Optional[BlockTemplate] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._editing_existing = template is not None
        self._original_name = template.name if template is not None else ""
        self._result: Optional[BlockTemplate] = None

        # --- initial state --------------------------------------------
        if template is None:
            self._name = ""
            self._shape = BlockShape(kind="rect", width=120.0, height=80.0)
            self._pins: list[PinDef] = []
            self._wires: list[InternalWire] = []
        else:
            self._name = template.name
            self._shape = BlockShape(
                kind=template.shape.kind,
                width=template.shape.width,
                height=template.shape.height,
            )
            self._pins = [
                PinDef(p.number, p.x, p.y, p.signal, p.direction, p.side)
                for p in template.pins
            ]
            self._wires = [
                InternalWire(w.source, w.target) for w in template.internal_wires
            ]

        self._mode = MODE_SELECT
        self._pending_pin_num: Optional[int] = None

        self._build_ui()
        self._apply_state_to_scene()
        self._apply_mode_ui()
        self.setWindowTitle(
            f"Edit block: {self._name}" if self._editing_existing else "New block"
        )
        self.resize(960, 700)

    # ==================================================================
    # UI construction
    # ==================================================================
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # --- top info row ---------------------------------------------
        top = QHBoxLayout()
        top.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit(self._name)
        self._name_edit.setMaximumWidth(180)
        self._name_edit.textChanged.connect(lambda t: setattr(self, "_name", t.strip()))
        top.addWidget(self._name_edit)

        top.addSpacing(20)

        top.addWidget(QLabel("Mode:"))
        self._rb_select  = QRadioButton("Select / Resize")
        self._rb_pins    = QRadioButton("Add pins")
        self._rb_connect = QRadioButton("Connect pins")
        self._rb_select.setChecked(True)
        self._mode_group = QButtonGroup(self)
        for rb, mode in (
            (self._rb_select,  MODE_SELECT),
            (self._rb_pins,    MODE_PINS),
            (self._rb_connect, MODE_CONNECT),
        ):
            self._mode_group.addButton(rb)
            top.addWidget(rb)
            rb.toggled.connect(lambda checked, m=mode: checked and self._set_mode(m))

        top.addStretch(1)
        root.addLayout(top)

        # --- signal/direction row -------------------------------------
        sig_row = QHBoxLayout()
        sig_row.addWidget(QLabel("Signal:"))
        self._cb_signal = QComboBox()
        for s in SignalType:
            self._cb_signal.addItem(s.value, s)
        self._cb_signal.setCurrentIndex(self._cb_signal.findData(SignalType.NODE))
        self._cb_signal.currentIndexChanged.connect(self._refresh_swatch)
        sig_row.addWidget(self._cb_signal)

        sig_row.addSpacing(16)
        sig_row.addWidget(QLabel("Direction:"))
        self._cb_direction = QComboBox()
        for d in PinDirection:
            self._cb_direction.addItem(d.value, d)
        self._cb_direction.setCurrentIndex(
            self._cb_direction.findData(PinDirection.INPUT))
        sig_row.addWidget(self._cb_direction)

        sig_row.addSpacing(16)
        sig_row.addWidget(QLabel("Marker:"))
        self._swatch = QFrame()
        self._swatch.setFixedSize(20, 20)
        self._swatch.setFrameShape(QFrame.Box)
        sig_row.addWidget(self._swatch)
        self._refresh_swatch()

        sig_row.addSpacing(24)
        sig_row.addWidget(QLabel("Shape W:"))
        self._sb_w = QDoubleSpinBox()
        self._sb_w.setRange(MIN_BLOCK_W, 2 * CANVAS_HALF_W - 20)
        self._sb_w.setSingleStep(PIN_PITCH)
        self._sb_w.setDecimals(0)
        self._sb_w.setValue(self._shape.width)
        self._sb_w.valueChanged.connect(self._on_spin_size)
        sig_row.addWidget(self._sb_w)

        sig_row.addWidget(QLabel("H:"))
        self._sb_h = QDoubleSpinBox()
        self._sb_h.setRange(MIN_BLOCK_H, 2 * CANVAS_HALF_H - 20)
        self._sb_h.setSingleStep(PIN_PITCH)
        self._sb_h.setDecimals(0)
        self._sb_h.setValue(self._shape.height)
        self._sb_h.valueChanged.connect(self._on_spin_size)
        sig_row.addWidget(self._sb_h)

        sig_row.addStretch(1)
        self._counts_label = QLabel("")
        sig_row.addWidget(self._counts_label)
        root.addLayout(sig_row)

        # --- scene view -----------------------------------------------
        self._scene = _EditorScene(self)
        self._scene.body_resized.connect(self._on_body_resized)
        self._scene.pin_clicked.connect(self._on_pin_clicked)
        self._scene.body_clicked.connect(self._on_body_clicked)
        self._scene.empty_clicked.connect(self._on_empty_clicked)
        self._view = _EditorView(self._scene, self)
        self._view.set_hover_callback(self._on_hover)
        root.addWidget(self._view, 1)

        # --- status + buttons -----------------------------------------
        bottom = QHBoxLayout()
        self._status = QLabel("")
        bottom.addWidget(self._status, 1)
        self._btn_undo_pin = QPushButton("Undo last pin")
        self._btn_undo_pin.clicked.connect(self._undo_last_pin)
        bottom.addWidget(self._btn_undo_pin)
        self._btn_clear = QPushButton("Clear all")
        self._btn_clear.clicked.connect(self._clear_all)
        bottom.addWidget(self._btn_clear)
        bottom.addSpacing(20)
        self._btn_ok = QPushButton("OK")
        self._btn_ok.setDefault(True)
        self._btn_ok.clicked.connect(self._on_accept)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self._btn_ok)
        bottom.addWidget(self._btn_cancel)
        root.addLayout(bottom)

    # ==================================================================
    # State → scene
    # ==================================================================
    def _apply_state_to_scene(self) -> None:
        self._scene.set_body_size(self._shape.width, self._shape.height)
        self._scene.rebuild_pins(self._pins)
        self._scene.rebuild_wires(self._wires, self._pins)
        self._refresh_counts()

    def _refresh_counts(self) -> None:
        self._counts_label.setText(
            f"Pins: {len(self._pins)}   Wires: {len(self._wires)}"
        )

    def _refresh_swatch(self) -> None:
        signal = self._cb_signal.currentData()
        c = DARK.pin_fill_for(signal)
        self._swatch.setStyleSheet(
            f"background:rgb({c.red()},{c.green()},{c.blue()}); border:1px solid #888;"
        )

    # ==================================================================
    # Mode
    # ==================================================================
    def _set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._pending_pin_num = None
        self._scene.set_pending_pin(None)
        self._apply_mode_ui()

    def _apply_mode_ui(self) -> None:
        m = self._mode
        self._scene.set_handles_visible(m == MODE_SELECT)
        self._scene.set_placement_mode(m == MODE_PINS)
        enable_sigdir = (m == MODE_PINS)
        self._cb_signal.setEnabled(enable_sigdir)
        self._cb_direction.setEnabled(enable_sigdir)
        self._swatch.setEnabled(enable_sigdir)
        self._sb_w.setEnabled(m == MODE_SELECT)
        self._sb_h.setEnabled(m == MODE_SELECT)

        # In Pins mode we hide the system cursor so the ghost-pin preview
        # IS the cursor. In any other mode we restore the default pointer.
        if m == MODE_PINS:
            self._view.viewport().setCursor(Qt.BlankCursor)
        else:
            self._view.viewport().unsetCursor()

        hint = {
            MODE_SELECT:  "Drag the handles to resize the block. Width and height snap to grid.",
            MODE_PINS:    "Move the ghost pin to a side and click to place. Green = OK, red = slot already taken.",
            MODE_CONNECT: "Click an output, then an input — or vice versa — to create an internal wire. Click empty space to cancel a pending selection.",
        }[m]
        self._status.setText(hint)

    # ==================================================================
    # Body size
    # ==================================================================
    def _on_body_resized(self, w: float, h: float) -> None:
        """Resize request coming from dragging a handle."""
        w, h = self._enforce_minimums(w, h)
        self._shape.width = w
        self._shape.height = h
        self._scene.set_body_size(w, h)
        self._keep_pins_on_sides()
        self._sync_spin_boxes()

    def _on_spin_size(self) -> None:
        """Resize request coming from the W/H spin boxes."""
        w, h = self._enforce_minimums(self._sb_w.value(), self._sb_h.value())
        # If enforcement clipped the value, write it back to the spin box —
        # this is what tells the user "can't go smaller".
        if w != self._sb_w.value() or h != self._sb_h.value():
            self._sync_spin_boxes_to(w, h)
            self._status.setText(
                f"Minimum size is {w:.0f}×{h:.0f} — limited by currently placed pins."
            )
        self._shape.width = w
        self._shape.height = h
        self._scene.set_body_size(w, h)
        self._keep_pins_on_sides()

    # ------------------------------------------------------------------
    def _required_minimums(self) -> tuple[float, float]:
        """Smallest (width, height) the block is allowed to have.

        The perpendicular coordinate of each pin is the wall it is attached
        to, and tracks the wall when the block is resized. So pins on
        LEFT/RIGHT do NOT constrain width (they simply slide along with the
        wall), but they DO constrain height — they must stay away from the
        corners so they don't get clamped together or escape off the edge.

        Rule per pin on side:
          * LEFT or RIGHT   → height must be ≥ 2 · (|p.y| + PIN_PITCH/2)
          * TOP  or BOTTOM  → width  must be ≥ 2 · (|p.x| + PIN_PITCH/2)

        This gives symmetric behaviour: you can always shrink along the
        axis pins are attached to, but not along the axis they sit on.
        """
        req_w = MIN_BLOCK_W
        req_h = MIN_BLOCK_H
        for p in self._pins:
            if p.side in (SIDE_LEFT, SIDE_RIGHT):
                req_h = max(req_h, 2 * (abs(p.y) + PIN_PITCH / 2))
            elif p.side in (SIDE_TOP, SIDE_BOTTOM):
                req_w = max(req_w, 2 * (abs(p.x) + PIN_PITCH / 2))
        return req_w, req_h

    def _enforce_minimums(self, w: float, h: float) -> tuple[float, float]:
        req_w, req_h = self._required_minimums()
        return max(req_w, w), max(req_h, h)

    def _keep_pins_on_sides(self) -> None:
        """After a resize, re-project each pin onto its recorded side and
        re-clamp the along-axis so none slide past a corner."""
        w, h = self._shape.width, self._shape.height
        for p in self._pins:
            if p.side == SIDE_LEFT:
                p.x = -w / 2
                p.y = _clamp_along(p.y, h)
            elif p.side == SIDE_RIGHT:
                p.x = w / 2
                p.y = _clamp_along(p.y, h)
            elif p.side == SIDE_TOP:
                p.y = -h / 2
                p.x = _clamp_along(p.x, w)
            elif p.side == SIDE_BOTTOM:
                p.y = h / 2
                p.x = _clamp_along(p.x, w)
            else:
                # Unknown side marker (shouldn't happen) — fall back to
                # geometric nearest-edge projection.
                side, nx, ny = _snap_to_side(p.x, p.y, w, h)
                p.side, p.x, p.y = side, nx, ny
        self._scene.rebuild_pins(self._pins)
        self._scene.rebuild_wires(self._wires, self._pins)
        self._refresh_counts()

    def _sync_spin_boxes(self) -> None:
        self._sync_spin_boxes_to(self._shape.width, self._shape.height)

    def _sync_spin_boxes_to(self, w: float, h: float) -> None:
        self._sb_w.blockSignals(True); self._sb_w.setValue(w); self._sb_w.blockSignals(False)
        self._sb_h.blockSignals(True); self._sb_h.setValue(h); self._sb_h.blockSignals(False)

    # ==================================================================
    # Pin placement (Pins mode)
    # ==================================================================
    def _on_body_clicked(self, scene_pos: QPointF) -> None:
        """A click inside the block body in Pins mode → snap to the nearest
        side and place a new pin there."""
        if self._mode != MODE_PINS:
            return
        w, h = self._shape.width, self._shape.height
        side, x, y = _snap_to_side(scene_pos.x(), scene_pos.y(), w, h)

        # Don't place two pins on the same slot.
        if any(abs(p.x - x) < 0.5 and abs(p.y - y) < 0.5 for p in self._pins):
            self._status.setText(
                f"A pin is already anchored at this slot on the {side} side."
            )
            return

        number = self._next_pin_number()
        pin = PinDef(
            number=number, x=x, y=y,
            signal=self._cb_signal.currentData(),
            direction=self._cb_direction.currentData(),
            side=side,
        )
        self._pins.append(pin)
        self._scene.rebuild_pins(self._pins)
        self._refresh_counts()
        # The freshly-placed pin now occupies this slot; re-evaluate the
        # preview so the ghost tint flips from green to red without the
        # user having to move the mouse.
        signal = self._cb_signal.currentData()
        self._scene.update_pin_preview(
            scene_pos,
            base_colour=DARK.pin_fill_for(signal),
            slot_occupied=True,
        )
        self._status.setText(
            f"Placed pin {number} on {side} side "
            f"({pin.signal.value}, {pin.direction.value})."
        )

    def _next_pin_number(self) -> int:
        used = {p.number for p in self._pins}
        n = 1
        while n in used:
            n += 1
        return n

    def _slot_taken(self, x: float, y: float) -> bool:
        return any(abs(p.x - x) < 0.5 and abs(p.y - y) < 0.5 for p in self._pins)

    # ==================================================================
    # Hover (drives the placement-mode ghost pin)
    # ==================================================================
    def _on_hover(self, scene_pos) -> None:
        """Called by _EditorView for every mouse move.

        scene_pos is None when the cursor left the viewport — hide preview.
        """
        if self._mode != MODE_PINS:
            return
        if scene_pos is None:
            self._scene._hide_pin_preview()
            return

        # Where would this click actually land? We need the same
        # side-projected point the scene uses so the preview ring shows
        # the true target slot.
        w, h = self._shape.width, self._shape.height
        _side, x, y = _snap_to_side(scene_pos.x(), scene_pos.y(), w, h)

        signal = self._cb_signal.currentData()
        base_colour = DARK.pin_fill_for(signal)
        self._scene.update_pin_preview(
            scene_pos,
            base_colour=base_colour,
            slot_occupied=self._slot_taken(x, y),
        )

    # ==================================================================
    # Pin click (Connect mode primary path)
    # ==================================================================
    def _on_pin_clicked(self, pin_number: int) -> None:
        """Handle a LMB click on a pin in Connect mode.

        State machine:
            1st click   → remember the pin as "pending start".
            2nd click   → validate and commit the wire.

        Validation rules (all silent — they just flash a status message):
          * Clicking the same pin twice cancels the pending selection.
          * The two pins must have opposite directions (one OUTPUT,
            one INPUT). Click order doesn't matter — we always store
            the wire as source=output, target=input.
          * Each input pin accepts at most one incoming wire
            (fan-in = 1). Outputs can drive many inputs.

        Click order doesn't matter because we care about the data
        ("who drives whom"), not the UX flow. So the user can start
        from either end.
        """
        pin = self._pin_by_number(pin_number)
        if pin is None:
            return

        if self._pending_pin_num is None:
            self._pending_pin_num = pin_number
            self._scene.set_pending_pin(pin)
            self._status.setText(
                f"Pin {pin.number} ({pin.direction.value.upper()}) selected — "
                f"click the other end to connect."
            )
            return

        if pin_number == self._pending_pin_num:
            self._pending_pin_num = None
            self._scene.set_pending_pin(None)
            self._status.setText("Selection cancelled.")
            return

        first = self._pin_by_number(self._pending_pin_num)
        second = pin

        if first.direction == second.direction:
            self._pending_pin_num = None
            self._scene.set_pending_pin(None)
            self._status.setText(
                f"Can't connect two {first.direction.value.upper()} pins — "
                f"one side must be OUTPUT, the other INPUT."
            )
            return

        if first.direction == PinDirection.OUTPUT:
            source, target = first, second
        else:
            source, target = second, first

        if any(w.target == target.number for w in self._wires):
            self._pending_pin_num = None
            self._scene.set_pending_pin(None)
            self._status.setText(
                f"Input pin {target.number} already has an incoming wire "
                f"(one-output-per-input rule)."
            )
            return

        self._wires.append(InternalWire(source=source.number, target=target.number))
        self._pending_pin_num = None
        self._scene.set_pending_pin(None)
        self._scene.rebuild_wires(self._wires, self._pins)
        self._refresh_counts()
        self._status.setText(
            f"Connected pin {source.number} (OUTPUT) → pin {target.number} (INPUT)."
        )

    def _on_empty_clicked(self) -> None:
        if self._mode == MODE_CONNECT and self._pending_pin_num is not None:
            self._pending_pin_num = None
            self._scene.set_pending_pin(None)
            self._status.setText("Selection cancelled.")

    # ==================================================================
    # Undo / clear
    # ==================================================================
    def _undo_last_pin(self) -> None:
        if not self._pins:
            return
        dropped = self._pins.pop()
        # drop wires referencing it
        self._wires = [
            w for w in self._wires
            if w.source != dropped.number and w.target != dropped.number
        ]
        self._pending_pin_num = None
        self._scene.set_pending_pin(None)
        self._scene.rebuild_pins(self._pins)
        self._scene.rebuild_wires(self._wires, self._pins)
        self._refresh_counts()
        self._status.setText(f"Removed pin {dropped.number}.")

    def _clear_all(self) -> None:
        self._pins.clear()
        self._wires.clear()
        self._pending_pin_num = None
        self._scene.set_pending_pin(None)
        self._scene.rebuild_pins(self._pins)
        self._scene.rebuild_wires(self._wires, self._pins)
        self._refresh_counts()
        self._status.setText("Cleared.")

    # ==================================================================
    # Helpers
    # ==================================================================
    def _pin_by_number(self, n: int) -> Optional[PinDef]:
        for p in self._pins:
            if p.number == n:
                return p
        return None

    # ==================================================================
    # Accept
    # ==================================================================
    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid name", "Block name is required.")
            return
        # Name collision check (allow saving unchanged name when editing)
        collides = self._library.exists(name) and (
            not self._editing_existing or name != self._original_name
        )
        if collides:
            res = QMessageBox.question(
                self, "Name already used",
                f'A block named "{name}" already exists in the library. Overwrite it?'
            )
            if res != QMessageBox.Yes:
                return

        # Edit-rename: delete the old JSON so we don't leave an orphan
        if self._editing_existing and name != self._original_name:
            old = self._library.directory / f"{self._original_name}.json"
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass

        try:
            self._result = self._library.commit(
                name=name,
                shape=self._shape,
                pins=self._pins,
                internal_wires=self._wires,
                overwrite=True,
            )
        except (OSError, ValueError) as err:
            QMessageBox.critical(self, "Save failed", str(err))
            return
        self.accept()

    def accepted_template(self) -> Optional[BlockTemplate]:
        return self._result