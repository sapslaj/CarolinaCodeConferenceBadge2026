# QRCodeDisplay

Puts a scannable QR code on the badge screen so somebody can point a phone at your chest and land on a link. Three codes ship with it; SW1 and SW2 flip between them.

The first one is a rickroll. The folder, the caption and the screen give nothing away — that is the point.

| Caption | Goes to |
|---|---|
| `SCAN ME` | `https://youtu.be/dQw4w9WgXcQ` |
| `BADGE HUB` | `https://badge.sapslaj.cloud` |
| `THE BADGE` | `https://blog.carolina.codes/p/2026-circuit-board-badge` |

## What you should see

A white card filling almost the whole screen with a black QR code on it, a caption in large text underneath, and a slow blue pixel walking along the NeoPixel strip to catch an eye from across the room. Nothing else moves.

## Controls

| Switch | Action |
|---|---|
| SW1 | Previous code |
| SW2 | Next code |
| SW3 | Mute/unmute the NeoPixels |

There is no auto-advance, on purpose. A code that changes while somebody is lining up their camera is a code that never gets scanned.

## Why the codes are pre-baked

Generating a QR code means Reed–Solomon error correction, mask selection and pattern placement — a few hundred lines the badge has no library for, and none of it needs to run at runtime because the links never change. So the matrices are generated on a laptop and pasted into `code.py` as ASCII art, in the same spirit as the sprite art in the Doom sample: `#` is a dark module, `.` is a light one.

To add your own, install [segno](https://github.com/heuer/segno) and print a matrix:

```bash
pip install segno
python3 -c "
import segno
qr = segno.make('https://example.com', error='l', boost_error=False)
print('v%s, %d modules' % (qr.version, len(qr.matrix)))
for row in qr.matrix:
    print('    \"%s\",' % ''.join('#' if m else '.' for m in row))
"
```

Paste the rows into a new entry in `QR_CODES` with a caption and the URL. The renderer works out the module size on its own, so a bigger code just draws smaller — nothing else to change.

**Do not hand-edit a matrix.** Every module carries error-correction data; flipping one to "fix" it corrupts the whole code. `code.py` checks at startup that each matrix is square and says so plainly if it isn't, which catches the usual paste accident, but it cannot tell you that you mangled the payload.

## Making it actually scan

Most homemade QR displays fail for one of three reasons, and all three are handled here:

- **No quiet zone.** The spec wants 4 modules of clear white margin around the code, and scanners give up well before zero. `fit_scale()` refuses to go below 2 and prefers 4 when it fits.
- **Modules too small.** A phone needs a few camera pixels per module. `fit_scale()` picks the largest whole-pixel module size that still fits with a margin — whole pixels matter, because a fractional scale makes some modules a pixel wider than others and smears the grid.
- **Not enough contrast.** The card is pure white on a black surround with the backlight at full, which is about the best a 1.77" LCD can do.

The table uses error correction level **L** rather than a higher level. That is deliberate: L keeps the two short links at 25×25 modules, so they render at 4 screen pixels per module instead of 3. On a screen this small, bigger modules buy more real-world scanning range than extra error correction does — there is no dirt or damage to correct for, only glare, and glare is beaten by module size. The long blog link needs 33×33 either way and lands at 3 pixels per module.

If you find a code that will not scan on some phone, the first thing to try is a shorter URL — that is what drops the version number, which is what buys module size.

## Verification

The three codes were checked by rendering them through this sample's own `draw_code()` into a real pixel buffer and decoding that buffer with OpenCV's QR detector, at native size and at 4× — so the offsets, the automatic scale choice and the dark-run merging are all covered, not just the pasted matrices. That test caught two genuine bugs before the sample was committed.

## Code design

- **Two colours, one bitmap.** The screen is a single `displayio.Bitmap` with a 2-entry palette. Light modules and the quiet zone are simply the card colour, so only the dark modules get drawn.
- **Dark runs are merged.** Adjacent dark modules in a row become one `fill_region` call instead of one per module, roughly halving the calls. It is drawn once when the code changes, never per frame — the main loop only polls switches and updates the LEDs.
- **Layout is derived, not hardcoded.** `fit_scale()` returns the module size and quiet zone, and everything else (card size, centring) falls out of those two numbers, so dropping in a larger code needs no other edits.
