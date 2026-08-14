"""
code.py -- Pride Flags carousel
================================
A rotating display of pride flags on the 128x160 LCD. Each flag is
drawn full-screen as horizontal stripes (the classic flag layout),
held for a few seconds, then the next one fades in. The 5 NeoPixels
scroll the current flag's stripe colors in step.

The carousel auto-advances, but the buttons let you page through
manually whenever you like.

Controls
--------
  SW1 (IO1)   -- previous flag
  SW2 (IO2)   -- next flag
  SW3 (IO43)  -- pause / resume auto-advance

Flags included
--------------
  Rainbow        Gilbert Baker's 6-stripe classic
  Trans          5-stripe trans pride flag
  Bi             3-stripe bisexual pride flag (40/20/40)
  Lesbian        7-stripe community (2018) flag
  Pan            3-stripe pansexual flag
  Ace            4-stripe asexual flag
  Nonbinary      4-stripe non-binary flag
  Genderfluid    5-stripe genderfluid flag
  Agender        7-stripe agender flag
  Philadelphia   Rainbow + black & brown (inclusion)
"""

import time
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
# Flags
# ------------------------------------------------------------------
# Each flag is (NAME, stripes) where stripes is a list of
# (color_0xBBGGRR, weight). weight controls relative stripe height
# (defaults to 1 = equal stripes). Colors are stored in the 0xBBGGRR
# form that displayio palettes expect, written here as readable hex.
#
# Hex conventions used (RGB):
#   rainbow red    #E40303   orange  #FF8C00   yellow #FFED00
#   rainbow green  #008026   blue    #004DFF   violet #750787
#   trans lt blue  #5BCEFA   pink    #F5A9B8   white  #FFFFFF
#   bi pink        #D60270   purple  #9B4F96   blue   #0033A0
#   lesbian        #D52D00 / #EF7627 / #FF9A56 / #FFFFFF /
#                  #D162A4 / #B55690 / #A30262
#   pan blue        #1BB3FF   yellow  #FFDD00   magenta #FF218C
#   ace black      #000000   gray    #A4A4A4   white #FFFFFF  purple #800080
#   nb  yellow     #FCF434   white   #FFFFFF   purple #9C59D1  black #000000
#   gf  pink       #FF75A2   white   #FFFFFF   purple #BE18D6
#       black      #000000   blue    #333EBD
#   agender black  #000000   gray #B9B9B9   white #FFFFFF   green #008026
#   philly brown   #613D17   black #000000
#
# We store colors as plain RGB ints and convert to 0xBBGGRR below so
# the same list can drive both the palette and the NeoPixels.
def C(rrggbb):
    # "rrggbb" -> 0xBBGGRR for displayio palettes
    r = (rrggbb >> 16) & 0xFF
    g = (rrggbb >> 8) & 0xFF
    b = rrggbb & 0xFF
    return (b << 16) | (g << 8) | r


def rgb_tuple(pal_int):
    # 0xBBGGRR -> (r, g, b) for NeoPixels
    return (pal_int & 0xFF, (pal_int >> 8) & 0xFF, (pal_int >> 16) & 0xFF)


