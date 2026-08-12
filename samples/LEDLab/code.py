"""
LEDLab -- 5-pixel demo
====================
A demo focused on showing what the 5-pixel WS2812 strip can do.
Cycle through patterns and palettes with the tactile buttons; the
display shows what's playing and mirrors the strip in a live preview.

Controls
--------
  SW1 (IO1)   -- next PATTERN   (16 options)
  SW2 (IO2)   -- next PALETTE   (10 options)
  SW3 (IO43)  -- next SPEED     (SLOW / NORM / FAST / TURBO)
"""

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
import adafruit_st7735r
from adafruit_display_text import label


# ------------------------------------------------------------------
# Hardware
# ------------------------------------------------------------------
NUM = 5

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
bl.value = False  # blank until scene is drawn

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
    h = h - int(h)
    if h < 0: h += 1.0
    if s == 0.0:
        c = int(v * 255)
        return (c, c, c)
    h6 = h * 6.0
    i = int(h6) % 6
    f = h6 - int(h6)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    if i == 0: return (int(v*255), int(t*255), int(p*255))
    if i == 1: return (int(q*255), int(v*255), int(p*255))
    if i == 2: return (int(p*255), int(v*255), int(t*255))
    if i == 3: return (int(p*255), int(q*255), int(v*255))
    if i == 4: return (int(t*255), int(p*255), int(v*255))
    return         (int(v*255), int(p*255), int(q*255))


def scale(rgb, b):
    if b <= 0.0: return (0, 0, 0)
    if b >= 1.0: return rgb
    return (int(rgb[0] * b), int(rgb[1] * b), int(rgb[2] * b))


def rgb_hex(rgb):
    return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


# ------------------------------------------------------------------
# Palettes
# ------------------------------------------------------------------
# Each palette is either the sentinel "rainbow" (full HSV wheel) or a
# list of RGB stops that are linearly interpolated end-to-end.
PALETTES = [
    ("RAINBOW", "rainbow"),
    ("FIRE",    [(2,0,0),(120,10,0),(255,80,0),(255,200,60),(255,255,220)]),
    ("OCEAN",   [(0,4,20),(0,30,80),(0,120,160),(120,220,255),(255,255,255)]),
    ("FOREST",  [(4,10,0),(20,60,0),(80,180,20),(200,255,80),(255,255,255)]),
    ("SUNSET",  [(20,0,60),(120,0,120),(255,60,80),(255,180,40),(255,255,200)]),
    ("NEON",    [(255,0,120),(180,0,255),(0,120,255),(0,255,200),(255,255,0)]),
    ("CANDY",   [(255,120,200),(200,180,255),(120,220,255),(200,255,200),(255,220,220)]),
    ("MONO",    [(20,20,20),(120,120,120),(255,255,255)]),
    ("PARTY",   [(255,0,0),(255,255,0),(0,255,0),(0,255,255),(0,0,255),(255,0,255)]),
    ("CBM",     [(4,20,4),(0,80,20),(60,200,120),(255,220,80),(255,255,180)]),
]


def palette_at(pal_idx, pos):
    """Return (r,g,b) at position `pos` (any float; wraps mod 1)."""
    data = PALETTES[pal_idx][1]
    if data == "rainbow":
        return hsv_to_rgb(pos, 1.0, 1.0)
    n = len(data)
    if n == 1:
        return data[0]
    pos = pos - int(pos)
    if pos < 0: pos += 1.0
    x = pos * (n - 1)
    i = int(x)
    if i >= n - 1: i = n - 2
    f = x - i
    a = data[i]; b = data[i + 1]
    return (int(a[0] + (b[0] - a[0]) * f),
            int(a[1] + (b[1] - a[1]) * f),
            int(a[2] + (b[2] - a[2]) * f))


# ------------------------------------------------------------------
# Pattern state (persisted across frames)
# ------------------------------------------------------------------
heat = [0.0] * NUM                      # FIRE
confetti_buf = [(0, 0, 0)] * NUM        # CONFETTI
twinkle_phase = [random.random() for _ in range(NUM)]
twinkle_rate  = [random.uniform(0.5, 1.5) for _ in range(NUM)]


