"""SchematicScene — holds blocks + wires, manages interaction modes.

Responsibilities kept in this file:
    * background + optional grid (theme-aware)
    * block lifecycle (add, remove, name uniqueness)
    * wire-drawing mode (state machine started by clicking an unoccupied pin)
    * pin occupancy bookkeeping
    * keyboard handling (Delete removes selection, Escape ends wire)
"""
from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QKeyEvent, QPainter, QPen
from PyQt5.QtWidgets import QGraphicsPathItem, QGraphicsScene, QGraphicsSceneMouseEvent

from editor.library import BlockTemplate

from theme import DARK, LIGHT, Theme

from .block_item import BlockItem, PinItem
from .wire import PinRef, WireItem, build_ortho_path


GRID_SIZE        = 20
GRID_MAJOR_EVERY = 5
PIN_HIT_RADIUS   = 8   # scene units


class SchematicScene(QGraphicsScene):
    wire_mode_changed = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._theme: Theme = DARK
        self._show_grid: bool = True

        self.setSceneRect(QRectF(-10_000, -10_000, 20_000, 20_000))

        # wire-drawing state
        self._wire_mode: bool = False
        self._wire_start_pin: Optional[PinRef] = None
        self._wire_start_side: Optional[str] = None
        self._wire_corners: list[QPointF] = []
        self._wire_preview: Optional[QGraphicsPathItem] = None

        # occupancy + wire registry
        self._wires: list[WireItem] = []
        self._occupied_pins: set[PinRef] = set()

    # ==================================================================
    # Theme & grid
    # ==================================================================
    @property
    def theme(self) -> Theme:
        return self._theme

    def set_theme(self, theme: Theme) -> None:
        if theme is self._theme:
            return
        self._theme = theme
        for b in self.block_items():
            b.apply_theme(theme)
        for w in self._wires:
            w.apply_theme(theme)
        if self._wire_preview is not None:
            self._wire_preview.setPen(self._make_preview_pen())
        self.update()

    def toggle_theme(self) -> None:
        self.set_theme(LIGHT if self._theme is DARK else DARK)

    def set_show_grid(self, show: bool) -> None:
        if show == self._show_grid:
            return
        self._show_grid = show
        self.update()

    # ------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, self._theme.bg)
        if not self._show_grid:
            return

        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE)
        top  = int(rect.top())  - (int(rect.top())  % GRID_SIZE)

        minor_pen = QPen(self._theme.grid_minor, 0)
        major_pen = QPen(self._theme.grid_major, 0)

        minor_v, minor_h, major_v, major_h = [], [], [], []

        x = left
        while x < rect.right():
            (major_v if x % (GRID_SIZE * GRID_MAJOR_EVERY) == 0 else minor_v).append(x)
            x += GRID_SIZE
        y = top
        while y < rect.bottom():
            (major_h if y % (GRID_SIZE * GRID_MAJOR_EVERY) == 0 else minor_h).append(y)
            y += GRID_SIZE

        painter.setPen(minor_pen)
        for x in minor_v:
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
        for y in minor_h:
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
        painter.setPen(major_pen)
        for x in major_v:
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
        for y in major_h:
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

    # ==================================================================
    # Wires follow blocks
    # ==================================================================
    def on_block_moved(self, block: BlockItem) -> None:
        """Called by BlockItem.itemChange after its scene position changes.

        Updates the first/last corner of every wire whose start/end pin
        lives on this block, so the wire endpoint stays glued to the pin.
        Waypoints in the middle intentionally stay put — the wire stretches
        rather than translating rigidly, matching KiCad's feel.
        """
        name = block.instance_name
        for w in self._wires:
            if w.start_pin is not None and w.start_pin[0] == name:
                pin = block.pin_by_number(w.start_pin[1])
                if pin is not None:
                    w.update_corner(0, pin.mapToScene(0.0, 0.0))
            # end_pin None means the wire is dangling — its tail is a free
            # scene-space point and must NOT track the block.
            if w.end_pin is not None and w.end_pin[0] == name:
                pin = block.pin_by_number(w.end_pin[1])
                if pin is not None:
                    w.update_corner(-1, pin.mapToScene(0.0, 0.0))

    # ==================================================================
    # Blocks
    # ==================================================================
    def block_items(self) -> list[BlockItem]:
        return [it for it in self.items() if isinstance(it, BlockItem)]

    def _block_by_name(self, name: str) -> Optional[BlockItem]:
        for b in self.block_items():
            if b.instance_name == name:
                return b
        return None

    def used_instance_names(self) -> set[str]:
        return {b.instance_name for b in self.block_items()}

    def suggest_instance_name(self, base: str) -> str:
        used = self.used_instance_names()
        i = 1
        while f"{base}_{i}" in used:
            i += 1
        return f"{base}_{i}"

    def add_block(self, template: BlockTemplate, instance_name: str, pos: QPointF) -> BlockItem:
        if instance_name in self.used_instance_names():
            raise ValueError(f"Instance name '{instance_name}' is already taken.")
        item = BlockItem(template, instance_name, theme=self._theme)
        item.setPos(pos)
        self.addItem(item)
        # restore occupancy visual for any pins that were already in the set
        # (happens e.g. if we later implement load-from-JSON)
        for pin_ref in self._occupied_pins:
            if pin_ref[0] == instance_name:
                item.set_pin_occupied(pin_ref[1], True)
        return item

    # ==================================================================
    # Wires / pin occupancy
    # ==================================================================
    def is_pin_occupied(self, block_name: str, pin_number: int) -> bool:
        return (block_name, pin_number) in self._occupied_pins

    def is_wire_mode(self) -> bool:
        return self._wire_mode

    def cancel_wire(self) -> None:
        """Public: used by the view when the user right-clicks or presses Esc."""
        if not self._wire_mode:
            return
        if len(self._wire_corners) <= 1:
            self._reset_wire_mode()
        else:
            self._finalize_wire(end_pin=None)

    # ..................................................................
    def _pin_at_scene_pos(self, scene_pos: QPointF) -> Optional[tuple[str, int, QPointF, PinItem]]:
        for block in self.block_items():
            for pin in block.pin_items:
                pin_pos = pin.mapToScene(0.0, 0.0)
                dx = pin_pos.x() - scene_pos.x()
                dy = pin_pos.y() - scene_pos.y()
                if dx * dx + dy * dy <= PIN_HIT_RADIUS * PIN_HIT_RADIUS:
                    return (block.instance_name, pin.number, pin_pos, pin)
        return None

    def _make_preview_pen(self) -> QPen:
        pen = QPen(self._theme.wire_preview, 2, Qt.DashLine, Qt.SquareCap, Qt.RoundJoin)
        return pen

    # ..................................................................
    def _start_wire(self, pin_ref: PinRef, start_pos: QPointF,
                    start_side: Optional[str] = None) -> None:
        self._wire_mode = True
        self._wire_start_pin = pin_ref
        self._wire_start_side = start_side
        self._wire_corners = [start_pos]

        self._wire_preview = QGraphicsPathItem()
        self._wire_preview.setPen(self._make_preview_pen())
        self._wire_preview.setZValue(-1)
        self.addItem(self._wire_preview)

        self._update_preview(start_pos)
        self.wire_mode_changed.emit(True)

    def _update_preview(self, cursor: QPointF) -> None:
        if self._wire_preview is None:
            return
        self._wire_preview.setPath(build_ortho_path(
            self._wire_corners, cursor,
            start_side=self._wire_start_side,
        ))

    def _wire_click(self, scene_pos: QPointF) -> None:
        """Handle an LMB click while in wire-drawing mode."""
        pin_hit = self._pin_at_scene_pos(scene_pos)
        if pin_hit is not None:
            block_name, pin_num, pin_pos, pin_item = pin_hit
            pin_ref = (block_name, pin_num)
            # can't land on the start pin itself or on an already occupied pin
            if pin_ref == self._wire_start_pin:
                return
            if self.is_pin_occupied(block_name, pin_num):
                return
            # valid endpoint → commit and finalise
            self._wire_corners.append(pin_pos)
            self._finalize_wire(end_pin=pin_ref, end_side=pin_item.pin_def.side)
            return
        # empty space → just a waypoint
        self._wire_corners.append(scene_pos)

    def _finalize_wire(self, end_pin: Optional[PinRef],
                       end_side: Optional[str] = None) -> None:
        assert self._wire_start_pin is not None
        wire = WireItem(
            corners=self._wire_corners,
            start_pin=self._wire_start_pin,
            end_pin=end_pin,
            theme=self._theme,
            start_side=self._wire_start_side,
            end_side=end_side,
        )
        self.addItem(wire)
        self._wires.append(wire)
        self._mark_pin_occupied(self._wire_start_pin, True)
        if end_pin is not None:
            self._mark_pin_occupied(end_pin, True)
        self._reset_wire_mode()

    def _reset_wire_mode(self) -> None:
        if self._wire_preview is not None:
            self.removeItem(self._wire_preview)
            self._wire_preview = None
        self._wire_mode = False
        self._wire_start_pin = None
        self._wire_start_side = None
        self._wire_corners = []
        self.wire_mode_changed.emit(False)

    def _mark_pin_occupied(self, pin_ref: PinRef, occupied: bool) -> None:
        if occupied:
            self._occupied_pins.add(pin_ref)
        else:
            self._occupied_pins.discard(pin_ref)
        block = self._block_by_name(pin_ref[0])
        if block is not None:
            block.set_pin_occupied(pin_ref[1], occupied)

    # ==================================================================
    # Removal
    # ==================================================================
    def remove_selected(self) -> int:
        removed = 0
        # copy list because we'll be modifying the scene
        for it in list(self.selectedItems()):
            if isinstance(it, BlockItem):
                self._remove_block(it)
                removed += 1
            elif isinstance(it, WireItem):
                self._remove_wire(it)
                removed += 1
        return removed

    def _remove_block(self, block: BlockItem) -> None:
        # delete any wires touching this block's pins first
        doomed = [
            w for w in self._wires
            if (w.start_pin is not None and w.start_pin[0] == block.instance_name)
            or (w.end_pin   is not None and w.end_pin[0]   == block.instance_name)
        ]
        for w in doomed:
            self._remove_wire(w)
        # forget any lingering occupancy entries for this block
        self._occupied_pins = {
            p for p in self._occupied_pins if p[0] != block.instance_name
        }
        self.removeItem(block)

    def _remove_wire(self, wire: WireItem) -> None:
        for pin_ref in (wire.start_pin, wire.end_pin):
            if pin_ref is not None and pin_ref in self._occupied_pins:
                self._mark_pin_occupied(pin_ref, False)
        if wire in self._wires:
            self._wires.remove(wire)
        self.removeItem(wire)

    def clear_user_items(self) -> None:
        # cancel any in-progress wire first
        if self._wire_mode:
            self._reset_wire_mode()
        for w in list(self._wires):
            self._remove_wire(w)
        for b in list(self.block_items()):
            self._remove_block(b)

    # ==================================================================
    # Save / load the whole schematic (macro-level JSON)
    # ==================================================================
    SCHEMATIC_VERSION = 1

    def to_dict(self) -> dict:
        """Snapshot of every block + wire on the scene.

        Block templates are NOT embedded — only the template `name` is
        stored. Loading a schematic requires the same block library to be
        present; missing templates are reported to the caller.
        """
        return {
            "version": self.SCHEMATIC_VERSION,
            "blocks":  [b.to_dict() for b in self.block_items()],
            "wires":   [w.to_dict() for w in self._wires],
        }

    def load_from_dict(self, data: dict, library) -> list[str]:
        """Replace current scene contents with `data`.

        Returns a list of non-fatal issues (missing templates, dropped
        wires, etc.) so the caller can surface them to the user. Raises
        ValueError only if the payload itself is structurally invalid.
        """
        if not isinstance(data, dict) or "blocks" not in data:
            raise ValueError("Invalid schematic — missing 'blocks' field.")

        warnings: list[str] = []
        version = data.get("version", 1)
        if version > self.SCHEMATIC_VERSION:
            warnings.append(
                f"File was saved by a newer editor (version {version}); "
                f"loading with best effort."
            )

        # Wipe current scene first so the new state isn't mixed with old.
        self.clear_user_items()

        # Index library templates by name for quick lookup.
        templates = {t.name: t for t in library.list_templates()}

        # --- blocks ---------------------------------------------------
        placed: set[str] = set()
        for blk in data.get("blocks", []):
            tpl_name = blk.get("template")
            inst = blk.get("instance_name")
            x = float(blk.get("x", 0.0))
            y = float(blk.get("y", 0.0))

            if not tpl_name or not inst:
                warnings.append(f"Skipped block with missing name/template: {blk!r}")
                continue
            tpl = templates.get(tpl_name)
            if tpl is None:
                warnings.append(
                    f"Skipped block '{inst}' — template '{tpl_name}' not in library."
                )
                continue
            if inst in placed:
                warnings.append(f"Duplicate instance name '{inst}' — skipping second.")
                continue
            try:
                self.add_block(tpl, inst, QPointF(x, y))
                placed.add(inst)
            except ValueError as err:
                warnings.append(f"Could not add block '{inst}': {err}")

        # --- wires ----------------------------------------------------
        for wd in data.get("wires", []):
            sp = wd.get("start_pin")
            ep = wd.get("end_pin")
            if not sp:
                warnings.append("Skipped wire with no start_pin.")
                continue

            start_pin = (sp["block"], int(sp["pin"]))
            end_pin   = (ep["block"], int(ep["pin"])) if ep else None

            # Ensure referenced blocks/pins exist.
            if start_pin[0] not in placed:
                warnings.append(
                    f"Dropped wire — start block '{start_pin[0]}' missing."
                )
                continue
            if end_pin is not None and end_pin[0] not in placed:
                warnings.append(
                    f"Dropped wire — end block '{end_pin[0]}' missing."
                )
                continue

            corners = [QPointF(float(c["x"]), float(c["y"])) for c in wd.get("corners", [])]
            if not corners:
                warnings.append("Skipped wire with no corners.")
                continue

            wire = WireItem(
                corners=corners,
                start_pin=start_pin,
                end_pin=end_pin,
                theme=self._theme,
                start_side=wd.get("start_side"),
                end_side=wd.get("end_side"),
            )
            self.addItem(wire)
            self._wires.append(wire)
            self._mark_pin_occupied(start_pin, True)
            if end_pin is not None:
                self._mark_pin_occupied(end_pin, True)

        return warnings

    # ==================================================================
    # Input routing
    # ==================================================================
    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            scene_pos = event.scenePos()
            if self._wire_mode:
                self._wire_click(scene_pos)
                event.accept()
                return
            # idle mode — only intercept if the click lands on an unoccupied pin
            pin_hit = self._pin_at_scene_pos(scene_pos)
            if pin_hit is not None:
                block_name, pin_num, pin_pos, pin_item = pin_hit
                if not self.is_pin_occupied(block_name, pin_num):
                    self._start_wire(
                        (block_name, pin_num), pin_pos,
                        start_side=pin_item.pin_def.side,
                    )
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._wire_mode:
            self._update_preview(event.scenePos())
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._wire_mode and event.button() == Qt.LeftButton:
            # commit the current cursor position, then end
            self._wire_click(event.scenePos())
            if self._wire_mode:   # not finalised by a pin-hit
                self.cancel_wire()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._wire_mode and event.key() == Qt.Key_Escape:
            self.cancel_wire()
            event.accept()
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.remove_selected() > 0:
                event.accept()
                return
        super().keyPressEvent(event)