# Each stripe: (RGB hex, weight)
FLAGS = [
    ("RAINBOW",
     [(0xE40303, 1), (0xFF8C00, 1), (0xFFED00, 1),
      (0x008026, 1), (0x004DFF, 1), (0x750787, 1)]),
    ("TRANS",
     [(0x5BCEFA, 1), (0xF5A9B8, 1), (0xFFFFFF, 1),
      (0xF5A9B8, 1), (0x5BCEFA, 1)]),
    ("BI",
     [(0xD60270, 2), (0x9B4F96, 1), (0x0033A0, 2)]),
    ("LESBIAN",
     [(0xD52D00, 1), (0xEF7627, 1), (0xFF9A56, 1), (0xFFFFFF, 1),
      (0xD162A4, 1), (0xB55690, 1), (0xA30262, 1)]),
    ("PAN",
     [(0x1BB3FF, 1), (0xFFDD00, 1), (0xFF218C, 1)]),
    ("ACE",
     [(0x000000, 1), (0xA4A4A4, 1), (0xFFFFFF, 1), (0x800080, 1)]),
    ("NONBINARY",
     [(0xFCF434, 1), (0xFFFFFF, 1), (0x9C59D1, 1), (0x000000, 1)]),
    ("GENDERFLUID",
     [(0xFF75A2, 1), (0xFFFFFF, 1), (0xBE18D6, 1),
      (0x000000, 1), (0x333EBD, 1)]),
    ("AGENDER",
     [(0x000000, 1), (0xB9B9B9, 1), (0xFFFFFF, 1), (0x008026, 1),
      (0xFFFFFF, 1), (0xB9B9B9, 1), (0x000000, 1)]),
    ("PHILADELPHIA",
     [(0x000000, 1), (0x613D17, 1), (0xE40303, 1), (0xFF8C00, 1),
      (0xFFED00, 1), (0x008026, 1), (0x004DFF, 1), (0x750787, 1)]),
]

MAX_COLORS = max(len(s) for _, s in FLAGS)   # widest flag -> palette size
HOLD_SEC = 4.0                                # seconds per flag (auto)
NUM = 5                                       # NeoPixel count


# ------------------------------------------------------------------
# Hardware
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, NUM, brightness=0.35, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

sw1 = digitalio.DigitalInOut(board.IO1);  sw1.switch_to_input(pull=digitalio.Pull.UP)
sw2 = digitalio.DigitalInOut(board.IO2);  sw2.switch_to_input(pull=digitalio.Pull.UP)
sw3 = digitalio.DigitalInOut(board.IO43); sw3.switch_to_input(pull=digitalio.Pull.UP)

# Font chip CS held high so it doesn't fight the LCD on the shared SPI bus.
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False  # blank until first flag is drawn

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
# Display scene: full-screen flag bitmap + name overlay at the bottom
# ------------------------------------------------------------------
W, H = 128, 160
NAME_BAR_H = 18                  # reserved strip at the bottom for the label
FLAG_H = H - NAME_BAR_H          # flag fills everything above the name bar

scene = displayio.Group()

flag_bitmap = displayio.Bitmap(W, FLAG_H, MAX_COLORS)
flag_palette = displayio.Palette(MAX_COLORS)
scene.append(displayio.TileGrid(flag_bitmap, pixel_shader=flag_palette,
                                x=0, y=0))

# Dark name bar across the bottom of the screen
bar_bitmap = displayio.Bitmap(W, NAME_BAR_H, 1)
bar_palette = displayio.Palette(1); bar_palette[0] = 0x101018
scene.append(displayio.TileGrid(bar_bitmap, pixel_shader=bar_palette,
                                x=0, y=FLAG_H))

name_lbl = label.Label(terminalio.FONT, text="", scale=2, color=0xFFFFFF,
                       background_color=0x101018)
