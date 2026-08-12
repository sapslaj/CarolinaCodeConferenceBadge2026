# DVD Bounce

Classic bouncing-DVD-logo screensaver on the badge, complete with color change on every wall hit. A NeoPixel LED chase runs in parallel with its own hue cycle so the strip feels like part of the animation.

## What you should see

- The word `DVD` bounces around the 128×160 display, changing to a new random-looking color each time it hits an edge.
- The 5 NeoPixels sweep back and forth with a fading trail, hue-shifting in step with the on-screen logo.

## Controls

None — it just runs.

## Code design

- **Independent bounce state** - for the on-screen logo (`dvd_x/y`, `dvd_dx/dy`) and the LED head (`px_pos`, `px_dir`). Both advance every loop tick; they only share the global `hue` variable.
- **Bounding box from the label itself** — `dvd.bounding_box` gives the current rendered width/height, so the bounce limits (`MAX_X`, `MAX_Y`) stay correct even if you change the text or scale.
- **HSV → RGB helper** produces smooth, saturated color transitions across the whole spectrum without a lookup table.
- **Wall hit = hue jump** — the DVD logo's color advances continuously as `hue` drifts, then gets a `+0.23` "kick" on every wall bounce. This mimics the original screensaver's abrupt palette changes without needing a discrete palette.
- **LED tail rendering** — each pixel's brightness is `1.0 − distance × 0.6`, so the head is bright and the two adjacent pixels form a soft fade. A small hue offset per pixel (`+ dist × 0.06`) gives the trail a subtle gradient.
- **No throttling** — the loop just calls `display.refresh()` every frame; `auto_refresh=False` keeps things predictable.
