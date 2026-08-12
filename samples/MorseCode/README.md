# Morse Code

Tap out Morse code on SW1 and watch it decode live on the display. The 5 NeoPixels give you color-coded feedback for every symbol — amber while held, blue flash for a dot, purple flash for a dash, green flash on each successful letter decode.

## Controls

- **SW1 (IO1)** — the Morse key. Short press = dot, long press = dash.
- Stop pressing to decode a letter (after ~360 ms of silence).
- Pause even longer (~720 ms) to insert a word space.

## What you should see

- **"MORSE CODE"** title at the top.
- **Current pattern** (dots and dashes) accumulates below the title as you key.
- **Big decoded character** (scale 5) appears in the middle after each letter.
- **Two-line history** at the bottom shows the last ~42 decoded characters.

## Code design

- **PARIS-timing constants** (`UNIT = 0.08 s`) - calibrated to roughly 10 WPM. All other thresholds are multiples of `UNIT`, so bumping that single value re-tunes the whole decoder.
- **Debounced edge detection** — `raw != btn_state` is only accepted after `DEBOUNCE` (25 ms) has elapsed since the last edge, avoiding false triggers on bounce.
- **State machine driven by two timers**:
  - `press_start → now` measures dot-vs-dash on release.
  - `last_release → now` measures the inter-symbol gap for letter/word boundaries.
- **`char_pending` flag** — set on release and cleared on decode, so a stray release doesn't fire the decode logic twice.
- **LED feedback via `set_leds(color, duration)`** — a self-scheduling helper that stores an "off time" and lets the main loop turn the LEDs off later, so button handling never blocks.
- **Lookup table** — the full Morse alphabet lives in a single `MORSE_TABLE` dict; `dict.get(pattern, '?')` gracefully handles typos.
- **Bounded history** — decoded text is trimmed to `MAX_TEXT_CHARS` (42) so the two-line display never overflows.
