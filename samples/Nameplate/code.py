"""
code_Nameplate.py -- Carolina Code Conference sample
=====================================================
Personalizable conference nameplate: big name on the display,
animated LED patterns on the 5 NeoPixels, palette color that also
recolors your on-screen name.

Edit the two lines below with your name, save the file, and
CircuitPython auto-reloads.

Controls
--------
  SW1 (IO1)   -- cycle LED pattern    (SOLID / BREATHE / CHASE / SPARKLE / WAVE)
  SW2 (IO2)   -- cycle color palette  (RAINBOW / WHITE / RED / ORANGE /
                                       YELLOW / GREEN / CYAN / BLUE /
                                       PURPLE / PINK)
  SW3 (IO43)  -- LEDs off             (SW1 or SW2 turns them back on)

Long names auto-scale down so they still fit the display.
"""

# ==============================================================
#   >>>  YOUR NAME  <<<
#   Edit these two strings, save the file, and the display and
#   LEDs will update automatically. Uppercase looks best.
# ==============================================================
FIRST_NAME = "HELLO"
LAST_NAME  = "WORLD"
# ==============================================================


import time
import math
import random
import board
import busio
import digitalio
import displayio
import fourwire
import neopixel
import terminalio
import bitmaptools
import adafruit_st7735r
from adafruit_display_text import label


# ------------------------------------------------------------------
# Hardware setup
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.35, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

sw1 = digitalio.DigitalInOut(board.IO1);  sw1.switch_to_input(pull=digitalio.Pull.UP)
sw2 = digitalio.DigitalInOut(board.IO2);  sw2.switch_to_input(pull=digitalio.Pull.UP)
sw3 = digitalio.DigitalInOut(board.IO43); sw3.switch_to_input(pull=digitalio.Pull.UP)

font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False

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
# Color helpers
# ------------------------------------------------------------------
def hsv_to_rgb(h, s, v):
    if s == 0.0:
        c = int(v * 255)
        return (c, c, c)
    h6 = h * 6.0
    i  = int(h6) % 6
    f  = h6 - int(h6)
    p  = v * (1.0 - s)
    q  = v * (1.0 - s * f)
    t  = v * (1.0 - s * (1.0 - f))
    if i == 0: return (int(v*255), int(t*255), int(p*255))
    if i == 1: return (int(q*255), int(v*255), int(p*255))
    if i == 2: return (int(p*255), int(v*255), int(t*255))
    if i == 3: return (int(p*255), int(q*255), int(v*255))
    if i == 4: return (int(t*255), int(p*255), int(v*255))
    return         (int(v*255), int(p*255), int(q*255))


def rgb_to_hex(rgb):
    return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


def scale_rgb(rgb, b):
    b = 0.0 if b < 0.0 else (1.0 if b > 1.0 else b)
    return (int(rgb[0] * b), int(rgb[1] * b), int(rgb[2] * b))


# ------------------------------------------------------------------
# Palettes and patterns
# ------------------------------------------------------------------
# Palette 0 is RAINBOW -- special-cased everywhere it's used.
PALETTES = [
    ("RAINBOW", None),
    ("WHITE",   (255, 255, 255)),
    ("RED",     (255,   0,   0)),
    ("ORANGE",  (255, 120,   0)),
    ("YELLOW",  (255, 220,   0)),
    ("GREEN",   (  0, 255,   0)),
    ("CYAN",    (  0, 200, 255)),
    ("BLUE",    ( 30,  60, 255)),
    ("PURPLE",  (180,   0, 255)),
    ("PINK",    (255,  50, 150)),
]

PATTERNS = ("SOLID", "BREATHE", "CHASE", "SPARKLE", "WAVE")


def palette_color(pal_idx, pixel_i, t):
    """Base RGB for a given pixel in a given palette at time t."""
    if pal_idx == 0:                           # RAINBOW
        hue = ((pixel_i / 5.0) + t * 0.15) % 1.0
        return hsv_to_rgb(hue, 1.0, 1.0)
    return PALETTES[pal_idx][1]


def display_color(pal_idx, t):
    """Single RGB for on-screen text tinted with the palette."""
    if pal_idx == 0:
        return hsv_to_rgb((t * 0.10) % 1.0, 1.0, 1.0)
    return PALETTES[pal_idx][1]


