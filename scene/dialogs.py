"""Dialogs used by the add-block workflow on the main scene.

    BlockSelectionDialog      — pick a template, start/edit one from the library
    ask_unique_instance_name  — prompt for a unique name for a placed block

The "create a new template" action delegates to BlockEditorDialog (see
block_editor.py), which is the authoritative UI for block design now that
SVG-based authoring is gone.
"""
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from editor import BlockEditorDialog, BlockLibrary, BlockTemplate


class BlockSelectionDialog(QDialog):
    """Pick an existing block template, create a new one, or edit one."""

    def __init__(self, library: BlockLibrary, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select block")
        self.resize(480, 460)
        self._library = library
        self._selected: Optional[BlockTemplate] = None

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Available blocks:"))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _i: self._accept())
        root.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        self._btn_new = QPushButton("+ New block…")
        self._btn_new.clicked.connect(self._on_new)
        buttons.addWidget(self._btn_new)
        self._btn_edit = QPushButton("Edit…")
        self._btn_edit.clicked.connect(self._on_edit)
        buttons.addWidget(self._btn_edit)
        self._btn_delete = QPushButton("Delete")
        self._btn_delete.clicked.connect(self._on_delete)
        buttons.addWidget(self._btn_delete)
        buttons.addStretch(1)
        self._btn_ok = QPushButton("OK")
        self._btn_ok.setDefault(True)
        self._btn_ok.clicked.connect(self._accept)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self._btn_ok)
        buttons.addWidget(self._btn_cancel)
        root.addLayout(buttons)

        self._populate()

    # ------------------------------------------------------------------
    def _populate(self, select_name: Optional[str] = None) -> None:
        self._list.clear()
        for tpl in self._library.list_templates():
            item = QListWidgetItem(
                f"{tpl.name}   "
                f"({len(tpl.pins)} pins, {len(tpl.internal_wires)} internal wires)"
            )
            item.setData(Qt.UserRole, tpl)
            self._list.addItem(item)
            if select_name and tpl.name == select_name:
                self._list.setCurrentItem(item)

        if self._list.count() == 0:
            placeholder = QListWidgetItem("(library is empty — use '+ New block…')")
            placeholder.setFlags(Qt.NoItemFlags)
            self._list.addItem(placeholder)

    # ------------------------------------------------------------------
    def _current_template(self) -> Optional[BlockTemplate]:
        item = self._list.currentItem()
        if item is None or not (item.flags() & Qt.ItemIsSelectable):
            return None
        return item.data(Qt.UserRole)

    # ------------------------------------------------------------------
    def _on_new(self) -> None:
        dlg = BlockEditorDialog(self._library, template=None, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            tpl = dlg.accepted_template()
            self._populate(select_name=tpl.name if tpl else None)

    def _on_edit(self) -> None:
        tpl = self._current_template()
        if tpl is None:
            QMessageBox.information(self, "No selection", "Select a block to edit.")
            return
        dlg = BlockEditorDialog(self._library, template=tpl, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            new_tpl = dlg.accepted_template()
            self._populate(select_name=new_tpl.name if new_tpl else tpl.name)

    def _on_delete(self) -> None:
        tpl = self._current_template()
        if tpl is None:
            QMessageBox.information(self, "No selection", "Select a block to delete.")
            return
        res = QMessageBox.question(
            self, "Delete block",
            f'Delete block "{tpl.name}" from the library? This removes its JSON file.'
        )
        if res != QMessageBox.Yes:
            return
        try:
            tpl.config_path.unlink(missing_ok=True)
        except OSError as err:
            QMessageBox.critical(self, "Delete failed", str(err))
            return
        self._populate()

    # ------------------------------------------------------------------
    def _accept(self) -> None:
        tpl = self._current_template()
        if tpl is None:
            QMessageBox.information(
                self, "No selection", "Select a block from the list first."
            )
            return
        self._selected = tpl
        self.accept()

    # ------------------------------------------------------------------
    def selected_template(self) -> Optional[BlockTemplate]:
        return self._selected


# ----------------------------------------------------------------------
# Instance-name prompt
# ----------------------------------------------------------------------
def ask_unique_instance_name(
    parent: QWidget,
    used_names: set[str],
    suggestion: str,
) -> Optional[str]:
    """Prompt the user until they give a non-empty, unique name (or cancel)."""
    default = suggestion
    while True:
        name, ok = QInputDialog.getText(
            parent,
            "Block name",
            "Enter a unique name for this block:",
            text=default,
        )
        if not ok:
            return None
        name = name.strip()
        if not name:
            QMessageBox.warning(parent, "Invalid name", "Name cannot be empty.")
            default = suggestion
            continue
        if name in used_names:
            QMessageBox.warning(
                parent, "Name taken",
                f'"{name}" is already used on the scene. Pick another.',
            )
            default = name
            continue
        return name