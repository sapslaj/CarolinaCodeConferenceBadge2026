# Tetris

Full Tetris on the 128×160 TFT: a 10×20 playfield with a side panel
showing the next piece, score, lines, level, and your best. The 5
NeoPixels form a level meter — one more LED lights up every ten lines.

## What you should see

- The board on the left, a side panel on the right with **NEXT** preview,
  score, lines (`L`), level (`LV`), and best (`HI`).
- Falling tetrominoes with a dim **ghost** piece showing where it will
  land. Lines clear with the classic 0/40/100/300/1200 scoring scaled by
  level; every 10 lines bumps the level and speeds up gravity.
- On top-out the screen shows **GAME OVER** / `SW3 restart`; the LEDs
  go red and the best score is saved.

## Controls

| Switch | Action |
|--------|--------|
| SW1 (IO1)      | Move **left** (auto-repeats while held) |
| SW2 (IO2)      | Move **right** (auto-repeats while held) |
| SW3 (IO43)     | **Rotate** clockwise |
| SW1 + SW2 held | **Soft drop** (piece falls fast while both are pressed) |

## Code design

- **7-bag randomiser** (`new_bag`) shuffles all seven pieces before any
  repeats — the modern Tetris standard, so you never get long droughts
  or floods of one piece.
- **Rotation by matrix, not lookup tables** — `rotate_cells` applies
  `(x,y) → (y,-x)` then normalises to `(0,0)`, so there's exactly one
  place that knows how to rotate. Wall kicks try a small set of offsets
  `(0,0) (-1,0) (1,0) (0,-1) (-2,0) (2,0)` and keep the first that fits —
  not full SRS, but feels right.
- **`lock_piece` is the single state transition** — it stamps the piece
  into the grid, clears lines, recomputes level/score, spawns the next
  piece, and detects top-out (spawn collision) to end the game.
- **Best score in NVM at offset 68/69**, clear of the Launcher (0..40)
  and Snake (64/65), so multiple games can coexist without clobbering.
- **`auto_refresh=False` + explicit `display.refresh()`** keeps the
  per-frame redraw (full board + ghost + piece, ~200 cells) smooth.
