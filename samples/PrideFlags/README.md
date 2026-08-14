# Pride Flags

A rotating carousel of pride flags on the 128×160 LCD. Each flag is drawn
full-screen as horizontal stripes (the classic flag layout), held for a few
seconds, then the next one slides in. The 5 NeoPixels scroll the current
flag's stripe colors in step with the on-screen flag.

## What you should see

- The display fills top-to-bottom with the stripes of a pride flag; the
  flag's name sits in a dark bar across the bottom of the screen.
- Every ~4 seconds the next flag appears automatically.
- The 5 NeoPixels cycle through the current flag's stripe colors, scrolling
  along the strip.

## Flags included

| Flag | Stripes | Notes |
|------|---------|-------|
| Rainbow | 6 | Gilbert Baker 6-stripe |
| Trans | 5 | Trans pride |
| Bi | 3 | Bisexual, 40/20/40 weighting |
| Lesbian | 7 | Community (2018) |
| Pan | 3 | Pansexual |
| Ace | 4 | Asexual |
| Nonbinary | 4 | Non-binary |
| Genderfluid | 5 | Genderfluid |
| Agender | 7 | Agender (green centre) |
| Philadelphia | 8 | Rainbow + black & brown inclusion stripes |

Adding a flag is easy: append a `(NAME, [(color, weight), ...])` entry to the
`FLAGS` list in `code.py`. Colors are plain RGB hex (e.g. `0xE40303`); the
`weight` of each stripe controls its relative height (defaults to `1` for
equal stripes — see the Bi flag for a weighted example).

## Controls

- **SW1** (IO1) — previous flag
- **SW2** (IO2) — next flag
- **SW3** (IO43) — pause / resume auto-advance

## Code design

- **One bitmap, indexed palette.** The flag is a single `displayio.Bitmap`
  sized `128 × (160 - name bar)`. Its palette has one entry per stripe color;
  `bitmaptools.fill_region` paints each stripe with the matching palette index.
  Switching flags just reloads the palette colors and re-fills the stripes —
  no per-pixel work.
- **Stripe heights always sum to the flag area.** `stripe_heights()` walks the
  weights and rounds each stripe so the total is exactly the flag height, so
  there's never a one-pixel gap at the bottom.
- **Name bar is a separate tile.** The flag bitmap is `FLAG_H` tall; a second,
  solid-color tile plus three labels (name, index `N/10`, pause state) sit in
  the reserved bottom strip so the labels never overwrite the stripes.
- **NeoPixel scroll reuses the flag's stripe colors.** `render_leds()` builds
  the flag's RGB list once per frame and linearly interpolates between adjacent
  stripe colors as a continuous head scrolls around the ring of stripes,
  mapped onto the 5 pixels. The on-screen flag and the strip always agree.
- **Pause stops the timer, not the LEDs.** When paused (`SW3`), the auto-advance
  deadline is pushed to infinity, but the NeoPixel scroll keeps running so the
  badge still feels alive.
