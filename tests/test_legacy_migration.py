"""Integration tests for the legacy-format migration in BlockTemplate.load().

The bug being guarded against: pre-shape JSON files store pin coordinates
in editor scene space, not block-local space. Loading them on a different
machine made pins drift outside the block body (the "розсипались" bug).

These tests run without Qt — `editor.library` has no Qt imports, by design.
"""
import json
import tempfile
import unittest
from pathlib import Path

from editor.library import (
    BlockLibrary,
    BlockTemplate,
    PinDirection,
    SignalType,
)


# Real coordinates copied verbatim from the broken
# blocks/genetic-data-svgrepo-com.json on origin/main. Spread ~500x525,
# all-positive, no `shape`, no `side`.
LEGACY_BLOCK = {
    "name": "genetic-data-svgrepo-com",
    "type": None,
    "pins": [
        {"number": 1, "x": 390.18, "y": 372.12, "signal": "node", "direction": "input"},
        {"number": 2, "x": 407.74, "y": 430.73, "signal": "node", "direction": "input"},
        {"number": 3, "x": 214.30, "y": 205.59, "signal": "node", "direction": "input"},
        {"number": 4, "x": 682.98, "y": 318.84, "signal": "node", "direction": "input"},
        {"number": 5, "x": 331.17, "y": 654.82, "signal": "node", "direction": "input"},
        {"number": 6, "x": 357.52, "y": 152.62, "signal": "node", "direction": "output"},
        {"number": 7, "x": 183.99, "y": 524.78, "signal": "node", "direction": "output"},
        {"number": 8, "x": 597.95, "y": 541.50, "signal": "node", "direction": "output"},
        {"number": 9, "x": 643.95, "y": 129.63, "signal": "node", "direction": "output"},
    ],
    "internal_wires": [
        {"source": 6, "target": 3},
        {"source": 7, "target": 1},
        {"source": 7, "target": 5},
        {"source": 9, "target": 4},
    ],
}

