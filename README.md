# PCB Tester — Schematic Editor + (future) Test Runner

A PyQt5 desktop tool for building hardware test plans. The workflow is:

1. **Design blocks** — draw rectangles with pins that represent ICs on your
   board. Each pin has a signal type (`node` / `GND` / `V+` / `V-` / `NC`) and
   a direction (`input` / `output`).
2. **Place blocks on a schematic** — compose a full circuit by placing block
   instances on a scene and connecting their pins with orthogonal wires.
3. **Run tests** — (not yet) feed the schematic to the test runner, let it
   exercise the real hardware, read the results.

## Code layout

```
pcb_tester/
├── main.py                  entry point — just creates QApplication + MainWindow
├── main_window.py           MainWindow — orchestrates everything
├── shared.py                constants used by multiple packages (pin size,
│                            wire stub length, arrow geometry)
├── theme.py                 colour themes (DARK / LIGHT) shared too
│
├── editor/                  Package #1 — design one block at a time
│   ├── dialog.py            the BlockEditorDialog window
│   ├── library.py           BlockTemplate + BlockLibrary (on-disk JSON)
│   ├── pin_arrow.py         helper that draws the arrow next to each pin
│   ├── config.py            editor-only UI constants
│   └── __init__.py          public API (what other packages may import)
│
├── scene/                   Package #2 — the main schematic
│   ├── scene.py             SchematicScene (QGraphicsScene subclass)
│   ├── view.py              SchematicView (QGraphicsView with zoom/pan)
│   ├── block_item.py        BlockItem + PinItem — a placed block
│   ├── wire.py              WireItem + orthogonal routing
│   ├── dialogs.py           BlockSelectionDialog, ask_unique_instance_name
│   └── __init__.py          public API
│
└── tester/                  Package #3 — STUB, run tests on real hardware
    ├── tester.py            placeholder class
    └── __init__.py
```

## Dependency rules

These four boundaries are what keep the project understandable, especially
as it grows. They're enforced by convention (no import-lint yet); if you
break them, later refactoring gets painful.

```
    main_window  ──► editor
                 ──► scene
                 ──► tester

    scene        ──► editor        (only via editor/__init__.py)

    editor   ──┐
    scene    ──┼──► shared, theme  (plain constants, no logic)
    tester   ──┘
```

Explicitly NOT allowed:

- `editor` imports from `scene` or `tester`
- `scene` imports from `tester`
- `tester` imports from `editor` or `scene`
- anyone imports from **internal** files of another package (e.g.
  `from editor.dialog import _EditorScene` — use the `__init__.py`
  exports instead)

`shared.py` and `theme.py` hold values, not behaviour, so depending on
them is considered cheap and doesn't count as coupling.

## Data flow

The important data shapes to know:

**Block template** (`editor/library.py::BlockTemplate.save/load`):
one JSON per block, in the library folder (`blocks/<name>.json`).
Independent of any particular schematic.

**Schematic** (`scene/scene.py::SchematicScene.to_dict / load_from_dict`):
one JSON per board layout. References block templates by name — they
have to exist in the library for a schematic to load.

**Test plan / results** (tester — TBD): the runner will take a
schematic dict + a list of template dicts and produce a results dict.
The data contract is documented in `tester/README.md`.

## Running

```
pip install PyQt5
python main.py
```

## Adding features

- **A feature inside block design (SVG import, text labels, new pin
  shapes, …)** — work only inside `editor/`. Describe the new public
  API in `editor/README.md`. The rest of the codebase shouldn't need
  to change.
- **A feature on the main schematic (labels on wires, bus groups, …)** —
  work only inside `scene/`. Use the editor through its public API;
  don't peek inside.
- **A feature touching both** — likely means adding a method on a data
  class in `editor/library.py` (so editor produces it) + consuming it
  in `scene/`. Keep the editor ignorant of where its output is used.