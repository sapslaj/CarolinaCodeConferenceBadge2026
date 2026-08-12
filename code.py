"""
code.py -- Sample launcher for the Carolina Code Conference 2026 badge.
=======================================================================
Shows a picker on boot, then hands off to one of the samples in
/samples/. The samples themselves are unchanged -- the launcher runs
their code.py verbatim via exec().

Boot behavior
-------------
On reset, the picker appears for a few seconds with a countdown. If
no button is pressed, the launcher auto-runs the sample chosen last
time. On a fresh badge with no saved selection, it runs whichever
sample is alphabetically first. Press any button during the countdown
to stay in the picker.

Samples are discovered dynamically -- any folder under /samples/ that
contains a code.py becomes a picker entry.

Picker controls
---------------
  SW1  -- up   (previous sample)
  SW2  -- down (next sample)
  SW3  -- run selected sample

The last selection persists in microcontroller.nvm across power
cycles, so hitting reset re-runs the same sample.

Restoring the launcher
----------------------
The launcher's source lives at samples/Launcher/code.py -- copy it
over the top-level code.py (same workflow as installing any other
sample) to get the picker back. The samples are self-contained.
"""

# --- backlight off FIRST, before the slow adafruit imports --------
# The LCD panel powers up bright white. If we wait until after
# adafruit_st7735r and adafruit_display_text finish importing (a few
# seconds on cold boot), the attendee stares at a white screen. Grab
# IO5 and drive it low up front so the panel is dark while the rest
# of the launcher warms up.
import board
import digitalio
bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False

import os
import time
import busio
import displayio
import fourwire
import terminalio
import microcontroller
import adafruit_st7735r
from adafruit_display_text import label


# ------------------------------------------------------------------
# Auto-discover samples: any folder under /samples/ that contains a
# code.py becomes a picker entry. Sorted alphabetically for stable
# ordering. Drop in a new sample folder and it just shows up.
#
# samples/Launcher/ holds a backup copy of this launcher so people can
# restore it after clobbering root code.py with another sample. Skip
# it here so it doesn't list itself in its own picker.
# ------------------------------------------------------------------
SELF_NAME = "Launcher"


def discover_samples():
    try:
        entries = os.listdir("/samples")
    except OSError:
        return ()
    valid = []
    for name in entries:
        if name.startswith(".") or name == SELF_NAME:
            continue
        try:
            os.stat("/samples/%s/code.py" % name)
        except OSError:
            continue
        valid.append(name)
    valid.sort()
    return tuple(valid)


SAMPLES = discover_samples()

COUNTDOWN_SEC = 3


# ------------------------------------------------------------------
# Hardware (all released before handing off to the sample)
# ------------------------------------------------------------------
def _btn(pin):
    b = digitalio.DigitalInOut(pin)
    b.switch_to_input(pull=digitalio.Pull.UP)
    return b


sw1 = _btn(board.IO1)
sw2 = _btn(board.IO2)
sw3 = _btn(board.IO43)

font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

displayio.release_displays()
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)
display_bus = fourwire.FourWire(
    spi, command=board.IO6, chip_select=board.IO10, reset=board.IO7,
    baudrate=8_000_000,
)
display = adafruit_st7735r.ST7735R(
    display_bus, width=128, height=160, rotation=0, bgr=True,
    auto_refresh=False,
)


# ------------------------------------------------------------------
# Persistence -- store the sample NAME in NVM (not the index), so
# adding, removing, or reordering samples doesn't scramble the saved
# pick. Layout: byte 0 = length, bytes 1..1+length = ASCII name.
# Fresh NVM reads 0xFF, which falls through to the default.
# ------------------------------------------------------------------
_NVM_MAX = 32


def load_index():
    if not SAMPLES:
        return 0
    try:
        length = microcontroller.nvm[0]
        if length == 0 or length > _NVM_MAX:
            return 0
        name = bytes(microcontroller.nvm[1:1 + length]).decode("ascii")
    except Exception:
        return 0
    try:
        return SAMPLES.index(name)
    except ValueError:
        return 0