# A sample modern-format block. Has `shape`, `side`, and pins already in
# block-local coordinates (origin at the centre).
MODERN_BLOCK = {
    "name": "chip_dip8",
    "type": None,
    "shape": {"kind": "rect", "width": 200.0, "height": 140.0},
    "pins": [
        {"number": 1, "x": -100.0, "y": -50.0, "signal": "GND",
         "direction": "input", "side": "left"},
        {"number": 2, "x":  100.0, "y": -50.0, "signal": "node",
         "direction": "output", "side": "right"},
        {"number": 3, "x":  100.0, "y":  50.0, "signal": "V+",
         "direction": "input", "side": "right"},
    ],
    "internal_wires": [],
}


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, name: str, payload: dict) -> Path:
        path = self.dir / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    # --- legacy ---------------------------------------------------------

    def test_legacy_pins_recentre_on_origin(self):
        """bbox of migrated pins must be symmetric around (0, 0)."""
        path = self._write("legacy", LEGACY_BLOCK)
        tpl = BlockTemplate.load(path)

        xs = [p.x for p in tpl.pins]
        ys = [p.y for p in tpl.pins]
        # bbox centre should land at origin within float tolerance
        self.assertAlmostEqual((min(xs) + max(xs)) / 2.0, 0.0, places=6)
        self.assertAlmostEqual((min(ys) + max(ys)) / 2.0, 0.0, places=6)

    def test_legacy_shape_encloses_all_pins(self):
        """Synthesised shape must be at least as large as the pin spread."""
        path = self._write("legacy", LEGACY_BLOCK)
        tpl = BlockTemplate.load(path)

        xs = [p.x for p in tpl.pins]
        ys = [p.y for p in tpl.pins]
        spread_w = max(xs) - min(xs)
        spread_h = max(ys) - min(ys)
        # padding only adds slack — shape never shrinks below the spread
        self.assertGreaterEqual(tpl.shape.width, spread_w)
        self.assertGreaterEqual(tpl.shape.height, spread_h)
        self.assertEqual(tpl.shape.kind, "rect")

    def test_legacy_pin_relative_geometry_preserved(self):
        """Pairwise pin offsets are unchanged by the recentre."""
        path = self._write("legacy", LEGACY_BLOCK)
        tpl = BlockTemplate.load(path)

        # pick any two pins; their delta must match the original delta
        original_by_num = {p["number"]: (p["x"], p["y"]) for p in LEGACY_BLOCK["pins"]}
        loaded_by_num = {p.number: (p.x, p.y) for p in tpl.pins}

        for a, b in [(1, 2), (3, 9), (5, 7)]:
            ox = original_by_num[a][0] - original_by_num[b][0]
            oy = original_by_num[a][1] - original_by_num[b][1]
            lx = loaded_by_num[a][0] - loaded_by_num[b][0]
            ly = loaded_by_num[a][1] - loaded_by_num[b][1]
            self.assertAlmostEqual(ox, lx, places=6)
            self.assertAlmostEqual(oy, ly, places=6)

    def test_legacy_sides_are_valid(self):
        """Every migrated pin gets a valid `side`, inferred from new coords."""
        path = self._write("legacy", LEGACY_BLOCK)
        tpl = BlockTemplate.load(path)
        for pin in tpl.pins:
            self.assertIn(pin.side, ("left", "right", "top", "bottom"),
                          msg=f"pin {pin.number} got side={pin.side!r}")

    def test_legacy_signal_and_direction_unchanged(self):
        path = self._write("legacy", LEGACY_BLOCK)
        tpl = BlockTemplate.load(path)
        by_num = {p.number: p for p in tpl.pins}
        self.assertEqual(by_num[6].direction, PinDirection.OUTPUT)
        self.assertEqual(by_num[1].direction, PinDirection.INPUT)
        self.assertEqual(by_num[1].signal, SignalType.NODE)

    def test_legacy_internal_wires_unchanged(self):
        path = self._write("legacy", LEGACY_BLOCK)
        tpl = BlockTemplate.load(path)
        wires = sorted((w.source, w.target) for w in tpl.internal_wires)
        self.assertEqual(wires, [(6, 3), (7, 1), (7, 5), (9, 4)])

    def test_legacy_load_is_deterministic_across_calls(self):
        """The migration is pure — loading twice gives identical results.
        This is the property that makes blocks portable across machines."""
        path = self._write("legacy", LEGACY_BLOCK)
        a = BlockTemplate.load(path)
        b = BlockTemplate.load(path)
        for pa, pb in zip(a.pins, b.pins):
            self.assertEqual((pa.number, pa.x, pa.y, pa.side),
                             (pb.number, pb.x, pb.y, pb.side))
        self.assertEqual((a.shape.width, a.shape.height),
                         (b.shape.width, b.shape.height))

    def test_legacy_load_does_not_mutate_disk(self):
        """load() must not silently rewrite the file."""
        path = self._write("legacy", LEGACY_BLOCK)
        before = path.read_bytes()
        BlockTemplate.load(path)
        after = path.read_bytes()
        self.assertEqual(before, after)

    # --- modern ---------------------------------------------------------

    def test_modern_block_passes_through_unchanged(self):
        """A file with `shape` is NOT touched by the legacy path."""
        path = self._write("modern", MODERN_BLOCK)
        tpl = BlockTemplate.load(path)

        self.assertEqual(tpl.shape.width, 200.0)
        self.assertEqual(tpl.shape.height, 140.0)
        # Coords must be exactly what's on disk — no implicit recentre.
        coords = sorted((p.number, p.x, p.y) for p in tpl.pins)
        self.assertEqual(coords, [
            (1, -100.0, -50.0),
            (2,  100.0, -50.0),
            (3,  100.0,  50.0),
        ])
        # Sides come straight from the file.
        sides = {p.number: p.side for p in tpl.pins}
        self.assertEqual(sides, {1: "left", 2: "right", 3: "right"})

    # --- round-trip migration via save() --------------------------------

    def test_save_after_legacy_load_writes_modern_format(self):
        """After load+save, the file is in the modern format and reload
        is a no-op (the actual fix path: legacy file gets healed once
        the user edits and saves it through the editor dialog)."""
        path = self._write("legacy", LEGACY_BLOCK)
        tpl = BlockTemplate.load(path)
        tpl.save()

        # save() writes to <directory>/<template.name>.json, which may
        # differ from the path we loaded from — that's by design.
        rewritten_path = self.dir / f"{tpl.name}.json"
        self.assertTrue(rewritten_path.exists())

        rewritten = json.loads(rewritten_path.read_text(encoding="utf-8"))
        self.assertIn("shape", rewritten)
        self.assertIn("side", rewritten["pins"][0])

        # And reloading the rewritten file produces identical geometry.
        reloaded = BlockTemplate.load(rewritten_path)
        for a, b in zip(tpl.pins, reloaded.pins):
            self.assertEqual((a.number, a.x, a.y, a.side),
                             (b.number, b.x, b.y, b.side))

    # --- BlockLibrary level --------------------------------------------

    def test_library_lists_migrated_template(self):
        """BlockLibrary.list_templates() returns the migrated template
        without raising on legacy files."""
        self._write("legacy", LEGACY_BLOCK)
        self._write("modern", MODERN_BLOCK)
        lib = BlockLibrary(directory=self.dir)
        names = sorted(t.name for t in lib.list_templates())
        self.assertEqual(names, ["chip_dip8", "genetic-data-svgrepo-com"])


if __name__ == "__main__":
    unittest.main()