# Snake

Classic Snake on the 128×160 TFT. Steer with two buttons (turn left /
turn right, relative to the snake's heading), eat the red food, grow,
and don't crash into yourself or the wall. The 5 NeoPixels grow into a
green bar as you get longer and flash white when you eat.

## What you should see

- A 16×18 grid of 8 px cells below a thin HUD strip showing your score
  and best.
- The snake (bright green head, dim green body) starts 3 long, moving
  right. A red food cell appears; eating it grows the snake and spawns
  new food.
- The snake speeds up slightly with every food eaten.
- On a crash the screen shows **GAME OVER**, your score and high score,
  and `SW3 to restart`. The LEDs go red.

## Controls

| Switch | Action |
|--------|--------|
| SW1 (IO1)  | Turn **left** (relative to current heading) |
| SW2 (IO2)  | Turn **right** (relative to current heading) |
| SW3 (IO43) | Start / restart after a crash |

## Code design

- **Relative turning** — `turn_left`/`turn_right` rotate the current
  `(dx, dy)` vector (CCW / CW). This is the two-button Snake control
  scheme: it's unambiguous and never requires a "reverse" that would
  be an instant self-collision.
- **Single bitmap playfield** redrawn each tick with `bitmaptools.fill_region`
  (clear → food → snake). Cheap enough at the ~6–16 Hz tick rate.
- **Self-collision excludes the tail** when the snake isn't growing,
  because the tail cell will move this tick — the standard Snake
  subtlety that lets you safely turn along your own body.
- **High score in NVM at offset 64/65** (2 bytes, big-endian), chosen
  clear of the Launcher's saved pick in bytes 0..40, so the two never
  clobber each other.
- **Speed = `0.16s` minus `0.004s` per food, floored at `0.06s`** — a
  gentle ramp that stays playable.
