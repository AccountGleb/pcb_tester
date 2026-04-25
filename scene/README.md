# Block editor

A self-contained sub-system for designing one block at a time. "Block" here
means the schematic symbol of a component: a body rectangle with pins
arranged on its sides, plus optional internal wires showing which output
pin drives which input pin.

## Public API

Only what `editor/__init__.py` re-exports is part of the contract.
Everything else in this directory can change without breaking callers.

```python
from editor import (
    BlockEditorDialog,   # the UI window — create or edit one template
    BlockLibrary,        # scans a folder of <name>.json files
    BlockTemplate,       # one block design (shape + pins + internal wires)
    BlockShape,          # rectangle primitive: kind, width, height
    PinDef,              # one pin on a block
    PinDirection,        # INPUT / OUTPUT enum
    SignalType,          # NODE / GND / V+ / V- / NC enum
    InternalWire,        # an output-to-input connection inside the block
)
```

Typical flow from a caller (e.g. the main schematic scene):

```python
library = BlockLibrary()                                   # scans ./blocks/
dlg = BlockEditorDialog(library, template=None)            # new block
if dlg.exec_() == QDialog.Accepted:
    tpl: BlockTemplate = dlg.accepted_template()
    # tpl was saved to disk inside the dialog's OK handler;
    # library.list_templates() now includes it.
```

To **edit** an existing template, pass it in:

```python
dlg = BlockEditorDialog(library, template=existing_template)
```

## On-disk format

One file per template, `blocks/<n>.json`:

```json
{
    "name": "chip_dip16",
    "type": null,
    "shape": { "kind": "rect", "width": 200, "height": 140 },
    "pins": [
        { "number": 1, "x": -100, "y": -50, "signal": "GND",
          "direction": "input", "side": "left" },
        ...
    ],
    "internal_wires": [
        { "source": 2, "target": 5 }
    ]
}
```

Coordinates are in block-local space; origin (0, 0) is the block's centre.

Old files without `shape` or `side` fields are migrated transparently on
load (shape defaults to 120×80; `side` is inferred from pin coordinates).

## Editor modes

The dialog has three modes, selected via radio buttons at the top:

1. **Select / Resize** — drag the 8 handles to grow or shrink the block.
   Handles snap to the pin-pitch grid. Pins already placed along the
   perpendicular sides move with the wall; pins along the parallel sides
   stay where they are and constrain how small that dimension can get.

2. **Add pins** — a ghost pin follows the cursor. Green when the slot is
   valid, red when it's outside the capture ring or already taken. Click
   to place a pin with the currently-selected signal type and direction.
   Pins snap to the nearest side and to a fixed pitch along that side.

3. **Connect pins** — click one pin then another to create an internal
   wire. Must go output → input. Each input pin accepts at most one
   incoming wire; outputs can fan out to many.

## Canvas

The editor's canvas is fixed-scale (no pan); wheel zooms. The reasoning:
you're designing a symbol, not navigating a map. Fixed extents and a
visible origin cross keep everything centred on (0, 0) so the rest of
the app can treat the block's origin as the middle of its body.

## Key files

- `library.py` — dataclasses + library on disk. **No Qt imports here.**
  The data model is reusable outside PyQt.
- `dialog.py` — all Qt UI. The only place that touches `QDialog`,
  `QGraphicsScene`, etc.
- `pin_arrow.py` — path-builder for the arrow next to each pin. Reused
  by the main scene so the block renders identically in both places.
- `config.py` — editor-only constants (canvas size, grid spacing,
  resize-handle size, preview colours). Not shared.

## Adding features

Within the scope of "still a block editor" — text labels on pins, SVG
import, rounded corners, a second primitive shape, ports for signal
buses — work inside this package. Try to keep the new feature
representable in the JSON so `BlockTemplate.save()` keeps working and
old blocks still load.

When the new thing adds a new exported name (say `TextLabel`), add it
to `editor/__init__.py`'s `__all__`. That's the signal to callers that
they can depend on it.