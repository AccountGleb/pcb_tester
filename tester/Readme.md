# Tester — stub

This package will host the logic that actually **runs** a test plan
against real hardware. Right now it's a placeholder.

## What it will do

Given a designed schematic, the tester should:

1. Read, for each pin, the expected value (from the block template —
   this is metadata the editor will eventually let the user set).
2. Exercise the board (drive outputs, measure inputs) via whatever
   physical interface is in use.
3. Compare measured vs expected values and compile a pass/fail report.

## What the tester DOES NOT depend on

- It does not import from `editor/` or `scene/`.
- It receives the schematic as a **plain dict** (what
  `SchematicScene.to_dict()` produces) and the block templates as a
  **list of plain dicts** (what `BlockTemplate.save()` writes).
- It returns a **plain dict** with results.

That decoupling is the whole point: the tester can be developed,
mocked, and unit-tested without a live Qt app, and the orchestrator
is the only place that knows how to pass data between packages.

## Expected input shape

```python
tester.run(schematic_dict, templates_list)
```

`schematic_dict` looks like what `SchematicScene.to_dict()` produces:

```json
{
    "version": 1,
    "blocks": [ {"template": "...", "instance_name": "...", "x": …, "y": …} ],
    "wires":  [ {...} ]
}
```

`templates_list` is a list where each item is a block template in the
on-disk JSON format (same as `blocks/<n>.json`):

```json
{
    "name": "...",
    "shape": {...},
    "pins":  [ {"number": 1, "x": …, "y": …, "signal": "...",
                "direction": "...", "side": "..."} ],
    "internal_wires": [...]
}
```

## Expected output shape (TBD)

To be defined when the hardware interface is picked. A reasonable first
pass:

```json
{
    "summary": { "passed": 12, "failed": 1, "skipped": 3 },
    "pins": [
        { "block": "U1", "pin": 2, "expected": 3.3, "measured": 3.28,
          "status": "pass", "timestamp": "..." },
        ...
    ]
}
```

The main window renders this back onto the schematic (colour pins by
pass/fail, show numeric overlays).

## Adding features

Work lives entirely inside this package. Everything the tester needs
from the rest of the program should arrive as a dict on its `run()`
call. If you find yourself wanting to `import scene` — stop and
extract whatever you need into the data contract instead.