name_lbl.anchor_point = (0.5, 0.5)
name_lbl.anchored_position = (W // 2, FLAG_H + NAME_BAR_H // 2)
scene.append(name_lbl)

# Small index hint (e.g. "3/10") in the corner of the name bar
idx_lbl = label.Label(terminalio.FONT, text="", color=0x808080,
                      background_color=0x101018)
idx_lbl.anchor_point = (1.0, 0.5)
idx_lbl.anchored_position = (W - 3, FLAG_H + NAME_BAR_H // 2)
scene.append(idx_lbl)

# Pause indicator on the left of the name bar
state_lbl = label.Label(terminalio.FONT, text="", color=0x60FF60,
                        background_color=0x101018)
state_lbl.anchor_point = (0.0, 0.5)
state_lbl.anchored_position = (3, FLAG_H + NAME_BAR_H // 2)
scene.append(state_lbl)

display.root_group = scene


# ------------------------------------------------------------------
# Stripe layout: compute integer stripe heights that sum to FLAG_H
# ------------------------------------------------------------------
def stripe_heights(stripes):
    total_w = sum(w for _, w in stripes)
    heights = []
    acc = 0
    for _, w in stripes:
        h = (FLAG_H * (acc + w)) // total_w - (FLAG_H * acc) // total_w
        heights.append(h)
        acc += w
    return heights


# ------------------------------------------------------------------
# Draw a flag into the bitmap
# ------------------------------------------------------------------
def draw_flag(flag_idx):
    name, stripes = FLAGS[flag_idx]
    heights = stripe_heights(stripes)
    # Load this flag's colors into the palette (extras stay as-is, unused)
    for i, (rgb, _w) in enumerate(stripes):
        flag_palette[i] = C(rgb)
    y = 0
    for i, h in enumerate(heights):
        if h <= 0:
            continue
        bitmaptools.fill_region(flag_bitmap, 0, y, W, y + h, i)
        y += h


# ------------------------------------------------------------------
# LED rendering: scroll the current flag's stripe colors across 5 px
# ------------------------------------------------------------------
LED_BRIGHTNESS = 0.5


def scale_rgb(rgb, b):
    return (int(rgb[0] * b), int(rgb[1] * b), int(rgb[2] * b))


def render_leds(flag_idx, t):
    name, stripes = FLAGS[flag_idx]
    cols = [rgb_tuple(C(rgb)) for rgb, _w in stripes]
    n = len(cols)
    # Continuous head position across the (n) color ring, mapped onto NUM
    # pixels with a gentle scroll speed.
    head = (t * 0.6) % n
    for i in range(NUM):
        pos = head + i
        lo = int(pos) % n
        hi = (lo + 1) % n
        frac = pos - int(pos)
        a, b = cols[lo], cols[hi]
        blend = (int(a[0] + (b[0] - a[0]) * frac),
                 int(a[1] + (b[1] - a[1]) * frac),
                 int(a[2] + (b[2] - a[2]) * frac))
        pixels[i] = scale_rgb(blend, LED_BRIGHTNESS)
    pixels.show()


# ------------------------------------------------------------------
# State
# ------------------------------------------------------------------
flag_idx = 0
paused = False
hold_until = time.monotonic() + HOLD_SEC

sw1_prev = True
sw2_prev = True
sw3_prev = True


def update_overlay():
    name_lbl.text = FLAGS[flag_idx][0]
    idx_lbl.text = "%d/%d" % (flag_idx + 1, len(FLAGS))
    state_lbl.text = "II" if paused else ">"


# First paint happens immediately so the screen isn't dark on boot.
draw_flag(flag_idx)
update_overlay()
display.refresh()
bl.value = True

print("Pride Flags -- showing %s (%d/%d)" %
      (FLAGS[flag_idx][0], flag_idx + 1, len(FLAGS)))


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
DEBOUNCE = 0.18
last_sw = 0.0

while True:
    now = time.monotonic()

    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    p1 = (not v1) and sw1_prev
    p2 = (not v2) and sw2_prev
    p3 = (not v3) and sw3_prev
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

    if (p1 or p2) and (now - last_sw) > DEBOUNCE:
        flag_idx = (flag_idx + (1 if p2 else -1)) % len(FLAGS)
        draw_flag(flag_idx)
        update_overlay()
        display.refresh()
        hold_until = now + HOLD_SEC
        last_sw = now
        print("flag:", FLAGS[flag_idx][0])

    if p3 and (now - last_sw) > DEBOUNCE:
        paused = not paused
        if paused:
            hold_until = float("inf")
        else:
            hold_until = now + HOLD_SEC
        update_overlay()
        display.refresh()
        last_sw = now
        print("paused" if paused else "resumed")

    # Auto-advance
    if not paused and now >= hold_until:
        flag_idx = (flag_idx + 1) % len(FLAGS)
        draw_flag(flag_idx)
        update_overlay()
        display.refresh()
        hold_until = now + HOLD_SEC
        print("auto ->", FLAGS[flag_idx][0])

    # Animate NeoPixels every frame (cheap; show() is the slow part)
    render_leds(flag_idx, now)

    time.sleep(0.03)