def save_index(idx):
    if not SAMPLES:
        return
    try:
        data = SAMPLES[idx].encode("ascii")[:_NVM_MAX]
        microcontroller.nvm[0] = len(data)
        microcontroller.nvm[1:1 + len(data)] = data
    except Exception as e:
        print("Launcher: could not save selection:", e)


# ------------------------------------------------------------------
# Picker UI
# ------------------------------------------------------------------
scene = displayio.Group()

bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1); bg_pal[0] = 0x000010
scene.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

title = label.Label(terminalio.FONT, text="PICK A SAMPLE", color=0x00FFFF)
title.anchor_point = (0.5, 0.5)
title.anchored_position = (64, 8)
scene.append(title)

status = label.Label(terminalio.FONT, text="", color=0xFFFF00)
status.anchor_point = (0.5, 0.5)
status.anchored_position = (64, 22)
scene.append(status)

item_labels = []
for i, name in enumerate(SAMPLES):
    lbl = label.Label(terminalio.FONT, text=name, color=0x808080)
    lbl.anchor_point = (0.5, 0.5)
    lbl.anchored_position = (64, 40 + i * 12)
    scene.append(lbl)
    item_labels.append(lbl)

hint1 = label.Label(terminalio.FONT, text="S1:up  S2:down", color=0x606060)
hint1.anchor_point = (0.5, 0.5)
hint1.anchored_position = (64, 144)
scene.append(hint1)

hint2 = label.Label(terminalio.FONT, text="S3:run", color=0x606060)
hint2.anchor_point = (0.5, 0.5)
hint2.anchored_position = (64, 154)
scene.append(hint2)

display.root_group = scene


def highlight(idx):
    for i, lbl in enumerate(item_labels):
        lbl.color = 0xFFFF00 if i == idx else 0x808080


# ------------------------------------------------------------------
# Boot -- countdown, then either open the menu or run the sample.
# ------------------------------------------------------------------
idx = load_index()
highlight(idx)
status.text = "auto in %ds" % COUNTDOWN_SEC
display.refresh()
bl.value = True

t_end = time.monotonic() + COUNTDOWN_SEC
entered_menu = False

while time.monotonic() < t_end:
    remaining = int(t_end - time.monotonic()) + 1
    new_status = "auto in %ds" % remaining
    if new_status != status.text:
        status.text = new_status
        display.refresh()
    if not (sw1.value and sw2.value and sw3.value):
        entered_menu = True
        break
    time.sleep(0.05)

if entered_menu:
    # wait for buttons to release before we start reading fresh presses
    while not (sw1.value and sw2.value and sw3.value):
        time.sleep(0.02)

    status.text = "SW3 to run"
    display.refresh()

    sw1_prev = sw2_prev = sw3_prev = True
    while True:
        v1, v2, v3 = sw1.value, sw2.value, sw3.value
        pressed1 = (not v1) and sw1_prev
        pressed2 = (not v2) and sw2_prev
        pressed3 = (not v3) and sw3_prev
        sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

        if pressed1:                              # SW1 = up
            idx = (idx - 1) % len(SAMPLES)
            highlight(idx); display.refresh(); time.sleep(0.12)
        if pressed2:                              # SW2 = down
            idx = (idx + 1) % len(SAMPLES)
            highlight(idx); display.refresh(); time.sleep(0.12)
        if pressed3:
            break
        time.sleep(0.02)

    save_index(idx)

status.text = "loading..."
display.refresh()

print("Launcher: running samples/%s/code.py" % SAMPLES[idx])


# ------------------------------------------------------------------
# Hand off -- release every pin/bus the launcher claimed so the
# sample can init its own hardware from a clean slate.
# ------------------------------------------------------------------
sw1.deinit(); sw2.deinit(); sw3.deinit()
font_cs.deinit()
bl.deinit()
displayio.release_displays()
spi.deinit()

path = "/samples/%s/code.py" % SAMPLES[idx]
with open(path) as f:
    source = f.read()
exec(source, {"__name__": "__main__", "__file__": path})
