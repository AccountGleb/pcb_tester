"""Test runner — stub.

This module is intentionally minimal right now. It's the entry point for
the "test schemas on real hardware" feature that will be added later.

The design agreed so far:

    * The main window hands `tester` a plain-dict description of the
      current schematic (see scene.SchematicScene.to_dict) plus the
      matching block templates (library dicts), nothing more.
    * The tester returns a plain-dict results report (pin-by-pin
      expected vs measured values, pass/fail, timestamps, etc).
    * The tester does not import from `editor` or `scene`. It only knows
      about data shapes.

The class below is a placeholder. The next work item is to decide the
exact input/output JSON shapes and implement a runner that talks to the
actual hardware.
"""
from typing import Any


class Tester:
    """Placeholder — fill in when wiring up hardware communication."""

    def __init__(self) -> None:
        pass

    def run(self, schematic: dict, templates: list[dict]) -> dict:
        """Run the test plan over `schematic` and return a results dict.

        Args:
            schematic: output of scene.SchematicScene.to_dict() — blocks,
                their positions, wires, and pin references. Pure data; no
                Qt objects.
            templates: list of block-template dicts (each is what
                BlockTemplate.save() writes). Needed so the tester knows
                the pins' signal types, directions, and expected values
                without pulling in the editor module.

        Returns:
            A dict with the test outcome. Exact shape is TBD.
        """
        raise NotImplementedError("Tester.run not implemented yet")