# ------------------------------------------------------------------
# Patterns -- each returns a list of NUM (r,g,b) tuples
# ------------------------------------------------------------------
def p_solid(pal, t, spd):
    return [palette_at(pal, (t * 0.10 * spd) % 1.0)] * NUM


def p_rainbow(pal, t, spd):
    return [palette_at(pal, (i / NUM) + t * 0.15 * spd) for i in range(NUM)]


def p_breathe(pal, t, spd):
    b = 0.10 + 0.90 * (0.5 + 0.5 * math.sin(t * 2.0 * spd))
    return [scale(palette_at(pal, (i / NUM) + t * 0.05 * spd), b) for i in range(NUM)]


def p_wave(pal, t, spd):
    out = [None] * NUM
    for i in range(NUM):
        b = 0.10 + 0.90 * (0.5 + 0.5 * math.sin(t * 3.0 * spd - i * 0.8))
        out[i] = scale(palette_at(pal, (i / NUM) + t * 0.10 * spd), b)
    return out


def p_comet(pal, t, spd):
    head = (t * 3.0 * spd) % NUM
    c = palette_at(pal, (t * 0.15 * spd) % 1.0)
    out = [(0, 0, 0)] * NUM
    for i in range(NUM):
        d = min(abs(i - head), abs(i - head - NUM), abs(i - head + NUM))
        b = max(0.0, 1.0 - d * 0.55)
        out[i] = scale(c, b * b)
    return out


def p_cylon(pal, t, spd):
    period = 2.0 / spd
    tp = (t % period) / period  # 0..1
    pos = (tp * 2.0 if tp < 0.5 else (1.0 - tp) * 2.0) * (NUM - 1)
    c = palette_at(pal, (t * 0.10 * spd) % 1.0)
    out = [(0, 0, 0)] * NUM
    for i in range(NUM):
        b = max(0.0, 1.0 - abs(i - pos) * 0.9)
        out[i] = scale(c, b * b)
    return out


def p_chase(pal, t, spd):
    step = int(t * 4.0 * spd) % 3
    c = palette_at(pal, (t * 0.10 * spd) % 1.0)
    return [c if (i + step) % 3 == 0 else (0, 0, 0) for i in range(NUM)]


def p_pulse(pal, t, spd):
    """Heartbeat: two beats then rest."""
    period = 1.2 / spd
    tp = (t % period) / period
    if   tp < 0.08: b = tp / 0.08
    elif tp < 0.20: b = 1.0 - (tp - 0.08) / 0.12 * 0.7
    elif tp < 0.28: b = 0.3 + (tp - 0.20) / 0.08 * 0.7
    elif tp < 0.50: b = 1.0 - (tp - 0.28) / 0.22
    else:           b = 0.0
    c = palette_at(pal, (t * 0.05 * spd) % 1.0)
    return [scale(c, b)] * NUM


def p_strobe(pal, t, spd):
    # ~2.5 Hz at NORM up to 10 Hz at TURBO -- fast enough to feel like a
    # strobe, gentle enough not to bother photosensitive viewers.
    on = int(t * 5.0 * spd) % 2 == 0
    c = palette_at(pal, (t * 0.10 * spd) % 1.0) if on else (0, 0, 0)
    return [c] * NUM


def p_vu(pal, t, spd):
    """Bar grows from centre pixel outward."""
    level = 0.5 + 0.5 * math.sin(t * 3.0 * spd)  # 0..1
    lit = level * 3.0                             # 0..3 tiers
    centre = NUM // 2
    out = [(0, 0, 0)] * NUM
    for off in range(3):
        if off > lit: break
        b = min(1.0, lit - off)
        c = palette_at(pal, off / 2.0)
        for idx in (centre - off, centre + off):
            if 0 <= idx < NUM:
                out[idx] = scale(c, b)
    return out


def p_fire(pal, t, spd):
    """Simple 1D flame sim; palette maps heat 0..1 to color."""
    for i in range(NUM):
        heat[i] = max(0.0, heat[i] - random.uniform(0.02, 0.09))
    for i in range(NUM - 1, 0, -1):
        below1 = heat[i - 1]
        below2 = heat[i - 2] if i >= 2 else heat[0]
        heat[i] = (below1 * 2 + below2) / 3.0
    if random.random() < 0.55 * spd:
        heat[0] = min(1.0, heat[0] + random.uniform(0.5, 1.0))
    return [palette_at(pal, heat[i]) for i in range(NUM)]


