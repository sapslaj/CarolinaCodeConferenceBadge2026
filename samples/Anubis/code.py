"""
Anubis -- Carolina Code Conference sample
==========================================
A simple slideshow: PENSIVE.BMP with a loading bar filling underneath
it for 5 seconds, then HAPPY.BMP full-screen for 30 seconds, then
back to PENSIVE and repeat forever.

No buttons, no menus -- just plug it in and let it loop.

Code design
-----------
- Both images are loaded once at startup into two separate
  `displayio.TileGrid`s stacked in the same `displayio.Group`. Only
  one is ever visible at a time, toggled with the `.hidden` attribute
  -- `TileGrid.bitmap`/`.pixel_shader` are read-only after
  construction in CircuitPython, so swapping the image on a single
  TileGrid isn't an option; two grids + `.hidden` is the supported
  way to do it.
- The loading bar is a small `displayio.Bitmap` redrawn with
  `bitmaptools.fill_region(bitmap, x1, y1, x2, y2, value)` -- note
  that's *corner coordinates* (x2/y2 exclusive), not width/height.
- A plain two-state timer (`phase` / `phase_start`) drives the loop;
  nothing blocks longer than a display-refresh tick, so the loop
  stays smooth and simple.
"""

import time
import board
import busio
import digitalio
import displayio
import fourwire
import neopixel
import bitmaptools
import adafruit_st7735r
import adafruit_imageload


# ------------------------------------------------------------------
# Hardware setup
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.35, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

# Font-ROM chip must stay deselected so the display owns the SPI bus
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False  # blank until the first frame is drawn

displayio.release_displays()
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)
display_bus = fourwire.FourWire(
    spi, command=board.IO6, chip_select=board.IO10, reset=board.IO7,
    baudrate=8_000_000,
)
display = adafruit_st7735r.ST7735R(
    display_bus, width=128, height=160, rotation=0, bgr=True, auto_refresh=False,
)


# ------------------------------------------------------------------
# Scene
# ------------------------------------------------------------------
scene = displayio.Group()

# Black background fills the full 128x160 space behind the 128x128 art
bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1); bg_pal[0] = 0x000000
scene.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

IMG_Y = (160 - 128) // 2  # 16 px from top, image centred vertically

pensive_bmp, pensive_pal = adafruit_imageload.load(
    "/img/anubis/pensive.bmp", bitmap=displayio.Bitmap, palette=displayio.Palette,
)
happy_bmp, happy_pal = adafruit_imageload.load(
    "/img/anubis/happy.bmp", bitmap=displayio.Bitmap, palette=displayio.Palette,
)

pensive_tile = displayio.TileGrid(pensive_bmp, pixel_shader=pensive_pal, y=IMG_Y)
happy_tile = displayio.TileGrid(happy_bmp, pixel_shader=happy_pal, y=IMG_Y)
happy_tile.hidden = True
scene.append(pensive_tile)
scene.append(happy_tile)

# --- Loading bar (only shown during the PENSIVE phase) ---
BAR_X, BAR_Y, BAR_W, BAR_H = 8, 148, 112, 8

bar_frame_bmp = displayio.Bitmap(BAR_W + 4, BAR_H + 4, 1)
bar_frame_pal = displayio.Palette(1); bar_frame_pal[0] = 0x333333
bar_frame_tile = displayio.TileGrid(
    bar_frame_bmp, pixel_shader=bar_frame_pal, x=BAR_X - 2, y=BAR_Y - 2,
)
scene.append(bar_frame_tile)

bar_bmp = displayio.Bitmap(BAR_W, BAR_H, 2)
bar_pal = displayio.Palette(2)
bar_pal[0] = 0x101010
bar_pal[1] = 0xC9A227  # gold
bar_tile = displayio.TileGrid(bar_bmp, pixel_shader=bar_pal, x=BAR_X, y=BAR_Y)
scene.append(bar_tile)

display.root_group = scene


def draw_bar(frac):
    if frac < 0.0:
        frac = 0.0
    elif frac > 1.0:
        frac = 1.0
    filled = int(BAR_W * frac)
    bitmaptools.fill_region(bar_bmp, 0, 0, BAR_W, BAR_H, 0)
    if filled > 0:
        bitmaptools.fill_region(bar_bmp, 0, 0, filled, BAR_H, 1)


# ------------------------------------------------------------------
# Phase timer
# ------------------------------------------------------------------
PENSIVE_SECS = 5.0
HAPPY_SECS = 30.0

PHASE_PENSIVE = "PENSIVE"
PHASE_HAPPY = "HAPPY"


def show_pensive():
    pensive_tile.hidden = False
    happy_tile.hidden = True
    bar_frame_tile.hidden = False
    bar_tile.hidden = False
    draw_bar(0.0)


def show_happy():
    pensive_tile.hidden = True
    happy_tile.hidden = False
    bar_frame_tile.hidden = True
    bar_tile.hidden = True


phase = PHASE_PENSIVE
phase_start = time.monotonic()
show_pensive()

print("Anubis slideshow running")


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
last_refresh = 0.0

while True:
    t = time.monotonic()
    elapsed = t - phase_start

    if phase == PHASE_PENSIVE:
        if elapsed >= PENSIVE_SECS:
            phase = PHASE_HAPPY
            phase_start = t
            show_happy()
        else:
            draw_bar(elapsed / PENSIVE_SECS)
    else:
        if elapsed >= HAPPY_SECS:
            phase = PHASE_PENSIVE
            phase_start = t
            show_pensive()

    if t - last_refresh > 0.05:
        display.refresh()
        last_refresh = t
        if not bl.value:
            bl.value = True

    time.sleep(0.02)
