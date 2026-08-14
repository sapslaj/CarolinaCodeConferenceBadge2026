# DVD Bounce

Classic bouncing-DVD-logo screensaver on the badge, complete with color change on every wall hit. A NeoPixel LED chase runs in parallel with its own hue cycle so the strip feels like part of the animation.

## What you should see

- The real `DVD VIDEO` logo (44×26) bounces around the 128×160 display, changing to a new random-looking color each time it hits an edge.
- The 5 NeoPixels sweep back and forth with a fading trail, hue-shifting in step with the on-screen logo.

## Controls

None — it just runs.

## Assets

`dvd_logo.bmp` sits next to `code.py` and is loaded from `/samples/DVDBounce/dvd_logo.bmp`, so the whole sample folder can just be copied to `CIRCUITPY` as-is.

`dvd_logo.png` is the full-resolution source (247×148, black on white). The BMP is derived from it: cropped, scaled to 44 px wide, and quantized to an 8-level **coverage ramp** — palette index 0 = no ink, index 7 = solid, 1–6 = the antialiased edges. The colors stored in the file are placeholders; `code.py` overwrites the whole ramp every frame.

Regenerate it after editing the PNG with any tool that produces an **8-bit indexed, uncompressed** BMP whose indices are ordered by ink coverage. Keeping the palette trimmed to exactly 8 entries is what lets `code.py` size its ramp from `len(palette)`; a 256-entry palette still renders correctly but makes the recolor loop do 248 pointless writes per frame.

## Code design

- **Independent bounce state** - for the on-screen logo (`dvd_x/y`, `dvd_dx/dy`) and the LED head (`px_pos`, `px_dir`). Both advance every loop tick; they only share the global `hue` variable.
- **Bounds from the bitmap** — the limits come from `logo.width`/`logo.height`, so swapping in a different BMP needs no other edits. A `TileGrid`'s `x`/`y` *is* its top-left corner, which makes the math plain subtraction. (Worth knowing if you go back to a text `Label`: that path is not equivalent. `Label.bounding_box` is in **unscaled** font units, so it must be multiplied by `scale`, and its `y_off` is negative because with the default `base_alignment=False` a label's `y` is the *vertical center* of the text, not its top. Ignoring either one clips the logo off the top and right edges while leaving a phantom gap at the bottom.)
- **Recolor via the palette, not the pixels** — the bitmap is never rewritten. Each frame only the 7 non-transparent palette entries are updated, each set to the current hue scaled by that index's ink coverage. That keeps the antialiased edges in the logo's color instead of leaving a grey fringe, and it costs 7 assignments per frame rather than touching 1,144 pixels.
- **Index 0 is transparent** — `make_transparent(0)` lets the near-black background `TileGrid` show through, so the logo has no white box around it.
- **HSV → RGB helper** produces smooth, saturated color transitions across the whole spectrum without a lookup table.
- **Wall hit = hue jump** — the DVD logo's color advances continuously as `hue` drifts, then gets a `+0.23` "kick" on every wall bounce. This mimics the original screensaver's abrupt palette changes without needing a discrete palette.
- **LED tail rendering** — each pixel's brightness is `1.0 − distance × 0.6`, so the head is bright and the two adjacent pixels form a soft fade. A small hue offset per pixel (`+ dist × 0.06`) gives the trail a subtle gradient.
- **No throttling** — the loop just calls `display.refresh()` every frame; `auto_refresh=False` keeps things predictable.