def p_confetti(pal, t, spd):
    """Random pixel gets a fresh palette color; all decay."""
    decay = max(0.55, 0.90 - 0.05 * spd)
    for i in range(NUM):
        r, g, b = confetti_buf[i]
        confetti_buf[i] = (int(r * decay), int(g * decay), int(b * decay))
    if random.random() < 0.35 * spd:
        confetti_buf[random.randrange(NUM)] = palette_at(pal, random.random())
    return list(confetti_buf)


def p_twinkle(pal, t, spd):
    out = [None] * NUM
    for i in range(NUM):
        twinkle_phase[i] += 0.02 * spd * twinkle_rate[i]
        b = 0.5 + 0.5 * math.sin(twinkle_phase[i] * math.pi * 2)
        b = b * b  # sharpen
        c = palette_at(pal, (i / NUM + t * 0.05 * spd) % 1.0)
        out[i] = scale(c, b)
        if random.random() < 0.005:
            twinkle_rate[i] = random.uniform(0.3, 1.7)
    return out


def p_plasma(pal, t, spd):
    """Sum of a few sines -> smooth shifting color."""
    out = [None] * NUM
    ts = t * spd
    for i in range(NUM):
        v = (math.sin(i * 0.9 + ts * 1.7)
             + math.sin(i * 1.7 - ts * 1.1)
             + math.sin((i + ts * 0.9) * 0.5)) / 3.0
        out[i] = palette_at(pal, (v + 1.0) / 2.0)
    return out


def p_wipe(pal, t, spd):
    """Fill one pixel at a time; when full, clear and step to next color."""
    step_time = 0.30 / spd
    steps = NUM + 2  # brief hold with strip full before reset
    ts = t / step_time
    color_idx = int(ts // steps)
    step = int(ts % steps)
    c = palette_at(pal, (color_idx * 0.17) % 1.0)
    out = [(0, 0, 0)] * NUM
    for i in range(min(step, NUM)):
        out[i] = c
    return out


def p_gradient(pal, t, spd):
    """Slow static-looking gradient that gently drifts."""
    out = [None] * NUM
    for i in range(NUM):
        pos = (i / (NUM - 1)) * 0.9 + t * 0.03 * spd
        out[i] = palette_at(pal, pos)
    return out


PATTERNS = (
    ("SOLID",    p_solid),
    ("RAINBOW",  p_rainbow),
    ("BREATHE",  p_breathe),
    ("WAVE",     p_wave),
    ("COMET",    p_comet),
    ("CYLON",    p_cylon),
    ("CHASE",    p_chase),
    ("PULSE",    p_pulse),
    ("STROBE",   p_strobe),
    ("VU",       p_vu),
    ("FIRE",     p_fire),
    ("CONFETTI", p_confetti),
    ("TWINKLE",  p_twinkle),
    ("PLASMA",   p_plasma),
    ("WIPE",     p_wipe),
    ("GRADIENT", p_gradient),
)

SPEEDS = (("SLOW", 0.5), ("NORM", 1.0), ("FAST", 2.0), ("TURBO", 4.0))


# ------------------------------------------------------------------
# Display scene
# ------------------------------------------------------------------
scene = displayio.Group()

# Dark background
bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1); bg_pal[0] = 0x000010
scene.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

# Title
title = label.Label(terminalio.FONT, text="LED LAB", scale=2, color=0x00FFFF)
title.anchor_point = (0.5, 0.5)
title.anchored_position = (64, 12)
scene.append(title)

# Divider under the title
div_bm = displayio.Bitmap(120, 1, 1)
div_pal = displayio.Palette(1); div_pal[0] = 0x004070
scene.append(displayio.TileGrid(div_bm, pixel_shader=div_pal, x=4, y=24))

# Big pattern name
pat_lbl = label.Label(terminalio.FONT, text="", scale=2, color=0xFFFFFF)
pat_lbl.anchor_point = (0.5, 0.5)
pat_lbl.anchored_position = (64, 44)
scene.append(pat_lbl)

