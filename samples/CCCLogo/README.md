# CCC Logo

Conference splash animation. The Carolina Code Conference logo fades in on the display while the NeoPixels bounce back and forth, hue-cycling through the spectrum. Loops forever — meant to be eye-catching on the demo table.

## What you should see

- The badge display starts dark. Over 1.5 s the backlight PWM ramps from 0 to full, revealing the CCC logo BMP centred vertically on the screen.
- After holding at full brightness for 0.5 s, the backlight fades back out over another 1.5 s and the cycle repeats.
- The 5 NeoPixels run a colour-bouncing "head + fading tail" animation the whole time. The head advances back and forth across the strip at ~5 pixels per second while the base hue rotates through the full spectrum every ~6.7 s.

## Controls

None — it just runs. Reset the board to restart the animation from the fade-in.

## Code design

- **BMP loaded once at startup** — `adafruit_imageload` reads `/img/CarolinaCodeConference.bmp` (128×128 8-bit indexed) and shares a `TileGrid` with a full-screen black background so the empty top/bottom bands are opaque rather than showing garbage from previous frames.
- **PWM backlight instead of a digital pin** — GPIO5 is opened with `pwmio.PWMOut` at 1 kHz so we can vary duty cycle between 0 and 65535 for smooth fades. A digital on/off would give an instant flash instead of the ramp.
- **Three-state fade machine** — `FADE_IN → HOLD_BRIGHT → FADE_OUT → …` driven by `time.monotonic()` deltas rather than `time.sleep()`, so the LED animation keeps running smoothly during every phase of the backlight cycle.
- **`display.refresh()` is called once at startup and never again** — the image is static, so there's no reason to burn cycles redrawing. All the visible motion is in the backlight PWM and the LED strip.
- **HSV → RGB helper** produces saturated hue transitions across the whole spectrum without a lookup table.
- **LED bounce with soft tail** — each pixel's brightness is `max(0, 1 − distance × 0.6)`, so the head is bright and the neighbouring pixels form a fade. A single moving float position (`px`) plus a direction sign is enough for the whole animation — no per-pixel state.
- **Font chip CS held high** so it doesn't fight the LCD on the shared SPI bus (per `AGENTS.md`).
