# Nameplate

A personalizable conference nameplate. Puts your name on the display in big letters, animates the 5 NeoPixels with your choice of pattern and palette, and tints the on-screen text to match. Copy this sample's `code.py` over the top-level `code.py` to run it (or pick it from the Launcher menu).

## How to personalize

Edit these two lines at the top of `code.py`, save, and CircuitPython auto-reloads:

```python
FIRST_NAME = "GARY"
LAST_NAME  = "KILDALL"
```

Uppercase looks best. Long names automatically scale down so they still fit.

## Controls

| Switch | Action |
|--------|--------|
| SW1 (IO1) | Cycle LED **pattern** — SOLID / BREATHE / CHASE / SPARKLE / WAVE |
| SW2 (IO2) | Cycle color **palette** — RAINBOW / WHITE / RED / ORANGE / YELLOW / GREEN / CYAN / BLUE / PURPLE / PINK |
| SW3 (IO43) | LEDs off (SW1 or SW2 wakes them back up) |

## Code design

- **Two orthogonal knobs** - `PATTERNS` (motion) and `PALETTES` (color) are decoupled, so any of the 5 patterns can render in any of the 10 palettes. That's 50 combinations from ~40 lines of pattern code.
- **`palette_color(pal_idx, pixel_i, t)`** - returns the base RGB for a given pixel, per palette. RAINBOW is special-cased to derive the hue from `(pixel_i, t)`; every other palette returns a constant color.
- **Patterns modulate brightness, not hue** - each pattern (BREATHE, CHASE, SPARKLE, WAVE) computes a 0.0–1.0 brightness per pixel and scales the palette color by it. This is why any palette drops into any pattern cleanly.
- **Auto-scaling text** — `choose_scale()` picks the largest `label` scale (4 → 1) that keeps the name within the display width, so short names go huge and long names still fit.
- **Display text tinted with the palette** — every ~100 ms the loop calls `display_color(palette_idx, t)` and re-tints the first/last name labels. In RAINBOW mode this makes the on-screen name slowly drift through hues in sync with the LEDs.
- **Display refresh throttled to ~10 Hz** - LEDs refresh every loop iteration (~50 Hz). The display doesn't need to keep up with the LEDs, and refreshing it less saves noticeable CPU.
- **Edge-triggered buttons** — three `sw{N}_prev` variables plus `(not v) and prev` gives one event per press, no repeat.
