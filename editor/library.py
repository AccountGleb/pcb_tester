"""Block data model and on-disk library.

Each block is defined entirely by its JSON config — no separate image file.

JSON format (blocks/<name>.json):
    {
        "name": "chip_dip16",
        "type": null,
        "shape": {
            "kind": "rect",
            "width": 120.0,
            "height": 80.0
        },
        "pins": [
            {"number": 1, "x": -60.0, "y": -20.0,
             "signal": "GND",  "direction": "input"},
            {"number": 2, "x": -60.0, "y":   0.0,
             "signal": "node", "direction": "output"},
            ...
        ],
        "internal_wires": [
            {"source": 2, "target": 5},
            ...
        ]
    }

Pin coordinates are in block-local space with (0, 0) at the block's centre.
The block size is fixed at authoring time and does not change on the main
schematic, so absolute block-local coordinates are sufficient.

Backward compatibility:
  Old-format files referenced a .svg sibling and stored pin coordinates
  in the editor's scene space rather than block-local space. Those SVGs
  are now ignored — only the JSON is consulted. If an old JSON lacks a
  `shape`, the loader treats it as legacy: it computes the bbox of the
  pins, recentres them on (0, 0), and synthesises a `rect` shape large
  enough to enclose every pin (plus a small padding). This makes legacy
  blocks portable across machines/screens. Any sibling .svg is left on
  disk untouched so the user can clean them up manually.
"""
import enum
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ----------------------------------------------------------------------
# Pin classification
# ----------------------------------------------------------------------
class SignalType(str, enum.Enum):
    """What kind of net the pin sits on."""
    NODE   = "node"
    GND    = "GND"
    VPLUS  = "V+"
    VMINUS = "V-"
    NC     = "NC"


class PinDirection(str, enum.Enum):
    """For testing: is this pin driven by the DUT or driving into it?"""
    INPUT  = "input"
    OUTPUT = "output"


def _infer_side(x: float, y: float, w: float, h: float) -> str:
    """Closest-edge fallback used when loading legacy pins without a `side`."""
    dl = abs(x - (-w / 2))
    dr = abs(x -  (w / 2))
    dt = abs(y - (-h / 2))
    db = abs(y -  (h / 2))
    best = min(dl, dr, dt, db)
    if best == dl: return "left"
    if best == dr: return "right"
    if best == dt: return "top"
    return "bottom"


# Tunables for the legacy-format migration in BlockTemplate.load().
# Chosen to leave a small visual margin around the pins so they don't
# sit exactly on the body edge in legacy (SVG-imported) blocks where
# pins were placed freely inside the symbol, not pinned to a side.
_LEGACY_PADDING = 40.0
_MIN_LEGACY_WIDTH = 60.0
_MIN_LEGACY_HEIGHT = 40.0


# ----------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------
@dataclass
class PinDef:
    number: int
    x: float
    y: float
    signal: SignalType = SignalType.NODE
    direction: PinDirection = PinDirection.INPUT
    # Which side of the block the pin is anchored to. One of:
    # "left", "right", "top", "bottom". Filled in by the editor at
    # placement time and re-used when the block is resized. For legacy
    # JSON without this field, the loader infers it from coordinates.
    side: str = "left"


@dataclass
class InternalWire:
    """OUTPUT pin drives an INPUT pin inside the block."""
    source: int
    target: int


@dataclass
class BlockShape:
    """Primitive shape of the block body.

    Only 'rect' is supported for now. Other kinds (circle, polygon) can be
    added later by extending the renderer in block_item.py; the data model
    is designed to accept a discriminator field.
    """
    kind: str = "rect"
    width: float = 120.0
    height: float = 80.0

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "BlockShape":
        if not data:
            return cls()    # default 120x80 rect
        return cls(
            kind=str(data.get("kind", "rect")),
            width=float(data.get("width", 120.0)),
            height=float(data.get("height", 80.0)),
        )

    def to_dict(self) -> dict:
        return {"kind": self.kind, "width": self.width, "height": self.height}


