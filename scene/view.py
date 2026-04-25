"""SchematicView — QGraphicsView with wheel zoom, LMB pan, and wire-aware RMB."""
from PyQt5.QtCore import QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QMouseEvent, QPainter, QWheelEvent
from PyQt5.QtWidgets import QAction, QGraphicsView, QMenu


class SchematicView(QGraphicsView):
    ZOOM_IN_FACTOR  = 1.20
    ZOOM_OUT_FACTOR = 1.0 / ZOOM_IN_FACTOR
    MIN_ZOOM_STEPS  = -25
    MAX_ZOOM_STEPS  = 25

    scene_pos_changed       = pyqtSignal(QPointF)
    add_block_requested     = pyqtSignal(QPointF)
    new_template_requested  = pyqtSignal(QPointF)

    def __init__(self, scene, parent=None) -> None:
        super().__init__(scene, parent)

        self.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)

        self._zoom_step = 0
        self.centerOn(0, 0)

        # React to the scene's wire-mode so we can feed back a cross-cursor
        scene.wire_mode_changed.connect(self._on_wire_mode_changed)

    # ------------------------------------------------------------------
    def _on_wire_mode_changed(self, on: bool) -> None:
        if on:
            # ScrollHandDrag insists on its own cursor while a drag is
            # active; but no drag is active when wire mode starts,
            # so override works as expected.
            self.viewport().setCursor(Qt.CrossCursor)
        else:
            self.viewport().unsetCursor()

    # ------------------------------------------------------------------
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() > 0:
            factor, step = self.ZOOM_IN_FACTOR, +1
        else:
            factor, step = self.ZOOM_OUT_FACTOR, -1
        new_step = self._zoom_step + step
        if self.MIN_ZOOM_STEPS <= new_step <= self.MAX_ZOOM_STEPS:
            self.scale(factor, factor)
            self._zoom_step = new_step
        event.accept()

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._zoom_step = 0

    def fit_content(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if rect.isEmpty():
            self.reset_zoom()
            self.centerOn(0, 0)
            return
        self.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
        self._zoom_step = 0

    # ------------------------------------------------------------------
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.scene_pos_changed.emit(self.mapToScene(event.pos()))
        super().mouseMoveEvent(event)

    # ------------------------------------------------------------------
    def contextMenuEvent(self, event) -> None:
        # Right-click while drawing a wire ends it (dangling), no menu.
        scene = self.scene()
        if scene is not None and getattr(scene, "is_wire_mode", lambda: False)():
            scene.cancel_wire()
            event.accept()
            return

        menu = QMenu(self)
        act_add = QAction("Add Block…", menu)
        act_new = QAction("New Block…", menu)
        menu.addAction(act_add)
        menu.addAction(act_new)

        chosen = menu.exec_(event.globalPos())
        if chosen is None:
            return
        scene_pos = self.mapToScene(event.pos())
        if chosen is act_add:
            self.add_block_requested.emit(scene_pos)
        elif chosen is act_new:
            self.new_template_requested.emit(scene_pos)

    # ------------------------------------------------------------------
    def view_center_in_scene(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())