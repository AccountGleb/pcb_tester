# deepseek_branch – Feature branch for SVG blocks, test mode, and advanced testing UI

Created from `main` at commit 8828a35 (Apr 25, 2026).  
Goal: implement functional testing infrastructure and enhance block visuals (SVG) while preserving the existing architecture.

## Planned features (see full spec in original issue)

### Phase 0 – Complete basic editor enhancements
- ✅ Global zoom/pan (already present, no per-block scaling intended)
- [ ] SVG support for block bodies (transparent PNG/SVG with configurable pin positions)
- [ ] Unique pin number (in addition to name)
- [ ] `model` (type) attribute for blocks, default null

### Phase 1 – Test mode and test runner
- [ ] Separate Editor / Test mode (UI toggle)
- [ ] In-app terminal + autoscript runner
- [ ] Translator module: highlight failing wires/pins based on expected vs measured
- [ ] Test session save/load
- [ ] Expected values for pins in block templates or test plan
- [ ] Fields for measured values (volts / bits) in test mode
- [ ] Wire selection, labels, comments

### Phase 2 – Advanced (future)
- [ ] LEARef display on schematic
- [ ] Export functionality

## How to work with this branch
- Keep dependency rules as defined in original README (editor ↔ scene ↔ tester boundaries).
- New features in `tester/` must not import from `editor/` or `scene/`.
- Use public APIs only (`editor/__init__.py`, `scene/__init__.py`).

## Initial commit
- Added this file.
- Next: add SVG loading to BlockTemplate and BlockItem.