# Anubis

A simple, hands-off slideshow. No buttons, no menus — plug it in and it loops forever:

1. **`img/anubis/pensive.bmp`** — shown full-screen with a gold loading bar filling in underneath it over **5 seconds**.
2. **`img/anubis/happy.bmp`** — shown full-screen (no bar) for **30 seconds**.
3. Back to step 1, forever.

## Requirements

Copy `pensive.bmp` and `happy.bmp` into an `img/anubis/` folder on the `CIRCUITPY` drive (alongside the existing `img/` folder at the top level) before running this sample — it loads them from `/img/anubis/pensive.bmp` and `/img/anubis/happy.bmp`. Both are expected to be 128×128, 8-bit indexed BMPs (same format `adafruit_imageload` already reads for the CCCLogo sample).

## Code design

- Both images are loaded **once** at startup into two separate `displayio.TileGrid`s stacked in the same `displayio.Group`. Only one is shown at a time via the `.hidden` attribute. `TileGrid.bitmap` and `.pixel_shader` are read-only after construction in CircuitPython, so swapping the image bitmap on a single TileGrid isn't possible — two pre-built grids toggled with `.hidden` is the supported way to do a "changing image."
- The loading bar is a small `displayio.Bitmap` redrawn each frame with `bitmaptools.fill_region(bitmap, x1, y1, x2, y2, value)`. That function takes **corner coordinates** (x2/y2 are exclusive), not a width/height pair — worth calling out since it's easy to get backwards.
- A plain two-state timer (`phase` / `phase_start`, compared against `time.monotonic()`) drives the loop. Nothing blocks longer than a display-refresh tick.
