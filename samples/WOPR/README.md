# WOPR

A *WarGames*-inspired "War Operation Plan Response" terminal for the conference badge. Green phosphor text types itself onto the display, a bank of status lights blinks along the bottom, and the NeoPixel strip idles like a 1980s military mainframe. A game menu lets you pick a simulation — including the one you really shouldn't.

## Boot sequence

On power-up WOPR types out its greeting one character at a time:

```
GREETINGS PROFESSOR
FALKEN.

SHALL WE PLAY A GAME?
```

Press any button to skip straight to the game menu.

## Controls

|   Switch   |              In the menu              |         While busy          |
|------------|----------------------------------------|------------------------------|
| SW1 (IO1)  | Move selection up                       | Abort back to the menu       |
| SW2 (IO2)  | Select / enter the highlighted game     | Abort back to the menu       |
| SW3 (IO43) | Move selection down                     | Abort back to the menu       |

Choose most games and WOPR "loads" them with a text progress bar, then reports the (inevitable) result. Choose **GLOBAL THERMONUCLEAR WAR** and it plays out the film's iconic ending instead — a DEFCON 5→1 countdown with a rotating list of target cities, a flash of red alert lights, and the punchline.

**Secret code:** hold SW1 and SW3 together for about a second while in the menu to skip straight to Global Thermonuclear War.

**Attract mode:** leave the menu untouched for 25 seconds and WOPR gets bored and plays a couple of random (non-nuclear) games against itself, screensaver-style, then waits for input again. Any button press interrupts it and returns to the menu immediately.

## Code design

- A tiny non-blocking **script interpreter** (`step_script`) drives the typewriter effect, timed pauses, and the DEFCON countdown one step per main-loop iteration — nothing longer than a button-poll `time.sleep()`, so the switches stay responsive during the longest sequences. Scripts are plain lists of tuples, e.g. `("type", row, text)`, `("pause", seconds)`, `("defcon", level, seconds)`.
- **Eight reusable row labels** (`row_lbl`) are shared by the boot greeting, the menu list, and the game-loading/DEFCON text. Nothing is re-created at runtime — only `.text` and `.color` are reassigned, same approach as the Nameplate and WiFiScanner samples.
- The **status-light bank** is one `displayio.Bitmap` + `bitmaptools.fill_region()` call per cell (same technique the WiFiScanner sample uses for its signal bars), so redrawing 24 cells every tick is cheap local memory work — the SPI bus only sees it on the next throttled `display.refresh()`.
- `set_panel_mode()` swaps the status lights *and* the NeoPixels between a calm green/amber idle flicker and a fast red "alert" flicker together, so the panel and the LED strip read as one system rather than two independent animations.
- Menu navigation uses the same edge-triggered button + scrolling-window pattern (`visible_start`) as the WiFiScanner sample's network list.
- **Attract mode** reuses `loading_script()` to build a longer script on the fly (`attract_script()`), so the screensaver is just the normal game-loading sequence run twice back to back with a couple of banner lines around it — no separate rendering path to maintain.
- The **secret code** is a level-triggered hold timer (`combo_start`), separate from the edge-triggered button presses used everywhere else, since it needs to detect "held for N seconds" rather than "just pressed."

## A note on testing

This sample was written and reviewed without physical badge hardware in hand. To keep it working on first flash, every display/LED/button API it uses (`fourwire.FourWire` + `adafruit_st7735r.ST7735R` init, `label.Label` text/color updates, `bitmaptools.fill_region`, `neopixel.NeoPixel`, edge-triggered `digitalio` button reads) is copied verbatim from patterns already confirmed working in the other samples in this repo, and all on-screen text was measured against the 128×160 panel (6 px/char at scale 1) so nothing should run off the edge of the screen. If you spot a glitch on real hardware, it's most likely in the new bits: the script interpreter, the status-light layout, or the attract/secret-code timers.

Two things worth calling out explicitly since they're easy to get wrong without a board to test on:
- `bitmaptools.fill_region(bitmap, x1, y1, x2, y2, value)` takes **corner coordinates**, not width/height — `x2`/`y2` are exclusive. Verified against the CircuitPython docs rather than assumed from the WiFiScanner sample's usage, which always happens to call it with `x1=y1=0` (where the distinction is invisible).
- CircuitPython's built-in `random` module has **no `sample()`** (unlike desktop Python) — attract mode picks two distinct random games with a hand-rolled retry loop instead.