# Position indicator (e.g. "5 / 16")
pat_idx_lbl = label.Label(terminalio.FONT, text="", color=0x808080)
pat_idx_lbl.anchor_point = (0.5, 0.5)
pat_idx_lbl.anchored_position = (64, 60)
scene.append(pat_idx_lbl)

# Palette + speed
pal_lbl = label.Label(terminalio.FONT, text="", color=0xFFA030)
pal_lbl.anchor_point = (0.5, 0.5)
pal_lbl.anchored_position = (64, 78)
scene.append(pal_lbl)

spd_lbl = label.Label(terminalio.FONT, text="", color=0x60FF60)
spd_lbl.anchor_point = (0.5, 0.5)
spd_lbl.anchored_position = (64, 92)
scene.append(spd_lbl)

# Live LED preview: 5 squares mirroring the strip
PREV_W    = 20
PREV_H    = 20
PREV_GAP  = 3
PREV_Y    = 108
PREV_X0   = (128 - (NUM * PREV_W + (NUM - 1) * PREV_GAP)) // 2
preview_palettes = []
for i in range(NUM):
    bm = displayio.Bitmap(PREV_W, PREV_H, 1)
    p  = displayio.Palette(1); p[0] = 0x000000
    scene.append(displayio.TileGrid(
        bm, pixel_shader=p,
        x=PREV_X0 + i * (PREV_W + PREV_GAP), y=PREV_Y))
    preview_palettes.append(p)

# Button hints
hint = label.Label(terminalio.FONT,
                   text="S1:PAT  S2:PAL  S3:SPD",
                   color=0x707070)
hint.anchor_point = (0.5, 0.5)
hint.anchored_position = (64, 148)
scene.append(hint)

display.root_group = scene


# ------------------------------------------------------------------
# State
# ------------------------------------------------------------------
pattern_idx = 4   # COMET -- flashy default
palette_idx = 1   # FIRE
speed_idx   = 1   # NORM

DEBOUNCE = 0.15
sw1_prev = True; sw1_last = 0.0
sw2_prev = True; sw2_last = 0.0
sw3_prev = True; sw3_last = 0.0


def refresh_text():
    pat_lbl.text     = PATTERNS[pattern_idx][0]
    pat_idx_lbl.text = "%d / %d" % (pattern_idx + 1, len(PATTERNS))
    pal_lbl.text     = "pal: " + PALETTES[palette_idx][0]
    spd_lbl.text     = "spd: " + SPEEDS[speed_idx][0]


refresh_text()
display.refresh()
bl.value = True

print("LED Lab -- pat=%s pal=%s spd=%s" % (
    PATTERNS[pattern_idx][0], PALETTES[palette_idx][0], SPEEDS[speed_idx][0]))


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
last_disp = 0.0
DISP_INTERVAL = 0.08

while True:
    now = time.monotonic()

    v1 = sw1.value; v2 = sw2.value; v3 = sw3.value

    if (not v1) and sw1_prev and (now - sw1_last) > DEBOUNCE:
        pattern_idx = (pattern_idx + 1) % len(PATTERNS)
        sw1_last = now
        refresh_text()
        print("pattern:", PATTERNS[pattern_idx][0])
    sw1_prev = v1

    if (not v2) and sw2_prev and (now - sw2_last) > DEBOUNCE:
        palette_idx = (palette_idx + 1) % len(PALETTES)
        sw2_last = now
        refresh_text()
        print("palette:", PALETTES[palette_idx][0])
    sw2_prev = v2

    if (not v3) and sw3_prev and (now - sw3_last) > DEBOUNCE:
        speed_idx = (speed_idx + 1) % len(SPEEDS)
        sw3_last = now
        refresh_text()
        print("speed:", SPEEDS[speed_idx][0])
    sw3_prev = v3

    # Render the strip
    _, fn = PATTERNS[pattern_idx]
    spd = SPEEDS[speed_idx][1]
    rgb_list = fn(palette_idx, now, spd)
    for i in range(NUM):
        pixels[i] = rgb_list[i]
    pixels.show()

    # Refresh display / preview (~12 Hz)
    if now - last_disp > DISP_INTERVAL:
        for i in range(NUM):
            preview_palettes[i][0] = rgb_hex(rgb_list[i])
        display.refresh()
        last_disp = now

    time.sleep(0.02)
