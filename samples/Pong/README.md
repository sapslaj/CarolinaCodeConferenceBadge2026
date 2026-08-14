# Pong vs AI

Pong on the 128×160 TFT. You control the left paddle; a simple AI
controls the right. The ball speeds up a little on every rally hit, and
the first side to 7 points wins the match. The 5 NeoPixels form a score
meter — green for your points, red for the CPU's, out of 7.

## What you should see

- A dashed centre net, your green paddle on the left, the CPU's red
  paddle on the right, and a white ball. The HUD shows the score and
  your cumulative wins.
- The ball's rebound angle depends on where it hits your paddle, so
  you can aim by hitting near the edges.
- The AI only actively tracks the ball while it's moving toward it
  and is capped at a slower speed than the ball can reach — so it's
  beatable but not a pushover.
- On match end the screen shows **YOU WIN!** or **CPU WINS** and
  `SW3 to play again`; wins are saved to NVM.

## Controls

| Switch | Action |
|--------|--------|
| SW1 (IO1)  | Move paddle **up** |
| SW2 (IO2)  | Move paddle **down** |
| SW3 (IO43) | **Pause / resume**; restart after a match ends |

## Code design

- **Float positions, int rendering** — paddle/ball positions are kept
  as floats for smooth sub-pixel motion and only cast to `int` at draw
  time, so the ball doesn't "stair-step" at low speeds.
- **Rebound angle from hit position** — `hit = (ball_y - paddle_centre)
  / half_height` in `[-1, 1]`; the vertical velocity becomes
  `hit * speed`, so edge hits spike the ball flat across.
- **AI with a deliberate blind spot** — the AI tracks the ball only when
  `bvx > 0` (ball coming toward it) and otherwise drifts back to centre.
  Its max speed (`AI_SPEED = 1.9`) is below the ball's cap (`5.5`), so
  fast angles beat it. This is the whole "is it fun?" lever — tune
  `AI_SPEED` to raise/lower difficulty.
- **Wins in NVM at offset 72**, a single byte, clear of the Launcher
  (0..40), Snake (64/65) and Tetris (68/69).
- **Full-screen bitmap redrawn each frame** with `bitmaptools.fill_region`
  for net, paddles and ball — at ~60 Hz (`time.sleep(0.016)`) it's
  flicker-free.
