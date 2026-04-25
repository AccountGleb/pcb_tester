"""Colour themes for the schematic editor.

A single Theme is a flat bag of QColors. Scene, BlockItem, PinItem and
WireItem each read from the current theme and re-apply when it changes.
"""
from dataclasses import dataclass

from PyQt5.QtGui import QColor

from editor.library import SignalType


@dataclass(frozen=True)
class Theme:
    name: str
    # background / grid
    bg: QColor
    grid_minor: QColor
    grid_major: QColor
    # block body
    block_fill: QColor
    block_stroke: QColor
    # pin fills per signal type
    pin_fill_node: QColor
    pin_fill_gnd: QColor
    pin_fill_vplus: QColor
    pin_fill_vminus: QColor
    pin_fill_nc: QColor
    pin_fill_occupied: QColor
    pin_stroke: QColor
    pin_label: QColor
    # block text
    name_label: QColor
    # wires
    wire: QColor
    wire_preview: QColor
    internal_wire: QColor

    # ------------------------------------------------------------------
    def pin_fill_for(self, signal: SignalType) -> QColor:
        return {
            SignalType.NODE:   self.pin_fill_node,
            SignalType.GND:    self.pin_fill_gnd,
            SignalType.VPLUS:  self.pin_fill_vplus,
            SignalType.VMINUS: self.pin_fill_vminus,
            SignalType.NC:     self.pin_fill_nc,
        }[signal]


DARK = Theme(
    name="dark",
    bg=QColor(38, 40, 46),
    grid_minor=QColor(56, 58, 66),
    grid_major=QColor(80, 84, 96),
    block_fill=QColor(70, 82, 104),
    block_stroke=QColor(180, 190, 210),
    pin_fill_node=QColor(250, 200,  90),
    pin_fill_gnd=QColor( 40,  40,  46),
    pin_fill_vplus=QColor(230,  90,  80),
    pin_fill_vminus=QColor( 90, 150, 240),
    pin_fill_nc=QColor(130, 130, 140),
    pin_fill_occupied=QColor(230, 120, 110),
    pin_stroke=QColor(230, 230, 235),
    pin_label=QColor(235, 235, 245),
    name_label=QColor(235, 235, 245),
    wire=QColor(120, 210, 140),
    wire_preview=QColor(120, 210, 140, 170),
    internal_wire=QColor(150, 220, 170, 160),
)


LIGHT = Theme(
    name="light",
    bg=QColor(248, 249, 251),
    grid_minor=QColor(225, 228, 235),
    grid_major=QColor(195, 200, 215),
    block_fill=QColor(225, 232, 245),
    block_stroke=QColor( 55,  65,  85),
    pin_fill_node=QColor(235, 170,  40),
    pin_fill_gnd=QColor( 30,  30,  35),
    pin_fill_vplus=QColor(215,  65,  60),
    pin_fill_vminus=QColor( 40, 100, 210),
    pin_fill_nc=QColor(160, 165, 175),
    pin_fill_occupied=QColor(200,  70,  55),
    pin_stroke=QColor( 40,  44,  54),
    pin_label=QColor( 40,  44,  54),
    name_label=QColor( 30,  33,  42),
    wire=QColor( 40, 130,  55),
    wire_preview=QColor( 40, 130,  55, 160),
    internal_wire=QColor( 70, 160,  90, 180),
)