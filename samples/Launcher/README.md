# Launcher

The sample picker that ships preloaded on the badge. On boot it shows a 3-second countdown and either auto-runs your last selection or opens a menu of every sample in `/samples/`. This folder holds the reference copy — if you clobber the top-level `code.py` with a sample and want the picker back, restore from here.

## What you should see

- Backlight comes on with a dark blue background and the title **PICK A SAMPLE** in cyan.
- A yellow `auto in 3s` counter counts down. If you press any button during the countdown, the picker stops the timer and stays open.
- Sample names are listed vertically. The current selection is highlighted yellow, the others are dim grey.
- Bottom of the screen shows the button hints: `S1:up  S2:down` and `S3:run`.
- After you pick (or the countdown expires), the screen shows `loading...` and the selected sample takes over.

## Controls

| Switch | Action |
|--------|--------|
| SW1 (IO1)  | Highlight previous sample |
| SW2 (IO2)  | Highlight next sample |
| SW3 (IO43) | Run the highlighted sample |

## Restoring the launcher

If you've copied a sample's `code.py` over the top-level `code.py` and now want the picker back:

1. Open `samples/Launcher/code.py`.
2. Copy it over the top-level `code.py`.
3. CircuitPython auto-reloads on save. Next reset shows the picker.

## Code design

- **Backlight off before slow imports** — the LCD panel powers up bright white, and `adafruit_st7735r` + `adafruit_display_text` take a few seconds to load on cold boot. Grabbing GPIO5 and driving it LOW *before* those imports keeps the panel dark during warm-up, so attendees don't see a jarring white flash.
- **Dynamic sample discovery** — `discover_samples()` scans `/samples/` and picks up any folder containing a `code.py`. Drop in a new sample folder and it appears in the menu with no code changes. Dotfile entries and `Launcher` itself are filtered out.
- **NVM-persisted selection** — the sample **name** (not its index) is stored in `microcontroller.nvm`. Adding, removing, or renaming samples doesn't scramble the saved pick. Byte 0 is the name length, bytes 1..N are the ASCII name.
- **Countdown UI** — a `time.monotonic()` deadline with a 50 ms polling loop watches the buttons. Any press before the deadline switches from "auto-run" mode to "menu" mode without an extra reset.
- **Edge-triggered navigation** — the menu tracks each button's previous value so one press moves one item, regardless of how long you hold it. A 120 ms cooldown after each move keeps rapid taps from over-shooting.
- **Full hardware release before hand-off** — every DigitalInOut, the SPI bus, and the display are `deinit()`'d and `release_displays()`'d before the sample runs. The selected sample gets a clean slate to init its own hardware from scratch, just as if it had been booted directly.
- **`exec()` in a scoped namespace** — the sample runs via `exec(source, {"__name__": "__main__", "__file__": path})`. Setting `__name__ = "__main__"` means samples that use `if __name__ == "__main__":` guards behave as if they were the entry point, which they effectively are.
