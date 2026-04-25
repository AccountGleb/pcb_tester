"""Main application window — wires scene, view, library, and settings panel."""
import json
from pathlib import Path

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
    QWidget,
)

from editor import BlockEditorDialog, BlockLibrary, BlockTemplate
from scene import (
    BlockSelectionDialog,
    SchematicScene,
    SchematicView,
    ask_unique_instance_name,
)
from theme import DARK, LIGHT


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Board Test Automation — Schematic Editor")
        self.resize(1280, 820)

        self.library = BlockLibrary()

        # --- scene & view -----------------------------------------------
        self.scene = SchematicScene(self)
        self.view = SchematicView(self.scene, self)
        self.setCentralWidget(self.view)

        self.view.scene_pos_changed.connect(self._on_scene_pos_changed)
        self.view.add_block_requested.connect(self._add_block_flow)
        self.view.new_template_requested.connect(lambda _p: self._new_template_flow())
        self.scene.wire_mode_changed.connect(self._on_wire_mode_changed)

        # Path of the schematic currently open, or None if unsaved.
        self._current_path: Path | None = None
        self._refresh_title()

        # --- top panel --------------------------------------------------
        self._build_toolbar()

        self.statusBar().showMessage(f"Ready — library: {self.library.directory}")

    # ==================================================================
    # Toolbar
    # ==================================================================
    def _build_toolbar(self) -> None:
        tb = QToolBar("Settings", self)
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)

        open_act = QAction("Open…", self)
        open_act.setShortcut(QKeySequence("Ctrl+O"))
        open_act.triggered.connect(self._open_schematic)
        tb.addAction(open_act)

        save_act = QAction("Save", self)
        save_act.setShortcut(QKeySequence("Ctrl+S"))
        save_act.triggered.connect(self._save_schematic)
        tb.addAction(save_act)

        save_as_act = QAction("Save As…", self)
        save_as_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_act.triggered.connect(self._save_schematic_as)
        tb.addAction(save_as_act)

        tb.addSeparator()

        add = QAction("Add Block", self)
        add.setShortcut(QKeySequence("A"))
        add.triggered.connect(lambda: self._add_block_flow(self.view.view_center_in_scene()))
        tb.addAction(add)

        new = QAction("New Block…", self)
        new.setShortcut(QKeySequence("N"))
        new.triggered.connect(self._new_template_flow)
        tb.addAction(new)

        tb.addSeparator()

        # ----- switches ------------------------------------------------
        self._cb_dark = QCheckBox("Dark theme")
        self._cb_dark.setChecked(True)
        self._cb_dark.setToolTip("Toggle between dark and light background")
        self._cb_dark.toggled.connect(self._on_dark_toggled)
        tb.addWidget(self._spacer(6))
        tb.addWidget(self._cb_dark)

        self._cb_grid = QCheckBox("Show grid")
        self._cb_grid.setChecked(True)
        self._cb_grid.setToolTip("Show or hide the background grid")
        self._cb_grid.toggled.connect(self.scene.set_show_grid)
        tb.addWidget(self._spacer(8))
        tb.addWidget(self._cb_grid)
        tb.addWidget(self._spacer(6))

        tb.addSeparator()

        fit = QAction("Fit View", self)
        fit.setShortcut(QKeySequence("F"))
        fit.triggered.connect(self.view.fit_content)
        tb.addAction(fit)

        reset = QAction("Reset Zoom", self)
        reset.setShortcut(QKeySequence("0"))
        reset.triggered.connect(self.view.reset_zoom)
        tb.addAction(reset)

        tb.addSeparator()

        clear = QAction("Clear Scene", self)
        clear.triggered.connect(self.scene.clear_user_items)
        tb.addAction(clear)

    @staticmethod
    def _spacer(width_px: int) -> QWidget:
        w = QWidget()
        w.setFixedWidth(width_px)
        return w

    # ==================================================================
    # Slots
    # ==================================================================
    def _on_dark_toggled(self, is_dark: bool) -> None:
        self.scene.set_theme(DARK if is_dark else LIGHT)

    def _on_scene_pos_changed(self, p: QPointF) -> None:
        base = f"x = {p.x():.0f}   y = {p.y():.0f}"
        if self.scene.is_wire_mode():
            base += "    [wire mode — click to add waypoint, Esc / right-click / double-click to end]"
        self.statusBar().showMessage(base)

    def _on_wire_mode_changed(self, on: bool) -> None:
        if on:
            self.statusBar().showMessage(
                "Wire mode — click to add waypoint, click an unoccupied pin to land there, "
                "Esc / right-click / double-click to end (dangling)."
            )
        else:
            self.statusBar().showMessage("Ready")

    # ==================================================================
    # Flows
    # ==================================================================
    def _add_block_flow(self, pos: QPointF) -> None:
        picker = BlockSelectionDialog(self.library, self)
        if picker.exec_() != QDialog.Accepted:
            return
        template = picker.selected_template()
        if template is None:
            return
        self._place_block(template, pos)

    def _new_template_flow(self) -> None:
        dlg = BlockEditorDialog(self.library, template=None, parent=self)
        dlg.exec_()

    def _place_block(self, template: BlockTemplate, pos: QPointF) -> None:
        suggestion = self.scene.suggest_instance_name(template.name)
        name = ask_unique_instance_name(self, self.scene.used_instance_names(), suggestion)
        if not name:
            return
        try:
            self.scene.add_block(template, name, pos)
        except ValueError as err:
            QMessageBox.critical(self, "Could not add block", str(err))

    # ==================================================================
    # Save / open the whole schematic
    # ==================================================================
    FILE_FILTER = "Schematic JSON (*.json);;All files (*)"
    FILE_EXT = ".json"

    def _refresh_title(self) -> None:
        base = "Board Test Automation — Schematic Editor"
        if self._current_path is not None:
            self.setWindowTitle(f"{self._current_path.name} — {base}")
        else:
            self.setWindowTitle(f"Untitled — {base}")

    def _save_schematic(self) -> None:
        """Ctrl+S: save to the current path, or fall through to Save As…"""
        if self._current_path is None:
            self._save_schematic_as()
            return
        self._write_to(self._current_path)

    def _save_schematic_as(self) -> None:
        default_name = (
            self._current_path.name if self._current_path is not None
            else f"schematic{self.FILE_EXT}"
        )
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save schematic",
            str(Path.cwd() / default_name),
            self.FILE_FILTER,
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix == "":
            path = path.with_suffix(self.FILE_EXT)
        self._write_to(path)

    def _write_to(self, path: Path) -> None:
        payload = self.scene.to_dict()
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except OSError as err:
            QMessageBox.critical(self, "Save failed", str(err))
            return
        self._current_path = path
        self._refresh_title()
        n_blocks = len(payload["blocks"])
        n_wires = len(payload["wires"])
        self.statusBar().showMessage(
            f"Saved {n_blocks} block(s) and {n_wires} wire(s) → {path}"
        )

    def _open_schematic(self) -> None:
        # If there's anything on the current scene, offer to save first.
        if self.scene.block_items() or self.scene._wires:
            res = QMessageBox.question(
                self, "Open schematic",
                "Opening a file will discard the current scene. Continue?",
                QMessageBox.Yes | QMessageBox.Cancel,
            )
            if res != QMessageBox.Yes:
                return

        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open schematic", str(Path.cwd()), self.FILE_FILTER
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as err:
            QMessageBox.critical(self, "Open failed", f"Could not read file:\n{err}")
            return

        try:
            warnings = self.scene.load_from_dict(payload, self.library)
        except ValueError as err:
            QMessageBox.critical(self, "Open failed", f"Invalid schematic: {err}")
            return

        self._current_path = path
        self._refresh_title()
        n_blocks = len(self.scene.block_items())
        n_wires = len(self.scene._wires)
        msg = f"Loaded {n_blocks} block(s) and {n_wires} wire(s) from {path.name}"
        self.statusBar().showMessage(msg)

        if warnings:
            QMessageBox.warning(
                self, "Loaded with warnings",
                "Schematic loaded, but with the following issues:\n\n  • "
                + "\n  • ".join(warnings),
            )