def render_pattern(pattern, pal_idx, t):
    """Return a list of 5 (r, g, b) tuples for the strip at time t."""
    out = [(0, 0, 0)] * 5

    if pattern == "SOLID":
        for i in range(5):
            out[i] = palette_color(pal_idx, i, t)

    elif pattern == "BREATHE":
        b = 0.15 + 0.85 * ((math.sin(t * 2.2) + 1) / 2)
        for i in range(5):
            out[i] = scale_rgb(palette_color(pal_idx, i, t), b)

    elif pattern == "CHASE":
        pos = (t * 3.0) % 5.0
        for i in range(5):
            # distance from the moving "head" -- soft tail
            d = min(abs(i - pos), abs(i - pos - 5), abs(i - pos + 5))
            b = max(0.0, 1.0 - d * 0.55)
            out[i] = scale_rgb(palette_color(pal_idx, i, t), b)

    elif pattern == "SPARKLE":
        for i in range(5):
            if random.random() < 0.25:
                b = random.uniform(0.4, 1.0)
                out[i] = scale_rgb(palette_color(pal_idx, i, t), b)
            # else leave black

    elif pattern == "WAVE":
        for i in range(5):
            phase = t * 3.0 - i * 0.6
            b = 0.15 + 0.85 * ((math.sin(phase) + 1) / 2)
            out[i] = scale_rgb(palette_color(pal_idx, i, t), b)

    return out


# ------------------------------------------------------------------
# Display scene
# ------------------------------------------------------------------
def choose_scale(text, max_px=124):
    """Biggest scale (4..1) that keeps the text within max_px."""
    for s in (4, 3, 2, 1):
        if len(text) * 6 * s <= max_px:
            return s
    return 1


scene = displayio.Group()

# Background: dark blue
bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1); bg_pal[0] = 0x000010
scene.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

# "HELLO" banner
hello = label.Label(terminalio.FONT, text="HELLO", scale=2, color=0x00FFFF)
hello.anchor_point = (0.5, 0.5)
hello.anchored_position = (64, 14)
scene.append(hello)

# "MY NAME IS"
subtitle = label.Label(terminalio.FONT, text="MY NAME IS", color=0x808080)
subtitle.anchor_point = (0.5, 0.5)
subtitle.anchored_position = (64, 32)
scene.append(subtitle)

# First name -- auto-scaled
first_lbl = label.Label(terminalio.FONT, text=FIRST_NAME,
                        scale=choose_scale(FIRST_NAME), color=0xFFFFFF)
first_lbl.anchor_point = (0.5, 0.5)
first_lbl.anchored_position = (64, 66)
scene.append(first_lbl)

# Last name -- auto-scaled
last_lbl = label.Label(terminalio.FONT, text=LAST_NAME,
                       scale=choose_scale(LAST_NAME), color=0xFFFFFF)
last_lbl.anchor_point = (0.5, 0.5)
last_lbl.anchored_position = (64, 112)
scene.append(last_lbl)

# Status footer (pattern / palette / on-off)
status_lbl = label.Label(terminalio.FONT, text="", color=0x606060, x=6, y=154)
scene.append(status_lbl)

display.root_group = scene


# ------------------------------------------------------------------
# State
# ------------------------------------------------------------------
pattern_idx = 1   # BREATHE -- gentle default
palette_idx = 0   # RAINBOW
leds_on     = True

sw1_prev = True
sw2_prev = True
sw3_prev = True


def update_status():
    if leds_on:
        status_lbl.text = "pat:%s  pal:%s" % (
            PATTERNS[pattern_idx], PALETTES[palette_idx][0])
    else:
        status_lbl.text = "LEDs off (S1/S2 to wake)"


# ------------------------------------------------------------------
# Boot
# ------------------------------------------------------------------
update_status()
display.refresh()
bl.value = True

print("Nameplate for %s %s" % (FIRST_NAME, LAST_NAME))
print("  first-name scale=%d, last-name scale=%d"
      % (choose_scale(FIRST_NAME), choose_scale(LAST_NAME)))


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
last_display_refresh = 0.0

while True:
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    pressed_sw1 = (not v1) and sw1_prev
    pressed_sw2 = (not v2) and sw2_prev
    pressed_sw3 = (not v3) and sw3_prev
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

    if pressed_sw1:
        pattern_idx = (pattern_idx + 1) % len(PATTERNS)
        leds_on = True
        print("pattern:", PATTERNS[pattern_idx])
        time.sleep(0.12)

    if pressed_sw2:
        palette_idx = (palette_idx + 1) % len(PALETTES)
        leds_on = True
        print("palette:", PALETTES[palette_idx][0])
        time.sleep(0.12)

    if pressed_sw3:
        leds_on = False
        print("LEDs off")
        pixels.fill((0, 0, 0)); pixels.show()
        time.sleep(0.12)

    t = time.monotonic()

    # LEDs
    if leds_on:
        rgb_list = render_pattern(PATTERNS[pattern_idx], palette_idx, t)
        for i in range(5):
            pixels[i] = rgb_list[i]
        pixels.show()

    # Display -- throttle to ~10 Hz
    if t - last_display_refresh > 0.1:
        tint = rgb_to_hex(display_color(palette_idx, t)) if leds_on else 0x606060
        first_lbl.color = tint
        last_lbl.color  = tint
        update_status()
        display.refresh()
        last_display_refresh = t

    time.sleep(0.02)