@dataclass
class BlockTemplate:
    """A reusable block design loaded from disk."""
    name: str
    shape: BlockShape = field(default_factory=BlockShape)
    type: Optional[str] = None
    pins: list[PinDef] = field(default_factory=list)
    internal_wires: list[InternalWire] = field(default_factory=list)

    # The directory the template lives in (needed for save/rename). Not
    # serialised — populated by the library when loading.
    directory: Optional[Path] = None

    # ..................................................................
    @property
    def config_path(self) -> Path:
        if self.directory is None:
            raise ValueError("Template has no directory assigned.")
        return self.directory / f"{self.name}.json"

    # ..................................................................
    @classmethod
    def load(cls, json_path: Path) -> "BlockTemplate":
        json_path = Path(json_path)
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # name: prefer the one in JSON, fall back to filename stem
        name = data.get("name") or json_path.stem

        raw_pins = list(data.get("pins", []))

        # Legacy migration: old JSON files (pre-shape) stored pin
        # coordinates in the editor's scene space, not block-local space.
        # On a different screen those absolute coords end up far outside
        # the block's body — pins "scatter" across the schematic.
        # Detect this by the absence of `shape`, then recentre the pins
        # on (0, 0) and synthesise a shape that encloses them all.
        if "shape" not in data and raw_pins:
            xs = [float(p["x"]) for p in raw_pins]
            ys = [float(p["y"]) for p in raw_pins]
            offset_x = (min(xs) + max(xs)) / 2.0
            offset_y = (min(ys) + max(ys)) / 2.0
            spread_w = max(xs) - min(xs)
            spread_h = max(ys) - min(ys)
            shape = BlockShape(
                kind="rect",
                width=max(spread_w + _LEGACY_PADDING, _MIN_LEGACY_WIDTH),
                height=max(spread_h + _LEGACY_PADDING, _MIN_LEGACY_HEIGHT),
            )
        else:
            shape = BlockShape.from_dict(data.get("shape"))
            offset_x = offset_y = 0.0

        pins: list[PinDef] = []
        for p in raw_pins:
            x = float(p["x"]) - offset_x
            y = float(p["y"]) - offset_y
            # Infer side from coordinates if missing — legacy JSON files
            # didn't record it. Now that x/y are in block-local space the
            # nearest-edge heuristic actually makes sense.
            side = p.get("side")
            if side not in ("left", "right", "top", "bottom"):
                side = _infer_side(x, y, shape.width, shape.height)
            pins.append(PinDef(
                number=int(p["number"]),
                x=x,
                y=y,
                signal=SignalType(p.get("signal", SignalType.NODE.value)),
                direction=PinDirection(p.get("direction", PinDirection.INPUT.value)),
                side=side,
            ))

        internal = [
            InternalWire(source=int(w["source"]), target=int(w["target"]))
            for w in data.get("internal_wires", [])
        ]

        return cls(
            name=name,
            shape=shape,
            type=data.get("type"),
            pins=pins,
            internal_wires=internal,
            directory=json_path.parent,
        )

    def save(self) -> None:
        payload = {
            "name": self.name,
            "type": self.type,
            "shape": self.shape.to_dict(),
            "pins": [
                {
                    "number": p.number,
                    "x": p.x,
                    "y": p.y,
                    "signal": p.signal.value,
                    "direction": p.direction.value,
                    "side": p.side,
                }
                for p in self.pins
            ],
            "internal_wires": [
                {"source": w.source, "target": w.target}
                for w in self.internal_wires
            ],
        }
        with self.config_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)


# ----------------------------------------------------------------------
# Library
# ----------------------------------------------------------------------
# The library lives at <project_root>/blocks/. After the refactor that
# moved this file into editor/, parent.parent walks back up to the
# project root so existing blocks/ folders next to main.py keep working.
DEFAULT_BLOCKS_DIR = Path(__file__).resolve().parent.parent / "blocks"


class BlockLibrary:
    """Scans a folder for <name>.json block templates.

    Old-format .svg sibling files are ignored (but not deleted). If a JSON
    file lacks a `shape` field, the loader treats it as legacy: pin
    coordinates are recentred on (0, 0) and a `shape` is synthesised from
    the pin bbox. The migrated values stay in memory; on the next
    `BlockTemplate.save()` (e.g. after the user edits the block) the file
    is rewritten in the modern block-local format.
    """

    def __init__(self, directory: Path = DEFAULT_BLOCKS_DIR) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    # ..................................................................
    def list_templates(self) -> list[BlockTemplate]:
        templates: list[BlockTemplate] = []
        for cfg in sorted(self.directory.glob("*.json")):
            try:
                templates.append(BlockTemplate.load(cfg))
            except (json.JSONDecodeError, OSError, KeyError, ValueError) as err:
                print(f"[BlockLibrary] skipping {cfg.name}: {err}")
        return templates

    # ..................................................................
    def exists(self, name: str) -> bool:
        return (self.directory / f"{name}.json").exists()

    # ..................................................................
    def commit(
        self,
        name: str,
        shape: BlockShape,
        pins: list[PinDef],
        internal_wires: Optional[list[InternalWire]] = None,
        overwrite: bool = False,
    ) -> BlockTemplate:
        """Persist a template as <name>.json. Raises FileExistsError if the
        target exists and overwrite=False."""
        if not name or not name.strip():
            raise ValueError("Block name cannot be empty.")
        name = name.strip()

        target = self.directory / f"{name}.json"
        if target.exists() and not overwrite:
            raise FileExistsError(target)

        tpl = BlockTemplate(
            name=name,
            shape=shape,
            type=None,
            pins=list(pins),
            internal_wires=list(internal_wires or []),
            directory=self.directory,
        )
        tpl.save()
        return tpl