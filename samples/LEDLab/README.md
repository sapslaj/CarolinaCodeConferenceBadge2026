# LED Lab

A hands-on demo built around the 5-pixel WS2812 strip. Cycle through
patterns, palettes, and speeds with the three tactile buttons; the
display names the current mode and mirrors the strip in a live preview.

## Controls

| Button | Action |
|--------|--------|
| SW1 (IO1)  | Next **pattern** (16 options) |
| SW2 (IO2)  | Next **palette** (10 options) |
| SW3 (IO43) | Next **speed** (SLOW / NORM / FAST / TURBO) |

## Patterns

| Name     | What it does |
|----------|--------------|
| SOLID    | Whole strip in one palette color, slowly drifting |
| RAINBOW  | Palette sweep spread across the 5 pixels, scrolling |
| BREATHE  | Full-strip sinusoidal fade in and out |
| WAVE     | Sinusoidal brightness travelling down the strip |
| COMET    | Bright head with a squared-brightness tail |
| CYLON    | Ping-pong scanner (Battlestar-style eye) |
| CHASE    | Classic 1-in-3 marquee chase |
| PULSE    | Heartbeat — double beat then rest |
| STROBE   | Full-strip on/off, 2.5 Hz at NORM up to 10 Hz at TURBO |
| VU       | Level bar growing out from the centre pixel |
| FIRE     | 1D flame sim; heat propagates up, palette maps 0..1 → color |
| CONFETTI | Random pixel gets a fresh color; all decay |
| TWINKLE  | Each pixel breathes at its own random rate |
| PLASMA   | Sum of a few sines → smooth shifting color per pixel |
| WIPE     | Fill one pixel at a time, then reset with next color |
| GRADIENT | Static-looking palette gradient that gently drifts |

## Palettes

RAINBOW is the full HSV wheel; the rest are 3–6 stop lists that are
linearly interpolated end-to-end.

`RAINBOW · FIRE · OCEAN · FOREST · SUNSET · NEON · CANDY · MONO · PARTY · CBM`

(`CBM` = Circuit Board Medics — greens and gold that pick up the PCB solder-mask look.)

Every pattern respects the currently selected palette — even patterns
that "should" have a fixed look (like FIRE) still cycle through whichever
palette is active. Try FIRE-pattern + OCEAN-palette for a plasma-torch
look, or PLASMA + CANDY for a pastel oil-slick.

## Code design

- **Patterns are just functions** `fn(palette_idx, t, speed) -> [5 RGB tuples]`.
  Adding a new one is one function plus a line in the `PATTERNS` tuple.
- **Palettes are stop-lists** interpolated by `palette_at(idx, pos)` where
  `pos` wraps mod 1. The `"rainbow"` sentinel takes the full HSV wheel
  path instead. This means every pattern can drive every palette without
  special-casing.
- **State lives at module scope** for patterns that need it (`heat`
  buffer for FIRE, `confetti_buf`, `twinkle_phase` / `twinkle_rate`).
  Kept simple — no classes — because there are only ever three of them.
- **Debouncing is timer-based** (`DEBOUNCE = 0.15 s`) rather than
  `time.sleep()` after a press, so button handling never stalls the
  animation.
- **Display refresh is throttled** to ~12 Hz. The LED strip renders every
  loop iteration (~50 Hz) because the strip is the star; the display
  update is heavier and doesn't need to match.
- **`brightness=0.35`** — a safe compromise between eye comfort, battery
  drain on CR123A, and staying inside the 3.3 V rail's current budget.
- **Font chip CS held high** so it doesn't fight the LCD on the shared
  SPI bus (per `AGENTS.md`).

## Notes

- The display shows the current pattern name, position (`5 / 16`),
  palette and speed selection, and a row of 5 squares that mirror the
  actual strip in real time.
- `auto_refresh=False` on the display + explicit `display.refresh()`
  keeps the LED animation smooth; letting `displayio` refresh whenever
  it wants would introduce visible hitches in the strip.
- Long-running with no `supervisor.reload()` escape hatch — if you edit
  and break `code.py`, drop to REPL and fix it there.
